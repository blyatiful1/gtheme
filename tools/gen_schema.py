#!/usr/bin/env python3
"""Generate the published JSON Schemas from the pydantic models.

The schemas under ``docs/schema/`` are what Look authors point their editor at,
and they are GENERATED — never hand-edited. ``tests/unit/test_schema_fresh.py``
regenerates in memory and fails if the committed files differ, so the docs
cannot silently drift from the code.

    ./.venv/bin/python tools/gen_schema.py            # write
    ./.venv/bin/python tools/gen_schema.py --check    # exit 1 if stale
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from gtheme.panels.descriptor import DomainDescriptor, PanelDescriptor  # noqa: E402
from gtheme.preset.model import Preset  # noqa: E402

OUT_DIR = REPO_ROOT / "docs" / "schema"

#: filename -> model. Adding a model here is all it takes to publish it.
MODELS = {
    "preset-v2.schema.json": Preset,
    "panel.schema.json": PanelDescriptor,
    "domain.schema.json": DomainDescriptor,
}

_BANNER = (
    "GENERATED FILE — do not edit. Regenerate with `python tools/gen_schema.py`. "
    "The source of truth is the pydantic model in src/gtheme/."
)


def render(model: type) -> str:
    """JSON Schema text for one model, stable across runs."""
    schema = model.model_json_schema()
    schema["$comment"] = _BANNER
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def expected() -> dict[Path, str]:
    """What every generated file should contain right now."""
    return {OUT_DIR / name: render(model) for name, model in MODELS.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; exit non-zero if the committed schemas are stale",
    )
    args = parser.parse_args(argv)

    stale = []
    for path, text in expected().items():
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        if current == text:
            continue
        stale.append(path)
        if not args.check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    if args.check and stale:
        for path in stale:
            print(f"stale: {path.relative_to(REPO_ROOT)}", file=sys.stderr)
        print("run: python tools/gen_schema.py", file=sys.stderr)
        return 1
    for path in stale:
        print(f"wrote {path.relative_to(REPO_ROOT)}")
    if not stale:
        print("schemas are up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
