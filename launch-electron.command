#!/bin/sh
case "$0" in
  /*) SCRIPT_PATH=$0 ;;
  *) SCRIPT_PATH=$PWD/$0 ;;
esac
SCRIPT_DIR=${SCRIPT_PATH%/*}
SCRIPT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR" && pwd)
exec /bin/sh "$SCRIPT_DIR/launch-electron.sh" "$@"
