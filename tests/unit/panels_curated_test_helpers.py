"""Loading and schema-corpus helpers shared by the curated-panel tests.

Kept beside the tests rather than in ``src/`` on purpose: the descriptor
engine that the app itself uses is a different agent's file, and these tests
must be able to fail even when that engine is mid-rewrite. What they check is
the *data* — the 24 ``data/panels/*.toml`` files — against two things that are
already frozen: the descriptor model, and the committed schema corpus captured
from real add-on downloads.
"""

from __future__ import annotations

import tomllib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from gtheme.panels.descriptor import PanelDescriptor

REPO_ROOT = Path(__file__).resolve().parents[2]
PANEL_DIR = REPO_ROOT / "data" / "panels"
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "schemas"


@dataclass(frozen=True)
class LoadedPanel:
    """One ``data/panels/*.toml`` file and the descriptor it parsed into."""

    path: Path
    descriptor: PanelDescriptor


def load_panels() -> list[LoadedPanel]:
    """Every curated panel, parsed through the frozen descriptor model."""
    panels = []
    for path in sorted(PANEL_DIR.glob("*.toml")):
        with path.open("rb") as handle:
            data = tomllib.load(handle)
        panels.append(LoadedPanel(path=path, descriptor=PanelDescriptor(**data)))
    return panels


@lru_cache(maxsize=1)
def corpus_keys() -> dict[str, set[str]]:
    """``{schema_id: {key, ...}}`` parsed from the committed fixture corpus.

    Parsed out of the ``.gschema.xml`` files themselves, never out of
    ``metadata.json`` and never out of a filename: four of the curated add-ons
    omit the settings-schema field entirely, and clipboard-history ships its
    settings in a file named after clipboard-indicator.
    """
    found: dict[str, set[str]] = {}
    for xml_path in sorted(FIXTURE_DIR.glob("*/schemas/*.gschema.xml")):
        root = ET.parse(xml_path).getroot()
        for schema in root.iter("schema"):
            schema_id = schema.get("id")
            if not schema_id:
                continue
            keys = found.setdefault(schema_id, set())
            keys.update(key.get("name", "") for key in schema.findall("key"))
    return found


@lru_cache(maxsize=1)
def corpus_enum_nicks() -> dict[str, set[str]]:
    """``{enum_id: {nick, ...}}`` for every enum and flags block in the corpus."""
    found: dict[str, set[str]] = {}
    for xml_path in sorted(FIXTURE_DIR.glob("*/schemas/*.gschema.xml")):
        root = ET.parse(xml_path).getroot()
        for block in list(root.iter("enum")) + list(root.iter("flags")):
            block_id = block.get("id")
            if not block_id:
                continue
            found.setdefault(block_id, set()).update(
                value.get("nick", "") for value in block.findall("value")
            )
    return found


@lru_cache(maxsize=1)
def corpus_key_types() -> dict[tuple[str, str], str]:
    """``{(schema_id, key): type_or_enum_id}`` for every key in the corpus.

    A plain GVariant type string for ordinary keys; the enum's id for keys
    declared with ``enum=``, so a test can check that a choice's stored value
    is one the add-on will actually accept.
    """
    found: dict[tuple[str, str], str] = {}
    for xml_path in sorted(FIXTURE_DIR.glob("*/schemas/*.gschema.xml")):
        root = ET.parse(xml_path).getroot()
        for schema in root.iter("schema"):
            schema_id = schema.get("id")
            if not schema_id:
                continue
            for key in schema.findall("key"):
                name = key.get("name", "")
                found[(schema_id, name)] = key.get("type") or key.get("enum") or ""
    return found
