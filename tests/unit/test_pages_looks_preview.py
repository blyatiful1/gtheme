"""The mock preview card: colour picking, and drawing that actually runs.

Marked ``gtk`` because it constructs libadwaita widgets and real render nodes.
Nothing here is presented, mapped or shown: :func:`paint_preview` draws into a
bare ``Gtk.Snapshot``, which is what makes it possible to prove the drawing code
executes without putting a window on the developer's screen.
"""

from __future__ import annotations

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for the preview card")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from gtheme.ui.preview import (  # noqa: E402
    ASPECT_RATIO,
    PreviewCard,
    PreviewColors,
    build_preview,
    colors_from_palette,
    load_texture,
    paint_preview,
)

pytestmark = pytest.mark.gtk


@pytest.fixture(autouse=True, scope="module")
def _adw():
    if not Gtk.init_check():
        pytest.skip("no display is available for GTK — run under gtk4-broadwayd")
    Adw.init()


NIGHTBLOOM = {
    "void": "#0A100C",
    "surface": "#0F1712",
    "jade": "#52E0A4",
    "bone": "#E8E4D6",
    "amber": "#F5C04A",
}


def test_palette_roles_come_from_the_names_authors_actually_use():
    colors = colors_from_palette(NIGHTBLOOM)
    assert colors.background == "#0A100C"
    assert colors.surface == "#0F1712"
    assert colors.accent == "#52E0A4"
    assert colors.text == "#E8E4D6"


def test_the_accent_leads_the_dot_row():
    colors = colors_from_palette(NIGHTBLOOM)
    assert colors.dots[0] == "#52E0A4"
    assert len(colors.dots) <= 5
    assert len(set(colors.dots)) == len(colors.dots)


def test_a_palette_with_no_colours_falls_back_rather_than_failing():
    assert colors_from_palette({}) == PreviewColors.fallback()
    assert colors_from_palette(None) == PreviewColors.fallback()


def test_entries_that_are_not_colours_are_ignored_not_refused():
    """One stray line in a palette must not cost the tile its picture."""
    colors = colors_from_palette({"bg": "#101010", "note": "written by hand", "accent": "#ff0000"})
    assert colors.background == "#101010"
    assert colors.accent == "#ff0000"


def test_an_unnamed_palette_still_yields_four_roles():
    colors = colors_from_palette({"one": "#111111", "two": "#222222"})
    assert colors.background == "#111111"
    assert colors.surface == "#222222"
    assert colors.accent and colors.text


def test_painting_produces_a_render_node():
    snapshot = Gtk.Snapshot()
    paint_preview(snapshot, colors_from_palette(NIGHTBLOOM), 320.0, 180.0)
    assert snapshot.to_node() is not None


def test_painting_with_a_wallpaper_produces_a_render_node(repo_root):
    picture = repo_root / "themes" / "nightbloom" / "wallpaper" / "nightbloom-glasshouse.png"
    texture = load_texture(picture)
    assert texture is not None, "the bundled Look's picture should load"
    snapshot = Gtk.Snapshot()
    paint_preview(snapshot, colors_from_palette(NIGHTBLOOM), 320.0, 180.0, texture=texture)
    assert snapshot.to_node() is not None


def test_painting_nothing_at_zero_size_is_safe():
    """A tile is drawn before it is allocated. That must not crash or draw."""
    snapshot = Gtk.Snapshot()
    paint_preview(snapshot, PreviewColors.fallback(), 0.0, 0.0)
    assert snapshot.to_node() is None


def test_a_missing_picture_loads_as_nothing(tmp_path):
    assert load_texture(None) is None
    assert load_texture(tmp_path / "not-here.png") is None
    broken = tmp_path / "broken.png"
    broken.write_text("this is not a picture", encoding="utf-8")
    assert load_texture(broken) is None


def test_a_look_with_a_picture_shows_the_picture(repo_root):
    frame = build_preview(
        palette=NIGHTBLOOM,
        pictures=[repo_root / "themes" / "nightbloom" / "wallpaper" / "nightbloom-glasshouse.png"],
    )
    assert isinstance(frame.get_child(), Gtk.Picture)


def test_a_look_without_a_picture_draws_its_palette(tmp_path):
    frame = build_preview(palette=NIGHTBLOOM, picture=tmp_path / "missing.png")
    child = frame.get_child()
    assert isinstance(child, PreviewCard)
    assert child.colors.accent == "#52E0A4"


def test_every_tile_is_the_shape_of_a_screen():
    frame = build_preview(palette=NIGHTBLOOM)
    assert frame.get_ratio() == pytest.approx(ASPECT_RATIO)


def test_the_card_can_be_constructed_and_recoloured():
    card = PreviewCard()
    assert card.colors == PreviewColors.fallback()
    card.set_colors(colors_from_palette(NIGHTBLOOM))
    assert card.colors.accent == "#52E0A4"
