#!/bin/bash
# Double-click this file to start KinKeep. The first time it also sets itself up (needs internet once).
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is not installed. A download page will open. Install it, then double-click this file again."
  open https://www.python.org/downloads/macos/
  read -r -p "Press Return to close." _; exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "First-time setup. Please wait, this takes a few minutes..."
  python3 -m venv .venv && .venv/bin/python -m pip install --upgrade pip && .venv/bin/python -m pip install -r requirements.txt || {
    echo; echo "Something went wrong. Take a screenshot of this window and send it to whoever is helping you."
    read -r -p "Press Return to close." _; exit 1; }
fi
exec .venv/bin/python -m kinkeep_desktop
