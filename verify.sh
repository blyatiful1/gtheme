#!/usr/bin/env bash
# The canonical check. Exit 0 means the project is green.
#
#   ./verify.sh           lint + unit/regression/gtk tiers
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

if [[ ! -x "$VENV_PY" ]]; then
    echo "verify.sh: .venv is missing. Create it with:" >&2
    echo "  uv venv --system-site-packages .venv && uv pip install -e '.[dev]'" >&2
    exit 1
fi

FULL=0
if [[ "${1:-}" == "--full" || "${GTHEME_FULL:-0}" == "1" ]]; then
    FULL=1
fi

echo "== ruff =="
"$VENV_RUFF" check .

echo "== pytest (unit + regression + gtk) =="
# The sandbox tier is excluded by addopts in pyproject.toml.
"$VENV_PY" -m pytest -q

if [[ "$FULL" == "1" ]]; then
    # Stamped BEFORE the page walk, checked after it. This is what makes
    # "fresh screenshots" mean "from this run" rather than "from some run".
    GTHEME_SCREENSHOT_RUN_START="$(date +%s)"
    export GTHEME_SCREENSHOT_RUN_START

    echo "== pytest (sandbox) =="
    # NEVER '|| true': a red sandbox is a red check.
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
