"""The security boundary: nothing gtheme writes escapes the destination root.

A Look is a folder of files somebody downloaded. Its ``theme.toml`` says where
each file goes. If it says ``~/../../etc/sudoers``, or ships a symlink pointing
out of its own folder, the answer is not "write it and hope" — it is a refusal,
before a single byte moves.

Two directions are confined, and both matter:

* ``confine_dest`` — where a file may land. Below the destination root
  (``$HOME``, or ``GTHEME_DEST_ROOT`` under test), after resolving ``..`` and
  symlinks.
* ``confine_src`` — where a file may come from. Inside the Look's own folder,
  again after resolving symlinks, so a Look cannot use a symlink as a siphon
  for ``~/.ssh/id_ed25519``.

The E1 refusal is the subtle one. If ``$HOME`` is empty or relative, the
destination root resolves to ``/`` or to the current directory, and then
*every* path is "inside the root" — confinement silently becomes a no-op. So a
root that is not an absolute path, or that is a filesystem root, is refused
outright rather than trusted. It cost v1 a bug to notice this
(``paths.py:102-108``); it is a named regression test here.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from .paths import dest_root

__all__ = [
    "ConfinementError",
    "confine_dest",
    "confine_src",
    "expand_dest",
    "preflight_dests",
    "safe_name",
]


class ConfinementError(Exception):
    """A path would have escaped its boundary. Always fatal, never a warning.

    Attributes:
        path: the offending path as it was written, for the message the user
            sees.
    """

    def __init__(self, message: str, *, path: str | None = None) -> None:
        super().__init__(message)
        self.path = path


def _checked_root(root: str | Path | None = None) -> Path:
    """The destination root, or a refusal (E1).

    Args:
        root: an explicit root, for a transaction that carries its own.
            Defaults to the process-wide one.

    Raises:
        ConfinementError: the root is relative, empty, or a filesystem root —
            any of which would make confinement vacuous.
    """
    root = Path(root).expanduser() if root is not None else dest_root()
    if not root.is_absolute():
        raise ConfinementError(
            f"refusing to write anywhere: the destination folder {str(root)!r} is not a "
            "full location. Check your home folder setting.",
            path=str(root),
        )
    resolved = root.resolve()
    if resolved == Path(resolved.anchor):
        raise ConfinementError(
            "refusing to write anywhere: the destination folder is the whole disk. "
            "Check your home folder setting.",
            path=str(root),
        )
    return resolved


def expand_dest(dest: str, root: str | Path | None = None) -> Path:
    """Expand a Look's destination against the destination root.

    ``~`` and ``$HOME`` both mean the destination root, so a test can reroot
    every Look in the collection at once. Any other absolute location is
    returned as written — and then refused by :func:`confine_dest` unless the
    caller explicitly allowed it.
    """
    dest = dest.replace("$HOME", "~")
    if dest == "~":
        return _checked_root(root)
    if dest.startswith("~/"):
        return _checked_root(root) / dest[2:]
    return Path(dest).expanduser()


def confine_dest(
    dest: str,
    *,
    allow_outside: bool = False,
    root: str | Path | None = None,
) -> Path:
    """Expand ``dest`` and prove it stays inside the destination root.

    Args:
        dest: the destination as the Look wrote it.
        allow_outside: skip the containment check. Exists for the one caller
            that legitimately addresses a fixed system location and has said so
            out loud; a Look can never set it.
        root: an explicit destination root. A transaction carries its own, so
            that one transaction cannot be rerouted by another one changing the
            environment mid-flight.

    Raises:
        ConfinementError: the root is unusable (E1), or the path escapes it.
    """
    checked = _checked_root(root)
    expanded = expand_dest(dest, root)
    if allow_outside:
        return expanded
    try:
        resolved = expanded.resolve()
    except OSError as exc:  # pragma: no cover - symlink loop, ELOOP
        raise ConfinementError(f"cannot make sense of the location {dest!r}: {exc}", path=dest) from exc
    if not resolved.is_relative_to(checked):
        raise ConfinementError(
            f"refusing to write outside your home folder: {dest}",
            path=dest,
        )
    return expanded


def confine_src(src: str, root: str | Path) -> Path:
    """Resolve ``src`` inside ``root`` and prove it did not leave.

    Args:
        src: a location relative to ``root``, as the Look wrote it.
        root: the Look's own folder.

    Raises:
        ConfinementError: ``src`` resolves outside ``root`` — via ``..``, via
            an absolute path, or via a symlink pointing away.
    """
    root_path = Path(root)
    resolved = (root_path / src).resolve()
    if not resolved.is_relative_to(root_path.resolve()):
        raise ConfinementError(
            f"this look tried to read a file from outside its own folder: {src}",
            path=src,
        )
    return resolved


def preflight_dests(dests: Iterable[str], root: str | Path | None = None) -> list[Path]:
    """Confine every destination before the first one is written.

    This is the whole point of a preflight. Checking each file as it is written
    means a Look whose fourth file escapes has already replaced three of yours
    by the time anyone notices.

    Raises:
        ConfinementError: on the first destination that fails.
    """
    return [confine_dest(dest, root=root) for dest in dests]


def safe_name(name: str) -> str:
    """Validate a name that will become a single folder component.

    Restore point ids and Look names both end up as ``<parent>/<name>``, so a
    name of ``..`` walks out of the parent. ASCII-only on purpose: Python's
    ``str.isalnum`` is true for full-width characters, and a "look" named with
    homographs is a name nobody can distinguish from a real one.

    Raises:
        ConfinementError: the name is empty or contains anything outside
            ``[A-Za-z0-9._-]`` — and it may not be ``.`` or ``..``.
    """
    if not name or name in (".", ".."):
        raise ConfinementError(f"unusable name {name!r}", path=name)
    for char in name:
        if not char.isascii() or not (char.isalnum() or char in "-_."):
            raise ConfinementError(
                f"unusable name {name!r}: letters, digits, '-', '_' and '.' only",
                path=name,
            )
    return name
