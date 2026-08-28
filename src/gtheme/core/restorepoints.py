"""Restore points: "put it back the way it was on Tuesday".

This is the feature no other GNOME customisation tool has, and it is the reason
someone who has never used Linux can safely press buttons in this app. Every
transaction takes one first, automatically, and the user can take one by hand
whenever they like.

A restore point is a recording of *exact current values* — the same GVariant
text the settings backend produces — plus a copy of every file gtheme is about
to overwrite. Applying one is not a special operation: it becomes a
:class:`~gtheme.core.transaction.Transaction` of ordinary
:class:`~gtheme.core.transaction.SettingWrite` and
:class:`~gtheme.core.transaction.FileWrite` operations and goes down the same
code path as applying a Look. One apply path, no second engine to keep correct.

The oldest ones are pruned to a cap, because an unbounded list is a list nobody
reads, and because the file copies are real bytes on a real disk.

**The "Before gtheme" point.** DESIGN.md F1: before the v2 rebuild razed the
tree, v1's state directory was copied to ``~/.local/state/gtheme.v1-backup``.
That copy holds v1's own pristine baseline — the only surviving record of what
this desktop looked like before gtheme *ever* ran. :func:`import_v1_baseline`
reads it, read-only, and materialises it as the "Before gtheme" restore point
the Home page promises. The v1 store is a source. It is never written and never
deleted, and its absence is normal rather than an error: a fresh install has no
v1 to import.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from .atomic import atomic_write_json, load_json
from .backends import get_backend, is_missing
from .confine import safe_name
from .paths import restore_points_dir, v1_backup_dir
from .settings_backend import BackendError, BackendErrorKind, SettingsBackend

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .transaction import Diff, Transaction

__all__ = [
    "DEFAULT_CAP",
    "PRISTINE_ID",
    "RestorePoint",
    "RestoreResult",
    "apply_point",
    "capture",
    "capture_from_diff",
    "delete",
    "import_v1_baseline",
    "list_restore_points",
    "load",
    "prune",
]

#: How many automatic restore points to keep. The pristine one is never pruned.
DEFAULT_CAP = 10

#: The id of the "Before gtheme" point. Fixed, so importing twice replaces it
#: rather than accumulating copies of the same moment.
PRISTINE_ID = "before-gtheme"

_DOCUMENT = "restore-point.json"
_FILES_DIRNAME = "files"


@dataclass
class RestorePoint:
    """One saved moment.

    Attributes:
        id: folder name, and the handle every other function takes. Sortable:
            automatic points are named after the moment they were taken.
        label: what to call it in the list — "NIGHTBLOOM", "Before gtheme".
        created: when it was taken, in UTC.
        kind: ``"auto"`` (taken before a change), ``"manual"`` (the user asked)
            or ``"pristine"`` (the imported before-gtheme state).
        settings: key to the exact value at the time, or None where the key had
            no value at all — which restores as "unset it again", not as some
            invented default.
        files: destination to the name of its saved copy; ``None`` where the
            file did not exist and restoring means deleting it again; or
            ``{"link": "<target>"}`` where the destination was a shortcut and
            restoring means putting that shortcut back rather than deleting
            somebody's own link into their dotfiles.
        warnings: what could not be recorded, in plain words. Never silent.
        path: where this lives on disk.
    """

    id: str
    label: str
    created: datetime
    kind: str = "auto"
    settings: dict[str, str | None] = field(default_factory=dict)
    files: dict[str, str | dict | None] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    path: Path | None = None

    @property
    def is_empty(self) -> bool:
        return not self.settings and not self.files

    @property
    def keys_to_unset(self) -> list[str]:
        """Settings that had no value at all when this moment was saved.

        Restoring one means *unsetting* it, which is a
        :class:`~gtheme.core.transaction.SettingReset` — so these travel
        through the same transaction as everything else and get the same
        preflight, restore point and rollback.

        This is not a corner case. The "Before gtheme" point imported from v1
        on this machine has 46 settings, and 33 of them are these: keys that
        belong to add-ons the user had never configured before a Look
        configured them.
        """
        return sorted(key for key, value in self.settings.items() if value is None)

    @property
    def files_to_remove(self) -> list[str]:
        """Files that did not exist when this moment was saved.

        Restoring means deleting whatever was put there — a
        :class:`~gtheme.core.transaction.FileRemove`, and the other half of the
        same story as :attr:`keys_to_unset`.
        """
        return sorted(dest for dest, blob in self.files.items() if blob is None)

    def human_date(self) -> str:
        """"25 August 2026" — the way the Undo page lists it."""
        return self.created.astimezone().strftime("%-d %B %Y, %H:%M")

    def to_transaction(self) -> Transaction:
        """Turn this moment back into the changes that would restore it.

        Applying a restore point is applying a transaction. Everything the
        engine guarantees for a Look — the confinement preflight, the pristine
        baseline, the all-or-nothing rollback — is therefore true of an undo as
        well, without a second implementation to keep in step.

        Absence is expressed too, and that is the whole point of this being one
        transaction. Two thirds of a pristine restore point is things that were
        NOT there: settings with no value, and files that did not exist. Those
        become :class:`~gtheme.core.transaction.SettingReset` and
        :class:`~gtheme.core.transaction.FileRemove` ops, so undoing them is
        covered by the confinement preflight, the pristine recording and the
        all-or-nothing rollback exactly like everything else.
        """
        from .transaction import (
            FileLink,
            FileRemove,
            FileWrite,
            SettingReset,
            SettingWrite,
            Transaction,
        )

        ops: list[FileWrite | FileRemove | FileLink | SettingWrite | SettingReset] = []
        base = (self.path or Path()) / _FILES_DIRNAME
        for dest, blob in sorted(self.files.items()):
            if isinstance(blob, dict):
                # A shortcut was here. Put the shortcut back, do not write
                # through it and do not delete it.
                ops.append(FileLink(dest=dest, target=str(blob.get("link") or "")))
            elif blob is None:
                ops.append(FileRemove(dest=dest))
            else:
                ops.append(FileWrite(src=str(base / blob), dest=dest))
        for key, value in sorted(self.settings.items()):
            if value is None:
                ops.append(SettingReset(key=key))
            else:
                ops.append(SettingWrite(key=key, value=value))
        # No ``look``: putting a saved moment back is not applying a Look. It
        # must not run the Look-switch cleanup, must not claim the ledger under
        # this moment's label, and must not record a current Look. The label is
        # deliberately dropped too, so the automatic moment taken before the
        # restore reads "Before your last change" instead of being a second
        # entry with the same name as the one being restored.
        return Transaction(ops)


def _now() -> datetime:
    return datetime.now(UTC)


def _claimed_settings() -> list[str]:
    """Every setting key the ownership ledger currently claims, in one list.

    A hand-saved moment is built from the descriptor corpus, which is derived
    from GNOME's own schemas and contains no third-party extension keys at all
    — while a Look may write any key it likes, and the four shipped ones write
    between 15 and 24 keys each that the corpus has never heard of (dash-to-dock
    indicators, blur-my-shell's per-application blur, tiling-shell borders,
    burn-my-windows' active profile). Saving "how my desktop looks now" without
    them recorded a moment that could not put those back (review-report M14).

    The ledger is the honest answer to "what has gtheme changed that a saved
    moment would otherwise miss?": it is written before every change, it is
    keyed by owner rather than by corpus membership, and the user's own page
    edits are in it too under ``MANUAL_OWNER``. Read through the ledger
    module's own API, never by parsing its file here.
    """
    from .ledger import read_ledger

    claimed: list[str] = []
    for owned in read_ledger().values():
        if not isinstance(owned, dict):
            continue
        claimed.extend(key for key in owned.get("settings", []) if isinstance(key, str))
    return claimed


def _new_id(when: datetime, base_dir: Path | None = None) -> str:
    """A folder name for a moment, and never one that is already taken.

    The timestamp alone is not enough, and that was a real bug rather than a
    theoretical one: it is written to the second, so two moments saved inside
    one second landed in the same folder and the second silently overwrote the
    first. That is where the stray ``.bak`` files beside the junk moments came
    from — a half-written moment on top of a whole one.

    The readable timestamp stays the base name, because people do look at these
    folders. Uniqueness comes from *claiming* the directory rather than from
    guessing an unused name: one ``mkdir`` that refuses to succeed twice, which
    makes this safe between two gtheme windows as well as between two clicks.
    """
    base = when.strftime("%Y-%m-%dT%H-%M-%S")
    if base_dir is None:
        return base
    for attempt in range(1, 1000):
        candidate = base if attempt == 1 else f"{base}-{attempt}"
        try:
            (base_dir / candidate).mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            continue
        return candidate
    # A thousand moments in one second is not a situation to have an opinion
    # about; it is one to stay correct through.
    return f"{base}-{uuid4().hex[:8]}"


def _root(root: str | Path | None = None) -> Path:
    return Path(root) if root is not None else restore_points_dir()


def _write(point: RestorePoint) -> RestorePoint:
    assert point.path is not None
    point.path.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        point.path / _DOCUMENT,
        {
            "id": point.id,
            "label": point.label,
            "created": point.created.isoformat(),
            "kind": point.kind,
            "settings": point.settings,
            "files": point.files,
            "warnings": point.warnings,
        },
    )
    return point


def _read(directory: Path) -> RestorePoint | None:
    data, _warning = load_json(directory / _DOCUMENT, None)
    if not isinstance(data, dict):
        return None
    try:
        created = datetime.fromisoformat(str(data.get("created")))
    except ValueError:
        created = datetime.fromtimestamp(directory.stat().st_mtime, UTC)
    settings = data.get("settings")
    files = data.get("files")
    return RestorePoint(
        id=str(data.get("id") or directory.name),
        label=str(data.get("label") or directory.name),
        created=created,
        kind=str(data.get("kind") or "auto"),
        settings=settings if isinstance(settings, dict) else {},
        files=files if isinstance(files, dict) else {},
        warnings=list(data.get("warnings") or []),
        path=directory,
    )


def list_restore_points(root: str | Path | None = None) -> list[RestorePoint]:
    """Every saved moment, newest first, with "Before gtheme" last.

    That order is what the Undo page shows: the thing you most likely want is
    at the top, and the nuclear option is at the bottom where it belongs.
    """
    base = _root(root)
    if not base.is_dir():
        return []
    points = [
        point
        for point in (_read(child) for child in base.iterdir() if child.is_dir())
        if point is not None
    ]
    points.sort(key=lambda point: (point.kind == "pristine", -point.created.timestamp()))
    return points


def load(point_id: str, root: str | Path | None = None) -> RestorePoint | None:
    """One saved moment by id, or None if there is no such thing."""
    directory = _root(root) / safe_name(point_id)
    return _read(directory) if directory.is_dir() else None


def delete(point_id: str, root: str | Path | None = None) -> bool:
    """Forget a saved moment, copies and all. Returns whether it was there."""
    directory = _root(root) / safe_name(point_id)
    if not directory.is_dir():
        return False
    shutil.rmtree(directory)
    return True


def capture(
    keys: list[str],
    dests: list[str] | None = None,
    *,
    label: str,
    kind: str = "auto",
    backend: SettingsBackend | None = None,
    root: str | Path | None = None,
    point_id: str | None = None,
    when: datetime | None = None,
) -> RestorePoint:
    """Record the current value of every named setting and file.

    Args:
        keys: setting keys, in the grammar frozen in ``core.settings_backend``.
        dests: files to copy. Missing ones are recorded as missing, so
            restoring deletes what was installed over them.
        label: what to call this in the list.
        kind: ``"auto"``, ``"manual"`` or ``"pristine"``.
        backend: how to read settings; defaults to the process backend.
        root: where to store it; defaults to the v2 restore-points directory.
        point_id: override the generated id. Used only by the v1 import, which
            has a fixed one.
        when: pretend it is this moment. The id is derived from it, so a test
            that needs several moments in a known order can say so instead of
            sleeping through real seconds.

    A key that cannot be read is recorded as having no value, with a warning
    naming it. That is honest and restorable: "there was nothing here" is a
    state, and restoring it means unsetting the key again.

    A ``manual`` moment covers more than it is asked for: every setting key the
    ownership ledger claims is added to ``keys``. See :func:`_claimed_settings`
    — the caller's list comes from the descriptor corpus, which knows nothing
    about the add-on keys a Look writes, and a moment that cannot put those
    back is not "how your whole desktop looked". Automatic moments are built
    from a transaction's own diff and already cover exactly what is changing,
    so they are left alone.
    """
    when = when or _now()
    reader = backend if backend is not None else get_backend()
    base_dir = _root(root)
    if kind == "manual":
        keys = [*keys, *_claimed_settings()]
    identifier = safe_name(point_id or _new_id(when, base_dir))
    point = RestorePoint(
        id=identifier,
        label=label,
        created=when,
        kind=kind,
        path=base_dir / identifier,
    )
    for key in dict.fromkeys(keys):
        try:
            point.settings[key] = reader.get(key)
        except BackendError as exc:
            if is_missing(exc) or exc.kind is BackendErrorKind.UNSET:
                # There is genuinely nothing here: no such schema, no such key,
                # or a location that has never been written. "There was nothing
                # here" is a state, and restoring it means unsetting the key
                # again. (The unset case is a *value* answer, not an
                # availability one — the same read that tells an apply "go
                # ahead, this is writable" tells a capture "record absence".)
                point.settings[key] = None
                continue
            # Anything else — the settings service was momentarily unreachable,
            # a value would not parse — means the value is UNKNOWN, not absent.
            # Recording it as absent would make restoring this moment *clear* a
            # setting that was never read, so it is left out of the moment
            # altogether and said out loud instead.
            point.warnings.append(
                f"could not save the current value of {key}: {exc}. "
                "It is not covered by this saved moment and will be left alone."
            )

    if dests:
        files_dir = point.path / _FILES_DIRNAME if point.path else None
        for index, dest in enumerate(dict.fromkeys(dests), start=1):
            source = Path(dest)
            if source.is_symlink():
                # A shortcut. It WAS here, so recording it as absent would make
                # restoring this moment delete the user's own link — somebody's
                # ~/.config/ghostty pointing into their dotfiles repository —
                # and leave a hole. The link is recorded as a link, exactly as
                # the pristine baseline records one, and restoring recreates it.
                try:
                    target = os.readlink(source)
                except OSError as exc:
                    point.files[dest] = None
                    point.warnings.append(f"could not read the shortcut at {dest}: {exc}")
                    continue
                point.files[dest] = {"link": target}
                continue
            if not source.is_file():
                # A missing file, or something exotic. Recording it as absent
                # means restoring removes whatever was put there, which is the
                # right answer for a file that was not there before.
                point.files[dest] = None
                continue
            assert files_dir is not None
            files_dir.mkdir(parents=True, exist_ok=True)
            blob = f"{index:04d}"
            try:
                shutil.copy2(source, files_dir / blob)
            except OSError as exc:
                point.files[dest] = None
                point.warnings.append(f"could not save a copy of {dest}: {exc}")
                continue
            point.files[dest] = blob

    return _write(point)


def capture_from_diff(
    diff: Diff,
    *,
    label: str,
    backend: SettingsBackend | None = None,
    root: str | Path | None = None,
    resolved_dests: dict[str, str] | None = None,
    resolved_keys: dict[str, str] | None = None,
    extra_keys: list[str] | None = None,
    extra_dests: list[str] | None = None,
) -> RestorePoint | None:
    """Take a restore point covering exactly what a transaction would change.

    Called by ``Transaction.apply`` before the first mutation. Returns None
    when the transaction would change nothing at all — a restore point that
    records no difference is clutter in a list people need to be able to read.

    Args:
        diff: what the transaction plans to do. Only real changes are covered;
            a value already at its target needs no saving.
        label: what to call this in the list.
        backend: how to read settings.
        root: where to store it.
        resolved_dests: a Look writes ``~/.config/...``; the copy has to be
            taken from the real location that expands to. The transaction has
            already worked those out, so it passes them in rather than having
            them worked out a second time and possibly differently.
        resolved_keys: the same, for setting keys. A Look writes
            ``dconf:/org/gnome/Ptyxis/Profiles/{{ ptyxis_default_profile }}/palette``
            and the transaction resolves the token before writing; saving the
            *literal* token path saves nothing, and restoring it then reset the
            real key — wiping the value the moment was supposed to protect.
        extra_keys: settings to save that the transaction will not write
            itself. Switching Looks *reverts* what the outgoing one owned and
            the incoming one does not manage — a real change to the desktop
            that the diff does not describe. Without these, "Undo" after a
            switch would put back the pristine state rather than the Look that
            was on a moment ago, which is not what anybody pressing it means.
        extra_dests: the same, for files.
    """
    from .transaction import (
        ENABLED_EXTENSIONS_KEY,
        ExtensionEnable,
        FileLink,
        FileRemove,
        FileWrite,
        SettingReset,
        SettingWrite,
    )

    mapping = resolved_dests or {}
    key_mapping = resolved_keys or {}
    keys: list[str] = []
    dests: list[str] = []
    for entry in diff.changes:
        op = entry.op
        # A reset and a removal need covering exactly like a write and a copy:
        # what is about to be cleared, or deleted, is what has to be saved
        # first. Leaving them out is what would make undoing an undo
        # impossible — and the commonest undo of all, restoring "Before
        # gtheme", is mostly resets and removals.
        if isinstance(op, SettingWrite | SettingReset):
            keys.append(key_mapping.get(op.key, op.key))
        elif isinstance(op, ExtensionEnable):
            keys.append(ENABLED_EXTENSIONS_KEY)
        elif isinstance(op, FileWrite | FileRemove | FileLink):
            dests.append(mapping.get(op.dest, op.dest))
    keys.extend(extra_keys or ())
    dests.extend(extra_dests or ())
    if not keys and not dests:
        return None
    point = capture(keys, dests, label=label, kind="auto", backend=backend, root=root)
    prune(root=root)
    return point


def prune(cap: int = DEFAULT_CAP, root: str | Path | None = None) -> list[str]:
    """Delete the oldest automatic points beyond ``cap``.

    Manual points and the "Before gtheme" point are never pruned: somebody
    asked for those, or they cannot be recreated.
    """
    automatic = [point for point in list_restore_points(root) if point.kind == "auto"]
    doomed = automatic[cap:]
    for point in doomed:
        if point.path is not None:
            shutil.rmtree(point.path, ignore_errors=True)
    return [point.id for point in doomed]


@dataclass
class RestoreResult:
    """What applying a saved moment did.

    Attributes:
        transaction: the outcome of the ordinary part — the values and files
            that could be written back. None when there was nothing to write.
        unset: settings returned to having no value.
        removed: files deleted because they were not there before.
        warnings: what could not be put back, in plain words.
        rolled_back: after a failure, whether the desktop really did come back
            to where it was before the restore started. Only meaningful
            alongside a warning from a failed restore — nothing was half-done
            when there was no failure, which is why it defaults to True. This
            is the difference between "nothing was changed" and "part of that
            moment was written and part was not", and an undo — the app's
            headline safety feature — is the last place to be vague about it
            (review-report L1).
    """

    transaction: object | None = None
    unset: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    rolled_back: bool = True


def apply_point(
    point_id: str,
    progress_cb=None,
    *,
    root: str | Path | None = None,
    backend: SettingsBackend | None = None,
    dest_root: str | Path | None = None,
) -> RestoreResult:
    """Put the desktop back to a saved moment.

    One transaction, for all of it. The values to write back, the files to copy
    back, the settings that had no value and the files that were not there all
    go through :class:`~gtheme.core.transaction.Transaction`, which means the
    confinement preflight, the pristine recording, the ownership ledger and the
    all-or-nothing rollback cover the whole restore rather than two thirds of
    it.

    (They did not always. Absence used to be carried out here, after the
    transaction, because the frozen operation set had no way to say "there
    should be nothing here" — which left the 33 unset settings and the 20
    absent files of this machine's own "Before gtheme" point outside every
    guarantee the engine makes. ``SettingReset`` and ``FileRemove`` are what
    closed that.)

    Args:
        point_id: which saved moment.
        progress_cb: passed through to the transaction.
        root: where restore points live.
        backend: how to read and write settings.
        dest_root: destination root for the file writes.

    Returns:
        A :class:`RestoreResult`. The three parts are still reported
        separately, because the Undo page says what it did in those terms —
        but they are now three readings of one outcome, not three code paths.
        An unknown id comes back as a result whose warnings say so, rather than
        as an exception: the caller is a page showing a list that may be out of
        date.
    """
    from .transaction import FileRemove, SettingReset, TransactionError

    result = RestoreResult()
    point = load(point_id, root=root)
    if point is None:
        result.warnings.append("that saved moment is no longer there")
        return result

    transaction = point.to_transaction()
    if dest_root is not None:
        transaction.dest_root = str(dest_root)
    if backend is not None:
        transaction.backend = backend
    if not transaction.ops:
        return result

    try:
        outcome = transaction.apply(progress_cb)
    except TransactionError as exc:
        result.warnings.append(str(exc))
        # Carry the engine's answer through instead of dropping it. The
        # transaction knows whether its own rollback finished; a page that
        # cannot see that has no way to tell the user which of the two very
        # different things just happened, and defaulting to the reassuring one
        # is how an app comes to say "nothing was changed" over a half-restored
        # desktop.
        result.rolled_back = exc.rolled_back
        return result

    result.transaction = outcome
    result.unset = sorted(op.key for op in outcome.applied if isinstance(op, SettingReset))
    result.removed = sorted(op.dest for op in outcome.applied if isinstance(op, FileRemove))
    result.warnings.extend(reason for _op, reason in outcome.skipped)

    # Going back to a saved moment means you are no longer using the Look you
    # were using — you are using the desktop as it was at that moment, which
    # may or may not have been a Look and which nothing here can honestly name.
    # A saved moment carries a label ("My desktop, 25 August") and applying it
    # runs a real transaction, so the one thing to be careful of is letting
    # that label be mistaken for a Look's. ``to_transaction`` passes neither a
    # label nor a look, which is what keeps the Look-switch cleanup switched
    # off here: a restore puts back exactly what the moment recorded and strips
    # nothing else off the desktop.
    from . import ledger as ledger_store

    ledger_store.clear_current_look()
    return result


# -- the v1 import (DESIGN.md F1) -----------------------------------------


def _v1_key(record: dict, fallback: str) -> str | None:
    """Translate a v1 baseline record's address into the v2 key grammar.

    v1 stored ``{"backend": "gsettings", "key": "org.gnome.desktop.interface
    color-scheme"}`` and indexed it as ``gsettings:<key>``. That index string
    *is* the v2 grammar, which is not a coincidence — the grammar was chosen to
    keep this import a rename rather than a translation. The record fields are
    preferred over the index key so a hand-edited index cannot mislead it.
    """
    backend = record.get("backend")
    key = record.get("key")
    if backend in ("gsettings", "dconf") and isinstance(key, str) and key:
        return f"{backend}:{key}"
    if fallback.startswith(("gsettings:", "dconf:")):
        return fallback
    return None


def import_v1_baseline(
    source: str | Path | None = None,
    root: str | Path | None = None,
) -> RestorePoint | None:
    """Build the "Before gtheme" restore point from v1's saved state.

    Args:
        source: the v1 backup directory. Defaults to
            ``~/.local/state/gtheme.v1-backup``; ``GTHEME_V1_BACKUP_DIR``
            overrides that.
        root: where to write the restore point.

    Returns:
        The imported point, or None when there is no v1 state to import —
        which is the normal case on a fresh install, and not an error.

    The v1 store is opened read-only and nothing is written back to it, ever.
    Everything importable is imported; everything that is not gets a warning
    naming what was lost, because a silent gap in the one recording of a
    person's original desktop is the worst possible failure here.
    """
    base = Path(source) if source is not None else v1_backup_dir()
    baseline = base / "backups" / "baseline"
    settings_index = baseline / "settings.json"
    files_index = baseline / "files.json"
    if not settings_index.is_file() and not files_index.is_file():
        return None

    when = _now()
    point = RestorePoint(
        id=PRISTINE_ID,
        label="Before gtheme",
        created=when,
        kind="pristine",
        path=_root(root) / PRISTINE_ID,
    )

    settings_data, warning = load_json(settings_index, {})
    if warning:
        point.warnings.append(warning)
    if isinstance(settings_data, dict):
        for index_key, record in settings_data.items():
            if not isinstance(record, dict):
                continue
            key = _v1_key(record, str(index_key))
            if key is None:
                point.warnings.append(f"could not read one saved setting ({index_key})")
                continue
            saved = record.get("saved")
            point.settings[key] = saved if isinstance(saved, str) else None

    files_data, warning = load_json(files_index, {})
    if warning:
        point.warnings.append(warning)
    if isinstance(files_data, dict):
        blobs = baseline / "files"
        files_dir = point.path / _FILES_DIRNAME if point.path else None
        for dest, record in files_data.items():
            if not isinstance(record, dict):
                continue
            if not record.get("existed"):
                point.files[dest] = None
                continue
            if record.get("symlink"):
                # v1 recorded links as links, and so does v2: ``{"link":
                # target}`` restores by putting the shortcut back. Recording it
                # as absence instead compiled to FileRemove — pressing "Before
                # gtheme" *deleted the user's own link* into their dotfiles
                # repository and left a hole, while the attached warning said
                # that one was "not covered here" (review-report H10). The
                # capture path has recorded links correctly since the same bug
                # was fixed there; the importer was simply never updated.
                target = record.get("target")
                if isinstance(target, str) and target:
                    point.files[dest] = {"link": target}
                    continue
                # A link whose target v1 never recorded cannot be recreated.
                # Leaving the destination out is the only honest answer.
                point.warnings.append(
                    f"{dest} was a shortcut to somewhere else before gtheme, and where it "
                    "pointed was not recorded; it is left exactly as it is"
                )
                continue
            blob = record.get("backup")
            source_blob = blobs / str(blob) if blob else None
            if source_blob is None or not source_blob.is_file():
                # "We cannot restore this" must never compile to "delete it".
                # A destination left out of the moment is one the restore does
                # not touch; recording None here would have removed the file
                # whose only saved copy is the thing that went missing.
                point.warnings.append(
                    f"the saved copy of {dest} is missing; it is left exactly as it is"
                )
                continue
            assert files_dir is not None
            files_dir.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(source_blob, files_dir / str(blob))
            except OSError as exc:
                # Same rule as the missing blob above: a copy that failed means
                # this destination is not covered, which is not the same thing
                # as "it was not there", and only one of those two is a
                # deletion.
                point.warnings.append(
                    f"could not copy the saved {dest}: {exc}; it is left exactly as it is"
                )
                continue
            point.files[dest] = str(blob)

    if point.is_empty and not point.warnings:
        return None
    return _write(point)


def read_v1_current(source: str | Path | None = None) -> str | None:
    """Which Look v1 had applied when it was last used, if any.

    Read-only, and only ever used to label things — "you were using MAGMA
    before" is a sentence worth being able to say.
    """
    base = Path(source) if source is not None else v1_backup_dir()
    try:
        text = (base / "current").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None
