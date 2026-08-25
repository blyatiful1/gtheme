#!/bin/bash
# MAGMA Plymouth theme installer.
# Copies the theme into /usr/share/plymouth/themes/magma and activates it.
# MUST be run as root (it touches /usr/share and rebuilds the initramfs).
set -euo pipefail

THEME_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/magma"
THEME_DST="/usr/share/plymouth/themes/magma"

if [[ ${EUID} -ne 0 ]]; then
    echo "ERROR: this script must run as root, e.g.: sudo bash ${BASH_SOURCE[0]}" >&2
    exit 1
fi

if ! command -v plymouth-set-default-theme >/dev/null 2>&1; then
    echo "ERROR: plymouth is not installed (plymouth-set-default-theme not found)." >&2
    exit 1
fi

for f in magma.plymouth magma.script glow.png bullet.png bar.png track.png; do
    if [[ ! -f "${THEME_SRC}/${f}" ]]; then
        echo "ERROR: theme source incomplete: missing ${THEME_SRC}/${f}" >&2
        exit 1
    fi
done

PREV_THEME="$(plymouth-set-default-theme 2>/dev/null || true)"
echo "Current default theme: ${PREV_THEME:-<unknown>}"

echo "Installing theme files to ${THEME_DST} ..."
mkdir -p "${THEME_DST}"
cp -f "${THEME_SRC}"/magma.plymouth "${THEME_SRC}"/magma.script "${THEME_SRC}"/*.png "${THEME_DST}"/

# -R sets the default theme AND rebuilds the initramfs (mkinitcpio on this
# system) so the theme is baked into early boot. Without -R the old theme
# would keep showing until the next initramfs rebuild.
echo "Setting default theme to 'magma' and rebuilding initramfs (this takes a while) ..."
plymouth-set-default-theme -R magma

echo
echo "Done. New default theme: $(plymouth-set-default-theme)"
echo "To revert, run:"
echo "    plymouth-set-default-theme -R ${PREV_THEME:-cachyos}"
