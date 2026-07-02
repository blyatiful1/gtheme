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

import ast
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
    process_lock,
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
        try:
            dst_b = op.dest.read_bytes()
        except OSError as exc:
            diffs.append(Diff("file", str(op.dest), op.install.component, "changed",
                              f"destination unreadable: {exc}"))
            continue
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
        if not _key_ok(rs):
            # Mirror apply's _key_ok skip so dry-run/diff never promise a write
            # ('//' dconf path) that the real apply will refuse.
            diffs.append(
                Diff("setting", rs.label, rs.component, "missing-src",
                     "invalid dconf path ('//'); will be skipped")
            )
            continue
        current = rs.get_current()
        if settings.values_equal(current, rs.value):
            status = "unchanged"
        else:
            status = "changed" if current is not None else "new"
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
        try:
            proc = subprocess.run(cmd, cwd=theme.path)
        except (FileNotFoundError, PermissionError) as exc:
            # Missing bash/sudo etc. must not crash apply with a raw traceback.
            result.warnings.append(f"cannot run hook {hook.script}: {exc}")
            if not hook.optional:
                result.failed = True
            continue
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
def _installed_extensions() -> set[str]:
    """UUIDs of installed GNOME Shell extensions (dir names + CLI if present)."""
    uuids: set[str] = set()
    for root in (
        paths.XDG_DATA_HOME / "gnome-shell" / "extensions",
        Path("/usr/share/gnome-shell/extensions"),
    ):
        try:
            uuids.update(p.name for p in root.iterdir() if p.is_dir())
        except OSError:
            pass
    if shutil.which("gnome-extensions"):
        try:
            out = subprocess.run(
                ["gnome-extensions", "list"], capture_output=True, text=True, timeout=10
            ).stdout
            uuids.update(out.split())
        except (OSError, subprocess.TimeoutExpired):
            pass
    return uuids


def check_requires(theme: Theme) -> list[str]:
    """Best-effort dependency check (warn only; never blocks an apply)."""
    from ..validate import package_installed

    missing: list[str] = []
    for pkg in theme.requires.packages:
        if not package_installed(pkg):
            missing.append(f"package may be missing: {pkg}")
    if theme.requires.extensions:
        installed = _installed_extensions()
        for ext in theme.requires.extensions:
            if ext not in installed:
                missing.append(f"gnome-shell extension not installed: {ext}")
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


def _has_session_bus() -> bool:
    """True if a D-Bus session bus looks reachable (gsettings/dconf need one)."""
    if os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        return True
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    return bool(runtime and (Path(runtime) / "bus").exists())


def _key_ok(rs: ResolvedSetting) -> bool:
    """False for keys apply must skip (and never record as planned/owned):
    unresolved ``{{ }}`` tokens, or a dconf path with ``//`` — an empty
    placeholder collapsed (e.g. unset Ptyxis profile); dconf rejects it."""
    if "{{" in rs.key:
        return False
    return not (rs.backend == "dconf" and "//" in rs.key)


def _merge_extension_lists(current: str | None, wanted: str) -> str | None:
    """Union of the user's enabled-extensions and the theme's (user's first).

    GVariant text for a string array is Python-literal compatible, and repr()
    of a list of str is valid GVariant text again. Parse defensively: return
    None on any surprise (caller falls back to a plain replace).
    """
    try:
        cur = ast.literal_eval(current) if current else []
        new = ast.literal_eval(wanted)
    except (ValueError, SyntaxError):
        return None  # e.g. gsettings' "@as []" for an empty array
    if not (isinstance(cur, list) and isinstance(new, list)):
        return None
    if not all(isinstance(x, str) for x in cur + new):
        return None
    merged = cur + [x for x in new if x not in cur]
    # A bare [] has no inferable GVariant type; never worth writing anyway.
    return repr(merged) if merged else None


def _write_ledger_entry(name: str, files, settings) -> None:
    """Set the ownership-ledger entry for ``name`` (sorted, de-duplicated)."""
    ledger = read_ledger()
    ledger[name] = {"files": sorted(set(files)), "settings": sorted(set(settings))}
    write_ledger(ledger)


def _drop_ledger_entry(name: str) -> None:
    ledger = read_ledger()
    if name in ledger:
        ledger.pop(name)
        write_ledger(ledger)


