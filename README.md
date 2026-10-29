# iPhone photo/video export (verified, resumable, with GUI)

Pulls the camera roll (`/DCIM`) off a USB-connected iPhone to a PC, then proves the copy
is complete before you delete anything on the phone. Read-only on the device: it never
deletes, moves or renames anything on the iPhone.

Built for the case where iCloud is on the free 5 GB tier, so nothing is in the cloud and
the phone is the only copy.

Two front ends, one engine:

- **GUI** — `run.bat` (Windows) opens a local app in the browser: filter, preview, pick, export.
- **CLI** — `iphone_export.py --dest <folder>` for scripted or unattended runs.

## Quick start (GUI, Windows)

1. Install **Python 3.11+** from python.org (tick "Add python.exe to PATH").
2. Install Apple's drivers: **iTunes from apple.com** (not the Microsoft Store build) or the
   **Apple Devices** app. This creates the "Apple Mobile Device Support" service.
3. Plug the iPhone in **directly** (no hub, no dock), unlock it, tap **Trust**.
4. Double-click **`run.bat`**. First run installs dependencies, then opens
   `http://127.0.0.1:8765/`.
5. Click **Connect iPhone**, filter, select, **Export**.

The app runs only on `127.0.0.1` — it is not reachable from the network.

## GUI: filters

| Filter | Use it for |
|---|---|
| **Older than a date** | The main case: "everything older than 1 Jan 2026" |
| **Between two dates** | One year or one month at a time |
| **Newer than a date** | Only recent files (checking the latest holiday) |
| **Not yet exported** | Incremental runs — only files the PC does not have |
| **Already exported** | Finding what to delete on the phone |
| **Type** (photo / Live Photo / video / screen recording / screenshot) | Skip screenshots, or grab only videos |
| **Size min–max MB** | Find the 200 MB videos eating the space |
| **Filename search** | Locate a specific `IMG_1234` |
| **Keep Live Photo pairs together** | Never split a `.HEIC`/`.JPG` still from its `.MOV` clip |

Presets cover the common combinations in one click. Filters compose: "older than 1 Jan 2026
+ not yet exported + videos" is a valid selection.

## GUI: preview and selection

- Click any file to open it in the right-hand panel: full image, or a **playable video**.
- **Include / Exclude** toggles that single file, so you can drop the one bad clip out of a
  batch of 200.
- Grid thumbnails load lazily, three at a time. Video cards show a 🎬 placeholder instead of
  a thumbnail on purpose: pulling a 300 MB video off the phone just to draw a 1 cm thumbnail
  is not worth it. Clicking a video previews it (a confirmation appears above 150 MB).
- **Select all shown** applies to the current filter, not the whole library.

## CLI

```
python iphone_export.py --dest D:\iphone-backup --dry-run    # inventory + size only
python iphone_export.py --dest D:\iphone-backup              # copy
```

Two phones plugged in at once? Pass the UDID:

```
python iphone_export.py --dest D:\iphone-backup --udid 00008101-001A2C3E0E91801E
```

Lightning iPhones typically move 1–3 GB/min, so a 100 GB library is roughly 1–2 hours.
Interrupt it any time; re-running resumes.

## What the engine does

- Recursive inventory of `/DCIM` (photos, videos, HEIC, Live Photo pairs) before copying.
- Copies to `<dest>/<device-UDID>/`, skipping files already present at the right size.
- Writes `manifest.csv` with device path, size, mtime, SHA-256 and status per file.
- Writes `VERIFY.txt` with counts and any missing/mismatched files.
- Re-running after a crash, unplug or timeout resumes instead of starting over.
- Re-downloads any local file whose size does not match the device (self-healing).

## What it does not do

- Does not touch WhatsApp media, other apps' containers, or iCloud-only items.
- Does not delete from the phone. That stays a manual, deliberate step (see below).
- Does not read "Recently Deleted" items.
- Cannot filter by favourite, album, camera (front/rear) or blur: iOS does not expose that
  metadata through the camera-roll file system. Only date, name, size, format and type.

## Before deleting anything on the phone

All four must be true:

1. `VERIFY.txt` shows `failed: 0`, `missing: 0`, `size mismatch: 0` (the GUI shows this as
   "Export verified").
2. You played 5 random videos from the copied folder on the PC (catches truncated files
   that still have the right byte count).
3. The folder exists on a **second** drive (external HDD/SSD). One copy is not a backup.
4. You know whether iCloud Photos is on. With it **on**, deleting on the phone deletes from
   iCloud too, so the PC copy becomes the only copy.

## Deleting on the phone (frees the space)

1. Photos > Library > **Select** > drag-select the range > trash > **Delete**.
2. Photos > Albums > **Recently Deleted** > **Delete All**. Until you do this, the space is
   not actually freed (iOS keeps deleted items for 30 days).
3. Settings > General > iPhone Storage to confirm the space is back.

Delete in batches (a month or a year at a time) and re-check the copy after each batch.

## Files

```
app.py              Flask app + API (local web GUI)
device.py           long-lived AFC connection behind a sync facade
exporter.py         copy / verify / manifest core shared by GUI and CLI
filters.py          date, type, size, status, name filters + Live Photo pairing
iphone_export.py    CLI front end
templates/index.html  the whole UI (single file, no build step)
run.bat             Windows launcher
tests/              fake-device fixtures + tests
```

## Tests

```
python test_export.py          # CLI pipeline: inventory, copy, resume, truncated-file heal
python tests/test_gui.py       # GUI API: filters, preview, thumbnails, export, resume
python tests/make_fake_device.py /tmp/fake_iphone    # demo data for the GUI
```

Both run against a fake device — no phone required. To try the GUI without a phone:

```
set IPHONE_EXPORT_FAKE=C:\tmp\fake_iphone
python app.py
```
