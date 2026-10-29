#!/usr/bin/env python3
"""API-level tests for the GUI (app.py) against a fake device - no phone needed.

Run: python tests/test_gui.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

tmp = Path(tempfile.mkdtemp(prefix="ipx-gui-"))
fake = tmp / "device"
dest = tmp / "dest"
dest.mkdir(parents=True)
os.environ["IPHONE_EXPORT_FAKE"] = str(fake)
os.environ["IPHONE_EXPORT_DEST"] = str(dest)
os.environ["IPHONE_EXPORT_CACHE"] = str(tmp / "cache")

from PIL import Image, ImageDraw  # noqa: E402

dcim = fake / "DCIM" / "100APPLE"
dcim.mkdir(parents=True)


def photo(name, when, colour="#2b6cb0"):
    p = dcim / name
    im = Image.new("RGB", (600, 450), colour)
    ImageDraw.Draw(im).text((20, 20), name, fill="white")
    im.save(p)
    ts = time.mktime(time.strptime(when, "%Y-%m-%d"))
    os.utime(p, (ts, ts))


def video(name, when):
    p = dcim / name
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "color=c=navy:s=320x240:d=1", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(p)], check=True)
    ts = time.mktime(time.strptime(when, "%Y-%m-%d"))
    os.utime(p, (ts, ts))


photo("IMG_0001.JPG", "2025-05-01")
photo("IMG_0002.JPG", "2025-11-20")
video("IMG_0002.MOV", "2025-11-20")          # live photo pair
photo("IMG_0003.PNG", "2026-04-02")          # screenshot, 2026
video("IMG_0004.MP4", "2024-02-02")          # old video
photo("IMG_0005.JPG", "2026-08-08")          # recent
(dcim / "notes.txt").write_text("ignored")

import app as gui  # noqa: E402
from exporter import MEDIA_EXT  # noqa: E402  (import after env + fixture)

failures: list[str] = []


def check(cond, msg):
    if not cond:
        failures.append(msg)
    print(("  ok   " if cond else "  FAIL ") + msg)


client = gui.app.test_client()

print("state")
s = client.get("/api/state").get_json()
check(s["fake"] is True, "fake device flag exposed")
check(len(s["presets"]) >= 5, "presets present")

print("connect")
r = client.post("/api/connect", json={}).get_json()
check("device" in r and r["device"]["udid"] == "FAKE-DEVICE", "device connected")
check(len(r["items"]) == 6, f"6 media files inventoried (got {len(r.get('items', []))})")
kinds = {i["name"]: i["kind"] for i in r["items"]}
check(kinds.get("IMG_0002.JPG") == "live", "live photo detected")
check(kinds.get("IMG_0002.MOV") == "live_mov", "live photo motion clip detected")
check(kinds.get("IMG_0003.PNG") == "screenshot", "screenshot detected")
check("notes.txt" not in kinds, "non-media file excluded")

print("filter: older than 2026-01-01")
f = client.post("/api/filter", json={"date_mode": "older", "date": "2026-01-01"}).get_json()
names = {i["name"] for i in f["items"]}
check(names == {"IMG_0001.JPG", "IMG_0002.JPG", "IMG_0002.MOV", "IMG_0004.MP4"},
      f"date filter exact set (got {sorted(names)})")
check(f["summary"]["count"] == 4, "summary count 4")

print("filter: videos only")
f2 = client.post("/api/filter", json={"date_mode": "all", "kinds": ["video"]}).get_json()
check({i["name"] for i in f2["items"]} == {"IMG_0004.MP4"}, "video-only filter")

print("filter: keep live pairs together")
f3 = client.post("/api/filter", json={"date_mode": "all", "kinds": ["live"]}).get_json()
check({i["name"] for i in f3["items"]} == {"IMG_0002.JPG", "IMG_0002.MOV"},
      "live still pulls its motion clip in")

print("preview")
p = client.post("/api/preview", json={"path": "/DCIM/100APPLE/IMG_0001.JPG"}).get_json()
check(p.get("ok") and p.get("kind") == "image", "image preview ok")
t = client.get("/api/thumb?path=/DCIM/100APPLE/IMG_0001.JPG")
check(t.status_code == 200 and t.mimetype == "image/jpeg", "thumbnail served as jpeg")
tv = client.get("/api/thumb?path=/DCIM/100APPLE/IMG_0004.MP4")
check(tv.status_code == 204, "video thumbnail skipped (204) to avoid pulling whole file")
v = client.post("/api/preview", json={"path": "/DCIM/100APPLE/IMG_0004.MP4"}).get_json()
check(v.get("kind") == "video", "video preview prepared")

print("export")
paths = [i["path"] for i in f["items"]]
client.post("/api/export", json={"paths": paths})
for _ in range(60):
    st = client.get("/api/export/status").get_json()
    if st["state"] != "running":
        break
    time.sleep(0.2)
check(st["state"] == "done", f"export finished (state={st['state']})")
check(st["failed"] == 0, "no failures")
check(st.get("safe_to_delete") is True, "verification says safe to delete")
out = Path(st["out_dir"])
check((out / "manifest.csv").exists(), "manifest written")
check((out / "VERIFY.txt").exists(), "VERIFY.txt written")
copied = sorted(p.name for p in out.rglob("*") if p.suffix.lower() in MEDIA_EXT)
check(len(copied) == 4, f"4 media files on disk (got {len(copied)})")

print("export again (resume)")
client.post("/api/export", json={"paths": paths})
for _ in range(60):
    st2 = client.get("/api/export/status").get_json()
    if st2["state"] != "running":
        break
    time.sleep(0.2)
check(st2.get("resumed") == 4 and st2.get("copied") == 0, "second run resumed all files")

print("exported flag after export")
f4 = client.post("/api/filter", json={"date_mode": "all", "exported": "no"}).get_json()
check(f4["summary"]["count"] == 2, f"2 unexported files remain (got {f4['summary']['count']})")

shutil.rmtree(tmp, ignore_errors=True)
print()
if failures:
    print("FAILURES:")
    for f_ in failures:
        print("  -", f_)
    sys.exit(1)
print("ALL GUI CHECKS PASSED")
