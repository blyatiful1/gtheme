#!/usr/bin/env bash
# gtheme installer — symlinks the `gtheme` CLI into ~/.local/bin and checks deps.
# No root needed. Re-runnable.
set -eu

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
TARGET="$BIN_DIR/gtheme"

echo ":: gtheme installer"

# 1) Python version
if ! command -v python3 >/dev/null; then
  echo "!! python3 not found — install Python 3.11+ first" >&2
  exit 1
fi
PYV=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
case "$PYV" in
  3.1[1-9]|3.[2-9]*) : ;;
  *) echo "!! Python $PYV found; gtheme needs 3.11+" >&2; exit 1 ;;
esac
echo "   python $PYV OK"

# 2) runtime deps
missing=""
for mod in jinja2 pydantic; do
  python3 -c "import $mod" 2>/dev/null || missing="$missing $mod"
done
if [ -n "$missing" ]; then
  echo "!! missing Python modules:$missing"
  echo "   Arch:    sudo pacman -S${missing// / python-}" | sed 's/python-jinja2/python-jinja2/'
  echo "   or:      pipx install jinja2 pydantic   (into a venv)"
  echo "   gtheme will not run until these are importable."
else
  echo "   jinja2 + pydantic OK"
fi

# 3) symlink the launcher
mkdir -p "$BIN_DIR"
ln -sfn "$REPO/bin/gtheme" "$TARGET"
chmod +x "$REPO/bin/gtheme"
echo "   linked $TARGET -> $REPO/bin/gtheme"

case ":$PATH:" in
  *":$BIN_DIR:"*) : ;;
  *) echo "   NOTE: add $BIN_DIR to your PATH" ;;
esac

echo ":: done — try: gtheme list"
