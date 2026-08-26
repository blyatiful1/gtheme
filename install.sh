#!/usr/bin/env bash
# gtheme installer.
#
# It does four things, and nothing else:
#   1. checks your computer has what gtheme needs, and says how to get it if not
#   2. makes gtheme its own private folder for the bits it installs
#      (nothing outside this folder and your own Home folder is touched)
#   3. puts "gtheme" on your list of commands
#   4. adds gtheme to your list of applications, so you can click it like any app
#
# It never asks for an administrator password, and running it twice is safe.
#
#   ./install.sh                     install, or update an existing install
#   ./install.sh --uninstall         take the launcher and the app entry away
#   ./install.sh --uninstall --force ... even if a look is still applied
#
# (Deliberately not `pip install --user`: every current Linux system refuses
# that now — the "externally-managed-environment" message. The private folder
# below is the supported way, and it is the same one the project's own
# developers use.)
set -eu

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$REPO/.venv"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
TARGET="$BIN_DIR/gtheme"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/gtheme"
APP_ID="io.github.blyatiful1.Gtheme"

DO_UNINSTALL=0
DO_FORCE=0
for arg in "$@"; do
  case "$arg" in
    --uninstall) DO_UNINSTALL=1 ;;
    --force)     DO_FORCE=1 ;;
    -h|--help)
      echo "usage: install.sh [--uninstall [--force]]"
      exit 0 ;;
    *) echo "!! I don't know the option: $arg" >&2; exit 2 ;;
  esac
done

say()  { echo "   $*"; }
step() { echo ":: $*"; }
oops() { echo "!! $*" >&2; }

# --- uninstall -------------------------------------------------------------
if [ "$DO_UNINSTALL" -eq 1 ]; then
  # Don't strand a changed desktop: without the launcher there is no way left
  # to put it back.
  if [ -s "$STATE_DIR/v2/current.json" ] && [ "$DO_FORCE" -eq 0 ]; then
    oops "your desktop is still using a look that gtheme applied."
    oops "open gtheme, go to Undo & Restore Points, and put it back first."
    oops "(or remove the launcher anyway: ./install.sh --uninstall --force)"
    exit 1
  fi
  if [ -L "$TARGET" ]; then
    rm -f "$TARGET"
    say "removed the gtheme command"
  elif [ -e "$TARGET" ]; then
    oops "$TARGET is something this script did not create — leaving it alone"
    exit 1
  else
    say "the gtheme command was not there"
  fi
  rm -f "$DATA_HOME/applications/$APP_ID.desktop"
  rm -f "$DATA_HOME/metainfo/$APP_ID.metainfo.xml"
  rm -f "$DATA_HOME/icons/hicolor/scalable/apps/$APP_ID.svg"
  rm -f "$DATA_HOME/icons/hicolor/symbolic/apps/$APP_ID-symbolic.svg"
  say "removed gtheme from your list of applications"
  command -v update-desktop-database >/dev/null 2>&1 \
    && update-desktop-database "$DATA_HOME/applications" >/dev/null 2>&1 || true
  command -v gtk4-update-icon-cache >/dev/null 2>&1 \
    && gtk4-update-icon-cache -qtf "$DATA_HOME/icons/hicolor" >/dev/null 2>&1 || true
  say "your looks, restore points and settings were NOT deleted."
  say "they live in $STATE_DIR — delete that folder yourself if you want them gone."
  say "(the private folder $VENV is also still here; remove it with: rm -rf $VENV)"
  step "done"
  exit 0
fi

step "installing gtheme"

# --- 1. what your computer needs -------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
  oops "python3 is not installed. Install it first, then run this again:"
  say  "Ubuntu/Debian/Mint:  sudo apt install python3 python3-venv"
  say  "Fedora:              sudo dnf install python3"
  say  "Arch/CachyOS/Endeavour: sudo pacman -S python"
  exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  PYV=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
  oops "your computer has Python $PYV, and gtheme needs 3.11 or newer."
  say  "Ubuntu 22.04 and older ship 3.10 — updating your system to a newer"
  say  "release is the fix."
  exit 1
fi
say "Python: OK"

# The graphical half of gtheme uses pieces that come from your system, never
# from the internet: they are the same pieces your desktop itself is built
# from, and they cannot be installed into a private folder.
MISSING=""
python3 - <<'PY' 2>/dev/null || MISSING="yes"
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: F401
PY
if [ -n "$MISSING" ]; then
  oops "some pieces gtheme needs are missing from your system."
  say  "Install them with the line for your system, then run this again:"
  say  "Ubuntu/Debian/Mint:  sudo apt install python3-gi gir1.2-adw-1 libadwaita-1-0 python3-venv"
  say  "Fedora:              sudo dnf install python3-gobject gtk4 libadwaita"
  say  "Arch/CachyOS/Endeavour: sudo pacman -S python-gobject gtk4 libadwaita"
  say  "(gtheme changes a GNOME desktop. On other desktops it will open and"
  say  " tell you it cannot help, rather than change anything.)"
  exit 1
