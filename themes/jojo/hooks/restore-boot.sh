#!/usr/bin/env bash
# gtheme JoJo boot restore hook (runs as root via the engine's sudo wrapper).
set -u
REAL=/home/crocco/.local/share/jojo-theme/staging/boot/restore-boot.sh
if [ ! -f "$REAL" ]; then
  echo "gtheme: JoJo boot restore script not found at $REAL — nothing to undo" >&2
  exit 0
fi
exec bash "$REAL" "$@"
