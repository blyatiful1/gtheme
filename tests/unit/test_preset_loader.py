"""Discovery and loading: installed beats bundled, and nothing raises."""

from __future__ import annotations

from pathlib import Path

import pytest

from gtheme.preset import loader

GOOD = """
format = 2

[meta]
name = "{name}"
title = "{name}"
description = ""
author = ""
version = "1.0.0"
screenshots = ["shot.png"]
"""


@pytest.fixture
def looks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A user folder and a bundled folder, both wired into the search path."""
    user = tmp_path / "user"
    bundled = tmp_path / "bundled"
    user.mkdir()
    bundled.mkdir()
    monkeypatch.setenv("GTHEME_THEMES_DIR", str(user))
    monkeypatch.setenv("GTHEME_BUNDLED_THEMES_DIR", str(bundled))
    return user, bundled


def _write(directory: Path, name: str, *, body: str | None = None, shot: bool = True) -> Path:
    folder = directory / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "theme.toml").write_text(body or GOOD.format(name=name), encoding="utf-8")
    if shot:
        (folder / "shot.png").write_bytes(b"x")
    return folder


def test_search_path_puts_the_user_first(looks):
    user, bundled = looks
    assert loader.search_paths() == [user, bundled]


def test_installed_shadows_bundled(looks):
    user, bundled = looks
    _write(bundled, "magma")
    _write(user, "magma")
    assert loader.discover()["magma"] == user / "magma"


def test_a_folder_without_a_manifest_is_not_a_look(looks):
    _user, bundled = looks
    (bundled / "notatheme").mkdir()
    assert loader.discover() == {}


def test_provenance_distinguishes_bundled_from_user(looks):
    user, bundled = looks
    _write(bundled, "b")
    _write(user, "u")
    results = {r.name: r for r in loader.load_all()}
    assert results["b"].provenance == "bundled"
    assert results["u"].provenance == "user"


def test_a_broken_look_is_listed_as_broken_not_hidden(looks):
    user, _bundled = looks
    _write(user, "broken", body="format = 2\n[meta]\nname = 'broken'\n")
    result = loader.load(user / "broken")
    assert not result.ok
    assert result.errors
    assert all("pydantic" not in line for line in result.errors)


def test_a_typo_is_an_error_because_the_format_forbids_extras(looks):
    user, _bundled = looks
    body = GOOD.format(name="typo") + '\n[[settings]]\nkye = "x"\nvalue = "y"\n'
    _write(user, "typo", body=body)
    assert not loader.load(user / "typo").ok


def test_a_v1_file_does_not_load_as_v2(looks):
    user, _bundled = looks
    _write(user, "old", body='[meta]\nname = "old"\n[[hooks]]\nscript = "x.sh"\n')
    result = loader.load(user / "old")
    assert not result.ok


def test_a_missing_picture_is_a_warning_not_an_error(looks):
    user, _bundled = looks
    _write(user, "nopic", shot=False)
    result = loader.load(user / "nopic")
    assert result.ok
    assert any("cannot be previewed" in w for w in result.warnings)


def test_a_missing_source_file_is_a_warning(looks):
    user, _bundled = looks
    body = GOOD.format(name="gap") + '\n[[files]]\nsrc = "gone.css"\ndest = "~/gone.css"\n'
    _write(user, "gap", body=body)
    result = loader.load(user / "gap")
    assert result.ok
    assert any("gone.css" in w and "will not be written" in w for w in result.warnings)


def test_a_folder_used_as_a_source_is_a_warning(looks):
    user, _bundled = looks
    body = GOOD.format(name="dir") + '\n[[files]]\nsrc = "sub"\ndest = "~/sub"\n'
    folder = _write(user, "dir", body=body)
    (folder / "sub").mkdir()
    assert any("one file at a time" in w for w in loader.load(folder).warnings)


def test_a_name_that_disagrees_with_the_folder_is_a_warning(looks):
    user, _bundled = looks
    folder = _write(user, "folder", body=GOOD.format(name="other"))
    assert any("folder name is what gtheme uses" in w for w in loader.load(folder).warnings)


def test_a_missing_folder_is_an_error_not_an_exception(tmp_path):
    result = loader.load(tmp_path / "nope")
    assert not result.ok
    assert "theme.toml" in result.errors[0]


def test_load_all_is_sorted_and_survives_a_broken_look(looks):
    user, _bundled = looks
    _write(user, "zebra")
    _write(user, "apple")
    _write(user, "broken", body="not toml [[[")
    names = [r.name for r in loader.load_all()]
    assert names == ["apple", "broken", "zebra"]


def test_the_bundled_folder_is_found_without_an_override(monkeypatch):
    monkeypatch.delenv("GTHEME_BUNDLED_THEMES_DIR", raising=False)
    assert loader.bundled_themes_dir().name in {"themes", "_bundled_themes"}


def test_the_user_folder_stays_out_of_v1s_namespace(monkeypatch, tmp_path):
    monkeypatch.delenv("GTHEME_THEMES_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    # v1 owned <data>/gtheme/themes and deleted it wholesale on update.
    assert loader.user_themes_dir() == tmp_path / "gtheme" / "v2" / "themes"
