#!/usr/bin/env bash
# gtheme NSX boot restore hook (runs as root via the engine's sudo wrapper).
#
# KNOWN LIMITATION: this hook is a no-op unless the separately-shipped NSX boot
# staging assets are present at $REAL. They are not bundled with the theme, so on
# a stock install this safely does nothing.
set -u
REAL="$HOME/.local/share/nsx-theme/staging/boot/restore-boot.sh"
if [ ! -f "$REAL" ]; then
  echo "gtheme: NSX boot restore script not found at $REAL — nothing to undo." >&2
  echo "gtheme: boot theming needs the separately-shipped NSX staging assets; nothing was changed." >&2
  exit 0
fi
exec bash "$REAL" "$@"
