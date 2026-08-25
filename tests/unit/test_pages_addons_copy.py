"""Everything the Add-ons page says, and the two helpers that decide names.

No widget is built here. The page module imports libadwaita at import time, so
the tier guard is the same one every UI test uses, but nothing in this file
touches the screen.
"""

from __future__ import annotations

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for the page module")

from gtheme.ego import install as ego_install  # noqa: E402
from gtheme.ego import updates as ego_updates  # noqa: E402
from gtheme.panels.loader import load_corpus  # noqa: E402
from gtheme.ui import jargon, registry  # noqa: E402
from gtheme.ui.pages import addons  # noqa: E402

pytestmark = pytest.mark.gtk


# -- the manifest ----------------------------------------------------------


def test_the_manifest_factory_is_this_module_s_build():
    """The page exists because the manifest already named it. Prove it lands."""
    assert registry.load_factory("addons") is addons.build


# -- names -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("uuid", "name", "expected"),
    [
        ("dash-to-dock@micxgx.gmail.com", "Dash to Dock", "Dash to Dock"),
        # The desktop hands back the identifier as the name when it could not
        # read a real one. Showing that would put an email address in the list.
        ("dash-to-dock@micxgx.gmail.com", "dash-to-dock@micxgx.gmail.com", "Dash to dock"),
        ("just-perfection-desktop@just-perfection", "", "Just perfection desktop"),
        ("Vitals@CoreCoding.com", "", "Vitals"),
        ("weird", "", "weird"),
    ],
)
def test_a_name_is_never_an_identifier(uuid, name, expected):
    assert addons.display_name(uuid, name) == expected


def test_a_name_is_never_empty():
    assert addons.display_name("", "")


def test_a_long_description_becomes_one_line():
    text = "First line.\n\nSecond paragraph that goes on " + "and on " * 40
    shortened = addons.summary_of(text)
    assert "\n" not in shortened
    assert len(shortened) <= 141
    assert shortened.endswith("…")


def test_a_short_description_is_left_alone():
    assert addons.summary_of("  Keeps your screen awake. ") == "Keeps your screen awake."


# -- copy ------------------------------------------------------------------


def test_every_sentence_this_page_says_is_free_of_jargon():
    problems = jargon.check_all(
        [(f"COPY[{key!r}]", text) for key, text in addons.COPY.items()]
    )
    assert problems == []


def test_the_group_titles_are_free_of_jargon():
    problems = jargon.check_all(
        [("category", title) for title in addons.CATEGORY_TITLES.values()]
        + [("category", addons.OTHER_CATEGORY_TITLE)]
        + [("sort", label) for _value, label in addons.SORTS]
    )
    assert problems == []


def test_no_sentence_is_a_second_wording_of_a_service_sentence():
    """The install and update paths own their wording; the page reuses it.

    Two ways of saying "it starts working after you log out and back in" is one
    way too many: the day one of them changes, the app is telling two stories
    about the same thing.
    """
    service_sentences = {
        text for text in ego_install.COPY.values() if isinstance(text, str)
    } | set(ego_updates.COPY.values())
    for key, text in addons.COPY.items():
        assert text not in service_sentences, f"COPY[{key!r}] restates a service sentence"


def test_the_page_shows_the_service_sentences_rather_than_its_own():
    """The honest ones, specifically: they are the ones worth pinning."""
    import inspect

    text = inspect.getsource(addons)
    assert 'UPDATE_COPY["staged"]' in text
    assert 'UPDATE_COPY["withdrawn"]' in text
    # Install outcomes reach the user as ``report.message``, which IS
    # ``ego.install.COPY`` — never re-worded here.
    assert "report.message" in text


def test_every_placeholder_in_the_copy_is_one_the_page_fills_in():
    known = {"name", "count", "text", "author", "stars"}
    for key, text in addons.COPY.items():
        for chunk in text.split("{")[1:]:
            field = chunk.split("}")[0]
            assert field in known, f"COPY[{key!r}] has an unknown placeholder {field!r}"


# -- categories ------------------------------------------------------------


def test_every_curated_panel_lands_in_a_group_this_page_draws():
    """A panel with a category nobody renders would silently vanish."""
    corpus = load_corpus()
    assert corpus.problems == []
    categories = {panel.target.category for panel in corpus.panels}
    assert categories, "the curated panels did not load"
    assert categories <= set(addons.CATEGORY_ORDER), (
        f"panels use categories this page does not draw: "
        f"{sorted(categories - set(addons.CATEGORY_ORDER))}"
    )


def test_every_group_this_page_draws_has_a_title():
    for category in addons.CATEGORY_ORDER:
        assert addons.CATEGORY_TITLES[category].strip()
