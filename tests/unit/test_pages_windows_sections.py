"""175 shortcuts, in groups, with a box to narrow them (persona-report §3.2).

"175 shortcuts in two flat accordions, corpus-ordered, no sub-headings, no
filter box. Ctrl+F is the real answer and nothing on the page says so."

The splitting is pure and is tested against the shipped corpus, because the
value of a section is only real if every row of the real file lands in one. The
filter is ``gtk`` and is driven by typing into the entry the page built.
"""

from __future__ import annotations

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for the page modules")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from gtheme.core import backends  # noqa: E402
from gtheme.panels.loader import load_domains  # noqa: E402
from gtheme.ui import jargon  # noqa: E402
from gtheme.ui.pages import windows  # noqa: E402
from gtheme.ui.rowindex import RowIndex  # noqa: E402


class FakeWindow:
    def __init__(self) -> None:
        self.rows = RowIndex()
        self.shown: list[str] = []

    def show_page(self, page_id: str) -> None:
        self.shown.append(page_id)


def _domain(domain_id: str):
    domains, _problems = load_domains()
    return next(domain for domain in domains if domain.id == domain_id)


# --------------------------------------------------------------------------
# the sections
# --------------------------------------------------------------------------


@pytest.mark.parametrize("domain_id", ["shortcuts", "mediakeys"])
def test_every_row_of_the_real_file_lands_in_exactly_one_section(domain_id):
    domain = _domain(domain_id)
    sections = windows.shortcut_sections(domain)

    placed = [row.id for _title, rows in sections for row in rows]
    assert sorted(placed) == sorted(row.id for row in domain.rows)
    assert len(placed) == len(set(placed)), "a row cannot be in two sections"


@pytest.mark.parametrize("domain_id", ["shortcuts", "mediakeys"])
def test_no_section_is_the_whole_file_again(domain_id):
    """A single accordion holding everything is the thing being fixed."""
    domain = _domain(domain_id)
    sections = windows.shortcut_sections(domain)

    assert len(sections) >= 5
    biggest = max(len(rows) for _title, rows in sections)
    assert biggest < len(domain.rows) / 2


def test_the_sections_are_named_in_words_and_never_left_empty():
    for domain_id in ("shortcuts", "mediakeys"):
        for title, rows in windows.shortcut_sections(_domain(domain_id)):
            assert rows, f"{title} is an empty heading"
            assert title[0].isupper()
    problems = jargon.check_all(
        [
            (f"windows.SECTIONS[{domain_id}]", title)
            for domain_id, rules in windows.SECTIONS.items()
            for title, _patterns in rules
        ]
        + [(f"windows.COPY[{k!r}]", v) for k, v in windows.COPY.items()]
    )
    assert problems == [], "\n".join(problems)


def test_a_few_shortcuts_land_where_a_person_would_look_for_them():
    sections = dict(windows.shortcut_sections(_domain("shortcuts")))
    where = {
        row.key: title for title, rows in sections.items() for row in rows
    }
    assert where["switch-to-workspace-left"] == "Desktops and screens"
    assert where["move-to-monitor-up"] == "Desktops and screens"
    assert where["screenshot"] == "Pictures of your screen"
    assert where["close"] == "The window you are using"
    assert where["toggle-overview"] == "The top bar, the overview and menus"

    media = dict(windows.shortcut_sections(_domain("mediakeys")))
    media_where = {row.key: title for title, rows in media.items() for row in rows}
    assert media_where["volume-up"] == "Sound"
    assert media_where["magnifier"] == "Ease of use"
    # Its own title is "Lock which way up the screen is" — not a video control.
    assert media_where["rotate-video-lock"] == "The keyboard, the touchpad and the screen"


def test_an_unknown_domain_is_left_as_one_section():
    domain = _domain("windows")
    assert [title for title, _rows in windows.shortcut_sections(domain)] == [domain.title]


# --------------------------------------------------------------------------
# the filter, and the hint
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="module")
def _adw():
    if not Gtk.init_check():
        pytest.skip("no display is available for GTK — run under gtk4-broadwayd")
    Adw.init()


