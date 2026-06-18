"""Tests for `gtheme capture` (engine.capture) — the comprehensive saver.

capture reads the live gsettings/dconf backend; these tests assert structural
correctness (a valid theme is produced, names are confined) without depending on
any specific live value, so they pass on a GNOME box and degrade gracefully off
one (where simply fewer settings are captured).
"""

from __future__ import annotations

import pytest

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
