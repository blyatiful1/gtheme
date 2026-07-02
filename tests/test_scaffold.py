"""Tests for `gtheme new` (engine.scaffold) — hermetic, dest_dir in tmp."""

from __future__ import annotations

import tomllib

from gtheme.engine import scaffold


def _settings_keys(theme_dir):
    data = tomllib.loads((theme_dir / "theme.toml").read_text(encoding="utf-8"))
    return {s["key"]: s["value"] for s in data.get("settings", [])}


def test_scaffold_dark_default_palette_sets_prefer_dark(tmp_path):
    # the default palette bg (#101014) is dark — the scaffold must not trip
    # validate's dark/color-scheme warning on its own output
    path = scaffold.new_theme("fresh", dest_dir=tmp_path)
    keys = _settings_keys(path)
    assert keys.get("org.gnome.desktop.interface color-scheme") == "'prefer-dark'"


def test_scaffold_light_palette_omits_color_scheme(tmp_path, monkeypatch):
    monkeypatch.setattr(scaffold, "_DEFAULT_PALETTE", 'bg = "#fafafa"\n')
    path = scaffold.new_theme("bright", dest_dir=tmp_path)
    assert "org.gnome.desktop.interface color-scheme" not in _settings_keys(path)


def test_scaffold_unparseable_palette_defaults_to_no_color_scheme(tmp_path, monkeypatch):
    monkeypatch.setattr(scaffold, "_DEFAULT_PALETTE", "not toml [[[\n")
    path = scaffold.new_theme("broken", dest_dir=tmp_path)
    assert "org.gnome.desktop.interface color-scheme" not in _settings_keys(path)
