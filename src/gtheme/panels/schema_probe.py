"""Finding an add-on's settings, and admitting when they are not there.

A descriptor names a ``(schema_id, key)`` pair. Nothing guarantees that pair
exists on *this* computer: the add-on may not be installed, or the installed
version may be older or newer than the one the descriptor was written against.
Both cases have to end in a row that is visibly unavailable and *says why* —
never in a control that looks live and writes nothing, and never in a traceback.

Three facts from the research drive the whole module:

* **Add-on settings are not in the system store.** Every curated add-on keeps
  its compiled settings under ``<extension dir>/schemas/``. A plain lookup in
  the default source finds none of them, so a source is built per directory
  with the default source as its parent.
* **Never trust ``metadata.json`` and never trust filenames.** Four of the
  curated add-ons omit ``settings-schema`` entirely, and clipboard-history
  ships its settings in a file named after clipboard-indicator. Ids come from
  parsing the XML, which is also why this module works on a directory that has
  no compiled blob at all: it can still say *which* ids live there, and then
  report honestly that they cannot be read.
* **Probing costs time and must not cost startup.** Refine's pattern:
  build every row immediately, then check it on an idle callback and grey the
  ones that failed. :func:`probe_rows_idle` is that, chunked so a hundred rows
  never block a frame.

The scan is read-only. It opens files under the extensions directories and
never writes anything anywhere.
"""

from __future__ import annotations

import enum
import os
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .descriptor import Row

__all__ = [
    "Availability",
    "ExtensionSchemas",
    "KEPT_IN_OWN_FILE",
    "Presence",
    "SchemaProbe",
    "extension_roots",
    "probe_rows_idle",
    "schema_ids_in",
]

#: Colon-separated override for the directories searched for add-ons. The test
#: suite points it at the committed fixture corpus; nothing else sets it.
ROOTS_ENV = "GTHEME_EXTENSION_ROOTS"


def extension_roots() -> list[Path]:
    """Every directory that may contain installed add-ons, in search order.

    The user's own directory first — a locally installed add-on shadows a
    system one of the same name, which is what the desktop itself does.
    """
    override = os.environ.get(ROOTS_ENV)
    if override:
        return [Path(part) for part in override.split(os.pathsep) if part]

    roots = [Path.home() / ".local" / "share" / "gnome-shell" / "extensions"]
    data_dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    for entry in data_dirs.split(os.pathsep):
        if entry:
            roots.append(Path(entry) / "gnome-shell" / "extensions")
    return roots


