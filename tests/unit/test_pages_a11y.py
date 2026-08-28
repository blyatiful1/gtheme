"""Every picture-only control has a name (persona-report §2.10).

The finding was a grep: ``alternative_text|AccessibleProperty`` over ``src/``
returned one line, the accent dots on the Colours page. Everything else a
person is asked to *choose by looking at* — the wallpaper grid, the icon-set
tiles, the pointer tiles, the picture on the Home card — was announced as an
unnamed image, or as nothing at all.

Two things are checked, and they are checked separately on purpose. That the
property is *set* is asked of the real widget through GTK's own accessibility
test helpers. What it *says* is asked of the pure functions that compose the
text, because GTK exposes no way to read an accessible property's value back.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for the page modules")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from gtheme.core import backends as core_backends  # noqa: E402
from gtheme.core.settings_backend import MemoryBackend  # noqa: E402
from gtheme.prefs import Prefs  # noqa: E402
from gtheme.system.iconscan import IconThemeEntry  # noqa: E402
from gtheme.ui.pages import _style_common as common  # noqa: E402
from gtheme.ui.pages import home, icons, wallpaper  # noqa: E402
from gtheme.ui.rowindex import RowIndex  # noqa: E402
from gtheme.ui.widgets import a11y  # noqa: E402

pytestmark = pytest.mark.gtk

LIGHT_ID = "org.gnome.desktop.background:picture-uri"


@pytest.fixture(autouse=True, scope="module")
def _adw():
    if not Gtk.init_check():
        pytest.skip("no display is available for GTK — run under gtk4-broadwayd")
    Adw.init()


class FakeWindow:
    def __init__(self, prefs: Any = None) -> None:
        self.rows = RowIndex()
        self.prefs = prefs
        self.toasts: list[str] = []

    def toast(self, text: str, **_kwargs: Any) -> None:
        self.toasts.append(text)

    def show_page(self, _page_id: str) -> None:  # pragma: no cover - not used here
        pass


# --------------------------------------------------------------------------
# the helpers themselves
# --------------------------------------------------------------------------


def test_the_helpers_set_the_properties_they_claim_to():
    button = Gtk.ToggleButton()
    a11y.name(button, "Papirus icon set")
    a11y.describe(button, "The small pictures used for apps")
    picture = Gtk.Image()
    a11y.hide_from_screen_readers(picture)

    assert Gtk.test_accessible_has_property(button, Gtk.AccessibleProperty.LABEL)
    assert Gtk.test_accessible_has_property(button, Gtk.AccessibleProperty.DESCRIPTION)
    assert Gtk.test_accessible_has_state(picture, Gtk.AccessibleState.HIDDEN)


# --------------------------------------------------------------------------
# the wallpaper grid
# --------------------------------------------------------------------------


@pytest.mark.mutating
def test_every_wallpaper_tile_is_named_captioned_and_described(memory_settings):
    window = FakeWindow()
    with core_backends.use_backend(memory_settings):
        wallpaper.build(window)
    flow = window.rows.lookup(LIGHT_ID).widget

    tiles = []
    index = 0
    while (child := flow.get_child_at_index(index)) is not None:
        tiles.append(child)
        index += 1
    assert tiles, "the real machine's catalogue must offer at least one picture"

    for tile in tiles:
        name = tile.get_tooltip_text()
        assert name, "a tile with no name at all"
        # The name: what a screen reader announces, which a tooltip is not.
        assert Gtk.test_accessible_has_property(tile, Gtk.AccessibleProperty.LABEL)
        # The caption: visible, so nobody has to hover to find out what this is.
        assert name in _labels(tile), "no visible caption under the tile"
        # And the picture inside it is not an unnamed image.
        picture = _first(tile, Gtk.Picture)
        assert picture is not None
        assert picture.get_alternative_text() in (
            name,
            wallpaper.tile_name(name, is_slideshow=True),
        )


# --------------------------------------------------------------------------
# the icon and pointer tiles
# --------------------------------------------------------------------------


def _entry(name: str) -> IconThemeEntry:
    from pathlib import Path

    return IconThemeEntry(
        directory_name=name,
        display_name=name.replace("-", " "),
        path=Path("/usr/share/icons") / name,
        is_cursor_theme=False,
    )


@pytest.mark.mutating
def test_icon_tiles_carry_a_name_and_their_sample_icons_stay_quiet(memory_settings):
    row = common.corpus_rows()["org.gnome.desktop.interface:icon-theme"]
    grid, _refresh = icons.icon_grid(
        memory_settings,
        row,
        [_entry("Papirus-Dark")],
        sample=lambda _entry: Gtk.Image(icon_name="folder"),
        noun="icon set",
    )

    button = _first(grid, Gtk.ToggleButton)
    assert button is not None
    assert Gtk.test_accessible_has_property(button, Gtk.AccessibleProperty.LABEL)
    sample = _first(button, Gtk.Image)
    assert sample is not None
    assert Gtk.test_accessible_has_state(sample, Gtk.AccessibleState.HIDDEN)


# --------------------------------------------------------------------------
# the Home card
# --------------------------------------------------------------------------


@pytest.mark.mutating
def test_the_home_card_picture_says_what_it_is(config_dir, tmp_path):
    backend = MemoryBackend()
    picture_file = tmp_path / "morning_light.png"
    picture_file.write_bytes(b"")
    backend.set(home.KEYS["wallpaper"], f"'{picture_file.as_uri()}'")

    page = home.HomePage(FakeWindow(Prefs()), backend=backend, thumbnails=False)

    assert page._picture.get_alternative_text() == (
        "Your background picture: Morning light"
    )


@pytest.mark.mutating
def test_with_no_background_picture_it_says_that_instead(config_dir):
    backend = MemoryBackend()
    backend.set(home.KEYS["wallpaper"], "''")
    backend.set(home.KEYS["wallpaper-dark"], "''")
    page = home.HomePage(FakeWindow(Prefs()), backend=backend, thumbnails=False)
    assert page._picture.get_alternative_text() == home.COPY["picture-none"]


@pytest.mark.mutating
def test_the_highlight_dot_is_a_picture_of_a_word_already_said(config_dir):
    """The row reads "Highlight colour: Blue"; the dot must not add noise."""
    backend = MemoryBackend()
    backend.set(home.KEYS["highlight"], "'blue'")
    page = home.HomePage(FakeWindow(Prefs()), backend=backend, thumbnails=False)

    dot = getattr(page, "_dot", None)
    assert dot is not None
    assert Gtk.test_accessible_has_state(dot, Gtk.AccessibleState.HIDDEN)


# --------------------------------------------------------------------------


def _first(widget: Gtk.Widget, kind: type):
    if isinstance(widget, kind):
        return widget
    child = widget.get_first_child()
    while child is not None:
        found = _first(child, kind)
        if found is not None:
            return found
        child = child.get_next_sibling()
    return None


def _labels(widget: Gtk.Widget) -> list[str]:
    found: list[str] = []
    if isinstance(widget, Gtk.Label):
        found.append(widget.get_label())
    child = widget.get_first_child()
    while child is not None:
        found.extend(_labels(child))
        child = child.get_next_sibling()
    return found
