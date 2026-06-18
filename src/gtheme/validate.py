"""Theme validation: manifest schema + source files + destinations + requires.

This is the truthful safety net: it must flag the dangerous manifests that the
engine would otherwise happily execute (path escapes, special-bit modes,
shell hooks, irreversible/root hooks, non-portable hard-coded home paths).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from .errors import ThemeSecurityError
from .manifest import Theme, load_theme
from .paths import confine_dest, confine_src


def package_installed(pkg: str) -> bool:
    """Best-effort: is ``pkg`` available as a binary OR a known system package?

    Many themed deps (e.g. ``papirus-icon-theme``) ship no PATH binary, so a
    bare ``shutil.which`` falsely reports them missing. Fall back to the host
    package manager before deciding.
    """
    if shutil.which(pkg):
        return True
    queries = (
        ["pacman", "-Qq", pkg],
        ["dpkg", "-s", pkg],
        ["rpm", "-q", pkg],
    )
    for q in queries:
        if shutil.which(q[0]) is None:
            continue
        try:
            if subprocess.run(q, capture_output=True).returncode == 0:
                return True
        except OSError:
            continue
    return False

# Special / dangerous permission bits on an installed file.
_SETUID = 0o4000
_SETGID = 0o2000
_STICKY = 0o1000
_WORLD_WRITE = 0o002

# A literal user home path baked into a source file (non-portable). Matches
# "/home/<name>/" for any plausible username.
_HOME_PATH_RE = re.compile(r"/home/[A-Za-z_][A-Za-z0-9_-]*/")

# Skip files larger than this when scanning for hard-coded paths (cheap check).
_SCAN_MAX_BYTES = 256 * 1024


def _parse_mode(mode: str) -> int | None:
    try:
        return int(mode, 8)
    except (ValueError, TypeError):
        return None


def _scan_for_home_path(path: Path) -> bool:
    """True if a small text file contains a literal /home/<name>/ path."""
    try:
        if path.stat().st_size > _SCAN_MAX_BYTES:
            return False
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError, UnicodeDecodeError):
        return False  # binary / too big / unreadable -> skip cheaply
    return bool(_HOME_PATH_RE.search(text))


def validate_dir(theme_dir: Path) -> tuple[Theme | None, list[str], list[str]]:
    """Return (theme | None, errors, warnings). ``theme is None`` => fatal."""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        theme = load_theme(theme_dir)
    except Exception as exc:  # noqa: BLE001
        return None, [f"manifest invalid: {exc}"], []

    # [[files]]: confinement, dangerous modes, source existence, portability.
    for fi in theme.files:
        # Source must stay inside the theme dir and must exist.
        src: Path | None = None
        try:
            src = confine_src(fi.src, theme.path)
        except ThemeSecurityError as exc:
            errors.append(f"[files] unsafe src/dest: {exc}")
        if src is None or not src.exists():
            errors.append(f"[files] missing src: {fi.src}")

        # Destination must stay inside DEST_ROOT.
        dest: Path | None = None
        try:
            dest = confine_dest(fi.dest)
        except ThemeSecurityError as exc:
            errors.append(f"[files] unsafe src/dest: {exc}")
        if dest is not None:
            parent = dest.parent
            if parent.exists() and not parent.is_dir():
                errors.append(f"[files] dest parent is not a dir: {parent}")

        # Dangerous permission bits.
        if fi.mode is not None:
            bits = _parse_mode(fi.mode)
            if bits is None:
                errors.append(f"[files] invalid mode {fi.mode!r} on {fi.src}")
            else:
                if bits & (_SETUID | _SETGID | _STICKY):
                    errors.append(
                        f"[files] {fi.src}: refuses special-bit mode "
                        f"{fi.mode} (setuid/setgid/sticky)"
                    )
                if bits & _WORLD_WRITE:
                    warnings.append(
                        f"[files] {fi.src}: world-writable mode {fi.mode}"
                    )
                if not (bits & 0o400):
                    # Owner-unreadable dest breaks a later diff/dry-run/re-apply.
                    warnings.append(
                        f"[files] {fi.src}: mode {fi.mode} is not owner-readable"
                    )

        # Portability: hard-coded home paths in installed text sources.
        if src is not None and src.exists():
            scan_targets: list[Path] = []
            if src.is_dir():
                scan_targets = [p for p in sorted(src.rglob("*")) if p.is_file()]
            elif src.is_file():
                scan_targets = [src]
            for target in scan_targets:
                if _scan_for_home_path(target):
                    rel = fi.src
                    if src.is_dir():
                        try:
                            rel = f"{fi.src}/{target.relative_to(src)}"
                        except ValueError:
                            rel = str(target)
                    warnings.append(
                        f"[files] hard-coded home path in {rel}; "
                        f"use {{{{ home }}}} + template=true"
                    )

    # [[hooks]]: every hook runs shell on apply; sudo/irreversible are worse.
    for hook in theme.hooks:
        if not (theme.path / hook.script).is_file():
            errors.append(f"[hooks] missing script: {hook.script}")
        if hook.sudo:
            warnings.append(
                f"[hooks] {hook.script} runs as ROOT (sudo) on apply"
            )
        else:
            warnings.append(
                f"[hooks] {hook.script} executes shell on apply"
            )
        if hook.restore:
            if not (theme.path / hook.restore).is_file():
                warnings.append(f"[hooks] missing restore script: {hook.restore}")
        else:
            warnings.append(
                f"[hooks] {hook.script} has no restore script; "
                f"its changes are irreversible"
            )

    # Palette colours must parse (the render engine relies on it).
    from .color import parse_hex

    for role, value in theme.palette.items():
        try:
            parse_hex(value)
        except ValueError as exc:
            errors.append(f"[palette] {role}: {exc}")

    # Soft checks: required tools / fonts.
    for pkg in theme.requires.packages:
        if not package_installed(pkg):
            warnings.append(f"required package may be missing: {pkg}")

    return theme, errors, warnings
