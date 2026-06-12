"""Apply / restore / diff — the core engine.

``apply`` installs a theme's files and settings (snapshotting the pristine
state first) and runs its hooks. ``restore`` walks the baseline back to the
pre-gtheme state. ``compute_diffs`` powers both ``--dry-run`` and ``diff``.
"""

from __future__ import annotations

import difflib
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .. import ansi
from ..backup import Baseline, clear_current, write_current
from ..manifest import FileInstall, Theme
from ..paths import ensure_state_dirs, expand_dest
from ..settings import ResolvedSetting, backend_available


# --------------------------------------------------------------------- model ---
@dataclass
class FileOp:
    install: FileInstall
    src: Path
    dest: Path


@dataclass
class Diff:
    kind: str            # "file" | "setting"
    label: str           # dest path or setting key
    component: str
    status: str          # "new" | "changed" | "unchanged" | "missing-src"
    detail: str = ""     # unified diff / before->after


@dataclass
class ApplyResult:
    applied_files: int = 0
    applied_settings: int = 0
    hooks_run: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _selected(component: str, only: set[str] | None) -> bool:
    return only is None or component in only


# ---------------------------------------------------------------- file walking ---
def iter_file_ops(theme: Theme, only: set[str] | None = None) -> list[FileOp]:
    """Expand [[files]] entries into concrete (src, dest) file operations.

    A ``src`` that resolves to a directory installs every file beneath it to
    the matching path under ``dest``.
    """
    ops: list[FileOp] = []
    for fi in theme.files:
        if not _selected(fi.component, only):
            continue
        src = (theme.path / fi.src).resolve()
        dest = expand_dest(fi.dest)
        if src.is_dir():
            for sub in sorted(src.rglob("*")):
                if sub.is_file():
                    ops.append(FileOp(fi, sub, dest / sub.relative_to(src)))
        else:
            ops.append(FileOp(fi, src, dest))
    return ops


def resolved_settings(theme: Theme, only: set[str] | None = None) -> list[ResolvedSetting]:
    return [ResolvedSetting(s) for s in theme.settings if _selected(s.component, only)]


# ----------------------------------------------------------------------- diff ---
def _read_text(path: Path) -> str | None:
    try:
        return path.read_text()
    except (UnicodeDecodeError, ValueError):
        return None
    except OSError:
        return None


def compute_diffs(theme: Theme, only: set[str] | None = None) -> list[Diff]:
    diffs: list[Diff] = []
    for op in iter_file_ops(theme, only):
        if not op.src.is_file():
            diffs.append(Diff("file", str(op.dest), op.install.component, "missing-src"))
            continue
        if not op.dest.exists():
            diffs.append(Diff("file", str(op.dest), op.install.component, "new"))
            continue
        src_b, dst_b = op.src.read_bytes(), op.dest.read_bytes()
        if src_b == dst_b:
            diffs.append(Diff("file", str(op.dest), op.install.component, "unchanged"))
            continue
        src_t, dst_t = _read_text(op.src), _read_text(op.dest)
        if src_t is None or dst_t is None:
            detail = f"binary content differs ({len(dst_b)} -> {len(src_b)} bytes)"
        else:
            lines = list(
                difflib.unified_diff(
                    dst_t.splitlines(), src_t.splitlines(),
                    "current", "theme", lineterm="", n=1,
                )
            )
            detail = "\n".join(lines[:40]) + ("\n…" if len(lines) > 40 else "")
        diffs.append(Diff("file", str(op.dest), op.install.component, "changed", detail))

    for rs in resolved_settings(theme, only):
        current = rs.get_current()
        status = "unchanged" if current == rs.value else ("changed" if current is not None else "new")
        detail = f"{current} -> {rs.value}" if status != "unchanged" else ""
        diffs.append(Diff("setting", rs.label, rs.component, status, detail))
    return diffs


