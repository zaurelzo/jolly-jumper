#!/bin/bash

garmin="garmin"
kalenji="kalenji"

if [ $# -ne 1 ]; then
  echo "[Usage] ./exporter.sh device-name. device-name must be equal to $garmin or $kalenji"
  exit 1
fi

if [ $1 = $garmin ]; then
  python3.8 fit-exporter.py
elif [ $1 = $kalenji ]; then
  #assume that kalenji_reader is in $PATH
  kalenji_reader -c watch-conf
  success=$?
  if [ $success != 0 ]; then
    echo "kalenji_reader failed with code $success"
    exit 1
  fi
  python3.8 exporter.py
else
  echo "$1 device is not supported"
  exit 1
fi
