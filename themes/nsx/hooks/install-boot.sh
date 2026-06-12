#!/usr/bin/env bash
# gtheme NSX boot hook (runs as root via the engine's sudo wrapper).
# Delegates to the existing, tested NSX boot installer (Plymouth tach splash,
# Limine menu, GDM greeter). It makes its own backups under nsx-theme/backup/boot.
#
# NOTE: a fully self-contained theme would bundle the boot assets here; for now
# this reuses the known-good installer shipped with the original nsx-theme.
set -u
REAL=/home/crocco/.local/share/nsx-theme/staging/boot/install-boot.sh
if [ ! -f "$REAL" ]; then
  echo "gtheme: NSX boot installer not found at $REAL — skipping boot theming" >&2
  exit 0
fi
exec bash "$REAL" "$@"
