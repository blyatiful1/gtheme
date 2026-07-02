"""Tests for the file-write path of the apply engine (the AF* audit fixes).

These construct FileOp directly so they exercise _write_file without touching
global paths/baseline state or the real gsettings backend.
"""

from __future__ import annotations

import os

import pytest

from gtheme.engine.apply import FileOp, _write_file, _has_session_bus
from gtheme.manifest import FileInstall


def _op(tmp_path, content=b"data", *, mode=None, template=False, dest_name="out.conf"):
    src = tmp_path / "src.conf"
    src.write_bytes(content)
    fi = FileInstall(component="c", src="files/src.conf", dest=f"~/{dest_name}",
                     mode=mode, template=template)
    return FileOp(fi, src=src, dest=tmp_path / dest_name)


def test_write_file_basic(tmp_path):
    op = _op(tmp_path, b"hello")
    _write_file(op)
    assert op.dest.read_bytes() == b"hello"


def test_write_file_applies_mode(tmp_path):
    op = _op(tmp_path, b"#!/bin/sh\n", mode="755")
    _write_file(op)
    assert (op.dest.stat().st_mode & 0o777) == 0o755


def test_write_file_refuses_directory_dest(tmp_path):
    op = _op(tmp_path)
    op.dest.mkdir()  # dest is now an existing directory
    with pytest.raises(IsADirectoryError):
        _write_file(op)
    # the directory must be left intact, with no stray file written inside
    assert op.dest.is_dir()
    assert list(op.dest.iterdir()) == []


def test_write_file_template_on_binary_raises_and_does_not_truncate(tmp_path):
    op = _op(tmp_path, b"\x89PNG\x00\xff", template=True)
    op.dest.write_bytes(b"PRE-EXISTING")
    with pytest.raises(ValueError):
        _write_file(op)
    # the live dest must NOT be truncated to 0 bytes
    assert op.dest.read_bytes() == b"PRE-EXISTING"


def test_write_file_replaces_symlink_not_target(tmp_path):
    target = tmp_path / "real-target"
    target.write_bytes(b"TARGET-UNTOUCHED")
    op = _op(tmp_path, b"new-content")
    op.dest.symlink_to(target)
    _write_file(op)
    assert not op.dest.is_symlink()
    assert op.dest.read_bytes() == b"new-content"
    assert target.read_bytes() == b"TARGET-UNTOUCHED"  # never written through


def test_has_session_bus(monkeypatch):
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    assert _has_session_bus() is True
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", os.path.dirname(__file__))
    # no 'bus' socket under this dir -> False
    assert _has_session_bus() is False
