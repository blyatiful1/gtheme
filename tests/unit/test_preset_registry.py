"""The zero-server registry: building it, reading it, and keeping it fresh."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from gtheme.preset import registry
from gtheme.preset.loader import ORIGIN_FILENAME, load
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


# ── fetching the index, through the seam ─────────────────────────────────
#
# ``fetch_look_async`` grew a ``fetch=`` seam so the interesting half — what is
# asked for, what is refused, where it lands — could be tested without a socket.
# The index fetch had no such seam, which meant the one code path every user
# hits when they open "Get more" was the one path no test could reach.


def _fetch_index(getter, **kwargs):
    landed: list[tuple] = []
    registry.fetch_index_async(
        lambda entries, error: landed.append((entries, error)), fetch=getter, **kwargs
    )
    assert len(landed) == 1, "on_done must be called exactly once"
    return landed[0]


def test_the_published_list_arrives_as_entries():
    document = {"version": 2, "themes": [{"name": "seaglass", "title": "Seaglass", "version": "1"}]}

    def server(url, on_done, _timeout):
        assert url == registry.INDEX_URL
        on_done(json.dumps(document).encode(), None)

    entries, error = _fetch_index(server)
    assert error is None
    assert [e.name for e in entries] == ["seaglass"]


def test_a_list_that_cannot_be_downloaded_is_said_out_loud():
    def offline(_url, on_done, _timeout):
        on_done(None, "is not available right now (404)")

    entries, error = _fetch_index(offline)
    assert entries is None
    assert error == "the list of community Looks is not available right now (404)"


def test_a_list_that_is_not_a_registry_is_refused_rather_than_shown_empty():
    """A malformed document must not read as "nobody has published anything"."""

    def nonsense(_url, on_done, _timeout):
        on_done(b"not json at all", None)

    entries, error = _fetch_index(nonsense)
    assert entries is None
    assert error and "could not be read" in error


def test_the_address_of_the_list_can_be_pointed_somewhere_else():
    asked: list[str] = []

    def server(url, on_done, _timeout):
        asked.append(url)
        on_done(b'{"version": 2, "themes": []}', None)

    entries, error = _fetch_index(server, url="https://example.invalid/index.json")
    assert (entries, error) == ([], None)
    assert asked == ["https://example.invalid/index.json"]


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


# ── downloading a community Look ───────────────────────────────────────────
#
# No network anywhere below. A fake fetcher answers out of a dict and raises on
# an address nobody recorded, so a test that silently gained a network
# dependency fails here rather than passing on a good day and failing in CI.


LOOK_TOML = """\
format = 2

[meta]
name = "seaglass"
title = "Seaglass"
description = "A quiet green."
author = "somebody"
version = "1.0.0"
screenshots = ["shot.png"]

[[settings]]
key = "gsettings:org.gnome.desktop.interface accent-color"
value = "'green'"
component = "colors"

[[files]]
src = "files/gtk.css"
dest = "~/.config/gtk-4.0/gtk.css"
"""


def _entry(name: str = "seaglass", **overrides) -> IndexEntry:
    base = {
        "name": name,
        "title": "Seaglass",
        "description": "A quiet green.",
        "author": "somebody",
        "version": "1.0.0",
        "provenance": "community",
    }
    return IndexEntry(**{**base, **overrides})


class FakeServer:
    """Answers recorded addresses. Anything else is a test's mistake."""

    def __init__(self, routes: dict[str, bytes | str]) -> None:
        self.routes = {k: v.encode() if isinstance(v, str) else v for k, v in routes.items()}
        self.asked: list[str] = []

    def __call__(self, url, on_done, _timeout):
        self.asked.append(url)
        tail = url.rsplit("/main/themes/", 1)[-1]
        if tail not in self.routes:
            on_done(None, "it is not available right now (404)")
            return
        on_done(self.routes[tail], None)


def _published(toml: str = LOOK_TOML, name: str = "seaglass") -> dict[str, bytes | str]:
    return {
        f"{name}/theme.toml": toml,
        f"{name}/files/gtk.css": "/* nothing */",
        f"{name}/shot.png": b"pretend png",
    }


def _fetch(entry, server, into):
    landed: list[tuple] = []
    registry.fetch_look_async(entry, lambda p, e: landed.append((p, e)), into=into, fetch=server)
    assert len(landed) == 1, "on_done must be called exactly once"
    return landed[0]


# ── a name that is already taken ─────────────────────────────────────────
#
# v1 answered this with --force on a command line, which in the app meant the
# answer was always "yes, silently". Downloading a community Look called
# `magma` replaced the user's own `magma`, or hid the built-in one, with
# nothing in the interface afterwards to say which one was now which.


