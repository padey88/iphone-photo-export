"""Copy + verify core shared by the CLI and the GUI.

Both entry points funnel through these functions so there is exactly one
implementation of "pull the file, hash it, record it, prove it landed".
"""
from __future__ import annotations

import csv
import hashlib
import os
import posixpath
import time
from datetime import datetime
from pathlib import Path

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


def local_path_for(out_dir: Path, device_path: str) -> Path:
    return out_dir / device_path.lstrip("/").replace("/", os.sep)


async def copy_items(afc, items, out_dir: Path, on_progress=None, on_error=None) -> dict:
    """Copy items (dicts with path/size/mtime) into out_dir.

    Resumes: a local file already at the right byte size is kept, not re-fetched.
    A local file at the wrong size is re-fetched (self-healing).
    Returns {"rows": [...], "copied": n, "resumed": n, "failed": n, "bytes": n}.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[list] = []
    copied = resumed = failed = 0
    total_bytes = 0

    for idx, item in enumerate(items, 1):
        local = local_path_for(out_dir, item["path"])
        local.parent.mkdir(parents=True, exist_ok=True)

        if local.exists() and local.stat().st_size == item["size"]:
            rows.append([item["path"], str(local), item["size"], item["mtime"],
                         sha256_file(local), "resumed"])
            resumed += 1
        else:
            tmp = local.with_suffix(local.suffix + ".part")
            try:
                await afc.pull(item["path"], str(tmp), progress_bar=False)
                if tmp.stat().st_size != item["size"]:
                    raise IOError(f"size {tmp.stat().st_size} != expected {item['size']}")
                tmp.replace(local)
                os.utime(local, (time.time(), item["mtime"] or time.time()))
                rows.append([item["path"], str(local), item["size"], item["mtime"],
                             sha256_file(local), "copied"])
                copied += 1
                total_bytes += item["size"]
            except Exception as exc:  # keep going; the verify pass will flag it
                tmp.unlink(missing_ok=True)
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


def verify_items(items, out_dir: Path) -> dict:
    """Check every expected file exists locally at the right size."""
    missing, mismatch = [], []
    for item in items:
        local = local_path_for(out_dir, item["path"])
        if not local.exists():
            missing.append(item["path"])
        elif local.stat().st_size != item["size"]:
            mismatch.append(item["path"])
    return {
        "expected": len(items),
        "expected_bytes": sum(i["size"] for i in items),
        "missing": missing,
        "mismatch": mismatch,
        "ok": not missing and not mismatch,
    }


def write_manifest(rows, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["device_path", "local_path", "size", "mtime_epoch", "sha256", "status"])
        w.writerows(rows)


def write_report(path: Path, *, serial: str, source: str, copy_result: dict,
                 verification: dict) -> None:
    with path.open("w", encoding="utf-8") as fh:
        fh.write(f"device       : {serial}\n")
        fh.write(f"source       : {source}\n")
        fh.write(f"finished     : {datetime.now().isoformat(timespec='seconds')}\n")
        fh.write(f"device files : {verification['expected']}\n")
        fh.write(f"device bytes : {verification['expected_bytes']} ({human(verification['expected_bytes'])})\n")
        fh.write(f"copied       : {copy_result['copied']}\n")
        fh.write(f"resumed      : {copy_result['resumed']}\n")
        fh.write(f"failed       : {copy_result['failed']}\n")
        fh.write(f"missing      : {len(verification['missing'])}\n")
        fh.write(f"size mismatch: {len(verification['mismatch'])}\n")
        for label, items in (("MISSING", verification["missing"]),
                             ("MISMATCH", verification["mismatch"])):
            if items:
                fh.write(f"\n{label}:\n" + "\n".join(items[:200]) + "\n")
        fh.write("\nDo NOT delete anything from the phone unless failed/missing/mismatch are all 0,\n")
        fh.write("you have played several random videos from this folder, and the folder exists\n")
        fh.write("on a second drive.\n")


def already_exported_index(dest_root: Path) -> dict[str, int]:
    """Map device path -> size for files already present in any earlier export."""
    index: dict[str, int] = {}
    if not dest_root.exists():
        return index
    for manifest in dest_root.glob("*/manifest.csv"):
        try:
            with manifest.open(newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    if row.get("device_path") and row.get("size"):
                        index[row["device_path"]] = int(row["size"])
        except Exception:
            continue
    return index


def walk_inventory(entries: list[dict]) -> list[dict]:
    """Normalise + classify raw AFC entries into inventory items."""
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
