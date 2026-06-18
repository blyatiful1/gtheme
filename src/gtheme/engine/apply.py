"""Apply / restore / diff — the core engine.

``apply`` installs a theme's files and settings (snapshotting the pristine
state first) and runs its hooks. ``restore`` walks the baseline back to the
pre-gtheme state. ``compute_diffs`` powers both ``--dry-run`` and ``diff``.

Safety model
------------
* Every hook is routed through a :data:`HookGate` consent callback. ``--no-hooks``
  / ``--no-sudo`` short-circuit first; with no gate, sudo or untrusted hooks are
  refused unless ``assume_yes``.
* Every file op is confined to ``$HOME`` (dest) and the theme dir (src) before a
  single byte is written, so a path escape aborts with zero side effects.
* The baseline is persisted atomically and incrementally, so a crash mid-apply
  still leaves a consistent, restorable state.
"""

from __future__ import annotations

import difflib
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .. import ansi, paths, settings
from ..backup import (
    Baseline,
    clear_current,
    read_current,
    read_ledger,
    write_current,
    write_ledger,
)
from ..errors import ThemeSecurityError
from ..manifest import FileInstall, Theme
from ..settings import ResolvedSetting, backend_available


# given {"event","script","sudo","untrusted","preview","theme"} -> True to run.
HookGate = Callable[[dict], bool]


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
    failed: bool = False
    notes: list[str] = field(default_factory=list)


def _selected(component: str, only: set[str] | None) -> bool:
    return only is None or component in only


# ---------------------------------------------------------------- file walking ---
def iter_file_ops(theme: Theme, only: set[str] | None = None) -> list[FileOp]:
    """Expand [[files]] entries into concrete (src, dest) file operations.

    Sources are confined to the theme directory and destinations to ``$HOME``
    (``DEST_ROOT``); a path escape raises :class:`ThemeSecurityError`. A ``src``
    that resolves to a directory installs every file beneath it to the matching
    path under ``dest`` (descendants are confined too — symlinks pointing out of
    the theme dir are skipped).
    """
    ops: list[FileOp] = []
    for fi in theme.files:
        if not _selected(fi.component, only):
            continue
        src = paths.confine_src(fi.src, theme.path)
        dest = paths.confine_dest(fi.dest)
        if src.is_dir():
            theme_root = theme.path.resolve()
            for sub in sorted(src.rglob("*")):
                if not sub.is_file():
                    continue
                # Confine each descendant: never follow a symlink out of the tree.
                resolved = sub.resolve()
                if not resolved.is_relative_to(theme_root):
                    continue
                ops.append(FileOp(fi, sub, dest / sub.relative_to(src)))
        else:
            ops.append(FileOp(fi, src, dest))
    return ops


def resolved_settings(theme: Theme, only: set[str] | None = None) -> list[ResolvedSetting]:
    return [ResolvedSetting(s) for s in theme.settings if _selected(s.component, only)]


# ----------------------------------------------------------------------- diff ---
def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, ValueError):
        return None
    except OSError:
        return None


def _rendered_src_bytes(op: FileOp) -> bytes | None:
    """Bytes that would actually be written for ``op`` (templated if requested)."""
    if getattr(op.install, "template", False):
        text = _read_text(op.src)
        if text is None:
            return None
        return settings.resolve(text).encode("utf-8")
    try:
        return op.src.read_bytes()
    except OSError:
        return None


def compute_diffs(theme: Theme, only: set[str] | None = None) -> list[Diff]:
    diffs: list[Diff] = []
    for op in iter_file_ops(theme, only):
        if not op.src.is_file():
            diffs.append(Diff("file", str(op.dest), op.install.component, "missing-src"))
            continue
        src_b = _rendered_src_bytes(op)
        if src_b is None:
            diffs.append(Diff("file", str(op.dest), op.install.component, "missing-src"))
            continue
        if not op.dest.exists():
            diffs.append(Diff("file", str(op.dest), op.install.component, "new"))
            continue
        dst_b = op.dest.read_bytes()
        if src_b == dst_b:
            diffs.append(Diff("file", str(op.dest), op.install.component, "unchanged"))
            continue
        src_t = src_b.decode("utf-8", "replace") if getattr(op.install, "template", False) else _read_text(op.src)
        dst_t = _read_text(op.dest)
        if src_t is None or dst_t is None or b"\x00" in src_b or b"\x00" in dst_b:
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
        if "{{" in rs.key:
            diffs.append(
                Diff("setting", rs.label, rs.component, "missing-src",
                     "unresolved placeholder; will be skipped")
            )
            continue
        current = rs.get_current()
        status = "unchanged" if current == rs.value else ("changed" if current is not None else "new")
        detail = f"{current} -> {rs.value}" if status != "unchanged" else ""
        diffs.append(Diff("setting", rs.label, rs.component, status, detail))
    return diffs


