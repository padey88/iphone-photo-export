#!/usr/bin/env python3
"""Build a fake iPhone DCIM tree for testing the GUI without a phone."""
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw

root = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/fake_iphone")
dcim = root / "DCIM" / "100APPLE"
dcim.mkdir(parents=True, exist_ok=True)


def img(path: Path, color: str, label: str):
    im = Image.new("RGB", (1200, 900), color)
    d = ImageDraw.Draw(im)
    d.rectangle([40, 40, 1160, 860], outline="white", width=6)
    d.text((70, 70), label, fill="white")
    im.save(path)


def touch(path: Path, when: str):
    ts = datetime.fromisoformat(when).timestamp()
    os.utime(path, (ts, ts))


def video(path: Path, seconds: int, when: str, color="navy"):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", f"color=c={color}:s=640x480:d={seconds}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    touch(path, when)


# 1: old photo, pre-2026
img(dcim / "IMG_0001.JPG", "#2b6cb0", "2025-06-01")
touch(dcim / "IMG_0001.JPG", "2025-06-01T10:00:00")

# 2: Live Photo pair (HEIC not written; JPG + MOV share the stem)
img(dcim / "IMG_0002.JPG", "#2f855a", "2025-12-15 live")
touch(dcim / "IMG_0002.JPG", "2025-12-15T08:30:00")
video(dcim / "IMG_0002.MOV", 2, "2025-12-15T08:30:00", "darkgreen")

# 3: screenshot in 2026 (should be excluded by "older than 2026")
img(dcim / "IMG_0003.PNG", "#6b46c1", "2026-03-01 screenshot")
touch(dcim / "IMG_0003.PNG", "2026-03-01T12:00:00")

# 4: old video, 2024
video(dcim / "IMG_0004.MP4", 3, "2024-01-10T09:00:00", "maroon")

# 5: screen recording, 2026
video(dcim / "RPReplay_Final1700000000.MP4", 2, "2026-02-01T09:00:00", "black")

# 6: recent photo 2026
img(dcim / "IMG_0005.JPG", "#b7791f", "2026-09-09")
touch(dcim / "IMG_0005.JPG", "2026-09-09T18:00:00")

# noise: non-media file must be ignored
(dcim / "notes.txt").write_text("ignore me")

files = sorted(p.name for p in dcim.iterdir())
print(f"built {root} with {len(files)} files: {files}")
