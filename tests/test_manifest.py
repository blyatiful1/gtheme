"""Contract tests for the theme manifest loader (gtheme.manifest)."""

from __future__ import annotations

import pytest

from gtheme import manifest


def _write_theme(tmp_path, body: str):
    theme_dir = tmp_path / "t"
    theme_dir.mkdir()
    (theme_dir / "theme.toml").write_text(body, encoding="utf-8")
    return theme_dir


GOOD = """\
[meta]
name = "demo"
title = "Demo"

[palette]
bg = "#0B0E18"
accent = "#7DC75B"

[[files]]
component = "gtk"
src = "files/gtk.css"
dest = "~/.config/gtk-4.0/gtk.css"
mode = "644"

[[settings]]
component = "desktop"
backend = "gsettings"
key = "org.gnome.desktop.interface accent-color"
value = "'green'"
"""


def test_good_theme_loads(tmp_path):
    theme = manifest.load_theme(_write_theme(tmp_path, GOOD))
    assert theme.meta.name == "demo"
    assert theme.palette["accent"] == "#7DC75B"
    assert len(theme.files) == 1
    assert theme.files[0].mode == "644"


def test_template_defaults_false(tmp_path):
    theme = manifest.load_theme(_write_theme(tmp_path, GOOD))
    assert theme.files[0].template is False


def test_template_can_be_true(tmp_path):
    body = GOOD.replace('mode = "644"', 'mode = "644"\ntemplate = true')
    theme = manifest.load_theme(_write_theme(tmp_path, body))
    assert theme.files[0].template is True


@pytest.mark.parametrize("bad_mode", ['"999"', '"rwxr-xr-x"', '"0o755"', '"75"'])
def test_bad_mode_raises(tmp_path, bad_mode):
    body = GOOD.replace('mode = "644"', f"mode = {bad_mode}")
    with pytest.raises(Exception):  # pydantic ValidationError
        manifest.load_theme(_write_theme(tmp_path, body))


def test_mode_none_is_allowed(tmp_path):
    body = GOOD.replace('mode = "644"\n', "")
    theme = manifest.load_theme(_write_theme(tmp_path, body))
    assert theme.files[0].mode is None


def test_octal_4digit_mode_ok(tmp_path):
    body = GOOD.replace('mode = "644"', 'mode = "0644"')
    theme = manifest.load_theme(_write_theme(tmp_path, body))
    assert theme.files[0].mode == "0644"


def test_non_utf8_theme_toml_raises_clean_error(tmp_path):
    # tomllib raises UnicodeDecodeError (a ValueError, not TOMLDecodeError) on
    # non-UTF8 input; load_theme must wrap it as a clean ThemeValidationError.
    from gtheme.errors import ThemeValidationError

    theme_dir = tmp_path / "t"
    theme_dir.mkdir()
    (theme_dir / "theme.toml").write_bytes(b'[meta]\nname = "x"\ntitle = "caf\xe9"\n')  # latin-1
    with pytest.raises(ThemeValidationError):
        manifest.load_theme(theme_dir)
