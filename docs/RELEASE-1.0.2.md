# iPhone Photo Export 1.0.2

Single-file Windows installer with the Python runtime, USB device-support installer, ffmpeg, and native desktop shell included.

## Fixed

- Files changed on the iPhone after browsing are freshly checked before transfer.
- Current exports verify file size and SHA-256; local tampering is reported.
- Filtered exports retain successful history without masking failed current runs.
- Duplicate exports and device disconnects during a transfer are blocked.
- Incomplete device inventories and connection failures are surfaced clearly.
- Existing native windows are raised on a second launch.
- Shutdown and uninstall wait for active exports instead of killing them.
- The last-30-days preset now covers 30 days.

## Verification

- Local engine, GUI, lifecycle, and integrity regression suites passed.
- Windows frozen self-test passed.
- Windows fake-device export, install, graceful shutdown, and uninstall checks are recorded in `docs/VERIFICATION.md`.
- No physical iPhone was attached to the build VM. Real USB/AFC behavior and HEIC samples still require a physical-device acceptance test before trusting a large library.

The app is read-only on the device. Keep a second backup and play exported videos before deleting anything from the phone.

SHA-256 for the attached installer is listed below and in the README.