fi
say "desktop pieces: OK"

# --- 2. the private folder --------------------------------------------------
if ! python3 -c 'import venv, ensurepip' >/dev/null 2>&1; then
  oops "your Python cannot make a private folder yet."
  say  "Ubuntu/Debian/Mint keep that part separate — install it and run this again:"
  say  "sudo apt install python3-venv"
  exit 1
fi
if [ ! -x "$VENV/bin/python" ]; then
  say "making a private folder for gtheme at $VENV ..."
  # --system-site-packages is required, not a preference: the graphical pieces
  # checked above live in the system's Python and must stay visible in here.
  if ! python3 -m venv --system-site-packages "$VENV"; then
    oops "that folder could not be made."
    say  "Ubuntu/Debian/Mint: sudo apt install python3-venv, then run this again."
    say  "(a half-made folder can be cleared with: rm -rf $VENV)"
    exit 1
  fi
else
  say "private folder: already there"
fi

say "getting the two small pieces gtheme needs from the internet ..."
if ! "$VENV/bin/python" -m pip install --quiet --upgrade pip >/dev/null 2>&1; then
  say "(could not update the installer itself — carrying on)"
fi
if ! "$VENV/bin/python" -m pip install --quiet -e "$REPO"; then
  oops "that did not work."
  say  "The usual reason is no internet connection. Check it and run this again."
  say  "(if it keeps failing, clear the folder and retry: rm -rf $VENV)"
  exit 1
fi
say "gtheme itself: installed"

# --- 3. the command ---------------------------------------------------------
mkdir -p "$BIN_DIR"
if [ -e "$TARGET" ] && [ ! -L "$TARGET" ]; then
  oops "$TARGET already exists and this script did not create it."
  say  "Move or delete it yourself, then run this again."
  exit 1
fi
chmod +x "$REPO/bin/gtheme" 2>/dev/null || true
ln -sfn "$REPO/bin/gtheme" "$TARGET"
say "the command \`gtheme\` now points at this folder"

# --- 4. the application entry ----------------------------------------------
# The entry that ships in data/ says `Exec=gtheme gui`, which is right for a
# system package (/usr/bin is always on the list of command folders). Installed
# into a home folder it might not be, and a launcher that does nothing when
# clicked is the worst possible first impression — so the copy that lands here
# names the launcher by its full path.
mkdir -p "$DATA_HOME/applications"
sed "s|^Exec=gtheme |Exec=$TARGET |" "$REPO/data/$APP_ID.desktop" \
  > "$DATA_HOME/applications/$APP_ID.desktop"
chmod 644 "$DATA_HOME/applications/$APP_ID.desktop"
install -Dm644 "$REPO/data/$APP_ID.metainfo.xml"  "$DATA_HOME/metainfo/$APP_ID.metainfo.xml"
install -Dm644 "$REPO/data/icons/hicolor/scalable/apps/$APP_ID.svg" \
               "$DATA_HOME/icons/hicolor/scalable/apps/$APP_ID.svg"
install -Dm644 "$REPO/data/icons/hicolor/symbolic/apps/$APP_ID-symbolic.svg" \
               "$DATA_HOME/icons/hicolor/symbolic/apps/$APP_ID-symbolic.svg"
# Both of these only refresh a cache. If they are missing, the desktop finds
# the new entry on its own the next time you log in.
command -v update-desktop-database >/dev/null 2>&1 \
  && update-desktop-database "$DATA_HOME/applications" >/dev/null 2>&1 || true
command -v gtk4-update-icon-cache >/dev/null 2>&1 \
  && gtk4-update-icon-cache -qtf "$DATA_HOME/icons/hicolor" >/dev/null 2>&1 || true
say "gtheme is now in your list of applications"

# --- how to start it --------------------------------------------------------
say "keep this folder ($REPO) where it is — gtheme runs from it."
ON_PATH=1
case ":$PATH:" in
  *":$BIN_DIR:"*) : ;;
  *) ON_PATH=0 ;;
esac

step "done"
say "Open it like any other app: press the key with the Windows/Command logo,"
say "type \"gtheme\", press Enter. (If it is not there yet, log out and back in.)"
if [ "$ON_PATH" -eq 1 ]; then
  say "Or, from a terminal window: gtheme"
else
  say "Or, from a terminal window: $TARGET"
  say "(typing plain \`gtheme\` needs $BIN_DIR added to your list of command"
  say " folders — this script does not edit your settings files for you.)"
  case "$(basename "${SHELL:-/bin/sh}")" in
    fish) say "fish: fish_add_path $BIN_DIR" ;;
    zsh)  say "zsh:  echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ~/.zshrc" ;;
    *)    say "bash: echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ~/.bashrc" ;;
  esac
fi
say "To take it away again: ./install.sh --uninstall"
