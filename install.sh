#!/usr/bin/env bash
# gtheme installer — symlinks the `gtheme` CLI into ~/.local/bin and checks deps.
# No root needed. Re-runnable.
#
#   ./install.sh                     install (symlink + dep check)
#   ./install.sh --pip               deps via a private venv (~/.local/share/gtheme/venv)
#   ./install.sh --uninstall         remove the ~/.local/bin/gtheme launcher
#   ./install.sh --uninstall --force ... even if a theme is still applied
set -eu

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
TARGET="$BIN_DIR/gtheme"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/gtheme"
VENV="${XDG_DATA_HOME:-$HOME/.local/share}/gtheme/venv"
# The --pip launcher is a real file, not a symlink; this marker is how we
# recognize our own wrapper later (replace/uninstall) without ever touching
# a foreign file that happens to sit at $TARGET.
WRAPPER_MARK="# gtheme launcher wrapper (written by install.sh; safe to delete)"

DO_PIP=0
DO_UNINSTALL=0
DO_FORCE=0
for arg in "$@"; do
  case "$arg" in
    --pip)       DO_PIP=1 ;;
    --uninstall) DO_UNINSTALL=1 ;;
    --force)     DO_FORCE=1 ;;
    -h|--help)
      echo "usage: install.sh [--pip] [--uninstall [--force]]"
      exit 0 ;;
    *) echo "!! unknown option: $arg" >&2; exit 2 ;;
  esac
done

is_wrapper() {
  [ -f "$1" ] && [ ! -L "$1" ] && grep -qF "$WRAPPER_MARK" "$1" 2>/dev/null
}

# --- uninstall -------------------------------------------------------------
if [ "$DO_UNINSTALL" -eq 1 ]; then
  # Refuse to strand a themed desktop: with the launcher gone there is no
  # `gtheme restore` left to undo it.
  if [ -s "$STATE_DIR/current" ] && [ "$DO_FORCE" -eq 0 ]; then
    echo "!! a theme is still applied ($(cat "$STATE_DIR/current")) — run \`gtheme restore\` first" >&2
    echo "   (or remove the launcher anyway with: ./install.sh --uninstall --force)" >&2
    exit 1
  fi
  if [ -L "$TARGET" ] || is_wrapper "$TARGET"; then
    rm -f "$TARGET"
    echo ":: removed $TARGET"
  elif [ -e "$TARGET" ]; then
    echo "!! $TARGET exists but was not installed by this script — leaving it alone" >&2
    exit 1
  else
    echo ":: nothing to remove ($TARGET not present)"
  fi
  # ponytail: the --pip venv is left in place — deleting it while themes/state
  # under ~/.local/{share,state}/gtheme still exist would be wrong anyway.
  if [ -d "$VENV" ]; then
    echo "   (the private venv remains; remove with: rm -rf $VENV)"
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
  echo "   (Ubuntu 22.04 ships 3.10 — upgrade to 24.04+, or install gtheme with a newer Python, e.g.: uv tool install --python 3.12 .)" >&2
  exit 1
fi
PYV=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
echo "   python $PYV OK"

# 2) runtime deps — version-gated: a bare `import pydantic` also succeeds on
# pydantic 1.x (what Debian 12 / Ubuntu 24.04 apt ships), which gtheme cannot
# use. Exit 0 = OK, 1 = missing, 2 = too old; prints the found version.
dep_probe() {  # dep_probe <python> <module> <min-version>
  "$1" - "$2" "$3" 2>/dev/null <<'PY'
import importlib, sys
mod, want = sys.argv[1], sys.argv[2]
try:
    m = importlib.import_module(mod)
except ImportError:
    sys.exit(1)
# jinja2 exposes __version__; pydantic exposes VERSION on both v1 and v2.
raw = str(getattr(m, "__version__", "") or getattr(m, "VERSION", "") or "0")
def tup(s):
    out = []
    for part in s.split("."):
        digits = "".join(c for c in part if c.isdigit())
        if not digits:
            break
        out.append(int(digits))
    return tuple(out) or (0,)
print(raw)
sys.exit(0 if tup(raw) >= tup(want) else 2)
PY
}

guidance() {
  echo "   easiest:        ./install.sh --pip   (private venv — works on any distro)"
  echo "   Debian/Ubuntu:  sudo apt install python3-jinja2 python3-pydantic"
  echo "                   (Debian 12 / Ubuntu 24.04 apt ships pydantic 1.x — too old;"
  echo "                    prefer ./install.sh --pip there)"
  echo "   Fedora:         sudo dnf install python3-jinja2 python3-pydantic"
  echo "   Arch:           sudo pacman -S python-jinja2 python-pydantic"
}

