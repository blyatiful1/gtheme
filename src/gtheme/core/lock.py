"""One gtheme at a time (the L1 defect).

Two concurrent applies interleave their read-modify-write cycles over the
ownership ledger and the baseline index, and two ``Baseline`` objects that
loaded the same blob counter will each write a snapshot to ``0007`` — the
second one silently destroying the only pre-gtheme copy of the first one's
file. There is no clever fix for that; there is a lock.

The lock is non-blocking on purpose. Queueing behind another run means the
window hangs with no explanation, and the honest answer takes one sentence:
something else is already changing your desktop, wait for it.
"""

from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .paths import lock_file

__all__ = ["LockBusy", "process_lock"]


class LockBusy(RuntimeError):
    """Another gtheme process holds the lock."""


@contextmanager
def process_lock(path: str | Path | None = None) -> Iterator[Path]:
    """Hold the exclusive gtheme lock for the duration of the block.

    Args:
        path: override the lock file. Defaults to the one in the v2 state
            directory, which ``GTHEME_STATE_DIR`` already reroots under test.

    Yields:
        The lock file's path.

    Raises:
        LockBusy: another process is applying or restoring right now.
    """
    target = Path(path) if path is not None else lock_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(fd)
        raise LockBusy(
            "something else is already changing your desktop — wait for it to finish"
        ) from exc
    try:
        yield target
    finally:
        # Closing the descriptor releases the lock; doing it explicitly means
        # the release happens here rather than whenever the object is collected.
        os.close(fd)
