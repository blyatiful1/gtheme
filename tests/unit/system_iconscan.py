"""Tests for gtheme.system.iconscan — plain filesystem fixture trees, no gi."""

from __future__ import annotations

from pathlib import Path

from gtheme.system.iconscan import cursor_themes, scan_icon_themes

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "system" / "icons"


def test_scan_icon_themes_excludes_hicolor_and_default() -> None:
    entries = scan_icon_themes([FIXTURES])
    names = {e.directory_name for e in entries}

    assert "hicolor" not in names
    assert "default" not in names
    assert names == {"Adwaita", "Papirus-Dark"}


def test_locolor_excluded_for_lacking_index_theme() -> None:
    entries = scan_icon_themes([FIXTURES])
    assert "locolor" not in {e.directory_name for e in entries}


def test_only_adwaita_is_a_cursor_theme() -> None:
    entries = scan_icon_themes([FIXTURES])
    cursors = cursor_themes(entries)

    assert {e.directory_name for e in cursors} == {"Adwaita"}


def test_display_name_read_from_index_theme() -> None:
    entries = scan_icon_themes([FIXTURES])
    by_dir = {e.directory_name: e for e in entries}
    assert by_dir["Papirus-Dark"].display_name == "Papirus-Dark"


def test_display_name_falls_back_to_directory_name_when_missing(tmp_path: Path) -> None:
    theme_dir = tmp_path / "NoNameHere"
    theme_dir.mkdir()
    (theme_dir / "index.theme").write_text("[Icon Theme]\nComment=oops\n", encoding="utf-8")

    # No Name= key at all -> not recognised as a real icon theme.
    assert scan_icon_themes([tmp_path]) == []


def test_earlier_root_shadows_later_root(tmp_path: Path) -> None:
    user_root = tmp_path / "user"
    system_root = tmp_path / "system"
    for root, name in ((user_root, "UserVersion"), (system_root, "SystemVersion")):
        d = root / "Shared"
        d.mkdir(parents=True)
        (d / "index.theme").write_text(f"[Icon Theme]\nName={name}\n", encoding="utf-8")

    entries = scan_icon_themes([user_root, system_root])
    assert len(entries) == 1
    assert entries[0].display_name == "UserVersion"
