"""Console — GNOME's own small terminal, and the honest limit of what it offers.

Console (``kgx``) is what a fresh GNOME image opens today, so a Terminal page
that has never heard of it says "No command window found" to somebody who is
looking straight at their command window (persona-report §3.2). It appears here
for that reason. What it does *not* do is pretend to give it a look it cannot
take.

**Console does not have a palette gtheme may write.** Every other program in
this package stores a background, a foreground and sixteen colours that gtheme
can set. Console deliberately does not: its schema (``org.gnome.Console``)
carries a chosen colour scheme — one of the ones it ships, plus a
``custom-liveries`` dictionary of the user's own — and the colours themselves
live inside a nested value whose shape is Console's business and changes
between versions. gtheme could guess at that shape; a wrong guess writes
something the user cannot see the inside of, over the whole dictionary of any
custom schemes they made themselves, in a program this machine cannot even
check against. So it does not guess, and the card says which part of the look
Console will not be taking. Saying so is the honest half of DESIGN.md's rule
about never claiming a change that did not happen.

**What it can honestly do** is the see-through background: ``transparency`` is
a plain switch, it means exactly what a look's opacity means, and a look with a
glass terminal now gets one here too. Even that key is checked against the
schema on this machine first, because it has not always existed.
"""

from __future__ import annotations

import shutil

from gtheme.core.settings_backend import BackendError, SettingsBackend

from .model import Palette, ReloadSemantics, SettingChange, TerminalState, TerminalWrites

__all__ = ["SCHEMA", "TRANSPARENCY_KEY", "ConsoleAdapter"]

SCHEMA = "org.gnome.Console"

#: The one setting gtheme is willing to write here.
TRANSPARENCY_KEY = f"gsettings:{SCHEMA} transparency"

#: What the card says about the colours, in the user's words. Read out loud on
#: the page next to the reload sentence, so nobody expects the look's colours
#: to arrive here and then wonders why they did not.
COLOURS_NOTE = (
    "Console chooses its own colours to go with light or dark mode, so gtheme "
    "leaves those as they are. It can still make the background see-through to "
    "match the look."
)


class ConsoleAdapter:
    """Match Console's see-through background to the look. Nothing else.

    Args:
        backend: the settings seam. Required — this adapter is settings-only,
            and a backend it invented itself could reach the real store.
    """

    id = "console"
    name = "Console"
    reload_semantics = ReloadSemantics.LIVE

    def __init__(self, backend: SettingsBackend) -> None:
        self.backend = backend

    # -- the protocol ------------------------------------------------------

    def detect(self) -> TerminalState:
        installed = any(shutil.which(command) for command in ("kgx", "gnome-console"))
        notes = [self.reload_semantics.sentence(), COLOURS_NOTE]
        if installed and not self._writable():
            notes = [
                self.reload_semantics.sentence(),
                "gtheme could not read this program's settings, so it will not change them.",
            ]
        return TerminalState(
            installed=installed,
            config_path=None,
            foreign_root=None,
            current=None,
            notes=notes,
        )

    def current(self) -> Palette | None:
        """None, honestly: Console's colours are not gtheme's to read back.

        Reporting the look gtheme last applied would be a guess about a program
        that picks its own colours, and the Terminal page would then claim
        Console is wearing something it is not.
        """
        return None

    def plan(self, palette: Palette) -> TerminalWrites:
        """The see-through background, when this Console has that setting.

        Raises:
            PermissionError: this program's settings could not be read at all,
                so gtheme will not write into them blind.
        """
        if not self._writable():
            raise PermissionError(
                "gtheme could not read this program's settings, so it has not "
                "changed anything."
            )
        return TerminalWrites(
            settings=(
                SettingChange(TRANSPARENCY_KEY, "true" if palette.opacity < 1.0 else "false"),
            )
        )

    # -- helpers -----------------------------------------------------------

    def _writable(self) -> bool:
        """Is the one key gtheme writes in the schema on *this* machine?"""
        try:
            self.backend.get(TRANSPARENCY_KEY)
        except BackendError:
            return False
        return True
