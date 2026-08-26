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

**A palette value is untrusted text.** A Look's ``[palette]`` table is written
by whoever made the Look, and the colours in it end up interpolated into other
programs' settings files — several of which can name a command to run. A value
like ``#fff"\\n[custom.pwn]\\ncommand = "id"`` closes gtheme's quote and opens a
table of its own, and starship then runs that command on every prompt. The
whole point of the preset format refusing to hold code (DESIGN.md F, no
``[hooks]``, ``extra='forbid'``, "nothing is executed") is lost if a colour can
smuggle it in. So this module is where a colour has to *be* a colour:
:class:`Palette` refuses anything that is not one, before any adapter sees it,
and the writers escape or refuse a second time on the way out.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

__all__ = [
    "Palette",
    "ReloadSemantics",
    "TerminalAdapter",
    "TerminalState",
    "check_colour",
    "check_name",
    "is_colour",
    "one_line",
    "read_palette",
    "toml_string",
]

#: What gtheme will accept as a colour: ``#rgb``, ``#rrggbb`` or ``#rrggbbaa``,
#: with the hash optional because ghostty and fish both write it bare.
HEX_COLOUR_RE = re.compile(r"^#?(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")

#: Characters that end a line, or that no settings file should be asked to hold.
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")

#: A look's name goes into file names and into comment lines. Nothing long
#: enough to be a payload, and nothing that can start a second line.
_MAX_NAME = 200


def is_colour(value: object) -> bool:
    """Whether ``value`` is a colour gtheme is willing to write anywhere."""
    return isinstance(value, str) and bool(HEX_COLOUR_RE.match(value))


def check_colour(value: object, *, what: str = "colour") -> str:
    """``value``, if it is a colour. Otherwise refuse, by name.

    Raises:
        ValueError: it is not a colour. The message is the one the user sees
            when a Look is refused, so it says which value was wrong.
    """
    if not is_colour(value):
        raise ValueError(
            f"{what} is not a colour gtheme will write into a settings file: {value!r}"
        )
    return str(value)


def check_name(value: object) -> str:
    """A look's name, if it is safe to put in a file. Otherwise refuse.

    Raises:
        ValueError: the name is empty, absurdly long, or holds a character that
            would start a new line in a config file — which is how a name, not
            just a colour, could smuggle a setting in.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"a look needs a name gtheme can write down, got {value!r}")
    if len(value) > _MAX_NAME:
        raise ValueError(
            f"that look's name is too long to write into a settings file ({len(value)} characters)"
        )
    if _CONTROL_RE.search(value):
        raise ValueError(
            f"that look's name has characters gtheme will not write into a "
            f"settings file: {value!r}"
        )
    return value


def one_line(value: str, *, what: str = "value", forbid: str = "") -> str:
    """``value``, if it fits on one line of a settings file. Otherwise refuse.

    The second layer. ghostty, btop, cava and Ptyxis all read line-shaped files
    with no escaping to speak of, so there is nothing to escape *into*: a value
    that could end the line early is refused here even though
    :class:`Palette` should already have refused it.

    Args:
        forbid: extra characters this particular file cannot hold — the quote
            btop wraps its values in, the apostrophe cava uses.

    Raises:
        ValueError: the value could break the line it is written on.
    """
    if _CONTROL_RE.search(value) or any(char in value for char in forbid):
        raise ValueError(f"{what} cannot be written into a settings file: {value!r}")
    return value


def toml_string(value: str) -> str:
    """``value`` as a TOML basic string, quotes included.

    The second layer for the TOML files (starship, alacritty). Unlike a
    line-shaped file, TOML *can* hold anything once it is escaped — so this
    escapes rather than refuses, and a value that somehow reached a writer
    unvalidated lands as a harmless string instead of a new table.
    """
    out = value.replace("\\", "\\\\").replace('"', '\\"')
    out = out.replace("\b", "\\b").replace("\t", "\\t").replace("\n", "\\n")
    out = out.replace("\f", "\\f").replace("\r", "\\r")
    out = _CONTROL_RE.sub(lambda m: f"\\u{ord(m.group(0)):04X}", out)
    return f'"{out}"'


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
    #: The program is not running: it prints once and exits. There is nothing
    #: to reload — the next run picks the change up.
    ONE_SHOT = "one-shot"

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
            ReloadSemantics.ONE_SHOT: "Run it again to see this.",
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
        """Refuse anything that is not a palette, before an adapter can write it.

        This is the choke point named in DESIGN.md F: the values come from a
        Look someone else wrote, and the adapters interpolate them into other
        programs' settings — starship's file can name a command to run. A
        colour that is not a colour is refused here, so no writer has to be
        trusted to escape it (they escape it anyway; see :func:`toml_string`).

        Raises:
            ValueError: a value is not a colour, the name cannot be written
                into a file, the ANSI list is the wrong length, or the opacity
                is out of range. Reading a palette back out of a config file
                goes through :func:`read_palette`, which turns this into "gtheme
                cannot tell" rather than an error.
        """
        if self.ansi and len(self.ansi) != 16:
            raise ValueError(f"{self.name}: an ANSI palette has 16 colours, got {len(self.ansi)}")
        if not isinstance(self.opacity, int | float) or isinstance(self.opacity, bool):
            raise ValueError(f"{self.name}: opacity must be a number, got {self.opacity!r}")
        if not 0.0 <= self.opacity <= 1.0:
            raise ValueError(f"{self.name}: opacity must be between 0 and 1")
        check_name(self.name)
        check_colour(self.background, what="the background")
        check_colour(self.foreground, what="the text colour")
        if self.cursor is not None:
            check_colour(self.cursor, what="the cursor colour")
        for index, colour in enumerate(self.ansi):
            check_colour(colour, what=f"colour {index}")


def read_palette(**fields: object) -> Palette | None:
    """A palette read back out of a config file, or None when it is not one.

    Reading is never a reason to refuse. A hand-written config may hold a
    colour name gtheme does not speak, and the honest answer to "what look is
    this terminal wearing?" is then "gtheme cannot tell" — not a traceback on
    the page that asked.
    """
    try:
        return Palette(**fields)  # type: ignore[arg-type]
    except ValueError:
        return None


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
