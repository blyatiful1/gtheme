"""Tiny ANSI styling helper (no rich dependency).

Honours ``NO_COLOR`` and disables styling when stdout is not a TTY. Also
provides 24-bit truecolor helpers (gradients, palette swatches) used by the
interactive menu — all of which degrade to plain text when colour is off.
"""

from __future__ import annotations

import os
import sys

_ENABLED = sys.stdout.isatty() and "NO_COLOR" not in os.environ
# Truecolor is gated separately: most modern terminals support it, but honour
# an explicit opt-out and the common COLORTERM signal when present.
_TRUECOLOR = _ENABLED and os.environ.get("GTHEME_NO_TRUECOLOR") is None


def enabled() -> bool:
    """Whether ANSI styling is active (TTY + not NO_COLOR)."""
    return _ENABLED


_CODES = {
    "reset": "0",
    "bold": "1",
    "dim": "2",
    "italic": "3",
    "underline": "4",
    "reverse": "7",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
    "white": "37",
    "grey": "90",
}


def style(text: str, *names: str) -> str:
    if not _ENABLED or not names:
        return text
    codes = ";".join(_CODES[n] for n in names if n in _CODES)
    return f"\033[{codes}m{text}\033[0m"


# ------------------------------------------------------------ truecolor ---
def _rgb(value) -> tuple[int, int, int]:
    """Coerce a ``#hex`` string or (r,g,b) tuple to an RGB triple."""
    if isinstance(value, (tuple, list)):
        r, g, b = value
        return int(r), int(g), int(b)
    from .color import parse_hex

    return parse_hex(value)


def fg(text: str, color) -> str:
    """Foreground-colour ``text`` with a hex string or (r,g,b) tuple."""
    if not _TRUECOLOR:
        return text
    try:
        r, g, b = _rgb(color)
    except (ValueError, TypeError):
        return text
    return f"\033[38;2;{r};{g};{b}m{text}\033[0m"


def bg(text: str, color) -> str:
    """Background-colour ``text`` with a hex string or (r,g,b) tuple."""
    if not _TRUECOLOR:
        return text
    try:
        r, g, b = _rgb(color)
    except (ValueError, TypeError):
        return text
    return f"\033[48;2;{r};{g};{b}m{text}\033[0m"


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def gradient(text: str, start, end) -> str:
    """Colour ``text`` along a left-to-right gradient between two colours."""
    if not _TRUECOLOR or not text:
        return text
    try:
        a, b = _rgb(start), _rgb(end)
    except (ValueError, TypeError):
        return text
    n = max(len(text) - 1, 1)
    out = []
    for i, ch in enumerate(text):
        r, g, bl = _lerp(a, b, i / n)
        out.append(f"\033[38;2;{r};{g};{bl}m{ch}")
    out.append("\033[0m")
    return "".join(out)


def swatch(color, width: int = 2) -> str:
    """A solid colour block ``width`` cells wide (falls back to spaces)."""
    block = " " * width
    return bg(block, color)


def swatches(palette: dict[str, str], limit: int = 8, width: int = 2) -> str:
    """A row of palette swatches; silently skips unparseable entries."""
    out = []
    for value in list(palette.values())[:limit]:
        try:
            out.append(swatch(value, width))
        except (ValueError, TypeError):
            continue
    return "".join(out)


def reset() -> str:
    return "\033[0m" if _ENABLED else ""


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
