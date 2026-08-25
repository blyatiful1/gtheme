"""Writes that cannot be torn in half, and state that cannot be lost.

The two properties tested here are the ones every other guarantee in the engine
sits on. If a file write can leave a truncated destination, the pristine copy is
not enough to recover — the thing being recovered *to* was destroyed. And if
the ownership index can be lost to a corrupt read, the app forgets what it owns
and undo silently stops working.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from gtheme.core.atomic import atomic_write_bytes, atomic_write_json, atomic_write_text, load_json


def test_a_write_lands_exactly(tmp_path: Path):
    dest = tmp_path / "file"
    atomic_write_bytes(dest, b"exact bytes")
    assert dest.read_bytes() == b"exact bytes"


def test_a_write_replaces_a_symlink_rather_than_writing_through_it(tmp_path: Path):
    """This machine's ``~/.config/ghostty`` is a link into a rice repository.

    Writing through it would edit that repository — somebody else's git
    checkout — instead of the destination the Look named.
    """
    real = tmp_path / "somewhere-else"
    real.write_text("do not touch me", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(real)

    atomic_write_text(link, "the new content")

    assert not link.is_symlink()
    assert link.read_text(encoding="utf-8") == "the new content"
    assert real.read_text(encoding="utf-8") == "do not touch me"


def test_a_failed_write_leaves_the_previous_file_intact(tmp_path: Path, monkeypatch):
    """Half a config file is worse than the old one. The rename is the commit."""
    dest = tmp_path / "file"
    dest.write_text("the old content", encoding="utf-8")

    def explode(_fd):
        raise OSError("disk full")

    monkeypatch.setattr(os, "fsync", explode)
    with pytest.raises(OSError):
        atomic_write_text(dest, "the new content")

    assert dest.read_text(encoding="utf-8") == "the old content"


def test_a_failed_write_leaves_no_temporary_file_behind(tmp_path: Path, monkeypatch):
    dest = tmp_path / "file"
    dest.write_text("old", encoding="utf-8")
    monkeypatch.setattr(os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError("nope")))
    with pytest.raises(OSError):
        atomic_write_text(dest, "new")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["file"]


def test_permissions_are_applied_and_privilege_bits_are_not(tmp_path: Path):
    dest = tmp_path / "script"
    atomic_write_bytes(dest, b"#!/bin/sh\n", 0o755)
    assert dest.stat().st_mode & 0o777 == 0o755


def test_json_state_keeps_the_previous_copy(tmp_path: Path):
    path = tmp_path / "ownership.json"
    atomic_write_json(path, {"first": 1})
    atomic_write_json(path, {"second": 2})
    assert json.loads(path.read_text()) == {"second": 2}
    assert json.loads(path.with_suffix(".json.bak").read_text()) == {"first": 1}


def test_a_damaged_index_falls_back_to_the_previous_copy(tmp_path: Path):
    """A corrupt ledger must degrade to "I have forgotten", never to a crash."""
    path = tmp_path / "ownership.json"
    atomic_write_json(path, {"good": True})
    atomic_write_json(path, {"also-good": True})
    path.write_text("{ this is not json", encoding="utf-8")

    value, warning = load_json(path, {})
    assert value == {"good": True}
    assert warning and "recovered" in warning


def test_an_unrecoverable_index_starts_fresh_and_says_so(tmp_path: Path):
    path = tmp_path / "ownership.json"
    path.write_text("{ broken", encoding="utf-8")
    value, warning = load_json(path, {"default": True})
    assert value == {"default": True}
    assert warning and "could not be recovered" in warning


def test_a_missing_index_is_not_a_warning(tmp_path: Path):
    """Never having written state is the normal first-run case, not a problem."""
    value, warning = load_json(tmp_path / "nothing-here.json", {})
    assert (value, warning) == ({}, None)


def test_json_state_is_written_sorted_so_two_runs_produce_the_same_bytes(tmp_path: Path):
    """A ledger that reorders itself makes every diff of it unreadable."""
    path = tmp_path / "a.json"
    other = tmp_path / "b.json"
    atomic_write_json(path, {"b": 1, "a": 2})
    atomic_write_json(other, {"a": 2, "b": 1})
    assert path.read_bytes() == other.read_bytes()
