"""What a terminal adapter has to be able to do.

THE CONTRACT IS FROZEN (DESIGN.md C3f). Four terminals plus two prompts are in
scope and they agree on almost nothing: ghostty is a ``key = value`` file that
does not reload itself, ptyxis stores per-profile settings in the desktop's own
settings store and applies them live, alacritty watches its file and reloads,
fish keeps colours in shell variables that exist only while it is running. The
protocol below is the smallest shape all of them fit.

Two rules that come out of the research and are part of the contract:

* **``reload_semantics`` is not decoration.** It is what the UI says out loud
  after applying. Telling someone their terminal changed when it will not
  change until they restart it is the kind of small lie that makes a person
  stop trusting the whole app.
* **A config directory that resolves outside the user's own config directory is
  refused by default** (DESIGN.md F7). On this machine ``~/.config/ghostty`` is
  a symlink into a separate rice repository; writing through it would silently
  edit a git working tree the user maintains by hand. The adapter must
  ``realpath`` the *directory*, and when it points elsewhere, say so and ask,
  rather than write.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

__all__ = [
    "Palette",
    "ReloadSemantics",
    "TerminalAdapter",
    "TerminalState",
]


class ReloadSemantics(enum.Enum):
    """When a change actually shows up, in the user's terms."""

    #: The change appears immediately in windows that are already open.
    LIVE = "live"
    #: The terminal watches its own settings file and picks the change up
    #: within a second or so.
    AUTO_RELOAD = "auto-reload"
    #: The user has to press the terminal's reload command, or use its menu.
    MANUAL_RELOAD = "manual-reload"
    #: Only new windows get it; the ones already open keep the old look.
    NEW_WINDOWS = "new-windows"
    #: The program has to be closed and started again.
    RESTART = "restart"

    def sentence(self) -> str:
        """One line for the UI, in plain words."""
        return {
            ReloadSemantics.LIVE: "This shows up straight away.",
            ReloadSemantics.AUTO_RELOAD: "This shows up in a moment.",
            ReloadSemantics.MANUAL_RELOAD: (
                "Open windows keep the old look until you tell the terminal to reload."
            ),
            ReloadSemantics.NEW_WINDOWS: "Windows you open from now on will use it.",
            ReloadSemantics.RESTART: "Close the program and open it again to see this.",
        }[self]


@dataclass(frozen=True)
class Palette:
    """The colours a terminal look is made of.

    Args:
        name: what to call this look.
        background: background colour, ``#rrggbb``.
        foreground: normal text colour.
        cursor: cursor colour; defaults to the foreground when absent.
        ansi: the sixteen ANSI colours in canonical order (black, red, green,
            yellow, blue, magenta, cyan, white, then the eight bright ones).
        opacity: 0.0 (invisible) to 1.0 (solid). Not every terminal can do it.
    """

    name: str
    background: str
    foreground: str
    cursor: str | None = None
    ansi: tuple[str, ...] = ()
    opacity: float = 1.0

    def __post_init__(self) -> None:
        if self.ansi and len(self.ansi) != 16:
            raise ValueError(f"{self.name}: an ANSI palette has 16 colours, got {len(self.ansi)}")
        if not 0.0 <= self.opacity <= 1.0:
            raise ValueError(f"{self.name}: opacity must be between 0 and 1")


@dataclass
class TerminalState:
    """What an adapter found on this machine.

    Args:
        installed: the program is present.
        config_path: the file or directory its settings live in, if any.
        foreign_root: set when ``config_path`` resolves outside the user's own
            settings folder — the F7 case. The UI must ask before writing.
        current: the look currently in effect, when it can be determined.
        notes: anything the user should be told, in plain words.
    """

    installed: bool
    config_path: Path | None = None
    foreign_root: Path | None = None
    current: Palette | None = None
    notes: list[str] = field(default_factory=list)


@runtime_checkable
class TerminalAdapter(Protocol):
    """One terminal or prompt gtheme can restyle."""

    #: Stable identifier: ``"ghostty"``, ``"ptyxis"``, ``"fish"``.
    id: str
    #: What the user calls it. Shown on the card.
    name: str
    #: When a change takes effect. Surfaced verbatim after applying.
    reload_semantics: ReloadSemantics

    def detect(self) -> TerminalState:
        """Look for the program and its settings. Never writes anything."""
        ...

    def current(self) -> Palette | None:
        """The look in effect now, or None if it cannot be determined."""
        ...

    def apply(self, palette: Palette) -> None:
        """Write the look.

        Must be atomic, must preserve settings gtheme does not understand
        (a hand-written file keeps its unknown lines and its comments), and
        must refuse a foreign config root unless the user opted in.

        Raises:
            PermissionError: the settings are managed elsewhere and the user
                has not taken them over (the F7 refusal).
        """
        ...
