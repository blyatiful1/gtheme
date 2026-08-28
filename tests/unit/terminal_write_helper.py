"""Land one adapter's plan, the way the engine lands it.

The adapters no longer write anything themselves: they work out what they want
written and hand it back, and :func:`gtheme.terminal.apply_all` puts all of it
through one transaction so the change is recorded, claimed and undoable
(review-report H8). That is the right shape and it is a poor fit for the
per-adapter tests, which are about **what** each program's settings should end
up saying — the comment that survives, the import list that does not grow, the
gradient stop that does not linger — and not about the engine.

So this is the smallest possible stand-in for the engine: it writes exactly the
bytes the adapter asked for, to exactly the destinations it named, and sets
exactly the settings it named. Every one of those per-adapter assertions
therefore still asserts what it always did, unchanged.

What it deliberately does *not* do is snapshot, claim, lock or roll back —
because it is not the engine, and pretending otherwise here would let the real
thing rot. That the real path does all of those is proven separately, against a
real :class:`~gtheme.core.transaction.Transaction`, in
``tests/regression/test_terminal_transaction.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gtheme.terminal.fsio import atomic_write_bytes
from gtheme.terminal.model import Palette, TerminalWrites

__all__ = ["land"]


def land(adapter: Any, palette: Palette, backend: Any = None) -> TerminalWrites:
    """Ask ``adapter`` what it wants changed, then change it.

    Args:
        adapter: the adapter under test.
        backend: where its settings go, for the settings-driven adapters.

    Returns:
        The plan, for a test that wants to look at it as well.
    """
    writes = adapter.plan(palette)
    for change in writes.files:
        atomic_write_bytes(Path(change.dest), change.payload)
    for change in writes.settings:
        if backend is None:  # pragma: no cover - a test that forgot the seam
            raise AssertionError(f"{adapter.id} planned a setting and no backend was given")
        backend.set(change.key, change.value)
    for run in writes.runs:
        run()
    return writes
