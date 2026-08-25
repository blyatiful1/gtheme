"""Night Light & Timing — warmer colours in the evening, and when.

Five settings, and one of them is the reason this page exists as its own page
rather than a group somewhere else: the start and end times are stored as
*fractions of an hour*. ``20.25`` means quarter past eight in the evening. A
spin button showing "20.25" is a control a person has to decode, so the row's
explanation carries the time in the words on a clock — "Set to 8:15 pm" — and
follows the number as it moves.

The bounds are not this page's invention. GNOME's own settings put no range on
either the times or the colour temperature: they will accept a start hour of
forty and a temperature of twelve, and the desktop will do something nobody can
undo through its own Settings app. ``panels.widgets.KNOWN_CLAMPS`` records what
gtheme promises instead — hours below 24, temperature between 1700 and 4700 —
and the descriptor carries those bounds. This page widens neither.
"""

from __future__ import annotations

from typing import Any

from ...core.backends import get_backend
from ...panels.descriptor import Row
from ...panels.schema_probe import SchemaProbe
from ..search import GroupSpec, page_rows, settings_page

__all__ = ["COPY", "SCHEDULE_ROWS", "build", "clock_time"]

PAGE_ID = "nightlight"

#: Every sentence this page writes itself. Kept together so the
#: plain-language lint can read them and so nothing is worded twice.
COPY: dict[str, str] = {
    "switch-title": "Warmer colours",
    "switch-description": (
        "In the evening your screen can shift towards orange, which many people "
        "find easier on the eyes. Nothing here changes what your screen can show "
        "— only how warm it looks."
    ),
    "schedule-title": "When",
    "schedule-description": (
        "Follow the sun where you are, or pick your own times. The times below "
        "are only used when you are not following the sun."
    ),
    "set-to": "Set to {time}.",
}

#: The two settings stored as a fraction of an hour rather than as a time.
SCHEDULE_ROWS: frozenset[str] = frozenset(
    {
        "org.gnome.settings-daemon.plugins.color:night-light-schedule-from",
        "org.gnome.settings-daemon.plugins.color:night-light-schedule-to",
    }
)

#: Which rows belong under "When". Everything else goes under "Warmer colours".
_SCHEDULE_GROUP: frozenset[str] = SCHEDULE_ROWS | {
    "org.gnome.settings-daemon.plugins.color:night-light-schedule-automatic",
}


def clock_time(hours: float) -> str:
    """``20.25`` becomes ``"8:15 pm"``. The whole point of this module.

    Values outside a day are wrapped rather than rejected: the desktop may
    already hold one (nothing stopped it), and showing "8:15 pm" for 44.25 is a
    better answer than showing nothing at all while the number sits there.
    """
    total = int(round(hours * 60)) % (24 * 60)
    hour, minute = divmod(total, 60)
    suffix = "am" if hour < 12 else "pm"
    display = hour % 12 or 12
    return f"{display}:{minute:02d} {suffix}"


def _describe_time(row: Row, widget: Any) -> None:
    """Keep a schedule row's explanation showing the time it is set to."""
    base = row.subtitle

    def update(*_args: Any) -> None:
        widget.set_subtitle(f"{base} {COPY['set-to'].format(time=clock_time(widget.get_value()))}")

    update()
    widget.connect("notify::value", update)


def build(window: Any, *, backend: Any = None, probe: SchemaProbe | None = None) -> Any:
    """The Night Light & Timing page.

    Args:
        window: the application window. Rows register themselves in its row
            index so search can deep-link to them.
        backend: the settings backend. Defaults to the app's — a page never
            constructs one, so a test can hand it a memory backend.
        probe: the window's schema probe. One per window; until the integration
            wave shares it, a page makes its own.
    """
    settings = backend if backend is not None else get_backend()
    scanner = probe if probe is not None else SchemaProbe()
    rows = page_rows(PAGE_ID)
    by_id = {row.id: row for row in rows}

    page = settings_page(
        window,
        PAGE_ID,
        [
            GroupSpec(
                COPY["switch-title"],
                COPY["switch-description"],
                [row for row in rows if row.id not in _SCHEDULE_GROUP],
            ),
            GroupSpec(
                COPY["schedule-title"],
                COPY["schedule-description"],
                [row for row in rows if row.id in _SCHEDULE_GROUP],
            ),
        ],
        backend=settings,
        probe=scanner,
    )

    index = getattr(window, "rows", None)
    if index is not None:
        for descriptor_id in SCHEDULE_ROWS:
            entry = index.lookup(descriptor_id)
            row = by_id.get(descriptor_id)
            # A greyed row has no value to describe and no adjustment to follow.
            if entry is None or row is None or not hasattr(entry.widget, "get_value"):
                continue
            _describe_time(row, entry.widget)
    return page
