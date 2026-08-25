"""Where gtheme v2 keeps its own state, and what it is allowed to read.

Everything here is a *function*, never a module constant. v1 resolved
``DEST_ROOT`` once at import time, which meant a test had to
``importlib.reload(paths)`` to point it anywhere else — and a test that forgets
to reload writes to the real home. Reading the environment on every call costs
nothing and removes that whole class of accident.

Three roots matter.

**The destination root** (``GTHEME_DEST_ROOT``, default ``$HOME``) is what a
Look's ``~/...`` destinations expand against, and the boundary
:mod:`gtheme.core.confine` enforces.

**The v2 state root** (``GTHEME_STATE_DIR``, default
``~/.local/state/gtheme/v2``) holds the pristine baseline, the ownership ledger
and the restore points. The ``v2`` suffix is not decoration: v1 wrote directly
into ``~/.local/state/gtheme`` and those files are still there on this machine.
DESIGN.md F1 is explicit that v2 never writes into or deletes them.

**The v1 backup** (``~/.local/state/gtheme.v1-backup``, overridable with
``GTHEME_V1_BACKUP_DIR``) is read-only, always, everywhere. It is the copy F1
took before the raze, and it is the only surviving record of what this desktop
looked like before gtheme v1 first touched it. :mod:`gtheme.core.restorepoints`
reads it to build the "Before gtheme" restore point the Home page promises.
Nothing in gtheme may write to it.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "V1_BACKUP_DIRNAME",
    "baseline_dir",
    "dest_root",
    "ledger_file",
    "lock_file",
    "restore_points_dir",
    "state_dir",
    "v1_backup_dir",
    "xdg_data_home",
    "xdg_state_home",
]

#: The directory F1's pre-raze copy lives in, beside the v1 state directory.
V1_BACKUP_DIRNAME = "gtheme.v1-backup"


def _env_path(var: str) -> Path | None:
    value = os.environ.get(var)
    return Path(value).expanduser() if value else None


def xdg_data_home() -> Path:
    return _env_path("XDG_DATA_HOME") or (Path.home() / ".local" / "share")


def xdg_state_home() -> Path:
    return _env_path("XDG_STATE_HOME") or (Path.home() / ".local" / "state")


def dest_root() -> Path:
    """The root a Look's ``~/...`` destinations expand against.

    ``GTHEME_DEST_ROOT`` overrides it. That override is the seam the whole test
    suite rests on, and the ``mutating`` guard in ``tests/conftest.py`` accepts
    it as proof a test cannot reach the real desktop.
    """
    return _env_path("GTHEME_DEST_ROOT") or Path.home()


def state_dir() -> Path:
    """The v2 state root. ``GTHEME_STATE_DIR`` overrides it.

    Note the ``v2``: v1's files sit in the parent directory and are never
    touched (DESIGN.md F1).
    """
    override = _env_path("GTHEME_STATE_DIR")
    if override is not None:
        return override
    return xdg_state_home() / "gtheme" / "v2"


def baseline_dir() -> Path:
    """Where the pristine first-touch snapshots live."""
    return state_dir() / "baseline"


def ledger_file() -> Path:
    """The ownership ledger: which Look owns which file and which setting."""
    return state_dir() / "ownership.json"


def lock_file() -> Path:
    """The flock file that keeps two gthemes from mutating at once."""
    return state_dir() / "lock"


def restore_points_dir() -> Path:
    """Where captured restore points are stored, newest last by name."""
    return state_dir() / "restore-points"


def v1_backup_dir() -> Path:
    """The read-only v1 backup copy. May not exist; that is not an error."""
    override = _env_path("GTHEME_V1_BACKUP_DIR")
    if override is not None:
        return override
    return xdg_state_home() / V1_BACKUP_DIRNAME
