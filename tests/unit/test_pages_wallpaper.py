"""Tests for gtheme.ui.pages.wallpaper.

Split the same way the module is: the pure helpers (no widget, no display)
need no marker; anything that constructs a row or a page is marked ``gtk``.
Nothing here presents a window, and every settings write goes through
``MemoryBackend`` — see ``tests/conftest.py`` for the isolation guard this
relies on.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for the wallpaper page")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from gtheme.core import backends as core_backends  # noqa: E402
from gtheme.system.wallpapers import WallpaperEntry  # noqa: E402
from gtheme.ui.pages import wallpaper  # noqa: E402
from gtheme.ui.rowindex import RowIndex  # noqa: E402

LIGHT_ID = "org.gnome.desktop.background:picture-uri"
DARK_ID = "org.gnome.desktop.background:picture-uri-dark"


class FakeWindow:
    """The slice of ``Window`` a page needs: ``rows`` and ``toast``."""

    def __init__(self) -> None:
        self.rows = RowIndex()
        self.toasts: list[str] = []

    def toast(self, text: str, **_kwargs: Any) -> None:
        self.toasts.append(text)


def _entry(name: str, filename: Path, filename_dark: Path | None = None) -> WallpaperEntry:
    return WallpaperEntry(
        name=name,
        filename=filename,
        filename_dark=filename_dark,
        options="zoom",
        shade_type="solid",
        primary_color=None,
        secondary_color=None,
        source_xml=Path("/nowhere.xml"),
    )


# --------------------------------------------------------------------------
# pure helpers
# --------------------------------------------------------------------------


def test_unquote_strips_gvariant_string_quoting():
    assert wallpaper._unquote("'file:///a/b.png'") == "file:///a/b.png"
    assert wallpaper._unquote('"x"') == "x"
    assert wallpaper._unquote(None) is None


def test_custom_filename_keeps_a_plausible_suffix_and_is_unique():
    first = wallpaper.custom_filename(Path("/tmp/holiday.PNG"))
    second = wallpaper.custom_filename(Path("/tmp/holiday.PNG"))
    assert first.startswith("custom-")
    assert first.endswith(".png")
    assert first != second  # collision-proof


def test_custom_filename_drops_an_unusable_suffix():
    assert "." not in wallpaper.custom_filename(Path("/tmp/noext"))


def test_tile_source_ordinary_picture_is_itself():
    entry = _entry("Plain", Path("/usr/share/backgrounds/gnome/adwaita-l.jxl"))
    value, source, is_slideshow = wallpaper.tile_source(entry, dark=False)
    assert value == source == Path("/usr/share/backgrounds/gnome/adwaita-l.jxl")
    assert is_slideshow is False


def test_tile_source_dark_prefers_filename_dark():
    entry = _entry(
        "Paired",
        Path("/usr/share/backgrounds/gnome/adwaita-l.jxl"),
        filename_dark=Path("/usr/share/backgrounds/gnome/adwaita-d.jxl"),
    )
    value, _source, _slideshow = wallpaper.tile_source(entry, dark=True)
    assert value == Path("/usr/share/backgrounds/gnome/adwaita-d.jxl")


def test_tile_source_dark_falls_back_to_light_with_no_dark_variant():
    entry = _entry("Light only", Path("/usr/share/backgrounds/gnome/adwaita-l.jxl"))
    value, _source, _slideshow = wallpaper.tile_source(entry, dark=True)
    assert value == Path("/usr/share/backgrounds/gnome/adwaita-l.jxl")


def test_tile_source_slideshow_uses_first_static_frame_as_thumbnail(tmp_path: Path):
    day = tmp_path / "day.png"
    night = tmp_path / "night.png"
    day.touch()
    night.touch()
    slideshow = tmp_path / "timed.xml"
    slideshow.write_text(
        f"""<background>
  <starttime><year>2024</year><month>1</month><day>1</day>
  <hour>0</hour><minute>0</minute><second>0</second></starttime>
  <static><duration>36000</duration><file>{day}</file></static>
  <transition type="overlay"><duration>60</duration><from>{day}</from><to>{night}</to></transition>
