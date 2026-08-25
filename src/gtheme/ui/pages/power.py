"""Power & Screen — when the screen dims, when it sleeps, when it locks.

Thirteen settings that a person thinks of as three questions: what happens to
the screen, what happens to the computer, and whether it asks for a password
afterwards. They are grouped that way here rather than by which part of the
desktop happens to own them — two of the three groups are drawn from settings
that live in three different places, and nobody using this page cares.

The one thing this page adds beyond grouping is a warning that is a
*consequence*, not a mechanism: a computer set to lock straight away with the
screen turning off after a minute will ask for a password constantly, and that
combination is chosen by accident. Saying so where it happens costs one
sentence and saves an afternoon.
"""

from __future__ import annotations

from typing import Any

from ...core.backends import get_backend
from ...core.settings_backend import BackendError
from ...panels.schema_probe import SchemaProbe
from ..search import GroupSpec, bare_number, page_rows, settings_page

__all__ = ["COPY", "build", "lock_warning"]

PAGE_ID = "power"

COPY: dict[str, str] = {
    "screen-title": "The screen",
    "screen-description": (
        "What happens to the picture when you stop using the computer. None of this "
        "closes anything you have open."
    ),
    "sleep-title": "The computer",
    "sleep-description": (
        "What the computer itself does after a long spell of nobody touching it. "
        "Going to sleep is the quick one to wake from; switching off is not."
    ),
    "lock-title": "Locking",
    "lock-description": (
        "Whether you have to type your password again after the screen has gone "
        "dark, and how long the computer waits before asking."
    ),
    "lock-warning": (
        "With these settings your computer will ask for your password within a "
        "minute of you looking away. Give it longer before it locks if that "
        "becomes annoying."
    ),
}

_SCREEN_ROWS: tuple[str, ...] = (
    "org.gnome.desktop.session:idle-delay",
    "org.gnome.settings-daemon.plugins.power:idle-dim",
    "org.gnome.settings-daemon.plugins.power:idle-brightness",
    "org.gnome.settings-daemon.plugins.power:ambient-enabled",
)

_LOCK_ROWS: tuple[str, ...] = (
    "org.gnome.desktop.screensaver:lock-enabled",
    "org.gnome.desktop.screensaver:lock-delay",
    "org.gnome.desktop.screensaver:idle-activation-enabled",
)

#: How soon "the screen goes dark and it locks straight away" counts as a
#: combination worth mentioning. Two minutes: below that, a person who looks
#: out of the window is typing their password again when they look back.
_NAGGING_SECONDS = 120


def _number(backend: Any, key: str) -> float | None:
    """A setting's value as a number. Both delays here are ``uint32`` keys,
    which the settings store prints as ``"uint32 300"`` — see
    :func:`gtheme.ui.search.bare_number`."""
    try:
        return float(bare_number(backend.get(key)).strip())
    except (BackendError, ValueError):
        return None


def _flag(backend: Any, key: str) -> bool | None:
    try:
        return backend.get(key).strip() == "true"
    except BackendError:
        return None


def lock_warning(backend: Any) -> str | None:
    """The sentence to show when this computer will nag for a password.

    Returns None when the combination is fine, which is the usual answer. Pure
    enough to test without a widget, which is why it is a function and not four
    lines inside :func:`build`.
    """
    if not _flag(backend, "gsettings:org.gnome.desktop.screensaver lock-enabled"):
        return None
    blank = _number(backend, "gsettings:org.gnome.desktop.session idle-delay")
    delay = _number(backend, "gsettings:org.gnome.desktop.screensaver lock-delay")
    if blank is None or delay is None:
        return None
    # A blank delay of zero means "never turn the screen off", so the lock
    # never fires on idle either and there is nothing to warn about.
    if blank == 0:
        return None
    if blank + delay <= _NAGGING_SECONDS:
        return COPY["lock-warning"]
    return None


def build(window: Any, *, backend: Any = None, probe: SchemaProbe | None = None) -> Any:
    """The Power & Screen page.

    Args:
        window: the application window.
        backend: the settings backend. Defaults to the app's.
        probe: the window's schema probe.
    """
    settings = backend if backend is not None else get_backend()
    scanner = probe if probe is not None else SchemaProbe()
    rows = page_rows(PAGE_ID)
    by_id = {row.id: row for row in rows}

    def take(ids: tuple[str, ...]) -> list[Any]:
        return [by_id[descriptor_id] for descriptor_id in ids if descriptor_id in by_id]

    placed = set(_SCREEN_ROWS) | set(_LOCK_ROWS)
    # Everything the corpus has that this page did not name goes under "The
    # computer". A row that exists in the data and on no group would be a
    # setting silently dropped, which is the one outcome the floor page and the
    # coverage test exist to prevent.
    sleep = [row for row in rows if row.id not in placed]

    # The warning goes above everything, because it is about a combination of
    # two of the groups below and is only useful before they are read.
    top = []
    warning = lock_warning(settings)
    if warning:
        from ..widgets.rows import warn_banner

        top.append(warn_banner(warning))

    return settings_page(
        window,
        PAGE_ID,
        [
            GroupSpec(COPY["screen-title"], COPY["screen-description"], take(_SCREEN_ROWS)),
            GroupSpec(COPY["sleep-title"], COPY["sleep-description"], sleep),
            GroupSpec(COPY["lock-title"], COPY["lock-description"], take(_LOCK_ROWS)),
        ],
        backend=settings,
        probe=scanner,
        top=top,
    )
