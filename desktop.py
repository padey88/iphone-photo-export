"""Native desktop entry point (frozen build).

    iPhonePhotoExport.exe                 -> native window (pywebview), fallback browser
    iPhonePhotoExport.exe --serve         -> just the local server (no window)
    iPhonePhotoExport.exe --selftest      -> bundled-dependency + fake-device smoke test
    iPhonePhotoExport.exe --fake <folder> -> run the UI against a folder instead of a phone

The Flask app is exactly the same one `python app.py` serves; this module only
owns the window, the log file and the packaged-resource paths.
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

APP_NAME = "iPhone Photo Export"


def resource_dir() -> Path:
    """Directory holding bundled read-only resources (templates, ffmpeg, ...)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).parent


def data_dir() -> Path:
    """Writable per-user directory for logs, thumbnails and preview cache."""
    root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    d = Path(root) / "iPhonePhotoExport"
    d.mkdir(parents=True, exist_ok=True)
    return d


def free_port(preferred: int = 8765) -> int:
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("no free TCP port")


class Logger:
    """Tiny file logger: a windowed build has no console to print to."""

    def __init__(self) -> None:
        self.path = data_dir() / "app.log"
        self._lock = threading.Lock()
        try:
            if self.path.exists() and self.path.stat().st_size > 2_000_000:
                self.path.replace(self.path.with_suffix(".1.log"))
        except OSError:
            pass

    def __call__(self, msg: str) -> None:
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n"
        with self._lock:
            try:
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(line)
            except OSError:
                pass
        try:
            sys.stdout.write(line)
            sys.stdout.flush()
        except Exception:
            pass


log = Logger()


def prepare_env() -> None:
    """Point the app at bundled resources and per-user writable folders."""
    base = resource_dir()
    here = Path(sys.executable).parent if getattr(sys, "frozen", False) else base
    os.environ.setdefault("IPHONE_EXPORT_RESOURCE", str(base))
    os.environ.setdefault("IPHONE_EXPORT_CACHE", str(data_dir() / "cache"))

    # ffmpeg ships next to the executable (bin\ffmpeg.exe); make it findable
    for cand in (here / "bin", base / "bin", here):
        if (cand / "ffmpeg.exe").exists() or (cand / "ffmpeg").exists():
            os.environ["PATH"] = str(cand) + os.pathsep + os.environ.get("PATH", "")
            break


def start_server(port: int) -> threading.Thread:
    import app as webapp

    def run() -> None:
        try:
            webapp.app.run(host="127.0.0.1", port=port, threaded=True, debug=False,
                           use_reloader=False)
        except Exception:
            log("server crashed:\n" + traceback.format_exc())

    t = threading.Thread(target=run, daemon=True, name="flask")
    t.start()
    return t


def wait_ready(port: int, timeout: float = 20.0) -> bool:
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.25)
    return False


def open_window(url: str) -> bool:
    """Native window if WebView2 is available, else the default browser."""
    try:
        import webview
    except Exception as exc:
        log(f"pywebview unavailable ({exc}); using the browser")
        return False
    try:
        webview.create_window(APP_NAME, url, width=1240, height=820, min_size=(960, 620))
        webview.start(private_mode=False)
        return True
    except Exception:
        log("pywebview failed:\n" + traceback.format_exc())
        return False


def selftest() -> int:
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, fn) -> None:
        try:
            checks.append((name, True, str(fn())))
        except Exception as exc:
            checks.append((name, False, f"{type(exc).__name__}: {exc}"))

    check("python", lambda: sys.version.split()[0])
    check("flask", lambda: __import__("flask").__version__)
    def pmd3_version() -> str:
        import pymobiledevice3
        v = getattr(pymobiledevice3, "__version__", None)
        if not v:
            from importlib.metadata import version as _v
            v = _v("pymobiledevice3")
        return v

    check("pymobiledevice3", pmd3_version)
    check("usbmux", lambda: (__import__("pymobiledevice3.usbmux", fromlist=["x"]).list_devices and "ok"))
    check("afc", lambda: (__import__("pymobiledevice3.services.afc", fromlist=["x"]).AfcService and "ok"))
    check("pillow", lambda: __import__("PIL").__version__)

    def heif() -> str:
        from pillow_heif import register_heif_opener
        register_heif_opener()
        return "registered"

    check("pillow-heif", heif)

    def ffmpeg() -> str:
        import shutil
        import subprocess
        exe = shutil.which("ffmpeg")
        if not exe:
            raise RuntimeError("ffmpeg not found on PATH")
        out = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=30)
        return out.stdout.splitlines()[0][:40]

    check("ffmpeg", ffmpeg)
    check("templates", lambda: (resource_dir() / "templates" / "index.html").stat().st_size)

    port = free_port()
    check("server", lambda: "listening" if (start_server(port) and wait_ready(port)) else "FAILED")

    def api() -> str:
        import json
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=10) as r:
            data = json.load(r)
        return f"{data['dest']} · {data['inventory_count']} items"

    check("api /api/state", api)
    check("webview2", lambda: "present" if __import__("webview") else "")

    ok = True
    lines = []
    for name, good, detail in checks:
        ok = ok and good
        lines.append(f"[{'PASS' if good else 'FAIL'}] {name:<22} {detail}")
    lines.append(f"SELFTEST: {'PASS' if ok else 'FAIL'}")
    report = "\n".join(lines)
    try:
        (data_dir() / "selftest.txt").write_text(report, encoding="utf-8")
    except OSError:
        pass
    print(report)
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(prog=APP_NAME)
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--fake", metavar="FOLDER")
    ap.add_argument("--open-browser", action="store_true")
    args = ap.parse_args()

    if args.fake:
        os.environ["IPHONE_EXPORT_FAKE"] = args.fake

    if args.selftest:
        prepare_env()
        return selftest()

    prepare_env()
    port = args.port or free_port(int(os.environ.get("IPHONE_EXPORT_PORT", 8765)))
    url = f"http://127.0.0.1:{port}/"
    log(f"starting {APP_NAME}: {url} (frozen={getattr(sys, 'frozen', False)})")
    start_server(port)
    if not wait_ready(port):
        log("server did not become ready in time")
        return 1

    if args.serve:
        log("serve mode: press Ctrl+C to stop")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0

    if open_window(url) and not args.open_browser:
        log("window closed; exiting")
        return 0

    webbrowser.open(url)
    log("browser mode: keep this process alive; close it to stop the app")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        log("fatal:\n" + traceback.format_exc())
        raise SystemExit(1)
