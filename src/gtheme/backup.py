"""The pristine-baseline snapshot store that makes restore generic.

The first time gtheme touches a file destination or a settings key, the prior
state is recorded here. ``apply`` never overwrites a recorded snapshot, so no
matter how many themes are applied or switched, ``restore`` always returns the
system to the state it had before gtheme first ran. A successful full restore
*consumes* the records — the desktop is pristine again, and the next apply
snapshots that (possibly user-edited) state as the new baseline.

The store is written atomically and incrementally: every record persists its
own index immediately (tmp + ``os.replace`` + fsync, with a ``.bak`` of the
prior file), so a crash mid-apply still leaves a consistent, restorable
baseline. ``load`` never raises on a corrupt index — it falls back to the
last-good ``.bak`` and otherwise starts empty, remembering a warning.
"""

from __future__ import annotations

import fcntl
import json
import os
import shutil
from contextlib import contextmanager
from pathlib import Path

from . import paths
from .errors import GthemeError
from .manifest import Setting
from .settings import ResolvedSetting


def read_current() -> str | None:
    try:
        return paths.CURRENT_FILE.read_text(encoding="utf-8").strip() or None
    except FileNotFoundError:
        return None


def write_current(name: str) -> None:
    paths.ensure_state_dirs()
    # tmp + replace, like every other state write — never a torn `current`.
    tmp = paths.CURRENT_FILE.with_name(paths.CURRENT_FILE.name + ".tmp")
    tmp.write_text(name + "\n", encoding="utf-8")
    os.replace(tmp, paths.CURRENT_FILE)


def clear_current() -> None:
    paths.CURRENT_FILE.unlink(missing_ok=True)


