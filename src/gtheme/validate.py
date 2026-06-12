"""Theme validation: manifest schema + source files + destinations + requires."""

from __future__ import annotations

import shutil
from pathlib import Path

from .engine.apply import iter_file_ops, resolved_settings
from .manifest import Theme, load_theme
from .paths import expand_dest


def validate_dir(theme_dir: Path) -> tuple[Theme | None, list[str], list[str]]:
    """Return (theme | None, errors, warnings). ``theme is None`` => fatal."""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        theme = load_theme(theme_dir)
    except Exception as exc:  # noqa: BLE001
        return None, [f"manifest invalid: {exc}"], []

    # Every declared source must exist.
    for fi in theme.files:
        src = theme.path / fi.src
        if not src.exists():
            errors.append(f"[files] missing src: {fi.src}")
        parent = expand_dest(fi.dest).parent
        if parent.exists() and not parent.is_dir():
            errors.append(f"[files] dest parent is not a dir: {parent}")

    # Hook scripts must exist.
    for hook in theme.hooks:
        if not (theme.path / hook.script).is_file():
            errors.append(f"[hooks] missing script: {hook.script}")
        if hook.restore and not (theme.path / hook.restore).is_file():
            warnings.append(f"[hooks] missing restore script: {hook.restore}")

    # Palette colours must parse (the render engine relies on it).
    from .color import parse_hex

    for role, value in theme.palette.items():
        try:
            parse_hex(value)
        except ValueError as exc:
            errors.append(f"[palette] {role}: {exc}")

    # Soft checks: required tools / fonts.
    for pkg in theme.requires.packages:
        if shutil.which(pkg) is None:
            warnings.append(f"required package/binary not found: {pkg}")

    return theme, errors, warnings
