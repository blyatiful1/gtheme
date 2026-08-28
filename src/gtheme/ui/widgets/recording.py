"""The recorder every page write goes through.

``docs/architecture.md`` says the transaction is "the only path by which
anything changes". Until this module existed that sentence was false for the
part of the app people use most: every row on More Settings, Top bar, Windows,
Night light, Sound, Power and every add-on panel wrote straight to the settings
store. Nothing was written down, so (a) Undo could not reach the change, (b)
``gtheme rescue`` could not either, and (c) worst of all, a Look that later
touched the same setting recorded the *already-edited* value as the pristine
one — "what your desktop looked like before gtheme" was wrong for that setting
for good (review-report H3).

What this module does **not** do is wrap every toggle in its own
:class:`~gtheme.core.transaction.Transaction`. That was the obvious fix and it
is a trap: a transaction takes a restore point, ten saved moments is the cap,
and a person nudging six sliders would quietly evict the automatic moment taken
before the Look they applied this morning — destroying the very way back the
restore point exists to be. So page edits are *coalesced*:

* the pristine value is recorded on **first touch**, exactly as a Look records
  it, into the same :class:`~gtheme.core.baseline.Baseline`;
* the ownership ledger claims the setting for :data:`MANUAL_OWNER`, which the
  switch cleanup deliberately walks past — a later Look never reverts an edit
  the person made themselves;
* **one** saved moment covers the whole burst of edits. The first write of a
  burst takes it; every further setting touched inside the same
  :data:`BURST_WINDOW` is added to that same moment, so the moment reads
  "Before your changes" for the whole session of fiddling rather than for the
  last toggle of it.

Everything happens under the same process lock a Look takes, so a row cannot
interleave with an apply running on the worker thread. When the lock is held
the write does not happen and the caller is told why, in a sentence
(:class:`WriteRefused`) — never a traceback out of a GTK signal handler.

Nothing here is a second engine. It records what the engine records, in the
engine's own files, through the engine's own public API.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ...core import ledger as ledger_store
from ...core import restorepoints
from ...core.atomic import load_json
from ...core.baseline import Baseline, BaselineError
from ...core.ledger import MANUAL_OWNER
from ...core.lock import LockBusy, process_lock
from ...core.paths import restore_points_dir
from ...core.settings_backend import BackendError, BackendErrorKind, SettingsBackend

__all__ = [
    "BURST_WINDOW",
    "COPY",
    "NOT_CHANGED",
    "RecordingBackend",
    "WriteRefused",
    "first_touch_value",
    "forget_burst",
    "reason_for",
    "recording",
]


#: How long one run of edits counts as a single burst. Long enough that
#: changing eight things on one page is one moment to go back to; short enough
#: that coming back after lunch and changing something else is a new one.
BURST_WINDOW = timedelta(minutes=10)


#: Every sentence this module can put in front of a person.
COPY: dict[str, str] = {
    #: What the coalesced saved moment is called in the Undo list.
    "moment": "Before your changes",
    "busy": (
        "Something else is changing your desktop right now, so this was left alone. "
        "Try again in a moment."
    ),
    "unrecorded": (
        "gtheme could not write down how this was beforehand, so it left it alone "
        "rather than change something it could not put back."
    ),
    "no-add-on": "This needs an add-on that isn't installed.",
    "different-version": (
        "The add-on on this computer is a different version and doesn't have this."
    ),
    "refused": "Your desktop would not keep the change.",
    "not-accepted": "Your desktop did not accept the change.",
}

#: How a row says a change did not happen. The Terminal page's wording, so the
#: sentence a person reads is the same one wherever it comes from.
NOT_CHANGED = "Not changed. {why}"


class WriteRefused(Exception):
    """The write did not happen, and there is a sentence saying why.

    Distinct from :class:`~gtheme.core.settings_backend.BackendError`: that one
    means the settings store refused, this one means *gtheme* refused, because
    it could not first record what it was about to overwrite. Both end in the
    same place — the widget goes back to showing the truth and the person is
    told — so both are caught together.

    Attributes:
        reason: the plain sentence to show. Never an exception's own text.
    """

    def __init__(self, reason: str, *, cause: BaseException | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.cause = cause


def reason_for(exc: BaseException) -> str:
    """The plain sentence for a failure a write handler caught.

    A backend's own message names the setting and the machinery around it —
    exactly the words DESIGN.md A7 says this app never puts in front of the
    reader — so the closed set of failure kinds is translated here instead of
    being interpolated.
    """
    if isinstance(exc, WriteRefused):
        return exc.reason
    if isinstance(exc, BackendError):
        if exc.kind is BackendErrorKind.NO_SCHEMA:
            return COPY["no-add-on"]
        if exc.kind is BackendErrorKind.NO_KEY:
            return COPY["different-version"]
        if exc.kind is BackendErrorKind.COMMIT_FAILED:
            return COPY["refused"]
        return COPY["not-accepted"]
    return COPY["not-accepted"]


# --------------------------------------------------------------------------
# the burst
# --------------------------------------------------------------------------


@dataclass
class _Burst:
    """One run of page edits, and the saved moment that covers all of it."""

    started: datetime
    #: Where the moment was taken. A burst belongs to the folder it was written
    #: in: if that moves under the process, the moment it names is not there and
    #: extending it would write a second, half-empty one.
    root: Path
    point_id: str | None = None
    #: Setting key to the value it held *before* this burst touched it. None
    #: where it held no value at all, which restores as "unset it again".
    before: dict[str, str | None] = field(default_factory=dict)


_burst: _Burst | None = None
_burst_guard = threading.Lock()


def forget_burst() -> None:
    """Start the next write as a fresh burst. The test seam, and nothing else."""
    global _burst
    with _burst_guard:
        _burst = None


def _now() -> datetime:
    return datetime.now(UTC)


class _Remembered(SettingsBackend):
    """Reads back the values a burst remembers, and nothing else.

    :func:`~gtheme.core.restorepoints.capture` reads every key it is asked to
    save through a backend. The burst's moment has to hold each setting as it
    was *before the burst touched it*, not as it is now — so the reader handed
    to the capture is this one, which answers from what was read at first touch.
    A moment rebuilt this way is identical to one taken in full at the instant
    the burst began, without having to guess in advance which settings the
    person is about to change.
    """

    def __init__(self, values: dict[str, str | None]) -> None:
        super().__init__(None)
        self._values = values

    def get(self, key: str) -> str:
        if key not in self._values:  # pragma: no cover - defensive
            raise BackendError(BackendErrorKind.NO_KEY, f"{key} is not in this moment", key=key)
        value = self._values[key]
        if value is None:
            # "There was nothing here" is a state, and the capture records it
            # as one: restoring the moment unsets the key again.
            raise BackendError(BackendErrorKind.UNSET, f"{key} had no value", key=key)
        return value

    def set(self, key: str, value: str) -> None:  # pragma: no cover - never written through
        raise BackendError(BackendErrorKind.OTHER, "a saved moment is not written through")

    def reset(self, key: str) -> None:  # pragma: no cover - never written through
        raise BackendError(BackendErrorKind.OTHER, "a saved moment is not written through")


def _current_burst(now: datetime) -> _Burst:
    """The burst this write belongs to, starting one if the last has aged out."""
    global _burst
    root = restore_points_dir()
    if _burst is None or now - _burst.started > BURST_WINDOW or _burst.root != root:
        _burst = _Burst(started=now, root=root)
    return _burst


def _cover(burst: _Burst, key: str, before: str | None) -> None:
    """Add one setting to the burst's saved moment, taking it if it is the first.

    Re-capturing with the burst's own id rewrites the same moment in place, so
    a burst is one entry in the Undo list however many things it touches.
    """
    burst.before[key] = before
    reader = _Remembered(burst.before)
    keys = list(burst.before)
    try:
        if burst.point_id is None:
            point = restorepoints.capture(
                keys,
                label=COPY["moment"],
                kind="auto",
                backend=reader,
                when=burst.started,
            )
            burst.point_id = point.id
            # The cap is what keeps the Undo list readable. Pruning here rather
            # than on every write is the whole point of coalescing: one moment
            # per burst evicts at most one older moment per burst.
            restorepoints.prune()
        else:
            restorepoints.capture(
                keys,
                label=COPY["moment"],
                kind="auto",
                backend=reader,
                when=burst.started,
                point_id=burst.point_id,
            )
    except OSError as exc:
        burst.before.pop(key, None)
        raise WriteRefused(COPY["unrecorded"], cause=exc) from exc


def _claim(key: str) -> None:
    """Tell the ownership ledger this setting is the person's own doing.

    Written *before* the change it describes (the R4 rule), and under
    :data:`~gtheme.core.ledger.MANUAL_OWNER`, which
    :func:`~gtheme.core.ledger.switch_cleanup` skips: applying a Look later
    must never quietly revert the highlight colour somebody chose by hand.
    """
    ledger = ledger_store.read_ledger()
    owned = ledger.get(MANUAL_OWNER)
    owned = owned if isinstance(owned, dict) else {}
    settings = [str(item) for item in owned.get("settings", []) if isinstance(item, str)]
    files = [str(item) for item in owned.get("files", []) if isinstance(item, str)]
    if key in settings:
        return
    try:
        ledger_store.write_entry(MANUAL_OWNER, files, [*settings, key])
    except OSError as exc:
        raise WriteRefused(COPY["unrecorded"], cause=exc) from exc


def _record(backend: SettingsBackend, key: str, component: str) -> None:
    """Everything that must be true before one setting is overwritten."""
    now = _now()
    with _burst_guard:
        burst = _current_burst(now)
        if key in burst.before:
            return
        baseline = Baseline(backend=backend).load()
        try:
            before = baseline.read_setting(key)
        except BackendError as exc:
            # The value is unknown, not absent. Recording "there was nothing
            # here" would make putting it back *clear* a setting nobody read.
            raise WriteRefused(COPY["unrecorded"], cause=exc) from exc
        try:
            baseline.record_setting(key, component, "")
        except (BaselineError, OSError) as exc:
            raise WriteRefused(COPY["unrecorded"], cause=exc) from exc
        _cover(burst, key, before)
        _claim(key)


def first_touch_value(backend: SettingsBackend, key: str) -> tuple[bool, str | None]:
    """What this setting held the first time gtheme ever touched it.

    Returns ``(recorded, value)``. ``recorded`` is False when the pristine
    recording has never heard of this setting, which is the honest difference
    between "put this back the way it was" and "put this back to what the
    computer came with" — the per-row reset button says whichever is true.
    ``value`` is None where the setting had no value at all, which is put back
    by unsetting it rather than by inventing one.

    Reads the settings index directly rather than through
    :meth:`~gtheme.core.baseline.Baseline.load`: this is asked once per reset
    button per refresh — forty times when a page re-reads itself — and ``load``
    also reads the file index and globs the stored copies, which none of this
    needs.
    """
    records, _warning = load_json(Baseline(backend=backend).settings_index, {})
    record = records.get(key) if isinstance(records, dict) else None
    if not isinstance(record, dict):
        return False, None
    saved = record.get("saved")
    return True, saved if isinstance(saved, str) else None


class RecordingBackend(SettingsBackend):
    """A settings backend that writes nothing down without writing it down.

    Wraps the real backend. Reads pass straight through; every write and every
    reset first records the pristine value, claims the setting for the person
    rather than for a Look, and makes sure the burst's saved moment covers it.

    Args:
        inner: the backend that actually holds the values.
        component: what to file the pristine recording under. A descriptor's
            id, where there is one; metadata only, and never shown.
    """

    def __init__(self, inner: SettingsBackend, *, component: str = "") -> None:
        super().__init__(inner.schema_source)
        self.inner = inner
        self.component = component

    def get(self, key: str) -> str:
        return self.inner.get(key)

    def set(self, key: str, value: str) -> None:
        self._recorded(key, lambda: self.inner.set(key, value))

    def reset(self, key: str) -> None:
        self._recorded(key, lambda: self.inner.reset(key))

    def can_write(self) -> bool:
        """Defer to the wrapped backend's own answer, when it has one."""
        ask = getattr(self.inner, "can_write", None)
        return bool(ask()) if callable(ask) else True

    def _recorded(self, key: str, write: Any) -> None:
        """Record, then write, with the lock held for both.

        The lock is the same one a Look takes, and it is why this is safe: an
        apply running on the worker thread and a switch being flipped on the
        main one cannot interleave their read-modify-write cycles over the
        ledger and the baseline index. Held for the recording *and* the write,
        so no apply can start between them.
        """
        holding = False
        try:
            with process_lock():
                holding = True
                _record(self.inner, key, self.component)
                write()
        except LockBusy as exc:
            raise WriteRefused(COPY["busy"], cause=exc) from exc
        except OSError as exc:
            if holding:
                # Came out of the write itself, not out of the recording. The
                # backends turn their own I/O failures into a typed
                # BackendError, so this is genuinely unexpected and is not
                # dressed up as a recording problem.
                raise
            # The lock file itself could not be made: a full or read-only state
            # directory. Writing anyway would change the desktop with nothing
            # recording it, which is the whole defect this module closes.
            raise WriteRefused(COPY["unrecorded"], cause=exc) from exc


def recording(backend: SettingsBackend, *, component: str = "") -> RecordingBackend:
    """The recording view of a backend. Wrapping a recorder returns it unchanged.

    Idempotent on purpose: a page may hand its rows a recording backend and the
    row library wraps whatever it is given, and recording the same write twice
    would claim it twice and take two moments for one burst.
    """
    if isinstance(backend, RecordingBackend):
        return backend
    return RecordingBackend(backend, component=component)
