#!/usr/bin/env bash
# gtheme JoJo boot hook (runs as root via the engine's sudo wrapper).
# Delegates to the existing, tested JoJo boot installer (Plymouth golden-spin,
# GDM, Limine). It makes its own backups under jojo-theme/backup/boot.
set -u
REAL=/home/crocco/.local/share/jojo-theme/staging/boot/install-boot.sh
if [ ! -f "$REAL" ]; then
  echo "gtheme: JoJo boot installer not found at $REAL — skipping boot theming" >&2
  exit 0
fi
exec bash "$REAL" "$@"
