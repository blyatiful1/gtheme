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

import json
import os
from pathlib import Path

from .errors import ThemeSecurityError


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

# Root that manifest "~" destinations expand against.
DEST_ROOT = _env_path("GTHEME_DEST_ROOT", HOME)

# Marker dropped into installed themes recording where they came from.
ORIGIN_FILE = ".gtheme-origin.json"


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


def confine_dest(dest: str, *, allow_outside: bool = False) -> Path:
    """Expand ``dest`` and confine it to ``DEST_ROOT``.

    Raises ``ThemeSecurityError`` if the resolved path escapes ``DEST_ROOT``
    (e.g. ``~/../../etc/foo`` or an absolute ``/etc/...``) unless
    ``allow_outside`` is set.
    """
    # E1: a broken environment (empty/relative $HOME -> DEST_ROOT "/" or "") would
    # make every path "inside" the root and defeat confinement. Refuse to write.
    root = DEST_ROOT.resolve()
    if not DEST_ROOT.is_absolute() or root == Path(root.anchor):
        raise ThemeSecurityError(
            f"unsafe DEST_ROOT {DEST_ROOT!r} (empty, relative, or filesystem root); "
            f"refusing to write — check $HOME / $GTHEME_DEST_ROOT"
        )
    expanded = expand_dest(dest)
    if not allow_outside and not expanded.resolve().is_relative_to(root):
        raise ThemeSecurityError(
            f"dest escapes {DEST_ROOT}: {dest}"
        )
    return expanded


def confine_src(src: str, theme_path: Path) -> Path:
    """Resolve ``src`` relative to ``theme_path`` and confine it there.

    Raises ``ThemeSecurityError`` if ``src`` (via ``../`` etc.) resolves
    outside the theme directory.
    """
    resolved = (theme_path / src).resolve()
    if not resolved.is_relative_to(theme_path.resolve()):
        raise ThemeSecurityError(
            f"src escapes theme dir {theme_path}: {src}"
        )
    return resolved


def read_origin(theme_path: Path) -> dict | None:
    """Parse ``theme_path/.gtheme-origin.json``, or None if absent/unreadable."""
    origin = theme_path / ORIGIN_FILE
    try:
        text = origin.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def theme_is_untrusted(theme_path: Path) -> bool:
    """True iff an origin marker records a downloaded source (git or .zip).

    Zips are the sharing/download format, so a zip-installed theme is just as
    untrusted as a cloned one (README: anything you downloaded is untrusted).
    """
    origin = read_origin(theme_path)
    return origin is not None and origin.get("type") in ("git", "zip")


def safe_theme_name(name: str) -> str:
    """Validate a name that will be used as a single directory component.

    Theme names must be slugs (letters, digits, ``-`` or ``_``) — the same rule
    the manifest enforces on ``[meta].name``. This stops a name like ``../x`` or
    ``..`` (e.g. from ``install --name`` or ``install /path/..``) from escaping
    the installed-themes directory when it becomes ``INSTALLED_THEMES_DIR/<name>``.
    Raises :class:`ThemeSecurityError` on anything else.
    """
    # ASCII-only: unicode isalnum() would admit homograph names like "ｎｓｘ".
    if not name or not all(c.isascii() and (c.isalnum() or c in "-_") for c in name):
        raise ThemeSecurityError(
            f"unsafe theme name {name!r}: use ASCII letters, digits, '-' or '_' only"
        )
    return name
