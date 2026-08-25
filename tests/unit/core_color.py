"""Colour arithmetic, ported unchanged from v1 — and it has to stay unchanged.

The Looks in ``themes/`` were authored against exactly this maths. A palette
that derives its surface colours by lightening the background 6% produces a
visibly different desktop if the lightening changes, and the author is not
around to re-tune it. So these are pinned to concrete values rather than to
properties.
"""

from __future__ import annotations

import pytest

from gtheme.core.color import (
    alpha,
    darken,
    hex8,
    is_dark,
    lighten,
    luminance,
    mix,
    parse_hex,
    to_hex,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("#ffffff", (255, 255, 255)),
        ("#000000", (0, 0, 0)),
        ("ff8800", (255, 136, 0)),
        ("#f80", (255, 136, 0)),
        ("#F80", (255, 136, 0)),
        ("#7fd6a2", (127, 214, 162)),
        # Four and eight digit bodies carry alpha, which parse_hex drops.
        ("#f80c", (255, 136, 0)),
        ("#ff8800cc", (255, 136, 0)),
        ("  #7fd6a2  ", (127, 214, 162)),
    ],
)
def test_hex_is_parsed(text, expected):
    assert parse_hex(text) == expected


@pytest.mark.parametrize("text", ["", "#", "#12345", "#1234567", "zzzzzz", "#gg0000", "12"])
def test_nonsense_is_refused(text):
    with pytest.raises(ValueError):
        parse_hex(text)


def test_channels_are_clamped_rather_than_wrapped():
    """A wrapped channel turns a nearly-white colour black, which is worse."""
    assert to_hex((300, -20, 128)) == "#ff0080"


def test_lightening_and_darkening_are_the_values_the_looks_were_authored_against():
    assert lighten("#000000", 50) == "#808080"
    assert darken("#ffffff", 50) == "#808080"
    # Checked against the v1 module itself, not computed by hand: the whole
    # point of pinning these is that they match what the Looks were tuned to.
    assert lighten("#101a14", 6) == "#1e2822"
    assert darken("#7fd6a2", 25) == "#5fa07a"


def test_the_extremes_are_exact():
    assert lighten("#123456", 0) == "#123456"
    assert lighten("#123456", 100) == "#ffffff"
    assert darken("#123456", 100) == "#000000"


def test_mixing_weights_the_second_colour():
    assert mix("#000000", "#ffffff", 0.5) == "#808080"
    assert mix("#000000", "#ffffff", 0.0) == "#000000"
    assert mix("#000000", "#ffffff", 1.0) == "#ffffff"


def test_alpha_renders_the_form_stylesheets_want():
    assert alpha("#7fd6a2", 0.5) == "rgba(127, 214, 162, 0.5)"
    assert alpha("#7fd6a2", 1) == "rgba(127, 214, 162, 1)"


def test_alpha_is_clamped_both_ways():
    assert alpha("#000000", 5) == "rgba(0, 0, 0, 1)"
    assert alpha("#000000", -3) == "rgba(0, 0, 0, 0)"


def test_eight_digit_output():
    assert hex8("#7fd6a2", 1) == "#7fd6a2ff"
    assert hex8("#7fd6a2", 0) == "#7fd6a200"
    assert hex8("#7fd6a2", 0.5) == "#7fd6a280"


def test_brightness_is_weighted_the_way_eyes_are():
    """Green looks brighter than blue at the same value, and the maths agrees."""
    assert luminance("#000000") == 0.0
    assert luminance("#ffffff") == pytest.approx(1.0)
    assert luminance("#00ff00") > luminance("#0000ff")


def test_dark_enough_for_light_text():
    assert is_dark("#101a14")
    assert is_dark("#000000")
    assert not is_dark("#ffffff")
    assert not is_dark("#7fd6a2")


def test_a_round_trip_through_hex_is_lossless():
    for text in ("#101a14", "#7fd6a2", "#ff8800", "#000000", "#ffffff"):
        assert to_hex(parse_hex(text)) == text
