# Changelog

All notable changes to iPhone Photo Export.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Age-based date presets (older than 1 / 2 / 5 years) using calendar-month
  cutoffs with month-end handling, plus an explicit user-chosen **before this
  date** bound.
- Alternative export layouts: `category` (Photos, Live Photos, Videos, Screen
  Recordings, Screenshots, Live Photo Videos, Other) and `date` (`YYYY-MM/`),
  alongside the default `source` layout that mirrors the device's DCIM tree.
- Collision handling: a second file with the same name is written as
  `name (2).ext` instead of overwriting the first.
- Single-file deletion on the device, gated behind the verification result and
  restricted to media extensions directly under `/DCIM/` — `..`, nested paths,
  and directories are refused.

### Changed
- The export worker carries the layout parameter end to end
  (`DeviceBridge.export_items` → `copy_items` → `local_path_for`), so the layout
  decides the destination path rather than being applied after the copy.

### Notes
- Unreleased work is on `main` and **not** in the v1.0.2 installer. Device-side
  deletion in particular needs an acceptance test on a physical iPhone — the
  fake-device test path cannot prove AFC `rm_single` behaviour on real hardware.

## [1.0.2] — 2026-11-03

### Fixed
- Files changed on the iPhone after browsing are re-checked before transfer, so
  a photo edited between preview and export is not silently skipped.
- The current export verifies size and SHA-256 per file — including local
  tampering and a missing hash — and reports the result instead of assuming
  success.
- Filtered exports keep the successful history from earlier runs without
  masking failures in the current run.
- Exports are serialized: duplicate submissions are rejected, and disconnect or
  destination changes are blocked mid-transfer.
- An incomplete device inventory is surfaced as an error instead of being
  treated as an empty library.
- Device connections are closed on connect failure and on disconnect; devices
  are identified canonically so a reconnect does not look like a new device.
- A second launch raises the existing native window instead of starting a
  parallel instance.
- Shutdown and uninstall wait for active exports rather than force-killing the
  app mid-copy.
- The last-30-days preset actually covers 30 days; it previously covered only
  the current day.

### Changed
- Runtime and build dependencies pinned for reproducible Windows builds.
- The build now fails if the bundled ffmpeg is not working, instead of shipping
  an installer whose video path is broken.
- Documented the verification boundary precisely: local post-transfer hashes are
  not independent live-device hashes.

## [1.0.1] — 2026-11-03

### Fixed
- **Single instance.** Probing the default port before choosing an ephemeral one
  means a second launch hands off to the running app instead of starting a
  parallel server with its own cache.
- **Browser fallback** exits when the UI stops pinging — previously it blocked
  forever with no window and no way to quit — and honours `--open-browser`
  without opening a window first.
- **Preview cache** is capped (default 3000 MB, 14-day expiry) instead of
  growing without limit as a library is browsed.
- **Export failure recovery** trusts the worker thread rather than a state flag,
  so a crashed export no longer blocks every future one; a mid-copy mass failure
  now warns clearly.
- Device connect errors are mapped to actionable messages: untrusted, locked,
  busy, or missing developer disk image.
- **Installer.** `msiexec` no longer exits 1622 from an empty `{log}` constant
  under `/VERYSILENT`, and the Apple driver install runs from `ssPostInstall` so
  a driver failure reports a warning instead of aborting setup after the payload
  is already copied (exit 3010 — reboot required — counts as success). The empty
  `drivers\` folder left behind in `{app}` is gone.

### Added
- `tests/test_fixes.py` covering the above, plus `docs/VERIFICATION.md` stating
  what is verified and what is not.

## [1.0.0] — 2026-11-03

### Added
- First public release: a single-file Windows installer containing the Python
  runtime, Flask, `pymobiledevice3`, Pillow + pillow-heif, ffmpeg 9.0, the UI,
  the native desktop shell, and Apple's `AppleMobileDeviceSupport64.msi`
  (installed silently, and only when the service is missing).
- USB camera-roll offload with filtering by date, type, and size, thumbnail
  preview, and per-file include/exclude.
- SHA-256 verification of every exported file against the manifest, written to
  `VERIFY.txt`.
- Read-only on the device: it never deletes, moves, or renames anything on the
  iPhone.
- Resumable, self-healing export — re-running skips files already transferred
  and verified.

### Notes
- Unsigned build. Windows SmartScreen warns on launch; the release page carries
  the SHA-256 so you can confirm the download.
- Apple's driver is redistributed from Apple's own iTunes package under Apple's
  terms. iTunes itself is not installed.

[Unreleased]: https://github.com/padey88/iphone-photo-export/compare/v1.0.2...HEAD
[1.0.2]: https://github.com/padey88/iphone-photo-export/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/padey88/iphone-photo-export/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/padey88/iphone-photo-export/releases/tag/v1.0.0
