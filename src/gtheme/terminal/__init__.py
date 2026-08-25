"""Terminal and shell looks — one adapter per program gtheme can restyle.

The Terminal page shows a card per program that is actually installed, and
nothing at all for the ones that are not: a list of eight terminals with seven
of them greyed out is a list of things the user cannot do. :func:`installed`
is what the page asks.

Every adapter satisfies :class:`~gtheme.terminal.model.TerminalAdapter`, writes
through :mod:`gtheme.terminal.fsio` (atomic, confined to the destination root),
and carries its own honest answer to "when will I see this?".
"""

from __future__ import annotations

from collections.abc import Sequence

from gtheme.core.settings_backend import SettingsBackend

from .alacritty import AlacrittyAdapter
from .ghostty import GhosttyAdapter
from .model import Palette, ReloadSemantics, TerminalAdapter, TerminalState
from .monitors import BtopAdapter, CavaAdapter, FastfetchAdapter
from .prompt import FishAdapter, StarshipAdapter
from .ptyxis import PtyxisAdapter

__all__ = [
    "AlacrittyAdapter",
    "BtopAdapter",
    "CavaAdapter",
    "FastfetchAdapter",
    "FishAdapter",
    "GhosttyAdapter",
    "Palette",
    "PtyxisAdapter",
    "ReloadSemantics",
    "StarshipAdapter",
    "TerminalAdapter",
    "TerminalState",
    "adapters",
    "apply_all",
    "installed",
]


def adapters(backend: SettingsBackend | None = None) -> list[TerminalAdapter]:
    """Every adapter, in the order the page shows them.

    Args:
        backend: the settings seam. Ptyxis is settings-driven and is left out
            entirely when no backend is given, rather than being handed one it
            invented — an adapter that reaches the real store on its own is how
            a test ends up editing the desktop.
    """
    found: list[TerminalAdapter] = [GhosttyAdapter(), AlacrittyAdapter()]
    if backend is not None:
        found.insert(1, PtyxisAdapter(backend))
    found.extend(
        [
            FishAdapter(),
            StarshipAdapter(),
            BtopAdapter(),
            CavaAdapter(),
            FastfetchAdapter(),
        ]
    )
    return found


def installed(backend: SettingsBackend | None = None) -> list[TerminalAdapter]:
    """Only the adapters whose program is present on this machine."""
    return [adapter for adapter in adapters(backend) if adapter.detect().installed]


def apply_all(
    palette: Palette,
    chosen: Sequence[TerminalAdapter],
) -> dict[str, str | None]:
    """Apply one look to several programs, reporting each one separately.

    One program refusing — ghostty's config directory belonging to another tool
    is the case that actually happens — must not stop the rest, and must not be
    reported as success. The result maps each adapter's id to ``None`` when it
    worked, or to the sentence to show the user when it did not.
    """
    outcome: dict[str, str | None] = {}
    for adapter in chosen:
        try:
            adapter.apply(palette)
        except (PermissionError, OSError, ValueError) as exc:
            outcome[adapter.id] = str(exc)
        else:
            outcome[adapter.id] = None
    return outcome
