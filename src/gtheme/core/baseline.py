"""The pristine baseline: what your desktop looked like before gtheme.

The first time gtheme touches a file or a setting, it records what was there.
It never records the same thing twice, so no matter how many Looks are applied
and switched afterwards, the recording still describes the *pre-gtheme* state.
That single rule is the product promise: undo always works, however long you
have been playing.

A successful full restore *consumes* the recording. This is not tidiness. A
kept record would stop the next apply from re-recording, and the desktop the
user has edited since would be silently reverted to a state months old the next
time they pressed undo.

The store is written incrementally and atomically. Every record persists its
own index the moment it is made, so a crash halfway through an apply leaves a
recording that describes exactly what had been changed by then — not an empty
one, and not a stale one. That is the crash-mid-apply guarantee, and it is why
there is no single "save at the end" call that a SIGKILL could skip.

Three defects from v1 live here as named behaviour:

* **F1** — a FIFO, socket or device node at a destination cannot be snapshotted
  (copying one blocks or raises). :meth:`Baseline.record_file` returns False
  and the caller must then leave the destination alone rather than write over
  something it cannot put back.
* **R5** — a record can become *dead*: its stored copy is gone, a symlink was
  recorded with no target, the add-on that owned a setting was uninstalled.
  Re-running restore can never fix those, so they are reported separately from
  transient failures and the caller may drop them. Without that, one dead
  record wedges restore forever.
* **R1/R3/R6** — only what actually reverted may be forgotten, and forgetting
  destroys the stored copy. A transient failure keeps its record *and* its
  blob, or the only pre-gtheme copy of somebody's file is gone for good.

There is no hook machinery here, and there is no ``hooks.json``. v1 recorded
which scripts it had run so it could run their undo scripts later; v2 runs no
scripts at all (DESIGN.md A4), so there is nothing to record.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .atomic import atomic_write_json, load_json
from .backends import get_backend, is_missing
from .paths import baseline_dir
from .settings_backend import BackendError, SettingsBackend

__all__ = ["Baseline", "RestoreOutcome", "missing_ancestors"]


def missing_ancestors(parent: Path) -> list[str]:
    """The directories a coming ``mkdir(parents=True)`` will create, deepest first.

    Captured *before* the mkdir runs, this is exactly what restore may remove
    again — no guessing. A directory that already existed but happened to be
    empty must survive a restore, and the only way to know the difference is to
    have looked beforehand.
    """
    created: list[str] = []
    current = parent
    while not current.exists() and current != current.parent:
        created.append(str(current))
        current = current.parent
    return created


@dataclass
class RestoreOutcome:
    """What a restore pass managed to do.

    Attributes:
        log: what was put back, one line each, in the user's words.
        warnings: what could not be, one line each.
        done: keys that reverted and may therefore be forgotten.
        dead: keys that can never revert — the stored copy is gone, or the
            setting no longer exists on this machine. Reported apart from
            transient failures so restore can finish instead of wedging.
    """

    log: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    done: list[str] = field(default_factory=list)
    dead: list[str] = field(default_factory=list)


class Baseline:
    """The on-disk recording of pre-gtheme file and setting state.

    Args:
        root: where the recording lives. Defaults to the v2 baseline directory,
            which ``GTHEME_STATE_DIR`` reroots under test.
        backend: how to read and write settings. Defaults to the process
            backend, which ``core.backends.use_backend`` replaces in tests.
    """

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        backend: SettingsBackend | None = None,
    ) -> None:
        self.dir = Path(root) if root is not None else baseline_dir()
        self.files_dir = self.dir / "files"
        self.files_index = self.dir / "files.json"
        self.settings_index = self.dir / "settings.json"
        self.files: dict[str, dict] = {}
        self.settings: dict[str, dict] = {}
        self.warnings: list[str] = []
        self._backend = backend
        self._counter = 0

    @property
    def backend(self) -> SettingsBackend:
        return self._backend if self._backend is not None else get_backend()

    # -- persistence -------------------------------------------------------

    def load(self) -> Baseline:
        """Read the recording from disk. Never raises; corruption is a warning."""
        self.warnings = []
        files, warning = load_json(self.files_index, {})
        if warning:
            self.warnings.append(warning)
        settings, warning = load_json(self.settings_index, {})
        if warning:
            self.warnings.append(warning)
        self.files = files if isinstance(files, dict) else {}
        self.settings = settings if isinstance(settings, dict) else {}
        self._counter = self._highest_blob_number()
        return self

    def _highest_blob_number(self) -> int:
        """The largest stored-copy number ever used.

        Counting the files instead would reuse a number after a delete, and the
        reused number would overwrite a copy still referenced by another record.
        """
        if not self.files_dir.is_dir():
            return 0
        highest = 0
        for path in self.files_dir.glob("*"):
            try:
                highest = max(highest, int(path.name))
            except ValueError:
                continue
        return highest

    def save(self) -> None:
        """Flush both indexes. Records already persisted themselves; this is a
        belt-and-braces final write."""
        self.dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.files_index, self.files)
        atomic_write_json(self.settings_index, self.settings)

    def _save_files(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.files_index, self.files)

    def _save_settings(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.settings_index, self.settings)

    @property
    def is_empty(self) -> bool:
        return not self.files and not self.settings

    def wipe(self) -> None:
        """Delete the whole recording. Only ever after a complete restore."""
        if self.dir.is_dir():
            shutil.rmtree(self.dir)
        self.files = {}
        self.settings = {}
        self._counter = 0

    # -- files -------------------------------------------------------------

    def record_file(self, dest: Path, component: str = "", label: str = "") -> bool:
        """Record what is at ``dest`` before something overwrites it.

        A symlink is recorded *as a link* — its target, never its contents — so
        restore recreates the link instead of writing a file through it. This
        machine's ``~/.config/ghostty`` is a symlink into a separate rice
        repository; dereferencing it would edit that repository.

        Returns:
            False for a FIFO, socket or device node at ``dest`` (the F1 case).
            No copy is possible and none is recorded, and the caller must then
            skip the write: overwriting something that cannot be put back is
            exactly what this class exists to prevent. True otherwise,
            including when ``dest`` does not exist yet.
        """
        key = str(dest)
        if key in self.files:
            return True
        if dest.is_symlink():
            try:
                target = os.readlink(dest)
            except OSError:
                target = ""
            self.files[key] = {
                "existed": True,
                "symlink": True,
                "target": target,
                "backup": None,
                "component": component,
                "label": label,
            }
        elif dest.is_file():
            self.files_dir.mkdir(parents=True, exist_ok=True)
            self._counter += 1
            stored = self.files_dir / f"{self._counter:04d}"
            shutil.copy2(dest, stored)
            self.files[key] = {
                "existed": True,
                "symlink": False,
                "target": None,
                "backup": stored.name,
                "component": component,
                "label": label,
            }
        elif dest.exists() and not dest.is_dir():
            return False
        else:
            self.files[key] = {
                "existed": False,
                "symlink": False,
                "target": None,
                "backup": None,
                "dirs": missing_ancestors(dest.parent),
                "component": component,
                "label": label,
            }
        self._save_files()
        return True

    def restore_files(self, only: set[str] | None = None) -> RestoreOutcome:
        """Put recorded files back. Filtered by component when ``only`` is given."""
        outcome = RestoreOutcome()
        created_dirs: list[str] = []
        for dest_text, record in self.files.items():
            if only is not None and record.get("component", "") not in only:
                continue
            dest = Path(dest_text)
            if record.get("existed"):
                if record.get("symlink"):
                    self._restore_symlink(dest, dest_text, record, outcome)
                    continue
                self._restore_blob(dest, dest_text, record, outcome)
            else:
                self._remove_installed(dest, dest_text, record, outcome, created_dirs)
        # Remove the directories the apply's mkdir created, deepest first and
        # only after every removal, so a sibling from another record does not
        # keep a directory alive. rmdir refuses a non-empty directory, so
        # anything still in use is left exactly where it is.
        for directory in sorted(set(created_dirs), key=lambda text: -len(Path(text).parts)):
            try:
                os.rmdir(directory)
            except OSError:
                pass
        return outcome

    def _restore_symlink(
        self, dest: Path, key: str, record: dict, outcome: RestoreOutcome
    ) -> None:
        target = record.get("target") or ""
        if not target:
            outcome.warnings.append(f"cannot put back the link at {dest}: its target was not recorded")
            outcome.dead.append(key)
            return
        try:
            if dest.is_symlink() or dest.exists():
                dest.unlink()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.symlink_to(target)
        except OSError as exc:
            outcome.warnings.append(f"could not put back the link at {dest}: {exc}")
            return
        outcome.log.append(f"put back the link {dest} -> {target}")
        outcome.done.append(key)

    def _restore_blob(self, dest: Path, key: str, record: dict, outcome: RestoreOutcome) -> None:
        blob = record.get("backup")
        source = self.files_dir / blob if blob else None
        if source is None or not source.is_file():
            outcome.warnings.append(f"the saved copy of {dest} is gone; left it as it is")
            outcome.dead.append(key)
            return
        try:
            # Never write through a link: drop whatever is at the destination
            # first, so a symlink planted there does not redirect the write.
            if dest.is_symlink() or dest.exists():
                dest.unlink()
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
        except OSError as exc:
            outcome.warnings.append(f"could not put back {dest}: {exc}")
            return
        outcome.log.append(f"put back {dest}")
        outcome.done.append(key)

    def _remove_installed(
        self,
        dest: Path,
        key: str,
        record: dict,
        outcome: RestoreOutcome,
        created_dirs: list[str],
    ) -> None:
        try:
            if dest.is_symlink() or (dest.exists() and not dest.is_dir()):
                dest.unlink()
                outcome.log.append(f"removed {dest}")
        except OSError as exc:
            outcome.warnings.append(f"could not remove {dest}: {exc}")
            return
        outcome.done.append(key)
        created_dirs.extend(record.get("dirs") or [])

    def forget_files(self, keys: list[str]) -> None:
        """Drop file records and delete their stored copies.

        Destructive. Only ever pass keys that actually reverted, or keys whose
        stored copy is already lost. Passing a transient failure here throws
        away the only pre-gtheme copy of somebody's file.
        """
        changed = False
        for key in keys:
            record = self.files.pop(key, None)
            if record is None:
                continue
            blob = record.get("backup")
            if blob:
                try:
                    (self.files_dir / blob).unlink(missing_ok=True)
                except OSError:
                    pass
            changed = True
        if changed:
            self._save_files()

    # -- settings ----------------------------------------------------------

    def read_setting(self, key: str) -> str | None:
        """The current value of a setting, or None if it has never been set."""
        try:
            return self.backend.get(key)
        except BackendError as exc:
            if is_missing(exc):
                return None
            raise

    def record_setting(self, key: str, component: str = "", label: str = "") -> None:
        """Record a setting's value before something overwrites it.

        A value of None means the key had none — restore resets it rather than
        writing a value back, which is the difference between "put it back" and
        "invent a value nobody chose".
        """
        if key in self.settings:
            return
        self.settings[key] = {
            "key": key,
            "saved": self.read_setting(key),
            "component": component,
            "label": label,
        }
        self._save_settings()

    def _already_at(self, key: str, saved: str | None) -> bool:
        """Is the setting already at its recorded value?

        A key that has no value now and had none then counts as already there:
        "there was nothing here" is a state, and it is the state we are in.
        """
        from .gvariant import values_equal

        try:
            current = self.backend.get(key)
        except BackendError as exc:
            return saved is None and is_missing(exc)
        if saved is None:
            return False
        return values_equal(current, saved)

    def restore_settings(self, only: set[str] | None = None) -> RestoreOutcome:
        """Put recorded settings back. Filtered by component when ``only`` is given."""
        outcome = RestoreOutcome()
        backend = self.backend
        for key, record in self.settings.items():
            if only is not None and record.get("component", "") not in only:
                continue
            target = record.get("key", key)
            saved = record.get("saved")
            try:
                if self._already_at(target, saved):
                    # Nothing to put back. Worth checking rather than writing
                    # anyway: a rollback records every key it is *about* to
                    # write, including the one whose write failed, and trying
                    # to "restore" that one would fail for the same reason and
                    # report a rollback that did not happen.
                    outcome.log.append(f"{target} was already as it was")
                    outcome.done.append(key)
                    continue
                if saved is None:
                    backend.reset(target)
                else:
                    backend.set(target, saved)
            except BackendError as exc:
                if saved is None and is_missing(exc):
                    # Nothing was set before and there is nothing to reset —
                    # the add-on is gone. That state is already pristine.
                    outcome.log.append(f"{target} was already unset")
                    outcome.done.append(key)
                    continue
                if is_missing(exc):
                    outcome.warnings.append(
                        f"cannot put back {target}: that setting no longer exists here"
                    )
                    outcome.dead.append(key)
                    continue
                outcome.warnings.append(f"could not put back {target}: {exc}")
                continue
            outcome.log.append(f"put back {target}")
            outcome.done.append(key)
        return outcome

    def forget_settings(self, keys: list[str]) -> None:
        """Drop setting records. See :meth:`forget_files` on when that is safe."""
        changed = False
        for key in keys:
            if self.settings.pop(key, None) is not None:
                changed = True
        if changed:
            self._save_settings()

    # -- selective passes --------------------------------------------------

    def restore_only_files(self, keys: list[str]) -> RestoreOutcome:
        """Restore exactly these file destinations and nothing else."""
        return self._restricted("files", keys, self.restore_files)

    def restore_only_settings(self, keys: list[str]) -> RestoreOutcome:
        """Restore exactly these setting keys and nothing else."""
        return self._restricted("settings", keys, self.restore_settings)

    def _restricted(self, attribute: str, keys: list[str], run) -> RestoreOutcome:
        whole = getattr(self, attribute)
        setattr(self, attribute, {k: whole[k] for k in keys if k in whole})
        try:
            return run()
        finally:
            setattr(self, attribute, whole)
