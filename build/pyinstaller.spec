# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: one self-contained folder (exe + runtime + ffmpeg).

Built by build.ps1. Everything the app needs at runtime lives inside the
dist folder, so the Inno Setup installer can ship a single .exe payload.
"""
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

# SPECPATH is the directory containing this spec (build/), so the app root is
# one level up.
ROOT = Path(SPECPATH).resolve().parent
DIST = ROOT / "payload"

datas = [
    (str(ROOT / "templates"), "templates"),
    (str(ROOT / "assets" / "app.png"), "assets"),
]
# ffmpeg is required for video thumbnails; ffprobe is optional and only added
# when it was staged (it costs another ~100 MB in the payload).
for name in ("ffmpeg.exe", "ffprobe.exe"):
    p = ROOT / "bin" / name
    if p.exists():
        datas.append((str(p), "bin"))
binaries = []
hiddenimports = [
    "app", "device", "exporter", "filters", "desktop",
    "flask", "jinja2", "werkzeug", "click", "itsdangerous",
    "PIL.Image", "pillow_heif",
    "webview", "clr_loader", "pythonnet",
]

for pkg in ("pymobiledevice3", "webview", "pillow_heif", "PIL"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:  # pragma: no cover
        print(f"WARN collect_all({pkg}) failed: {exc}")

hiddenimports += collect_submodules("pymobiledevice3")

# pymobiledevice3 spawns its own subcommands; keep its CLI entry points reachable.
hiddenimports += ["pymobiledevice3.__main__", "pymobiledevice3.cli"]

block_cipher = None

a = Analysis(
    [str(ROOT / "desktop.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "pytest", "IPython", "jupyter"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="iPhonePhotoExport",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ROOT / "assets" / "app.ico") if (ROOT / "assets" / "app.ico").exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="iPhonePhotoExport",
)
