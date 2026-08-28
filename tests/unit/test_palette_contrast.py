"""Contrast, measured — persona-report §2.10.

"No contrast-ratio function anywhere in the tree" was the finding, and the
evidence for it was one of gtheme's own bundled Looks: NETRUNNER's dimmed-text
colour sits below the accessibility floor on NETRUNNER's own background, and
nothing in the app or the tooling could have noticed.

So there are two halves here. ``core.color`` learns to measure, against the
numbers the accessibility guidelines fix rather than against gtheme's own
palette maths; and ``gtheme validate`` says what it measures, as a warning that
never fails a Look.
"""

from __future__ import annotations

import tomllib

import pytest

from gtheme.cli import main
from gtheme.core import color
from gtheme.preset.model import palette_contrast_warnings

# --------------------------------------------------------------------------
# the measurement
# --------------------------------------------------------------------------


def test_black_on_white_is_the_maximum_and_a_colour_on_itself_is_the_minimum():
    assert round(color.contrast_ratio("#000000", "#ffffff"), 2) == 21.0
    assert color.contrast_ratio("#3E5578", "#3E5578") == 1.0


def test_it_does_not_matter_which_colour_is_called_the_background():
    assert color.contrast_ratio("#0A111F", "#D8E7F0") == color.contrast_ratio(
        "#D8E7F0", "#0A111F"
    )


def test_the_reading_luminance_is_gamma_corrected_and_the_palette_one_is_not():
    """Two luminances on purpose: one judges readability, one derives Looks.

    ``luminance`` is what ``lighten``/``darken``/``is_dark`` and every bundled
    Look were authored against, so it is left exactly as it was. The
    guidelines' figure undoes the display's gamma curve first, and for a
    mid-grey the two answers are far apart — far enough to move a pair across
    the 3:1 line, which is why the readability check does not reuse the other.
    """
    assert color.luminance("#808080") == pytest.approx(0.502, abs=0.005)
    assert color.relative_luminance("#808080") == pytest.approx(0.2158, abs=0.005)
    assert color.relative_luminance("#ffffff") == pytest.approx(1.0)
    assert color.relative_luminance("#000000") == pytest.approx(0.0)


def test_readable_contrast_is_the_three_to_one_floor():
    assert color.READABLE_CONTRAST == 3.0
    assert color.readable_contrast("#0A111F", "#D8E7F0")  # 14.9:1, the body text
    assert not color.readable_contrast("#0A111F", "#3E5578")  # 2.49:1, the dimmed text


def test_a_colour_that_is_not_a_colour_is_still_an_error():
    with pytest.raises(ValueError):
        color.contrast_ratio("#0A111F", "chartreuse")


# --------------------------------------------------------------------------
# what a Look is warned about
# --------------------------------------------------------------------------


def test_netrunners_dimmed_text_is_caught_on_netrunners_own_background(repo_root):
    """The finding, reproduced against the shipped file rather than a fixture."""
    raw = tomllib.loads((repo_root / "themes" / "netrunner" / "theme.toml").read_text())

    warnings = palette_contrast_warnings(raw["palette"])

    assert any("bright_black" in line for line in warnings), warnings
    assert all("fg" not in line.split()[0] for line in warnings), warnings


def test_the_background_and_the_surfaces_are_not_measured_against_themselves():
    palette = {
        "bg": "#0A111F",
        "surface1": "#111A2C",  # a backdrop, 1.09:1, and not a mistake
        "selection": "#14324A",
        "ansi_black": "#142036",
        "fg": "#D8E7F0",
    }
    assert palette_contrast_warnings(palette) == []


def test_a_palette_that_never_says_which_colour_is_the_background_is_left_alone():
    """NIGHTBLOOM names its backdrop ``void``. Guessing would be worse."""
    assert palette_contrast_warnings({"void": "#0A100C", "jade": "#52E0A4"}) == []


def test_the_line_names_both_colours_and_the_ratio():
    (line,) = palette_contrast_warnings({"bg": "#0A111F", "bright_black": "#3E5578"})
    assert "palette.bright_black" in line
    assert "#3E5578" in line and "#0A111F" in line
    assert "2.49 to 1" in line


def test_the_floor_can_be_raised_for_a_stricter_read():
    palette = {"bg": "#0A111F", "comment": "#5F7396"}  # 3.94:1
    assert palette_contrast_warnings(palette) == []
    assert palette_contrast_warnings(palette, minimum=4.5)


# --------------------------------------------------------------------------
# and what the command says
# --------------------------------------------------------------------------


def _look(directory, palette: str) -> None:
    (directory / "theme.toml").write_text(
        f"""
        format = 2
        [meta]
        name = "demo"
        title = "Demo"
        description = "A demo Look."
        author = "someone"
        version = "1.0.0"
        {palette}
        """,
        encoding="utf-8",
    )


def test_validate_warns_about_a_pair_nobody_can_read_and_still_succeeds(tmp_path, capsys):
    _look(tmp_path, '[palette]\n        bg = "#0A111F"\n        bright_black = "#3E5578"')

    assert main(["validate", str(tmp_path)]) == 0, "a moody palette is not an invalid Look"

    captured = capsys.readouterr()
    assert "warning:" in captured.err
    assert "bright_black" in captured.err
    assert "worth another look" in captured.out


def test_validate_still_says_looks_fine_when_every_pair_reads(tmp_path, capsys):
    _look(tmp_path, '[palette]\n        bg = "#0A111F"\n        fg = "#D8E7F0"')

    assert main(["validate", str(tmp_path)]) == 0
    captured = capsys.readouterr()
    assert "looks fine" in captured.out
    assert captured.err == ""


def test_every_bundled_look_still_validates(repo_root, capsys):
    """Warnings are warnings. None of the shipped Looks may fail the command."""
    themes = repo_root / "themes"
    directories = sorted(d for d in themes.iterdir() if (d / "theme.toml").is_file())
    assert len(directories) >= 4
    for directory in directories:
        assert main(["validate", str(directory)]) == 0, directory.name
    capsys.readouterr()