# ---------------------------------------------------------------------- hooks ---
def _run_hooks(
    theme: Theme,
    event: str,
    only: set[str] | None,
    allow_sudo: bool,
    result: ApplyResult,
    baseline: "Baseline | None" = None,
) -> None:
    for hook in theme.hooks:
        if hook.event != event or not _selected(hook.component, only):
            continue
        script = (theme.path / hook.script).resolve()
        if not script.is_file():
            result.warnings.append(f"hook script missing: {hook.script}")
            continue
        if hook.sudo and not allow_sudo:
            result.warnings.append(f"skipped sudo hook {hook.script} (--no-sudo)")
            continue
        cmd = (["sudo", "bash", str(script)] if hook.sudo else ["bash", str(script)])
        print(ansi.bullet(f"hook[{event}] {hook.script}" + (" (sudo)" if hook.sudo else "")))
        proc = subprocess.run(cmd, cwd=theme.path)
        if proc.returncode == 0:
            result.hooks_run.append(hook.script)
            # Remember it ran so its restore script can be invoked on `restore`.
            if baseline is not None and hook.restore:
                baseline.record_hook(str(theme.path), hook.restore, hook.sudo)
        elif hook.optional:
            result.warnings.append(f"optional hook failed: {hook.script}")
        else:
            result.warnings.append(f"hook FAILED: {hook.script} (exit {proc.returncode})")


# ---------------------------------------------------------------------- apply ---
def check_requires(theme: Theme) -> list[str]:
    """Best-effort dependency check (warn only; never blocks an apply)."""
    missing: list[str] = []
    for pkg in theme.requires.packages:
        if shutil.which(pkg) is None:
            missing.append(f"package/binary not found: {pkg}")
    if theme.requires.fonts and shutil.which("fc-list"):
        installed = subprocess.run(
            ["fc-list"], capture_output=True, text=True
        ).stdout.lower()
        for font in theme.requires.fonts:
            if font.lower() not in installed:
                missing.append(f"font not found: {font}")
    return missing


def apply(
    theme: Theme,
    only: set[str] | None = None,
    dry_run: bool = False,
    do_hooks: bool = True,
    allow_sudo: bool = True,
) -> ApplyResult:
    result = ApplyResult()

    for warn in check_requires(theme):
        result.warnings.append(warn)

    if dry_run:
        return result  # caller prints compute_diffs(); nothing is written

    ensure_state_dirs()
    baseline = Baseline().load()

    if do_hooks:
        _run_hooks(theme, "pre", only, allow_sudo, result, baseline)

    for op in iter_file_ops(theme, only):
        if not op.src.is_file():
            result.warnings.append(f"missing source: {op.install.src}")
            continue
        baseline.record_file(op.dest)
        op.dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(op.src, op.dest)
        if op.install.mode:
            os.chmod(op.dest, int(op.install.mode, 8))
        result.applied_files += 1

    for rs in resolved_settings(theme, only):
        if not backend_available(rs.backend):
            result.warnings.append(f"{rs.backend} not available; skipped {rs.label}")
            continue
        baseline.record_setting(rs)
        if rs.apply():
            result.applied_settings += 1
        else:
            result.warnings.append(f"failed to set {rs.label}")

    if do_hooks:
        _run_hooks(theme, "post", only, allow_sudo, result, baseline)

    baseline.save()
    write_current(theme.meta.name)
    return result


# -------------------------------------------------------------------- restore ---
def restore(wipe: bool = False, allow_sudo: bool = True) -> tuple[list[str], list[str]]:
    """Revert to the pristine baseline. Returns (log lines, warnings)."""
    baseline = Baseline().load()
    warnings: list[str] = []
    if baseline.is_empty and not baseline.hooks:
        return [], ["nothing to restore — no baseline recorded"]

    # Undo only the install hooks that actually ran (recorded in the baseline).
    for rec in baseline.hooks:
        script = (Path(rec["dir"]) / rec["restore"]).resolve()
        if not script.is_file():
            warnings.append(f"restore hook missing: {rec['restore']}")
            continue
        if rec["sudo"] and not allow_sudo:
            warnings.append(f"skipped sudo restore hook {rec['restore']} (--no-sudo)")
            continue
        cmd = (["sudo", "bash", str(script)] if rec["sudo"] else ["bash", str(script)])
        print(ansi.bullet(f"restore hook {rec['restore']}"))
        subprocess.run(cmd, cwd=rec["dir"])

    log = baseline.restore_files()
    log += baseline.restore_settings()
    clear_current()
    if wipe:
        baseline.wipe()
    return log, warnings
