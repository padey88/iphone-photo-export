# Changelog

## 1.0.2

### Fixed
- Refresh device metadata before each transfer so files changed after browsing are not skipped.
- Verify SHA-256 for the current export, including local tampering and missing hashes.
- Preserve successful export history across filtered runs without masking current failures.
- Serialize exports, reject duplicate submissions, and block disconnect/destination changes mid-transfer.
- Surface incomplete device inventories instead of treating them as empty libraries.
- Close device connections on connect failure and disconnect; use canonical device identifiers.
- Raise an existing native window on a second launch.
- Wait for active exports during shutdown and uninstall rather than force-killing the app.
- Fix the last-30-days preset to cover 30 days rather than only today.

### Changed
- Pin runtime and build dependencies for reproducible Windows builds.
- Require a working bundled ffmpeg during the build.
- Document the exact verification boundary: local post-transfer hashes are not independent live-device hashes.

## 1.0.1

- Initial single-file Windows installer and native desktop app.
