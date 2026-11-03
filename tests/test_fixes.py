#!/usr/bin/env python3
"""Regression tests for the pre-release fixes — no phone, no window needed.

Covers:
  * preview-cache budget (browsing a big library must not fill C:)
  * a dead export thread must not block every future export
  * a live export must still block a second one
  * /api/ping and /api/state both feed the browser-mode idle watchdog
  * single-instance detection

Run: python tests/test_fixes.py
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

tmp = Path(tempfile.mkdtemp(prefix="ipx-fixes-"))
fake = tmp / "device"
dest = tmp / "dest"
dest.mkdir(parents=True)
os.environ["IPHONE_EXPORT_FAKE"] = str(fake)
os.environ["IPHONE_EXPORT_DEST"] = str(dest)
os.environ["IPHONE_EXPORT_CACHE"] = str(tmp / "cache")

from PIL import Image  # noqa: E402

dcim = fake / "DCIM" / "100APPLE"
dcim.mkdir(parents=True)
for i in range(3):
    Image.new("RGB", (400, 300), (30, 90, 180)).save(dcim / f"IMG_{i}.JPG")

import app as webapp  # noqa: E402

failures = []


def check(cond, label):
    print(("  ok   " if cond else "  FAIL ") + label)
    if not cond:
        failures.append(label)


client = webapp.app.test_client()
client.post("/api/connect", json={})

print("preview cache budget")
small = 1024 * 1024
for i in range(6):
    p = webapp.MEDIA / f"seed{i}.bin"
    p.write_bytes(b"x" * small)
    # stagger mtimes so "oldest first" is deterministic
    os.utime(p, (time.time() - (10 - i) * 60, time.time() - (10 - i) * 60))
orig_budget = webapp.CACHE_BUDGET_MB
webapp.CACHE_BUDGET_MB = 3
webapp.cache_gc()
remaining = [p for p in webapp.MEDIA.iterdir() if p.is_file()]
total = sum(p.stat().st_size for p in remaining)
check(total <= 3 * small, f"cache trimmed to {total / small:.1f}MB under a 3MB budget")
check(len(remaining) < 6, "oldest cached files were evicted")
check(all("seed0" not in p.name and "seed1" not in p.name for p in remaining),
      "the two oldest entries are the ones dropped")
webapp.CACHE_BUDGET_MB = orig_budget
for p in list(webapp.MEDIA.iterdir()):
    p.unlink(missing_ok=True)

print("export concurrency")
state_path = "/DCIM/100APPLE/IMG_0.JPG"


class _Dead:
    def is_alive(self):
        return False


webapp.STATE["job"] = {"state": "running", "total": 1, "done": 0}
webapp.STATE["job_thread"] = _Dead()
r = client.post("/api/export", json={"paths": [state_path]})
check(r.status_code == 200,
      f"a dead export thread does not block new exports (got {r.status_code})")
st = {"state": "unknown"}
for _ in range(80):
    st = client.get("/api/export/status").get_json()
    if st["state"] != "running":
        break
    time.sleep(0.1)
check(st["state"] == "done", f"the replaced export actually ran (state={st['state']})")


class _Alive:
    def is_alive(self):
        return True


webapp.STATE["job"] = {"state": "running"}
webapp.STATE["run_id"] = "test-active-export"
webapp.STATE["job_thread"] = _Alive()
r = client.post("/api/export", json={"paths": [state_path]})
check(r.status_code == 409, f"a live export still blocks a second one (got {r.status_code})")
webapp.STATE["job"] = None
webapp.STATE["job_thread"] = None
webapp.STATE["run_id"] = None
webapp.STATE["job_id"] = None

print("browser-mode idle watchdog")
webapp.STATE["last_ping"] = 0
r = client.get("/api/ping")
check(r.status_code == 200 and webapp.STATE["last_ping"] > 0, "/api/ping records a heartbeat")
webapp.STATE["last_ping"] = 0
client.get("/api/state")
check(webapp.STATE["last_ping"] > 0, "/api/state also records a heartbeat")

print("single-instance detection")
import socket  # noqa: E402

import desktop  # noqa: E402

with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    unused_port = s.getsockname()[1]
check(desktop.existing_instance(unused_port) is False,
      "nothing listening -> not an existing instance")

# bring up a real server and confirm the probe sees it
srv_port = desktop.free_port(0)
desktop.start_server(srv_port)
ready = desktop.wait_ready(srv_port, timeout=25)
check(ready, "temporary server came up for the probe")
check(desktop.existing_instance(srv_port) is True, "existing instance detected")
check(desktop.free_port(8765) > 0, "free_port returns a usable port")

print()
if failures:
    print(f"FAILURES ({len(failures)}):")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("ALL FIX CHECKS PASSED")
