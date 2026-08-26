#!/usr/bin/env bash
# The live-desktop-unchanged gate (DESIGN.md F16).
#
#   tools/check_live_baseline.sh --baseline-dir <dir>
#
# gtheme is a program that changes how a desktop looks, and it is being built
# ON the desktop it would change. The whole test suite is written around not
# touching it — private buses, rerooted settings stores, a canary on every
# sandbox test — and this is the proof that all of that worked: it re-takes the
# exact same readings that were taken before a line of v2 was written, and
# compares them, byte for byte, with the ones on file.
#
# READ-ONLY, entirely. Every command below is a `get`, a `dump`, a `find` or a
# hash. Nothing here writes anything anywhere except its own temporary files.
#
# The baseline is somebody's personal configuration — their wallpaper path,
# their extensions, the shape of their desk — so it does NOT live in this
# public repository. It lives in ~/gtheme-rebuild/research/, and this script is
# pointed at it. `verify.sh --full` runs this when GTHEME_BASELINE_DIR is set,
# and skips it, loudly, when it is not.
#
# Exit 0 means: the desktop this was built on is exactly as it was found.

set -euo pipefail

BASELINE_DIR=""
KEEP=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --baseline-dir)
            BASELINE_DIR="${2:-}"
            shift 2
            ;;
        --baseline-dir=*)
            BASELINE_DIR="${1#*=}"
            shift
            ;;
        --keep)
            # Leave the fresh capture on disk, for looking at a difference by
            # hand. Printed at the end when it is used.
            KEEP=1
            shift
            ;;
        -h|--help)
            sed -n '2,25p' "$0"
            exit 0
            ;;
        *)
            echo "check_live_baseline.sh: unknown argument $1" >&2
            exit 2
            ;;
    esac
done

if [[ -z "$BASELINE_DIR" ]]; then
    echo "check_live_baseline.sh: --baseline-dir is required" >&2
    exit 2
fi
if [[ ! -d "$BASELINE_DIR" ]]; then
    echo "check_live_baseline.sh: no such baseline directory: $BASELINE_DIR" >&2
    exit 2
fi

FRESH="$(mktemp -d -t gtheme-live-baseline-XXXXXX)"
cleanup() {
    if [[ -z "$KEEP" ]]; then
        rm -rf "$FRESH"
    fi
}
trap cleanup EXIT

# Untranslated output, always. A baseline taken in one language and re-taken in
# another differs in every line and in nothing that matters.
export LC_ALL=C

# ---------------------------------------------------------------------------
# re-take the readings
# ---------------------------------------------------------------------------

gsettings list-recursively org.gnome.desktop.interface | sort > "$FRESH/live-interface.txt"

{
    gsettings list-recursively org.gnome.desktop.background | sort
    echo "---screensaver---"
    gsettings list-recursively org.gnome.desktop.screensaver | sort
} > "$FRESH/live-background.txt"

gsettings list-recursively org.gnome.desktop.wm.preferences | sort > "$FRESH/live-wm.txt"

{
    echo "enabled-extensions:"
    gsettings get org.gnome.shell enabled-extensions
    echo "disabled-extensions:"
    gsettings get org.gnome.shell disabled-extensions
    echo "disable-user-extensions:"
    gsettings get org.gnome.shell disable-user-extensions
    echo "favorite-apps:"
    gsettings get org.gnome.shell favorite-apps
} > "$FRESH/live-shell.txt"

{
    echo "--- mouse ---"
    gsettings list-recursively org.gnome.desktop.peripherals.mouse | sort
    echo "--- touchpad ---"
    gsettings list-recursively org.gnome.desktop.peripherals.touchpad | sort
    echo "--- a11y interface ---"
    gsettings list-recursively org.gnome.desktop.a11y.interface | sort
} > "$FRESH/live-a11y-peripherals.txt"

dconf dump /org/gnome/shell/extensions/ > "$FRESH/live-extension-config.dconf"

# ---------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------

FAILED=0
report() {
    echo "check_live_baseline: $1" >&2
    FAILED=1
}

for name in live-interface.txt live-background.txt live-wm.txt live-shell.txt \
            live-a11y-peripherals.txt live-extension-config.dconf; do
    stored="$BASELINE_DIR/$name"
    if [[ ! -f "$stored" ]]; then
        report "the baseline has no $name — cannot prove anything about it"
        continue
    fi
    # The stored captures were written before this script existed, so they are
    # compared as SETS OF LINES rather than in file order: `gsettings
    # list-recursively` does not promise an order, and a reshuffled file with
    # identical contents is not a change to somebody's desktop.
    if ! diff -q <(sort "$stored") <(sort "$FRESH/$name") > /dev/null; then
        report "$name CHANGED since the baseline was taken:"
        diff <(sort "$stored") <(sort "$FRESH/$name") | head -40 >&2
    fi
done

# ---------------------------------------------------------------------------
# the two directories that must not have moved either
# ---------------------------------------------------------------------------
#
# The settings above are what gtheme writes. These are what it copies: its own
# state directory (restore points, the ledger, the pristine baseline) and the
# live rice repository the terminal adapter is pointed at by a symlink. A
# recorded hash of each goes in the baseline directory the first time this
# runs, because neither was hashed when the original readings were taken —
# and from then on it is a comparison like every other line above.

hash_tree() {
    local root="$1"
    if [[ ! -e "$root" ]]; then
        echo "absent"
        return
    fi
    # Names and contents, in a fixed order, symlinks recorded as their target
    # rather than followed — following the ghostty link would hash the rice
    # repo twice and hide a change to the link itself.
    {
        find "$root" -type l -printf '%P -> %l\n' 2>/dev/null | sort
        find "$root" -type f -printf '%P\n' 2>/dev/null | sort | while IFS= read -r rel; do
            printf '%s %s\n' "$rel" "$(sha256sum "$root/$rel" | cut -d' ' -f1)"
        done
    } | sha256sum | cut -d' ' -f1
}

STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/gtheme"
RICE_DIR="$HOME/nightbloom"

{
    printf 'state %s\n' "$(hash_tree "$STATE_DIR")"
    printf 'rice %s\n' "$(hash_tree "$RICE_DIR")"
} > "$FRESH/live-trees.sha256"

STORED_TREES="$BASELINE_DIR/live-trees.sha256"
if [[ ! -f "$STORED_TREES" ]]; then
    cp "$FRESH/live-trees.sha256" "$STORED_TREES"
    echo "check_live_baseline: recorded the first hashes of $STATE_DIR and $RICE_DIR"
    echo "                     into $STORED_TREES — future runs compare against them."
elif ! diff -q "$STORED_TREES" "$FRESH/live-trees.sha256" > /dev/null; then
    report "the recorded directories CHANGED since the baseline was taken:"
    diff "$STORED_TREES" "$FRESH/live-trees.sha256" >&2
fi

if [[ -n "$KEEP" ]]; then
    echo "check_live_baseline: the fresh capture is in $FRESH"
fi

if [[ "$FAILED" != "0" ]]; then
    echo "check_live_baseline: the live desktop is NOT as the baseline found it." >&2
    exit 1
fi

echo "check_live_baseline: the live desktop is byte-for-byte as the baseline found it."
