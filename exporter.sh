#!/bin/bash

set -euo pipefail

GARMIN="garmin"
KALENJI="kalenji"
VENV_DIR=".venv"
REQ_HASH_FILE="$VENV_DIR/.requirements_hash"

# -------------------------
# Usage
# -------------------------

usage() {
  echo "Usage: ./exporter.sh <device> [--no-bike]"
  echo "Supported devices: $GARMIN | $KALENJI"
  echo ""
  echo "Options:"
  echo "  --no-bike   Skip bike assignment and upload without setting a bike"
  exit 1
}

# -------------------------
# Parse arguments
# -------------------------

if [ $# -lt 1 ]; then
  usage
fi

DEVICE=$1
NO_BIKE=""

shift
while [ $# -gt 0 ]; do
  case "$1" in
    --no-bike) NO_BIKE="--no-bike" ;;
    *) echo "Error: unknown option '$1'"; usage ;;
  esac
  shift
done

if [ "$DEVICE" != "$GARMIN" ] && [ "$DEVICE" != "$KALENJI" ]; then
  echo "Error: unsupported device '$DEVICE'"
  usage
fi

# -------------------------
# Virtual environment setup
# -------------------------

if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtual environment..."
  python3 -m venv "$VENV_DIR"
fi

# Only reinstall dependencies if requirements.txt has changed
CURRENT_HASH=$(md5sum requirements.txt | cut -d' ' -f1)
STORED_HASH=$(cat "$REQ_HASH_FILE" 2>/dev/null || echo "")

if [ "$CURRENT_HASH" != "$STORED_HASH" ]; then
  echo "Installing dependencies..."
  "$VENV_DIR/bin/pip" install --quiet --upgrade pip
  "$VENV_DIR/bin/pip" install --quiet -r requirements.txt
  echo "$CURRENT_HASH" > "$REQ_HASH_FILE"
else
  echo "Dependencies up to date."
fi

# -------------------------
# Kalenji pre-step: extract GPX files from watch
# -------------------------

if [ "$DEVICE" = "$KALENJI" ]; then
  echo "Extracting activities from Kalenji watch..."
  kalenji_reader -c watch-conf
fi

# -------------------------
# Run unified Python exporter
# -------------------------

echo "Starting upload for device: $DEVICE"
if [ -n "$NO_BIKE" ]; then
  "$VENV_DIR/bin/python" exporter.py --device "$DEVICE" --no-bike
else
  "$VENV_DIR/bin/python" exporter.py --device "$DEVICE"
fi
