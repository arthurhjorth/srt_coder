#!/usr/bin/env zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

APP_URL="http://127.0.0.1:8085"
RUNTIME_DIR="$SCRIPT_DIR/.runtime"
PID_FILE="$RUNTIME_DIR/server.pid"
LOG_FILE="$RUNTIME_DIR/server.log"
UV_BIN=""

resolve_uv_bin() {
  if [[ -x "$SCRIPT_DIR/.local/bin/uv" ]]; then
    echo "$SCRIPT_DIR/.local/bin/uv"
    return 0
  fi
  if [[ -x "$SCRIPT_DIR/.local/uv" ]]; then
    echo "$SCRIPT_DIR/.local/uv"
    return 0
  fi
  return 1
}

mkdir -p "$RUNTIME_DIR"

echo "Starting SRT Coder..."

UV_BIN="$(resolve_uv_bin || true)"

if [[ -f "$PID_FILE" ]]; then
  EXISTING_PID="$(cat "$PID_FILE" || true)"
  if [[ -n "${EXISTING_PID}" ]] && kill -0 "$EXISTING_PID" >/dev/null 2>&1; then
    echo "SRT Coder is already running (PID $EXISTING_PID)."
    open "$APP_URL"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

if [[ -z "$UV_BIN" || ! -x "$UV_BIN" ]]; then
  echo "Installing local runtime manager (uv) ..."
  if ! command -v curl >/dev/null 2>&1; then
    echo "Error: curl is required but not found."
    exit 1
  fi
  export UV_INSTALL_DIR="$SCRIPT_DIR/.local"
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi

UV_BIN="$(resolve_uv_bin || true)"
if [[ -z "$UV_BIN" ]]; then
  echo "Error: uv was not found after installation."
  echo "Expected at .local/bin/uv or .local/uv"
  exit 1
fi

echo "Preparing Python environment ..."
if [[ ! -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
  "$UV_BIN" venv "$SCRIPT_DIR/.venv" --python 3.13
else
  echo "Using existing virtual environment at .venv"
fi
"$UV_BIN" pip install --python "$SCRIPT_DIR/.venv/bin/python" -r "$SCRIPT_DIR/requirements.txt"

echo "Launching app ..."
nohup "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/app.py" >"$LOG_FILE" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"

# Wait for app to come up and then open browser.
for _ in {1..30}; do
  if command -v curl >/dev/null 2>&1; then
    if curl -s "$APP_URL" >/dev/null 2>&1; then
      break
    fi
  fi
  sleep 0.5
done

echo "SRT Coder running. Log: $LOG_FILE"
open "$APP_URL"
