#!/usr/bin/env python3
"""Read-only iPhone photo/video exporter with resume, manifest and verification.

Pulls /DCIM (camera roll) from a USB-connected, trusted iPhone to a local folder,
writes a SHA-256 manifest, and verifies every file before you delete anything on
the phone. It NEVER deletes, moves or modifies anything on the device.

Requirements (Windows / macOS / Linux):
    pip install pymobiledevice3
    Windows also needs Apple Mobile Device drivers: install iTunes from apple.com
    (not the Microsoft Store build) or the "Apple Devices" app.

Usage:
    python iphone_export.py --dest D:\\iphone-backup                 # single phone
    python iphone_export.py --dest D:\\iphone-backup --udid <UDID>   # pick one of two
    python iphone_export.py --dest D:\\iphone-backup --dry-run       # inventory only

Exit codes: 0 ok, 1 no device / error, 2 verification mismatch (do not delete).
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import os
import posixpath
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.services.afc import AfcService
    from pymobiledevice3.usbmux import list_devices
except ImportError:
    sys.exit("pymobiledevice3 is not installed. Run: pip install pymobiledevice3")

MEDIA_EXT = {
    ".jpg", ".jpeg", ".heic", ".heif", ".png", ".gif", ".tif", ".tiff",
    ".dng", ".mov", ".mp4", ".m4v", ".avi", ".aae",
}
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


async def pick_device(udid: str | None):
    try:
        all_devices = await list_devices()
    except Exception as exc:
        sys.exit(
            "Cannot talk to usbmuxd (Apple's device service).\n"
            f"  detail: {exc}\n"
            "Windows fix: install iTunes from apple.com (or the 'Apple Devices' app) so the\n"
            "Apple Mobile Device Support service exists, plug the iPhone in directly (no hub),\n"
            "unlock it and tap 'Trust'. Then run this script again.\n"
            "macOS/Linux fix: ensure usbmuxd is running (Linux: sudo systemctl start usbmuxd)."
        )
    devices = [d for d in all_devices if getattr(d, "connection_type", "USB") == "USB"]
    if not devices:
        sys.exit("No USB device found. Unlock the iPhone, tap Trust, keep the screen on.")
    if udid:
        for d in devices:
            if getattr(d, "serial", "") == udid:
                return d.serial
        sys.exit(f"UDID {udid} not connected. Connected: {[d.serial for d in devices]}")
    if len(devices) > 1:
        print("More than one device is connected. Re-run with --udid one of:")
        for d in devices:
            print("  ", d.serial)
        sys.exit(1)
    return devices[0].serial


async def walk(afc: AfcService, root: str) -> list[dict]:
    """Recursive inventory of media files under root."""
    items: list[dict] = []

    async def rec(path: str) -> None:
        try:
            entries = await afc.listdir(path)
        except Exception as exc:  # unreadable dir (rare) - skip, do not abort
            print(f"  ! cannot list {path}: {exc}")
            return
        for name in entries:
            full = posixpath.join(path, name)
            try:
                if await afc.isdir(full):
                    await rec(full)
                    continue
                st = await afc.stat(full)
            except Exception as exc:
                print(f"  ! cannot stat {full}: {exc}")
                continue
            if Path(name).suffix.lower() not in MEDIA_EXT:
                continue
            items.append({
                "path": full,
                "name": name,
                "size": int(st["st_size"]),
                "mtime": int(st["st_mtime"].timestamp()) if st.get("st_mtime") else 0,
            })

    await rec(root)
    return items


async def main() -> int:
    ap = argparse.ArgumentParser(description="Export iPhone camera roll to a local folder (read-only).")
    ap.add_argument("--dest", required=True, help="local destination folder")
    ap.add_argument("--udid", help="device UDID (needed when two phones are plugged in)")
    ap.add_argument("--root", default="/DCIM", help="device path to export (default /DCIM)")
    ap.add_argument("--dry-run", action="store_true", help="inventory only, copy nothing")
    args = ap.parse_args()

    dest_root = Path(args.dest).expanduser().resolve()
    serial = await pick_device(args.udid)
    lockdown = await create_using_usbmux(serial=serial)

    async with AfcService(lockdown=lockdown) as afc:
        print(f"device: {serial}")
        print(f"reading inventory from {args.root} ...")
        items = await walk(afc, args.root)
        if not items:
            print("Nothing found under", args.root)
            return 1

        total = sum(i["size"] for i in items)
        photos = sum(1 for i in items if Path(i["name"]).suffix.lower() not in {".mov", ".mp4", ".m4v", ".avi"})
        videos = len(items) - photos
        print(f"found: {len(items)} files ({photos} images, {videos} videos), {human(total)}")
        print(f"dest : {dest_root}")

        free = 0
        try:
            import shutil
            free = shutil.disk_usage(dest_root if dest_root.exists() else dest_root.parent).free
        except Exception:
            pass
        if free and free < total * 1.1:
            print(f"WARNING: destination has {human(free)} free, need ~{human(total * 1.1)}")

        if args.dry_run:
            by_dir: dict[str, int] = {}
            for i in items:
                by_dir[posixpath.dirname(i["path"])] = by_dir.get(posixpath.dirname(i["path"]), 0) + 1
            for d, c in sorted(by_dir.items()):
                print(f"  {d}: {c} files")
            return 0

        # Stable per-device folder so re-runs resume instead of duplicating the library.
        out_dir = dest_root / serial
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = out_dir / "manifest.csv"
        log_path = out_dir / "export.log"
        print(f"target: {out_dir}  (re-run resumes; existing complete files are skipped)")

        done = copied = skipped = failed = 0
        copied_bytes = 0
        started = time.time()
        rows: list[list] = []

        with manifest_path.open("w", newline="", encoding="utf-8") as mf, \
                log_path.open("a", encoding="utf-8") as log:
            w = csv.writer(mf)
            w.writerow(["device_path", "local_path", "size", "mtime_epoch", "sha256", "status"])

            for idx, item in enumerate(items, 1):
                rel = item["path"].lstrip("/").replace("/", os.sep)
                local = out_dir / rel
                local.parent.mkdir(parents=True, exist_ok=True)

                if local.exists() and local.stat().st_size == item["size"]:
                    rows.append([item["path"], str(local), item["size"], item["mtime"],
                                 sha256_file(local), "resumed"])
                    skipped += 1
                    done += 1
                    continue

                tmp = local.with_suffix(local.suffix + ".part")
                try:
                    await afc.pull(item["path"], str(tmp), progress_bar=False)
                    if tmp.stat().st_size != item["size"]:
                        raise IOError(f"size {tmp.stat().st_size} != {item['size']}")
                    tmp.replace(local)
                    os.utime(local, (time.time(), item["mtime"] or time.time()))
                    rows.append([item["path"], str(local), item["size"], item["mtime"],
                                 sha256_file(local), "copied"])
                    copied += 1
                    copied_bytes += item["size"]
                except Exception as exc:
                    tmp.unlink(missing_ok=True)
                    rows.append([item["path"], str(local), item["size"], item["mtime"], "", f"FAILED: {exc}"])
                    failed += 1
                    log.write(f"FAILED {item['path']}: {exc}\n")
                done += 1

                if done % 25 == 0 or done == len(items):
                    rate = copied_bytes / max(time.time() - started, 1)
                    print(f"  {done}/{len(items)}  copied={copied} skipped={skipped} failed={failed}  "
                          f"{human(rate)}/s", flush=True)
                    mf.flush()

            for row in rows:
                w.writerow(row)

        # ---- verification pass ----
        missing, mismatch = [], []
        for item in items:
            rel = item["path"].lstrip("/").replace("/", os.sep)
            local = out_dir / rel
            if not local.exists():
                missing.append(item["path"])
            elif local.stat().st_size != item["size"]:
                mismatch.append(item["path"])

        report = out_dir / "VERIFY.txt"
        with report.open("w", encoding="utf-8") as fh:
            fh.write(f"device      : {serial}\n")
            fh.write(f"source      : {args.root}\n")
            fh.write(f"finished    : {datetime.now().isoformat(timespec='seconds')}\n")
            fh.write(f"device files: {len(items)}\n")
            fh.write(f"device bytes: {total} ({human(total)})\n")
            fh.write(f"copied      : {copied}\n")
            fh.write(f"resumed     : {skipped}\n")
            fh.write(f"failed      : {failed}\n")
            fh.write(f"missing     : {len(missing)}\n")
            fh.write(f"size mismatch: {len(mismatch)}\n")
            if missing:
                fh.write("\nMISSING:\n" + "\n".join(missing[:200]) + "\n")
            if mismatch:
                fh.write("\nMISMATCH:\n" + "\n".join(mismatch[:200]) + "\n")
            fh.write("\nDo NOT delete anything from the phone unless failed/missing/mismatch are all 0,\n")
            fh.write("you have opened several random videos from this folder, and the folder is copied\n")
            fh.write("to a second drive.\n")

        print()
        print(f"copied {copied}, resumed {skipped}, failed {failed}, missing {len(missing)}, mismatch {len(mismatch)}")
        print(f"manifest: {manifest_path}")
        print(f"report  : {report}")
        if failed or missing or mismatch:
            print("\nVERIFICATION FAILED - do not delete anything from the phone.")
            return 2
        print("\nAll files verified. Now: (1) play 5 random videos from this folder,")
        print("(2) copy the folder to a second drive, (3) only then delete on the phone.")
        return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\ninterrupted - re-run with the same --dest to resume")
        sys.exit(130)
