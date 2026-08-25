"""Enumerate installed GNOME Shell extensions and their real schema ids.

Two facts from research/ego-api.md drive every design choice here:

* **``metadata.json``'s ``settings-schema`` field cannot be trusted.**
  dash-to-dock, dash-to-panel, ding and gsconnect all omit it entirely, and
  the field existing does not mean it is the whole truth — clipboard-history
  ships a schema *file* named after a different extension
  (``org.gnome.shell.extensions.clipboard-indicator.gschema.xml``), so even
  matching by filename is wrong. The only reliable source of a schema id is
  the ``id`` attribute inside the ``<schema>`` element of the compiled-or-not
  ``schemas/*.gschema.xml`` file itself, and this module parses that
  directly and ignores ``settings-schema`` for identification.
* **The directory name is the uuid, never anything in the JSON.** A
  malformed or missing ``metadata.json`` still yields a usable entry.

This module does no GTK/GObject work and imports no ``gi`` — it is plain
``pathlib``/``json``/``xml.etree``, safe to unit-test without a display.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

__all__ = [
    "ExtensionEntry",
    "default_extension_roots",
    "scan_extensions",
]


@dataclass(frozen=True)
class ExtensionEntry:
    """One installed extension directory."""

    #: The directory name. Authoritative — never read from metadata.json.
    uuid: str
    #: ``metadata.json``'s ``"name"``, falling back to the uuid if absent or
    #: the file is unreadable.
    name: str
    description: str | None
    #: ``metadata.json``'s ``"shell-version"`` list, raw strings, as-is.
    shell_versions: tuple[str, ...]
    path: Path
    #: Schema ids parsed from ``schemas/*.gschema.xml`` ``id`` attributes.
    #: May be more than one (blur-my-shell, night-theme-switcher and others
    #: split settings across several child schemas) or empty (an extension
    #: with no settings at all).
    schema_ids: tuple[str, ...]
    #: ``metadata.json``'s own ``"settings-schema"`` claim, kept only for
    #: diagnostics — NEVER use this to resolve a schema id, see module
    #: docstring. ``None`` when the field is absent, which happens for
    #: several of the most popular extensions.
    declared_settings_schema: str | None


def default_extension_roots() -> list[Path]:
    """Real search order: user extensions, then system-installed ones."""
    home = Path(os.environ.get("HOME", str(Path.home())))
    data_home = Path(os.environ.get("XDG_DATA_HOME", str(home / ".local" / "share")))
    return [
        data_home / "gnome-shell" / "extensions",
        Path("/usr/share/gnome-shell/extensions"),
    ]


def _read_metadata(metadata_path: Path) -> dict:
    try:
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _schema_ids_in_file(xml_path: Path) -> list[str]:
    try:
        root = ElementTree.fromstring(xml_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ElementTree.ParseError):
        return []
    # Handles both a bare <schemalist> root and one nested under other markup;
    # findall with './/' covers <schema> at any depth defensively.
    return [el.get("id") for el in root.findall(".//schema") if el.get("id")]


def _scan_one(uuid_dir: Path) -> ExtensionEntry:
    metadata = _read_metadata(uuid_dir / "metadata.json")
    shell_versions_raw = metadata.get("shell-version", [])
    shell_versions = tuple(str(v) for v in shell_versions_raw) if isinstance(
        shell_versions_raw, list
    ) else ()

    schema_ids: list[str] = []
    schemas_dir = uuid_dir / "schemas"
    if schemas_dir.is_dir():
        for xml_path in sorted(schemas_dir.glob("*.gschema.xml")):
            for schema_id in _schema_ids_in_file(xml_path):
                if schema_id not in schema_ids:
                    schema_ids.append(schema_id)

    return ExtensionEntry(
        uuid=uuid_dir.name,
        name=str(metadata.get("name") or uuid_dir.name),
        description=(str(metadata["description"]) if metadata.get("description") else None),
        shell_versions=shell_versions,
        path=uuid_dir,
        schema_ids=tuple(schema_ids),
        declared_settings_schema=(
            str(metadata["settings-schema"]) if metadata.get("settings-schema") else None
        ),
    )


def scan_extensions(roots: list[Path]) -> list[ExtensionEntry]:
    """Walk ``roots`` in order; a uuid found in an earlier root wins.

    Matches the real precedence: a user-installed copy of an extension takes
    over from a package-provided one with the same uuid (window-calls on the
    research machine is exactly this case).
    """
    seen: dict[str, ExtensionEntry] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir() or child.name in seen:
                continue
            if not (child / "metadata.json").is_file():
                continue
            seen[child.name] = _scan_one(child)
    return sorted(seen.values(), key=lambda e: e.name.casefold())
