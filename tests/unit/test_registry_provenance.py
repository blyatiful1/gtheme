"""Where a listed Look came from, and what its tile is allowed to show.

Three findings from the usability audit meet in this file, and they are really
one finding: the "Get more Looks" tab was a mirror. The published index lists
the four Looks that ship inside gtheme, every entry said ``provenance:
"bundled"``, every tile badged "Already on this computer", and clicking one
bounced the person back to the tab they came from — so the honest empty state
("Nobody has published a Look yet. Yours could be the first.") was unreachable.
On top of that ``entry_for()`` defaulted to ``"bundled"``, so the first Look
somebody else contributed would have been published as one of gtheme's own. And
every community tile was drawn as a neutral grey card, because nothing ever
fetched the picture the index already names.

No network anywhere below: every fetch goes through the seam the module already
takes, so a test that quietly grew a network dependency fails here rather than
passing on a good day.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gtheme.preset.emit import dumps_preset
from gtheme.preset.loader import ORIGIN_FILENAME
from gtheme.preset.model import Meta, Preset
from gtheme.preset.registry import (
    LOOK_BASE_URL,
    MAX_LOOK_FILE_BYTES,
    IndexEntry,
    browsable,
    build_index,
    bundled_look_names,
    cached_screenshot,
    entry_for,
    fetch_screenshot_async,
    parse_index,
    screenshot_cache_dir,
    screenshot_url,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"pretend the rest of a picture"


def _entry(name: str = "seaglass", **overrides) -> IndexEntry:
    base = {
        "name": name,
        "title": "Seaglass",
        "description": "A quiet green.",
        "author": "somebody",
        "version": "1.0.0",
        "screenshots": ["shot.png"],
        "provenance": "community",
    }
    return IndexEntry(**{**base, **overrides})


def _a_look(folder: Path, name: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    preset = Preset(
        format=2,
        meta=Meta(
            name=name,
            title=name.title(),
            description="",
            author="somebody",
            version="1.0.0",
            screenshots=["shot.png"],
        ),
    )
    (folder / "theme.toml").write_text(dumps_preset(preset), encoding="utf-8")
    (folder / "shot.png").write_bytes(PNG)


# ── who published this Look ───────────────────────────────────────────────


def test_describing_a_look_will_not_guess_who_published_it():
    """The old default said "bundled" — gtheme vouching for a stranger's Look."""
    preset = Preset(
        format=2,
        meta=Meta(name="a", title="A", description="", author="", version="1"),
    )
    with pytest.raises(TypeError):
        entry_for(preset)  # type: ignore[call-arg]


def test_a_made_up_origin_is_refused_rather_than_published():
    preset = Preset(
        format=2,
        meta=Meta(name="a", title="A", description="", author="", version="1"),
    )
    with pytest.raises(ValueError, match="bundled, community or user"):
        entry_for(preset, provenance="official")


def test_an_entry_that_never_said_where_it_came_from_is_not_treated_as_ours():
    assert IndexEntry(name="a", title="A", description="", author="", version="1").provenance == (
        "community"
    )
    assert not IndexEntry(name="a", title="A", description="", author="", version="1").is_bundled


def test_a_downloaded_look_copied_into_the_folder_keeps_its_own_origin(tmp_path: Path):
    """Merging somebody's Look into themes/ must not relabel it as gtheme's."""
    _a_look(tmp_path / "ours", "ours")
    _a_look(tmp_path / "theirs", "theirs")
    (tmp_path / "theirs" / ORIGIN_FILENAME).write_text(
        json.dumps({"provenance": "community", "name": "theirs", "author": "somebody"}),
        encoding="utf-8",
    )

    document, skipped = build_index(tmp_path)

    assert skipped == []
    origins = {entry["name"]: entry["provenance"] for entry in document["themes"]}
    assert origins == {"ours": "bundled", "theirs": "community"}


def test_indexing_a_collection_of_other_peoples_looks_says_so(tmp_path: Path):
    _a_look(tmp_path / "theirs", "theirs")
    document, _skipped = build_index(tmp_path, provenance="community")
    assert [entry["provenance"] for entry in document["themes"]] == ["community"]


def test_the_shipped_looks_are_still_published_as_gthemes_own(repo_root: Path):
    document = json.loads((repo_root / "themes" / "index.json").read_text(encoding="utf-8"))
    assert {entry["provenance"] for entry in document["themes"]} == {"bundled"}


# ── what the Browse tab may offer ─────────────────────────────────────────


def test_the_published_index_offers_nothing_new_and_says_so(repo_root: Path):
    """The audit's finding, pinned: today's registry is four Looks you have.

    An empty grid is the truth here, and the truth invites somebody to publish
    the first one. Four tiles badged "Already on this computer" invite nothing.
    """
    entries = parse_index((repo_root / "themes" / "index.json").read_text(encoding="utf-8"))
    assert len(entries) == 4, "the committed index changed; this test needs re-reading"
    assert browsable(entries, shipped={"magma", "netrunner", "hyperclass", "nightbloom"}) == []


def test_a_look_somebody_else_published_is_offered():
    entry = _entry()
    assert browsable([entry], shipped={"magma"}) == [entry]


