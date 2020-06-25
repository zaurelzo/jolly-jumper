#!/bin/bash
#assume that kalenji_reader is in $PATH
kalenji_reader -c watch-conf
success=$?
if [ $success != 0 ]
then
  echo "kalenji_reader failed with code $success"
  exit 1
fi
python3.7 exporter.py