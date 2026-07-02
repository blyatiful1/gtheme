"""Tests for gtheme.validate — error formatting + the soft (warn-only) checks.

All themes are built in tmp dirs; nothing touches the live desktop. The soft
checks must stay warnings so validation passes on CI boxes with no GNOME.
"""

from __future__ import annotations

from gtheme import validate as val


def _theme(tmp_path, body):
    d = tmp_path / "t"
    d.mkdir()
    (d / "theme.toml").write_text(body, encoding="utf-8")
    return d


# --- manifest error formatting (no raw pydantic dumps) -----------------------


def test_validation_error_is_one_line_per_error(tmp_path):
    d = _theme(tmp_path, '[meta]\nname = "../evil"\n')
    theme, errors, _w = val.validate_dir(d)
    assert theme is None
    assert len(errors) == 1
    line = errors[0]
    assert line.startswith(str(d / "theme.toml"))
    assert "[meta].name" in line
    # the raw pydantic dump artifacts must be gone
    assert "errors.pydantic.dev" not in line
    assert "validation error for Theme" not in line


def test_validation_error_reports_each_field(tmp_path):
    d = _theme(tmp_path, '[meta]\nname = "ok"\nbogus = 1\nalso_bogus = 2\n')
    theme, errors, _w = val.validate_dir(d)
    assert theme is None
    assert len(errors) == 2
    assert all(e.startswith(str(d / "theme.toml")) for e in errors)


def test_toml_syntax_error_names_the_file(tmp_path):
    d = _theme(tmp_path, "not toml [[[\n")
    theme, errors, _w = val.validate_dir(d)
    assert theme is None
    assert errors[0].startswith(str(d / "theme.toml"))


# --- requires.extensions (warn-only) ------------------------------------------


_EXT_THEME = '[meta]\nname = "t"\n\n[requires]\nextensions = ["foo@bar"]\n'


def _isolate_extension_dirs(tmp_path, monkeypatch):
    """Point both probe locations (user XDG + system) at throwaway dirs."""
    monkeypatch.setattr(val.paths, "XDG_DATA_HOME", tmp_path / "xdg")
    monkeypatch.setattr(val, "_SYSTEM_EXTENSION_DIR", tmp_path / "sys-exts")


def test_missing_extension_warns(tmp_path, monkeypatch):
    _isolate_extension_dirs(tmp_path, monkeypatch)
    d = _theme(tmp_path, _EXT_THEME)
    theme, errors, warnings = val.validate_dir(d)
    assert theme is not None and errors == []  # warn, never error
    assert any("foo@bar" in w and "extension" in w for w in warnings)


def test_extension_under_xdg_data_home_does_not_warn(tmp_path, monkeypatch):
    # GNOME resolves user extensions via $XDG_DATA_HOME — the probe must too
    # (same semantics as apply's check_requires).
    _isolate_extension_dirs(tmp_path, monkeypatch)
    (tmp_path / "xdg/gnome-shell/extensions/foo@bar").mkdir(parents=True)
    d = _theme(tmp_path, _EXT_THEME)
    _t, _e, warnings = val.validate_dir(d)
    assert not any("foo@bar" in w for w in warnings)


def test_extension_in_system_dir_does_not_warn(tmp_path, monkeypatch):
    _isolate_extension_dirs(tmp_path, monkeypatch)
    (tmp_path / "sys-exts/foo@bar").mkdir(parents=True)
    d = _theme(tmp_path, _EXT_THEME)
    _t, _e, warnings = val.validate_dir(d)
    assert not any("foo@bar" in w for w in warnings)


# --- dest inside the installed-themes namespace --------------------------------


def test_dest_in_installed_themes_dir_warns(tmp_path):
    d = _theme(tmp_path, (
        '[meta]\nname = "t"\n\n'
        "[[files]]\n"
        'component = "commands"\n'
        'src = "files/bin"\n'
        'dest = "~/.local/share/gtheme/themes/t/bin"\n'
    ))
    (d / "files/bin").mkdir(parents=True)
    (d / "files/bin/tool").write_text("#!/bin/sh\n")
    theme, errors, warnings = val.validate_dir(d)
    assert theme is not None and errors == []
    assert any("installed-themes" in w for w in warnings)


def test_assets_dest_does_not_warn(tmp_path):
    d = _theme(tmp_path, (
        '[meta]\nname = "t"\n\n'
        "[[files]]\n"
        'component = "commands"\n'
        'src = "files/bin"\n'
        'dest = "~/.local/share/gtheme/assets/t/bin"\n'
    ))
    (d / "files/bin").mkdir(parents=True)
    (d / "files/bin/tool").write_text("#!/bin/sh\n")
    _t, errors, warnings = val.validate_dir(d)
    assert errors == []
    assert not any("installed-themes" in w for w in warnings)


def test_sibling_of_installed_themes_dir_does_not_warn(tmp_path):
    # themes-backup is a *sibling* of the themes namespace, not inside it —
    # a bare startswith prefix test would false-positive here.
    d = _theme(tmp_path, (
        '[meta]\nname = "t"\n\n'
        "[[files]]\n"
        'component = "commands"\n'
        'src = "files/bin"\n'
        'dest = "~/.local/share/gtheme/themes-backup/t/bin"\n'
    ))
    (d / "files/bin").mkdir(parents=True)
    (d / "files/bin/tool").write_text("#!/bin/sh\n")
    _t, errors, warnings = val.validate_dir(d)
    assert errors == []
    assert not any("installed-themes" in w for w in warnings)


# --- dark design without color-scheme ------------------------------------------


def test_dark_palette_without_color_scheme_warns(tmp_path):
    d = _theme(tmp_path, '[meta]\nname = "t"\n\n[palette]\nbg = "#0D0D0F"\n')
    _t, _e, warnings = val.validate_dir(d)
    assert any("color-scheme" in w for w in warnings)


def test_dark_palette_with_color_scheme_does_not_warn(tmp_path):
    d = _theme(tmp_path, (
        '[meta]\nname = "t"\n\n[palette]\nbg = "#0D0D0F"\n\n'
        "[[settings]]\n"
        'component = "desktop"\n'
        'backend = "gsettings"\n'
        'key = "org.gnome.desktop.interface color-scheme"\n'
        "value = \"'prefer-dark'\"\n"
    ))
    _t, _e, warnings = val.validate_dir(d)
    assert not any("color-scheme" in w for w in warnings)


def test_light_palette_does_not_warn(tmp_path):
    d = _theme(tmp_path, '[meta]\nname = "t"\n\n[palette]\nbg = "#FAFAFA"\n')
    _t, _e, warnings = val.validate_dir(d)
    assert not any("color-scheme" in w for w in warnings)


def test_dark_wallpaper_primary_color_warns_without_palette(tmp_path):
    d = _theme(tmp_path, (
        '[meta]\nname = "t"\n\n'
        "[[settings]]\n"
        'component = "wallpaper"\n'
        'backend = "gsettings"\n'
        'key = "org.gnome.desktop.background primary-color"\n'
        "value = \"'#0B0E18'\"\n"
    ))
    _t, _e, warnings = val.validate_dir(d)
    assert any("color-scheme" in w for w in warnings)
