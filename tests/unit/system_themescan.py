"""Tests for gtheme.system.themescan — plain filesystem fixture trees, no gi."""

from __future__ import annotations

from pathlib import Path

from gtheme.system.themescan import dark_variant_name, gtk_themes, scan_themes, shell_themes

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "system" / "themes"


def test_scan_themes_classifies_by_structure() -> None:
    entries = scan_themes([FIXTURES])
    by_name = {e.name: e for e in entries}

    assert by_name["adw-gtk3"].has_gtk3 is True
    assert by_name["adw-gtk3"].has_shell is False
    assert by_name["Nightbloom"].has_shell is True
    assert by_name["Nightbloom"].has_gtk3 is False


def test_gtk_and_shell_theme_filters() -> None:
    entries = scan_themes([FIXTURES])
    gtk_names = {e.name for e in gtk_themes(entries)}
    shell_names = {e.name for e in shell_themes(entries)}

    assert gtk_names == {"adw-gtk3", "adw-gtk3-dark", "Emacs"}
    assert shell_names == {"Nightbloom"}


def test_earlier_root_shadows_later_root(tmp_path: Path) -> None:
    user_root = tmp_path / "user"
    system_root = tmp_path / "system"
    (user_root / "Shared" / "gtk-4.0").mkdir(parents=True)
    (system_root / "Shared" / "gtk-3.0").mkdir(parents=True)

    entries = scan_themes([user_root, system_root])

    assert len(entries) == 1
    assert entries[0].has_gtk4 is True
    assert entries[0].has_gtk3 is False  # the system copy never got a look-in


def test_directories_with_no_theme_content_are_skipped(tmp_path: Path) -> None:
    (tmp_path / "just-a-folder").mkdir()
    assert scan_themes([tmp_path]) == []


def test_missing_root_is_ignored(tmp_path: Path) -> None:
    assert scan_themes([tmp_path / "does-not-exist"]) == []


def test_dark_variant_name_both_directions() -> None:
    available = {"adw-gtk3", "adw-gtk3-dark", "Emacs"}
    assert dark_variant_name("adw-gtk3", available) == "adw-gtk3-dark"
    assert dark_variant_name("adw-gtk3-dark", available) == "adw-gtk3"


def test_dark_variant_name_absent_returns_none() -> None:
    assert dark_variant_name("Emacs", {"Emacs"}) is None