def test_a_free_name_is_free(tmp_path):
    assert registry.name_conflict("nobody-has-this-name", into=tmp_path) is None


def test_a_look_the_user_already_has_is_named_as_theirs(tmp_path):
    (tmp_path / "seaglass").mkdir()
    (tmp_path / "seaglass" / "theme.toml").write_text(LOOK_TOML, encoding="utf-8")
    assert registry.name_conflict("seaglass", into=tmp_path) == "yours"


def test_a_look_gtheme_ships_is_named_as_built_in(tmp_path):
    """The one that used to be invisible: the user's folder wins in discovery."""
    assert registry.name_conflict("magma", into=tmp_path) == "built-in"


def test_installing_over_a_look_that_is_here_is_refused_until_it_is_asked_for(tmp_path):
    server = FakeServer(_published())
    first = _fetch(_entry(), server, tmp_path)
    assert first[1] is None

    (tmp_path / "seaglass" / "theme.toml").write_text(
        LOOK_TOML.replace("Seaglass", "The one I already had"), encoding="utf-8"
    )

    path, error = _fetch(_entry(), FakeServer(_published()), tmp_path)
    assert path is None
    assert error and "already here" in error
    # And the Look that was there is untouched.
    assert "The one I already had" in (tmp_path / "seaglass" / "theme.toml").read_text()


def test_saying_replace_installs_over_it(tmp_path):
    (tmp_path / "seaglass").mkdir()
    (tmp_path / "seaglass" / "theme.toml").write_text("format = 2\n", encoding="utf-8")

    landed = []
    registry.fetch_look_async(
        _entry(),
        lambda p, e: landed.append((p, e)),
        into=tmp_path,
        replace=True,
        fetch=FakeServer(_published()),
    )
    path, error = landed[0]
    assert error is None, error
    assert path == tmp_path / "seaglass"
    assert "Seaglass" in (path / "theme.toml").read_text()


def test_a_replace_that_fails_at_the_last_step_keeps_the_look_that_was_there(tmp_path, monkeypatch):
    """Pins review finding preset/registry.py:406 (the replace half).

    The old order deleted the destination and *then* renamed the validated
    staging copy over it; a failure in between lost both — the Look the user
    had and the one just downloaded, since the BaseException handler removes
    staging. The old copy is now moved aside and put back.
    """
    (tmp_path / "seaglass").mkdir()
    (tmp_path / "seaglass" / "theme.toml").write_text(
        LOOK_TOML.replace("Seaglass", "The one I already had"), encoding="utf-8"
    )

    real_replace = registry.os.replace

    def explode(src, dst):
        if Path(src).name.endswith(".downloading"):
            raise OSError("no space left on device")
        return real_replace(src, dst)

    monkeypatch.setattr(registry.os, "replace", explode)

    landed = []
    registry.fetch_look_async(
        _entry(),
        lambda p, e: landed.append((p, e)),
        into=tmp_path,
        replace=True,
        fetch=FakeServer(_published()),
    )
    path, error = landed[0]
    assert path is None and error
    assert "The one I already had" in (tmp_path / "seaglass" / "theme.toml").read_text()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["seaglass"]


def test_a_look_whose_name_starts_with_a_dot_is_refused(tmp_path):
    """Pins review finding preset/registry.py:406 (the hidden-folder half).

    discover() skips dot-named folders so an abandoned '.name.downloading'
    staging folder is never listed as a Look; a Look actually called '.x'
    would therefore install and then be invisible, so it is refused instead.
    """
    with pytest.raises(registry.LookFetchError) as raised:
        registry.install_look(_entry(name=".sneaky"), {"theme.toml": b"format = 2\n"}, into=tmp_path)
    assert "dot" in str(raised.value)
    assert list(tmp_path.iterdir()) == []


def test_the_refusal_names_which_kind_of_collision_it_is(tmp_path):
    (tmp_path / "seaglass").mkdir()
    (tmp_path / "seaglass" / "theme.toml").write_text("format = 2\n", encoding="utf-8")
    with pytest.raises(registry.LookNameTaken) as raised:
        registry.install_look(_entry(), {"theme.toml": b"format = 2\n"}, into=tmp_path)
    assert raised.value.name == "seaglass"
    assert raised.value.held_by == "yours"


def test_a_published_look_is_downloaded_and_becomes_usable(tmp_path):
    server = FakeServer(_published())
    path, error = _fetch(_entry(), server, tmp_path)

    assert error is None, error
    assert path == tmp_path / "seaglass"
    assert (path / "theme.toml").is_file()
    assert (path / "files" / "gtk.css").read_text() == "/* nothing */"
    assert (path / "shot.png").read_bytes() == b"pretend png"

    result = load(path)
    assert result.ok, result.errors
    assert result.preset.meta.name == "seaglass"


