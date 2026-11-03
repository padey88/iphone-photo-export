# Push the working tree to the Windows build VM (run from the Linux host).
#   ./build/ship.sh            # sync sources only
#   ./build/ship.sh --build    # sync, then run build.ps1 remotely
set -euo pipefail
VM="${VM:-fadhilrashid@192.168.100.99}"
DEST="${DEST:-C:/build/ipe/src}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EXCLUDES=(--exclude=.venv --exclude=.venv-shot --exclude=__pycache__
          --exclude=.pytest_cache --exclude=.git --exclude=payload
          --exclude=installer --exclude=bin --exclude=.demo-iphone)

echo "==> syncing $ROOT -> $VM:$DEST"
# PowerShell native-command stdin can decode a pipe as text and corrupt a tar
# archive. scp transports the archive byte-for-byte before extracting it.
ARCHIVE="$(mktemp "${TMPDIR:-/tmp}/iphone-export-src.XXXXXX.tgz")"
trap 'rm -f "$ARCHIVE"' EXIT
tar czf "$ARCHIVE" -C "$ROOT" "${EXCLUDES[@]}" .
scp -q "$ARCHIVE" "$VM:C:/build/ipe/src.tgz"
ssh "$VM" "powershell -NoProfile -Command \"New-Item -ItemType Directory -Force -Path '$DEST' | Out-Null; tar -xzf C:/build/ipe/src.tgz -C '$DEST'; if (\$LASTEXITCODE -ne 0) { exit \$LASTEXITCODE }\""

echo "==> syncing ffmpeg binaries ($(du -sh "$ROOT/bin" 2>/dev/null | cut -f1 || echo none))"
if [ -d "$ROOT/bin" ]; then
  ssh "$VM" "powershell -NoProfile -Command \"New-Item -ItemType Directory -Force -Path '$DEST/bin' | Out-Null\""
  for f in "$ROOT"/bin/*; do
    [ -f "$f" ] && scp -q "$f" "$VM:$DEST/bin/"
  done
fi

if [ "${1:-}" = "--build" ]; then
  echo "==> building on the VM"
  ssh "$VM" "powershell -NoProfile -ExecutionPolicy Bypass -File C:\\build\\ipe\\src\\build\\build.ps1"
fi
echo "==> done"
