"""schema/theme.schema.json must stay in sync with what the manifest accepts.

The JSON Schema exists for theme authors (editor validation via taplo /
even-better-toml); publishing it unenforced would let it silently drift from
the pydantic models. This validates every bundled theme.toml against it —
CI fails when manifest.py and the schema diverge on real manifests.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

REPO = Path(__file__).resolve().parents[1]
SCHEMA = REPO / "schema" / "theme.schema.json"
THEMES = REPO / "themes"


def _bundled_manifests() -> list[Path]:
    return sorted(THEMES.glob("*/theme.toml"))


def test_bundled_themes_match_published_schema():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    manifests = _bundled_manifests()
    assert manifests, "no bundled themes found"
    problems = []
    for mf in manifests:
        data = tomllib.loads(mf.read_text(encoding="utf-8"))
        for err in validator.iter_errors(data):
            problems.append(f"{mf.parent.name}: {'/'.join(map(str, err.path))}: {err.message}")
    assert not problems, "\n".join(problems)
