"""Pango font descriptions: parsing, round-tripping, and family enumeration.

``font-name`` and friends are Pango font description strings, and GNOME 50
uses the variable-font axis suffix live: the font this app is running under
right now is ``'Adwaita Sans 11 @wght=460'`` (gnome-domains.md §2). A parser
that only understands ``family size`` silently drops the ``@wght=460`` on the
next write — the axis value the user picked reverts to whatever the font's
default weight is. :func:`parse_font_description` keeps every piece as raw
text specifically so :meth:`FontSpec.to_pango_string` reproduces the original
string byte-for-byte when nothing changed, and only the piece that changed
differs when something did.

Family *enumeration* needs Pango's font map, which needs ``gi`` — that import
is contained inside :func:`scan_font_families` so the parser above stays
testable without a display.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "FontFamilyEntry",
    "FontSpec",
    "parse_font_description",
    "scan_font_families",
]

# A trailing " @axis=value[,axis=value...]" suffix.
_AXIS = r"[A-Za-z][A-Za-z0-9]*=[^,\s]+"
_AXES_RE = re.compile(rf"\s+@(?P<axes>{_AXIS}(?:,{_AXIS})*)\s*$")
# A trailing numeric size token, once any axis suffix has been stripped.
_SIZE_RE = re.compile(r"\s+(?P<size>\d+(?:\.\d+)?)\s*$")


@dataclass(frozen=True)
class FontSpec:
    """A parsed Pango font description, kept as raw text per field.

    ``family_and_style`` deliberately does not separate the family name from
    style words ("Bold", "Semi-Condensed", ...) — Pango's own grammar needs a
    weight/style/stretch keyword table to do that split correctly, and this
    app never needs to: it only ever reads a value back to show it, or writes
    a whole description back out.
    """

    family_and_style: str
    #: Raw size text (e.g. ``"11"``), or ``None`` if the description had none.
    size: str | None
    #: Ordered ``(axis, value)`` pairs from the ``@...`` suffix, raw text.
    axes: tuple[tuple[str, str], ...] = ()

    def axes_dict(self) -> dict[str, str]:
        return dict(self.axes)

    def to_pango_string(self) -> str:
        """Reassemble the description. Round-trips :func:`parse_font_description`."""
        parts = [self.family_and_style]
        if self.size is not None:
            parts.append(self.size)
        text = " ".join(parts)
        if self.axes:
            text += " @" + ",".join(f"{k}={v}" for k, v in self.axes)
        return text

    def with_size(self, size: str) -> FontSpec:
        return FontSpec(self.family_and_style, size, self.axes)

    def with_axis(self, axis: str, value: str) -> FontSpec:
        """Set (or add) one axis, preserving the order of the others."""
        remaining = tuple((k, v) for k, v in self.axes if k != axis)
        return FontSpec(self.family_and_style, self.size, (*remaining, (axis, value)))


def parse_font_description(text: str) -> FontSpec:
    """Parse a Pango font description string, e.g. ``'Adwaita Sans 11 @wght=460'``."""
    remaining = text.strip()
    axes: tuple[tuple[str, str], ...] = ()

    axes_match = _AXES_RE.search(remaining)
    if axes_match:
        axes = tuple(
            (part.split("=", 1)[0], part.split("=", 1)[1])
            for part in axes_match.group("axes").split(",")
        )
        remaining = remaining[: axes_match.start()]

    size: str | None = None
    size_match = _SIZE_RE.search(remaining)
    if size_match:
        size = size_match.group("size")
        remaining = remaining[: size_match.start()]

    return FontSpec(family_and_style=remaining.strip(), size=size, axes=axes)


@dataclass(frozen=True)
class FontFamilyEntry:
    """One installed font family, as Pango reports it."""

    name: str
    is_monospace: bool


def scan_font_families() -> list[FontFamilyEntry]:
    """Enumerate installed font families via Pango's default font map.

    Contains the only ``gi`` import in this module — kept inside the function
    body so the rest of :mod:`fontscan` (the part with logic worth testing)
    never requires a display or PyGObject to import.
    """
    import gi

    gi.require_version("PangoCairo", "1.0")
    from gi.repository import PangoCairo

    fontmap = PangoCairo.FontMap.get_default()
    families = fontmap.list_families()
    seen: dict[str, bool] = {}
    for family in families:
        name = family.get_name()
        if name not in seen:
            seen[name] = bool(family.is_monospace())
    return sorted(
        (FontFamilyEntry(name=n, is_monospace=m) for n, m in seen.items()),
        key=lambda f: f.name.casefold(),
    )
