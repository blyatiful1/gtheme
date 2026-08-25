"""Enumerate installed GTK and GNOME Shell themes.

Themes are discovered by *structure*, not by asking any index: a directory is
a GTK theme if it has a ``gtk-3.0`` or ``gtk-4.0`` subdirectory, and a shell
theme if it has ``gnome-shell/gnome-shell.css`` (research/gnome-domains.md
§1.2, §4). There is no manifest to read — a theme is whatever a directory
under one of the theme roots looks like.

Search order matters: GNOME looks in ``~/.themes``, then
``$XDG_DATA_HOME/themes`` (usually ``~/.local/share/themes``), then each
``$XDG_DATA_DIRS/themes`` (usually ``/usr/share/themes``), and a name found
earlier wins. :func:`scan_themes` takes the root list explicitly so it can be
driven against a fixture tree in tests; :func:`default_theme_roots` supplies
the real search order for production use.

This module does no GTK/GObject work and imports no ``gi`` — it is plain
``pathlib``, safe to unit-test without a display.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "ThemeEntry",
    "dark_variant_name",
    "default_theme_roots",
    "gtk_themes",
    "scan_themes",
    "shell_themes",
]


@dataclass(frozen=True)
class ThemeEntry:
    """One theme directory, and what it provides."""

    #: The directory's own name — this is the value written to
    #: ``interface gtk-theme`` / ``user-theme name``, not a display label.
    name: str
    path: Path
    #: Has a ``gtk-3.0`` subdirectory: usable as ``interface gtk-theme`` for
    #: legacy GTK3 apps (libadwaita apps ignore this key entirely — see
    #: gnome-domains.md §1.2).
    has_gtk3: bool
    #: Has a ``gtk-4.0`` subdirectory: usable for non-libadwaita GTK4 apps.
    has_gtk4: bool
    #: Has ``gnome-shell/gnome-shell.css``: usable as
    #: ``org.gnome.shell.extensions.user-theme name``.
    has_shell: bool

    @property
    def is_gtk_theme(self) -> bool:
        return self.has_gtk3 or self.has_gtk4


def default_theme_roots() -> list[Path]:
    """The real search order: ``~/.themes``, XDG data home, then XDG data dirs."""
    home = Path(os.environ.get("HOME", str(Path.home())))
    data_home = Path(os.environ.get("XDG_DATA_HOME", str(home / ".local" / "share")))
    data_dirs_env = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share")
    data_dirs = [Path(p) for p in data_dirs_env.split(":") if p]
    roots = [home / ".themes", data_home / "themes"]
    roots.extend(d / "themes" for d in data_dirs)
    return roots


def scan_themes(roots: list[Path]) -> list[ThemeEntry]:
    """Walk ``roots`` in order and return one entry per theme name.

    A name found in an earlier root shadows the same name in a later one,
    matching how GNOME itself resolves theme names (user overrides system).
    Directories that provide neither GTK nor shell theming are skipped.
    """
    seen: dict[str, ThemeEntry] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir() or child.name in seen:
                continue
            has_gtk3 = (child / "gtk-3.0").is_dir()
            has_gtk4 = (child / "gtk-4.0").is_dir()
            has_shell = (child / "gnome-shell" / "gnome-shell.css").is_file()
            if not (has_gtk3 or has_gtk4 or has_shell):
                continue
            seen[child.name] = ThemeEntry(
                name=child.name,
                path=child,
                has_gtk3=has_gtk3,
                has_gtk4=has_gtk4,
                has_shell=has_shell,
            )
    return sorted(seen.values(), key=lambda t: t.name.casefold())


def gtk_themes(entries: list[ThemeEntry]) -> list[ThemeEntry]:
    """Entries usable as ``interface gtk-theme``."""
    return [e for e in entries if e.is_gtk_theme]


def shell_themes(entries: list[ThemeEntry]) -> list[ThemeEntry]:
    """Entries usable as ``user-theme name``."""
    return [e for e in entries if e.has_shell]


def dark_variant_name(name: str, available: set[str]) -> str | None:
    """The dark-mode counterpart of a GTK theme name, if one is installed.

    Toggling dark mode has to write both ``color-scheme`` and ``gtk-theme``
    (gnome-domains.md §1.2, "the classic split-brain bug") because the dark
    variant of a GTK3 theme is a *separate directory*, not a flag — this is
    the lookup that makes that compound write possible: ``adw-gtk3`` and
    ``adw-gtk3-dark`` are two names, and this function finds the other one
    given either.
    """
    if name.endswith("-dark"):
        light = name[: -len("-dark")]
        return light if light in available else None
    dark = f"{name}-dark"
    return dark if dark in available else None
