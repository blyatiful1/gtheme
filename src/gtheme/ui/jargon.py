"""The words this app is not allowed to say.

THE CONTRACT IS FROZEN (DESIGN.md A7). The reader we are building for has never
used Linux. Every word below is one they would have to look up, and looking it
up is the failure — a person who has to search the web to understand a checkbox
has already been let down by the checkbox.

:data:`BANNED` is enforced by a lint test over every descriptor title and
subtitle in ``data/panels/`` and ``data/domains/``, every page title and
subtitle in ``ui.registry``, and every user-visible string in ``ui/``.
:data:`TRANSLATIONS` is the replacement table, and is also what the More
Settings floor page runs a schema's own ``<summary>`` through before showing
it — those summaries are written by developers for developers, and are labelled
as system text when shown.

Matching is on whole words, case-insensitively, so "Nutshell" does not trip
"shell" and "Ghostty" does not trip anything. Deliberate exceptions live in
:data:`ALLOWED_PHRASES`: "Terminal" is allowed because it is the name of a
thing on the user's screen, and "GNOME" is allowed in the two places the app
has to name the desktop it is changing.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

__all__ = [
    "ALLOWED_PHRASES",
    "BANNED",
    "TRANSLATIONS",
    "check",
    "find_banned",
    "translate",
]


#: Words no user-facing string may contain. Grouped by why.
BANNED: frozenset[str] = frozenset(
    {
        # -- the settings machinery. The user does not have a "settings
        # database"; they have a desktop that looks a certain way.
        "dconf",
        "gsettings",
        "gschema",
        "schema",
        "schemas",
        "gvariant",
        "variant",
        "keyfile",
        "backend",
        "namespace",
        # -- identifiers and internals
        "uuid",
        "uuids",
        "pk",
        "id",
        "ids",
        "enum",
        "boolean",
        "bool",
        "int",
        "string",
        "regex",
        "null",
        "nil",
        "binary",
        # -- the platform. "Shell" is the single worst offender: it means a
        # command interpreter to one reader and the top bar to another.
        "shell",
        "gnome-shell",
        "gtk",
        "gtk3",
        "gtk4",
        "libadwaita",
        "adwaita",
        "wayland",
        "x11",
        "xorg",
        "compositor",
        "mutter",
        "dbus",
        "d-bus",
        "systemd",
        "daemon",
        "portal",
        "freedesktop",
        "xdg",
        # -- font rendering vocabulary, which reads as physics to a novice
        "hinting",
        "antialiasing",
        "anti-aliasing",
        "subpixel",
        "rgba",
        "pango",
        "dpi",
        # -- window-manager vocabulary
        "headerbar",
        "titlebar",
        "csd",
        "ssd",
        "wm",
        "decorations",
        # -- the phrase GNOME itself uses and nobody understands
        "legacy applications",
        "legacy",
        # -- developer process words
        "deprecated",
        "stdout",
        "stderr",
        "cli",
        "sudo",
        "chmod",
        "symlink",
        "symlinked",
        "repo",
        "repository",
        "commit",
        "config",
        "configs",
        "argv",
        "env",
        "path",
        "instantiate",
        "serialize",
        "serialise",
        "cache",
        "hash",
    }
)


#: Phrases that contain a banned word and are allowed anyway, matched before
#: the word scan. Keep this list short and argued.
ALLOWED_PHRASES: tuple[str, ...] = (
    # The desktop has a name and sometimes the app must say it: "gtheme works
    # with GNOME 49 and 50." Naming it is honest; explaining it is the
    # glossary's job.
    "gnome",
    # A terminal is a window the user can point at. It is also a page title.
    "terminal",
    # The user's own words for the thing, kept because they are the words on
    # the buttons of every other app they have used.
    "file path",
)


#: Jargon on the left, what to say instead on the right. Used by
#: :func:`translate` for auto-generated floor rows, and as the house style
#: reference for everyone writing copy by hand.
TRANSLATIONS: dict[str, str] = {
    "extension": "add-on",
    "extensions": "add-ons",
    "gnome shell theme": "top bar style",
    "shell theme": "top bar style",
    "shell": "top bar",
    "panel": "top bar",
    "top panel": "top bar",
    "dash": "the row of app icons",
    "dock": "the row of app icons",
    "overview": "the app view",
    "activities": "the app view",
    "workspace": "desktop",
    "workspaces": "desktops",
    "hot corner": "the top-left corner shortcut",
    "wallpaper": "background picture",
    "color scheme": "light or dark",
    "colour scheme": "light or dark",
    "accent color": "highlight colour",
    "accent colour": "highlight colour",
    "gtk theme": "app style",
    "icon theme": "icon set",
    "cursor theme": "pointer style",
    "font": "text style",
    "font rendering": "how sharp text looks",
    "hinting": "text sharpness",
    "antialiasing": "text smoothing",
    "titlebar": "the bar at the top of a window",
    "headerbar": "the bar at the top of a window",
    "legacy applications": "older apps",
    "dconf": "your desktop's saved settings",
    "gsettings": "your desktop's saved settings",
    "schema": "a list of settings an add-on understands",
    "uuid": "the add-on's identifier",
    "night light": "warmer colours in the evening",
    "reduced motion": "less movement",
    "high contrast": "stronger colours for readability",
    "relogin": "log out and back in",
    "log out": "log out",
}

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9\-']*")


def _mask_allowed(text: str) -> str:
    """Blank out allowed phrases so their contents are not scanned."""
    lowered = text.lower()
    for phrase in ALLOWED_PHRASES:
        lowered = lowered.replace(phrase, " " * len(phrase))
    return lowered


def find_banned(text: str) -> list[str]:
    """Banned words in ``text``, in order of appearance, without duplicates.

    Multi-word banned entries ("legacy applications") are matched as phrases;
    single words are matched on whole-word boundaries.
    """
    masked = _mask_allowed(text)
    found: list[str] = []

    for entry in BANNED:
        if " " in entry and entry in masked:
            found.append(entry)

    for word in _WORD_RE.findall(masked):
        if word in BANNED and word not in found:
            found.append(word)

    return found


def check(text: str, *, where: str = "") -> list[str]:
    """Human-readable complaints about ``text``. Empty list means it is fine.

    Args:
        text: the user-facing string to check.
        where: what to name in the message — a descriptor id, a page id.
    """
    problems = []
    for word in find_banned(text):
        suggestion = TRANSLATIONS.get(word)
        prefix = f"{where}: " if where else ""
        if suggestion:
            problems.append(f'{prefix}says {word!r} — say "{suggestion}" instead')
        else:
            problems.append(f"{prefix}says {word!r}, which the reader will not know")
    return problems


def check_all(items: Iterable[tuple[str, str]]) -> list[str]:
    """Check many ``(where, text)`` pairs at once. Returns every complaint."""
    problems: list[str] = []
    for where, text in items:
        problems.extend(check(text, where=where))
    return problems


def translate(text: str) -> str:
    """Replace known jargon with plain words, longest phrase first.

    Best-effort, and used only on text gtheme did not write — the ``<summary>``
    strings that come out of the system's own settings descriptions, shown on
    the More Settings floor page and labelled as system text. Copy gtheme
    writes itself is written in plain words to begin with; this is not a
    licence to write jargon and post-process it.
    """
    out = text
    for jargon in sorted(TRANSLATIONS, key=len, reverse=True):
        pattern = re.compile(rf"\b{re.escape(jargon)}\b", re.IGNORECASE)
        out = pattern.sub(TRANSLATIONS[jargon], out)
    return out
