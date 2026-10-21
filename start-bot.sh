#!/bin/sh
cd "$(dirname "$0")" || exit 1
if [ ! -x env/bin/python ]; then
  echo "env/ is missing. Run ./setup.sh first." >&2
  exit 1
fi
exec env/bin/python main.py "$@"
