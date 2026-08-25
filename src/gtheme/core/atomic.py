"""Writes that a power cut cannot tear in half.

Every byte gtheme puts on disk — a Look's file, the ownership ledger, a
baseline index — goes through here. The rule is the same everywhere: write a
sibling temporary file, ``fsync`` it, then ``os.replace`` it into place, and
``fsync`` the directory afterwards. ``os.replace`` is atomic within a
filesystem, so at no instant does the destination contain a half-written file:
it holds either the old contents or the new ones.

Two details that look fussy and are not:

* **A symlink at the destination is replaced, not written through.** v1 learned
  this from ``~/.config/ghostty``, which on this machine is a symlink into a
  separate rice repository. Writing through it would edit somebody else's git
  checkout.
* **JSON state keeps a ``.bak``.** :func:`load_json` falls back to it and never
  raises, because a corrupt ownership ledger must degrade to "I have forgotten
  what I own", never to "the app will not start".
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

__all__ = [
    "atomic_write_bytes",
    "atomic_write_json",
    "atomic_write_text",
    "fsync_dir",
    "load_json",
]


def fsync_dir(directory: Path) -> None:
    """Flush a directory entry, so a rename survives a crash. Best effort."""
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_bytes(dest: Path, data: bytes, mode: int | None = None) -> None:
    """Write ``data`` to ``dest`` atomically.

    Args:
        dest: the file to write. Its parent must already exist.
        data: the exact bytes to land.
        mode: permission bits to set on the result, or None to leave the
            temporary file's default.

    A symlink at ``dest`` is removed first, so the link target is never
    modified.
    """
    tmp = dest.with_name(dest.name + ".gtheme-tmp")
    try:
        with open(tmp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        if dest.is_symlink():
            dest.unlink()
        os.replace(tmp, dest)
        fsync_dir(dest.parent)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def atomic_write_text(dest: Path, text: str, mode: int | None = None) -> None:
    """:func:`atomic_write_bytes` for UTF-8 text."""
    atomic_write_bytes(dest, text.encode("utf-8"), mode)


def atomic_write_json(path: Path, data: Any) -> None:
    """Write ``data`` as JSON, keeping the previous file as ``<name>.bak``.

    The ``.bak`` is what :func:`load_json` falls back to. Copying it before the
    write means the fallback is always one generation behind, never a partial
    copy of the generation being written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        try:
            shutil.copy2(path, path.with_name(path.name + ".bak"))
        except OSError:
            pass
    atomic_write_text(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def load_json(path: Path, default: Any) -> tuple[Any, str | None]:
    """Read JSON from ``path``. Never raises.

    Returns:
        ``(value, warning)``. On a clean read the warning is None. On a corrupt
        file the ``.bak`` is tried and the warning says so; if that fails too,
        ``default`` comes back with a warning naming what was lost. A caller
        that ignores the warning still gets a usable value, which is the point.
    """
    if not path.is_file():
        return default, None
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, ValueError):
        pass
    backup = path.with_name(path.name + ".bak")
    if backup.is_file():
        try:
            value = json.loads(backup.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            value = None
        else:
            return value, f"{path.name} was damaged; recovered the previous copy"
    return default, f"{path.name} was damaged and could not be recovered; starting fresh"
