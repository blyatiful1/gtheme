"""Ptyxis — GNOME's own terminal, themed through settings and a palette file.

Ptyxis is the well-behaved one: a palette is a small INI file dropped in a known
folder, and selecting it is a settings write that takes effect in windows that
are already open. Nothing has to be restarted and nothing has to be reloaded.

The one subtlety is *which* settings. Ptyxis keeps per-profile settings under a
relocatable schema — ``org.gnome.Ptyxis.Profile`` has no fixed path, one
instance per profile UUID — so the palette and the opacity are not addressable
until the default profile's UUID is known. v1 wrote that into presets as the
``{{ ptyxis_default_profile }}`` placeholder, resolved at apply time; the same
placeholder is honoured here, and :func:`profile_path` is what resolves it.

All settings traffic goes through the frozen :class:`SettingsBackend` seam, so
the unit tests write to an in-memory GSettings backend and the live desktop is
never involved.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from gtheme.core.gvariant import quote
from gtheme.core.settings_backend import BackendError, SettingsBackend

from .fsio import confine, data_root
from .model import (
    FileChange,
    Palette,
    ReloadSemantics,
    SettingChange,
    TerminalState,
    TerminalWrites,
    one_line,
    read_palette,
)

__all__ = [
    "PROFILE_PLACEHOLDER",
    "palette_file_name",
    "PROFILE_SCHEMA",
    "PtyxisAdapter",
    "profile_path",
    "render_palette_file",
]

#: The token v1 presets use, kept for compatibility with imported v1 themes.
PROFILE_PLACEHOLDER = "{{ ptyxis_default_profile }}"

#: Both spellings appear in the wild; presets are hand-written files.
_PLACEHOLDER_FORMS = (PROFILE_PLACEHOLDER, "{{ptyxis_default_profile}}")

SCHEMA = "org.gnome.Ptyxis"
PROFILE_SCHEMA = "org.gnome.Ptyxis.Profile"

_DEFAULT_PROFILE_KEY = f"gsettings:{SCHEMA} default-profile-uuid"


def palette_file_name(name: str) -> str:
    """A palette name safe to use as a file name.

    A palette name arrives from a preset — a file someone else wrote — so
    anything that could climb out of the palettes folder is stripped rather
    than trusted. The result is also what goes into the ``palette`` setting,
    because Ptyxis selects a palette by its file's name.
    """
    cleaned = "".join(c for c in name if c.isalnum() or c in " -_").strip()
    cleaned = cleaned.replace("..", "")
    return cleaned or "gtheme"


def profile_path(uuid: str) -> str:
    """The settings path for one profile. Always ends in ``/``, as GIO demands."""
    return f"/org/gnome/Ptyxis/Profiles/{uuid}/"


def profile_key(uuid: str, key: str) -> str:
    """A key string for one per-profile setting, in the frozen key grammar."""
    return f"gsettings-path:{PROFILE_SCHEMA}:{profile_path(uuid)} {key}"


def resolve_placeholders(text: str, uuid: str) -> str:
    """Replace ``{{ ptyxis_default_profile }}`` with a real profile UUID."""
    for form in _PLACEHOLDER_FORMS:
        text = text.replace(form, uuid)
    return text


def render_palette_file(palette: Palette) -> str:
    """A Ptyxis ``.palette`` file: INI, one section per light/dark.

    Ptyxis switches between the ``[Dark]`` and ``[Light]`` sections with the
    desktop's colour scheme, so both are written. gtheme palettes are a single
    set of colours, so both sections get the same values rather than gtheme
    inventing a light variant nobody asked for; a look that wants two of them
    ships two palettes.
    """
    # A .palette file is INI: one setting per line, no escaping anywhere. A
    # value carrying a newline would become a second setting, so every value is
    # refused rather than escaped if it could end its own line. Palette has
    # already refused it; this is the second lock on the same door.
    name = one_line(palette.name, what="the look name")
    background = one_line(palette.background, what="the background")
    foreground = one_line(palette.foreground, what="the text colour")
    cursor = one_line(palette.cursor or palette.foreground, what="the cursor colour")
    ansi = [
        one_line(colour, what=f"colour {index}")
        for index, colour in enumerate(palette.ansi or ())
    ]
    lines = [
        "# Written by gtheme.",
        "[Palette]",
        f"Name={name}",
        "",
    ]
    for section in ("Dark", "Light"):
        lines.append(f"[{section}]")
        lines.append(f"Background={background}")
        lines.append(f"Foreground={foreground}")
        lines.append(f"Cursor={cursor}")
        lines.append(f"CursorForeground={background}")
        for index, colour in enumerate(ansi):
            lines.append(f"Color{index}={colour}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


class PtyxisAdapter:
    """Restyle Ptyxis: drop a palette file, then select it for the profile.

    Args:
        backend: the settings seam. Required — this adapter is settings-first,
            and a backend it invented itself could reach the real store.
        palettes_dir: override where palette files go. Normally omitted.
    """

    id = "ptyxis"
    name = "Ptyxis"
    reload_semantics = ReloadSemantics.LIVE

    def __init__(
        self,
        backend: SettingsBackend,
        *,
        palettes_dir: Path | None = None,
    ) -> None:
        self.backend = backend
        self._palettes_dir = Path(palettes_dir) if palettes_dir is not None else None

    @property
    def palettes_dir(self) -> Path:
        if self._palettes_dir is not None:
            return self._palettes_dir
        return data_root() / "org.gnome.Ptyxis" / "palettes"

    # -- the protocol ------------------------------------------------------

    def default_profile_uuid(self) -> str | None:
        """The profile the user actually types into, or None if unreadable."""
        try:
            raw = self.backend.get(_DEFAULT_PROFILE_KEY)
        except BackendError:
            return None
        return raw.strip().strip("'\"") or None

    def detect(self) -> TerminalState:
        installed = shutil.which("ptyxis") is not None
        uuid = self.default_profile_uuid()
        notes = [self.reload_semantics.sentence()]
        if installed and uuid is None:
            notes.append(
                "gtheme could not read this terminal's settings, so it will not change them."
            )
        return TerminalState(
            installed=installed,
            config_path=self.palettes_dir if installed else None,
            foreign_root=None,
            current=self.current() if installed else None,
            notes=notes,
        )

    def current(self) -> Palette | None:
        uuid = self.default_profile_uuid()
        if uuid is None:
            return None
        name = self._get(profile_key(uuid, "palette"))
        if not name:
            return None
        opacity = 1.0
        raw_opacity = self._get(profile_key(uuid, "opacity"))
        if raw_opacity:
            try:
                opacity = float(raw_opacity)
            except ValueError:
                opacity = 1.0
        return self._read_palette_file(name, opacity)

    def plan(self, palette: Palette) -> TerminalWrites:
        """The palette file, and the two settings that select it.

        The file is listed first and the transaction writes files before
        settings, so the terminal is never briefly asked for a palette that is
        not on disk yet.

        The two settings used to be written straight through the backend, which
        is why an unwritable key ended a click with a traceback nobody saw and
        the palette file already on disk (review-report H12). They are ordinary
        settings, so they now go through the engine like every other setting in
        the app: recorded, claimed, and undoable.

        Raises:
            PermissionError: the default profile could not be determined, so
                there is nothing safe to write to.
        """
        uuid = self.default_profile_uuid()
        if uuid is None:
            raise PermissionError(
                "gtheme could not tell which terminal profile is in use, so it "
                "has not changed anything."
            )
        file_name = palette_file_name(palette.name)
        target = confine(self.palettes_dir / f"{file_name}.palette")
        return TerminalWrites(
            files=(FileChange(str(target), render_palette_file(palette).encode("utf-8")),),
            settings=(
                SettingChange(profile_key(uuid, "palette"), quote(file_name)),
                SettingChange(profile_key(uuid, "opacity"), repr(float(palette.opacity))),
            ),
        )

    # -- helpers -----------------------------------------------------------

    def _get(self, key: str) -> str | None:
        try:
            return self.backend.get(key).strip().strip("'\"") or None
        except BackendError:
            return None

    def _read_palette_file(self, name: str, opacity: float) -> Palette | None:
        path = self.palettes_dir / f"{name}.palette"
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        values = _read_section(text, "Dark")
        background = values.get("Background")
        foreground = values.get("Foreground")
        if not background or not foreground:
            return None
        ansi = tuple(values[f"Color{i}"] for i in range(16) if f"Color{i}" in values)
        return read_palette(
            name=name,
            background=background,
            foreground=foreground,
            cursor=values.get("Cursor"),
            ansi=ansi if len(ansi) == 16 else (),
            opacity=opacity,
        )


def _read_section(text: str, section: str) -> dict[str, str]:
    """The ``key=value`` pairs of one INI section, ignoring the rest."""
    values: dict[str, str] = {}
    inside = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            inside = line[1:-1].strip() == section
            continue
        if not inside or not line or line.startswith(("#", ";")):
            continue
        key, sep, value = line.partition("=")
        if sep:
            values[key.strip()] = value.strip()
    return values


