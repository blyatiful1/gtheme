"""Tiny ANSI styling helper (no rich dependency).

Honours ``NO_COLOR`` and disables styling when stdout is not a TTY. Colour
depth is detected once at import: 24-bit where COLORTERM (or a known-good
TERM) advertises it, a 256-colour quantized fallback for ``*-256color``
terminals, and plain text otherwise — so gradients and palette swatches
survive SSH sessions and the Linux console instead of emitting garbage.
Glyphs degrade to ASCII when stdout's encoding can't carry them (non-UTF-8
locales), and every helper returns its input untouched when styling is off.
"""

from __future__ import annotations

import os
import re
import sys

_ENABLED = sys.stdout.isatty() and "NO_COLOR" not in os.environ


def _detect_depth() -> int:
    """Colour depth: 16777216 (truecolor), 256, or 0 (don't emit colour)."""
    if not _ENABLED:
        return 0
    if os.environ.get("GTHEME_NO_TRUECOLOR"):  # explicit opt-down
        return 256
    if os.environ.get("COLORTERM", "") in ("truecolor", "24bit"):
        return 16_777_216
    term = os.environ.get("TERM", "")
    # Terminals that support truecolor but don't always export COLORTERM.
    if any(t in term for t in ("kitty", "alacritty", "wezterm", "ghostty", "foot")):
        return 16_777_216
    if "256color" in term:
        return 256
    # ponytail: unknown/basic terminals get no RGB colour at all rather than
    # a lossy 8-colour mapping — swatches show as blanks, nothing breaks.
    return 0


_DEPTH = _detect_depth()


def enabled() -> bool:
    """Whether ANSI styling is active (TTY + not NO_COLOR)."""
    return _ENABLED


# ------------------------------------------------------------------- glyphs ---
def _encodable(sample: str) -> bool:
    enc = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        sample.encode(enc)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


# One switch for every non-ASCII character we print, so a C/latin-1 locale
# gets working ASCII stand-ins instead of a UnicodeEncodeError.
_FANCY = _encodable("✓✗❯·─◉○●↑↓›✦…")
GLYPH = {
    "ok": "✓" if _FANCY else "+",
    "err": "✗" if _FANCY else "x",
    "warn": "!",
    "dot": "·" if _FANCY else "-",
    "pointer": "❯" if _FANCY else ">",
    "rule": "─" if _FANCY else "-",
    "on": "◉" if _FANCY else "[x]",
    "off": "○" if _FANCY else "[ ]",
    "active": "●" if _FANCY else "*",
    "up": "↑" if _FANCY else "^",
    "down": "↓" if _FANCY else "v",
    "crumb": "›" if _FANCY else ">",
    "star": "✦" if _FANCY else "*",
    "ell": "…" if _FANCY else "~",
    "prompt": "›" if _FANCY else ">",
}


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


def reverse(text: str) -> str:
    """Reverse-video ``text`` — the selection-bar idiom that adapts to any
    terminal colour scheme."""
    return style(text, "reverse")


# --------------------------------------------------------- width / truncate ---
_SGR_RE = re.compile(r"\x1b\[[0-9;:]*m")


def strip(text: str) -> str:
    """Remove SGR styling sequences, leaving the visible characters."""
    return _SGR_RE.sub("", text)


def visible_len(text: str) -> int:
    """Printable width of ``text`` (SGR sequences don't count)."""
    return len(strip(text))


def truncate(text: str, width: int) -> str:
    """ANSI-aware cut to ``width`` visible cells, ellipsized, style-balanced."""
    if width <= 0:
        return ""
    if visible_len(text) <= width:
        return text
    budget = width - 1  # room for the ellipsis
    out: list[str] = []
    pos = 0
    for m in _SGR_RE.finditer(text):
        chunk = text[pos : m.start()]
        out.append(chunk[:budget])
        budget -= min(len(chunk), budget)
        out.append(m.group())  # keep escapes so open styles stay balanced
        pos = m.end()
        if budget == 0:
            break
    else:
        out.append(text[pos:][:budget])
    out.append(GLYPH["ell"])
    if _ENABLED:
        out.append("\033[0m")
    return "".join(out)


def pad(text: str, width: int) -> str:
    """ANSI-aware ljust: pad with spaces to ``width`` visible cells."""
    return text + " " * max(0, width - visible_len(text))


# ------------------------------------------------------------ truecolor ---
def _rgb(value) -> tuple[int, int, int]:
    """Coerce a ``#hex`` string or (r,g,b) tuple to an RGB triple."""
    if isinstance(value, (tuple, list)):
        r, g, b = value
        return int(r), int(g), int(b)
    from .color import parse_hex

    return parse_hex(value)


def _ansi256(r: int, g: int, b: int) -> int:
    """Quantize RGB to the xterm-256 palette (grey ramp for near-greys)."""
    if abs(r - g) < 12 and abs(g - b) < 12 and abs(r - b) < 12:
        if r < 8:
            return 16
        if r > 248:
            return 231
        return 232 + (r - 8) * 24 // 241
    return 16 + 36 * (r * 6 // 256) + 6 * (g * 6 // 256) + (b * 6 // 256)


def _code(r: int, g: int, b: int, *, background: bool) -> str:
    """The SGR body for an RGB colour at the detected depth ('' if colourless)."""
    base = 48 if background else 38
    if _DEPTH >= 16_777_216:
        return f"{base};2;{r};{g};{b}"
    if _DEPTH >= 256:
        return f"{base};5;{_ansi256(r, g, b)}"
    return ""


def _paint(text: str, color, *, background: bool) -> str:
    try:
        r, g, b = _rgb(color)
    except (ValueError, TypeError):
        return text
    code = _code(r, g, b, background=background)
    if not code:
        return text
    return f"\033[{code}m{text}\033[0m"


def fg(text: str, color) -> str:
    """Foreground-colour ``text`` with a hex string or (r,g,b) tuple."""
    return _paint(text, color, background=False)


def bg(text: str, color) -> str:
    """Background-colour ``text`` with a hex string or (r,g,b) tuple."""
    return _paint(text, color, background=True)


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def gradient(text: str, start, end) -> str:
    """Colour ``text`` along a left-to-right gradient between two colours."""
    if not _DEPTH or not text:
        return text
    try:
        a, b = _rgb(start), _rgb(end)
    except (ValueError, TypeError):
        return text
    n = max(len(text) - 1, 1)
    out = []
    for i, ch in enumerate(text):
        r, g, bl = _lerp(a, b, i / n)
        out.append(f"\033[{_code(r, g, bl, background=False)}m{ch}")
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


def rule(width: int) -> str:
    """A dim horizontal hairline ``width`` cells wide."""
    return style(GLYPH["rule"] * max(0, width), "grey")


def reset() -> str:
    return "\033[0m" if _ENABLED else ""


def header(text: str) -> str:
    return style(text, "bold", "cyan")


def ok(text: str) -> str:
    return f"{style(GLYPH['ok'], 'green')} {text}"


def warn(text: str) -> str:
    return f"{style(GLYPH['warn'], 'yellow')} {text}"


def err(text: str) -> str:
    return f"{style(GLYPH['err'], 'red')} {text}"


def bullet(text: str) -> str:
    return f"  {style(GLYPH['dot'], 'grey')} {text}"
