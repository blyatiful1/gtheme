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
