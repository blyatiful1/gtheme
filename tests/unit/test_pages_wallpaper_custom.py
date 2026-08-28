"""A picture you choose yourself joins the catalogue (persona-report §3.2).

The old behaviour: the picture was copied to
``~/.local/share/backgrounds/gtheme/custom-9f2c1a7b3e05.png``, the setting was
pointed at it, and that was the end of it. It never appeared in the grid it was
chosen from, on that launch or any later one, and the only name it had was the
random one. The picker also refused slideshow XML — the kind of background
three of the four bundled Looks set.

Split like the module: the naming and the catalogue writing are pure and need
no display; anything that builds a widget or decodes a picture is ``gtk``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for the wallpaper page")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Gio", "2.0")
from gi.repository import Gio, Gtk  # noqa: E402

from gtheme.core import backends as core_backends  # noqa: E402
from gtheme.system.wallpapers import scan_wallpaper_catalogue  # noqa: E402
from gtheme.ui.pages import wallpaper  # noqa: E402
from gtheme.ui.rowindex import RowIndex  # noqa: E402

LIGHT_KEY = "gsettings:org.gnome.desktop.background picture-uri"


class FakeWindow:
    def __init__(self) -> None:
        self.rows = RowIndex()
        self.toasts: list[str] = []

    def toast(self, text: str, **_kwargs: Any) -> None:
        self.toasts.append(text)


def _png(path: Path) -> Path:
    from gi.repository import GdkPixbuf

    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 4, 4)
    pixbuf.savev(str(path), "png", [], [])
    return path


def _slideshow(path: Path, frame: Path) -> Path:
    path.write_text(
        "<background><starttime><year>2026</year><month>1</month><day>1</day>"
        "<hour>0</hour><minute>0</minute><second>0</second></starttime>"
        f"<static><duration>3600.0</duration><file>{frame}</file></static>"
        "</background>",
        encoding="utf-8",
    )
    return path


# --------------------------------------------------------------------------
# names a person can read
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("holiday_beach-2024.JPG", "Holiday beach 2024"),
        ("DSC00194.png", "DSC00194"),
        ("a picture   with  spaces.png", "A picture with spaces"),
        ("_-_.png", "Your own picture"),
    ],
)
def test_readable_name_comes_from_the_file_the_reader_picked(filename, expected):
    assert wallpaper.readable_name(Path("/somewhere") / filename) == expected


def test_readable_name_does_not_run_away_with_a_very_long_file_name():
    name = wallpaper.readable_name(Path("/x/" + "word " * 40 + ".png"))
    assert len(name) <= 48


def test_the_copy_on_disk_keeps_its_collision_proof_name():
    """Two people's ``photo.jpg`` must not become one file. Only the *label*
    changes; the name in the folder stays random on purpose."""
    assert wallpaper.custom_filename(Path("/x/photo.jpg")).startswith("custom-")


def test_a_slideshow_tile_says_so_in_words_not_only_in_a_badge():
    assert wallpaper.tile_name("Sunrise", is_slideshow=True) == (
        "Sunrise — changes during the day"
    )
    assert wallpaper.tile_name("Sunrise", is_slideshow=False) == "Sunrise"


# --------------------------------------------------------------------------
# the catalogue itself
# --------------------------------------------------------------------------


@pytest.mark.mutating
def test_a_recorded_picture_is_readable_by_the_real_catalogue_scanner(tmp_dest_root):
    """End to end through the scanner every other tile in the grid comes from."""
    picture = Path("/usr/share/backgrounds/example.png")

    assert wallpaper.record_in_catalogue("Holiday beach", picture) == "Holiday beach"

    catalogue = wallpaper.custom_catalogue_path()
    assert catalogue.is_file()
    entries = scan_wallpaper_catalogue([catalogue.parent])
    assert [(entry.name, entry.filename) for entry in entries] == [
        ("Holiday beach", picture)
    ]


@pytest.mark.mutating
def test_a_second_picture_is_added_rather_than_replacing_the_first(tmp_dest_root):
    wallpaper.record_in_catalogue("First", Path("/pictures/one.png"))
    wallpaper.record_in_catalogue("Second", Path("/pictures/two.png"))

    entries = scan_wallpaper_catalogue([wallpaper.custom_catalogue_path().parent])
    assert [entry.name for entry in entries] == ["First", "Second"]


@pytest.mark.mutating
def test_two_pictures_with_the_same_name_are_told_apart(tmp_dest_root):
    assert wallpaper.record_in_catalogue("Beach", Path("/a/beach.png")) == "Beach"
    assert wallpaper.record_in_catalogue("Beach", Path("/b/beach.png")) == "Beach (2)"

    entries = scan_wallpaper_catalogue([wallpaper.custom_catalogue_path().parent])
    assert [entry.name for entry in entries] == ["Beach", "Beach (2)"]


@pytest.mark.mutating
def test_a_name_with_xml_in_it_survives_the_round_trip(tmp_dest_root):
    """The file is read by every picker on the machine, not only by gtheme."""
    wallpaper.record_in_catalogue("Fish & <chips>", Path("/a/fish.png"))

    entries = scan_wallpaper_catalogue([wallpaper.custom_catalogue_path().parent])
    assert [entry.name for entry in entries] == ["Fish & <chips>"]


@pytest.mark.mutating
def test_a_catalogue_that_will_not_parse_is_replaced_not_refused(tmp_dest_root):
    catalogue = wallpaper.custom_catalogue_path()
    catalogue.parent.mkdir(parents=True, exist_ok=True)
    catalogue.write_text("this is not xml at all <<<", encoding="utf-8")

    wallpaper.record_in_catalogue("Rescued", Path("/a/one.png"))

    entries = scan_wallpaper_catalogue([catalogue.parent])
    assert [entry.name for entry in entries] == ["Rescued"]


# --------------------------------------------------------------------------
# choosing one
# --------------------------------------------------------------------------


@pytest.mark.gtk
def test_the_picker_accepts_slideshows_as_well_as_pictures():
    def info(name: str, content_type: str) -> Gio.FileInfo:
        item = Gio.FileInfo()
        item.set_name(name)
        item.set_display_name(name)
        item.set_content_type(content_type)
        return item

    filters = wallpaper.custom_file_filters()
    first = filters.get_item(0)

    assert first.match(info("sunrise.xml", "application/xml"))
    assert first.match(info("holiday.png", "image/png"))
    assert filters.get_n_items() == 2, "and a slideshows-only choice as well"


@pytest.mark.gtk
@pytest.mark.mutating
def test_choosing_a_picture_names_it_and_offers_it_back(
    memory_settings, tmp_dest_root, tmp_path
):
    source = _png(tmp_path / "holiday_beach.png")
    window = FakeWindow()
    row = wallpaper._load_domain_rows()["picture-uri"]
    added: list[Any] = []

    with core_backends.use_backend(memory_settings):
        wallpaper._install_custom_wallpaper(
            window, memory_settings, row, source, lambda: None, on_added=added.append
        )

    # It is on the desktop…
    written = memory_settings.get(LIGHT_KEY)
    assert written.startswith("'file://")
    # …it is in the catalogue, under a name somebody can read…
    entries = scan_wallpaper_catalogue([wallpaper.custom_catalogue_path().parent])
    assert [entry.name for entry in entries] == ["Holiday beach"]
    assert "custom-" not in entries[0].name
    # …and the grid was handed it, so it appears without a restart.
    assert [entry.name for entry in added] == ["Holiday beach"]
    assert added[0].filename.as_uri() == written.strip("'")
    assert any("Holiday beach" in text for text in window.toasts), window.toasts


@pytest.mark.gtk
@pytest.mark.mutating
def test_a_slideshow_can_be_chosen_and_is_written_as_the_slideshow(
    memory_settings, tmp_dest_root, tmp_path
):
    frame = _png(tmp_path / "morning.png")
    source = _slideshow(tmp_path / "all day.xml", frame)
    window = FakeWindow()
    row = wallpaper._load_domain_rows()["picture-uri"]

    with core_backends.use_backend(memory_settings):
        wallpaper._install_custom_wallpaper(
            window, memory_settings, row, source, lambda: None
        )

    written = memory_settings.get(LIGHT_KEY)
    assert written.endswith(".xml'"), written
    assert Path(written.strip("'").removeprefix("file://")).is_file()


@pytest.mark.gtk
@pytest.mark.mutating
def test_a_slideshow_whose_pictures_are_gone_is_refused_and_says_why(
    memory_settings, tmp_dest_root, tmp_path
):
    source = _slideshow(tmp_path / "broken.xml", tmp_path / "not-there.png")
    window = FakeWindow()
    row = wallpaper._load_domain_rows()["picture-uri"]

    with core_backends.use_backend(memory_settings):
        before = memory_settings.get(LIGHT_KEY)
        wallpaper._install_custom_wallpaper(
            window, memory_settings, row, source, lambda: None
        )
        assert memory_settings.get(LIGHT_KEY) == before

    assert any("could not find the pictures" in text for text in window.toasts)
    copies = (tmp_dest_root / ".local" / "share" / "backgrounds" / "gtheme").glob("custom-*")
    assert list(copies) == [], "the copy of a file that cannot be used is not kept"


@pytest.mark.gtk
@pytest.mark.mutating
def test_the_chosen_picture_lands_in_the_grid_without_a_restart(
    memory_settings, tmp_dest_root, tmp_path
):
    """Driven through the page's own callable, not a stand-in for it."""
    source = _png(tmp_path / "my_own_picture.png")
    window = FakeWindow()

    with core_backends.use_backend(memory_settings):
        wallpaper.build(window)
        flow = window.rows.lookup("org.gnome.desktop.background:picture-uri").widget
        before = _tile_count(flow)
        row = wallpaper._load_domain_rows()["picture-uri"]
        wallpaper._install_custom_wallpaper(
            window,
            memory_settings,
            row,
            source,
            lambda: None,
            on_added=flow.gtheme_add_tile,
        )

    assert _tile_count(flow) == before + 1
    assert "My own picture" in [child.get_tooltip_text() for child in _tiles(flow)]


