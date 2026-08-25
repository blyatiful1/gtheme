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

import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .atomic import atomic_write_json, load_json
from .backends import get_backend
from .confine import safe_name
from .paths import restore_points_dir, v1_backup_dir
from .settings_backend import BackendError, SettingsBackend

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
        files: destination to the name of its saved copy, or None where the
            file did not exist and restoring means deleting it again.
        warnings: what could not be recorded, in plain words. Never silent.
        path: where this lives on disk.
    """

    id: str
    label: str
    created: datetime
    kind: str = "auto"
    settings: dict[str, str | None] = field(default_factory=dict)
    files: dict[str, str | None] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    path: Path | None = None

    @property
    def is_empty(self) -> bool:
        return not self.settings and not self.files

    @property
    def keys_to_unset(self) -> list[str]:
        """Settings that had no value at all when this moment was saved.

        Restoring one means *unsetting* it, and there is no operation for that:
        the frozen set is FileWrite, SettingWrite, ExtensionEnable and
        ExtensionInstall, and a write cannot say "there should be nothing
        here". :func:`apply_point` handles these separately — see its note.

        This is not a corner case. The "Before gtheme" point imported from v1
        on this machine has 46 settings, and 33 of them are these: keys that
        belong to add-ons the user had never configured before a Look
        configured them.
        """
        return sorted(key for key, value in self.settings.items() if value is None)

    @property
    def files_to_remove(self) -> list[str]:
        """Files that did not exist when this moment was saved.

        Restoring means deleting whatever was put there. Same story as
        :attr:`keys_to_unset`: no operation expresses it.
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

        Settings that had no value at all are not expressible as a write, so
        they are left out here; the pristine baseline is what resets those, and
        ``gtheme rescue`` is what runs it.
        """
        from .transaction import FileWrite, SettingWrite, Transaction

        ops: list[FileWrite | SettingWrite] = []
        base = (self.path or Path()) / _FILES_DIRNAME
        for dest, blob in sorted(self.files.items()):
            if blob is None:
                continue
            ops.append(FileWrite(src=str(base / blob), dest=dest))
        for key, value in sorted(self.settings.items()):
            if value is None:
                continue
            ops.append(SettingWrite(key=key, value=value))
        return Transaction(ops, label=self.label)


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id(when: datetime) -> str:
    return when.strftime("%Y-%m-%dT%H-%M-%S")


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

    A key that cannot be read is recorded as having no value, with a warning
    naming it. That is honest and restorable: "there was nothing here" is a
    state, and restoring it means unsetting the key again.
    """
    when = _now()
    reader = backend if backend is not None else get_backend()
    identifier = safe_name(point_id or _new_id(when))
    point = RestorePoint(
        id=identifier,
        label=label,
        created=when,
        kind=kind,
        path=_root(root) / identifier,
    )
    for key in dict.fromkeys(keys):
        try:
            point.settings[key] = reader.get(key)
        except BackendError:
            point.settings[key] = None

    if dests:
        files_dir = point.path / _FILES_DIRNAME if point.path else None
        for index, dest in enumerate(dict.fromkeys(dests), start=1):
            source = Path(dest)
            if source.is_symlink() or not source.is_file():
                # A link, a missing file, or something exotic. Recording it as
                # absent means restoring removes whatever was put there, which
                # is the right answer for a file that was not there before.
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
        extra_keys: settings to save that the transaction will not write
            itself. Switching Looks *reverts* what the outgoing one owned and
            the incoming one does not manage — a real change to the desktop
            that the diff does not describe. Without these, "Undo" after a
            switch would put back the pristine state rather than the Look that
            was on a moment ago, which is not what anybody pressing it means.
        extra_dests: the same, for files.
    """
    from .transaction import ENABLED_EXTENSIONS_KEY, ExtensionEnable, FileWrite, SettingWrite

    mapping = resolved_dests or {}
    keys: list[str] = []
    dests: list[str] = []
    for entry in diff.changes:
        op = entry.op
        if isinstance(op, SettingWrite):
            keys.append(op.key)
        elif isinstance(op, ExtensionEnable):
            keys.append(ENABLED_EXTENSIONS_KEY)
        elif isinstance(op, FileWrite):
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
    """

    transaction: object | None = None
    unset: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def apply_point(
    point_id: str,
    progress_cb=None,
    *,
    root: str | Path | None = None,
    backend: SettingsBackend | None = None,
    dest_root: str | Path | None = None,
) -> RestoreResult:
    """Put the desktop back to a saved moment.

    The writes go through an ordinary :class:`Transaction`, so the confinement
    preflight, the pristine recording and the all-or-nothing rollback all apply
    to them exactly as they do to applying a Look.

    The rest does not, and this is worth being explicit about rather than
    hiding. Two thirds of a pristine restore point is *absence*: settings that
    had no value, and files that were not there. The frozen operation set has
    no way to say either — ``SettingWrite`` writes a value and ``FileWrite``
    writes a file — so those are carried out here, after the transaction, each
    one recorded in the pristine baseline first so it is itself undoable.

    That split is a gap in the contract, not a design: a first-class "unset"
    and "remove" operation would fold this back into the one apply path where
    DESIGN.md A8 wants it. Until that is decided, this function is the whole
    truth about restoring a moment, and it reports the three parts separately
    so the Undo page can say what it actually did.

    Args:
        point_id: which saved moment.
        progress_cb: passed through to the transaction.
        root: where restore points live.
        backend: how to read and write settings.
        dest_root: destination root for the file writes.

    Returns:
        A :class:`RestoreResult`. An unknown id comes back as a result whose
        warnings say so, rather than as an exception — the caller is a page
        showing a list that may be out of date.
    """
    from .backends import get_backend
    from .baseline import Baseline
    from .lock import process_lock
    from .transaction import TransactionError

    result = RestoreResult()
    point = load(point_id, root=root)
    if point is None:
        result.warnings.append("that saved moment is no longer there")
        return result

    transaction = point.to_transaction()
    if dest_root is not None:
        transaction.dest_root = str(dest_root)
    if transaction.ops:
        try:
            result.transaction = transaction.apply(progress_cb)
        except TransactionError as exc:
            result.warnings.append(str(exc))
            return result

    writer = backend if backend is not None else get_backend()
    keys = point.keys_to_unset
    files = point.files_to_remove
    if not keys and not files:
        return result

    with process_lock():
        baseline = Baseline(backend=writer).load()
        for key in keys:
            baseline.record_setting(key, "", point.label)
            try:
                writer.reset(key)
            except BackendError as exc:
                result.warnings.append(f"could not clear one setting: {exc}")
                continue
            result.unset.append(key)
        for dest in files:
            target = Path(dest)
            if not target.exists() and not target.is_symlink():
                continue
            if not baseline.record_file(target, "", point.label):
                result.warnings.append(f"left {dest} alone: it is not an ordinary file")
                continue
            try:
                target.unlink()
            except OSError as exc:
                result.warnings.append(f"could not remove {dest}: {exc}")
                continue
            result.removed.append(dest)
        baseline.save()
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
                # v1 recorded links as links. A restore point restores files;
                # re-creating the link is the pristine baseline's job, so say
                # so rather than pretending the file is covered.
                point.files[dest] = None
                point.warnings.append(
                    f"{dest} was a shortcut to somewhere else before gtheme; "
                    "undoing that one is not covered here"
                )
                continue
            blob = record.get("backup")
            source_blob = blobs / str(blob) if blob else None
            if source_blob is None or not source_blob.is_file():
                point.files[dest] = None
                point.warnings.append(f"the saved copy of {dest} is missing")
                continue
            assert files_dir is not None
            files_dir.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(source_blob, files_dir / str(blob))
            except OSError as exc:
                point.files[dest] = None
                point.warnings.append(f"could not copy the saved {dest}: {exc}")
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
