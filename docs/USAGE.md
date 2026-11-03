# App usage flow

1. Launch the app. It opens the native window when WebView2 is available, otherwise the browser.
2. Connect a trusted, unlocked iPhone by USB. The status shows `iPhone not detected`, or the
   device model, iOS version and iPhone device name. This is not the Windows username.
3. Choose the export directory. **Save as default** persists it for future launches;
   **Add favorite** saves it to the folder picker. Favorites can be removed without deleting files.
4. Filter by age preset, custom before-date, type, size or export status. Category view defaults
   to Photos and also offers Videos and Live Photos; All media removes the type restriction.
   Details list and thumbnail views share the same selection. Thumbnail click enlarges/plays;
   list double-click opens the in-app preview and complete available metadata.
5. Select all filtered objects with the header checkbox, or use Ctrl-click and Shift-click.
   With focus in the details list, Shift+Up/Down and Shift+PageUp/PageDown extend the range.
6. Choose Source folders, Category folders, or Date (YYYY-MM), then Export selected. Existing
   verified files resume at their recorded paths. New structured exports use collision-safe names.
7. Click Verify. The app rechecks the exact current selection against that run's size and SHA-256
   manifest. Verification uses the actual recorded local path for every file.
8. Optionally delete the verified originals. Type `DELETE` in the explicit confirmation dialog.
   The server freshly verifies every selected export and rechecks each original's size/mtime before
   removing exactly one file below `/DCIM`. Failed or changed originals are left in place and
   reported. Successful deletions are recorded in `CLEANUP.txt`.

## Metadata boundary

AFC exposes filename, device path, modified time, size, media category and Live Photo pairing.
It does not expose Photos album membership or EXIF creation/GPS directly. Preview loads available
EXIF fields from the cached image, including capture time and GPS when present. Album membership
remains explicitly unavailable. Video EXIF is not extracted. This prevents blank fields from being
mistaken for known metadata.

## Cleanup boundary

The deletion path is implemented and tested with an isolated synthetic device. It has not been
tested with a physical iPhone. iOS Photos may retain deleted items in Recently Deleted or restrict
camera-roll deletion. Do not treat this as production-safe until a sacrificial physical-device test
confirms deletion behavior and the user has verified a second backup.
