from __future__ import annotations

import csv
import hashlib
import os
import posixpath
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import filters

MEDIA_EXT = {
    ".jpg", ".jpeg", ".heic", ".heif", ".png", ".gif", ".tif", ".tiff",
    ".dng", ".mov", ".mp4", ".m4v", ".avi", ".aae",
}
VIDEO_EXT = {".mov", ".mp4", ".m4v", ".avi"}
CHUNK = 4 * 1024 * 1024


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def local_path_for(out_dir: Path, device_path: str, layout: str = "source",
                   item: dict | None = None) -> Path:
    # Inventory paths originate from a trusted AFC session, but still constrain
    # them to the chosen output directory before constructing a local path.
    parts = [part for part in device_path.replace("\\", "/").split("/")
             if part not in ("", ".")]
    if any(part == ".." or ":" in part for part in parts):
        raise ValueError(f"unsafe device path: {device_path!r}")
    if layout == "category":
        kind = filters.classify([{"path": device_path, "name": parts[-1],
                                  "ext": Path(parts[-1]).suffix.lower(),
                                  "mtime": int((item or {}).get("mtime", 0)),
                                  "size": int((item or {}).get("size", 0))}], {})[0]["kind"]
        folder = {"photo": "Photos", "live": "Live Photos", "video": "Videos",
                  "recording": "Screen Recordings", "screenshot": "Screenshots",
                  "live_mov": "Live Photo Videos"}.get(kind, "Other")
        parts = [folder, parts[-1]]
    elif layout == "date":
        month = datetime.fromtimestamp(int((item or {}).get("mtime", 0))).strftime("%Y-%m")
        parts = [month, parts[-1]]
    elif layout != "source":
        raise ValueError("layout must be source, category or date")
    local = out_dir.joinpath(*parts)
    if not local.is_relative_to(out_dir):
        raise ValueError(f"device path escapes output folder: {device_path!r}")
    return local


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for n in range(2, 10000):
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"no available destination name for {path.name}")


def device_mtime(item: dict) -> int:
    """Return the most recent known modification time for an item."""
    return max(int(item.get("mtime") or 0), int(item.get("source_mtime") or 0))


def _is_current(local: Path, item: dict) -> bool:
    """A size match alone is not sufficient to skip a changed device file."""
    try:
        return (local.is_file()
                and local.stat().st_size == int(item["size"])
                and int(local.stat().st_mtime) == device_mtime(item))
    except OSError:
        return False


def _current_resumable_row(local: Path, item: dict, existing: dict | None) -> list:
    digest = sha256_file(local)
    if existing and existing.get("sha256") and existing["sha256"] != digest:
        raise IOError("existing file hash differs from the previous manifest; re-export it")
    return [item["path"], str(local), item["size"], device_mtime(item), digest, "resumed"]


