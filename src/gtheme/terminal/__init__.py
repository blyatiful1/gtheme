"""Terminal and shell looks — one adapter per program gtheme can restyle.

The Terminal page shows a card per program that is actually installed, and
nothing at all for the ones that are not: a list of ten terminals with nine of
them greyed out is a list of things the user cannot do. :func:`installed` is
what the page asks.

Every adapter satisfies :class:`~gtheme.terminal.model.TerminalAdapter`, works
out its writes without making them, and carries its own honest answer to "when
will I see this?".

**Where the writing happens, and why it moved.** It used to happen inside each
adapter, which meant the one part of the app that rewrites a person's *own*
settings files — ``alacritty.toml``, ``starship.toml``, ``btop.conf``, the
Ptyxis profile — was the one part that recorded nothing: no pristine copy, no
ownership claim, no saved moment, not even the process lock a Look takes
(review-report H8). ``gtheme rescue`` restored a list these destinations were
never on. So :func:`apply_all` collects what every chosen adapter wants and
lands all of it through **one** :class:`~gtheme.core.transaction.Transaction`,
which is where snapshotting, the ledger, the restore point and the lock already
live. Nothing here is a second engine; it is the same one, finally used.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from gtheme.core import applog
from gtheme.core.baseline import Baseline, BaselineError
from gtheme.core.confine import ConfinementError
from gtheme.core.lock import LockBusy, process_lock
from gtheme.core.settings_backend import SettingsBackend
from gtheme.core.transaction import (
    FileWrite,
    Op,
    Progress,
    SettingWrite,
    Transaction,
    TransactionError,
)

from .alacritty import AlacrittyAdapter
from .console import ConsoleAdapter
from .ghostty import GhosttyAdapter
from .gnometerminal import GnomeTerminalAdapter
from .model import (
    FileChange,
    Palette,
    ReloadSemantics,
    SettingChange,
    TerminalAdapter,
    TerminalState,
    TerminalWrites,
)
from .monitors import BtopAdapter, CavaAdapter, FastfetchAdapter
from .prompt import FishAdapter, StarshipAdapter
from .ptyxis import PtyxisAdapter

__all__ = [
    "COPY",
    "AlacrittyAdapter",
    "ApplyReport",
    "BtopAdapter",
    "CavaAdapter",
    "ConsoleAdapter",
    "FastfetchAdapter",
    "FileChange",
    "FishAdapter",
    "GhosttyAdapter",
    "GnomeTerminalAdapter",
    "Palette",
    "PtyxisAdapter",
    "ReloadSemantics",
    "SettingChange",
    "StarshipAdapter",
    "TerminalAdapter",
    "TerminalState",
    "TerminalWrites",
    "adapters",
    "apply_all",
    "installed",
]

#: What this module says to a person. Every sentence is about their computer.
COPY: dict[str, str] = {
    #: What the saved moment this takes is called in the Undo list.
    "moment": "Before the terminal colours",
    #: The whole batch failed and the engine put everything back.
    "rolled-back": "Nothing was changed.",
    #: The whole batch failed and the engine could not put everything back.
    "half-done": "Some of it may have been changed anyway.",
    #: Something nobody predicted. The details go to the log, not to the person.
    "unexpected": "gtheme could not change this one, so it left it as it was.",
    #: Another change was already running.
    "busy": (
        "Something else is changing your desktop right now, so this was left alone. "
        "Try again in a moment."
    ),
    #: The program's own store could not be written down first.
    "unrecorded": (
        "gtheme could not write down how this was beforehand, so it left it alone "
        "rather than change something it could not put back."
    ),
}


def adapters(backend: SettingsBackend | None = None) -> list[TerminalAdapter]:
    """Every adapter, in the order the page shows them.

    Args:
        backend: the settings seam. Ptyxis, GNOME Terminal and Console are
            settings-driven and are left out entirely when no backend is given,
            rather than being handed one they invented — an adapter that
            reaches the real store on its own is how a test ends up editing the
            desktop.
    """
    found: list[TerminalAdapter] = [GhosttyAdapter()]
    if backend is not None:
        found.extend(
            [PtyxisAdapter(backend), GnomeTerminalAdapter(backend), ConsoleAdapter(backend)]
        )
    found.append(AlacrittyAdapter())
    found.extend(
        [
            FishAdapter(),
            StarshipAdapter(),
            BtopAdapter(),
            CavaAdapter(),
            FastfetchAdapter(),
        ]
    )
    return found


def installed(
    backend: SettingsBackend | None = None,
) -> list[tuple[TerminalAdapter, TerminalState]]:
    """The adapters whose program is present, each with what it found.

    Returns the state alongside the adapter because every caller needs it and
    :meth:`~gtheme.terminal.model.TerminalAdapter.detect` is not cheap: it walks
    ``PATH`` looking for the program and then parses that program's config file
    to work out which look it is wearing. Opening the page ran it two or three
    times per adapter — once to decide the program was installed, once for the
    card, once more for the notice on the card — synchronously, between the
    click on the sidebar and the page appearing (review-report L17). Once is
    enough, and the answer travels with the adapter that gave it.
    """
    found = []
    for adapter in adapters(backend):
        state = adapter.detect()
        if state.installed:
            found.append((adapter, state))
    return found


@dataclass(frozen=True)
class ApplyReport:
    """What one :func:`apply_all` did, per program and as a whole.

    Attributes:
        problems: every chosen adapter's id, mapped to None when its part
            worked or to the sentence to show the user when it did not.
        restore_point: the moment taken before the change, when one was.
        warnings: what that moment could only save in part. The page carries
            them out to the person rather than dropping them.
    """

    problems: dict[str, str | None] = field(default_factory=dict)
    restore_point: str | None = None
    warnings: tuple[str, ...] = ()

    @property
    def changed(self) -> list[str]:
        """The ids that were changed."""
        return [name for name, problem in self.problems.items() if problem is None]

    @property
    def failed(self) -> list[str]:
        """The ids that were not."""
        return [name for name, problem in self.problems.items() if problem is not None]


def apply_all(
    palette: Palette,
    chosen: Sequence[TerminalAdapter],
    *,
    backend: SettingsBackend | None = None,
    dest_root: str | None = None,
    narrate: Callable[[str], None] | None = None,
) -> ApplyReport:
    """Apply one look to several programs, reporting each one separately.

    Three phases, and the order is the point.

    **Work out.** Every adapter is asked what it wants written, and nothing is
    written. A program refusing — ghostty's config directory belonging to
    another tool is the case that actually happens, fastfetch having no config
    to recolour is the next — is found here, before the first byte, and takes
    only itself out of the batch. Each adapter is wrapped on its own: an
    adapter that raises something nobody predicted must not stop the rest, and
    must not be reported as success (review-report H12).

    **Land it.** Everything the adapters asked for goes through one
    transaction, which records what was there before, claims it as the user's
    own doing, takes a saved moment, holds the process lock, and puts it all
    back if any part of it fails. If it does fail, every program that was in
    the batch says so — a half-applied terminal look reported as success is
    what this whole shape exists to prevent.

    **Run the rest.** fish's colours live in fish's own store and are set by
    running fish. That happens last, under the same lock, with what fish is
    about to overwrite recorded first.

    Args:
        palette: the look to hand out.
        chosen: the adapters the user left switched on.
        backend: the settings seam. Passed to the transaction so a test never
            reaches the real settings store.
        dest_root: the root every file write must stay inside. Defaults to the
            user's home, which ``GTHEME_DEST_ROOT`` reroots under test.
        narrate: called with a sentence as the change proceeds, for the
            progress dialog.
    """
    log = applog.logger(__name__)
    problems: dict[str, str | None] = {}
    plans: list[tuple[TerminalAdapter, TerminalWrites]] = []

    for adapter in chosen:
        try:
            plans.append((adapter, adapter.plan(palette)))
        except Exception as exc:  # noqa: BLE001 - isolation is the whole point
            problems[adapter.id] = _refusal(exc, log, adapter.id)

    ops: list[Op] = []
    owners: list[tuple[str, Op]] = []
    staging = Path(tempfile.mkdtemp(prefix="gtheme-terminal-"))
    try:
        for adapter, writes in plans:
            for change in writes.files:
                ops.append(_file_op(change, staging, len(ops)))
                owners.append((adapter.id, ops[-1]))
            for change in writes.settings:
                ops.append(SettingWrite(key=change.key, value=change.value, component="terminal"))
                owners.append((adapter.id, ops[-1]))
        landed = _land(ops, owners, plans, problems, backend, dest_root, narrate)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    if not landed.ok:
        return ApplyReport(problems=problems)

    _run_the_rest(plans, problems, backend, log)
    for adapter, _writes in plans:
        problems.setdefault(adapter.id, None)
    return ApplyReport(
        problems=problems,
        restore_point=landed.restore_point,
        warnings=landed.warnings,
    )


# ---------------------------------------------------------------------------
# the three phases
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Landed:
    """What the transaction phase did, for the phase after it."""

    ok: bool
    restore_point: str | None = None
    warnings: tuple[str, ...] = ()


def _file_op(change: FileChange, staging: Path, index: int) -> FileWrite:
    """One file, staged where the transaction can read it.

    A :class:`~gtheme.core.transaction.FileWrite` copies a file rather than
    carrying bytes, so the bytes an adapter worked out are put in a throwaway
    file first. Written with the process's own umask and handed over with no
    explicit mode, so the destination ends up with exactly the permissions the
    adapters' own writer gave it before this went through the engine.
    """
    source = staging / f"{index:04d}"
    source.write_bytes(change.payload)
    return FileWrite(src=str(source), dest=change.dest)


def _land(
    ops: list[Op],
    owners: list[tuple[str, Op]],
    plans: list[tuple[TerminalAdapter, TerminalWrites]],
    problems: dict[str, str | None],
    backend: SettingsBackend | None,
    dest_root: str | None,
    narrate: Callable[[str], None] | None,
) -> _Landed:
    """Write every file and setting, or none of them."""
    if not ops:
        return _Landed(ok=True)

    transaction = Transaction(ops, dest_root=dest_root, label=COPY["moment"])
    if backend is not None:
        # The documented per-instance seam. Without it a test would write the
        # Ptyxis profile of the desktop it is running on.
        transaction.backend = backend  # type: ignore[attr-defined]

    def report(_stage: Progress, text: str) -> None:
        if narrate is not None and text:
            narrate(text)

    try:
        result = transaction.apply(report)
    except TransactionError as exc:
        state = COPY["rolled-back"] if exc.rolled_back else COPY["half-done"]
        _blame_everyone(plans, problems, f"{exc} {state}")
        return _Landed(ok=False)
    except OSError as exc:
        # Not every way an apply can fail is a TransactionError: the lock file
        # and the state directory are touched before the transaction's own
        # guarded section. No state claim is made here, because this branch has
        # no way to know what landed (review-report M3).
        _blame_everyone(plans, problems, str(exc))
        return _Landed(ok=False)

    for op, reason in result.skipped:
        owner = next((name for name, candidate in owners if candidate is op), None)
        if owner is not None:
            problems[owner] = reason
    return _Landed(
        ok=True,
        restore_point=result.restore_point,
        warnings=tuple(result.restore_warnings),
    )


def _blame_everyone(
    plans: list[tuple[TerminalAdapter, TerminalWrites]],
    problems: dict[str, str | None],
    reason: str,
) -> None:
    """Tell every program in the batch that the batch did not happen.

    All-or-nothing is what a transaction buys, and it has to be said out loud
    on every card rather than shown as a silent absence of "Done". Every
    program that got as far as being planned is told, including the ones whose
    own part was not a file or a setting: their turn came after this one, so
    for them too nothing happened.
    """
    for adapter, _writes in plans:
        problems[adapter.id] = reason


def _run_the_rest(
    plans: list[tuple[TerminalAdapter, TerminalWrites]],
    problems: dict[str, str | None],
    backend: SettingsBackend | None,
    log: logging.Logger,
) -> None:
    """The programs whose store is neither a file nor a setting. Today: fish.

    Held under the same process lock the transaction takes, so running somebody
    else's program to change their colours still cannot interleave with a Look
    being applied on the worker thread.
    """
    outstanding = [(adapter, writes) for adapter, writes in plans if writes.runs]
    if not outstanding:
        return
    try:
        with process_lock():
            for adapter, writes in outstanding:
                if problems.get(adapter.id) is not None:
                    continue
                try:
                    _record(writes.records, backend)
                    for run in writes.runs:
                        run()
                except BaselineError as exc:
                    log.warning(
                        "terminal: could not record %s before changing it: %s", adapter.id, exc
                    )
                    problems[adapter.id] = COPY["unrecorded"]
                except Exception as exc:  # noqa: BLE001 - isolation is the whole point
                    problems[adapter.id] = _refusal(exc, log, adapter.id)
    except LockBusy:
        for adapter, _writes in outstanding:
            if problems.get(adapter.id) is None:
                problems[adapter.id] = COPY["busy"]


def _record(dests: tuple[str, ...], backend: SettingsBackend | None) -> None:
    """Save what a program is about to overwrite by itself.

    fish rewrites its own variables file when the script runs, so the file is
    recorded into the pristine baseline first — the same recording a Look makes
    before it writes a file, made by the same class, so ``gtheme rescue`` can
    put the colours back. A recording that cannot be made is a reason not to
    make the change: :class:`~gtheme.core.baseline.BaselineError` reaches the
    caller, which leaves that program alone and says so.
    """
    if not dests:
        return
    baseline = Baseline(backend=backend).load()
    for dest in dests:
        baseline.record_file(Path(dest), "terminal", COPY["moment"])


def _refusal(exc: BaseException, log: logging.Logger, adapter_id: str) -> str:
    """The sentence to show for one program's failure.

    A refusal this package writes itself — ghostty's foreign directory, an edit
    that would break a config, a look whose colours are not colours — carries a
    sentence meant for the person, and that sentence is shown. Anything else is
    a surprise: the person gets one plain line and the details go to the log,
    because "AttributeError: 'NoneType' object has no attribute 'strip'" is not
    a thing to put on a card (and printing nothing at all is what used to
    happen — the traceback went to a terminal nobody was looking at).
    """
    if isinstance(exc, PermissionError | ValueError | ConfinementError):
        text = str(exc).strip()
        if text:
            return text
    log.exception("terminal: %s could not be changed", adapter_id, exc_info=exc)
    return COPY["unexpected"]
