"""Where terminal config lives, and how gtheme is allowed to write to it.

Every byte the terminal adapters write goes through this module. Three rules,
all of them borrowed from what v1 already learned the hard way:

* **Destinations expand against a root.** ``~/.config/ghostty/config`` means
  ``$GTHEME_DEST_ROOT/.config/ghostty/config`` when that variable is set, which
  is what lets the whole adapter suite be exercised on a throwaway tree instead
  of on the desktop the user is actually sitting in front of.
* **A resolved destination that escapes the root is refused** — not clamped,
  not warned about. ``~/.config/ghostty`` on this machine is a symlink into a
  separate git repository the user maintains by hand, and writing through it is
  exactly the accident this check exists to prevent (DESIGN.md F7).
* **Writes are atomic.** Temp file in the destination's own directory, flush,
  ``fsync``, ``os.replace``. A terminal config truncated by a crash is a
  terminal that will not start.

The E1 refusal is ported verbatim in spirit from v1's ``paths.py``: a broken
environment where the root is empty, relative, or ``/`` would make every path
"inside" the root and quietly defeat confinement, so it refuses to write at all.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

__all__ = [
    "ConfinementError",
    "atomic_write_bytes",
    "atomic_write_text",
    "config_root",
    "confine",
    "data_root",
    "dest_root",
    "expand",
    "state_root",
]


class ConfinementError(Exception):
    """A path resolved somewhere gtheme is not allowed to write."""


def _env_path(var: str) -> Path | None:
    value = os.environ.get(var)
    return Path(value).expanduser() if value else None


def dest_root() -> Path:
    """The root ``~`` expands against. ``GTHEME_DEST_ROOT`` or the real home.

    Raises:
        ConfinementError: the root is empty, relative, or the filesystem root
            (the v1 E1 case) — confinement would be meaningless, so nothing is
            written.
    """
    root = _env_path("GTHEME_DEST_ROOT") or Path.home()
    if not root.is_absolute():
        raise ConfinementError(
            f"unsafe destination root {str(root)!r} (relative); refusing to write — "
            "check $HOME / $GTHEME_DEST_ROOT"
        )
    resolved = root.resolve()
    if resolved == Path(resolved.anchor):
        raise ConfinementError(
            f"unsafe destination root {str(root)!r} (filesystem root); refusing to write — "
            "check $HOME / $GTHEME_DEST_ROOT"
        )
    return root


def config_root() -> Path:
    """The user's settings folder — ``~/.config``, rerooted when under test.

    ``XDG_CONFIG_HOME`` is honoured only when there is no destination-root
    override. Under a test root the two would contradict each other, and the
    root has to win or the test is writing outside its sandbox.
    """
    if os.environ.get("GTHEME_DEST_ROOT"):
        return dest_root() / ".config"
    return _env_path("XDG_CONFIG_HOME") or (dest_root() / ".config")


def data_root() -> Path:
    """The user's data folder — ``~/.local/share``, rerooted when under test."""
    if os.environ.get("GTHEME_DEST_ROOT"):
        return dest_root() / ".local" / "share"
    return _env_path("XDG_DATA_HOME") or (dest_root() / ".local" / "share")


def state_root() -> Path:
    """Where gtheme keeps its own runtime state (``~/.local/state/gtheme/v2``).

    v1's files live in the parent directory and are never touched (DESIGN.md
    F1). ``GTHEME_STATE_DIR`` overrides the location outright; that is the seam
    the suite uses.
    """
    override = _env_path("GTHEME_STATE_DIR")
    if override is not None:
        return override
    if os.environ.get("GTHEME_DEST_ROOT"):
        return dest_root() / ".local" / "state" / "gtheme" / "v2"
    base = _env_path("XDG_STATE_HOME") or (dest_root() / ".local" / "state")
    return base / "gtheme" / "v2"


def expand(dest: str | Path) -> Path:
    """Expand a destination against :func:`dest_root`.

    ``~`` and ``$HOME`` both mean the root. Any other absolute path is returned
    as it is — and will then fail :func:`confine`, which is the point.
    """
    text = str(dest).replace("$HOME", "~")
    if text == "~":
        return dest_root()
    if text.startswith("~/"):
        return dest_root() / text[2:]
    return Path(text)


def confine(dest: str | Path) -> Path:
    """Expand ``dest`` and prove it stays inside the destination root.

    Symlinks are followed before the check, including symlinked *directories*,
    which is what catches the F7 case: ``~/.config/ghostty`` looks like it is
    inside the home directory and resolves into a rice repository that is not
    gtheme's to edit.

    Returns:
        The expanded (unresolved) path, so callers write through the symlink
        they asked for once they are entitled to.

    Raises:
        ConfinementError: the resolved path is outside the root.
    """
    expanded = expand(dest)
    root = dest_root().resolve()
    resolved = expanded.resolve()
    if not resolved.is_relative_to(root):
        raise ConfinementError(f"{expanded} resolves to {resolved}, outside {root}")
    return expanded


def atomic_write_bytes(path: Path, payload: bytes, *, mode: int | None = None) -> None:
    """Replace ``path`` with ``payload`` in one step, or not at all.

    The temp file is created in the destination's own directory so the final
    ``os.replace`` cannot cross a filesystem boundary — and so a refused
    destination never gets a stray ``.gtheme-*.tmp`` left behind in it.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".gtheme-", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def atomic_write_text(path: Path, text: str, *, mode: int | None = None) -> None:
    """:func:`atomic_write_bytes` for UTF-8 text."""
    atomic_write_bytes(path, text.encode("utf-8"), mode=mode)
