"""iPhone Photo Export - local web GUI.

    python app.py            # starts http://127.0.0.1:8765 and opens the browser
    python app.py --no-open  # headless (used by the tests)

Environment:
    IPHONE_EXPORT_DEST   destination folder (default ~/Pictures/iPhone-Export)
    IPHONE_EXPORT_FAKE   path to a fake device folder (tests / demo, no phone)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import quote

from flask import Flask, jsonify, request, send_file

import exporter
import filters
from device import DeviceBridge, DeviceError

try:  # HEIC support
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:
    pass
from PIL import Image

APP_DIR = Path(__file__).parent
CACHE = Path(os.environ.get("IPHONE_EXPORT_CACHE", Path.home() / ".iphone-export-cache"))
THUMBS = CACHE / "thumbs"
MEDIA = CACHE / "media"
for d in (THUMBS, MEDIA):
    d.mkdir(parents=True, exist_ok=True)

THUMB_PX = 480
VIDEO_CONFIRM_MB = 150

app = Flask(__name__, static_folder=str(APP_DIR / "static"),
            static_url_path="/static", template_folder=str(APP_DIR / "templates"))

bridge = DeviceBridge()
STATE: dict = {
    "inventory": [],          # raw items from device
    "classified": [],         # annotated
    "exported_index": {},
    "dest": Path(os.environ.get("IPHONE_EXPORT_DEST",
                                Path.home() / "Pictures" / "iPhone-Export")).expanduser(),
    "job": None,
    "last_export": None,
}
LOCK = threading.Lock()


def token_for(device_path: str) -> str:
    return hashlib.sha1(device_path.encode()).hexdigest()[:16]


def find_item(device_path: str) -> dict | None:
    for it in STATE["classified"]:
        if it["path"] == device_path:
            return it
    return None


def refresh_inventory() -> dict:
    items = bridge.inventory("/DCIM")
    exported = exporter.already_exported_index(STATE["dest"])
    classified = filters.classify(exporter.walk_inventory(items), exported)
    STATE["inventory"] = items
    STATE["classified"] = classified
    STATE["exported_index"] = exported
    return {"items": classified, "summary": filters.summarize(classified)}


# --------------------------------------------------------------------------- API
@app.get("/")
def index():
    return send_file(APP_DIR / "templates" / "index.html")


@app.get("/api/state")
def api_state():
    return jsonify({
        "connected": bridge.connected,
        "device": bridge.info,
        "dest": str(STATE["dest"]),
        "presets": filters.suggest_presets(),
        "kinds": [
            {"id": "photo", "label": "Photos"},
            {"id": "live", "label": "Live Photos"},
            {"id": "video", "label": "Videos"},
            {"id": "recording", "label": "Screen recordings"},
            {"id": "screenshot", "label": "Screenshots"},
        ],
        "fake": bool(bridge.fake_root),
        "inventory_count": len(STATE["classified"]),
    })


@app.get("/api/devices")
def api_devices():
    try:
        return jsonify({"devices": bridge.devices()})
    except DeviceError as exc:
        return jsonify({"error": str(exc)}), 503


@app.post("/api/connect")
def api_connect():
    payload = request.get_json(silent=True) or {}
    try:
        info = bridge.connect(payload.get("udid"))
    except DeviceError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500
    try:
        data = refresh_inventory()
    except Exception as exc:
        return jsonify({"error": f"connected but reading /DCIM failed: {exc}"}), 500
    return jsonify({"device": info, **data, "summary_all": data["summary"]})


@app.post("/api/disconnect")
def api_disconnect():
    bridge.disconnect()
    with LOCK:
        STATE["inventory"], STATE["classified"] = [], []
    return jsonify({"ok": True})


@app.post("/api/refresh")
def api_refresh():
    if not bridge.connected:
        return jsonify({"error": "not connected"}), 400
    try:
        return jsonify(refresh_inventory())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/filter")
def api_filter():
    spec = request.get_json(silent=True) or {}
    picked = filters.apply_filters(STATE["classified"], spec)
    return jsonify({"items": picked, "summary": filters.summarize(picked)})


@app.post("/api/config")
def api_config():
    payload = request.get_json(silent=True) or {}
    if "dest" in payload and payload["dest"]:
        dest = Path(payload["dest"]).expanduser()
        try:
            dest.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            return jsonify({"error": f"cannot use {dest}: {exc}"}), 400
        STATE["dest"] = dest
        STATE["exported_index"] = exporter.already_exported_index(dest)
    return jsonify({"dest": str(STATE["dest"])})


# ------------------------------------------------------------------ preview
def _ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def make_thumb(item: dict) -> Path | None:
    """Ensure a JPEG thumbnail exists for the item; returns its path or None."""
    thumb = THUMBS / f"{token_for(item['path'])}.jpg"
    if thumb.exists() and thumb.stat().st_size > 0:
        return thumb
    media = ensure_media(item)
    if not media:
        return None
    try:
        if item["is_video"]:
            ff = _ffmpeg()
            if not ff:
                return None
            subprocess.run([ff, "-y", "-loglevel", "error", "-ss", "0.5", "-i", str(media),
                            "-frames:v", "1", "-vf", f"scale={THUMB_PX}:-2", str(thumb)],
                           check=True, timeout=120)
        else:
            with Image.open(media) as im:
                im = im.convert("RGB")
                im.thumbnail((THUMB_PX, THUMB_PX))
                im.save(thumb, "JPEG", quality=82)
    except Exception:
        return None
    return thumb if thumb.exists() and thumb.stat().st_size > 0 else None


def ensure_media(item: dict) -> Path | None:
    """Pull the full file into the cache (needed for previews and video playback)."""
    ext = item.get("ext") or Path(item["path"]).suffix.lower()
    media = MEDIA / f"{token_for(item['path'])}{ext}"
    if media.exists() and media.stat().st_size == item["size"]:
        return media
    tmp = media.with_suffix(media.suffix + ".part")
    try:
        bridge.pull(item["path"], tmp)
        if tmp.stat().st_size != item["size"]:
            tmp.unlink(missing_ok=True)
            return None
        tmp.replace(media)
        return media
    except Exception:
        tmp.unlink(missing_ok=True)
        return None


@app.post("/api/preview")
def api_preview():
    payload = request.get_json(silent=True) or {}
    item = find_item(payload.get("path", ""))
    if not item:
        return jsonify({"error": "unknown item"}), 404

    cached = (MEDIA / f"{token_for(item['path'])}{item['ext']}").exists()
    if item["is_video"] and not cached and item["mb"] > VIDEO_CONFIRM_MB and not payload.get("confirm"):
        return jsonify({"needs_confirm": True, "size_mb": item["mb"],
                        "message": f"Downloading {item['mb']:.0f} MB to preview this video?"})

    media = ensure_media(item)
    if not media:
        return jsonify({"error": "could not read file from device"}), 500
    thumb = make_thumb(item)
    return jsonify({
        "ok": True,
        "kind": "video" if item["is_video"] else "image",
        "media_url": f"/api/media/{token_for(item['path'])}",
        "thumb_url": f"/api/thumb?path={quote(item['path'])}" if thumb else None,
        "name": item["name"], "size_mb": item["mb"], "date": item["date"],
        "kind_label": item["kind"],
    })


@app.get("/api/thumb")
def api_thumb():
    """Thumbnail by device path. Pulls the file into the cache once, then reuses."""
    path = request.args.get("path", "")
    item = find_item(path)
    if not item:
        return ("", 404)
    if item["is_video"]:
        # Videos are not pulled just to render a grid: too expensive.
        return ("", 204)
    thumb = make_thumb(item)
    if not thumb:
        return ("", 204)
    return send_file(thumb, mimetype="image/jpeg", max_age=3600)


@app.get("/api/media/<token>")
def api_media(token: str):
    for it in STATE["classified"]:
        if token_for(it["path"]) == token:
            media = MEDIA / f"{token}{it['ext']}"
            if media.exists():
                return send_file(media, conditional=True)
            return ("", 404)
    return ("", 404)


# ------------------------------------------------------------------- export
def run_export(paths: list[str], dest: Path, udid: str, job: dict) -> None:
    items = [i for i in STATE["classified"] if i["path"] in set(paths)]
    items = [{"path": i["path"], "size": i["size"], "mtime": i["mtime"]} for i in items]
    out_dir = dest / udid

    def on_progress(p):
        job.update(p)

    def on_error(path, msg):
        job.setdefault("errors", []).append({"path": path, "error": msg})

    try:
        result = bridge.call(
            exporter.copy_items(bridge.afc(), items, out_dir, on_progress=on_progress,
                                on_error=on_error),
            timeout=7200)
        verification = exporter.verify_items(items, out_dir)
        exporter.write_manifest(result["rows"], out_dir / "manifest.csv")
        exporter.write_report(out_dir / "VERIFY.txt", serial=udid, source="/DCIM",
                              copy_result=result, verification=verification)
        job.update({
            "state": "done",
            "copied": result["copied"], "resumed": result["resumed"],
            "failed": result["failed"],
            "verification": {k: v for k, v in verification.items() if k not in ("missing", "mismatch")},
            "missing": len(verification["missing"]),
            "mismatch": len(verification["mismatch"]),
            "safe_to_delete": verification["ok"] and result["failed"] == 0,
            "out_dir": str(out_dir),
            "seconds": round(time.time() - job["started"], 1),
        })
        with LOCK:
            STATE["exported_index"] = exporter.already_exported_index(dest)
            STATE["last_export"] = job
            for it in STATE["classified"]:
                if it["path"] in set(paths):
                    it["exported"] = True
    except Exception as exc:
        job.update({"state": "error", "error": f"{type(exc).__name__}: {exc}"})
    finally:
        job["finished"] = time.time()


@app.post("/api/export")
def api_export():
    payload = request.get_json(silent=True) or {}
    paths = payload.get("paths") or []
    if not paths:
        return jsonify({"error": "nothing selected"}), 400
    if STATE["job"] and STATE["job"].get("state") == "running":
        return jsonify({"error": "an export is already running"}), 409
    if not bridge.connected:
        return jsonify({"error": "not connected"}), 400
    job = {"state": "running", "total": len(paths), "done": 0,
           "copied": 0, "resumed": 0, "failed": 0, "bytes": 0,
           "current": "", "started": time.time()}
    STATE["job"] = job
    threading.Thread(target=run_export,
                     args=(paths, STATE["dest"], bridge.udid or "device", job),
                     daemon=True).start()
    return jsonify({"ok": True, "job": job})


@app.get("/api/export/status")
def api_export_status():
    return jsonify(STATE["job"] or {"state": "idle"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("IPHONE_EXPORT_PORT", 8765)))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()
    url = f"http://{args.host}:{args.port}/"
    if not args.no_open:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"iPhone Photo Export running at {url}")
    print(f"destination: {STATE['dest']}")
    app.run(host=args.host, port=args.port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