async def copy_items(afc, items, out_dir: Path, on_progress=None, on_error=None,
                     layout: str = "source") -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    old_index = manifest_index(out_dir)
    rows: list[list] = []
    copied = resumed = failed = 0
    total_bytes = 0

    for idx, item in enumerate(items, 1):
        item = dict(item)
        item["mtime"] = device_mtime(item)
        existing = old_index.get(item["path"])
        if existing and existing.get("local_path"):
            # Continue an existing export at its recorded location. Changing the
            # UI layout later must not duplicate files already verified elsewhere.
            local = Path(existing["local_path"])
            if not local.is_relative_to(out_dir):
                raise ValueError(f"manifest path escapes export folder: {local}")
        else:
            local = local_path_for(out_dir, item["path"], layout, item)
            if layout != "source":
                local = unique_path(local)
        local.parent.mkdir(parents=True, exist_ok=True)

        if item.get("device_error"):
            rows.append([item["path"], str(local), item["size"], item["mtime"], "",
                         f"FAILED: could not read device metadata: {item['device_error']}"])
            failed += 1
            if on_error:
                on_error(item["path"], item["device_error"])
        else:
            try:
                if _is_current(local, item):
                    rows.append(_current_resumable_row(local, item, existing))
                    resumed += 1
                else:
                    # If a same-sized device edit was made within one second, or
                    # the timestamp changed, compare content before resuming.
                    if local.exists() and local.stat().st_size == item["size"] and existing:
                        expected_hash = item.get("source_sha256") or existing.get("sha256")
                        # A different device mtime requires a fresh pull. The
                        # previous manifest describes old bytes, not the new ones.
                        device_changed = item["mtime"] != int(existing.get("mtime_epoch") or 0)
                        if not device_changed and expected_hash and sha256_file(local) == expected_hash:
                            os.utime(local, (time.time(), item["mtime"] or time.time()))
                            rows.append(_current_resumable_row(local, item, existing))
                            resumed += 1
                        else:
                            tmp = local.with_suffix(local.suffix + ".part")
                            try:
                                await afc.pull(item["path"], str(tmp), progress_bar=False)
                                if tmp.stat().st_size != item["size"]:
                                    raise IOError(f"size {tmp.stat().st_size} != expected {item['size']}")
                                digest = sha256_file(tmp)
                                tmp.replace(local)
                                os.utime(local, (time.time(), item["mtime"] or time.time()))
                                rows.append([item["path"], str(local), item["size"], item["mtime"],
                                             digest, "copied"])
                                copied += 1
                                total_bytes += item["size"]
                            except Exception:
                                tmp.unlink(missing_ok=True)
                                raise
                    else:
                        tmp = local.with_suffix(local.suffix + ".part")
                        try:
                            if tmp.exists():
                                tmp.unlink()
                            await afc.pull(item["path"], str(tmp), progress_bar=False)
                            if tmp.stat().st_size != item["size"]:
                                raise IOError(f"size {tmp.stat().st_size} != expected {item['size']}")
                            digest = sha256_file(tmp)
                            if item.get("source_sha256") and digest != item["source_sha256"]:
                                raise IOError("copied file hash differs from the device snapshot")
                            tmp.replace(local)
                            os.utime(local, (time.time(), item["mtime"] or time.time()))
                            rows.append([item["path"], str(local), item["size"], item["mtime"],
                                         digest, "copied"])
                            copied += 1
                            total_bytes += item["size"]
                        except Exception:
                            tmp.unlink(missing_ok=True)
                            raise
            except Exception as exc:
                rows.append([item["path"], str(local), item["size"], item["mtime"],
                             "", f"FAILED: {exc}"])
                failed += 1
                if on_error:
                    on_error(item["path"], str(exc))

        if on_progress:
            on_progress({
                "done": idx, "total": len(items),
                "copied": copied, "resumed": resumed, "failed": failed,
                "bytes": total_bytes, "current": item["path"],
            })

    return {"rows": rows, "copied": copied, "resumed": resumed,
            "failed": failed, "bytes": total_bytes}


def verify_items(items, out_dir: Path, manifest_rows=None) -> dict:
    """Verify bytes against this export's manifest, not only file existence.

    SHA-256 compares local content to the hash calculated immediately after its
    USB transfer. AFC's read API does not provide a cheap independent server-side
    hash, so this verifies export integrity and subsequent local modification;
    it does not claim to re-hash the live iPhone file.
    """
    if manifest_rows is not None:
        expected_rows = {row[0]: {"sha256": row[4], "status": row[5], "local_path": row[1]}
                         for row in manifest_rows if row[5] in ("copied", "resumed")}
    else:
        expected_rows = manifest_index(out_dir)
    missing, mismatch, hash_mismatch, missing_hash = [], [], [], []
    for item in items:
        path = item["path"]
        row = expected_rows.get(path)
        local = local_path_for(out_dir, path, (item or {}).get("layout", "source"), item)
        if row and row.get("local_path"):
            candidate = Path(row["local_path"])
            if not candidate.is_relative_to(out_dir):
                mismatch.append(path)
                continue
            local = candidate
        try:
            if not local.is_file():
                missing.append(path)
            elif local.stat().st_size != int(item["size"]):
                mismatch.append(path)
            elif not row or not row.get("sha256"):
                missing_hash.append(path)
            elif sha256_file(local) != row["sha256"]:
                hash_mismatch.append(path)
        except OSError:
            missing.append(path)
    return {
        "expected": len(items),
        "expected_bytes": sum(i["size"] for i in items),
        "missing": missing,
        "mismatch": mismatch,
        "hash_mismatch": hash_mismatch,
        "missing_hash": missing_hash,
        "ok": not (missing or mismatch or hash_mismatch or missing_hash),
    }


