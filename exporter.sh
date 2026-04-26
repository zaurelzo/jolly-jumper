#!/bin/bash

set -euo pipefail

GARMIN="garmin"
KALENJI="kalenji"
VENV_DIR=".venv"

# -------------------------
# Usage
# -------------------------

usage() {
  echo "Usage: ./exporter.sh <device>"
  echo "Supported devices: $GARMIN | $KALENJI"
  exit 1
}

# -------------------------
# Validate arguments
# -------------------------

if [ $# -ne 1 ]; then
  usage
fi

DEVICE=$1

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

echo "Installing dependencies..."
"$VENV_DIR/bin/pip" install  --upgrade pip
"$VENV_DIR/bin/pip" install  -r requirements.txt

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
"$VENV_DIR/bin/python" exporter.py --device "$DEVICE"
