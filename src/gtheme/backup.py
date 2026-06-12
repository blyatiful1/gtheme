"""The pristine-baseline snapshot store that makes restore generic.

The first time gtheme touches a file destination or a settings key, the prior
state is recorded here. ``apply`` only ever *adds* to the baseline, so no
matter how many themes are applied or switched, ``restore`` always returns the
system to the state it had before gtheme first ran.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import paths
from .manifest import Setting
from .settings import ResolvedSetting


def read_current() -> str | None:
    try:
        return paths.CURRENT_FILE.read_text().strip() or None
    except FileNotFoundError:
        return None


def write_current(name: str) -> None:
    paths.ensure_state_dirs()
    paths.CURRENT_FILE.write_text(name + "\n")


def clear_current() -> None:
    paths.CURRENT_FILE.unlink(missing_ok=True)


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
        self._counter = 0

    def load(self) -> "Baseline":
        if self.files_meta.is_file():
            self.files = json.loads(self.files_meta.read_text())
        if self.settings_meta.is_file():
            self.settings = json.loads(self.settings_meta.read_text())
        if self.hooks_meta.is_file():
            self.hooks = json.loads(self.hooks_meta.read_text())
        self._counter = len(list(self.files_dir.glob("*"))) if self.files_dir.is_dir() else 0
        return self

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.files_meta.write_text(json.dumps(self.files, indent=2) + "\n")
        self.settings_meta.write_text(json.dumps(self.settings, indent=2) + "\n")
        self.hooks_meta.write_text(json.dumps(self.hooks, indent=2) + "\n")

    def record_hook(self, theme_dir: str, restore_script: str, sudo: bool) -> None:
        """Remember that an install hook ran, so its restore can be run later."""
        ident = {"dir": theme_dir, "restore": restore_script, "sudo": sudo}
        if ident not in self.hooks:
            self.hooks.append(ident)

    @property
    def is_empty(self) -> bool:
        return not self.files and not self.settings

    # ----------------------------------------------------------------- files ---
    def record_file(self, dest: Path) -> None:
        key = str(dest)
        if key in self.files:
            return
        if dest.exists() and not dest.is_dir():
            self.files_dir.mkdir(parents=True, exist_ok=True)
            self._counter += 1
            stored = self.files_dir / f"{self._counter:04d}"
            shutil.copy2(dest, stored)
            self.files[key] = {"existed": True, "backup": stored.name}
        else:
            self.files[key] = {"existed": False, "backup": None}

    def restore_files(self) -> list[str]:
        log: list[str] = []
        for dest_str, rec in self.files.items():
            dest = Path(dest_str)
            if rec["existed"]:
                src = self.files_dir / rec["backup"]
                if src.is_file():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)
                    log.append(f"restored {dest}")
            else:
                if dest.exists() and not dest.is_dir():
                    dest.unlink()
                    log.append(f"removed {dest}")
        return log

    # -------------------------------------------------------------- settings ---
    def record_setting(self, rs: ResolvedSetting) -> None:
        key = f"{rs.backend}:{rs.key}"
        if key in self.settings:
            return
        self.settings[key] = {
            "backend": rs.backend,
            "key": rs.key,
            "saved": rs.get_current(),
        }

    def restore_settings(self) -> list[str]:
        log: list[str] = []
        for rec in self.settings.values():
            stub = Setting(
                component="", backend=rec["backend"], key=rec["key"], value=""
            )
            rs = ResolvedSetting(stub, ctx={})  # key already resolved
            if rs.restore(rec["saved"]):
                log.append(f"restored {rec['backend']} {rec['key']}")
        return log

    def wipe(self) -> None:
        if self.dir.is_dir():
            shutil.rmtree(self.dir)
