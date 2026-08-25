"""The two config editors, on their own — everything else depends on them."""

from __future__ import annotations

from gtheme.terminal.kv import IniFile, KeyValueFile

SAMPLE = """\
# a comment
theme = old

font-family = A
font-family = B
opacity = 0.9

# trailing note
"""


def test_a_file_that_is_not_edited_comes_back_byte_identical():
    assert KeyValueFile.parse(SAMPLE).render() == SAMPLE


def test_setting_a_key_keeps_its_place():
    parsed = KeyValueFile.parse(SAMPLE)
    parsed.set("theme", "new")
    lines = parsed.render().splitlines()
    assert lines[1] == "theme = new"
    assert lines[0] == "# a comment"


def test_setting_a_key_that_repeats_collapses_it_to_one():
    """A second line for a single-valued key would silently win."""
    parsed = KeyValueFile.parse("theme = a\ntheme = b\n")
    parsed.set("theme", "c")
    assert parsed.render() == "theme = c\n"


def test_repeated_keys_survive_and_can_be_replaced_as_a_block():
    parsed = KeyValueFile.parse(SAMPLE)
    assert parsed.values("font-family") == ["A", "B"]
    parsed.set_repeated("font-family", ["X", "Y", "Z"])
    rendered = parsed.render()
    assert rendered.count("font-family = ") == 3
    assert rendered.index("font-family = X") < rendered.index("opacity")


def test_a_new_key_lands_before_a_trailing_blank_line():
    parsed = KeyValueFile.parse("a = 1\n\n")
    parsed.set("b", "2")
    assert parsed.render() == "a = 1\nb = 2\n\n"


def test_the_last_value_wins_when_a_key_repeats():
    parsed = KeyValueFile.parse("x = 1\nx = 2\n")
    assert parsed.value("x") == "2"


def test_a_line_with_no_separator_is_left_alone():
    parsed = KeyValueFile.parse("just some text\nk = v\n")
    parsed.set("k", "w")
    assert parsed.render() == "just some text\nk = w\n"


INI = """\
# top note
[general]
framerate = 60

[color]
# gradient note
gradient = 0
gradient_color_1 = '#111'
gradient_color_2 = '#222'

[smoothing]
noise = 40
"""


def test_ini_round_trips_untouched():
    assert IniFile.parse(INI).render() == INI


def test_ini_set_only_touches_the_named_section():
    parsed = IniFile.parse(INI)
    parsed.set("color", "gradient", "1")
    rendered = parsed.render()
    assert "gradient = 1" in rendered
    assert "framerate = 60" in rendered
    assert "# gradient note" in rendered
    assert parsed.value("general", "framerate") == "60"


def test_ini_adds_a_key_inside_its_section_not_at_the_end_of_the_file():
    parsed = IniFile.parse(INI)
    parsed.set("color", "gradient_count", "2")
    lines = parsed.render().splitlines()
    assert lines.index("gradient_count = 2") < lines.index("[smoothing]")


def test_ini_creates_a_missing_section():
    parsed = IniFile.parse("[general]\nframerate = 60\n")
    parsed.set("color", "gradient", "1")
    assert parsed.render().endswith("[color]\ngradient = 1\n")


def test_ini_remove_prefixed_clears_a_whole_family_of_keys():
    parsed = IniFile.parse(INI)
    assert parsed.remove_prefixed("color", "gradient_color_") == 2
    rendered = parsed.render()
    assert "gradient_color_" not in rendered
    assert "gradient = 0" in rendered
    assert "noise = 40" in rendered


def test_ini_ignores_a_key_of_the_same_name_in_another_section():
    parsed = IniFile.parse("[a]\nk = 1\n\n[b]\nk = 2\n")
    parsed.set("b", "k", "9")
    assert parsed.value("a", "k") == "1"
    assert parsed.value("b", "k") == "9"
