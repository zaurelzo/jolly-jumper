#!/bin/bash

# Supported devices
GARMIN="garmin"
KALENJI="kalenji"

# Validate input arguments
if [ $# -ne 1 ]; then
  echo "[Usage] ./exporter.sh <device>"
  echo "Supported devices: $GARMIN | $KALENJI"
  exit 1
fi

DEVICE=$1

# Garmin workflow
if [ "$DEVICE" = "$GARMIN" ]; then
  echo "Running Garmin exporter..."
  python3.8 fit-exporter.py
  exit $?

# Kalenji workflow
elif [ "$DEVICE" = "$KALENJI" ]; then
  echo "Running Kalenji exporter..."

  # Extract activities from watch
  kalenji_reader -c watch-conf
  if [ $? -ne 0 ]; then
    echo "Error: kalenji_reader failed"
    exit 1
  fi

  # Upload extracted GPX files
  python3.8 exporter.py
  exit $?

# Unsupported device
else
  echo "Error: unsupported device '$DEVICE'"
  echo "Supported devices are: $GARMIN, $KALENJI"
  exit 1
fi