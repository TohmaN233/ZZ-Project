#!/bin/sh
set -eu

case "$0" in
  /*) SCRIPT_PATH=$0 ;;
  *) SCRIPT_PATH=$PWD/$0 ;;
esac
SCRIPT_DIR=${SCRIPT_PATH%/*}
SCRIPT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR" && pwd)
cd "$SCRIPT_DIR"
export PYTHONIOENCODING=utf-8

if ! command -v npm >/dev/null 2>&1; then
  echo "[ERROR] npm was not found in PATH." >&2
  echo "Install Node.js 20 or newer and try again." >&2
  exit 1
fi

if [ ! -f package.json ]; then
  echo "[ERROR] package.json was not found next to this launcher." >&2
  exit 1
fi

python_is_supported() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

if [ -n "${ZZ_PYTHON:-}" ]; then
  if ! python_is_supported "$ZZ_PYTHON"; then
    echo "[ERROR] ZZ_PYTHON does not point to a working Python 3.10+ interpreter." >&2
    exit 1
  fi
elif command -v python3 >/dev/null 2>&1 && python_is_supported "$(command -v python3)"; then
  ZZ_PYTHON=$(command -v python3)
elif command -v python >/dev/null 2>&1 && python_is_supported "$(command -v python)"; then
  ZZ_PYTHON=$(command -v python)
else
  echo "[ERROR] Python 3.10 or newer was not found in PATH." >&2
  exit 1
fi
export ZZ_PYTHON

if [ "${1:-}" = "--check" ]; then
  echo "Launcher check passed."
  echo "npm: $(command -v npm)"
  echo "python: $ZZ_PYTHON"
  exit 0
fi

if [ ! -x node_modules/.bin/electron ]; then
  echo "Electron dependencies were not found. Installing npm dependencies once..."
  npm install
fi

echo "Starting ZENONZARD Offline Project from $SCRIPT_DIR"
exec npm run electron:dev
