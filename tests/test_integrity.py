"""Regression tests for export integrity and concurrent request handling."""
import asyncio
import csv
import os
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

import app as webapp
import exporter
import filters
from device import DeviceBridge, DeviceError, _FakeAfc


@pytest.fixture()
def roll(tmp_path):
    root = tmp_path / "device"
    dcim = root / "DCIM" / "100APPLE"
    dcim.mkdir(parents=True)
    (dcim / "IMG_1.JPG").write_bytes(b"first-version")
    (dcim / "IMG_2.JPG").write_bytes(b"second-version")
    for path in dcim.iterdir():
        os.utime(path, (1700000000, 1700000000))
    bridge = DeviceBridge()
    with patch.dict(os.environ, {"IPHONE_EXPORT_FAKE": str(root)}):
        bridge.fake_root = str(root)
        bridge.connect()
        inventory = bridge.inventory()
        yield bridge, inventory, tmp_path / "out"
    bridge.disconnect()


def test_export_refreshes_device_metadata_and_detects_same_size_edit(roll):
    bridge, inventory, dest = roll
    first = asyncio.run(exporter.copy_items(bridge.afc(), inventory, dest))
    exporter.write_manifest(first["rows"], dest / "history" / "first.csv")
    path = Path(bridge.fake_root) / "DCIM/100APPLE/IMG_1.JPG"
    # Same byte count, newer mtime: must not be silently resumed.
    path.write_bytes(b"FIRST-CHANGED")
    os.utime(path, (1700000100, 1700000100))
    second = bridge.export_items(inventory, dest, lambda p: None, lambda p, e: None)
    assert second["copied"] == 1
    assert second["resumed"] == 1
    assert second["failed"] == 0
    local = exporter.local_path_for(dest, "/DCIM/100APPLE/IMG_1.JPG")
    assert local.read_bytes() == b"FIRST-CHANGED"
    verification = exporter.verify_items(inventory, dest, second["rows"])
    assert verification["ok"]


def test_export_detects_local_tampering(roll):
    bridge, inventory, dest = roll
    result = bridge.export_items(inventory, dest, lambda p: None, lambda p, e: None)
    local = exporter.local_path_for(dest, inventory[0]["path"])
    local.write_bytes(b"corrupt" + local.read_bytes()[7:])
    check = exporter.verify_items(inventory, dest, result["rows"])
    assert not check["ok"]
    assert check["hash_mismatch"] == [inventory[0]["path"]]


def test_filtered_export_preserves_history_without_hiding_failed_retry(roll):
    bridge, inventory, dest = roll
    first = bridge.export_items(inventory[:1], dest, lambda p: None, lambda p, e: None)
    exporter.write_manifest(first["rows"], dest / "history" / "one.csv")
    assert set(exporter.already_exported_index(dest)) == {inventory[0]["path"]}
    second = bridge.export_items(inventory[1:], dest, lambda p: None, lambda p, e: None)
    exporter.write_manifest(second["rows"], dest / "history" / "two.csv")
    assert set(exporter.already_exported_index(dest)) == {i["path"] for i in inventory}
    failed = [list(first["rows"][0][:5]) + ["FAILED: cable unplugged"]]
    exporter.write_manifest(failed, dest / "manifest.csv")
    assert not exporter.verify_items(inventory[:1], dest, failed)["ok"]


def test_device_path_cannot_escape_destination(tmp_path):
    with pytest.raises(ValueError):
        exporter.local_path_for(tmp_path, "/DCIM/../../outside.jpg")


def test_one_month_preset_uses_calendar_month():
    presets = filters.suggest_presets(datetime(2026, 11, 3))
    assert next(p for p in presets if p["id"] == "before_1_month")["spec"]["date"] == "2026-10-03"


def test_inventory_failure_is_not_an_empty_library(roll):
    bridge, _, _ = roll
    with patch.object(bridge.afc(), "listdir", side_effect=OSError("USB disconnected")):
        with pytest.raises(DeviceError, match="cannot read"):
            bridge.inventory()


