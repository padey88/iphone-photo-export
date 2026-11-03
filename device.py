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
from datetime import datetime, timezone
from pathlib import Path

import exporter
from exporter import MEDIA_EXT


class DeviceError(RuntimeError):
    pass


class _FakeAfc:
    """Directory-backed stand-in for AfcService."""

    # A real USB pull is slow; the demo can throttle the fake one so the progress
    # bar can be observed (and screenshotted) instead of finishing instantly.
    THROTTLE_MBPS = float(os.environ.get("IPHONE_EXPORT_FAKE_MBPS", "0") or 0)

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
        return {"st_size": st.st_size, "st_mtime": datetime.fromtimestamp(st.st_mtime, timezone.utc)}

    async def pull(self, src: str, dst: str, progress_bar: bool = False) -> None:
        data = self._p(src).read_bytes()
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        if self.THROTTLE_MBPS > 0:
            per_chunk = 4 * 1024 * 1024
            with open(dst, "wb") as fh:
                for i in range(0, len(data), per_chunk):
                    fh.write(data[i:i + per_chunk])
                    await asyncio.sleep(per_chunk / (self.THROTTLE_MBPS * 1024 * 1024))
            return
        Path(dst).write_bytes(data)


class DeviceBridge:
    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="afc-loop")
        self._thread.start()
        self._afc = None
        self._lockdown = None
        self._busy = False
        self._inventory_generation = 0
        self._inventories: dict[int, dict[str, dict]] = {}
        self._active_inventory: int | None = None
        self.udid: str | None = None
        self.info: dict = {}
        self.fake_root = os.environ.get("IPHONE_EXPORT_FAKE")

    # ---------- plumbing ----------
    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def call(self, coro, timeout: float | None = 300):
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
        if self._busy:
            raise DeviceError("Stop the running export before reconnecting the iPhone.")
        self.disconnect()
        if self.fake_root:
            root = Path(self.fake_root).expanduser().resolve()
            if not (root / "DCIM").is_dir():
                raise DeviceError(f"fake device has no DCIM folder: {root}")
            self._afc = _FakeAfc(root)
            self.udid = "FAKE-DEVICE"
            self.info = {"udid": self.udid, "name": "Fake iPhone (demo)",
                         "model": "iPhone12,3", "ios": "17.0"}
            self._inventories.clear()
            self._active_inventory = None
            return self.info
        return self.call(self._connect(udid), timeout=90)

    def disconnect(self) -> None:
        if self._busy:
            raise DeviceError("Stop the running export before disconnecting the iPhone.")
        if self._afc is None:
            return
        afc = self._afc
        self._afc = None
        try:
            self.call(self._disconnect(afc), timeout=20)
        finally:
            self._lockdown = None
            self.udid = None
            self.info = {}

    def inventory(self, root: str = "/DCIM") -> list[dict]:
        if not self._afc:
            raise DeviceError("not connected")
        if self._busy:
            raise DeviceError("An export is running; wait for it to finish before refreshing.")
        result = self.call(self._inventory(root), timeout=None)
        self._inventory_generation += 1
        self._inventories = {self._inventory_generation: {i["path"]: i for i in result}}
        self._active_inventory = self._inventory_generation
        return result

    def export_items(self, items, out_dir, on_progress, on_error):
        """Serialize a transfer on the dedicated AFC event loop.

        A transfer can span hours, so it cannot share call()'s short operation
        timeout. Previews continue against the last completed device snapshot.
        """
        if not self._afc:
            raise DeviceError("not connected")
        if self._busy:
            raise DeviceError("another device operation is already running")
        if self._active_inventory is not None:
            self._inventories = {self._active_inventory:
                                 self._inventories[self._active_inventory]}
        self._busy = True
        try:
            return self.call(self._export(items, out_dir, on_progress, on_error), timeout=None)
        finally:
            self._busy = False

    async def _export(self, items, out_dir, on_progress, on_error):
        afc = self._afc
        if afc is None:
            raise DeviceError("not connected")
        refreshed = []
        for item in items:
            try:
                st = await afc.stat(item["path"])
                mtime = st.get("st_mtime")
                if isinstance(mtime, datetime):
                    if mtime.tzinfo is None:
                        mtime = mtime.replace(tzinfo=timezone.utc)
                    epoch = int(mtime.timestamp())
                else:
                    epoch = int(mtime or 0)
                current = {**item, "size": int(st["st_size"]), "source_mtime": epoch}
            except Exception as exc:
                # Keep the requested metadata so verification cannot mistake a
                # missing device file for a valid copy of a newly changed one.
                current = {**item, "device_error": str(exc)}
            refreshed.append(current)
        return await exporter.copy_items(afc, refreshed, out_dir,
                                         on_progress=on_progress, on_error=on_error)

    def pull(self, device_path: str, local_path: Path) -> None:
        afc = self._afc
        if afc is None:
            raise DeviceError("not connected")
        if self._busy:
            raise DeviceError("An export is running; previews will be available afterwards.")
        self.call(afc.pull(device_path, str(local_path), progress_bar=False), timeout=3600)

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
                "name": "iPhone",
                "model": "",
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

        # The two failures users actually hit are an untrusted/locked phone and a
        # pre-iOS-13 device that needs the developer disk image. Turn the raw
        # exception into something actionable instead of surfacing a traceback.
        try:
            self._lockdown = await create_using_usbmux(serial=chosen["udid"])
            self._afc = await AfcService(lockdown=self._lockdown).__aenter__()
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            low = detail.lower()
            if self._lockdown is not None:
                try:
                    await self._lockdown.close()
                except Exception:
                    pass
            self._lockdown = None
            self._afc = None
            if "password" in low or "trust" in low or "pair" in low or "not paired" in low:
                raise DeviceError(
                    "The iPhone has not trusted this PC yet. Unlock the phone, "
                    "tap Trust on the prompt, then press Connect again. If no "
                    f"prompt appears, unplug and replug the cable. Detail: {detail}") from exc
            if "developer" in low or "disk image" in low or "dvt" in low:
                raise DeviceError(
                    "This iOS version needs Apple's developer disk image before "
                    f"files can be read. Detail: {detail}") from exc
            if "busy" in low or "invalid service" in low or "concurrent" in low:
                raise DeviceError(
                    "The phone is busy (another app is using it). Close iTunes, "
                    "Photos, QuickTime, or any other tool holding the device, then "
                    f"retry. Detail: {detail}") from exc
            raise DeviceError(f"Could not open the iPhone's file service. Detail: {detail}") from exc
        self.udid = chosen["udid"]
        info = dict(chosen)
        try:
            info["name"] = await self._lockdown.get_value(key="DeviceName") or chosen["name"]
            info["ios"] = await self._lockdown.get_value(key="ProductVersion") or ""
            info["model"] = await self._lockdown.get_value(key="ProductType") or chosen["model"]
        except Exception:
            pass
        self.info = info
        # Older UDIDs may be hyphenated in usbmuxd but not in Lockdown. Always
        # use the device's canonical identifier for destination folder stability.
        try:
            self.udid = self._lockdown.udid or self.udid
            self.info["udid"] = self.udid
        except Exception:
            pass
        return info

    async def _disconnect(self, afc=None) -> None:
        afc = afc if afc is not None else self._afc
        lockdown = self._lockdown
        self._afc = None
        self._lockdown = None
        try:
            if afc is not None and not isinstance(afc, _FakeAfc):
                await afc.__aexit__(None, None, None)
        finally:
            if lockdown is not None:
                await lockdown.close()

    async def _inventory(self, root: str) -> list[dict]:
        afc = self._afc
        items: list[dict] = []
        failures: list[str] = []

        async def rec(path: str) -> None:
            try:
                entries = await afc.listdir(path)
            except Exception as exc:
                raise DeviceError(f"cannot read {path}: {exc}") from exc
            for name in entries:
                full = posixpath.join(path, name)
                try:
                    if await afc.isdir(full):
                        await rec(full)
                        continue
                    st = await afc.stat(full)
                except Exception as exc:
                    failures.append(f"{full}: {exc}")
                    continue
                if Path(name).suffix.lower() not in MEDIA_EXT:
                    continue
                mtime = st.get("st_mtime")
                # pymobiledevice3 returns a UTC datetime for AFC mtimes. Never
                # interpret it in the PC's timezone or shift it by that offset.
                if isinstance(mtime, datetime):
                    if getattr(mtime, "tzinfo", None) is None:
                        mtime = mtime.replace(tzinfo=timezone.utc)
                    epoch = int(mtime.timestamp())
                else:
                    epoch = int(mtime or 0)
                items.append({
                    "path": full,
                    "name": name,
                    "size": int(st["st_size"]),
                    "mtime": epoch,
                })

        await rec(root)
        if failures:
            raise DeviceError("Inventory incomplete; reconnect and retry. "
                              + " | ".join(failures[:5]))
        items.sort(key=lambda x: x["mtime"], reverse=True)
        return items
