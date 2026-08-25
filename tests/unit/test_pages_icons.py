"""Icons & Pointer: the grids, the samples, and the honest one-tile case."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for the page library")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402
from test_pages_style_common import build_page, make_window  # noqa: E402

from gtheme.system.iconscan import IconThemeEntry  # noqa: E402
from gtheme.ui import jargon  # noqa: E402
from gtheme.ui.pages import _style_common as common  # noqa: E402
from gtheme.ui.pages import icons  # noqa: E402

pytestmark = pytest.mark.gtk

ICON_KEY = "gsettings:org.gnome.desktop.interface icon-theme"


def _entry(name: str, *, cursors: bool = False) -> IconThemeEntry:
    return IconThemeEntry(
        directory_name=name,
        display_name=name.replace("-", " "),
        path=Path("/nowhere") / name,
        is_cursor_theme=cursors,
    )


def _tiles(grid: Gtk.FlowBox) -> list[Gtk.ToggleButton]:
    return [w for w in _walk(grid) if isinstance(w, Gtk.ToggleButton)]


def _walk(widget: Gtk.Widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from _walk(child)
        child = child.get_next_sibling()


# --------------------------------------------------------------------------
# the copy
# --------------------------------------------------------------------------


def test_every_sentence_this_page_says_is_plain_english():
    problems = jargon.check_all([(f"icons.COPY[{k!r}]", v) for k, v in icons.COPY.items()])
    assert problems == [], "\n".join(problems)


@pytest.mark.parametrize(
    ("count", "must_contain"),
    [
        (0, "could not find any pointer styles"),
        (1, "Only one pointer style is installed"),
        (4, "cannot be drawn inside a window"),
    ],
)
def test_the_pointer_group_explains_whatever_it_is_showing(count, must_contain):
    """One tile is the normal state on a stock desktop, and looks broken unless said."""
    assert must_contain in icons.pointer_description(count)


# --------------------------------------------------------------------------
# the grid
# --------------------------------------------------------------------------


@pytest.mark.mutating
def test_one_tile_per_installed_set_and_the_current_one_is_checked(memory_settings):
    row = common.corpus_rows()["org.gnome.desktop.interface:icon-theme"]
    memory_settings.set(ICON_KEY, "'Papirus'")
    grid, _refresh = icons.icon_grid(
        memory_settings,
        row,
        [_entry("Adwaita"), _entry("Papirus"), _entry("breeze")],
        sample=lambda _e: Gtk.Label(label="."),
    )
    tiles = _tiles(grid)
    assert len(tiles) == 3
    assert [t.get_active() for t in tiles] == [False, True, False]


@pytest.mark.mutating
def test_clicking_a_tile_writes_that_set(memory_settings):
    row = common.corpus_rows()["org.gnome.desktop.interface:icon-theme"]
    memory_settings.set(ICON_KEY, "'Adwaita'")
    grid, _refresh = icons.icon_grid(
        memory_settings,
        row,
        [_entry("Adwaita"), _entry("Papirus")],
        sample=lambda _e: Gtk.Label(label="."),
    )
    _tiles(grid)[1].set_active(True)
    assert memory_settings.get(ICON_KEY) == "'Papirus'"


@pytest.mark.mutating
def test_a_set_that_is_not_installed_leaves_every_tile_unchecked(memory_settings):
    """Checking the first tile instead would say the desktop holds something it does not."""
    row = common.corpus_rows()["org.gnome.desktop.interface:icon-theme"]
    memory_settings.set(ICON_KEY, "'Gone'")
    grid, _refresh = icons.icon_grid(
        memory_settings,
        row,
        [_entry("Adwaita"), _entry("Papirus")],
        sample=lambda _e: Gtk.Label(label="."),
    )
    assert not any(t.get_active() for t in _tiles(grid))
    assert memory_settings.get(ICON_KEY) == "'Gone'"


@pytest.mark.mutating
def test_an_empty_grid_is_a_grid_and_not_a_crash(memory_settings):
    row = common.corpus_rows()["org.gnome.desktop.interface:cursor-theme"]
    grid, _refresh = icons.icon_grid(memory_settings, row, [])
    assert _tiles(grid) == []


def test_a_tile_shows_that_set_s_own_icons():
    """Four pictures, from a private theme rather than the one in use."""
    box = icons.sample_images(_entry("Adwaita"))
    images = [w for w in _walk(box) if isinstance(w, Gtk.Image)]
    assert len(images) == len(icons.SAMPLE_ICONS)
    assert all(image.get_paintable() is not None for image in images)


# --------------------------------------------------------------------------
# the page
# --------------------------------------------------------------------------


@pytest.mark.mutating
def test_the_page_shows_every_setting_it_was_made_responsible_for(tmp_path, memory_settings):
    window = make_window(tmp_path)
    build_page(icons, window, memory_settings)
    for descriptor_id in common.surfaced_ids("icons"):
        assert descriptor_id in window.rows, f"{descriptor_id} was not rendered"


@pytest.mark.mutating
def test_the_pointer_size_offers_the_three_sizes_gnome_uses(tmp_path, memory_settings):
    window = make_window(tmp_path)
    build_page(icons, window, memory_settings)
    entry = window.rows.lookup("org.gnome.desktop.interface:cursor-size")
    assert entry is not None
    assert isinstance(entry.widget, Adw.ComboRow)
    labels = [
        entry.widget.get_model().get_string(i)
        for i in range(entry.widget.get_model().get_n_items())
    ]
    assert labels[:3] == ["Normal", "Large", "Very large"]


@pytest.mark.mutating
def test_each_grid_carries_the_put_this_back_button(tmp_path, memory_settings):
    window = make_window(tmp_path)
    page = build_page(icons, window, memory_settings)
    resets = [
        w
        for w in _walk(page)
        if isinstance(w, Gtk.Button) and w.get_tooltip_text() == "Put this back the way it was"
    ]
    assert len(resets) >= 2, "the icon set and the pointer style both need one"


@pytest.mark.mutating
def test_the_pointer_words_a_person_would_search_for_find_the_row(tmp_path, memory_settings):
    window = make_window(tmp_path)
    build_page(icons, window, memory_settings)
    assert window.rows.search("cursor")
    assert window.rows.search("where is my mouse")
