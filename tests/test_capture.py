"""Tests for `gtheme capture` (engine.capture) — the comprehensive saver.

capture reads the live gsettings/dconf backend; these tests assert structural
correctness (a valid theme is produced, names are confined) without depending on
any specific live value, so they pass on a GNOME box and degrade gracefully off
one (where simply fewer settings are captured).
"""

from __future__ import annotations

import tomllib

import pytest

from gtheme import paths
from gtheme.engine import capture as cap
from gtheme.errors import ThemeSecurityError
from gtheme.manifest import load_theme


def test_capture_creates_a_valid_theme(tmp_path):
    path, notes = cap.capture("snap", title="Snap", dest_dir=tmp_path)
    assert (path / "theme.toml").is_file()
    # the generated manifest must parse + validate as a real theme
    theme = load_theme(path)
    assert theme.meta.name == "snap"
    assert theme.meta.title == "Snap"
    assert isinstance(notes, list)


def test_capture_rejects_unsafe_name(tmp_path):
    with pytest.raises(ThemeSecurityError):
        cap.capture("../evil", dest_dir=tmp_path)


def test_capture_refuses_existing(tmp_path):
    (tmp_path / "snap").mkdir()
    with pytest.raises(FileExistsError):
        cap.capture("snap", dest_dir=tmp_path)


def test_setting_targets_includes_curated_baseline(tmp_path):
    targets = cap._setting_targets()
    keys = {key for _c, _b, key in targets}
    # the curated baseline must always be present, deduplicated
    assert "org.gnome.desktop.interface accent-color" in keys
    assert "org.gnome.desktop.background picture-uri" in keys
    assert len(targets) == len({(b, k) for _c, b, k in targets})  # no dupes


# --- companion bundling (self-contained exports) -----------------------------


