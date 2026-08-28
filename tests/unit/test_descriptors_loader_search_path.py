"""Where the corpus is looked for, and the installs that used to be missed.

The search order is the whole of an install's correctness: if the corpus is not
found, thirteen of the fifteen pages render with nothing on them and say
nothing about why. Three of the four ways this app can be installed put the
data in three different places, and only one of them is named by XDG_DATA_DIRS.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from gtheme.panels import loader


@pytest.fixture(autouse=True)
def _no_data_dir_override(monkeypatch: pytest.MonkeyPatch):
    """These tests are about the fallbacks, so the override has to be off."""
    monkeypatch.delenv(loader.DATA_DIR_ENV, raising=False)


def _corpus_at(root: Path) -> Path:
    (root / "panels").mkdir(parents=True)
    (root / "domains").mkdir(parents=True)
    return root


def test_a_plain_install_into_a_virtual_environment_is_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """`pip install .` into a virtual environment, which is what CONTRIBUTING says.

    The data lands at <venv>/share/gtheme, which no environment variable
    names. Before this was searched, that install found no corpus at all.
    """
    venv = tmp_path / "venv"
    installed = _corpus_at(venv / "share" / "gtheme")
    monkeypatch.setattr(loader, "_CHECKOUT_DATA_DIR", tmp_path / "not-a-checkout")
    monkeypatch.setattr(sys, "prefix", str(venv))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "empty-home"))
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "empty-system"))

    assert loader.data_dir() == installed


def test_a_per_user_install_is_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """`pip install --user`, and distribution packages that stage into the home."""
    home = tmp_path / "userdata"
    installed = _corpus_at(home / "gtheme")
    monkeypatch.setattr(loader, "_CHECKOUT_DATA_DIR", tmp_path / "not-a-checkout")
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "empty-prefix"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home))
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "empty-system"))

    assert loader.data_dir() == installed


def test_the_system_copy_is_still_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The distribution package, which is the one that always worked."""
    system = tmp_path / "usr" / "share"
    installed = _corpus_at(system / "gtheme")
    monkeypatch.setattr(loader, "_CHECKOUT_DATA_DIR", tmp_path / "not-a-checkout")
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "empty-prefix"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "empty-home"))
    monkeypatch.setenv("XDG_DATA_DIRS", str(system))

    assert loader.data_dir() == installed


def test_the_copy_belonging_to_this_program_wins_over_the_shared_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """All four exist at once. The one installed alongside this code is right."""
    venv = tmp_path / "venv"
    _corpus_at(venv / "share" / "gtheme")
    _corpus_at(tmp_path / "userdata" / "gtheme")
    _corpus_at(tmp_path / "usr" / "share" / "gtheme")
    monkeypatch.setattr(loader, "_CHECKOUT_DATA_DIR", tmp_path / "not-a-checkout")
    monkeypatch.setattr(sys, "prefix", str(venv))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "userdata"))
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "usr" / "share"))

    assert loader.data_dir() == venv / "share" / "gtheme"


def test_the_search_order_reads_most_specific_first(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XDG_DATA_HOME", "/somewhere/mine")
    monkeypatch.setenv("XDG_DATA_DIRS", "/somewhere/shared:/somewhere/else")
    order = loader.data_dir_candidates("/asked/for")

    assert order == [
        Path("/asked/for"),
        loader._CHECKOUT_DATA_DIR,
        Path(sys.prefix) / "share" / "gtheme",
        Path("/somewhere/mine/gtheme"),
        Path("/somewhere/shared/gtheme"),
        Path("/somewhere/else/gtheme"),
    ]


def test_the_override_is_tried_before_anything_that_is_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv(loader.DATA_DIR_ENV, str(tmp_path))
    order = loader.data_dir_candidates()

    assert order[0] == tmp_path
    assert Path(sys.prefix) / "share" / "gtheme" in order


# -- existing is not the same as being a corpus ----------------------------


def test_a_directory_that_is_not_a_corpus_does_not_shadow_the_one_that_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The bug the per-user candidate introduced, on a real machine's shape.

    ``~/.local/share/gtheme`` is a name other things use: a gtheme v1 left one
    behind holding ``assets/`` and ``themes/`` and no descriptors at all.
    Taking it because it was a directory shadowed the distribution's copy and
    rendered thirteen of fifteen pages blank with nothing in ``problems``.
    """
    home = tmp_path / "userdata"
    leftover = home / "gtheme"
    (leftover / "assets").mkdir(parents=True)
    (leftover / "themes").mkdir()
    system = tmp_path / "usr" / "share"
    installed = _corpus_at(system / "gtheme")
    monkeypatch.setattr(loader, "_CHECKOUT_DATA_DIR", tmp_path / "not-a-checkout")
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "empty-prefix"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home))
    monkeypatch.setenv("XDG_DATA_DIRS", str(system))

    assert loader.data_dir() == installed


def test_half_a_corpus_is_still_a_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """One of the two directories is enough, deliberately.

    An install that shipped ``domains/`` and lost ``panels/`` is a packaging
    fault worth seeing. It is seen by loading the half that is there and
    reporting nothing for the rest — not by walking past the directory.
    """
    home = tmp_path / "userdata"
    (home / "gtheme" / "domains").mkdir(parents=True)
    monkeypatch.setattr(loader, "_CHECKOUT_DATA_DIR", tmp_path / "not-a-checkout")
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "empty-prefix"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home))
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "empty-system"))

    assert loader.data_dir() == home / "gtheme"


def test_nowhere_holding_a_corpus_is_nowhere(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Directories that exist and hold no descriptors are not an answer."""
    home = tmp_path / "userdata"
    (home / "gtheme" / "themes").mkdir(parents=True)
    (tmp_path / "usr" / "share" / "gtheme").mkdir(parents=True)
    monkeypatch.setattr(loader, "_CHECKOUT_DATA_DIR", tmp_path / "not-a-checkout")
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "empty-prefix"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home))
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "usr" / "share"))

    assert loader.data_dir() is None


def test_a_directory_somebody_named_is_taken_as_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The override is not second-guessed, even when it holds no corpus.

    Being quietly passed over in favour of the checkout further down the list
    would have the person reading data they did not ask for, with nothing on
    screen to tell them so. An empty corpus is the honest answer to an empty
    directory.
    """
    empty = tmp_path / "pointed-at"
    empty.mkdir()
    _corpus_at(tmp_path / "usr" / "share" / "gtheme")
    monkeypatch.setenv(loader.DATA_DIR_ENV, str(empty))
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "usr" / "share"))

    assert loader.data_dir() == empty
    assert loader.data_dir(tmp_path / "asked-for-and-absent") == empty
