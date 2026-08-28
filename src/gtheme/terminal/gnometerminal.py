"""GNOME Terminal — the one Ubuntu still ships, themed through its profile.

The terminal a great many people actually have. Fedora Workstation moved to
Ptyxis and GNOME's own image now defaults to Console, but Ubuntu — the desktop
most first-time Linux users are handed — still ships GNOME Terminal, and gtheme
knew nothing about it: the Terminal page said "No command window found"
directly above a dropdown offering it (persona-report §3.2).

It works like Ptyxis in shape and not in detail. Colours live in the desktop's
own settings store under a **relocatable** schema — one instance of
``org.gnome.Terminal.Legacy.Profile`` per profile UUID, under
``/org/gnome/terminal/legacy/profiles:/:<uuid>/`` — so nothing is addressable
until the default profile's UUID is read out of
``org.gnome.Terminal.ProfilesList``. Changes show up in windows that are
already open.

Three things this adapter does not assume.

**That the profile is using its own colours at all.** ``use-theme-colors`` is
true by default, and while it is, the stored background and foreground are not
what is on the screen. So :meth:`GnomeTerminalAdapter.current` reports "gtheme
cannot tell" rather than reading back colours the terminal is ignoring, and
:meth:`GnomeTerminalAdapter.plan` turns the switch off in the same batch that
writes the colours — otherwise gtheme would write a look nobody could see.

**That every version has every key.** The transparency pair
(``use-transparent-background``, ``background-transparency-percent``) is not in
every build of the schema, and a distribution patch has moved it before. Each
key is checked against the schema on this machine before it is planned, and one
the schema does not have is simply left out — rather than failing the whole
batch on a key that was never there.

**That the UUID is a UUID.** It is read out of the settings store and pasted
into a settings path, so it is checked against the shape a UUID has before it
is used for anything.
"""

from __future__ import annotations

import re
import shutil

from gtheme.core.gvariant import format_string_list, parse_string_list, quote, unquote
from gtheme.core.settings_backend import BackendError, SettingsBackend

from .model import (
    Palette,
    ReloadSemantics,
    SettingChange,
    TerminalState,
    TerminalWrites,
    hex6,
    read_palette,
)

__all__ = [
    "LIST_SCHEMA",
    "PROFILE_SCHEMA",
    "PROFILES_PATH",
    "GnomeTerminalAdapter",
    "profile_key",
    "profile_path",
]

#: Where the list of profiles, and the name of the default one, live.
LIST_SCHEMA = "org.gnome.Terminal.ProfilesList"

#: The relocatable schema, one instance per profile.
PROFILE_SCHEMA = "org.gnome.Terminal.Legacy.Profile"

#: The settings path the profiles hang below. The colon is part of it — this is
#: GNOME Terminal's own spelling, not a typo.
PROFILES_PATH = "/org/gnome/terminal/legacy/profiles:/"

_DEFAULT_PROFILE_KEY = f"gsettings:{LIST_SCHEMA} default"

#: A profile identifier is a UUID and nothing else. It arrives from the
#: settings store and is pasted into a settings path, so it is checked rather
#: than trusted.
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")


def profile_path(uuid: str) -> str:
    """The settings path for one profile. Always ends in ``/``, as GIO demands."""
    return f"{PROFILES_PATH}:{uuid}/"


def profile_key(uuid: str, key: str) -> str:
    """A key string for one per-profile setting, in the frozen key grammar."""
    return f"gsettings-path:{PROFILE_SCHEMA}:{profile_path(uuid)} {key}"


