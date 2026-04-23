#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

OUT_DIR="$ROOT_DIR/release"
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

# Archive that is easy to share with non-technical macOS users.
ZIP_NAME="srt_coder_mac_release.zip"

zip -r "$OUT_DIR/$ZIP_NAME" \
  Start.command \
  Stop.command \
  README.md \
  requirements.txt \
  app.py \
  config.py \
  models.py \
  auth \
  domain \
  parsing \
  state \
  storage \
  ui \
  coded_data \
  interview_data \
  tests \
  -x "*.DS_Store" "*/.git/*" "*/.venv/*" "*/.nicegui/*" "*/__pycache__/*" "coded_data/exports/*" "release/*"

echo "Created: $OUT_DIR/$ZIP_NAME"
