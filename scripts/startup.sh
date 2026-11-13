#!/bin/bash
# Container entrypoint. Starts as root only to fix volume ownership, then drops to uid 1000.
set -euo pipefail
export DATA_DIR="${DATA_DIR:-/data}"
PORT="${PORT:-8000}"

if [ "$(id -u)" = "0" ]; then
  mkdir -p "$DATA_DIR"
  if [ "$(stat -c %u "$DATA_DIR")" != "1000" ]; then
    echo "[startup] giving the thg user ownership of $DATA_DIR"
    chown -R 1000:1000 "$DATA_DIR" || echo "[startup] WARNING: could not chown $DATA_DIR"
  fi
  exec setpriv --reuid=1000 --regid=1000 --init-groups --no-new-privs "$0" "$@"
fi

export HOME="$DATA_DIR/system/home"
VENV="$DATA_DIR/system/venv"
mkdir -p "$HOME"
# Python packages the user installs live in a venv on the volume, so they survive redeploys.
if ! "$VENV/bin/python" -c 'import sys' >/dev/null 2>&1; then
  echo "[startup] creating Python virtualenv at $VENV"
  rm -rf "$VENV"
  python3 -m venv "$VENV"
fi

cd /app
echo "[startup] Python $(python3 --version) | listening on port $PORT | data in $DATA_DIR"
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" \
  --proxy-headers --forwarded-allow-ips='*' --timeout-graceful-shutdown 10 --no-server-header
