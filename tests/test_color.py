"""Contract tests for the colour primitives (gtheme.color)."""

from __future__ import annotations

import pytest

from gtheme import color


# --- parse_hex -------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        ("#000000", (0, 0, 0)),
        ("#ffffff", (255, 255, 255)),
        ("#FFFFFF", (255, 255, 255)),
        ("ffffff", (255, 255, 255)),  # leading '#' optional
        ("#7dc75b", (125, 199, 91)),
        ("#fff", (255, 255, 255)),  # 3-digit short form
        ("#abc", (170, 187, 204)),
        ("#11223344", (17, 34, 51)),  # 8-digit: RGB taken, alpha ignored
    ],
)
def test_parse_hex_valid(value, expected):
    assert color.parse_hex(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "#",
        "#12345",       # 5 digits not allowed
        "#1234567",     # 7 digits not allowed
        "#gggggg",      # non-hex chars
        "#zz",
        "not a colour",
        "-00000",       # leading minus must be rejected
        "#-00000",
    ],
)
def test_parse_hex_invalid(value):
    with pytest.raises(ValueError):
        color.parse_hex(value)


# --- lighten / darken / mix ------------------------------------------------


def test_lighten_moves_toward_white():
    out = color.parse_hex(color.lighten("#000000", 50))
    assert out == (128, 128, 128)


def test_lighten_full_is_white():
    assert color.parse_hex(color.lighten("#123456", 100)) == (255, 255, 255)


def test_darken_moves_toward_black():
    out = color.parse_hex(color.darken("#ffffff", 50))
    assert out == (128, 128, 128)


def test_darken_full_is_black():
    assert color.parse_hex(color.darken("#abcdef", 100)) == (0, 0, 0)


def test_mix_midpoint():
    assert color.parse_hex(color.mix("#000000", "#ffffff", 0.5)) == (128, 128, 128)


def test_mix_endpoints():
    assert color.parse_hex(color.mix("#102030", "#ffffff", 0.0)) == (16, 32, 48)
    assert color.parse_hex(color.mix("#102030", "#ffffff", 1.0)) == (255, 255, 255)


# --- hex8 alpha clamping ---------------------------------------------------


def test_hex8_alpha_clamped_high():
    # alpha above 1.0 clamps to ff (8-char body)
    out = color.hex8("#7dc75b", 2.0)
    assert out == "#7dc75bff"
    assert len(out) == 9  # '#' + 8 hex digits


def test_hex8_alpha_clamped_low():
    # negative alpha clamps to 00
    out = color.hex8("#7dc75b", -0.5)
    assert out == "#7dc75b00"
    assert len(out) == 9


def test_hex8_alpha_mid():
    out = color.hex8("#000000", 0.5)
    assert out == "#00000080"
