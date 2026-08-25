"""Enumerate installed icon themes and cursor themes.

Both are discovered by structure, matching gnome-domains.md §1.3/§1.4:

* an **icon theme** is a directory with an ``index.theme`` file that declares
  a ``[Icon Theme]`` section with a ``Name`` — ``hicolor`` (the fallback
  theme) and ``default`` (a bare cursor pointer, no ``index.theme`` at all on
  this machine) must never be offered as a choice;
* a **cursor theme** is an icon directory that additionally has a ``cursors``
  subdirectory — of the icon themes on the research machine, only ``Adwaita``
  qualifies, so the app must enumerate cursor themes by that structural test
  rather than by listing everything under ``icons/``.

No ``gi`` import: plain ``pathlib`` and a small INI reader, safe to unit-test
without a display.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "IconThemeEntry",
    "cursor_themes",
    "default_icon_roots",
    "scan_icon_themes",
]

#: Directory names that are structurally icon themes but must never be
#: surfaced as a user-facing choice.
_EXCLUDED = frozenset({"hicolor", "default"})


@dataclass(frozen=True)
class IconThemeEntry:
    """One icon theme directory."""

    #: The directory name — the value written to ``interface icon-theme`` /
    #: ``interface cursor-theme``.
    directory_name: str
    #: ``Name=`` from ``index.theme``. Falls back to the directory name if the
    #: key is missing (malformed themes exist in the wild).
    display_name: str
    path: Path
    #: Has a ``cursors`` subdirectory.
    is_cursor_theme: bool


def default_icon_roots() -> list[Path]:
    """Real search order: ``~/.icons``, XDG data home, then XDG data dirs."""
    home = Path(os.environ.get("HOME", str(Path.home())))
    data_home = Path(os.environ.get("XDG_DATA_HOME", str(home / ".local" / "share")))
    data_dirs_env = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share")
    data_dirs = [Path(p) for p in data_dirs_env.split(":") if p]
    roots = [home / ".icons", data_home / "icons"]
    roots.extend(d / "icons" for d in data_dirs)
    return roots


def _read_index_theme_name(index_file: Path) -> str | None:
    """The ``Name=`` value of the ``[Icon Theme]`` section, or ``None``.

    Deliberately not ``configparser`` — icon theme ``index.theme`` files
    routinely have duplicate keys and interpolation-hostile values (``%``
    literally in directory lists) that trip ``configparser`` defaults.
    """
    try:
        text = index_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    in_section = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_section = stripped == "[Icon Theme]"
            continue
        if not in_section or not stripped or stripped.startswith(("#", ";")):
            continue
        key, sep, value = stripped.partition("=")
        if sep and key.strip() == "Name":
            return value.strip()
    return None


def scan_icon_themes(roots: list[Path]) -> list[IconThemeEntry]:
    """Walk ``roots`` in order; a directory name found earlier wins."""
    seen: dict[str, IconThemeEntry] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir() or child.name in seen or child.name in _EXCLUDED:
                continue
            index_file = child / "index.theme"
            display_name = _read_index_theme_name(index_file)
            if display_name is None:
                # No [Icon Theme] Name= — not a real icon theme (e.g. "locolor",
                # or a bare cursors-only dir with no metadata at all).
                continue
            seen[child.name] = IconThemeEntry(
                directory_name=child.name,
                display_name=display_name,
                path=child,
                is_cursor_theme=(child / "cursors").is_dir(),
            )
    return sorted(seen.values(), key=lambda t: t.display_name.casefold())


def cursor_themes(entries: list[IconThemeEntry]) -> list[IconThemeEntry]:
    """Entries usable as ``interface cursor-theme``."""
    return [e for e in entries if e.is_cursor_theme]
