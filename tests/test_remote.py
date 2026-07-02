"""Tests for the download/install/update engine (engine.remote).

These exercise the routing + copy logic that the edge-case audit hardened:
local-path-vs-URL routing, single-theme-at-root collections, and the atomic,
overlap-safe, symlink-safe, force-gated _copy_theme.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from gtheme.engine import remote
from gtheme.errors import GthemeError, ThemeSecurityError


def _theme(dirpath: Path, name: str = "x") -> Path:
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / "theme.toml").write_text(f'[meta]\nname = "{name}"\n', encoding="utf-8")
    return dirpath


# --- routing ---------------------------------------------------------------


def test_is_url_existing_local_path_is_not_url(tmp_path):
    p = tmp_path / "mycoll.git"
    p.mkdir()
    assert remote._is_url(str(p)) is False


def test_is_url_recognises_remotes():
    assert remote._is_url("https://example.com/r.git")
    assert remote._is_url("git@host:user/repo.git")
    assert remote._is_url("/no/such/path/repo.git")  # nonexistent -> treated as URL


def test_themes_in_collection_single_theme_at_root(tmp_path):
    root = _theme(tmp_path / "solo")
    found = remote._themes_in_collection(root)
    assert found == {"solo": root}


def test_themes_in_collection_with_themes_wrapper(tmp_path):
    _theme(tmp_path / "themes" / "a")
    _theme(tmp_path / "themes" / "b")
    found = remote._themes_in_collection(tmp_path)
    assert set(found) == {"a", "b"}


# --- .zip install source ---------------------------------------------------


def _zip_of(theme_dir: Path, zip_path: Path, arc_prefix: str) -> Path:
    """Zip ``theme_dir`` into ``zip_path`` under a top-level ``arc_prefix/`` dir."""
    with zipfile.ZipFile(zip_path, "w") as zf:
        for p in sorted(theme_dir.rglob("*")):
            if p.is_file():
                zf.write(p, arcname=str(Path(arc_prefix) / p.relative_to(theme_dir)))
    return zip_path


def test_install_from_zip(tmp_path, installed):
    # Mirrors `gtheme export` output: a single top-level <name>/ dir in the zip.
    src = _theme(tmp_path / "src", "forest")
    zp = _zip_of(src, tmp_path / "forest.zip", "forest")
    names = remote.install(str(zp))
    assert names == ["forest"]
    assert (installed / "forest" / "theme.toml").is_file()
    origin = json.loads((installed / "forest" / remote.ORIGIN_FILE).read_text())
    assert origin["type"] == "path" and origin["source"] == str(zp.resolve())


def test_install_zip_rejects_non_archive(tmp_path, installed):
    bogus = tmp_path / "notreally.zip"
    bogus.write_text("this is not a zip", encoding="utf-8")
    # Not a real archive -> falls through to the bare-name error, not a crash.
    with pytest.raises((GthemeError, FileNotFoundError)):
        remote.install(str(bogus))


def test_extract_zip_is_zip_slip_safe(tmp_path):
    # A malicious entry with ../ must not escape the extraction dir.
    zp = tmp_path / "evil.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("../escaped.txt", "pwned")
    into = tmp_path / "box" / "unzipped"
    remote._extract_zip(zp, into)
    # Nothing written above the extraction root anywhere up the tree.
    assert not (into.parent / "escaped.txt").exists()
    assert not (tmp_path / "escaped.txt").exists()


# --- _copy_theme: atomic, overlap-safe, force-gated ------------------------


@pytest.fixture
def installed(tmp_path, monkeypatch):
    d = tmp_path / "installed"
    d.mkdir()
    monkeypatch.setattr(remote, "INSTALLED_THEMES_DIR", d)
    return d


def test_copy_theme_basic(tmp_path, installed):
    src = _theme(tmp_path / "src")
    dest = remote._copy_theme(src, "foo", {"type": "path"})
    assert dest == installed / "foo"
    assert (dest / "theme.toml").is_file()
    origin = json.loads((dest / remote.ORIGIN_FILE).read_text())
    assert origin["type"] == "path"


def test_copy_theme_refuses_existing_without_force(tmp_path, installed):
    src = _theme(tmp_path / "src")
    remote._copy_theme(src, "foo", {"type": "path"})
    with pytest.raises(FileExistsError):
        remote._copy_theme(src, "foo", {"type": "path"})


def test_copy_theme_force_overwrites(tmp_path, installed):
    remote._copy_theme(_theme(tmp_path / "s1", "one"), "foo", {"type": "path"})
    remote._copy_theme(_theme(tmp_path / "s2", "two"), "foo", {"type": "path"}, force=True)
    assert 'name = "two"' in (installed / "foo" / "theme.toml").read_text()


def test_copy_theme_rejects_src_under_dest(tmp_path, installed):
    # src nested under the would-be dest must never rmtree its own source.
    dest = installed / "foo"
    nested = _theme(dest / "inner", "inner")
    with pytest.raises(ThemeSecurityError):
        remote._copy_theme(nested, "foo", {"type": "path"})


def test_copy_theme_preserves_dangling_symlink(tmp_path, installed):
    src = _theme(tmp_path / "src")
    (src / "dead.link").symlink_to("/nonexistent/target")
    dest = remote._copy_theme(src, "foo", {"type": "path"})
    link = dest / "dead.link"
    assert link.is_symlink()  # copied as a link, not dereferenced -> no crash


def test_copy_theme_failure_leaves_no_staging(tmp_path, installed, monkeypatch):
    src = _theme(tmp_path / "src")

    # Force os.replace to fail after staging is built; staging must be cleaned up.
    import os as _os
    monkeypatch.setattr(remote.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(OSError):
        remote._copy_theme(src, "foo", {"type": "path"})
    assert not (installed / ".foo.staging").exists()