# ---------------------------------------------------------------------- hooks ---
def _preview(script: Path, lines: int = 20) -> str:
    text = _read_text(script)
    if text is None:
        return "(unreadable / binary script)"
    head = text.splitlines()[:lines]
    return "\n".join(head)


def _consent(
    gate: "HookGate | None",
    info: dict,
    assume_yes: bool,
    result: ApplyResult,
) -> bool:
    """Decide whether a hook may run. Shared by apply and restore."""
    if assume_yes:
        return True
    if gate is not None:
        return bool(gate(info))
    # Default-deny: refuse sudo or untrusted hooks when running non-interactively.
    if info["sudo"] or info["untrusted"]:
        kind = "sudo" if info["sudo"] else "untrusted"
        result.warnings.append(
            f"refused {kind} hook {info['script']!r} (no consent); "
            f"re-run interactively or pass --yes to approve"
        )
        return False
    # Non-sudo hook from a trusted (local/bundled) theme: preserve behaviour.
    return True


def _run_hooks(
    theme: Theme,
    event: str,
    only: set[str] | None,
    allow_sudo: bool,
    result: ApplyResult,
    baseline: "Baseline | None" = None,
    hook_gate: "HookGate | None" = None,
    assume_yes: bool = False,
) -> None:
    untrusted = paths.theme_is_untrusted(theme.path)
    for hook in theme.hooks:
        if hook.event != event or not _selected(hook.component, only):
            continue
        script = paths.confine_src(hook.script, theme.path)
        if not script.is_file():
            result.warnings.append(f"hook script missing: {hook.script}")
            if not hook.optional:
                result.failed = True
            continue
        if hook.sudo and not allow_sudo:
            result.warnings.append(f"skipped sudo hook {hook.script} (--no-sudo)")
            continue
        info = {
            "event": event,
            "script": str(script),
            "sudo": hook.sudo,
            "untrusted": untrusted,
            "preview": _preview(script),
            "theme": theme.meta.name,
        }
        if not _consent(hook_gate, info, assume_yes, result):
            if not hook.optional:
                result.failed = True
            continue
        cmd = (["sudo", "bash", str(script)] if hook.sudo else ["bash", str(script)])
        print(ansi.bullet(f"hook[{event}] {hook.script}" + (" (sudo)" if hook.sudo else "")))
        proc = subprocess.run(cmd, cwd=theme.path)
        if proc.returncode == 0:
            result.hooks_run.append(hook.script)
            # Remember it ran so its restore script can be invoked on `restore`.
            if baseline is not None and hook.restore:
                baseline.record_hook(
                    str(theme.path), hook.restore, hook.sudo,
                    hook.component, theme.meta.name,
                )
        elif hook.optional:
            result.warnings.append(f"optional hook failed: {hook.script}")
        else:
            result.warnings.append(f"hook FAILED: {hook.script} (exit {proc.returncode})")
            result.failed = True


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


def _is_wayland() -> bool:
    return (
        os.environ.get("XDG_SESSION_TYPE") == "wayland"
        or bool(os.environ.get("WAYLAND_DISPLAY"))
    )


def _dryrun_notes(theme: Theme, only: set[str] | None, result: ApplyResult) -> None:
    """Surface things --dry-run would otherwise hide: hooks, out-of-home dests,
    unresolved placeholders."""
    untrusted = paths.theme_is_untrusted(theme.path)
    home = paths.DEST_ROOT.resolve()
    for hook in theme.hooks:
        if not _selected(hook.component, only):
            continue
        flags = []
        if hook.sudo:
            flags.append("sudo")
        if untrusted:
            flags.append("untrusted")
        if hook.optional:
            flags.append("optional")
        suffix = (" [" + ", ".join(flags) + "]") if flags else ""
        result.notes.append(f"would run hook[{hook.event}] {hook.script}{suffix}")
    for op in iter_file_ops(theme, only):
        try:
            outside = not op.dest.resolve().is_relative_to(home)
        except OSError:
            outside = False
        if outside:
            result.notes.append(f"destination outside $HOME: {op.dest}")
    for rs in resolved_settings(theme, only):
        if "{{" in rs.key:
            result.notes.append(f"unresolved placeholder; setting skipped: {rs.label}")


def _write_file(op: FileOp) -> None:
    """Write ``op.src`` to ``op.dest`` (templated if requested), never through a link."""
    op.dest.parent.mkdir(parents=True, exist_ok=True)
    # If the dest is a symlink, drop the link itself and write a real file in its
    # place — never write through it to the link target.
    if op.dest.is_symlink():
        op.dest.unlink()
    if getattr(op.install, "template", False):
        text = _read_text(op.src)
        rendered = settings.resolve(text if text is not None else "")
        op.dest.write_text(rendered, encoding="utf-8")
    else:
        shutil.copy2(op.src, op.dest)
    if op.install.mode:
        # Mask off setuid/setgid/sticky; only honour the permission bits.
        os.chmod(op.dest, int(op.install.mode, 8) & 0o777)