def test_a_downloaded_look_is_badged_as_somebody_elses(tmp_path):
    """It lands in the user's own folder; without a marker it would say "Yours"."""
    path, _error = _fetch(_entry(), FakeServer(_published()), tmp_path)
    assert (path / ORIGIN_FILENAME).is_file()
    assert load(path).provenance == "community"


def test_only_what_the_look_declares_is_asked_for(tmp_path):
    """A Look is a declaration. There is no directory listing to walk."""
    server = FakeServer({**_published(), "seaglass/secret.txt": "not declared"})
    path, _error = _fetch(_entry(), server, tmp_path)
    assert not (path / "secret.txt").exists()
    assert not any("secret" in url for url in server.asked)
    assert server.asked[0].endswith("/seaglass/theme.toml"), "the description comes first"


def test_a_look_that_could_run_a_command_does_not_validate_and_is_not_installed(tmp_path):
    """The declarative-only promise, enforced by the format rather than a scan.

    A v1 Look with a [[hooks]] table does not validate as v2 — Preset forbids
    unknown fields — so there is no path by which a downloaded Look smuggles a
    command onto somebody's machine. Validating *before* installing is what
    makes that a property of the download and not only of the format.
    """
    hooked = LOOK_TOML + '\n[[hooks]]\nscript = "pwn.sh"\nsudo = true\n'
    path, error = _fetch(_entry(), FakeServer(_published(hooked)), tmp_path)

    assert path is None
    assert "understand" in error
    assert list(tmp_path.iterdir()) == [], "nothing was written at all"


@pytest.mark.parametrize(
    "escape",
    ["../../.bashrc", "/etc/passwd", "files/../../../.ssh/authorized_keys"],
)
def test_a_look_that_reaches_outside_its_own_folder_is_refused(tmp_path, escape):
    """These strings come off the internet inside a document somebody wrote."""
    toml = LOOK_TOML.replace('src = "files/gtk.css"', f'src = "{escape}"')
    server = FakeServer(_published(toml))
    path, error = _fetch(_entry(), server, tmp_path)

    assert path is None
    assert "outside its own folder" in error
    assert list(tmp_path.iterdir()) == []
    assert not any(escape.split("/")[-1] in url for url in server.asked), (
        "it must be refused before a single byte of it is requested"
    )


def test_a_look_whose_name_could_escape_is_refused_before_anything_is_asked(tmp_path):
    server = FakeServer(_published())
    path, error = _fetch(_entry(name="../../etc"), server, tmp_path)
    assert path is None
    assert "name" in error
    assert server.asked == []


def test_a_missing_picture_costs_the_picture_and_not_the_look(tmp_path):
    """One 404 on an optional file must not lose the whole download."""
    published = _published()
    del published["seaglass/shot.png"]
    path, error = _fetch(_entry(), FakeServer(published), tmp_path)

    assert error is None, error
    assert (path / "theme.toml").is_file()
    assert not (path / "shot.png").exists()


def test_a_description_that_cannot_be_downloaded_is_an_honest_refusal(tmp_path):
    path, error = _fetch(_entry(), FakeServer({}), tmp_path)
    assert path is None
    assert "Seaglass could not be downloaded" in error
    assert list(tmp_path.iterdir()) == []


def test_a_description_that_is_not_readable_at_all_is_an_honest_refusal(tmp_path):
    path, error = _fetch(_entry(), FakeServer({"seaglass/theme.toml": "not toml ["}), tmp_path)
    assert path is None
    assert "description file could not be read" in error


def test_downloading_over_a_look_of_the_same_name_replaces_it_whole(tmp_path):
    """No half-replaced Look. The old folder is swapped, never edited."""
    existing = tmp_path / "seaglass"
    (existing / "files").mkdir(parents=True)
    (existing / "leftover.txt").write_text("from the old one", encoding="utf-8")

    path, error = _fetch(_entry(), FakeServer(_published()), tmp_path)
    assert error is None, error
    assert not (path / "leftover.txt").exists()


def test_a_refused_download_leaves_no_staging_folder_behind(tmp_path):
    _fetch(_entry(), FakeServer(_published(LOOK_TOML + '\n[[hooks]]\nscript = "x.sh"\n')), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_the_look_address_is_built_from_the_registry_url_not_a_second_one():
    """Two spellings of one location is one of them going stale."""
    assert registry.LOOK_BASE_URL == INDEX_URL.rsplit("/", 1)[0]
    assert registry.look_url("seaglass", "files/gtk.css") == (
        "https://raw.githubusercontent.com/blyatiful1/gtheme/main/themes/"
        "seaglass/files/gtk.css"
    )