def schema_ids_in(schemas_dir: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """``(fixed, relocatable)`` schema ids declared under a ``schemas/`` dir.

    Read from the XML, never from ``metadata.json`` and never from the file
    names. A schema with no ``path`` attribute is relocatable: it has no home
    of its own and can only be read against an explicit path, which is why
    burn-my-windows' per-profile settings need the three-part key form.
    """
    fixed: list[str] = []
    relocatable: list[str] = []
    for path in sorted(schemas_dir.glob("*.gschema.xml")):
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            continue
        for element in root.iter("schema"):
            schema_id = element.get("id")
            if not schema_id:
                continue
            if element.get("path"):
                fixed.append(schema_id)
            else:
                relocatable.append(schema_id)
    return tuple(fixed), tuple(relocatable)


@dataclass(frozen=True)
class ExtensionSchemas:
    """What one installed add-on directory offers.

    Args:
        uuid: the add-on's directory name.
        directory: its ``schemas/`` directory.
        fixed: schema ids that have a path of their own.
        relocatable: schema ids that need an explicit path.
        compiled: whether a compiled blob is present. Without one the ids are
            known but no value can be read, and rows say so rather than
            pretending the add-on is absent.
    """

    uuid: str
    directory: Path
    fixed: tuple[str, ...]
    relocatable: tuple[str, ...]
    compiled: bool

    @property
    def schema_ids(self) -> tuple[str, ...]:
        return self.fixed + self.relocatable


class Presence(enum.StrEnum):
    """Whether a descriptor can be honoured here. Closed set."""

    #: The setting exists and can be read and written.
    AVAILABLE = "available"
    #: Nothing on this computer provides the setting — the add-on is missing.
    MISSING_ADDON = "missing-addon"
    #: The add-on is here but this version has no such setting.
    MISSING_SETTING = "missing-setting"
    #: The setting is here and cannot be read. A broken install, usually.
    UNREADABLE = "unreadable"
    #: The add-on describes the setting but keeps its value somewhere gtheme
    #: cannot reach. See :data:`KEPT_IN_OWN_FILE`.
    STORED_ELSEWHERE = "stored-elsewhere"


#: What a greyed row says. One sentence, no machinery words: the person
#: reading it wants to know whether to install something, not what a schema is.
REASONS: dict[Presence, str] = {
    Presence.AVAILABLE: "",
    Presence.MISSING_ADDON: "This needs an add-on that isn't installed.",
    Presence.MISSING_SETTING: (
        "The version of this add-on on your computer doesn't have this setting."
    ),
    Presence.UNREADABLE: "This setting is installed but can't be read on this computer.",
    Presence.STORED_ELSEWHERE: (
        "This add-on keeps this setting in a file of its own, so it has to be "
        "changed in the add-on's own window."
    ),
}


#: Add-ons that describe their settings normally and then store the values
#: somewhere the desktop's own settings store never sees.
#:
#: burn-my-windows is the one known case and it is worth spelling out, because
#: everything about it looks fine until nothing happens. Its per-profile
#: settings carry a perfectly ordinary fixed path, but the add-on reads and
#: writes them through ``Gio.keyfile_settings_backend_new`` against
#: ``~/.config/burn-my-windows/profiles/<id>.conf``
#: (``src/ProfileManager.js``, ``_getProfileSettings``). Verified on this
#: machine: the profile file exists and holds real values, while
#: ``dconf dump /org/gnome/shell/extensions/burn-my-windows-profile/`` is empty.
#: A row that wrote to that path would report success, change nothing, and be
#: undiagnosable. So the row says where the setting really lives instead.
KEPT_IN_OWN_FILE: dict[str, str] = {
    "org.gnome.shell.extensions.burn-my-windows-profile": (
        "~/.config/burn-my-windows/profiles/"
    ),
}


@dataclass(frozen=True)
class Availability:
    """The verdict for one row, with the sentence to show if it is bad news."""

    presence: Presence
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.presence is Presence.AVAILABLE

    @classmethod
    def of(cls, presence: Presence) -> Availability:
        return cls(presence, REASONS[presence])


class SchemaProbe:
    """Looks settings up across every installed add-on and the system.

    One instance lives for the life of the window. Directory scans, compiled
    sources and lookups are all memoised, including the "known missing" answer:
    an add-on that is not installed is discovered once, not once per row.

    Args:
        roots: directories to scan. Defaults to :func:`extension_roots`.
        include_default: also fall back to the system's own settings, which is
            where every core-GNOME descriptor resolves. Off only in tests that
            want to prove an add-on lookup did not accidentally hit the system.
    """

    def __init__(
        self,
        roots: Sequence[Path] | None = None,
        *,
        include_default: bool = True,
    ) -> None:
        self._roots = [Path(root) for root in (roots if roots is not None else extension_roots())]
        self._include_default = include_default
        self._extensions: dict[str, ExtensionSchemas] | None = None
        self._by_schema: dict[str, str] = {}
        self._sources: dict[str, Any] = {}
        self._schemas: dict[str, Any] = {}

    # -- scanning ----------------------------------------------------------

    @property
    def extensions(self) -> dict[str, ExtensionSchemas]:
        """Every add-on found, by directory name. Scans once."""
        if self._extensions is None:
            found: dict[str, ExtensionSchemas] = {}
            for root in self._roots:
                if not root.is_dir():
                    continue
                for entry in sorted(root.iterdir()):
                    schemas_dir = entry / "schemas"
                    if entry.name in found or not schemas_dir.is_dir():
                        continue
                    fixed, relocatable = schema_ids_in(schemas_dir)
                    if not fixed and not relocatable:
                        continue
                    found[entry.name] = ExtensionSchemas(
                        uuid=entry.name,
                        directory=schemas_dir,
                        fixed=fixed,
                        relocatable=relocatable,
                        compiled=(schemas_dir / "gschemas.compiled").is_file(),
                    )
            self._extensions = found
            self._by_schema = {
                schema_id: ext.uuid
                for ext in found.values()
                for schema_id in ext.schema_ids
            }
        return self._extensions

    def owner_of(self, schema_id: str) -> str | None:
        """Which add-on declares a schema id, if any does."""
        self.extensions  # noqa: B018 - force the scan
        return self._by_schema.get(schema_id)

    # -- sources -----------------------------------------------------------

    def _gio(self) -> Any:
        from gi.repository import Gio

        return Gio

    def source_for(self, schema_id: str) -> Any | None:
        """The settings source a schema id resolves in, or None.

        For an add-on, a source built from its own directory with the system
        source as parent. For anything else, the system source. Returns None
        when the directory has no compiled settings to read — the ids are
        known, the values are not, and :meth:`availability` turns that into
        :attr:`Presence.UNREADABLE` rather than a crash.
        """
        Gio = self._gio()
        uuid = self.owner_of(schema_id)
        if uuid is None:
            return Gio.SettingsSchemaSource.get_default() if self._include_default else None

        cached = self._sources.get(uuid, ...)
        if cached is not ...:
            return cached

        extension = self.extensions[uuid]
        parent = Gio.SettingsSchemaSource.get_default() if self._include_default else None
        source: Any | None
        try:
            source = Gio.SettingsSchemaSource.new_from_directory(
                str(extension.directory), parent, True
            )
        except Exception:
            # No compiled blob, or one this machine cannot read. Both mean the
            # same thing to the user: the add-on is there, the setting is not
            # reachable. Remember the failure so the next row is instant.
            source = None
        self._sources[uuid] = source
        return source

    def lookup(self, schema_id: str) -> Any | None:
        """The schema object for an id, from wherever it lives."""
        cached = self._schemas.get(schema_id, ...)
        if cached is not ...:
            return cached
        source = self.source_for(schema_id)
        schema = source.lookup(schema_id, True) if source is not None else None
        self._schemas[schema_id] = schema
        return schema

    def source_for_row(self, row: Row) -> Any | None:
        """The source to hand a backend so it can address this row."""
        return self.source_for(row.schema_id)

    # -- the verdict -------------------------------------------------------

    def availability(self, row: Row) -> Availability:
        """Whether this descriptor can be honoured on this computer."""
        if row.schema_id in KEPT_IN_OWN_FILE:
            return Availability.of(Presence.STORED_ELSEWHERE)
        try:
            schema = self.lookup(row.schema_id)
        except Exception:  # pragma: no cover - defensive; a lookup must not throw
            return Availability.of(Presence.UNREADABLE)

        if schema is None:
            if self.owner_of(row.schema_id) is not None:
                # The add-on is installed; its settings just cannot be read.
                return Availability.of(Presence.UNREADABLE)
            return Availability.of(Presence.MISSING_ADDON)
        if not schema.has_key(row.key):
            return Availability.of(Presence.MISSING_SETTING)
        return Availability.of(Presence.AVAILABLE)

    def probe(self, rows: Iterable[Row]) -> Iterator[tuple[Row, Availability]]:
        """Verdicts for many rows, lazily. The synchronous half of the probe."""
        for row in rows:
            yield row, self.availability(row)


def probe_rows_idle(
    probe: SchemaProbe,
    rows: Sequence[Row],
    on_result: Callable[[Row, Availability], None],
    *,
    on_done: Callable[[], None] | None = None,
    chunk: int = 8,
) -> int:
    """Probe rows on the main loop's idle time. Returns the source id.

    Rows are built first and checked afterwards, so opening a page is never
    delayed by disk work; a few rows at a time keeps any single callback well
    under a frame. Remove the returned source with ``GLib.source_remove`` if
    the page is torn down before the probe finishes.
    """
    from gi.repository import GLib

    pending = probe.probe(rows)

    def step() -> bool:
        for _ in range(max(1, chunk)):
            try:
                row, availability = next(pending)
            except StopIteration:
                if on_done is not None:
                    on_done()
                return GLib.SOURCE_REMOVE
            on_result(row, availability)
        return GLib.SOURCE_CONTINUE

    return GLib.idle_add(step)
