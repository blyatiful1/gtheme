"""Tests for gtheme.system.thumbnails — the no-gi portion.

Cache lookup and generation need GnomeDesktop and are exercised under the
``gtk`` marker in ``system_thumbnails_gtk.py``.
"""

from __future__ import annotations

from pathlib import Path

from gtheme.system.thumbnails import guess_content_type, thumbnail_uri_for_path


def test_thumbnail_uri_is_a_resolved_file_uri(tmp_path: Path) -> None:
    image = tmp_path / "wallpaper.png"
    image.write_bytes(b"not a real png")

    uri = thumbnail_uri_for_path(image)

    assert uri.startswith("file://")
    assert uri.endswith("wallpaper.png")


def test_guess_content_type_known_extension() -> None:
    assert guess_content_type(Path("wallpaper.png")) == "image/png"


def test_guess_content_type_jxl_stock_wallpaper() -> None:
    # mimetypes has no JPEG-XL entry on most systems; GNOME 50 ships every
    # stock wallpaper as .jxl, so this one is a named regression.
    assert guess_content_type(Path("adwaita-l.jxl")) == "image/jxl"


def test_guess_content_type_unknown_extension_falls_back() -> None:
    assert guess_content_type(Path("mystery.qqq")) == "application/octet-stream"
