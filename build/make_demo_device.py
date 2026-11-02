"""Build a realistic fake iPhone camera roll for screenshots and demos.

    python build/make_demo_device.py --out /tmp/demo/phone

Creates /DCIM with stills across several months, a Live Photo pair, three real
H.264 videos (so playback and video thumbnails work), a screen recording, a
screenshot and one oversized video. Used by make_screenshots.py.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

PALETTE = [
    (255, 138, 76), (76, 175, 80), (33, 150, 243), (233, 30, 99),
    (255, 193, 7), (121, 85, 72), (63, 81, 181), (0, 188, 212),
    (156, 39, 176), (255, 87, 34), (96, 125, 139), (139, 195, 74),
]
LABELS = [
    "Beach", "Sunset", "Kopi", "Garden", "KLCC", "Rain", "Durian", "Market",
    "Mosque", "Bukit", "Family", "Dinner", "Train", "Rainbow", "Cats",
    "Raya", "Cameron", "Laksa", "Ferry", "Campus", "Monsoon", "Rooftop",
    "Nasi Lemak", "Waterfall",
]


def fetch_photo(dest: Path, seed: str, size=(1600, 1200), cache: Path | None = None) -> bool:
    """Try to download a real, freely usable photo (Lorem Picsum / Unsplash).

    Screenshots with photographic thumbnails look honest; synthetic art reads as
    a mock-up. Falls back to drawing when the network is unavailable.
    """
    import urllib.request

    cache = cache or Path("/tmp/ipe-demo-photos")
    cache.mkdir(parents=True, exist_ok=True)
    w, h = size
    blob = cache / f"{seed}-{w}x{h}.jpg"
    if not blob.exists():
        url = f"https://picsum.photos/seed/{seed}/{w}/{h}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "iphone-export-demo"})
            with urllib.request.urlopen(req, timeout=30) as r:
                blob.write_bytes(r.read())
        except Exception as exc:
            print(f"  ! {seed}: {exc}")
            return False
    if blob.stat().st_size < 5000:
        return False
    from PIL import Image
    with Image.open(blob) as im:
        im.convert("RGB").save(dest, "JPEG", quality=88)
    return True


def make_photo(path: Path, idx: int, label: str, size=(1600, 1200)) -> None:
    """Real photo if the network allows, otherwise a drawn stand-in."""
    if fetch_photo(path, f"{label.lower().replace(' ', '-')}-{idx}", size):
        return
    _draw_photo(path, idx, label, size)


def _draw_photo(path: Path, idx: int, label: str, size=(1600, 1200)) -> None:
    import random

    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    rnd = random.Random(idx * 7919)
    w, h = size
    r, g, b = PALETTE[idx % len(PALETTE)]
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)

    # sky gradient (top: tinted, bottom: warm horizon)
    horizon = int(h * 0.58)
    for y in range(horizon):
        t = y / horizon
        d.line([(0, y), (w, y)], fill=(int(120 + 100 * t), int(150 + 60 * t), int(210 - 40 * t)))
    # water
    for y in range(horizon, h):
        t = (y - horizon) / max(1, h - horizon)
        d.line([(0, y), (w, y)], fill=(int(90 - 40 * t), int(130 - 50 * t), int(180 - 40 * t)))

    # sun + glow
    sx, sy = int(w * rnd.uniform(0.15, 0.8)), int(horizon * rnd.uniform(0.25, 0.55))
    for rad, alpha in ((int(h * .22), 40), (int(h * .14), 70), (int(h * .07), 255)):
        d.ellipse([sx - rad, sy - rad, sx + rad, sy + rad], fill=(255, 240, 190, alpha) if alpha < 255 else (255, 246, 214))

    # hills: 3 layers, darker in front
    for layer in range(3):
        base = horizon + int(h * 0.02 * layer)
        amp = h * (0.10 - 0.025 * layer)
        pts = [(0, h)]
        step = max(8, w // 40)
        for x in range(0, w + step, step):
            pts.append((x, base - amp * (0.5 + 0.5 * rnd.random())))
        pts.append((w, h))
        shade = int(70 + 40 * layer)
        d.polygon(pts, fill=(shade, shade + 18, shade + 30))

    # sun reflection on the water
    d.line([(sx, horizon + 4), (sx, h)], fill=(255, 250, 220), width=max(2, w // 120))

    # foreground tint from the palette so each photo feels different
    overlay = Image.new("RGB", (w, h), (r, g, b))
    img = Image.blend(img, overlay, 0.18)
    img = img.filter(ImageFilter.GaussianBlur(0.6))

    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", int(h * .062))
    except OSError:
        font = ImageFont.load_default()
    # soft shadow then the label
    d.text((int(w * .071) + 3, int(h * .855) + 3), label, font=font, fill=(0, 0, 0))
    d.text((int(w * .07), int(h * .85)), label, font=font, fill=(255, 255, 255))
    img.save(path, "JPEG", quality=88)


def ffmpeg(out: Path, spec: str, extra: list[str] | None = None) -> None:
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", spec,
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast"] + (extra or []) + [str(out)]
    subprocess.run(cmd, check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/demo/phone")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    root = Path(args.out)
    if root.exists() and not args.keep:
        shutil.rmtree(root)
    dcim = root / "DCIM" / "100APPLE"
    dcim2 = root / "DCIM" / "101APPLE"
    dcim.mkdir(parents=True, exist_ok=True)
    dcim2.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    for i, label in enumerate(LABELS):
        folder = dcim if i % 2 == 0 else dcim2
        p = folder / f"IMG_{1000 + i:04d}.JPG"
        make_photo(p, i, label)
        ts = (now - timedelta(days=i * 5)).timestamp()
        os.utime(p, (ts, ts))

    # Live Photo pair (still + motion clip sharing the stem)
    still = dcim / "IMG_2001.HEIC"
    tmp = dcim / "IMG_2001.JPG"
    make_photo(tmp, 3, "Live Photo")
    tmp.rename(still)
    shutil.copy2(still, dcim / "IMG_2002.HEIC")
    # iOS stores the motion part next to the still with the same stem
    motion = dcim / "IMG_2001.MOV"
    ffmpeg(motion, "testsrc2=size=1440x1080:rate=30:duration=3")
    ts = (now - timedelta(days=4)).timestamp()
    os.utime(motion, (ts, ts))

    vids = [
        ("IMG_3001.MOV", "testsrc2=size=1280x720:rate=30:duration=4", 12),
        ("IMG_3002.MOV", "smptebars=size=1280x720:rate=30:duration=3", 40),
        ("RPReplay_Final1690000000.MP4", "testsrc=size=720x1280:rate=30:duration=3", 65),
    ]
    for name, spec, days in vids:
        out = dcim / name
        ffmpeg(out, spec)
        ts = (now - timedelta(days=days)).timestamp()
        os.utime(out, (ts, ts))

    big = dcim / "IMG_4001.MOV"
    ffmpeg(big, "testsrc2=size=1920x1080:rate=30:duration=40", ["-b:v", "12M"])
    ts = (now - timedelta(days=3)).timestamp()
    os.utime(big, (ts, ts))

    # an iOS-style screenshot
    shot = dcim / "IMG_5001.PNG"
    make_photo(shot, 6, "Screenshot", size=(1206, 2622))
    ts = (now - timedelta(days=1)).timestamp()
    os.utime(shot, (ts, ts))

    files = [p for p in root.rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    print(f"demo device: {len(files)} files, {total / 1e6:.1f} MB at {root}")


if __name__ == "__main__":
    main()