def test_a_mirror_of_a_look_that_ships_is_not_offered_however_it_labels_itself():
    """A stale or mislabelled entry must not smuggle a mirror back into the grid."""
    assert browsable([_entry(name="magma")], shipped={"magma"}) == []


def test_a_look_with_no_picture_is_not_offered():
    """Nobody should be asked to install a desktop they cannot see first."""
    assert browsable([_entry(screenshots=[])], shipped=set()) == []


def test_the_shipped_names_are_read_off_disk(tmp_path: Path, monkeypatch):
    _a_look(tmp_path / "seaglass", "seaglass")
    monkeypatch.setenv("GTHEME_BUNDLED_THEMES_DIR", str(tmp_path))
    assert bundled_look_names() == frozenset({"seaglass"})
    assert browsable([_entry()]) == []


# ── the picture on a tile ─────────────────────────────────────────────────


class FakeServer:
    """Answers one recorded address. Anything else is a 404, like the real one."""

    def __init__(self, routes: dict[str, bytes]) -> None:
        self.routes = routes
        self.asked: list[str] = []

    def __call__(self, url, on_done, _timeout):
        self.asked.append(url)
        payload = self.routes.get(url)
        if payload is None:
            on_done(None, "is not available right now (404)")
            return
        on_done(payload, None)


def _fetch(entry: IndexEntry, server, cache: Path):
    landed: list[tuple] = []
    fetch_screenshot_async(
        entry, lambda p, e: landed.append((p, e)), cache_dir=cache, fetch=server
    )
    assert len(landed) == 1, "on_done must be called exactly once"
    return landed[0]


def test_the_picture_the_index_names_is_the_one_fetched():
    assert screenshot_url(_entry()) == f"{LOOK_BASE_URL}/seaglass/shot.png"


def test_a_look_with_no_picture_has_no_address():
    assert screenshot_url(_entry(screenshots=[])) is None


def test_a_picture_path_reaching_outside_the_look_has_no_address():
    """A bad path is a reason to draw the fallback card, never a crash."""
    assert screenshot_url(_entry(screenshots=["../../../etc/passwd"])) is None
    assert screenshot_url(_entry(name="../elsewhere")) is None


def test_a_fetched_picture_lands_somewhere_a_tile_can_point_at(tmp_path: Path):
    server = FakeServer({f"{LOOK_BASE_URL}/seaglass/shot.png": PNG})
    path, error = _fetch(_entry(), server, tmp_path)
    assert error is None
    assert path is not None and path.read_bytes() == PNG
    assert path.parent == tmp_path


def test_a_picture_already_fetched_is_not_asked_for_again(tmp_path: Path):
    entry = _entry()
    server = FakeServer({f"{LOOK_BASE_URL}/seaglass/shot.png": PNG})
    first, _ = _fetch(entry, server, tmp_path)
    assert cached_screenshot(entry, cache_dir=tmp_path) == first

    second, error = _fetch(entry, server, tmp_path)
    assert (second, error) == (first, None)
    assert len(server.asked) == 1, "a cache hit must not touch the network"


def test_a_new_version_of_a_look_is_not_shown_last_years_desktop(tmp_path: Path):
    server = FakeServer({f"{LOOK_BASE_URL}/seaglass/shot.png": PNG})
    first, _ = _fetch(_entry(version="1.0.0"), server, tmp_path)
    second, _ = _fetch(_entry(version="2.0.0"), server, tmp_path)
    assert first != second
    assert len(server.asked) == 2


def test_nothing_is_cached_before_the_picture_arrives(tmp_path: Path):
    assert cached_screenshot(_entry(), cache_dir=tmp_path) is None


def test_a_picture_that_cannot_be_downloaded_leaves_the_tile_to_its_fallback(tmp_path: Path):
    server = FakeServer({})
    path, error = _fetch(_entry(), server, tmp_path)
    assert path is None
    assert error is not None and "404" in error
    assert list(tmp_path.iterdir()) == [], "a failed fetch must cache nothing"


def test_something_that_is_not_an_image_is_refused_rather_than_cached(tmp_path: Path):
    server = FakeServer({f"{LOOK_BASE_URL}/seaglass/shot.png": b"<html>404 not found</html>"})
    path, error = _fetch(_entry(), server, tmp_path)
    assert path is None
    assert error is not None and "not an image" in error
    assert list(tmp_path.iterdir()) == []


def test_an_enormous_picture_is_refused(tmp_path: Path):
    huge = PNG + b"\0" * (MAX_LOOK_FILE_BYTES + 1)
    server = FakeServer({f"{LOOK_BASE_URL}/seaglass/shot.png": huge})
    path, error = _fetch(_entry(), server, tmp_path)
    assert path is None
    assert error is not None and "larger" in error
    assert list(tmp_path.iterdir()) == []


def test_a_look_with_no_picture_is_answered_without_asking_anybody(tmp_path: Path):
    server = FakeServer({})
    path, error = _fetch(_entry(screenshots=[]), server, tmp_path)
    assert path is None
    assert error == "Seaglass has no picture to show"
    assert server.asked == []


def test_pictures_are_cached_where_the_rest_of_gtheme_caches(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GTHEME_CACHE_DIR", str(tmp_path / "throwaway"))
    assert screenshot_cache_dir() == tmp_path / "throwaway" / "looks"