def _switch_cleanup(
    theme: Theme,
    only: set[str] | None,
    ops: list[FileOp],
    baseline: Baseline,
    result: ApplyResult,
) -> None:
    """Revert items the outgoing theme owned that the incoming one does not manage.

    Strictly additive and conservative: reverts each orphaned item to the
    pristine baseline (never mutating baseline originals), then forgets it. If
    anything is uncertain we leave the item in place rather than revert wrongly.
    """
    prev = read_current()
    if not prev or prev == theme.meta.name:
        return
    ledger = read_ledger()
    prev_owned = ledger.get(prev)
    if not isinstance(prev_owned, dict):
        return

    # What the incoming apply manages (so we don't revert shared items).
    incoming_files = {str(op.dest) for op in ops}
    incoming_settings = {
        f"{rs.backend}:{rs.key}" for rs in resolved_settings(theme, only) if "{{" not in rs.key
    }

    orphan_files = [f for f in prev_owned.get("files", []) if f not in incoming_files]
    orphan_settings = [s for s in prev_owned.get("settings", []) if s not in incoming_settings]

    if orphan_files:
        # Restore just these dests from the pristine baseline, then forget them.
        rlog, rwarn = _restore_specific_files(baseline, orphan_files)
        for line in rlog:
            result.notes.append(f"switch-cleanup: {line}")
        result.warnings.extend(rwarn)
        baseline.forget_files([k for k in orphan_files if k in baseline.files])

    if orphan_settings:
        rlog, rwarn = _restore_specific_settings(baseline, orphan_settings)
        for line in rlog:
            result.notes.append(f"switch-cleanup: {line}")
        result.warnings.extend(rwarn)
        baseline.forget_settings([k for k in orphan_settings if k in baseline.settings])

    # Drop the outgoing theme from the ledger; the incoming theme is recorded later.
    ledger.pop(prev, None)
    write_ledger(ledger)


def _restore_specific_files(baseline: Baseline, keys: list[str]) -> tuple[list[str], list[str]]:
    """Restore only the given file dests from the pristine baseline."""
    saved = baseline.files
    baseline.files = {k: saved[k] for k in keys if k in saved}
    try:
        log, warns = baseline.restore_files()
    finally:
        baseline.files = saved
    return log, warns


def _restore_specific_settings(baseline: Baseline, keys: list[str]) -> tuple[list[str], list[str]]:
    """Restore only the given setting keys from the pristine baseline."""
    saved = baseline.settings
    baseline.settings = {k: saved[k] for k in keys if k in saved}
    try:
        log, warns = baseline.restore_settings()
    finally:
        baseline.settings = saved
    return log, warns