@pytest.mark.gtk
@pytest.mark.mutating
def test_it_is_still_in_the_grid_on_the_next_launch(
    memory_settings, tmp_dest_root, tmp_path, monkeypatch
):
    """The whole of §3.2: "set once, then invisible for ever" ends here.

    The page is built twice with nothing kept in between, so the only thing
    that can carry the picture across is the catalogue file — read back by the
    same scanner every other tile in the grid comes from.
    """
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_dest_root / ".local" / "share"))
    source = _png(tmp_path / "beach_day.png")
    window = FakeWindow()

    with core_backends.use_backend(memory_settings):
        wallpaper.build(window)
        flow = window.rows.lookup("org.gnome.desktop.background:picture-uri").widget
        before = _tile_count(flow)
        row = wallpaper._load_domain_rows()["picture-uri"]
        wallpaper._install_custom_wallpaper(
            window, memory_settings, row, source, lambda: None
        )

        relaunched = FakeWindow()
        wallpaper.build(relaunched)
        grid = relaunched.rows.lookup("org.gnome.desktop.background:picture-uri").widget

    assert _tile_count(grid) == before + 1
    assert "Beach day" in [child.get_tooltip_text() for child in _tiles(grid)]


def _tiles(flow: Gtk.FlowBox) -> list[Gtk.FlowBoxChild]:
    found: list[Gtk.FlowBoxChild] = []
    index = 0
    while True:
        child = flow.get_child_at_index(index)
        if child is None:
            return found
        found.append(child)
        index += 1


def _tile_count(flow: Gtk.FlowBox) -> int:
    return len(_tiles(flow))