</background>""",
        encoding="utf-8",
    )
    entry = _entry("Timed", slideshow)
    value, source, is_slideshow = wallpaper.tile_source(entry, dark=False)
    assert value == slideshow  # written to the setting exactly as catalogued
    assert source == day  # but shown as its first static frame
    assert is_slideshow is True


def test_load_domain_rows_finds_the_wallpaper_toml():
    rows = wallpaper._load_domain_rows()
    assert set(rows) >= {
        "picture-uri",
        "picture-uri-dark",
        "picture-options",
        "primary-color",
        "secondary-color",
        "color-shading-type",
    }
    assert rows["picture-uri"].kind.value == "picker"


# --------------------------------------------------------------------------
# widget construction — needs a display (offscreen is fine)
# --------------------------------------------------------------------------


@pytest.mark.gtk
@pytest.mark.mutating
def test_build_returns_a_preferences_page_with_two_grids_and_style_group(memory_settings):
    window = FakeWindow()
    with core_backends.use_backend(memory_settings):
        page = wallpaper.build(window)
    assert isinstance(page, Adw.PreferencesPage)
    # Both picker rows registered themselves, with their own FlowBox widget.
    light = window.rows.lookup(LIGHT_ID)
    dark = window.rows.lookup(DARK_ID)
    assert light is not None and isinstance(light.widget, Gtk.FlowBox)
    assert dark is not None and isinstance(dark.widget, Gtk.FlowBox)
    # The style rows rode along too.
    assert window.rows.lookup("org.gnome.desktop.background:picture-options") is not None


@pytest.mark.gtk
@pytest.mark.mutating
def test_picking_a_catalogue_tile_writes_the_setting_and_updates_selection(memory_settings):
    window = FakeWindow()
    with core_backends.use_backend(memory_settings):
        wallpaper.build(window)
        entry = window.rows.lookup(LIGHT_ID)
        flow = entry.widget
        first_tile = flow.get_child_at_index(0)
        assert first_tile is not None, "the real machine's catalogue must offer at least one picture"
        expected = first_tile.wallpaper_value

        flow.emit("child-activated", first_tile)

        assert memory_settings.get("gsettings:org.gnome.desktop.background picture-uri") == (
            f"'{expected}'"
        )
        selected = flow.get_selected_children()
        assert selected and selected[0] is first_tile


@pytest.mark.gtk
@pytest.mark.mutating
def test_lock_screen_group_states_the_mirroring_honestly(memory_settings):
    window = FakeWindow()
    with core_backends.use_backend(memory_settings):
        page = wallpaper.build(window)
    texts: list[str] = []
    child = page.get_first_child()
    while child is not None:
        texts.append(_collect_text(child))
        child = child.get_next_sibling()
    joined = " ".join(texts)
    assert "light background picture" in joined
    assert "dark version" in joined


def _collect_text(widget: Gtk.Widget) -> str:
    parts: list[str] = []
    for getter in ("get_title", "get_subtitle", "get_description"):
        method = getattr(widget, getter, None)
        if method is not None:
            try:
                value = method()
            except TypeError:
                continue
            if isinstance(value, str):
                parts.append(value)
    child = widget.get_first_child()
    while child is not None:
        parts.append(_collect_text(child))
        child = child.get_next_sibling()
    return " ".join(parts)


@pytest.mark.gtk
@pytest.mark.mutating
def test_custom_picture_is_copied_validated_and_written(memory_settings, tmp_dest_root, tmp_path):
    import gi as _gi

    _gi.require_version("Gdk", "4.0")
    from gi.repository import Gdk, GdkPixbuf

    source = tmp_path / "holiday.png"
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 4, 4)
    pixbuf.savev(str(source), "png", [], [])

    window = FakeWindow()
    row = wallpaper._load_domain_rows()["picture-uri"]
    done = {"called": False}

    with core_backends.use_backend(memory_settings):
        wallpaper._install_custom_wallpaper(
            window, memory_settings, row, source, lambda: done.__setitem__("called", True)
        )

    assert done["called"], window.toasts
    written = memory_settings.get("gsettings:org.gnome.desktop.background picture-uri")
    assert written.startswith("'file://")
    dest_uri = written.strip("'")
    dest_path = Path(dest_uri.removeprefix("file://"))
    assert dest_path.is_file()
    assert dest_path.is_relative_to(tmp_dest_root / ".local" / "share" / "backgrounds" / "gtheme")
    # It really is a decodable picture, not just bytes with the right name.
    Gdk.Texture.new_from_filename(str(dest_path))


@pytest.mark.gtk
@pytest.mark.mutating
def test_custom_picture_that_is_not_an_image_is_rejected_and_removed(
    memory_settings, tmp_dest_root, tmp_path
):
    source = tmp_path / "not-a-picture.png"
    source.write_bytes(b"this is definitely not an image file")

    window = FakeWindow()
    row = wallpaper._load_domain_rows()["picture-uri"]
    key = "gsettings:org.gnome.desktop.background picture-uri"

    with core_backends.use_backend(memory_settings):
        before = memory_settings.get(key)
        wallpaper._install_custom_wallpaper(window, memory_settings, row, source, lambda: None)
        after = memory_settings.get(key)

    assert any("doesn't look like a picture" in text for text in window.toasts)
    assert after == before  # never written
    backgrounds_dir = tmp_dest_root / ".local" / "share" / "backgrounds" / "gtheme"
    assert list(backgrounds_dir.glob("custom-*")) == []  # the bad copy was removed
