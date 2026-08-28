"""Sound — the noises the desktop makes, and whether it makes them.

Seven settings, six of which are switches. The seventh is the interesting one:
which *set* of short sounds the desktop plays. The descriptor calls it a
``picker``, meaning "the row shows what is installed, never a text box", and
the base row library deliberately leaves that kind unbuilt — a picker's content
comes from scanning the machine, which is not the row library's business.

So this page scans. A sound set on a Linux desktop is a directory holding an
``index.theme`` file, in one of the standard sound directories, and the scan is
nothing more than that. Two things it takes care over:

* **The set the desktop is using is always in the list**, even when the scan
  did not find it — the person can see what they have and put it back.
* **The list is never empty.** ``freedesktop`` is the set every desktop ships,
  so it is offered even on a machine where nothing could be read.

That turns the picker into an ordinary pick-one row, which then goes through
the same builder as everything else and gets the same explanation, the same
"put this back" button and the same honest greying.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ...core.backends import get_backend
from ...core.gvariant import quote, unquote
from ...core.settings_backend import BackendError
from ...panels.descriptor import Choice, Row, WidgetKind
from ...panels.schema_probe import SchemaProbe
from ..search import GroupSpec, page_rows, settings_page

__all__ = ["COPY", "SOUND_SET_ROW", "build", "installed_sound_sets"]

PAGE_ID = "sound"

#: The setting that names which collection of short sounds is in use.
SOUND_SET_ROW = "org.gnome.desktop.sound:theme-name"

#: The set every desktop ships. Always offered, so the list is never empty.
DEFAULT_SOUND_SET = "freedesktop"

#: What the desktop stores when the sounds have been picked one by one rather
#: than taken from a set. Shown honestly rather than hidden, because a person
#: who has one wants to know why the list looks odd.
CUSTOM_SOUND_SET = "__custom"

COPY: dict[str, str] = {
    "sets-title": "Which sounds",
    "sets-description": (
        "The collection of short sounds your desktop plays. Different collections "
        "sound different; none of them change how music or video sounds."
    ),
    "when-title": "When to make a sound",
    "when-description": (
        "Whether your desktop makes a noise when something happens. Turn these off "
        "for a silent computer."
    ),
    "alerts-title": "Getting your attention",
    "alerts-description": (
        "What happens when an app wants you to look at it. A flash instead of a "
        "sound is useful in a quiet room, or if you cannot hear the sound."
    ),
    "custom-label": "Sounds you picked yourself",
    "no-sound-set": "gtheme could not read the collections of sounds on this computer.",
}

#: Which rows sit in which group. Anything the corpus grows later that is not
#: named here still appears — under "When to make a sound" — because a control
#: that exists in the data and not on the page is the failure this app is about.
_ALERT_ROWS: frozenset[str] = frozenset(
    {
        "org.gnome.desktop.wm.preferences:audible-bell",
        "org.gnome.desktop.wm.preferences:visual-bell",
        "org.gnome.desktop.wm.preferences:visual-bell-type",
    }
)


def _sound_roots() -> list[Path]:
    """Every directory a collection of sounds can live in, in search order."""
    home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    roots = [Path(home) / "sounds", Path.home() / ".local" / "share" / "sounds"]
    data_dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    roots.extend(Path(entry) / "sounds" for entry in data_dirs.split(os.pathsep) if entry)
    return roots


def installed_sound_sets(roots: list[Path] | None = None) -> list[str]:
    """The collections of sounds on this computer, sorted, never empty.

    A collection is a directory with an ``index.theme`` in it. That is the
    whole rule, and it is the same one the desktop itself applies.
    """
    found: set[str] = {DEFAULT_SOUND_SET}
    for root in roots if roots is not None else _sound_roots():
        try:
            entries = sorted(root.iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                if (entry / "index.theme").is_file():
                    found.add(entry.name)
            except OSError:  # pragma: no cover - an unreadable directory
                continue
    return sorted(found)


def _current_sound_set(backend: Any, row: Row) -> str | None:
    from ..widgets.rows import key_for

    try:
        raw = backend.get(key_for(row))
    except BackendError:
        return None
    return unquote(raw) or None


def sound_set_row(row: Row, backend: Any, *, sets: list[str] | None = None) -> Row:
    """Turn the picker descriptor into a pick-one row over what is installed.

    The set currently in use is added to the offered list when the scan missed
    it, so the row never quietly proposes changing something it cannot show.
    """
    names = list(sets) if sets is not None else installed_sound_sets()
    current = _current_sound_set(backend, row)
    if current and current not in names and current != CUSTOM_SOUND_SET:
        names.append(current)
    choices = [Choice(value=quote(name), label=name) for name in sorted(names)]
    if current == CUSTOM_SOUND_SET:
        choices.append(Choice(value=quote(CUSTOM_SOUND_SET), label=COPY["custom-label"]))
    return row.model_copy(update={"kind": WidgetKind.CHOICE, "choices": choices})


def build(window: Any, *, backend: Any = None, probe: SchemaProbe | None = None) -> Any:
    """The Sound page.

    Args:
        window: the application window.
        backend: the settings backend. Defaults to the app's.
        probe: the window's schema probe.
    """
    settings = backend if backend is not None else get_backend()
    scanner = probe if probe is not None else SchemaProbe()

    rows = [
        sound_set_row(row, settings) if row.id == SOUND_SET_ROW else row
        for row in page_rows(PAGE_ID)
    ]

    sets = [row for row in rows if row.id == SOUND_SET_ROW]
    alerts = [row for row in rows if row.id in _ALERT_ROWS]
    when = [row for row in rows if row.id != SOUND_SET_ROW and row.id not in _ALERT_ROWS]

    return settings_page(
        window,
        PAGE_ID,
        [
            GroupSpec(COPY["sets-title"], COPY["sets-description"], sets),
            GroupSpec(COPY["when-title"], COPY["when-description"], when),
            GroupSpec(COPY["alerts-title"], COPY["alerts-description"], alerts),
        ],
        backend=settings,
        probe=scanner,
    )
