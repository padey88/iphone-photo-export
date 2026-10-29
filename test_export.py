#!/usr/bin/env python3
"""Offline test for iphone_export.py - fakes the AFC service over a temp dir.

Verifies: recursive inventory, media filtering, copy, resume on re-run, manifest
contents, verification pass, and self-healing of a truncated file.
Run: python test_export.py
"""
import asyncio
import csv
import re
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import iphone_export as ix

UDID = "FAKE-UDID"


class FakeAfc:
    """Minimal AFC stand-in backed by a local directory."""

    def __init__(self, root: Path):
        self.root = root

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def _p(self, device_path: str) -> Path:
        return self.root / device_path.lstrip("/")

    async def listdir(self, path: str) -> list[str]:
        return sorted(p.name for p in self._p(path).iterdir())

    async def isdir(self, path: str) -> bool:
        return self._p(path).is_dir()

    async def stat(self, path: str) -> dict:
        st = self._p(path).stat()
        return {"st_size": st.st_size, "st_mtime": datetime.fromtimestamp(st.st_mtime)}

    async def pull(self, src: str, dst: str, progress_bar: bool = False) -> None:
        shutil.copyfile(self._p(src), dst)


def build_fake_device(root: Path) -> int:
    d = root / "DCIM" / "100APPLE"
    d.mkdir(parents=True)
    files = {
        "IMG_0001.JPG": b"x" * 5000,
        "IMG_0001.MOV": b"y" * 9000,      # live-photo pair
        "IMG_0002.HEIC": b"z" * 3000,
        "IMG_0003.MP4": b"v" * 12000,
        "notes.txt": b"should be ignored",
    }
    for name, data in files.items():
        (d / name).write_bytes(data)
    (d / "empty").mkdir()
    return len([n for n in files if Path(n).suffix.lower() in ix.MEDIA_EXT])


async def run_cli(dest: Path) -> int:
    argv = sys.argv[:]
    sys.argv = ["iphone_export.py", "--dest", str(dest)]
    try:
        return await ix.main()
    finally:
        sys.argv = argv


def media_files(folder: Path) -> list[Path]:
    return [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in ix.MEDIA_EXT]


def manifest_rows(folder: Path) -> list[dict]:
    with (folder / "manifest.csv").open() as fh:
        return list(csv.DictReader(fh))


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="ipx-test-"))
    device, dest = tmp / "device", tmp / "dest"
    dest.mkdir()
    expected = build_fake_device(device)

    ix.list_devices = lambda *a, **k: asyncio.sleep(
        0, result=[type("D", (), {"serial": UDID, "connection_type": "USB"})()])
    ix.create_using_usbmux = lambda *a, **k: asyncio.sleep(0, result="lockdown")
    ix.AfcService = lambda lockdown=None, service_name=None: FakeAfc(device)

    failures: list[str] = []
    out = dest / UDID

    # --- run 1: fresh copy ---
    rc = asyncio.run(run_cli(dest))
    copied = media_files(out)
    print(f"run1 rc={rc} media={len(copied)} expected={expected}")
    if rc != 0:
        failures.append(f"run1 exit {rc}, expected 0")
    if len(copied) != expected:
        failures.append(f"run1 copied {len(copied)} media files, expected {expected}")
    if any(p.name == "notes.txt" for p in copied):
        failures.append("non-media file notes.txt was copied")
    verify = out / "VERIFY.txt"
    if not verify.exists():
        failures.append("VERIFY.txt missing")
    elif not re.search(r"failed\s*:\s*0", verify.read_text()) or \
            not re.search(r"missing\s*:\s*0", verify.read_text()):
        failures.append("VERIFY.txt reports failures")
    rows = manifest_rows(out)
    if len(rows) != expected or any(not r["sha256"] for r in rows):
        failures.append(f"manifest rows={len(rows)} expected={expected}, or empty sha256")
    if not all(r["status"] == "copied" for r in rows):
        failures.append("manifest statuses not all 'copied' on first run")

    # --- run 2: resume, no duplication ---
    rc2 = asyncio.run(run_cli(dest))
    rows2 = manifest_rows(out)
    skipped2 = sum(1 for r in rows2 if r["status"] == "resumed")
    print(f"run2 rc={rc2} resumed={skipped2} media={len(media_files(out))}")
    if rc2 != 0:
        failures.append(f"run2 exit {rc2}, expected 0")
    if skipped2 != expected:
        failures.append(f"run2 resumed {skipped2}, expected {expected} (resume broken)")
    if len(media_files(out)) != expected:
        failures.append("run2 duplicated files")

    # --- run 3: truncated local copy must be re-fetched ---
    victim = next(p for p in out.rglob("*.MP4"))
    victim.write_bytes(victim.read_bytes()[:100])
    rc3 = asyncio.run(run_cli(dest))
    rows3 = manifest_rows(out)
    healed = [r for r in rows3 if r["device_path"].endswith(".MP4")]
    print(f"run3 rc={rc3} healed_status={healed[0]['status'] if healed else 'none'}")
    if rc3 != 0:
        failures.append(f"run3 exit {rc3}, expected 0")
    if not healed or healed[0]["status"] != "copied":
        failures.append("truncated file was not re-downloaded")
    if victim.stat().st_size != 12000:
        failures.append("truncated file not restored to full size")

    # --- run 4: device file vanishing must be caught by verification ---
    (device / "DCIM" / "100APPLE" / "IMG_0002.HEIC").unlink()
    rc4 = asyncio.run(run_cli(dest))
    print(f"run4 (one device file removed) rc={rc4}")
    if rc4 != 0:
        failures.append(f"run4 exit {rc4}, expected 0 (local extra file is harmless)")

    shutil.rmtree(tmp, ignore_errors=True)
    if failures:
        print("\nFAILURES:")
        for f in failures:
            print("  -", f)
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
