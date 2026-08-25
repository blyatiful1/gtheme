"""The zero-server registry: building it, reading it, and keeping it fresh."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from gtheme.preset.registry import (
    INDEX_URL,
    INDEX_VERSION,
    IndexEntry,
    build_index,
    entry_for,
    parse_index,
    write_index,
)

V1_FIELDS = ("name", "title", "description", "author", "version", "components")
V2_FIELDS = ("format", "screenshots", "min_shell", "provenance")


def test_the_registry_url_is_the_one_every_install_already_fetches():
    """Changing this orphans every existing install (DESIGN.md A1/A2)."""
    assert INDEX_URL == (
        "https://raw.githubusercontent.com/blyatiful1/gtheme/main/themes/index.json"
    )
    assert "/themes/index.json" in INDEX_URL


# ── the committed index ──────────────────────────────────────────────────


def test_the_committed_index_is_up_to_date(repo_root: Path):
    committed = json.loads((repo_root / "themes" / "index.json").read_text(encoding="utf-8"))
    rebuilt, skipped = build_index(repo_root / "themes")
    assert skipped == []
    assert committed == rebuilt


def test_the_build_tool_agrees(repo_root: Path):
    result = subprocess.run(
        [sys.executable, str(repo_root / "tools" / "build_index.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_the_committed_index_keeps_every_v1_field(repo_root: Path):
    document = json.loads((repo_root / "themes" / "index.json").read_text(encoding="utf-8"))
    assert document["version"] == INDEX_VERSION
    for entry in document["themes"]:
        for field in (*V1_FIELDS, *V2_FIELDS):
            assert field in entry, field


def test_every_bundled_look_is_in_the_index(repo_root: Path):
    document = json.loads((repo_root / "themes" / "index.json").read_text(encoding="utf-8"))
    names = {entry["name"] for entry in document["themes"]}
    assert names == {"magma", "netrunner", "hyperclass", "nightbloom"}


def test_every_indexed_screenshot_exists(repo_root: Path):
    document = json.loads((repo_root / "themes" / "index.json").read_text(encoding="utf-8"))
    for entry in document["themes"]:
        assert entry["screenshots"], entry["name"]
        for shot in entry["screenshots"]:
            assert (repo_root / "themes" / entry["name"] / shot).is_file(), shot


def test_the_reasons_a_look_was_skipped_are_not_published(tmp_path):
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "theme.toml").write_text("format = 2\n", encoding="utf-8")
    document, skipped = build_index(tmp_path)
    assert document["themes"] == []
    assert [name for name, _reason in skipped] == ["broken"]
    assert "skipped" not in document


# ── describing a Look ────────────────────────────────────────────────────


def test_components_come_from_the_closed_registry(repo_root: Path):
    from gtheme.preset.model import Component

    document = json.loads((repo_root / "themes" / "index.json").read_text(encoding="utf-8"))
    known = {str(c) for c in Component}
    for entry in document["themes"]:
        assert set(entry["components"]) <= known


def test_a_look_with_add_ons_says_so(tmp_path):
    from gtheme.preset.model import ExtensionsBlock, Meta, Preset

    preset = Preset(
        format=2,
        meta=Meta(
            name="a", title="A", description="", author="", version="1", screenshots=["s.png"]
        ),
        extensions=ExtensionsBlock(enable=["x@y"]),
    )
    assert "addons" in entry_for(preset).components


# ── reading a fetched index ──────────────────────────────────────────────


def test_parse_round_trips_what_build_writes(repo_root: Path):
    text = (repo_root / "themes" / "index.json").read_text(encoding="utf-8")
    entries = parse_index(text)
    assert [e.name for e in entries] == ["hyperclass", "magma", "netrunner", "nightbloom"]
    assert all(e.format == 2 for e in entries)


def test_parse_accepts_bytes():
    document = {"version": 2, "themes": [{"name": "a", "title": "A", "version": "1"}]}
    assert parse_index(json.dumps(document).encode())[0].name == "a"


def test_an_unknown_field_does_not_break_an_older_client():
    document = {
        "version": 3,
        "themes": [{"name": "a", "title": "A", "version": "1", "something_new": True}],
    }
    assert parse_index(json.dumps(document))[0].name == "a"


def test_one_malformed_entry_does_not_hide_the_others():
    document = {"version": 2, "themes": [{"title": "no name"}, {"name": "fine"}, "junk"]}
    assert [e.name for e in parse_index(json.dumps(document))] == ["fine"]


def test_a_v1_index_still_reads():
    """v1 entries have no ``format``; they are format 1 by omission."""
    document = {
        "version": 1,
        "themes": [
            {
                "name": "magma",
                "title": "MAGMA",
                "description": "d",
                "author": "a",
                "version": "2.0.0",
                "components": ["wallpaper"],
            }
        ],
    }
    entry = parse_index(json.dumps(document))[0]
    assert entry.format == 1
    assert entry.screenshots == []


@pytest.mark.parametrize("text", ["not json", "[]", '{"themes": 5}', '{"nope": 1}'])
def test_a_document_that_is_not_a_registry_says_so(text):
    with pytest.raises(ValueError):
        parse_index(text)


def test_write_index_returns_where_it_wrote(tmp_path):
    (tmp_path / "empty").mkdir()
    out = write_index(tmp_path)
    assert out == tmp_path / "index.json"
    assert json.loads(out.read_text(encoding="utf-8")) == {"version": 2, "themes": []}


def test_an_entry_serialises_every_field():
    entry = IndexEntry(name="a", title="A", description="", author="", version="1")
    assert set(entry.to_json()) == set(V1_FIELDS) | set(V2_FIELDS)


# -- the publish gate ------------------------------------------------------
#
# "Every Look has a picture" is a real requirement (DESIGN.md A8) that does not
# live in the model, because the model also describes restore points, which are
# written by machine and may have nothing to photograph. It lives here, on the
# path a Look actually travels to reach the community index.


def _a_look_without_a_picture(root: Path) -> None:
    from gtheme.preset.emit import dumps_preset
    from gtheme.preset.model import Meta, Preset

    folder = root / "picturless"
    folder.mkdir(parents=True)
    preset = Preset(
        format=2,
        meta=Meta(
            name="picturless",
            title="No picture",
            description="",
            author="someone",
            version="1.0.0",
            screenshots=[],
        ),
    )
    (folder / "theme.toml").write_text(dumps_preset(preset), encoding="utf-8")


def _run_build_index(
    repo_root: Path, themes_dir: Path, *extra: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(repo_root / "tools" / "build_index.py"),
            "--themes-dir",
            str(themes_dir),
            *extra,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_publishing_a_look_with_no_picture_is_refused(repo_root: Path, tmp_path: Path):
    _a_look_without_a_picture(tmp_path)
    result = _run_build_index(repo_root, tmp_path)
    assert result.returncode == 1, result.stdout
    assert "no picture" in result.stderr
    assert "picturless" in result.stderr
    assert not (tmp_path / "index.json").exists(), "a refused index must not be written"


def test_publishing_a_look_whose_picture_is_missing_is_refused(repo_root: Path, tmp_path: Path):
    from gtheme.preset.emit import dumps_preset
    from gtheme.preset.model import Meta, Preset

    folder = tmp_path / "promiser"
    folder.mkdir(parents=True)
    preset = Preset(
        format=2,
        meta=Meta(
            name="promiser",
            title="Promises a picture",
            description="",
            author="someone",
            version="1.0.0",
            screenshots=["shots/desktop.png"],
        ),
    )
    (folder / "theme.toml").write_text(dumps_preset(preset), encoding="utf-8")
    result = _run_build_index(repo_root, tmp_path)
    assert result.returncode == 1, result.stdout
    assert "listed but not there" in result.stderr
    assert "promiser/shots/desktop.png" in result.stderr


def test_the_bundled_looks_all_pass_the_publish_gate(repo_root: Path):
    """The gate is only worth anything if the real index still crosses it.

    ``--check`` so that running the tests never rewrites a committed file; the
    gate runs before the check/write fork, so it is exercised either way.
    """
    result = _run_build_index(repo_root, repo_root / "themes", "--check")
    assert result.returncode == 0, result.stderr
