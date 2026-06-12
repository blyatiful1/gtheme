"""Filesystem locations for gtheme.

Two kinds of theme live side by side:
  * the bundled collection that ships in the repo (``<repo>/themes``), and
  * user-installed / authored themes under ``$XDG_DATA_HOME/gtheme/themes``.

``DEST_ROOT`` is the root that a manifest's ``~`` destinations expand against.
It is normally ``$HOME`` but can be pointed at a throwaway directory via
``GTHEME_DEST_ROOT`` so apply/restore can be exercised without touching the
live desktop.
"""

from __future__ import annotations

import os
from pathlib import Path


def _env_path(var: str, default: Path) -> Path:
    val = os.environ.get(var)
    return Path(val).expanduser() if val else default


HOME = Path.home()

# XDG base dirs (no platformdirs dependency).
XDG_DATA_HOME = _env_path("XDG_DATA_HOME", HOME / ".local" / "share")
XDG_STATE_HOME = _env_path("XDG_STATE_HOME", HOME / ".local" / "state")
XDG_CONFIG_HOME = _env_path("XDG_CONFIG_HOME", HOME / ".config")

# Where gtheme keeps its own data.
DATA_DIR = XDG_DATA_HOME / "gtheme"
STATE_DIR = XDG_STATE_HOME / "gtheme"
INSTALLED_THEMES_DIR = DATA_DIR / "themes"
BACKUP_DIR = STATE_DIR / "backups"
BASELINE_DIR = BACKUP_DIR / "baseline"
CURRENT_FILE = STATE_DIR / "current"

# The repo this package was checked out from: src/gtheme/paths.py -> repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]
_PKG_DIR = Path(__file__).resolve().parent

TEMPLATES_DIR = _PKG_DIR / "templates"


def _first_existing(*candidates: Path) -> Path:
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


# Source checkout keeps the collection at <repo>/themes; an installed wheel ships
# it inside the package as _bundled_themes (see pyproject force-include).
BUNDLED_THEMES_DIR = _first_existing(REPO_ROOT / "themes", _PKG_DIR / "_bundled_themes")
SKELETON_DIR = _first_existing(REPO_ROOT / "template", _PKG_DIR / "_skeleton")

# Root that manifest "~" destinations expand against.
DEST_ROOT = _env_path("GTHEME_DEST_ROOT", HOME)


def theme_search_paths() -> list[Path]:
    """Directories that may contain themes, in priority order (installed first)."""
    paths: list[Path] = []
    for p in (INSTALLED_THEMES_DIR, BUNDLED_THEMES_DIR):
        if p not in paths:
            paths.append(p)
    return paths


def expand_dest(dest: str) -> Path:
    """Expand a manifest destination against ``DEST_ROOT``.

    ``~`` and ``$HOME`` map to ``DEST_ROOT`` (so tests can reroot them); any
    other absolute path is returned untouched.
    """
    dest = dest.replace("$HOME", "~")
    if dest == "~":
        return DEST_ROOT
    if dest.startswith("~/"):
        return DEST_ROOT / dest[2:]
    return Path(dest).expanduser()


def ensure_state_dirs() -> None:
    for d in (DATA_DIR, STATE_DIR, INSTALLED_THEMES_DIR, BACKUP_DIR):
        d.mkdir(parents=True, exist_ok=True)