class GnomeTerminalAdapter:
    """Restyle GNOME Terminal by writing its default profile's colours.

    Args:
        backend: the settings seam. Required — this adapter is settings-only,
            and a backend it invented itself could reach the real store.
    """

    id = "gnome-terminal"
    name = "GNOME Terminal"
    reload_semantics = ReloadSemantics.LIVE

    def __init__(self, backend: SettingsBackend) -> None:
        self.backend = backend

    # -- the protocol ------------------------------------------------------

    def default_profile_uuid(self) -> str | None:
        """The profile new windows use, or None when it cannot be read."""
        raw = self._get(_DEFAULT_PROFILE_KEY)
        if raw is None:
            return None
        return raw if _UUID_RE.match(raw) else None

    def detect(self) -> TerminalState:
        installed = shutil.which("gnome-terminal") is not None
        uuid = self.default_profile_uuid() if installed else None
        notes = [self.reload_semantics.sentence()]
        if installed and uuid is None:
            notes.append(
                "gtheme could not read this terminal's settings, so it will not change them."
            )
        return TerminalState(
            installed=installed,
            config_path=None,
            foreign_root=None,
            current=self.current() if installed else None,
            notes=notes,
        )

    def current(self) -> Palette | None:
        """The colours the profile is wearing, when it is wearing its own.

        While ``use-theme-colors`` is on, the stored colours are not the ones on
        the screen — so the honest answer is that gtheme cannot tell, not the
        pair of values the terminal is currently ignoring.
        """
        uuid = self.default_profile_uuid()
        if uuid is None or self._flag(uuid, "use-theme-colors", default=True):
            return None
        background = self._value(uuid, "background-color")
        foreground = self._value(uuid, "foreground-color")
        if not background or not foreground:
            return None
        ansi = parse_string_list(self._get(profile_key(uuid, "palette"))) or []
        return read_palette(
            name=self._value(uuid, "visible-name") or "Your own colours",
            background=background,
            foreground=foreground,
            cursor=self._value(uuid, "cursor-background-color"),
            ansi=tuple(ansi) if len(ansi) == 16 else (),
            opacity=self._opacity(uuid),
        )

    def plan(self, palette: Palette) -> TerminalWrites:
        """Every colour the default profile understands, and nothing else.

        Raises:
            PermissionError: the default profile could not be read, so there is
                nothing safe to write to.
        """
        uuid = self.default_profile_uuid()
        if uuid is None:
            raise PermissionError(
                "gtheme could not tell which terminal profile is in use, so it "
                "has not changed anything."
            )
        background = hex6(palette.background)
        foreground = hex6(palette.foreground)
        cursor = hex6(palette.cursor or palette.foreground)

        wanted: list[tuple[str, str]] = [
            # First, or the colours below are stored and ignored.
            ("use-theme-colors", "false"),
            ("background-color", quote(background)),
            ("foreground-color", quote(foreground)),
            ("bold-color-same-as-fg", "true"),
            ("cursor-colors-set", "true"),
            ("cursor-background-color", quote(cursor)),
            ("cursor-foreground-color", quote(background)),
        ]
        if len(palette.ansi) == 16:
            wanted.append(("palette", format_string_list([hex6(c) for c in palette.ansi])))
        see_through = palette.opacity < 1.0
        wanted.append(("use-transparent-background", "true" if see_through else "false"))
        if see_through:
            # The setting is how *transparent* the background is, which is the
            # other way round from a look's opacity.
            wanted.append(
                ("background-transparency-percent", str(round((1.0 - palette.opacity) * 100)))
            )
        changes = tuple(
            SettingChange(profile_key(uuid, key), value)
            for key, value in wanted
            if self._has(profile_key(uuid, key))
        )
        if not changes:
            # Not one colour key answered. Whatever this schema is, it is not
            # the one this adapter knows, and reporting "Done" over a profile
            # nothing was written to would be the lie the page exists to avoid.
            raise PermissionError(
                "gtheme could not read this terminal's settings, so it has not "
                "changed anything."
            )
        return TerminalWrites(settings=changes)

    # -- helpers -----------------------------------------------------------

    def _get(self, key: str) -> str | None:
        try:
            return unquote(self.backend.get(key)).strip() or None
        except BackendError:
            return None

    def _has(self, key: str) -> bool:
        """Is this key in the schema on *this* machine?

        A key the schema does not have cannot be written, and asking the engine
        to write it would fail the whole batch — including the keys that do
        exist. Every version of the profile schema has the colour keys; the
        transparency pair is the one that moves.
        """
        try:
            self.backend.get(key)
        except BackendError:
            return False
        return True

    def _value(self, uuid: str, key: str) -> str | None:
        return self._get(profile_key(uuid, key))

    def _flag(self, uuid: str, key: str, *, default: bool) -> bool:
        raw = self._value(uuid, key)
        if raw is None:
            return default
        return raw.strip().lower() == "true"

    def _opacity(self, uuid: str) -> float:
        if not self._flag(uuid, "use-transparent-background", default=False):
            return 1.0
        raw = self._value(uuid, "background-transparency-percent")
        try:
            percent = float(raw) if raw is not None else 0.0
        except ValueError:
            return 1.0
        return min(max(1.0 - percent / 100.0, 0.0), 1.0)
