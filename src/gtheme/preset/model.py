"""Preset format v2 — "a Look" — as pydantic models.

THE CONTRACT IS FROZEN. Field names here are the on-disk format; renaming one
invalidates every published Look. ``extra='forbid'`` everywhere is deliberate:
a typo in a hand-written ``theme.toml`` must be an error the author sees, not a
silently ignored line. It is also what makes the removal of hooks *provable* —
a v1 file with a ``[hooks]`` section does not validate as v2, so there is no
path by which a Look can smuggle a command onto someone's machine.

The JSON Schema published in ``docs/`` is generated from these classes by
``tools/gen_schema.py`` and a freshness test fails if it drifts.

Sketch of the format::

    format = 2

    [meta]
    name = "nightbloom"
    title = "NIGHTBLOOM"
    description = "A solarpunk glasshouse at dusk."
    author = "blyatiful1"
    version = "1.0.0"
    min_shell = "49"
    screenshots = ["screenshots/desktop-light.png"]   # required to publish

    [palette]
    bg = "#101a14"
    accent = "#7fd6a2"

    [[files]]
    src = "ghostty/config"
    dest = "~/.config/ghostty/config"
    template = true

    [[settings]]
    key = "gsettings:org.gnome.desktop.interface color-scheme"
    value = "'prefer-dark'"
    component = "colors"

    [extensions]
    enable = ["blur-my-shell@aunetx"]

    [[extensions.install]]
    uuid = "blur-my-shell@aunetx"
    source = "ego"
    ego_pk = 3193

    [[extensions.settings]]
    uuid = "blur-my-shell@aunetx"
    schema_id = "org.gnome.shell.extensions.blur-my-shell.panel"
    key = "blur"
    value = "true"
"""

from __future__ import annotations

import enum
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

__all__ = [
    "Component",
    "ExtensionInstallEntry",
    "ExtensionSetting",
    "ExtensionsBlock",
    "FileEntry",
    "Meta",
    "Preset",
    "SettingEntry",
    "format_validation_errors",
    "load_preset_dir",
]

#: The file a Look is defined in. Fixed name; the folder name is the Look's id.
PRESET_FILENAME = "theme.toml"


class Component(enum.StrEnum):
    """The closed registry of "parts of the desktop" a change can belong to.

    This drives how a change is *described*, never what is written. It is a
    closed set so that the preview dialog can be exhaustive: every setting a
    Look touches has to fall into one of these buckets, which is what lets the
    diff be summarised as "Wallpaper, highlight colour, icons, and 3 add-ons"
    instead of as a list of key names.
    """

    WALLPAPER = "wallpaper"
    COLORS = "colors"
    ICONS = "icons"
    CURSOR = "cursor"
    FONTS = "fonts"
    SHELL_THEME = "shell-theme"
    TOPBAR = "topbar"
    WINDOWS = "windows"
    WORKSPACES = "workspaces"
    ANIMATIONS = "animations"
    NIGHT_LIGHT = "night-light"
    SOUND = "sound"
    POWER = "power"
    TERMINAL = "terminal"
    ADDONS = "addons"
    PRIVACY = "privacy"
    ACCESSIBILITY = "accessibility"
    OTHER = "other"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Meta(_Strict):
    """Who made this Look, what it is called, and what it looks like."""

    name: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    title: str
    description: str
    author: str
    version: str
    #: Lowest GNOME Shell major version this Look was built against, as a
    #: string ("49"). Compared numerically; a Look never *blocks* on it, the
    #: app just warns that parts may not apply.
    min_shell: str | None = None
    #: Pictures of this Look, relative to its folder.
    #:
    #: Empty is allowed *here* and forbidden at PUBLISH time — a Look with no
    #: picture cannot be previewed, and an unpreviewable Look is exactly what
    #: this app exists to spare people (DESIGN.md A8). But the same model also
    #: describes a restore point, and a restore point is written by machine
    #: from a desktop that may have no wallpaper file to photograph. Requiring
    #: a picture in the model meant every such capture had to name a file it
    #: had not written, which then failed the loader's own missing-picture
    #: warning. The requirement lives in ``tools/build_index.py`` instead,
    #: which is the gate a Look actually crosses to reach the community index.
    screenshots: list[str] = Field(default_factory=list)


class FileEntry(_Strict):
    """One file the Look writes and thereby owns."""

    src: str
    dest: str
    mode: str | None = Field(default=None, pattern=r"^0[0-7]{3}$")
    template: bool = False
    merge: Literal["none"] = "none"


