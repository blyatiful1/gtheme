"""The words the app is not allowed to say, and the copy that must obey."""

from __future__ import annotations

import pytest

from gtheme.ui import jargon, registry


def test_the_words_design_names_are_all_banned():
    """DESIGN.md A7 lists these by name. None may quietly fall off the list."""
    for word in (
        "dconf",
        "gsettings",
        "uuid",
        "schema",
        "shell",
        "gtk",
        "hinting",
        "antialiasing",
        "headerbar",
        "legacy applications",
    ):
        assert word in jargon.BANNED, f"{word!r} must stay banned"


def test_banned_words_are_lowercase_and_non_empty():
    for word in jargon.BANNED:
        assert word == word.lower()
        assert word.strip() == word
        assert word


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Blur the gnome-shell panel", "shell"),
        ("Change the dconf value", "dconf"),
        ("The add-on's UUID", "uuid"),
        ("Support for legacy applications", "legacy applications"),
        ("Turn on font hinting", "hinting"),
    ],
)
def test_find_banned_catches_jargon(text, expected):
    assert expected in jargon.find_banned(text)


@pytest.mark.parametrize(
    "text",
    [
        "The picture behind everything",
        "Change everything at once",
        "In a nutshell, this makes windows wobble",  # 'nutshell' is not 'shell'
        "Open your Terminal",  # an allowed phrase
        "Works on GNOME 49 and 50",  # naming the desktop is allowed
    ],
)
def test_find_banned_does_not_false_positive(text):
    assert jargon.find_banned(text) == []


def test_check_suggests_a_replacement_when_there_is_one():
    problems = jargon.check("Pick a shell theme", where="topbar")
    assert problems
    assert "topbar:" in problems[0]
    assert "top bar" in problems[0]


def test_check_is_quiet_on_good_copy():
    assert jargon.check("Warmer colours in the evening") == []


def test_translate_replaces_longest_phrase_first():
    assert jargon.translate("accent color") == "highlight colour"
    assert "add-ons" in jargon.translate("Manage extensions")


def test_every_page_title_and_subtitle_is_jargon_free():
    """The lint that matters: the app's own visible copy."""
    problems = jargon.check_all(
        [(f"{page.id}.title", page.title) for page in registry.MANIFEST]
        + [(f"{page.id}.subtitle", page.subtitle or "") for page in registry.MANIFEST]
    )
    assert problems == []


def test_every_section_name_is_jargon_free():
    assert jargon.check_all([("section", name) for name in registry.SECTIONS]) == []


def test_translation_targets_are_themselves_jargon_free():
    """A replacement that is itself jargon would be a joke at the reader's expense."""
    problems = []
    for source, replacement in jargon.TRANSLATIONS.items():
        problems.extend(jargon.check(replacement, where=f"TRANSLATIONS[{source!r}]"))
    assert problems == []
