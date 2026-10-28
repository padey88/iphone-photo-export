# iPhone photo/video export (verified, resumable)

Pulls the camera roll (`/DCIM`) off a USB-connected iPhone to a PC, then proves the copy
is complete before you delete anything on the phone. Read-only on the device: it never
deletes, moves or renames anything on the iPhone.

Built for the case where iCloud is on the free 5 GB tier, so nothing is in the cloud and
the phone is the only copy.

## Quick start

**Prerequisites:** Python 3.11+, iTunes or the Apple Devices app installed (provides the
Windows USB drivers), and a direct USB cable — no hub or dock.

**Setup:**
```
pip install pymobiledevice3
```

**Scripts:** `iphone_export.py` (inventory, copy, SHA-256 manifest, verification, resumable,
read-only) and `test_export.py` (test suite, no phone needed).

**Workflow:**

1. Run `--dry-run` first to check the inventory and total size.
   ```
   python iphone_export.py --dest D:\iphone-backup --dry-run
   ```
2. Run the export.
   ```
   python iphone_export.py --dest D:\iphone-backup
   ```
3. Confirm `VERIFY.txt` shows `0` for failed, missing and size mismatch.
4. Play 5 random videos from the PC copy.
5. Copy the folder to an external drive — a second copy.
6. Delete photos on the iPhone in batches, then **empty Recently Deleted**
   (Photos > Albums > Recently Deleted > Delete All). The space is not freed until you do.

## What it does

- Recursive inventory of `/DCIM` (photos, videos, HEIC, Live Photo `.MOV` pairs) before copying.
- Copies to `<dest>/<device-UDID>/`, skipping files already present at the right size.
- Writes `manifest.csv` with device path, size, mtime, SHA-256 and status per file.
- Writes `VERIFY.txt` with counts and any missing/mismatched files.
- Re-running after a crash, unplug or timeout resumes instead of starting over.
- Re-downloads any local file whose size does not match the device (self-healing).

## What it does not do

- Does not touch WhatsApp media, other apps' containers, or iCloud-only items.
- Does not delete from the phone. That stays a manual, deliberate step (see below).
- Does not read "Recently Deleted" items.

## Windows setup (one time)

1. Install **Python 3.11+** from python.org (tick "Add python.exe to PATH").
2. Install Apple's drivers: **iTunes from apple.com** (not the Microsoft Store build) or the
   **Apple Devices** app. This creates the "Apple Mobile Device Support" service.
3. Open Command Prompt and install the engine:
   ```
   pip install pymobiledevice3
   ```
4. Plug the iPhone in **directly** (no hub, no dock), unlock it, and tap **Trust**.
   Keep the screen unlocked during the transfer; set Settings > Display & Brightness >
   Auto-Lock to **Never** while copying.

## Workflow per phone

```
python iphone_export.py --dest D:\iphone-backup --dry-run    :: inventory + size only
python iphone_export.py --dest D:\iphone-backup              :: copy
```

Two phones plugged in at once? List them, then pass the UDID:

```
python iphone_export.py --dest D:\iphone-backup --dry-run
python iphone_export.py --dest D:\iphone-backup --udid 00008101-001A2C3E0E91801E
```

Lightning iPhones typically move 1-3 GB/min, so a 100 GB library is roughly 1-2 hours.
Interrupt it any time; re-running resumes.

## Before deleting anything on the phone

All four must be true:

1. `VERIFY.txt` shows `failed: 0`, `missing: 0`, `size mismatch: 0`.
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

## Tests

```
python test_export.py
```

Runs the whole pipeline against a fake device: inventory, filtering, copy, resume,
manifest, and re-fetch of a truncated file. No phone required.
