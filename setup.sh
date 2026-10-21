#!/bin/sh
set -e
cd "$(dirname "$0")"

PYTHON=""
for candidate in python3 python3.14 python3.13 python3.12; do
  if command -v "$candidate" >/dev/null 2>&1 \
      && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null; then
    PYTHON="$candidate"
    break
  fi
done
if [ -z "$PYTHON" ]; then
  echo "Python 3.12 or newer is required. Install it from https://www.python.org/downloads/ and run ./setup.sh again." >&2
  exit 1
fi

if [ ! -x env/bin/python ]; then
  echo "Creating env/ with $("$PYTHON" --version)..."
  "$PYTHON" -m venv env || {
    echo "Could not create env/. On Debian/Ubuntu install the venv module: sudo apt install python3-venv" >&2
    exit 1
  }
fi
# Older installs used opencv-python; it shares the cv2 package with the headless build, so both cannot coexist.
env/bin/python -m pip uninstall --disable-pip-version-check -y -q opencv-python 2>/dev/null || true
env/bin/python -m pip install --disable-pip-version-check -r requirements.txt
env/bin/python -c 'import cv2, numpy'

env/bin/python adb.py || true
echo "Setup complete. Start the dashboard with ./start-gui.sh or the CLI bot with ./start-bot.sh"
