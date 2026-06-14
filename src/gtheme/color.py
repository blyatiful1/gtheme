"""Colour primitives for the palette render engine.

Everything works on ``#RRGGBB`` strings. These back the Jinja filters
(``lighten``/``darken``/``mix``/``alpha``) and the ANSI-16 derivation, so a
theme author can define ~10 named colours and have a whole desktop rendered.
"""

from __future__ import annotations

RGB = tuple[int, int, int]


_HEX_DIGITS = set("0123456789abcdefABCDEF")


def parse_hex(value: str) -> RGB:
    s = value.strip().lstrip("#")
    # Accept 3 (#RGB), 4 (#RGBA), 6 (#RRGGBB), or 8 (#RRGGBBAA) digit bodies.
    if len(s) in (3, 4):
        s = "".join(c * 2 for c in s)  # expand short form: each nibble doubled
    if len(s) not in (6, 8):
        raise ValueError(f"not a 3/4/6/8-digit hex colour: {value!r}")
    if not all(c in _HEX_DIGITS for c in s):
        raise ValueError(f"not a hex colour: {value!r}")
    # For 8-digit (#RRGGBBAA) bodies take the RGB channels, ignore alpha.
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def to_hex(rgb: RGB) -> str:
    r, g, b = (max(0, min(255, round(c))) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _mix(a: RGB, b: RGB, t: float) -> RGB:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def lighten(value: str, pct: float) -> str:
    """Mix ``pct`` percent toward white."""
    return to_hex(_mix(parse_hex(value), (255, 255, 255), pct / 100.0))


def darken(value: str, pct: float) -> str:
    """Mix ``pct`` percent toward black."""
    return to_hex(_mix(parse_hex(value), (0, 0, 0), pct / 100.0))


def mix(a: str, b: str, t: float = 0.5) -> str:
    """Mix two colours; ``t`` is the weight of ``b`` (0..1)."""
    return to_hex(_mix(parse_hex(a), parse_hex(b), t))


def alpha(value: str, a: float) -> str:
    """Return an ``rgba(r, g, b, a)`` string (handy for GTK css)."""
    r, g, b = parse_hex(value)
    a = max(0.0, min(1.0, a))
    return f"rgba({r}, {g}, {b}, {a:g})"


def hex8(value: str, a: float) -> str:
    """Return ``#RRGGBBAA`` with ``a`` in 0..1."""
    r, g, b = parse_hex(value)
    a = max(0.0, min(1.0, a))
    return f"#{r:02x}{g:02x}{b:02x}{round(a * 255):02x}"


def luminance(value: str) -> float:
    r, g, b = (c / 255.0 for c in parse_hex(value))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def is_dark(value: str) -> bool:
    return luminance(value) < 0.4
