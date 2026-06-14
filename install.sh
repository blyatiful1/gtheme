#!/usr/bin/env bash
# gtheme installer — symlinks the `gtheme` CLI into ~/.local/bin and checks deps.
# No root needed. Re-runnable.
#
#   ./install.sh              install (symlink + dep check)
#   ./install.sh --pip        also `pip install --user jinja2 pydantic` if missing
#   ./install.sh --uninstall  remove the ~/.local/bin/gtheme symlink
set -eu

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
TARGET="$BIN_DIR/gtheme"

DO_PIP=0
DO_UNINSTALL=0
for arg in "$@"; do
  case "$arg" in
    --pip)       DO_PIP=1 ;;
    --uninstall) DO_UNINSTALL=1 ;;
    -h|--help)
      echo "usage: install.sh [--pip] [--uninstall]"
      exit 0 ;;
    *) echo "!! unknown option: $arg" >&2; exit 2 ;;
  esac
done

# --- uninstall -------------------------------------------------------------
if [ "$DO_UNINSTALL" -eq 1 ]; then
  if [ -L "$TARGET" ]; then
    rm -f "$TARGET"
    echo ":: removed $TARGET"
  elif [ -e "$TARGET" ]; then
    echo "!! $TARGET exists but is not a symlink — leaving it alone" >&2
    exit 1
  else
    echo ":: nothing to remove ($TARGET not present)"
  fi
  exit 0
fi

echo ":: gtheme installer"

# 1) Python version (need >= 3.11 for tomllib)
if ! command -v python3 >/dev/null; then
  echo "!! python3 not found — install Python 3.11+ first" >&2
  exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  PYV=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
  echo "!! Python $PYV found; gtheme needs 3.11+" >&2
  exit 1
fi
PYV=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
echo "   python $PYV OK"

# 2) runtime deps
missing=""
for mod in jinja2 pydantic; do
  python3 -c "import $mod" 2>/dev/null || missing="$missing $mod"
done
if [ -n "$missing" ]; then
  echo "!! missing Python modules:$missing"
  if [ "$DO_PIP" -eq 1 ]; then
    echo "   installing with pip --user ...$missing"
    # shellcheck disable=SC2086 -- $missing is a deliberate space-separated arg list
    python3 -m pip install --user $missing
    echo "   installed:$missing"
  else
    echo "   Arch:   sudo pacman -S python-jinja2 python-pydantic"
    echo "   pip:    python3 -m pip install --user jinja2 pydantic"
    echo "   or re-run: ./install.sh --pip"
    echo "!! gtheme will not run until these are importable." >&2
    exit 1
  fi
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
echo "   (uninstall later with: ./install.sh --uninstall)"
