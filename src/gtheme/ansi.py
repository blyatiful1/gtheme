"""Tiny ANSI styling helper (no rich dependency).

Honours ``NO_COLOR`` and disables styling when stdout is not a TTY.
"""

from __future__ import annotations

import os
import sys

_ENABLED = sys.stdout.isatty() and "NO_COLOR" not in os.environ

_CODES = {
    "reset": "0",
    "bold": "1",
    "dim": "2",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
    "grey": "90",
}


def style(text: str, *names: str) -> str:
    if not _ENABLED or not names:
        return text
    codes = ";".join(_CODES[n] for n in names if n in _CODES)
    return f"\033[{codes}m{text}\033[0m"


def header(text: str) -> str:
    return style(text, "bold", "cyan")


def ok(text: str) -> str:
    return f"{style('✓', 'green')} {text}"


def warn(text: str) -> str:
    return f"{style('!', 'yellow')} {text}"


def err(text: str) -> str:
    return f"{style('✗', 'red')} {text}"


def bullet(text: str) -> str:
    return f"  {style('·', 'grey')} {text}"