DEPS_OK=1
for spec in "jinja2 3.1" "pydantic 2"; do
  mod=${spec% *}
  want=${spec#* }
  ver=$(dep_probe python3 "$mod" "$want") && rc=0 || rc=$?
  if [ "$rc" -eq 1 ]; then
    DEPS_OK=0
    echo "!! missing Python module: $mod"
  elif [ "$rc" -eq 2 ]; then
    DEPS_OK=0
    if [ "$mod" = pydantic ]; then
      echo "!! your distro ships pydantic $ver; gtheme needs 2.x"
    else
      echo "!! $mod $ver is too old; gtheme needs $mod >= $want"
    fi
  fi
done

USE_VENV=0
if [ "$DEPS_OK" -eq 1 ]; then
  echo "   jinja2 + pydantic OK"
  if [ "$DO_PIP" -eq 1 ]; then
    echo "   (--pip: system modules are fine — no venv needed)"
  fi
elif [ "$DO_PIP" -eq 1 ]; then
  # PEP 668 blocks `pip install --user` on every modern distro, so --pip means
  # a private venv instead: stdlib-only, no root, survives system upgrades.
  if ! python3 -c 'import venv, ensurepip' 2>/dev/null; then
    echo "!! python3 cannot create venvs here (venv/ensurepip missing)." >&2
    echo "   Debian/Ubuntu split it into its own package — install it, then re-run:" >&2
    echo "   sudo apt install python3-venv" >&2
    exit 1
  fi
  if [ ! -x "$VENV/bin/python" ]; then
    echo "   creating private venv at $VENV ..."
    if ! python3 -m venv "$VENV"; then
      echo "!! venv creation failed." >&2
      echo "   on Debian/Ubuntu: sudo apt install python3-venv, then re-run" >&2
      exit 1
    fi
  fi
  echo "   installing jinja2 + pydantic into the venv ..."
  if "$VENV/bin/python" -m pip install --quiet 'jinja2>=3.1' 'pydantic>=2'; then
    echo "   venv deps OK"
    USE_VENV=1
  else
    echo "!! pip install into the venv failed (network down? stale venv?)." >&2
    echo "   (a stale venv can be reset with: rm -rf $VENV — then re-run)" >&2
    guidance
    echo "!! gtheme will not run until jinja2 + pydantic are importable." >&2
    exit 1
  fi
else
  guidance
  echo "!! gtheme will not run until jinja2 + pydantic are importable." >&2
  exit 1
fi

# 3) install the launcher
mkdir -p "$BIN_DIR"
# Refuse to clobber a foreign file/dir at the target: `ln -sfn` into an
# existing directory would silently create TARGET/gtheme and "succeed".
if [ -e "$TARGET" ] && [ ! -L "$TARGET" ] && ! is_wrapper "$TARGET"; then
  echo "!! $TARGET exists and was not installed by this script — remove it first" >&2
  exit 1
fi
# chmod the real launcher BEFORE linking, and don't abort if it's already +x
# (e.g. a read-only/foreign-owned checkout where the bit is already set).
chmod +x "$REPO/bin/gtheme" 2>/dev/null || echo "   (note: bin/gtheme already executable)"
if [ "$USE_VENV" -eq 1 ]; then
  # A tiny wrapper instead of a symlink: it runs the checkout's launcher with
  # the venv's python (which has jinja2+pydantic). rm first — writing through
  # an existing symlink would clobber bin/gtheme itself.
  rm -f "$TARGET"
  cat > "$TARGET" <<EOF
#!/bin/sh
$WRAPPER_MARK
exec "$VENV/bin/python" "$REPO/bin/gtheme" "\$@"
EOF
  chmod +x "$TARGET"
  echo "   wrote $TARGET (runs bin/gtheme with the venv python)"
else
  ln -sfn "$REPO/bin/gtheme" "$TARGET"
  echo "   linked $TARGET -> $REPO/bin/gtheme"
fi
echo "   NOTE: gtheme runs from this folder ($REPO) — don't delete or move it"
echo "         (want it self-contained? use pipx instead: pipx install $REPO)"

ON_PATH=1
case ":$PATH:" in
  *":$BIN_DIR:"*) : ;;
  *)
    ON_PATH=0
    echo "   NOTE: $BIN_DIR is not on your PATH, so plain \`gtheme\` won't work yet."
    # Print-only on purpose: we never auto-edit shell rc files.
    case "$(basename "${SHELL:-/bin/sh}")" in
      fish) echo "   fix (fish):  fish_add_path $BIN_DIR" ;;
      zsh)  echo "   fix (zsh):   echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ~/.zshrc" ;;
      *)    echo "   fix (bash):  echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ~/.bashrc" ;;
    esac
    echo "   ... then open a new terminal (on Ubuntu, logging out and back in also works)."
    ;;
esac

if [ "$ON_PATH" -eq 1 ]; then
  echo ":: done — try: gtheme list"
else
  echo ":: done — after fixing PATH (new terminal), try: gtheme list"
  echo "   (works right away: $TARGET list)"
fi
echo "   (uninstall later with: ./install.sh --uninstall)"
