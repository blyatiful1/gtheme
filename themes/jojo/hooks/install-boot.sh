#!/usr/bin/env bash
# gtheme JoJo boot hook (runs as root via the engine's sudo wrapper).
# Delegates to the existing, tested JoJo boot installer (Plymouth golden-spin,
# GDM, Limine). It makes its own backups under jojo-theme/backup/boot.
#
# KNOWN LIMITATION: this hook is a no-op unless the separately-shipped JoJo
# boot staging assets are present at $REAL. They are not bundled with the theme,
# so on a stock install this safely does nothing.
set -u
REAL="$HOME/.local/share/jojo-theme/staging/boot/install-boot.sh"
if [ ! -f "$REAL" ]; then
  echo "gtheme: JoJo boot installer not found at $REAL — skipping boot theming." >&2
  echo "gtheme: boot theming needs the separately-shipped JoJo staging assets; install those first." >&2
  exit 0
fi
exec bash "$REAL" "$@"
