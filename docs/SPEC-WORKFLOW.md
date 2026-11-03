# Spec: eight-step iPhone media workflow

## Objective
Deliver the requested launch -> connection -> destination -> filter/view -> selection ->
export -> verification -> optional cleanup flow without weakening existing transfer integrity.

## Tech stack
Python/Flask, pymobiledevice3 AFC, Pillow/pillow-heif, vanilla JavaScript/CSS, pytest.
No new runtime dependency for the core workflow.

## Commands
- `.venv-shot/bin/python -m pytest tests/test_integrity.py tests/test_workflow.py -q`
- `.venv-shot/bin/python tests/test_gui.py`
- `.venv-shot/bin/python tests/test_fixes.py`
- `.venv-shot/bin/python test_export.py`
- `node --check <extracted-template-script>`
- `build/build.ps1 -SkipFetch` on the Windows build VM for the release artifact.

## Structure
- `app.py`: preferences, metadata, verification, cleanup endpoints and export orchestration.
- `device.py`: single-file AFC deletion and metadata available from the device.
- `exporter.py`: collision-safe layouts, exact selection verification, cleanup report support.
- `filters.py`: classification unchanged except required metadata propagation.
- `templates/index.html`: guided controls, category/unified views, sortable list/grid,
  selection keyboard handling, previews and cleanup confirmation.
- `tests/`: engine regression, UI simulation and destructive-operation guards.

## Boundaries
- Always show model, iOS version and device name when supplied by Lockdown.
- Always distinguish unavailable metadata from an empty value.
- Always verify the current run's exact unique selection before enabling cleanup.
- Always require an explicit `DELETE` confirmation for original-file removal.
- Always constrain deletion to one known media file below `/DCIM`; never recursive delete.
- Ask first for real-device hardware acceptance, never simulate it as a hardware pass.
- Never delete originals automatically merely because a transfer thread completed.
- Never claim AFC supplies Photos album membership, EXIF GPS or creation time when it does not.
- Never allow manifest paths to escape the chosen export directory.

## Success criteria
- Disconnected status reads exactly `iPhone not detected`.
- Destination can be saved as default and added/removed as a favorite across restarts.
- Category view defaults to Photos, Videos or Live Photos; All shows every filtered object.
- List exposes filename, created, modified, albums, size, location and complete available
  metadata; all primary columns sort; double-click opens an in-app preview.
- Grid click enlarges/plays; Ctrl-click toggles; Shift+Up/Down/PageUp/PageDown selects ranges;
  Select all covers all filtered objects, including not-yet-rendered ones.
- Source/category/date layouts never silently overwrite same-named files.
- Verification checks exact selected paths, actual current-run rows, sizes and SHA-256.
- Cleanup is rejected for incomplete/mismatched/stale selections and wrong confirmation.
- Existing suites remain green. Hardware-dependent AFC deletion remains explicitly untested
  until exercised with a sacrificial physical-device file.
