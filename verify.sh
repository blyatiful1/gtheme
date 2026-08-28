#!/usr/bin/env bash
# The canonical check. Exit 0 means the project is green.
#
#   ./verify.sh           lint + unit/regression/dconf/gtk tiers
#   ./verify.sh --full    the above, plus the sandbox tier and the screenshot
#                         and live-desktop-unchanged gates
#
# Everything runs out of ./.venv on purpose: PEP 668 marks the system Python
# externally-managed, so a bare `python`/`pip` here is either the wrong
# interpreter or an error. Create the venv once with:
#
#   uv venv --system-site-packages .venv && uv pip install -e '.[dev]'
#
set -euo pipefail
cd "$(dirname "$0")"

VENV_PY=".venv/bin/python"
VENV_RUFF=".venv/bin/ruff"

# Both venv binaries are checked, not just the interpreter. Missing ruff used
# to surface as a bare "No such file or directory" from the lint line below:
# install.sh installs the app without the `[dev]` extras, so anyone who set up
# that way and then followed CONTRIBUTING got exactly that, with nothing saying
# what to do about it (review-report L12).
if [[ ! -x "$VENV_PY" ]]; then
    echo "verify.sh: .venv is missing. Create it with:" >&2
    echo "  uv venv --system-site-packages .venv && uv pip install -e '.[dev]'" >&2
    exit 1
fi

if [[ ! -x "$VENV_RUFF" ]]; then
    echo "verify.sh: .venv has no ruff — it was created without the dev extras." >&2
    echo "  uv venv --system-site-packages .venv && uv pip install -e '.[dev]'" >&2
    exit 1
fi

# Every tier that touches settings needs a session bus it can talk to, and the
# suite must not borrow whichever one the shell it was launched from happens to
# have (review-report M16): the settings phase decides whether to run from
# DBUS_SESSION_BUS_ADDRESS, so a run with no bus errors out and a run with the
# live bus is one mistake away from the real desktop. `dbus-run-session` gives
# the tiers a private one, and makes the verdict the same in a terminal, over
# ssh and in a makepkg chroot.
if ! command -v dbus-run-session >/dev/null 2>&1; then
    echo "verify.sh: dbus-run-session is missing — the test tiers need a private" >&2
    echo "           session bus. Install it (Arch: dbus  Debian/Ubuntu: dbus)." >&2
    exit 1
fi

FULL=0
if [[ "${1:-}" == "--full" || "${GTHEME_FULL:-0}" == "1" ]]; then
    FULL=1
fi

echo "== ruff =="
"$VENV_RUFF" check .

echo "== pytest (unit + regression + dconf + gtk) =="
# The sandbox tier is excluded by addopts in pyproject.toml. The dconf tier is
# not: it needs a private bus and no shell, so it runs here and in CI.
dbus-run-session -- "$VENV_PY" -m pytest -q

if [[ "$FULL" == "1" ]]; then
    # Stamped BEFORE the page walk, checked after it. This is what makes
    # "fresh screenshots" mean "from this run" rather than "from some run".
    GTHEME_SCREENSHOT_RUN_START="$(date +%s)"
    export GTHEME_SCREENSHOT_RUN_START

    echo "== pytest (sandbox) =="
    # NEVER '|| true': a red sandbox is a red check.
    #
    # Not wrapped in dbus-run-session, unlike the tier above, and that is the
    # point rather than an oversight: every session in this tier starts a bus
    # of its own with its own XDG roots, and the live canary around each test
    # has to read the REAL desktop to be able to say it did not move.
    "$VENV_PY" -m pytest -q -m sandbox

    echo "== screenshot freshness =="
    "$VENV_PY" tools/check_screenshots.py

    # F16 — prove the LIVE desktop is byte-for-byte unchanged by the run. The
    # baseline lives outside this repo (it is personal configuration); set
    # GTHEME_BASELINE_DIR to the directory holding it to enable this gate.
    if [[ -n "${GTHEME_BASELINE_DIR:-}" ]]; then
        if [[ -x tools/check_live_baseline.sh ]]; then
            echo "== live desktop unchanged =="
            tools/check_live_baseline.sh --baseline-dir "$GTHEME_BASELINE_DIR"
        else
            # A silently skipped safety check is worse than none at all.
            echo "verify.sh: GTHEME_BASELINE_DIR is set but tools/check_live_baseline.sh" >&2
            echo "           is missing or not executable — the live-desktop gate did NOT run." >&2
            exit 1
        fi
    fi
fi

echo "verify.sh: OK"