def write_manifest(rows, path: Path) -> None:
    """Write only this run, atomically.

    A separate cumulative index preserves history across filtered exports. This
    file must never let an older successful row make a current failure look
    verified.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["device_path", "local_path", "size", "mtime_epoch", "sha256",
              "status", "last_error"]
    records = []
    for row in rows:
        status = row[5]
        records.append({
            "device_path": row[0], "local_path": row[1], "size": row[2],
            "mtime_epoch": row[3], "sha256": row[4], "status": status,
            "last_error": status.removeprefix("FAILED: ") if status.startswith("FAILED:") else "",
        })
    with tempfile.NamedTemporaryFile("w", newline="", encoding="utf-8",
                                     dir=path.parent, prefix=path.name + ".",
                                     suffix=".tmp", delete=False) as fh:
        tmp = Path(fh.name)
        try:
            writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(records)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
    tmp.replace(path)


def manifest_index(dest_root: Path) -> dict[str, dict]:
    """Index successful exports by device path from the per-run journal."""
    index: dict[str, dict] = {}
    paths = [dest_root / "manifest.csv"] if (dest_root / "manifest.csv").is_file() else []
    paths += sorted((dest_root / "history").glob("*.csv")) if (dest_root / "history").is_dir() else []
    if not paths:
        # Backward compatibility with v1.0.x output directories.
        paths = sorted(dest_root.glob("*/manifest.csv"), key=lambda p: p.stat().st_mtime)
    manifests = paths
    for manifest in manifests:
        try:
            with manifest.open(newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    if (row.get("device_path") and row.get("size")
                            and row.get("status") in ("copied", "resumed")
                            and row.get("sha256")):
                        index[row["device_path"]] = row
        except (OSError, ValueError, csv.Error):
            continue
    return index


def write_report(path: Path, *, serial: str, source: str, copy_result: dict,
                 verification: dict) -> None:
    with path.open("w", encoding="utf-8") as fh:
        fh.write(f"device       : {serial}\n")
        fh.write(f"source       : {source}\n")
        fh.write(f"finished     : {datetime.now().astimezone().isoformat(timespec='seconds')}\n")
        fh.write(f"device files : {verification['expected']}\n")
        fh.write(f"device bytes : {verification['expected_bytes']} ({human(verification['expected_bytes'])})\n")
        fh.write(f"copied       : {copy_result['copied']}\n")
        fh.write(f"resumed      : {copy_result['resumed']}\n")
        fh.write(f"failed       : {copy_result['failed']}\n")
        for key, label in (("missing", "missing"), ("mismatch", "size mismatch"),
                           ("hash_mismatch", "hash mismatch"), ("missing_hash", "missing hash")):
            fh.write(f"{label:<13}: {len(verification[key])}\n")
        for key, label in (("missing", "MISSING"), ("mismatch", "SIZE MISMATCH"),
                           ("hash_mismatch", "HASH MISMATCH"), ("missing_hash", "MISSING HASH")):
            if verification[key]:
                fh.write(f"\n{label}:\n" + "\n".join(verification[key][:200]) + "\n")
        fh.write("\nSHA-256 compares the exported local bytes to the manifest recorded after\n")
        fh.write("the USB transfer. It does not independently re-hash the iPhone file.\n")
        fh.write("\nDo NOT delete anything from the phone unless failed/missing/mismatch/hash_mismatch\n")
        fh.write("are all 0, you have played several random videos from this folder, and the\n")
        fh.write("folder exists on a second drive.\n")


def already_exported_index(dest_root: Path) -> dict[str, dict]:
    return manifest_index(dest_root)


def walk_inventory(entries: list[dict]) -> list[dict]:
    out = []
    for e in entries:
        name = posixpath.basename(e["path"])
        ext = Path(name).suffix.lower()
        out.append({
            "path": e["path"],
            "name": name,
            "size": int(e["size"]),
            "mtime": int(e["mtime"]),
            "ext": ext,
            "is_video": ext in VIDEO_EXT,
        })
    return out
