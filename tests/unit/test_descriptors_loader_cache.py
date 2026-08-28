"""The corpus is read off disk once, not once per page.

Forty-four descriptor files and a seven-hundred-line manifest describe data
that is installed and does not change while a window is open. Re-reading them
put twenty milliseconds of parsing in front of every navigation, on the thread
that draws the window, fifteen pages over.

The rule these tests hold: the same question about the same directory is
answered from memory, a directory nobody has asked about is read, and a test
that changes a file says so with :func:`gtheme.panels.loader.reload`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gtheme.panels import loader
from gtheme.panels.loader import Corpus, load_corpus, load_dispositions, page_rows, reload

PANEL_TOML = """
id = "example"

[target]
uuids = ["example@example.com"]
schema_id = "org.gnome.shell.extensions.example"
category = "looks"
summary = "Makes the corners of windows round."

[[rows]]
schema_id = "org.gnome.shell.extensions.example"
key = "corner-radius"
title = "Corner roundness"
subtitle = "How rounded the corners of every window are."
kind = "slider"
clamp_min = 0
clamp_max = 32
"""

DOMAIN_TOML = """
id = "colors"
title = "Colours & Style"

[[rows]]
schema_id = "org.gnome.desktop.interface"
key = "color-scheme"
title = "Dark mode"
subtitle = "Use dark colours everywhere."
kind = "toggle"
"""

#: A page every build of the corpus surfaces rows onto.
PAGE = "power"


@pytest.fixture(autouse=True)
def _forget_what_was_read():
    """Nothing cached leaks into or out of one of these tests."""
    reload()
    yield
    reload()


@pytest.fixture
def corpus_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "panels").mkdir()
    (tmp_path / "domains").mkdir()
    (tmp_path / "panels" / "example.toml").write_text(PANEL_TOML, encoding="utf-8")
    (tmp_path / "domains" / "colors.toml").write_text(DOMAIN_TOML, encoding="utf-8")
    monkeypatch.setenv(loader.DATA_DIR_ENV, str(tmp_path))
    return tmp_path


class _Counter:
    def __init__(self, wrapped):
        self.wrapped = wrapped
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return self.wrapped(*args, **kwargs)


def test_the_descriptor_files_are_parsed_once_however_often_they_are_asked_for(
    corpus_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    reads = _Counter(loader._read)
    monkeypatch.setattr(loader, "_read", reads)

    first = load_corpus()
    for _ in range(5):
        load_corpus()

    assert reads.calls == 2, "two files, parsed once each"
    assert load_corpus() is first


def test_the_manifest_is_read_once_too(corpus_dir: Path):
    assert load_dispositions() is load_dispositions()


def test_a_different_directory_is_a_different_answer(corpus_dir: Path, tmp_path: Path):
    other = tmp_path / "elsewhere"
    (other / "domains").mkdir(parents=True)

    assert load_corpus().rows, "the seeded corpus has rows"
    assert load_corpus(other).rows == [], "an empty directory is empty, not the cached one"


def test_a_file_written_after_the_read_shows_up_once_reload_is_asked_for(corpus_dir: Path):
    """What :func:`reload` is for, and the reason nothing else needs it."""
    before = {domain.id for domain in load_corpus().domains}
    (corpus_dir / "domains" / "sound.toml").write_text(
        DOMAIN_TOML.replace('id = "colors"', 'id = "sound"'), encoding="utf-8"
    )

    assert {domain.id for domain in load_corpus().domains} == before

    reload()

    assert {domain.id for domain in load_corpus().domains} == before | {"sound"}


# -- the joins, which are what the pages actually call ----------------------


def _explode(*_args, **_kwargs):
    raise AssertionError("went back to disk")


def test_a_page_asked_for_twice_is_not_rebuilt_from_disk(monkeypatch: pytest.MonkeyPatch):
    first = page_rows(PAGE)
    assert first, f"{PAGE} resolved to no rows at all"

    monkeypatch.setattr(loader, "load_corpus", _explode)
    monkeypatch.setattr(loader, "load_dispositions", _explode)

    assert [row.id for row in page_rows(PAGE)] == [row.id for row in first]


def test_the_floor_is_not_rebuilt_from_disk_either(monkeypatch: pytest.MonkeyPatch):
    first = loader.floor_ids()

    monkeypatch.setattr(loader, "load_corpus", _explode)
    monkeypatch.setattr(loader, "load_dispositions", _explode)

    assert loader.floor_ids() == first


def test_a_corpus_handed_in_is_the_one_used(monkeypatch: pytest.MonkeyPatch):
    """The caller already read it. Reading it again was the whole complaint."""
    from gtheme.ui import registry

    dispositions = loader.load_dispositions()
    empty = Corpus()
    monkeypatch.setattr(loader, "load_corpus", _explode)

    assert page_rows(PAGE, corpus=empty, dispositions=dispositions) == []
    # Nothing is authored in an empty corpus, so everything on the floor page
    # is floor — which is only true if the handed-in corpus was the one read.
    assert loader.floor_ids(corpus=empty, dispositions=dispositions) == sorted(
        loader.surfaced_ids(registry.FLOOR_PAGE_ID, dispositions)
    )


def test_the_list_a_page_hands_back_belongs_to_the_caller():
    """Cached does not mean shared: throwing one away must not empty the next."""
    first = page_rows(PAGE)
    first.clear()

    assert page_rows(PAGE), "the cached rows were handed out by reference"
