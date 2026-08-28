"""Colour arithmetic on ``#RRGGBB`` strings.

Ported unchanged from v1, because it was already right and because the Looks in
``themes/`` were authored against exactly this maths — a palette that derives
``surface1`` by lightening the background 6% produces a different desktop if
the lightening changes. The one thing worth saying about it: everything works
on plain hex text, so a Look's ``[palette]`` stays readable and hand-editable
in a text editor.

Accepts 3-, 4-, 6- and 8-digit bodies. Alpha in an 8-digit body is parsed and
then ignored by :func:`parse_hex`; :func:`alpha` and :func:`hex8` are how alpha
is expressed on the way out.
"""

from __future__ import annotations

__all__ = [
    "RGB",
    "alpha",
    "contrast_ratio",
    "darken",
    "hex8",
    "is_dark",
    "lighten",
    "luminance",
    "mix",
    "READABLE_CONTRAST",
    "parse_hex",
    "readable_contrast",
    "relative_luminance",
    "to_hex",
]

RGB = tuple[int, int, int]

_HEX_DIGITS = set("0123456789abcdefABCDEF")


def parse_hex(value: str) -> RGB:
    """Read ``#RGB`` / ``#RGBA`` / ``#RRGGBB`` / ``#RRGGBBAA`` into ``(r, g, b)``.

    Raises:
        ValueError: the text is not a hex colour of one of those four lengths.
    """
    text = value.strip().lstrip("#")
    if len(text) in (3, 4):
        text = "".join(char * 2 for char in text)
    if len(text) not in (6, 8):
        raise ValueError(f"not a 3/4/6/8-digit hex colour: {value!r}")
    if not all(char in _HEX_DIGITS for char in text):
        raise ValueError(f"not a hex colour: {value!r}")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def to_hex(rgb: RGB) -> str:
    """Render ``(r, g, b)`` as ``#rrggbb``, clamping each channel to 0-255."""
    red, green, blue = (max(0, min(255, round(channel))) for channel in rgb)
    return f"#{red:02x}{green:02x}{blue:02x}"


def _mix(first: RGB, second: RGB, weight: float) -> RGB:
    return tuple(  # type: ignore[return-value]
        round(first[i] + (second[i] - first[i]) * weight) for i in range(3)
    )


def lighten(value: str, pct: float) -> str:
    """Mix ``pct`` percent toward white."""
    return to_hex(_mix(parse_hex(value), (255, 255, 255), pct / 100.0))


def darken(value: str, pct: float) -> str:
    """Mix ``pct`` percent toward black."""
    return to_hex(_mix(parse_hex(value), (0, 0, 0), pct / 100.0))


def mix(first: str, second: str, weight: float = 0.5) -> str:
    """Mix two colours; ``weight`` is how much of ``second`` to use (0..1)."""
    return to_hex(_mix(parse_hex(first), parse_hex(second), weight))


def alpha(value: str, amount: float) -> str:
    """Render as ``rgba(r, g, b, a)`` — the form stylesheets want."""
    red, green, blue = parse_hex(value)
    amount = max(0.0, min(1.0, amount))
    return f"rgba({red}, {green}, {blue}, {amount:g})"


def hex8(value: str, amount: float) -> str:
    """Render as ``#RRGGBBAA`` with ``amount`` in 0..1."""
    red, green, blue = parse_hex(value)
    amount = max(0.0, min(1.0, amount))
    return f"#{red:02x}{green:02x}{blue:02x}{round(amount * 255):02x}"


def luminance(value: str) -> float:
    """Relative brightness, 0..1, weighted the way human eyes are."""
    red, green, blue = (channel / 255.0 for channel in parse_hex(value))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def is_dark(value: str) -> bool:
    """Would light text be readable on this colour?"""
    return luminance(value) < 0.4


#: The ratio below which two colours are too close to read one on the other.
#: Three to one is the accessibility guidelines' floor for large text and for
#: anything that is not text at all — a dimmed line in a terminal, the border of
#: a box. It is deliberately not the 4.5:1 body-text figure: a Look is allowed
#: to be moody, and a check that fired on every atmospheric palette would be
#: switched off rather than acted on. Three to one catches the pairs that are
#: not a choice but a mistake.
READABLE_CONTRAST = 3.0


def relative_luminance(value: str) -> float:
    """Brightness the way the accessibility guidelines define it, 0..1.

    Not :func:`luminance`, and the difference matters. That one weights the
    channels the way an eye does but reads them straight off the hex digits;
    this one undoes the display's gamma curve first, which is what the WCAG
    contrast formula is defined over. The two disagree by enough to move a
    palette from one side of a threshold to the other, so the one used for
    judging readability is spelled out separately rather than reusing the one
    the Look palettes are *derived* with — changing that would change every
    bundled Look.
    """

    def channel(raw: int) -> float:
        scaled = raw / 255.0
        return scaled / 12.92 if scaled <= 0.04045 else ((scaled + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(raw) for raw in parse_hex(value))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(first: str, second: str) -> float:
    """How far apart two colours are to read, from 1 (identical) to 21.

    The WCAG ratio: ``(lighter + 0.05) / (darker + 0.05)`` over
    :func:`relative_luminance`. Symmetrical — which colour is the background
    does not change the answer.
    """
    lighter, darker = sorted((relative_luminance(first), relative_luminance(second)))[::-1]
    return (lighter + 0.05) / (darker + 0.05)


def readable_contrast(first: str, second: str, minimum: float = READABLE_CONTRAST) -> bool:
    """Whether one of these colours can be read on the other."""
    return contrast_ratio(first, second) >= minimum
