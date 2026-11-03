# Verification status

What has actually been executed, what has not, and why. Updated with each release.

Last run: 2026-11-03, Windows 11 build 26200, clean VM, installer v1.0.1
(`iPhonePhotoExport-1.0.1-Setup.exe`, SHA-256 `a7b06a5b...18ec5a0`).

## Verified by execution

### Build and packaging

| Check | How | Result |
|---|---|---|
| PyInstaller bundle builds | `build.ps1` on Windows | pass |
| Frozen exe starts and serves | `--selftest` | 12/12 checks pass |
| Bundled Python 3.11 runtime | `--selftest` | 3.11.15 |
| Flask importable | `--selftest` | 3.1.3 |
| pymobiledevice3 importable | `--selftest` | 11.49.2 |
| `usbmux` + `AfcService` importable | `--selftest` | ok |
| Pillow decodes images | `--selftest` | 13.0.0 |
| `pillow-heif` registers | `--selftest` | registered |
| Bundled ffmpeg runs | `--selftest` | 9.0.2-essentials |
| Templates present in bundle | `--selftest` | 24042 bytes |
| Live HTTP round trip | `--selftest` | `/api/state` 200 |
| Inno Setup compiles | `ISCC.exe` | pass, 144 MB |

### Installer behaviour

| Check | How | Result |
|---|---|---|
| Silent install | `/VERYSILENT /SUPPRESSMSGBOXES` | exit 0 |
| Files land in `C:\Program Files\iPhone Photo Export` | post-install inspection | present |
| Apple driver installs when missing | `sc query` after install | `Apple Mobile Device Service` RUNNING |
| Driver skipped when present | `NeedsAppleDriver` check on reinstall | skipped, logged |
| No leftover `drivers\` folder in `{app}` | post-install inspection | absent |
| Uninstall removes the app | `unins000.exe /VERYSILENT` | exit 0, directory gone |
| Uninstall leaves the shared driver | `sc query` after uninstall | still present (correct) |
| Installed exe re-passes selftest | `--selftest` from install dir | 12/12 pass |

### Runtime behaviour

| Check | How | Result |
|---|---|---|
| Native window opens | scheduled task in the interactive session; window title read back | `iPhone Photo Export` |
| Server binds loopback only | `netstat` / config | `127.0.0.1` |
| Second launch does not double-start | launch twice, count listeners | 1 listener, second process exits |
| Browser fallback exits when unused | `browser_mode(idle_timeout=6)` | exits after grace period, rc 0 |
| Browser fallback stays up while pinging | 95 pings over 95s | still running, exits after pings stop |
| Preview cache respects budget | seed 6×1MB, budget 3MB | trimmed to 2.0MB, oldest evicted |
| Dead export thread does not wedge | fake `is_alive()=False` | new export accepted (200) |
| Live export still blocks a second | fake `is_alive()=True` | 409 |
| Heartbeats from `/api/ping` and `/api/state` | state inspection | recorded |

### Engine and API (fake device)

| Check | How | Result |
|---|---|---|
| Recursive `/DCIM` inventory | `test_export.py` | pass |
| Media filtering | `test_export.py` | pass |
| Copy + SHA-256 manifest | `test_export.py` | pass |
| Resume on re-run | `test_export.py` | pass |
| Self-heal truncated file | `test_export.py` | pass |
| Verification pass | `test_export.py` | `failed=0 missing=0 mismatch=0` |
| Full GUI flow | `tests/test_gui.py` | pass |
| Live Photo pairing | `tests/test_gui.py` | still + motion clip together |
| Video poster frame | `tests/test_gui.py` | JPEG served |
| Oversized video skipped for thumbnail | `tests/test_gui.py` | 204 |
| Frozen end-to-end | `verify_frozen.ps1` | `safe_to_delete=True` |
| Release download integrity | re-download the published asset | SHA-256 matches |

## Not verified — and why

| Gap | Why not | Risk | Mitigation |
|---|---|---|---|
| **Real iPhone connect / AFC read** | No iPhone was attached to the build VM; `list_devices()` returned 0 devices | The core path is untested against real hardware | `pymobiledevice3` is a mature, widely used library and the AFC calls are the documented API. Still: **try the app on one phone before trusting a large library to it.** |
| **Trust prompt flow** | Requires a physical device | First-run friction may differ per iOS version | Connect errors are now mapped to actionable messages (untrusted / busy / developer image) |
| **HEIC decode from a real iPhone** | No real `.HEIC` sample; fixtures use generated JPEG | HEIC thumbnails may fail on some iOS variants | `pillow-heif` registers a full HEIF opener; failure degrades to a placeholder, not a crash |
| **Multi-GB transfer over USB** | Fake device serves from disk | Sustained throughput and USB resets untested | Resume + self-heal are tested; a dropped cable surfaces as failures with a clear note |
| **Windows 10** | Only Windows 11 26200 available | `MinVersion=10.0.17763` is declared but unexercised | No version-specific APIs are used beyond WebView2, which has a documented fallback |
| **Code signing** | No certificate | SmartScreen warns on first run | SHA-256 published in the README and release notes |
| **Antivirus false positives** | PyInstaller one-file builds are sometimes flagged | Install may be blocked on locked-down machines | Payload is a folder bundle, not one-file compressed, which lowers the rate |

## How to close the remaining gaps

The single most valuable step: run the installer on a machine with a real iPhone.

```powershell
# 1. does the phone show up at the OS level?
Get-PnpDevice -PresentOnly | Where-Object { $_.FriendlyName -match 'Apple|iPhone' }

# 2. does the bundled stack see it?
& "$env:ProgramFiles\iPhone Photo Export\iPhonePhotoExport.exe" --selftest
# then use the app: Connect -> pick 5 files -> Export -> check VERIFY.txt
```

If connect fails, the app log (`%LOCALAPPDATA%\iPhonePhotoExport\app.log`) records the raw
exception, and the UI shows the mapped, actionable message.

## Reproducing this table

```powershell
.\build\build.ps1                 # build + selftest + installer
.\build\verify_frozen.ps1         # frozen exe end to end on a fake device
python test_export.py             # engine
python tests\test_gui.py          # API flow
python tests\test_fixes.py        # cache, concurrency, watchdog, single instance
```