def apply(
    theme: Theme,
    only: set[str] | None = None,
    dry_run: bool = False,
    do_hooks: bool = True,
    allow_sudo: bool = True,
    hook_gate: "HookGate | None" = None,
    assume_yes: bool = False,
) -> ApplyResult:
    result = ApplyResult()

    for warn in check_requires(theme):
        result.warnings.append(warn)

    if dry_run:
        _dryrun_notes(theme, only, result)
        return result  # caller prints compute_diffs(); nothing is written

    paths.ensure_state_dirs()
    baseline = Baseline().load()
    for w in baseline.warnings:
        result.warnings.append(w)

    # PRE-FLIGHT: resolve + confine every file op before writing a single byte.
    # A ThemeSecurityError here aborts with zero side effects (propagates to CLI).
    ops = iter_file_ops(theme, only)

    # Switch-cleanup: revert orphans from the previously-applied theme.
    try:
        _switch_cleanup(theme, only, ops, baseline, result)
    except Exception as exc:  # noqa: BLE001 — cleanup must never abort an apply
        result.warnings.append(f"switch-cleanup skipped: {exc}")

    owned_files: list[str] = []
    owned_settings: list[str] = []

    # Wrap the mutation body so a mid-apply exception still leaves a consistent,
    # restorable baseline. Each record persists itself atomically immediately
    # (see backup.record_*), so re-raising here keeps the store consistent.
    try:
        if do_hooks:
            _run_hooks(theme, "pre", only, allow_sudo, result, baseline, hook_gate, assume_yes)

        for op in ops:
            if not op.src.is_file():
                result.warnings.append(f"missing source: {op.install.src}")
                result.failed = True
                continue
            try:
                baseline.record_file(op.dest, op.install.component, theme.meta.name)
                _write_file(op)
            except OSError as exc:
                result.warnings.append(f"failed to write {op.dest}: {exc}")
                result.failed = True
                continue
            owned_files.append(str(op.dest))
            result.applied_files += 1

        for rs in resolved_settings(theme, only):
            if "{{" in rs.key:
                # Unresolved placeholder — skip and do NOT record a junk key.
                result.warnings.append(f"skipped setting with unresolved placeholder: {rs.label}")
                continue
            if not backend_available(rs.backend):
                result.warnings.append(f"{rs.backend} not available; skipped {rs.label}")
                continue
            baseline.record_setting(rs, rs.component, theme.meta.name)
            owned_settings.append(f"{rs.backend}:{rs.key}")
            if rs.apply():
                result.applied_settings += 1
            else:
                result.warnings.append(f"failed to set {rs.label}")
                result.failed = True

        if do_hooks:
            _run_hooks(theme, "post", only, allow_sudo, result, baseline, hook_gate, assume_yes)
    except BaseException:
        # The incremental store is already consistent; flush the final indexes.
        baseline.save()
        raise

    baseline.save()

    # Record this theme's active ownership for future switch-cleanup.
    ledger = read_ledger()
    existing = ledger.get(theme.meta.name) if isinstance(ledger.get(theme.meta.name), dict) else {}
    merged_files = sorted(set(existing.get("files", []) if isinstance(existing, dict) else []) | set(owned_files))
    merged_settings = sorted(set(existing.get("settings", []) if isinstance(existing, dict) else []) | set(owned_settings))
    ledger[theme.meta.name] = {"files": merged_files, "settings": merged_settings}
    write_ledger(ledger)

    write_current(theme.meta.name)

    # Shell-reload guidance (esp. Wayland, where Shell can't reload live).
    if _is_wayland():
        result.notes.append(
            "Wayland session detected: log out and back in to finish "
            "GNOME Shell / extension / wallpaper changes."
        )
    else:
        result.notes.append(
            "Restart GNOME Shell (Alt+F2, r) or log out to finish "
            "Shell / extension changes."
        )

    return result


# -------------------------------------------------------------------- restore ---
def restore(
    only: set[str] | None = None,
    wipe: bool = False,
    allow_sudo: bool = True,
    hook_gate: "HookGate | None" = None,
    assume_yes: bool = False,
) -> tuple[list[str], list[str]]:
    """Revert to the pristine baseline. Returns (log lines, warnings)."""
    baseline = Baseline().load()
    warnings: list[str] = []
    warnings.extend(baseline.warnings)
    if baseline.is_empty and not baseline.hooks:
        return [], warnings + ["nothing to restore — no baseline recorded"]

    # A throwaway result just to reuse the consent machinery for hook gating.
    gate_result = ApplyResult()

    # Undo only the install hooks that actually ran (recorded in the baseline),
    # gated exactly like apply hooks.
    for rec in baseline.hooks:
        if only is not None and rec.get("component", "") not in only:
            continue
        theme_dir = Path(rec["dir"])
        # Confine the restore script to the theme dir, exactly as apply confines
        # hook.script — a recorded "../" path must not run code outside the theme.
        try:
            script = paths.confine_src(rec["restore"], theme_dir)
        except ThemeSecurityError:
            warnings.append(f"refusing restore hook outside theme dir: {rec['restore']}")
            continue
        if not script.is_file():
            warnings.append(f"restore hook missing: {rec['restore']}")
            continue
        if rec["sudo"] and not allow_sudo:
            warnings.append(f"skipped sudo restore hook {rec['restore']} (--no-sudo)")
            continue
        info = {
            "event": "restore",
            "script": str(script),
            "sudo": rec["sudo"],
            "untrusted": paths.theme_is_untrusted(theme_dir),
            "preview": _preview(script),
            "theme": rec.get("theme", ""),
        }
        if not _consent(hook_gate, info, assume_yes, gate_result):
            continue
        cmd = (["sudo", "bash", str(script)] if rec["sudo"] else ["bash", str(script)])
        print(ansi.bullet(f"restore hook {rec['restore']}"))
        proc = subprocess.run(cmd, cwd=rec["dir"])
        if proc.returncode != 0:
            warnings.append(f"restore hook FAILED: {rec['restore']} (exit {proc.returncode})")
    warnings.extend(gate_result.warnings)

    flog, fwarn = baseline.restore_files(only)
    slog, swarn = baseline.restore_settings(only)
    log = flog + slog
    warnings.extend(fwarn)
    warnings.extend(swarn)

    if only is None:
        clear_current()
        # Full restore returns to pristine: drop the ownership ledger too.
        write_ledger({})
        if wipe:
            baseline.wipe()

    return log, warnings
