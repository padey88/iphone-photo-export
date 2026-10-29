#!/usr/bin/env python3
"""Read-only iPhone photo/video exporter with resume, manifest and verification.

Pulls /DCIM (camera roll) from a USB-connected, trusted iPhone to a local folder,
writes a SHA-256 manifest, and verifies every file before you delete anything on
the phone. It NEVER deletes, moves or modifies anything on the device.

This is the command-line front end; app.py is the same engine with a GUI.

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
import posixpath
import sys
import time
from pathlib import Path

try:
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.services.afc import AfcService
    from pymobiledevice3.usbmux import list_devices
except ImportError:
    sys.exit("pymobiledevice3 is not installed. Run: pip install pymobiledevice3")

import exporter
from exporter import MEDIA_EXT, human

VIDEO_EXT = {".mov", ".mp4", ".m4v", ".avi"}


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
            mtime = st.get("st_mtime")
            items.append({
                "path": full,
                "name": name,
                "size": int(st["st_size"]),
                "mtime": int(mtime.timestamp()) if hasattr(mtime, "timestamp") else int(mtime or 0),
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
        videos = sum(1 for i in items if Path(i["name"]).suffix.lower() in VIDEO_EXT)
        print(f"found: {len(items)} files ({len(items) - videos} images, {videos} videos), {human(total)}")
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
        print(f"target: {out_dir}  (re-run resumes; existing complete files are skipped)")

        started = time.time()

        def on_progress(p):
            if p["done"] % 25 and p["done"] != p["total"]:
                return
            rate = p["bytes"] / max(time.time() - started, 1)
            print(f"  {p['done']}/{p['total']}  copied={p['copied']} resumed={p['resumed']} "
                  f"failed={p['failed']}  {human(rate)}/s", flush=True)

        result = await exporter.copy_items(afc, items, out_dir, on_progress=on_progress)
        verification = exporter.verify_items(items, out_dir)
        exporter.write_manifest(result["rows"], out_dir / "manifest.csv")
        exporter.write_report(out_dir / "VERIFY.txt", serial=serial, source=args.root,
                              copy_result=result, verification=verification)

        print()
        print(f"copied {result['copied']}, resumed {result['resumed']}, failed {result['failed']}, "
              f"missing {len(verification['missing'])}, mismatch {len(verification['mismatch'])}")
        print(f"manifest: {out_dir / 'manifest.csv'}")
        print(f"report  : {out_dir / 'VERIFY.txt'}")
        if result["failed"] or not verification["ok"]:
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
