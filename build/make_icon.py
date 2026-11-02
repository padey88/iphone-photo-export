"""Generate assets/app.ico (and a PNG preview) without any external tools.

A clean, phone-shaped glyph: rounded device with a lens and a photo stack,
rendered at 256px then downsampled to every icon size Windows asks for.
"""
from __future__ import annotations

import struct
from pathlib import Path

from PIL import Image, ImageDraw

try:
    LANCZOS = Image.Resampling.LANCZOS
except AttributeError:  # Pillow < 9.1
    LANCZOS = 1  # Image.LANCZOS == Image.ANTIALIAS constant

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "assets"
SIZES = [16, 24, 32, 48, 64, 128, 256]
BASE = 1024


def rounded(size: int, radius: int, fill):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=fill)
    return img


def make_master() -> Image.Image:
    s = BASE
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # backdrop: soft blue gradient in a rounded square
    for y in range(s):
        t = y / s
        col = (int(37 + 22 * t), int(99 + 40 * t), int(235 - 10 * t), 255)
        d.line([(0, y), (s, y)], fill=col)
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=255)
    img.putalpha(mask)

    # photo stack (back sheets), offset up-right
    d = ImageDraw.Draw(img)
    sheet = (255, 255, 255, 70)
    card = (255, 255, 255, 235)
    d.rounded_rectangle([int(s * .36), int(s * .18), int(s * .84), int(s * .60)],
                        radius=int(s * .05), fill=sheet)
    d.rounded_rectangle([int(s * .30), int(s * .24), int(s * .78), int(s * .66)],
                        radius=int(s * .05), fill=(255, 255, 255, 150))

    # phone body
    body = [int(s * .16), int(s * .16), int(s * .62), int(s * .84)]
    d.rounded_rectangle(body, radius=int(s * .10), fill=(15, 23, 42, 255))
    d.rounded_rectangle([body[0] + int(s * .025), body[1] + int(s * .025),
                         body[2] - int(s * .025), body[3] - int(s * .025)],
                        radius=int(s * .085), fill=(248, 250, 252, 255))

    # camera lens
    cx, cy, r = int(s * .39), int(s * .35), int(s * .085)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(30, 41, 59, 255))
    d.ellipse([cx - int(r * .55), cy - int(r * .55), cx + int(r * .55), cy + int(r * .55)],
              fill=(96, 165, 250, 255))
    d.ellipse([cx - int(r * .25), cy - int(r * .25), cx + int(r * .25), cy + int(r * .25)],
              fill=(226, 240, 255, 255))

    # screen: little photo + arrow hinting transfer
    d.rounded_rectangle([int(s * .21), int(s * .50), int(s * .57), int(s * .74)],
                        radius=int(s * .04), fill=(219, 234, 254, 255))
    d.ellipse([int(s * .255), int(s * .535), int(s * .315), int(s * .595)], fill=(251, 191, 36, 255))
    d.polygon([(int(s * .215), int(s * .735)), (int(s * .32), int(s * .625)),
               (int(s * .40), int(s * .70)), (int(s * .455), int(s * .655)),
               (int(s * .565), int(s * .735))], fill=(59, 130, 246, 255))

    # transfer arrow
    ax, ay = int(s * .72), int(s * .70)
    d.line([(ax - int(s * .10), ay), (ax + int(s * .08), ay)], fill=(255, 255, 255, 255),
           width=int(s * .035))
    d.polygon([(ax + int(s * .12), ay), (ax + int(s * .045), ay - int(s * .055)),
               (ax + int(s * .045), ay + int(s * .055))], fill=(255, 255, 255, 255))
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    master = make_master()
    master.resize((256, 256), 1).save(OUT / "app.png")

    images = [master.resize((n, n), 1) for n in SIZES]
    ico = OUT / "app.ico"
    images[0].save(ico, format="ICO", sizes=[(n, n) for n in SIZES],
                   append_images=images[1:])
    print(f"wrote {ico} ({ico.stat().st_size} bytes, {len(SIZES)} sizes)")

    # also emit an installer-side wizard image (small + large)
    master.resize((55, 55), 1).save(OUT / "wizard-small.bmp")
    master.resize((164, 314), 1).crop((0, 0, 164, 314)).save(OUT / "wizard-large.bmp")
    print("wrote assets/app.png, wizard-small.bmp, wizard-large.bmp")


if __name__ == "__main__":
    main()