def test_disconnect_is_blocked_during_export(roll):
    bridge, inventory, dest = roll
    entered = threading.Event()
    release = threading.Event()

    original_copy = exporter.copy_items

    async def slow_copy(*args, **kwargs):
        entered.set()
        await asyncio.to_thread(release.wait, 5)
        return await original_copy(*args, **kwargs)

    with patch("device.exporter.copy_items", slow_copy):
        worker = threading.Thread(target=bridge.export_items,
                                  args=(inventory, dest, lambda p: None, lambda p, e: None))
        worker.start()
        assert entered.wait(3)
        with pytest.raises(DeviceError, match="export"):
            bridge.disconnect()
        release.set()
        worker.join(5)
    assert not worker.is_alive()


def test_export_lock_rejects_double_submission(tmp_path):
    device = tmp_path / "device"
    (device / "DCIM" / "100APPLE").mkdir(parents=True)
    (device / "DCIM/100APPLE/IMG_1.JPG").write_bytes(b"image")
    with patch.dict(os.environ, {"IPHONE_EXPORT_FAKE": str(device),
                                 "IPHONE_EXPORT_DEST": str(tmp_path / "dest"),
                                 "IPHONE_EXPORT_CACHE": str(tmp_path / "cache")}):
        with patch.object(webapp.bridge, "fake_root", str(device)):
            client = webapp.app.test_client()
            assert client.post("/api/connect", json={}).status_code == 200
        with webapp.LOCK:
            webapp.STATE["run_id"] = "in-flight"
            webapp.STATE["job"] = {"id": "in-flight", "state": "running"}
        try:
            response = client.post("/api/export", json={"paths": ["/DCIM/100APPLE/IMG_1.JPG"]})
            assert response.status_code == 409
            assert client.post("/api/disconnect", json={}).status_code == 409
            assert client.post("/api/config", json={"dest": str(tmp_path / "other")}).status_code == 409
        finally:
            with webapp.LOCK:
                webapp.STATE["run_id"] = None
                webapp.STATE["job"] = None
        webapp.bridge.disconnect()


def test_age_presets_and_custom_before_filter():
    presets = filters.suggest_presets(datetime(2026, 3, 31))
    age = presets[:5]
    assert [p["label"] for p in age] == [
        "Before 1 month ago", "Before 3 months ago", "Before 6 months ago",
        "Before 9 months ago", "Before 1 year ago",
    ]
    assert [p["spec"]["date"] for p in age] == [
        "2026-02-28", "2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31",
    ]
    assert all(p["spec"]["date_mode"] == "older" for p in age)

    def item(name, date):
        return {"path": name, "name": name, "mtime": datetime.fromisoformat(date).timestamp(),
                "size": 1, "ext": ".jpg", "kind": "photo", "exported": False,
                "mb": 0, "dir": "/DCIM", "stem": name}

    items = [item("old.JPG", "2025-01-01"), item("cutoff.JPG", "2025-06-30"),
             item("new.JPG", "2026-01-01")]
    picked = filters.apply_filters(items, {"date_mode": "older", "date": "2025-06-30",
                                          "keep_pairs": False})
    assert [i["name"] for i in picked] == ["old.JPG"]


def test_device_utc_naive_datetime_is_not_shifted(roll):
    bridge, _, _ = roll
    naive = datetime(2023, 11, 14, 22, 13, 20)
    with patch.object(bridge.afc(), "stat", return_value={"st_size": 1, "st_mtime": naive}):
        with patch.object(bridge.afc(), "listdir", return_value=["x.JPG"]):
            with patch.object(bridge.afc(), "isdir", return_value=False):
                items = bridge.inventory()
    assert items[0]["mtime"] == int(naive.replace(tzinfo=__import__("datetime").timezone.utc).timestamp())
