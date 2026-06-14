#!/usr/bin/env bash
# gtheme JoJo boot restore hook (runs as root via the engine's sudo wrapper).
#
# KNOWN LIMITATION: this hook is a no-op unless the separately-shipped JoJo
# boot staging assets are present at $REAL. They are not bundled with the theme,
# so on a stock install this safely does nothing.
set -u
REAL="$HOME/.local/share/jojo-theme/staging/boot/restore-boot.sh"
if [ ! -f "$REAL" ]; then
  echo "gtheme: JoJo boot restore script not found at $REAL — nothing to undo." >&2
  echo "gtheme: boot theming needs the separately-shipped JoJo staging assets; nothing was changed." >&2
  exit 0
fi
exec bash "$REAL" "$@"
