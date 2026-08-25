"""The write path itself: rerooting, confinement, atomicity."""

from __future__ import annotations

import inspect
import os
from pathlib import Path

import pytest

from gtheme.terminal import fsio


def test_dest_root_follows_the_env_seam(tmp_dest_root: Path):
    assert fsio.dest_root() == tmp_dest_root
    assert fsio.config_root() == tmp_dest_root / ".config"
    assert fsio.data_root() == tmp_dest_root / ".local" / "share"


def test_config_root_ignores_xdg_when_a_test_root_is_set(
    tmp_dest_root: Path, monkeypatch: pytest.MonkeyPatch
):
    """The sandbox root has to win, or a test writes outside its sandbox."""
    monkeypatch.setenv("XDG_CONFIG_HOME", "/etc")
    assert fsio.config_root() == tmp_dest_root / ".config"


def test_unsafe_root_is_refused(monkeypatch: pytest.MonkeyPatch):
    """The v1 E1 case: a root of '/' makes every path 'inside' it.

    The wording is core's, because the check is core's — the refusal is phrased
    for the person reading it, not for the developer who wrote it.
    """
    monkeypatch.setenv("GTHEME_DEST_ROOT", "/")
    with pytest.raises(fsio.ConfinementError, match="the whole disk"):
        fsio.dest_root()


def test_relative_root_is_refused(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GTHEME_DEST_ROOT", "relative/place")
    with pytest.raises(fsio.ConfinementError, match="not a full location"):
        fsio.dest_root()


def test_expand_maps_home_onto_the_root(tmp_dest_root: Path):
    assert fsio.expand("~/.config/x") == tmp_dest_root / ".config" / "x"
    assert fsio.expand("$HOME/y") == tmp_dest_root / "y"
    assert fsio.expand("~") == tmp_dest_root


def test_confine_refuses_a_path_that_climbs_out(tmp_dest_root: Path):
    with pytest.raises(fsio.ConfinementError):
        fsio.confine("~/../elsewhere/file")
    with pytest.raises(fsio.ConfinementError):
        fsio.confine("/etc/passwd")


def test_confine_refuses_a_symlinked_directory_that_escapes(tmp_dest_root: Path, tmp_path: Path):
    """The F7 shape, checked at the lowest level: symlinks resolve first."""
    outside = tmp_path / "somewhere-else"
    outside.mkdir()
    link = tmp_dest_root / ".config"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside)
    with pytest.raises(fsio.ConfinementError, match="outside"):
        fsio.confine("~/.config/ghostty/config")


@pytest.mark.mutating
def test_atomic_write_replaces_and_leaves_no_temp_file(tmp_dest_root: Path):
    target = tmp_dest_root / "nested" / "config"
    fsio.atomic_write_text(target, "one\n")
    fsio.atomic_write_text(target, "two\n")
    assert target.read_text() == "two\n"
    assert [p.name for p in target.parent.iterdir()] == ["config"]


@pytest.mark.mutating
def test_a_failed_write_leaves_the_original_and_no_debris(
    tmp_dest_root: Path, monkeypatch: pytest.MonkeyPatch
):
    target = tmp_dest_root / "config"
    fsio.atomic_write_text(target, "original\n")

    def explode(*args: object, **kwargs: object) -> None:
        raise OSError("disk gave up")

    monkeypatch.setattr(os, "replace", explode)
    with pytest.raises(OSError, match="disk gave up"):
        fsio.atomic_write_text(target, "replacement\n")
    assert target.read_text() == "original\n"
    assert [p.name for p in tmp_dest_root.iterdir()] == ["config"]


def test_state_root_prefers_its_own_seam(tmp_dest_root: Path, state_dir: Path):
    assert fsio.state_root() == state_dir


def test_fsio_is_core_and_not_a_second_implementation():
    """Ruling 16: one confinement engine, one atomic writer, two names.

    The sharp end is the exception class. Two ``ConfinementError`` types would
    mean an ``except`` in a terminal adapter silently failing to catch a
    refusal raised by core, or the other way round.
    """
    from gtheme.core.atomic import atomic_write_bytes as core_write
    from gtheme.core.confine import ConfinementError as CoreConfinementError
    from gtheme.core.confine import confine_dest, expand_dest

    assert fsio.ConfinementError is CoreConfinementError
    assert fsio.confine("~/x") == confine_dest("~/x")
    assert fsio.expand("~/x") == expand_dest("~/x")
    # The write itself is core's; fsio only makes the parent directory first.
    source = inspect.getsource(fsio.atomic_write_bytes)
    assert "_atomic.atomic_write_bytes" in source
    assert "mkstemp" not in inspect.getsource(fsio)
    assert core_write is not None
