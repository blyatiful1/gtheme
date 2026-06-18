"""Tests for `gtheme export` (engine.export) — the shareable-archive packer."""

from __future__ import annotations

import zipfile

import pytest

from gtheme.engine import export as exp
from gtheme.errors import GthemeError


def _theme(tmp_path):
    d = tmp_path / "foo"
    (d / "files").mkdir(parents=True)
    (d / "theme.toml").write_text('[meta]\nname = "foo"\n', encoding="utf-8")
    (d / "files" / "a.conf").write_text("x", encoding="utf-8")
    (d / ".gtheme-origin.json").write_text("{}", encoding="utf-8")  # excluded
    (d / "files" / "junk.pyc").write_text("nope", encoding="utf-8")  # excluded
    staging = d / ".foo.staging"
    staging.mkdir()
    (staging / "s").write_text("nope", encoding="utf-8")  # excluded
    return d


def test_export_creates_installable_zip(tmp_path, monkeypatch):
    d = _theme(tmp_path)
    monkeypatch.setattr(exp, "find", lambda name: d)
    out, count = exp.export_theme("foo", out=str(tmp_path / "out.zip"))
    assert out.exists()
    names = zipfile.ZipFile(out).namelist()
    assert "foo/theme.toml" in names
    assert "foo/files/a.conf" in names
    # every entry lives under a single top-level <name>/ dir
    assert all(n.startswith("foo/") for n in names)
    # bookkeeping / caches / staging are excluded
    assert all("gtheme-origin" not in n for n in names)
    assert all(not n.endswith(".pyc") for n in names)
    assert all(".foo.staging" not in n for n in names)
    assert count == len(names)


def test_export_unknown_theme_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(exp, "find", lambda name: None)
    with pytest.raises(GthemeError):
        exp.export_theme("nope")


def test_export_default_output_is_named_zip(tmp_path, monkeypatch):
    d = _theme(tmp_path)
    monkeypatch.setattr(exp, "find", lambda name: d)
    monkeypatch.chdir(tmp_path)
    out, _ = exp.export_theme("foo")
    assert out.name == "foo.zip"


def test_export_coerces_extension(tmp_path, monkeypatch):
    d = _theme(tmp_path)
    monkeypatch.setattr(exp, "find", lambda name: d)
    out, _ = exp.export_theme("foo", out=str(tmp_path / "bundle"))
    assert out.suffix == ".zip"
