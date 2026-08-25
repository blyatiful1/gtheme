"""Tests for gtheme.system.wallpapers — plain XML fixture trees, no gi."""

from __future__ import annotations

from pathlib import Path

from gtheme.system.wallpapers import (
    SlideshowEvent,
    SlideshowTransition,
    parse_slideshow,
    scan_wallpaper_catalogue,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "system" / "wallpapers-catalogue"


def test_scans_static_catalogue_entry() -> None:
    entries = scan_wallpaper_catalogue([FIXTURES])
    by_name = {e.name: e for e in entries}
    adwaita = by_name["Default Background"]

    assert adwaita.filename == Path("/usr/share/backgrounds/gnome/adwaita-l.jxl")
    assert adwaita.filename_dark == Path("/usr/share/backgrounds/gnome/adwaita-d.jxl")
    assert adwaita.options == "zoom"
    assert adwaita.shade_type == "solid"
    assert adwaita.primary_color == "#3071AE"
    assert adwaita.is_slideshow is False


def test_slideshow_discriminated_by_filename_extension() -> None:
    entries = scan_wallpaper_catalogue([FIXTURES])
    by_name = {e.name: e for e in entries}
    timed = by_name["Timed Background"]

    assert timed.filename.suffix == ".xml"
    assert timed.is_slideshow is True
    assert timed.filename_dark is None


def test_missing_optional_fields_get_defaults() -> None:
    entries = scan_wallpaper_catalogue([FIXTURES])
    by_name = {e.name: e for e in entries}
    timed = by_name["Timed Background"]

    assert timed.primary_color is None
    assert timed.secondary_color is None


def test_doctype_line_does_not_break_parsing(tmp_path: Path) -> None:
    # Every real catalogue file references a DTD that isn't installed
    # anywhere; the parser must not attempt to resolve it.
    xml = tmp_path / "one.xml"
    xml.write_text(
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE wallpapers SYSTEM "gnome-wp-list.dtd">\n'
        "<wallpapers><wallpaper><name>X</name>"
        "<filename>/tmp/x.png</filename></wallpaper></wallpapers>\n",
        encoding="utf-8",
    )
    entries = scan_wallpaper_catalogue([tmp_path])
    assert len(entries) == 1
    assert entries[0].name == "X"


def test_malformed_xml_yields_no_entries_not_a_crash(tmp_path: Path) -> None:
    xml = tmp_path / "broken.xml"
    xml.write_text("<wallpapers><wallpaper><name>oops</wallpaper>", encoding="utf-8")
    assert scan_wallpaper_catalogue([tmp_path]) == []


def test_entries_missing_a_filename_are_skipped(tmp_path: Path) -> None:
    xml = tmp_path / "incomplete.xml"
    xml.write_text(
        "<wallpapers><wallpaper><name>No file here</name></wallpaper></wallpapers>",
        encoding="utf-8",
    )
    assert scan_wallpaper_catalogue([tmp_path]) == []


def test_parse_slideshow_start_time_and_sequence() -> None:
    start, events = parse_slideshow(FIXTURES / "timed-slideshow.xml")

    assert (start.year, start.month, start.day) == (2024, 1, 1)
    assert (start.hour, start.minute, start.second) == (0, 0, 0)
    assert len(events) == 4
    assert isinstance(events[0], SlideshowEvent)
    assert events[0].duration == 36000.0
    assert events[0].file == Path("/path/day.jxl")
    assert isinstance(events[1], SlideshowTransition)
    assert events[1].kind == "overlay"
    assert events[1].from_file == Path("/path/day.jxl")
    assert events[1].to_file == Path("/path/night.jxl")


def test_parse_slideshow_totals_a_full_day() -> None:
    _, events = parse_slideshow(FIXTURES / "timed-slideshow.xml")
    total = sum(e.duration for e in events)
    assert total == 86400.0


def test_parse_slideshow_missing_file_returns_empty(tmp_path: Path) -> None:
    start, events = parse_slideshow(tmp_path / "nope.xml")
    assert events == []
    assert start.year == 0