def _fake_home(tmp_path, monkeypatch):
    """Point capture's dest expansion at a throwaway HOME tree."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(paths, "DEST_ROOT", home)   # expand_dest reads this
    monkeypatch.setattr(cap, "DEST_ROOT", home)     # capture's own snapshot
    return home


def test_bundle_alacritty_imports_bundles_companion(tmp_path, monkeypatch):
    home = _fake_home(tmp_path, monkeypatch)
    (home / ".config/alacritty").mkdir(parents=True)
    (home / ".config/alacritty/jojo.toml").write_text("# colors\n")
    theme = tmp_path / "theme"
    (theme / "files/alacritty").mkdir(parents=True)
    (theme / "files/alacritty/alacritty.toml").write_text(
        '[general]\nimport = ["~/.config/alacritty/jojo.toml"]\n'
    )
    entries, notes = [], []
    cap._bundle_alacritty_imports(theme, entries, notes)
    assert (theme / "files/alacritty/jojo.toml").is_file()
    assert ("terminal", "files/alacritty/jojo.toml",
            "~/.config/alacritty/jojo.toml") in entries


def test_bundle_alacritty_imports_notes_missing(tmp_path, monkeypatch):
    _fake_home(tmp_path, monkeypatch)
    theme = tmp_path / "theme"
    (theme / "files/alacritty").mkdir(parents=True)
    (theme / "files/alacritty/alacritty.toml").write_text(
        '[general]\nimport = ["~/.config/alacritty/gone.toml"]\n'
    )
    entries, notes = [], []
    cap._bundle_alacritty_imports(theme, entries, notes)
    assert entries == []
    assert any("gone.toml" in n and "missing" in n for n in notes)


def test_bundle_alacritty_import_traversal_is_confined(tmp_path, monkeypatch):
    # A ~/.. traversal in an import list must never pull an out-of-home file
    # (SSH keys, /etc/*) into a shareable theme.
    _fake_home(tmp_path, monkeypatch)
    theme = tmp_path / "theme"
    (theme / "files/alacritty").mkdir(parents=True)
    (theme / "files/alacritty/alacritty.toml").write_text(
        '[general]\nimport = ["~/../../etc/hostname"]\n'
    )
    entries, notes = [], []
    cap._bundle_alacritty_imports(theme, entries, notes)
    assert entries == []
    assert not (theme / "files/alacritty/hostname").exists()
    assert any("outside home" in n for n in notes)


def test_bundle_btop_theme_traversal_is_confined(tmp_path, monkeypatch):
    _fake_home(tmp_path, monkeypatch)
    theme = tmp_path / "theme"
    (theme / "files/btop").mkdir(parents=True)
    (theme / "files/btop/btop.conf").write_text(
        'color_theme = "~/../../etc/passwd"\n'
    )
    entries, notes = [], []
    cap._bundle_btop_theme(theme, entries, notes)
    assert entries == []
    assert not (theme / "files/btop/passwd").exists()
    assert any("outside home" in n for n in notes)


def test_bundle_companion_symlink_escape_is_confined(tmp_path, monkeypatch):
    # An in-home path that is a symlink out of home must also be refused.
    home = _fake_home(tmp_path, monkeypatch)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n")
    (home / ".config/alacritty").mkdir(parents=True)
    (home / ".config/alacritty/link.toml").symlink_to(outside)
    theme = tmp_path / "theme"
    theme.mkdir()
    entries, notes = [], []
    cap._bundle_companion("~/.config/alacritty/link.toml", "terminal",
                          "files/alacritty/link.toml", theme, entries, notes, "test")
    assert entries == []
    assert not (theme / "files/alacritty/link.toml").exists()
    assert any("outside home" in n for n in notes)


def test_bundle_btop_theme_by_name(tmp_path, monkeypatch):
    home = _fake_home(tmp_path, monkeypatch)
    (home / ".config/btop/themes").mkdir(parents=True)
    (home / ".config/btop/themes/jojo.theme").write_text("theme[main_bg]\n")
    theme = tmp_path / "theme"
    (theme / "files/btop").mkdir(parents=True)
    (theme / "files/btop/btop.conf").write_text('color_theme = "jojo"\n')
    entries, notes = [], []
    cap._bundle_btop_theme(theme, entries, notes)
    assert (theme / "files/btop/jojo.theme").is_file()
    assert ("monitor", "files/btop/jojo.theme",
            "~/.config/btop/themes/jojo.theme") in entries


def test_bundle_btop_theme_skips_builtins(tmp_path, monkeypatch):
    _fake_home(tmp_path, monkeypatch)
    theme = tmp_path / "theme"
    (theme / "files/btop").mkdir(parents=True)
    (theme / "files/btop/btop.conf").write_text('color_theme = "Default"\n')
    entries, notes = [], []
    cap._bundle_btop_theme(theme, entries, notes)
    assert entries == [] and notes == []


def test_bundle_ptyxis_palette(tmp_path, monkeypatch):
    home = _fake_home(tmp_path, monkeypatch)
    pal = home / ".local/share/org.gnome.Ptyxis/palettes"
    pal.mkdir(parents=True)
    (pal / "JoJo.palette").write_text("[Palette]\n")
    theme = tmp_path / "theme"
    theme.mkdir()
    settings = [("terminal", "dconf",
                 "/org/gnome/Ptyxis/Profiles/abc123/palette", "'JoJo'")]
    entries, notes = [], []
    cap._bundle_ptyxis_palette(settings, theme, entries, notes)
    assert (theme / "files/ptyxis/JoJo.palette").is_file()
    assert ("terminal", "files/ptyxis/JoJo.palette",
            "~/.local/share/org.gnome.Ptyxis/palettes/JoJo.palette") in entries


def test_bundle_ptyxis_palette_notes_missing(tmp_path, monkeypatch):
    _fake_home(tmp_path, monkeypatch)
    theme = tmp_path / "theme"
    theme.mkdir()
    settings = [("terminal", "dconf",
                 "/org/gnome/Ptyxis/Profiles/abc123/palette", "'Nope'")]
    entries, notes = [], []
    cap._bundle_ptyxis_palette(settings, theme, entries, notes)
    assert entries == []
    assert any("Nope" in n and "missing" in n for n in notes)


class _FakePaletteSetting:
    """Stands in for ResolvedSetting: only the Ptyxis palette key has a value."""

    def __init__(self, setting, ctx=None):
        self.backend = setting.backend
        self.component = setting.component
        self.key = setting.key.replace("{{ ptyxis_default_profile }}", "abc123")
        self.value = setting.value

    def get_current(self):
        return "'JoJo'" if self.key.endswith("/palette") else None


def test_capture_bundles_companions_end_to_end(tmp_path, monkeypatch):
    home = _fake_home(tmp_path, monkeypatch)
    (home / ".config/alacritty").mkdir(parents=True)
    (home / ".config/alacritty/alacritty.toml").write_text(
        '[general]\nimport = ["~/.config/alacritty/jojo.toml"]\n'
    )
    (home / ".config/alacritty/jojo.toml").write_text("# colors\n")
    (home / ".config/btop/themes").mkdir(parents=True)
    (home / ".config/btop/btop.conf").write_text('color_theme = "jojo"\n')
    (home / ".config/btop/themes/jojo.theme").write_text("theme[main_bg]\n")
    pal = home / ".local/share/org.gnome.Ptyxis/palettes"
    pal.mkdir(parents=True)
    (pal / "JoJo.palette").write_text("[Palette]\n")
    monkeypatch.setattr(cap, "ResolvedSetting", _FakePaletteSetting)
    monkeypatch.setattr(cap, "_setting_targets", lambda: [
        ("terminal", "dconf",
         "/org/gnome/Ptyxis/Profiles/{{ ptyxis_default_profile }}/palette"),
    ])

    path, notes = cap.capture("snap", dest_dir=tmp_path)
    theme = load_theme(path)  # manifest incl. companions must round-trip
    dests = {f.dest for f in theme.files}
    assert "~/.config/alacritty/jojo.toml" in dests
    assert "~/.config/btop/themes/jojo.theme" in dests
    assert "~/.local/share/org.gnome.Ptyxis/palettes/JoJo.palette" in dests
    assert (path / "files/alacritty/jojo.toml").is_file()
    assert (path / "files/btop/jojo.theme").is_file()
    assert (path / "files/ptyxis/JoJo.palette").is_file()


# --- share-safety scan --------------------------------------------------------


def test_scan_flags_fish_secret_export(tmp_path, monkeypatch):
    home = _fake_home(tmp_path, monkeypatch)
    (home / ".config/fish").mkdir(parents=True)
    (home / ".config/fish/config.fish").write_text(
        "set -gx OPENAI_API_KEY sk-abc123\nset -gx EZA_ICONS_AUTO 1\n"
    )
    monkeypatch.setattr(cap, "ResolvedSetting", _FakePaletteSetting)
    monkeypatch.setattr(cap, "_setting_targets", lambda: [])
    _path, notes = cap.capture("snap", dest_dir=tmp_path)
    flagged = [n for n in notes if "REVIEW BEFORE SHARING" in n]
    assert any("config.fish:1" in n and "secret" in n for n in flagged)
    # the harmless export must NOT be flagged
    assert not any(":2" in n for n in flagged)


def test_scan_flags_hardcoded_home_path(tmp_path):
    theme = tmp_path / "theme"
    (theme / "files/fish").mkdir(parents=True)
    (theme / "files/fish/config.fish").write_text(
        "set PATH /home/someuser/bin $PATH\n"
    )
    notes = []
    cap._scan_captured_text(
        theme, [("shell-cfg", "files/fish/config.fish", "~/.config/fish/config.fish")], notes
    )
    assert any("home path" in n and "config.fish:1" in n for n in notes)


# --- TOML string escaping ------------------------------------------------------


@pytest.mark.parametrize("raw", ["a\nb", "tab\there", "quote \" back \\ slash", "bell\x07"])
def test_toml_str_round_trips_control_chars(raw):
    encoded = cap._toml_str(raw)
    assert tomllib.loads(f"v = {encoded}")["v"] == raw
