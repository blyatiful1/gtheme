"""Tests for gtheme.system.fontscan.

The parser/round-trip tests need no gi. Family enumeration is exercised
separately under the ``gtk`` marker, since it needs Pango's font map.
"""

from __future__ import annotations

import pytest

from gtheme.system.fontscan import FontSpec, parse_font_description


@pytest.mark.parametrize(
    "text",
    [
        "Adwaita Sans 11 @wght=460",
        "Adwaita Sans Bold 11",
        "Monaspace Neon 11",
        "Adwaita Sans Bold 11 @wght=700,wdth=100",
        "Cantarell",
    ],
)
def test_round_trips_exactly(text: str) -> None:
    assert parse_font_description(text).to_pango_string() == text


def test_parses_pieces_of_the_live_font_name() -> None:
    spec = parse_font_description("Adwaita Sans 11 @wght=460")
    assert spec.family_and_style == "Adwaita Sans"
    assert spec.size == "11"
    assert spec.axes == (("wght", "460"),)


def test_no_axes_no_size() -> None:
    spec = parse_font_description("Cantarell")
    assert spec == FontSpec(family_and_style="Cantarell", size=None, axes=())


def test_multiple_axes_preserve_order() -> None:
    spec = parse_font_description("Iosevka NF 12 @wght=500,wdth=87")
    assert spec.axes == (("wght", "500"), ("wdth", "87"))
    assert spec.axes_dict() == {"wght": "500", "wdth": "87"}


def test_with_axis_changes_only_the_named_axis() -> None:
    spec = parse_font_description("Adwaita Sans 11 @wght=460")
    changed = spec.with_axis("wght", "700")
    assert changed.to_pango_string() == "Adwaita Sans 11 @wght=700"


def test_with_axis_appends_a_new_axis() -> None:
    spec = parse_font_description("Adwaita Sans 11")
    changed = spec.with_axis("wght", "700")
    assert changed.to_pango_string() == "Adwaita Sans 11 @wght=700"


def test_with_size_preserves_axes() -> None:
    spec = parse_font_description("Adwaita Sans 11 @wght=460")
    changed = spec.with_size("13")
    assert changed.to_pango_string() == "Adwaita Sans 13 @wght=460"
