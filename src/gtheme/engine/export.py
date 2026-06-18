"""`gtheme export` — bundle a theme directory into one shareable .zip archive.

The archive contains a single top-level ``<name>/`` directory, so unzipping it
yields a clean theme dir that installs with ``gtheme install <unzipped-dir>``.
Install-local bookkeeping (the origin marker), caches, and staging/temp files
are left out so the bundle is portable and reproducible.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from ..errors import GthemeError
from ..paths import ORIGIN_FILE
from ..registry import find

_SKIP_NAMES = {ORIGIN_FILE, "__pycache__", ".DS_Store", ".git"}
_SKIP_SUFFIXES = (".pyc", ".gtheme-tmp")


def _included(rel: Path) -> bool:
    parts = rel.parts
    if any(p in _SKIP_NAMES for p in parts):
        return False
    if rel.suffix in _SKIP_SUFFIXES:
        return False
    if any(p.endswith(".staging") for p in parts):
        return False
    return True


def export_theme(name: str, out: str | None = None) -> tuple[Path, int]:
    """Zip the theme ``name`` into ``out``. Returns (archive_path, file_count)."""
    src = find(name)
    if src is None:
        raise GthemeError(f"theme not found: {name}")
    src = Path(src)

    out_path = Path(out).expanduser() if out else Path.cwd() / f"{name}.zip"
    if out_path.is_dir():
        out_path = out_path / f"{name}.zip"
    if out_path.suffix.lower() != ".zip":
        out_path = out_path.with_suffix(".zip")

    members: list[tuple[Path, Path]] = []
    for p in sorted(src.rglob("*")):
        if not p.is_file():  # skips dirs and dangling symlinks
            continue
        rel = p.relative_to(src)
        if _included(rel):
            members.append((p, rel))
    if not members:
        raise GthemeError(f"nothing to export for {name!r} (no files found in {src})")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(out_path.name + ".tmp")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for p, rel in members:
                # Top-level <name>/ folder so the archive unzips to a theme dir.
                zf.write(p, arcname=str(Path(name) / rel))
        tmp.replace(out_path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return out_path, len(members)
