# Push the working tree to the Windows build VM (run from the Linux host).
#   ./build/ship.sh            # sync sources only
#   ./build/ship.sh --build    # sync, then run build.ps1 remotely
set -euo pipefail
VM="${VM:-fadhilrashid@192.168.100.99}"
DEST="${DEST:-C:/build/ipe/src}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> syncing $ROOT -> $VM:$DEST"
tar czf - -C "$ROOT" \
  --exclude=.venv --exclude=__pycache__ --exclude=.git \
  --exclude=payload --exclude=installer --exclude=bin \
  . | ssh "$VM" "powershell -NoProfile -Command \"New-Item -ItemType Directory -Force -Path '$DEST' | Out-Null; \$in=[Console]::OpenStandardInput(); \$fs=[IO.File]::Create('C:/build/ipe/src.tgz'); \$in.CopyTo(\$fs); \$fs.Close(); tar -xzf C:/build/ipe/src.tgz -C '$DEST'\"" 2>/dev/null || {
    echo "tar not available on the VM; falling back to scp of a tarball"
    tar czf /tmp/ipe_src.tgz -C "$ROOT" --exclude=.venv --exclude=__pycache__ --exclude=.git --exclude=payload --exclude=installer --exclude=bin .
    scp -q /tmp/ipe_src.tgz "$VM:C:/build/ipe/src.tgz"
    ssh "$VM" "cd /d C:\\build\\ipe && tar -xzf src.tgz -C src"
  }

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