@pytest.fixture
def page(memory_settings):
    """The real page, built against an in-memory store.

    ``memory_settings`` rather than a hand-made backend: the isolation guard in
    ``tests/conftest.py`` counts seams by fixture name, and a ``mutating`` test
    that quietly skipped would look exactly like one that passed.
    """
    window = FakeWindow()
    with backends.use_backend(memory_settings):
        widget = windows.build(window)
    return widget


@pytest.mark.gtk
@pytest.mark.mutating
def test_the_page_says_that_ctrl_f_searches_everything(page):
    descriptions = " ".join(
        group.get_description() or "" for group in _all(page, Adw.PreferencesGroup)
    )
    assert "Ctrl+F" in descriptions
    assert "123 shortcuts" in descriptions and "52 keys" in descriptions


@pytest.mark.gtk
@pytest.mark.mutating
def test_typing_in_the_box_narrows_the_list_to_what_matches(page):
    boxes = _filter_boxes(page)
    assert set(boxes) == {"gtheme-filter-shortcuts", "gtheme-filter-mediakeys"}

    # Matched against the words the rows are written in, which are the same
    # words the app-wide search matches — not against GNOME's key names.
    _type(boxes["gtheme-filter-shortcuts"], "picture of")

    visible = [
        row
        for row in _all(page, Adw.ExpanderRow)
        if row.get_visible() and row.get_title() in _section_titles("shortcuts")
    ]
    assert {row.get_title() for row in visible} == {"Pictures of your screen"}
    assert all(row.get_expanded() for row in visible), "a filter nobody can see is none"


@pytest.mark.gtk
@pytest.mark.mutating
def test_emptying_the_box_puts_everything_back_and_closes_it_again(page):
    box = _filter_boxes(page)["gtheme-filter-shortcuts"]
    _type(box, "picture of")
    _type(box, "")

    expanders = [
        row
        for row in _all(page, Adw.ExpanderRow)
        if row.get_title() in _section_titles("shortcuts")
    ]
    assert all(row.get_visible() for row in expanders)
    assert not any(row.get_expanded() for row in expanders)


@pytest.mark.gtk
@pytest.mark.mutating
def test_a_search_that_matches_nothing_says_so_rather_than_going_blank(page):
    box = _filter_boxes(page)["gtheme-filter-shortcuts"]

    _type(box, "xyzzy")

    assert not any(
        row.get_visible()
        for row in _all(page, Adw.ExpanderRow)
        if row.get_title() in _section_titles("shortcuts")
    )
    said = [
        row.get_title()
        for row in _all(page, Adw.ActionRow)
        if row.get_visible() and "xyzzy" in (row.get_title() or "")
    ]
    assert said, "nothing on screen explained the empty list"


def _type(entry: Gtk.SearchEntry, text: str) -> None:
    """Type into the box the way somebody would, without a main loop.

    ``Gtk.SearchEntry`` holds ``search-changed`` back for a moment so that a
    filter does not run on every keystroke. That delay is a timeout, and a unit
    test has no loop to run it in, so the signal the page really listens to is
    emitted here instead of waiting for a timer that will never fire.
    """
    entry.set_text(text)
    entry.emit("search-changed")


def _filter_boxes(page: Gtk.Widget) -> dict[str, Gtk.SearchEntry]:
    """This page's own filter boxes, by name — libadwaita builds others."""
    return {
        entry.get_name(): entry
        for entry in _all(page, Gtk.SearchEntry)
        if entry.get_name().startswith("gtheme-filter-")
    }


def _section_titles(domain_id: str) -> set[str]:
    return {title for title, _patterns in windows.SECTIONS[domain_id]}


def _all(widget: Gtk.Widget, kind: type) -> list:
    found = []
    if isinstance(widget, kind):
        found.append(widget)
    child = widget.get_first_child()
    while child is not None:
        found.extend(_all(child, kind))
        child = child.get_next_sibling()
    return found