def _run_recorded_hooks(
    records: list[dict],
    allow_sudo: bool,
    hook_gate: "HookGate | None",
    assume_yes: bool,
) -> tuple[list[str], list[str], list[dict]]:
    """Run recorded restore hooks (gated like apply). Returns (log, warnings, ran).

    ``ran`` is the subset of records whose restore script exited 0, so the caller
    can ``forget_hooks`` them. Shared by ``restore`` and ``remove``.
    """
    log: list[str] = []
    warnings: list[str] = []
    ran: list[dict] = []
    gate_result = ApplyResult()
    for rec in records:
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
        try:
            proc = subprocess.run(cmd, cwd=rec["dir"])
        except (FileNotFoundError, PermissionError) as exc:
            warnings.append(f"cannot run restore hook {rec['restore']}: {exc}")
            continue
        if proc.returncode == 0:
            log.append(f"ran restore hook {rec['restore']}")
            ran.append(rec)
        else:
            warnings.append(f"restore hook FAILED: {rec['restore']} (exit {proc.returncode})")
    warnings.extend(gate_result.warnings)
    return log, warnings, ran


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
        elif not _key_ok(rs):
            result.notes.append(f"invalid dconf path ('//'); setting skipped: {rs.label}")


def _atomic_write_bytes(dest: Path, data: bytes, mode: int | None) -> None:
    """Write ``data`` to ``dest`` atomically (tmp + fsync + os.replace).

    A SIGKILL or ENOSPC mid-write can never leave a half-written/truncated dest:
    the prior file stays intact until the rename succeeds. Replaces a symlink at
    ``dest`` rather than writing through it to the link target.
    """
    tmp = dest.with_name(dest.name + ".gtheme-tmp")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        if dest.is_symlink():
            dest.unlink()
        os.replace(tmp, dest)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _write_file(op: FileOp) -> None:
    """Write ``op.src`` to ``op.dest`` (templated if requested), never through a link."""
    dest = op.dest
    # Refuse an existing-directory dest: a plain copy would silently create
    # dir/<basename> — the wrong inode for chmod and untracked by the baseline.
    # (A symlink-to-dir is fine: it is replaced as a link below.)
    if dest.is_dir() and not dest.is_symlink():
        raise IsADirectoryError(f"destination is a directory, not a file: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)

    if getattr(op.install, "template", False):
        text = _read_text(op.src)
        if text is None:
            # template=true on a binary/non-UTF8 src must NOT silently truncate
            # the live file to 0 bytes; fail loudly so apply records it.
            raise ValueError(f"cannot template binary/non-UTF8 source: {op.install.src}")
        data = settings.resolve(text).encode("utf-8")
    else:
        data = op.src.read_bytes()

    if op.install.mode:
        # Mask off setuid/setgid/sticky; only honour the permission bits.
        mode: int | None = int(op.install.mode, 8) & 0o777
    else:
        # Preserve the source's permission bits (as shutil.copy2 used to).
        try:
            mode = op.src.stat().st_mode & 0o777
        except OSError:
            mode = None
    _atomic_write_bytes(dest, data, mode)


def _switch_cleanup(
    theme: Theme,
    ops: list[FileOp],
    baseline: Baseline,
    result: ApplyResult,
) -> None:
    """Revert items outgoing themes owned that the incoming one does not manage.

    Only runs on a FULL apply (a --only overlay is not a switch — see apply()).
    Walks every ledger entry, not just ``current``, so components overlaid from
    a third theme are cleaned too. Strictly conservative: reverts each orphaned
    item to the pristine baseline (never mutating baseline originals), then
    forgets ONLY the items that actually reverted — a failed or dead revert
    keeps its record (and blob) so `gtheme restore` can still recover it.
    """
    ledger = read_ledger()
    outgoing = [
        n for n, owned in ledger.items()
        if n != theme.meta.name and isinstance(owned, dict)
    ]
    if not outgoing:
        return

    # What the incoming apply manages (so we don't revert shared items).
    incoming_files = {str(op.dest) for op in ops}
    incoming_settings = {
        f"{rs.backend}:{rs.key}" for rs in resolved_settings(theme, None) if _key_ok(rs)
    }

    kept = 0
    for prev in outgoing:
        prev_owned = ledger[prev]
        orphan_files = [f for f in prev_owned.get("files", []) if f not in incoming_files]
        orphan_settings = [s for s in prev_owned.get("settings", []) if s not in incoming_settings]

        if orphan_files:
            # Restore just these dests from the pristine baseline, then forget
            # what reverted; failures/dead stay restorable via `gtheme restore`.
            rlog, rwarn, done, _dead = _restore_specific_files(baseline, orphan_files)
            for line in rlog:
                result.notes.append(f"switch-cleanup: {line}")
            result.warnings.extend(rwarn)
            baseline.forget_files(done)
            kept += sum(1 for k in orphan_files if k in baseline.files)

        if orphan_settings:
            rlog, rwarn, done, _dead = _restore_specific_settings(baseline, orphan_settings)
            for line in rlog:
                result.notes.append(f"switch-cleanup: {line}")
            result.warnings.extend(rwarn)
            baseline.forget_settings(done)
            kept += sum(1 for k in orphan_settings if k in baseline.settings)

        # Drop the outgoing theme from the ledger; the incoming one is recorded later.
        ledger.pop(prev, None)
    write_ledger(ledger)
    if kept:
        result.warnings.append(
            f"{kept} item(s) from the previous theme could not be reverted; "
            f"kept in the baseline — `gtheme restore` can still recover them"
        )


def _restore_specific_files(
    baseline: Baseline, keys: list[str]
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Restore only the given file dests from the pristine baseline."""
    saved = baseline.files
    baseline.files = {k: saved[k] for k in keys if k in saved}
    try:
        log, warns, done, dead = baseline.restore_files()
    finally:
        baseline.files = saved
    return log, warns, done, dead


def _restore_specific_settings(
    baseline: Baseline, keys: list[str]
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Restore only the given setting keys from the pristine baseline."""
    saved = baseline.settings
    baseline.settings = {k: saved[k] for k in keys if k in saved}
    try:
        log, warns, done, dead = baseline.restore_settings()
    finally:
        baseline.settings = saved
    return log, warns, done, dead


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

    # L1: everything below mutates shared state — one gtheme at a time.
    with process_lock():
        return _apply_locked(theme, only, result, do_hooks, allow_sudo, hook_gate, assume_yes)


def _apply_locked(
    theme: Theme,
    only: set[str] | None,
    result: ApplyResult,
    do_hooks: bool,
    allow_sudo: bool,
    hook_gate: "HookGate | None",
    assume_yes: bool,
) -> ApplyResult:
    paths.ensure_state_dirs()
    baseline = Baseline().load()
    for w in baseline.warnings:
        result.warnings.append(w)

    # PRE-FLIGHT: resolve + confine every file op before writing a single byte.
    # A ThemeSecurityError here aborts with zero side effects (propagates to CLI).
    ops = iter_file_ops(theme, only)

    # Switch-cleanup: revert orphans from previously-applied themes. A --only
    # overlay is not a switch: it must never strip the rest of the desktop.
    if only is None:
        try:
            _switch_cleanup(theme, ops, baseline, result)
        except Exception as exc:  # noqa: BLE001 — cleanup must never abort an apply
            result.warnings.append(f"switch-cleanup skipped: {exc}")

    owned_files: list[str] = []
    owned_settings: list[str] = []

    # Ownership recorded before this apply (so re-applying with --only accumulates).
    _prior = read_ledger().get(theme.meta.name)
    prior_files = set(_prior.get("files", [])) if isinstance(_prior, dict) else set()
    prior_settings = set(_prior.get("settings", [])) if isinstance(_prior, dict) else set()
    prev_current = read_current()  # pre-apply current, for the AS4 rollback

    # What this apply intends to own (used for the crash-safe early ledger write).
    planned_files = [str(op.dest) for op in ops]
    setting_list = resolved_settings(theme, only)
    planned_settings = [f"{rs.backend}:{rs.key}" for rs in setting_list if _key_ok(rs)]

    # AS5: if a settings-bearing theme is applied with no reachable session bus,
    # skip the settings phase wholesale (one note) instead of flooding failures.
    skip_settings_no_bus = bool(setting_list) and not _has_session_bus()
    if skip_settings_no_bus:
        result.notes.append(
            "no GNOME session bus detected; desktop settings were skipped "
            "(run from a graphical GNOME session for them to take effect)"
        )
    settings_selected = 0
    settings_backend_skipped = 0

    # Wrap the mutation body so a mid-apply exception still leaves a consistent,
    # restorable baseline. Each record persists itself atomically immediately
    # (see backup.record_*), so re-raising here keeps the store consistent.
    try:
        if do_hooks:
            _run_hooks(theme, "pre", only, allow_sudo, result, baseline, hook_gate, assume_yes)
            # H2: a failed/refused REQUIRED pre-hook is a precondition — if it did
            # not run, do NOT apply files/settings (leave the theme un-applied).
            if result.failed:
                result.notes.append("a required pre-hook did not run; theme was NOT applied")
                baseline.save()
                return result

        # R4: record planned ownership + current BEFORE mutating, so an interrupt
        # mid-apply still leaves current/ledger consistent with what is on disk.
        _write_ledger_entry(theme.meta.name, prior_files | set(planned_files),
                            prior_settings | set(planned_settings))
        write_current(theme.meta.name)

        for op in ops:
            if not op.src.is_file():
                result.warnings.append(f"missing source: {op.install.src}")
                result.failed = True
                continue
            try:
                if not baseline.record_file(op.dest, op.install.component, theme.meta.name):
                    # F1: FIFO/socket/device at dest — unsnapshotable; leave it be.
                    result.warnings.append(f"cannot snapshot special file {op.dest}; skipped")
                    continue
                _write_file(op)
            except (OSError, ValueError) as exc:
                # OSError: dest dir/perm/disk. ValueError: e.g. template on binary.
                result.warnings.append(f"failed to write {op.dest}: {exc}")
                result.failed = True
                continue
            owned_files.append(str(op.dest))
            result.applied_files += 1

        if not skip_settings_no_bus:
            for rs in setting_list:
                if "{{" in rs.key:
                    # Unresolved placeholder — skip and do NOT record a junk key.
                    result.warnings.append(f"skipped setting with unresolved placeholder: {rs.label}")
                    result.notes.append(
                        "an unresolved {{ }} token left a setting unset "
                        "(e.g. Ptyxis not detected); other settings still applied"
                    )
                    continue
                if not _key_ok(rs):
                    # An empty placeholder collapsed to '//' — dconf rejects it.
                    result.warnings.append(f"skipped setting with invalid dconf path: {rs.label}")
                    continue
                settings_selected += 1
                if not backend_available(rs.backend):
                    result.warnings.append(f"{rs.backend} not available; skipped {rs.label}")
                    settings_backend_skipped += 1
                    continue
                # Snapshot pristine BEFORE apply; forget it if apply fails so we
                # never keep an un-restorable record for a key we never changed.
                key = f"{rs.backend}:{rs.key}"
                newly = key not in baseline.settings
                baseline.record_setting(rs, rs.component, theme.meta.name)
                # X1: enabled-extensions is a shared list — merge the theme's in
                # instead of clobbering the user's (their dock/extensions would
                # silently vanish). The baseline still restores the exact old value.
                if rs.backend == "gsettings" and rs.schema == "org.gnome.shell" \
                        and rs.gkey == "enabled-extensions":
                    merged = _merge_extension_lists(rs.get_current(), rs.value)
                    if merged is not None and merged != rs.value:
                        rs.value = merged
                        result.notes.append(
                            "merged theme extensions into enabled-extensions (yours kept)"
                        )
                if rs.apply():
                    owned_settings.append(key)
                    result.applied_settings += 1
                else:
                    err = (rs.error or "").lower()
                    if "no such schema" in err or "no such key" in err:
                        # AS8: key/schema absent (optional app, older GNOME) — a
                        # per-setting skip, never a whole-apply failure.
                        result.warnings.append(f"skipped {rs.label}: not on this system")
                        if newly:
                            baseline.forget_settings([key])
                        continue
                    detail = f": {rs.error}" if rs.error else ""
                    result.warnings.append(f"failed to set {rs.label}{detail}")
                    result.failed = True
                    if newly:
                        baseline.forget_settings([key])

        if do_hooks:
            _run_hooks(theme, "post", only, allow_sudo, result, baseline, hook_gate, assume_yes)
    except BaseException:
        # The incremental store is already consistent; flush the final indexes.
        baseline.save()
        raise

    baseline.save()

    # AS4: a settings-only apply where every setting was skipped for a missing
    # backend (or the whole settings phase was skipped for no bus) and nothing
    # else applied is not a real apply — roll back current/ledger and fail.
    nothing_applied = (
        result.applied_files == 0 and result.applied_settings == 0 and not result.hooks_run
    )
    all_settings_unbacked = settings_selected > 0 and settings_backend_skipped == settings_selected
    if nothing_applied and (all_settings_unbacked or skip_settings_no_bus):
        result.failed = True
        # AS4: roll back the R4 early write — but never destroy ownership this
        # theme accumulated in EARLIER applies (it is still on disk).
        if prior_files or prior_settings:
            _write_ledger_entry(theme.meta.name, prior_files, prior_settings)
        else:
            _drop_ledger_entry(theme.meta.name)
        if only is not None and prev_current and prev_current != theme.meta.name:
            # A --only overlay ran no switch-cleanup: prev theme is still applied.
            write_current(prev_current)
        elif not (prior_files or prior_settings):
            clear_current()
        return result

    # Replace the planned ledger entry with what was actually applied.
    _write_ledger_entry(theme.meta.name, prior_files | set(owned_files),
                        prior_settings | set(owned_settings))

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
) -> tuple[list[str], list[str], bool]:
    """Revert to the pristine baseline.

    Returns ``(log, warnings, hard_failed)`` where ``hard_failed`` is True only
    if a file/setting actually failed to revert (hook notices are soft).
    """
    with process_lock():  # L1: see apply()
        return _restore_locked(only, wipe, allow_sudo, hook_gate, assume_yes)


def _restore_locked(
    only: set[str] | None,
    wipe: bool,
    allow_sudo: bool,
    hook_gate: "HookGate | None",
    assume_yes: bool,
) -> tuple[list[str], list[str], bool]:
    baseline = Baseline().load()
    warnings: list[str] = []
    warnings.extend(baseline.warnings)
    if baseline.is_empty and not baseline.hooks:
        return [], warnings + ["nothing to restore — no baseline recorded"], False

    # Undo the install hooks that actually ran (recorded in the baseline),
    # gated exactly like apply hooks; forget the ones that ran.
    hook_records = [
        r for r in baseline.hooks if only is None or r.get("component", "") in only
    ]
    hlog, hwarn, ran = _run_recorded_hooks(hook_records, allow_sudo, hook_gate, assume_yes)
    warnings.extend(hwarn)
    if ran:
        baseline.forget_hooks(ran)

    flog, fwarn, fdone, fdead = baseline.restore_files(only)
    slog, swarn, sdone, sdead = baseline.restore_settings(only)
    log = hlog + flog + slog
    warnings.extend(fwarn)
    warnings.extend(swarn)

    # R5: a dead record (blob lost, symlink without target, schema/key gone)
    # can never revert by re-running — its warning above names it; drop it so
    # restore can complete instead of wedging forever.
    if fdead:
        baseline.forget_files(fdead)
        warnings.append(
            f"dropped {len(fdead)} baseline record(s) whose pre-gtheme copy is "
            f"lost; the file(s) named above were left as-is"
        )
    if sdead:
        baseline.forget_settings(sdead)
        warnings.append(
            f"dropped {len(sdead)} baseline setting record(s) whose schema/key "
            f"no longer exists (app uninstalled?)"
        )

    # Hard failure = a TRANSIENT file/setting revert failure (not a hook notice,
    # not a dead record): anything selected that is neither done nor dropped.
    f_sel = [k for k, r in baseline.files.items() if only is None or r.get("component", "") in only]
    s_sel = [k for k, r in baseline.settings.items() if only is None or r.get("component", "") in only]
    hard_failed = any(k not in fdone for k in f_sel) or any(k not in sdone for k in s_sel)

    if only is None:
        # R1: only discard recovery state when the revert actually succeeded.
        if not hard_failed:
            # R6: consume the baseline like R3 does — after a full revert the
            # on-disk state IS pristine; a kept record would stop the next apply
            # from re-snapshotting and silently revert future user edits.
            # (Un-run hook records stay retryable; --wipe removes everything.)
            baseline.forget_files(list(baseline.files))
            baseline.forget_settings(list(baseline.settings))
            clear_current()
            write_ledger({})
            if wipe:
                baseline.wipe()
        elif wipe:
            warnings.append(
                "kept baseline (--wipe skipped): some items failed to revert; "
                "fix the cause and re-run restore"
            )
    else:
        # R3: forget the reverted components so current/ledger stay truthful.
        if not hard_failed:
            baseline.forget_files(fdone)
            baseline.forget_settings(sdone)
            cur = read_current()
            if cur:
                ledger = read_ledger()
                ent = ledger.get(cur)
                if isinstance(ent, dict):
                    drop_f, drop_s = set(fdone) | set(fdead), set(sdone) | set(sdead)
                    ent["files"] = [f for f in ent.get("files", []) if f not in drop_f]
                    ent["settings"] = [s for s in ent.get("settings", []) if s not in drop_s]
                    ledger[cur] = ent
                    write_ledger(ledger)
            if baseline.is_empty:
                clear_current()

    return log, warnings, hard_failed
