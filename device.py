"""Long-lived AFC connection behind a synchronous facade.

Flask handlers are sync; pymobiledevice3 is async. One background event loop owns
the connection so every request reuses the same trusted session instead of
re-pairing per call (which costs ~1s and can trip the trust prompt).

Set IPHONE_EXPORT_FAKE=/path/to/folder to run the whole app against a fake
device (used by the automated UI tests and handy for demos without a phone).
"""
from __future__ import annotations

import asyncio
import os
import posixpath
import threading
from datetime import datetime
from pathlib import Path

from exporter import MEDIA_EXT


class DeviceError(RuntimeError):
    pass


class _FakeAfc:
    """Directory-backed stand-in for AfcService."""

    def __init__(self, root: Path):
        self.root = root

    def _p(self, device_path: str) -> Path:
        return self.root / device_path.lstrip("/")

    async def listdir(self, path: str) -> list[str]:
        p = self._p(path)
        if not p.exists():
            raise FileNotFoundError(path)
        return sorted(x.name for x in p.iterdir())

    async def isdir(self, path: str) -> bool:
        return self._p(path).is_dir()

    async def stat(self, path: str) -> dict:
        st = self._p(path).stat()
        return {"st_size": st.st_size, "st_mtime": datetime.fromtimestamp(st.st_mtime)}

    async def pull(self, src: str, dst: str, progress_bar: bool = False) -> None:
        data = self._p(src).read_bytes()
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(dst).write_bytes(data)


class DeviceBridge:
    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="afc-loop")
        self._thread.start()
        self._afc = None
        self._lockdown = None
        self.udid: str | None = None
        self.info: dict = {}
        self.fake_root = os.environ.get("IPHONE_EXPORT_FAKE")

    # ---------- plumbing ----------
    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def call(self, coro, timeout: float = 300):
        if not self._loop.is_running():
            raise DeviceError("background loop is not running")
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=timeout)

    # ---------- public sync API ----------
    @property
    def connected(self) -> bool:
        return self._afc is not None

    def devices(self) -> list[dict]:
        if self.fake_root:
            return [{"udid": "FAKE-DEVICE", "name": "Fake iPhone (demo)", "model": "iPhone12,3",
                     "ios": "17.0", "connection": "USB"}]
        return self.call(self._list_devices(), timeout=30)

    def connect(self, udid: str | None = None) -> dict:
        self.disconnect()
        if self.fake_root:
            root = Path(self.fake_root).expanduser().resolve()
            if not (root / "DCIM").is_dir():
                raise DeviceError(f"fake device has no DCIM folder: {root}")
            self._afc = _FakeAfc(root)
            self.udid = "FAKE-DEVICE"
            self.info = {"udid": self.udid, "name": "Fake iPhone (demo)",
                         "model": "iPhone12,3", "ios": "17.0"}
            return self.info
        return self.call(self._connect(udid), timeout=90)

    def disconnect(self) -> None:
        if self._afc is None:
            return
        try:
            self.call(self._disconnect(), timeout=20)
        except Exception:
            pass
        self._afc = None
        self._lockdown = None
        self.udid = None
        self.info = {}

    def inventory(self, root: str = "/DCIM") -> list[dict]:
        if not self._afc:
            raise DeviceError("not connected")
        return self.call(self._inventory(root), timeout=300)

    def pull(self, device_path: str, local_path: Path) -> None:
        if not self._afc:
            raise DeviceError("not connected")
        self.call(self._afc.pull(device_path, str(local_path), progress_bar=False), timeout=3600)

    def afc(self):
        return self._afc

    # ---------- async internals ----------
    async def _list_devices(self) -> list[dict]:
        from pymobiledevice3.usbmux import list_devices
        try:
            raw = await list_devices()
        except Exception as exc:
            raise DeviceError(
                "Cannot reach Apple's device service (usbmuxd). Install iTunes from "
                f"apple.com or the Apple Devices app, plug the iPhone in directly, "
                f"unlock it and tap Trust. Detail: {exc}") from exc
        out = []
        for d in raw:
            out.append({
                "udid": getattr(d, "serial", ""),
                "name": getattr(d, "device_name", None) or "iPhone",
                "model": getattr(d, "product_id", None) or "",
                "ios": "",
                "connection": getattr(d, "connection_type", "USB"),
            })
        return out

    async def _connect(self, udid: str | None) -> dict:
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.afc import AfcService

        devices = await self._list_devices()
        usb = [d for d in devices if d["connection"] == "USB"] or devices
        if not usb:
            raise DeviceError("No iPhone detected. Unlock it, tap Trust, keep the screen on.")
        chosen = None
        if udid:
            chosen = next((d for d in usb if d["udid"] == udid), None)
            if not chosen:
                raise DeviceError(f"UDID {udid} not connected")
        elif len(usb) == 1:
            chosen = usb[0]
        else:
            raise DeviceError("Two or more phones are connected - choose one.")

        self._lockdown = await create_using_usbmux(serial=chosen["udid"])
        self._afc = await AfcService(lockdown=self._lockdown).__aenter__()
        self.udid = chosen["udid"]
        info = dict(chosen)
        try:
            info["name"] = await self._lockdown.get_value(key="DeviceName") or chosen["name"]
            info["ios"] = await self._lockdown.get_value(key="ProductVersion") or ""
            info["model"] = await self._lockdown.get_value(key="ProductType") or chosen["model"]
        except Exception:
            pass
        self.info = info
        return info

    async def _disconnect(self) -> None:
        try:
            await self._afc.__aexit__(None, None, None)
        finally:
            self._afc = None
            self._lockdown = None

    async def _inventory(self, root: str) -> list[dict]:
        afc = self._afc
        items: list[dict] = []

        async def rec(path: str) -> None:
            try:
                entries = await afc.listdir(path)
            except Exception:
                return
            for name in entries:
                full = posixpath.join(path, name)
                try:
                    if await afc.isdir(full):
                        await rec(full)
                        continue
                    st = await afc.stat(full)
                except Exception:
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
        items.sort(key=lambda x: x["mtime"], reverse=True)
        return items