class SettingEntry(_Strict):
    """One desktop setting the Look writes."""

    #: Key string in the grammar frozen in ``core.settings_backend``.
    key: str
    #: GVariant text, exactly as ``Variant.print_(True)`` renders it. Quoting
    #: matters: a string value is ``"'Adwaita'"``, an empty string list is
    #: ``"@as []"``.
    value: str
    merge: Literal["none", "list-union"] = "none"
    component: Component = Component.OTHER


class ExtensionSetting(_Strict):
    """A setting belonging to one add-on.

    Addressed by ``(schema_id, key)`` rather than by key alone, because several
    add-ons split their settings across child schemas — blur-my-shell has eight
    of them, and ``blur`` means something different in each.
    """

    uuid: str
    schema_id: str
    key: str
    value: str
    #: Instance path for a relocatable schema (burn-my-windows profiles). When
    #: set it must start and end with "/".
    path: str | None = None

    @field_validator("path")
    @classmethod
    def _path_shape(cls, v: str | None) -> str | None:
        if v is not None and not (v.startswith("/") and v.endswith("/")):
            raise ValueError("a relocatable schema path must start and end with '/'")
        return v


class ExtensionInstallEntry(_Strict):
    """Where an add-on comes from, when it is not already installed."""

    uuid: str
    #: DESIGN.md F12. ``ego`` may be offered for download from
    #: extensions.gnome.org; ``local-only`` is a private add-on that must
    #: already be present, and whose absence produces a named skip warning
    #: rather than an error. A community Look never bundles extension code.
    source: Literal["ego", "local-only"] = "ego"
    ego_pk: int | None = None
    #: Other uuids that satisfy the same need; the first present one wins.
    alternates: list[str] = Field(default_factory=list)


class ExtensionsBlock(_Strict):
    """Which add-ons the Look wants, and how they are configured."""

    enable: list[str] = Field(default_factory=list)
    install: list[ExtensionInstallEntry] = Field(default_factory=list)
    settings: list[ExtensionSetting] = Field(default_factory=list)

    @model_validator(mode="after")
    def _uuids_are_declared(self) -> ExtensionsBlock:
        known = set(self.enable)
        for entry in self.install:
            if entry.uuid not in known:
                raise ValueError(
                    f"[[extensions.install]] names {entry.uuid!r}, which is not in "
                    "extensions.enable"
                )
        for setting in self.settings:
            if setting.uuid not in known:
                raise ValueError(
                    f"[[extensions.settings]] names {setting.uuid!r}, which is not in "
                    "extensions.enable"
                )
        seen: set[str] = set()
        for entry in self.install:
            if entry.uuid in seen:
                raise ValueError(f"two [[extensions.install]] entries for {entry.uuid!r}")
            seen.add(entry.uuid)
        return self

    def install_for(self, uuid: str) -> ExtensionInstallEntry:
        """Install metadata for a uuid, defaulted when the Look omitted it."""
        for entry in self.install:
            if entry.uuid == uuid:
                return entry
        return ExtensionInstallEntry(uuid=uuid)


class Preset(_Strict):
    """A Look. The whole on-disk format, in one class."""

    #: Always 2. v1 files are converted by ``preset.v1_import``; they do not
    #: stay valid, because staying valid would mean keeping hooks.
    format: Literal[2]
    meta: Meta
    palette: dict[str, str] = Field(default_factory=dict)
    files: list[FileEntry] = Field(default_factory=list)
    settings: list[SettingEntry] = Field(default_factory=list)
    extensions: ExtensionsBlock = Field(default_factory=ExtensionsBlock)


def load_preset_dir(directory: str | Path) -> Preset:
    """Load and validate the ``theme.toml`` in a Look's folder.

    Raises:
        FileNotFoundError: no ``theme.toml`` there.
        ValueError: the file is not valid TOML, or not a valid v2 Look. A
            pydantic ``ValidationError`` is a ``ValueError``, so callers catch
            the one type and hand it to :func:`format_validation_errors`.
    """
    path = Path(directory) / PRESET_FILENAME
    if not path.is_file():
        raise FileNotFoundError(f"{path} does not exist — a Look needs a {PRESET_FILENAME}")
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{path} is not valid TOML: {exc}") from exc
    return Preset.model_validate(raw)


def format_validation_errors(exc: Exception) -> list[str]:
    """Turn a validation failure into lines an author can act on."""
    if not isinstance(exc, ValidationError):
        return [str(exc)]
    lines = []
    for err in exc.errors():
        where = ".".join(str(p) for p in err["loc"]) or "(top level)"
        lines.append(f"{where}: {err['msg']}")
    return lines