@contextmanager
def process_lock():
    """L1: exclusive inter-process lock around state mutations (apply/restore/remove).

    Concurrent runs interleave ledger read-modify-writes, and two Baselines
    that loaded the same blob counter would clobber each other's PRISTINE
    copies. Fail fast (LOCK_NB) instead of queueing behind e.g. a blocked
    sudo hook.
    """
    paths.ensure_state_dirs()
    fd = os.open(paths.STATE_DIR / "lock", os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        raise GthemeError(
            "another gtheme is already applying/restoring — wait for it to finish"
        ) from None
    try:
        yield
    finally:
        os.close(fd)  # closing the fd releases the flock


# ---------------------------------------------------- active-ownership ledger ---
# Records, per applied theme, the concrete file dests and setting keys it
# actively installs. Lets ``apply`` (switch) revert items the *outgoing* theme
# owned that the *incoming* one does not manage, restoring them from the pristine
# baseline. The baseline originals themselves are never mutated.
_LEDGER_FILE = paths.STATE_DIR / "ownership.json"


def read_ledger() -> dict[str, dict]:
    """Map theme-name -> {"files": [...], "settings": [...]}. Never raises."""
    data, _ = _load_json(_LEDGER_FILE, {})
    return data if isinstance(data, dict) else {}


def write_ledger(ledger: dict[str, dict]) -> None:
    paths.ensure_state_dirs()
    _atomic_write_json(_LEDGER_FILE, ledger)


def _atomic_write_json(path: Path, data) -> None:
    """Write ``data`` as JSON to ``path`` atomically.

    Keeps a ``<name>.bak`` copy of the prior file, writes a sibling tmp file,
    fsyncs it, then ``os.replace``s it into place and fsyncs the directory.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        try:
            shutil.copy2(path, path.with_name(path.name + ".bak"))
        except OSError:
            pass
    tmp = path.with_name(path.name + ".tmp")
    text = json.dumps(data, indent=2) + "\n"
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    try:
        dfd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass


def _load_json(path: Path, default):
    """Load JSON from ``path``, falling back to ``<name>.bak``.

    Returns ``(value, warning_or_None)``. Never raises on corruption.
    """
    if not path.is_file():
        return default, None
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (json.JSONDecodeError, OSError, ValueError):
        bak = path.with_name(path.name + ".bak")
        if bak.is_file():
            try:
                value = json.loads(bak.read_text(encoding="utf-8"))
                return value, f"baseline index {path.name} was corrupt; recovered from {bak.name}"
            except (json.JSONDecodeError, OSError, ValueError):
                pass
        return default, f"baseline index {path.name} was corrupt and unrecoverable; starting empty"


def _missing_ancestors(parent: Path) -> list[str]:
    """The not-yet-existing ancestors of a dest (deepest first).

    Captured BEFORE apply's ``mkdir(parents=True)`` runs, these are exactly
    the directories that mkdir will create — so restore can remove precisely
    them and never guess (a pre-existing-but-empty dir must survive restore).
    """
    dirs: list[str] = []
    p = parent
    while not p.exists() and p != p.parent:
        dirs.append(str(p))
        p = p.parent
    return dirs


class Baseline:
    """On-disk record of pre-gtheme file and setting state."""

    def __init__(self) -> None:
        self.dir = paths.BASELINE_DIR
        self.files_dir = self.dir / "files"
        self.files_meta = self.dir / "files.json"
        self.settings_meta = self.dir / "settings.json"
        self.hooks_meta = self.dir / "hooks.json"
        self.files: dict[str, dict] = {}
        self.settings: dict[str, dict] = {}
        self.hooks: list[dict] = []
        self.warnings: list[str] = []
        self._counter = 0

    def load(self) -> "Baseline":
        self.warnings = []
        self.files, w = _load_json(self.files_meta, {})
        if w:
            self.warnings.append(w)
        self.settings, w = _load_json(self.settings_meta, {})
        if w:
            self.warnings.append(w)
        self.hooks, w = _load_json(self.hooks_meta, [])
        if w:
            self.warnings.append(w)
        if not isinstance(self.files, dict):
            self.files = {}
        if not isinstance(self.settings, dict):
            self.settings = {}
        if not isinstance(self.hooks, list):
            self.hooks = []
        # Counter tracks the highest blob index ever used, so we never clobber an
        # existing backup blob (file *count* would reuse numbers after deletes).
        self._counter = self._max_blob_index()
        return self

    def _max_blob_index(self) -> int:
        if not self.files_dir.is_dir():
            return 0
        hi = 0
        for p in self.files_dir.glob("*"):
            try:
                hi = max(hi, int(p.name))
            except ValueError:
                continue
        return hi

    def save(self) -> None:
        """Persist all three indexes atomically (final write)."""
        self.dir.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(self.files_meta, self.files)
        _atomic_write_json(self.settings_meta, self.settings)
        _atomic_write_json(self.hooks_meta, self.hooks)

    def _save_files(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(self.files_meta, self.files)

    def _save_settings(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(self.settings_meta, self.settings)

    def _save_hooks(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(self.hooks_meta, self.hooks)

    def record_hook(
        self,
        theme_dir: str,
        restore_script: str,
        sudo: bool,
        component: str = "hook",
        theme: str = "",
    ) -> None:
        """Remember that an install hook ran, so its restore can be run later."""
        ident = {
            "dir": theme_dir,
            "restore": restore_script,
            "sudo": sudo,
            "component": component,
            "theme": theme,
        }
        if ident not in self.hooks:
            self.hooks.append(ident)
            self._save_hooks()

    def forget_hooks(self, records: list[dict]) -> None:
        """Drop recorded hooks (after their restore ran, or on theme removal)."""
        changed = False
        for rec in records:
            if rec in self.hooks:
                self.hooks.remove(rec)
                changed = True
        if changed:
            self._save_hooks()

    def hooks_for_theme(self, theme: str, theme_dir: str | None = None) -> list[dict]:
        """Recorded hooks belonging to ``theme`` (by name or recorded dir)."""
        out = []
        for rec in self.hooks:
            if rec.get("theme") == theme or (theme_dir and rec.get("dir") == theme_dir):
                out.append(rec)
        return out

    @property
    def is_empty(self) -> bool:
        return not self.files and not self.settings

    # ----------------------------------------------------------------- files ---
    def record_file(self, dest: Path, component: str = "", theme: str = "") -> bool:
        """Snapshot ``dest``'s pristine state before it is overwritten.

        Symlinks are recorded as links (target only — never dereferenced) so
        restore can recreate the link instead of writing through it. Returns
        False — recording nothing — for a FIFO/socket/device at ``dest``: no
        snapshot is possible (a copy would raise, or block on a device node),
        so the caller must skip the write and leave the dest alone.
        """
        key = str(dest)
        if key in self.files:
            return True
        # Check symlink-ness BEFORE anything overwrites the destination.
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
                "theme": theme,
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
                "theme": theme,
            }
        elif dest.exists() and not dest.is_dir():
            # F1: special file (FIFO/socket/device) — no snapshot, no record.
            return False
        else:
            self.files[key] = {
                "existed": False,
                "symlink": False,
                "target": None,
                "backup": None,
                # Dirs the coming mkdir(parents=True) will create; restore
                # rmdirs exactly these (older records without the field: none).
                "dirs": _missing_ancestors(dest.parent),
                "component": component,
                "theme": theme,
            }
        self._save_files()
        return True

    def restore_files(
        self, only: set[str] | None = None
    ) -> tuple[list[str], list[str], list[str], list[str]]:
        """Revert recorded files. Returns ``(log, warnings, done, dead)``.

        ``done`` holds the keys that actually reverted — the only ones a caller
        may forget. ``dead`` holds unrecoverable records (blob lost, symlink
        without a target): re-running can never fix those, the caller decides
        their fate. A key in neither list failed transiently and must keep its
        record AND blob. Filtered by component when ``only`` is given.
        """
        log: list[str] = []
        warnings: list[str] = []
        done: list[str] = []
        dead: list[str] = []
        created_dirs: list[str] = []
        for dest_str, rec in self.files.items():
            if only is not None and rec.get("component", "") not in only:
                continue
            dest = Path(dest_str)
            if rec.get("existed"):
                if rec.get("symlink"):
                    target = rec.get("target") or ""
                    if not target:
                        warnings.append(f"cannot restore symlink (no target recorded): {dest}")
                        dead.append(dest_str)
                        continue
                    try:
                        if dest.is_symlink() or dest.exists():
                            dest.unlink()
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.symlink_to(target)
                        log.append(f"restored symlink {dest} -> {target}")
                        done.append(dest_str)
                    except OSError as exc:
                        warnings.append(f"failed to restore symlink {dest}: {exc}")
                    continue
                backup = rec.get("backup")
                src = self.files_dir / backup if backup else None
                if src is not None and src.is_file():
                    try:
                        # Never write through a link: drop whatever is at dest first.
                        if dest.is_symlink() or dest.exists():
                            dest.unlink()
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dest)
                        log.append(f"restored {dest}")
                        done.append(dest_str)
                    except OSError as exc:
                        warnings.append(f"failed to restore {dest}: {exc}")
                else:
                    warnings.append(f"backup blob missing for {dest}; cannot restore")
                    dead.append(dest_str)
            else:
                # Did not exist before gtheme: remove what we installed.
                try:
                    if dest.is_symlink():
                        dest.unlink()
                        log.append(f"removed {dest}")
                    elif dest.exists() and not dest.is_dir():
                        dest.unlink()
                        log.append(f"removed {dest}")
                    done.append(dest_str)
                    created_dirs.extend(rec.get("dirs") or [])
                except OSError as exc:
                    warnings.append(f"failed to remove {dest}: {exc}")
        # Drop the dirs apply's mkdir created (recorded per file), AFTER all
        # removals so siblings from other records don't block the rmdir; rmdir
        # refuses non-empty dirs, so anything still in use survives.
        for d in sorted(set(created_dirs), key=lambda s: -len(Path(s).parts)):
            try:
                os.rmdir(d)
            except OSError:
                pass
        return log, warnings, done, dead

    def forget_files(self, keys: list[str]) -> None:
        """Drop file records AND their pristine blobs.

        Destructive: only ever pass keys whose revert succeeded (``done`` from
        :meth:`restore_files`) or whose blob is already lost (``dead``) — never
        a transient failure, or the only pre-gtheme copy is gone for good.
        """
        changed = False
        for key in keys:
            if key in self.files:
                rec = self.files.pop(key)
                blob = rec.get("backup")
                if blob:
                    try:
                        (self.files_dir / blob).unlink(missing_ok=True)
                    except OSError:
                        pass
                changed = True
        if changed:
            self._save_files()

    # -------------------------------------------------------------- settings ---
    def record_setting(self, rs: ResolvedSetting, component: str = "", theme: str = "") -> None:
        key = f"{rs.backend}:{rs.key}"
        if key in self.settings:
            return
        self.settings[key] = {
            "backend": rs.backend,
            "key": rs.key,
            "saved": rs.get_current(),
            "component": component,
            "theme": theme,
        }
        self._save_settings()

    def restore_settings(
        self, only: set[str] | None = None
    ) -> tuple[list[str], list[str], list[str], list[str]]:
        """Reset recorded settings to their saved values.

        Returns ``(log, warnings, done, dead)`` — ``done`` holds the keys that
        reverted (or were benignly already-pristine) and are safe to forget;
        ``dead`` holds records whose schema/key no longer exists (app
        uninstalled after apply): re-running can never fix those, the caller
        decides their fate. (_run pins LC_ALL=C, so the error text is stable.)
        """
        log: list[str] = []
        warnings: list[str] = []
        done: list[str] = []
        dead: list[str] = []
        for key, rec in self.settings.items():
            if only is not None and rec.get("component", "") not in only:
                continue
            stub = Setting(
                component="", backend=rec["backend"], key=rec["key"], value=""
            )
            rs = ResolvedSetting(stub, ctx={})  # key already resolved
            if rs.restore(rec["saved"]):
                log.append(f"restored {rec['backend']} {rec['key']}")
                done.append(key)
            elif rec.get("saved") is None:
                # Key had no prior value; a reset that can't run (e.g. the schema
                # is gone) is benign — it is already effectively pristine.
                log.append(f"{rec['backend']} {rec['key']} left unset")
                done.append(key)
            else:
                err = (rs.error or "").lower()
                if "no such schema" in err or "no such key" in err:
                    warnings.append(
                        f"cannot restore {rec['backend']} {rec['key']}: "
                        f"schema/key no longer exists"
                    )
                    dead.append(key)
                else:
                    warnings.append(f"failed to restore {rec['backend']} {rec['key']}")
        return log, warnings, done, dead

    def forget_settings(self, keys: list[str]) -> None:
        """Drop setting records (used by switch-cleanup after reverting them)."""
        changed = False
        for key in keys:
            if key in self.settings:
                self.settings.pop(key)
                changed = True
        if changed:
            self._save_settings()

    def wipe(self) -> None:
        if self.dir.is_dir():
            shutil.rmtree(self.dir)
