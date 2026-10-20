#!/bin/zsh
cd "${0:A:h}/.." || exit 1
if command -v python3.9 >/dev/null 2>&1; then
  exec python3.9 gui/server.py
fi
exec python3 gui/server.py
