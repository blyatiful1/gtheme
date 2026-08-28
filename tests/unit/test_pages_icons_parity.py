"""The icon-set group explains what it is showing, like the pointer one does.

persona-report §3.2: "The icon-set group has no 'only one installed' sentence;
the pointer group does. On a fresh Fedora you get one tile and no idea whether
that is all there is."

Pure text, no display needed: the sentence is chosen by a function and the page
hands it the count.
"""

from __future__ import annotations

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for the page modules")

from gtheme.ui import jargon  # noqa: E402
from gtheme.ui.pages import icons  # noqa: E402


@pytest.mark.parametrize(
    ("count", "must_contain"),
    [
        (0, "could not find any icon sets"),
        (1, "Only one icon set is installed"),
        (4, "Each tile below"),
    ],
)
def test_the_icon_group_explains_whatever_it_is_showing(count, must_contain):
    assert must_contain in icons.icon_set_description(count)


def test_one_tile_is_explained_the_same_way_in_both_groups():
    """The two groups are the same shape and now make the same promise."""
    icon_sentence = icons.icon_set_description(1)
    pointer_sentence = icons.pointer_description(1)
    for sentence in (icon_sentence, pointer_sentence):
        assert "Only one" in sentence
        assert "More can be added from your software app" in sentence
        assert "a Look can bring one with it" in sentence


def test_a_normal_machine_is_not_told_anything_it_does_not_need():
    assert "Only one" not in icons.icon_set_description(6)


def test_the_new_sentences_are_plain_english():
    problems = jargon.check_all(
        [
            ("icons.icon_set_description(0)", icons.icon_set_description(0)),
            ("icons.icon_set_description(1)", icons.icon_set_description(1)),
        ]
    )
    assert problems == [], "\n".join(problems)
