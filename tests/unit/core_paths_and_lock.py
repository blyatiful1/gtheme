"""Where state lives, and the lock that keeps one gtheme from meeting another.

Two small modules with one large consequence between them. Every path is a
function reading the environment on each call, rather than a constant fixed at
import — v1 fixed them at import and a test that forgot to reload the module
wrote to the real home directory. And v2's state lives under ``v2/``, beside
v1's files rather than on top of them, because those files are the only record
of what this desktop looked like before any of this started.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from gtheme.core import paths
from gtheme.core.lock import LockBusy, process_lock

# -- paths -----------------------------------------------------------------


def test_the_destination_root_follows_its_override(monkeypatch, tmp_path):
    monkeypatch.setenv("GTHEME_DEST_ROOT", str(tmp_path))
    assert paths.dest_root() == tmp_path


def test_the_destination_root_is_read_on_every_call(monkeypatch, tmp_path):
    """v1 read it once at import, and a test that forgot to reload wrote home."""
    monkeypatch.setenv("GTHEME_DEST_ROOT", str(tmp_path / "first"))
    assert paths.dest_root().name == "first"
    monkeypatch.setenv("GTHEME_DEST_ROOT", str(tmp_path / "second"))
    assert paths.dest_root().name == "second"


def test_the_destination_root_is_the_home_folder_by_default(monkeypatch):
    monkeypatch.delenv("GTHEME_DEST_ROOT", raising=False)
    assert paths.dest_root() == Path.home()


def test_v2_state_lives_beside_v1_and_not_on_top_of_it(monkeypatch, tmp_path):
    """DESIGN.md F1. v1's files are the only copy of the original desktop."""
    monkeypatch.delenv("GTHEME_STATE_DIR", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert paths.state_dir() == tmp_path / "gtheme" / "v2"
    assert paths.state_dir().parent == tmp_path / "gtheme"


def test_the_v1_backup_is_a_separate_directory_entirely(monkeypatch, tmp_path):
    monkeypatch.delenv("GTHEME_V1_BACKUP_DIR", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert paths.v1_backup_dir() == tmp_path / "gtheme.v1-backup"
    assert paths.v1_backup_dir() != paths.state_dir()
    assert not paths.state_dir().is_relative_to(paths.v1_backup_dir())


def test_everything_the_engine_writes_is_under_the_state_override(monkeypatch, tmp_path):
    """The seam the whole test suite leans on: one variable moves all of it."""
    monkeypatch.setenv("GTHEME_STATE_DIR", str(tmp_path / "state"))
    for path in (
        paths.state_dir(),
        paths.baseline_dir(),
        paths.ledger_file(),
        paths.lock_file(),
        paths.restore_points_dir(),
    ):
        assert path.is_relative_to(tmp_path / "state")


def test_the_v1_backup_can_be_pointed_somewhere_else_for_a_test(monkeypatch, tmp_path):
    monkeypatch.setenv("GTHEME_V1_BACKUP_DIR", str(tmp_path / "fake-v1"))
    assert paths.v1_backup_dir() == tmp_path / "fake-v1"


# -- the lock --------------------------------------------------------------


def test_the_lock_can_be_taken_and_released(tmp_path):
    target = tmp_path / "lock"
    with process_lock(target):
        assert target.exists()
    with process_lock(target):
        pass


def test_a_second_attempt_fails_immediately_rather_than_waiting(tmp_path):
    """Fail fast. Queueing means the window hangs with no explanation."""
    target = tmp_path / "lock"
    with process_lock(target):
        with pytest.raises(LockBusy):
            with process_lock(target):
                pass


def test_the_lock_is_released_even_when_the_body_raises(tmp_path):
    target = tmp_path / "lock"
    with pytest.raises(ValueError):
        with process_lock(target):
            raise ValueError("something went wrong")
    with process_lock(target):
        pass


def test_the_message_is_one_a_person_can_act_on(tmp_path):
    target = tmp_path / "lock"
    with process_lock(target):
        with pytest.raises(LockBusy) as caught:
            with process_lock(target):
                pass
    message = str(caught.value)
    assert "wait for it to finish" in message
    from gtheme.ui import jargon

    assert jargon.check(message) == []


def test_the_lock_creates_its_directory_if_it_has_to(tmp_path):
    target = tmp_path / "not" / "there" / "yet" / "lock"
    with process_lock(target):
        assert target.is_file()


def test_the_lock_is_held_against_another_process(tmp_path):
    """A thread would share the file descriptor; flock is between processes."""
    import subprocess
    import sys

    target = tmp_path / "lock"
    code = (
        "import fcntl, os, sys\n"
        f"fd = os.open({str(target)!r}, os.O_CREAT | os.O_RDWR, 0o644)\n"
        "try:\n"
        "    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        "except OSError:\n"
        "    print('busy'); sys.exit(0)\n"
        "print('free')\n"
    )
    with process_lock(target):
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.stdout.strip() == "busy"
    assert os.path.exists(target)
