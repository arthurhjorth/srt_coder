#!/usr/bin/env zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/.runtime/server.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "No running server found."
  exit 0
fi

PID="$(cat "$PID_FILE" || true)"
if [[ -z "$PID" ]]; then
  rm -f "$PID_FILE"
  echo "No running server found."
  exit 0
fi

if kill -0 "$PID" >/dev/null 2>&1; then
  kill "$PID" >/dev/null 2>&1 || true
  for _ in {1..20}; do
    if ! kill -0 "$PID" >/dev/null 2>&1; then
      break
    fi
    sleep 0.2
  done
  if kill -0 "$PID" >/dev/null 2>&1; then
    kill -9 "$PID" >/dev/null 2>&1 || true
  fi
  echo "Stopped SRT Coder (PID $PID)."
else
  echo "Process $PID is not running."
fi

rm -f "$PID_FILE"
