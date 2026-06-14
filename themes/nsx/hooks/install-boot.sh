#!/usr/bin/env bash
# gtheme NSX boot hook (runs as root via the engine's sudo wrapper).
# Delegates to the existing, tested NSX boot installer (Plymouth tach splash,
# Limine menu, GDM greeter). It makes its own backups under nsx-theme/backup/boot.
#
# KNOWN LIMITATION: this hook is a no-op unless the separately-shipped NSX boot
# staging assets are present at $REAL. They are not bundled with the theme, so on
# a stock install this safely does nothing.
set -u
REAL="$HOME/.local/share/nsx-theme/staging/boot/install-boot.sh"
if [ ! -f "$REAL" ]; then
  echo "gtheme: NSX boot installer not found at $REAL — skipping boot theming." >&2
  echo "gtheme: boot theming needs the separately-shipped NSX staging assets; install those first." >&2
  exit 0
fi
exec bash "$REAL" "$@"
