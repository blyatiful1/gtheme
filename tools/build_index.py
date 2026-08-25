#!/usr/bin/env python3
"""Regenerate ``themes/index.json`` — the zero-server community registry.

The file this writes is fetched raw from GitHub by every gtheme install, so it
is the closest thing the project has to a published API. Run it after adding,
removing or bumping a bundled Look.

    ./.venv/bin/python tools/build_index.py            # write
    ./.venv/bin/python tools/build_index.py --check    # exit 1 if stale

``--check`` is what the test suite uses, so an index that drifts from the Looks
beside it fails the canonical check rather than shipping.

This is also where "every Look has a picture" is enforced. The requirement is
real (DESIGN.md A8 — an unpreviewable Look is exactly what this app exists to
spare people), but it belongs at PUBLISH time rather than in the model: the
same model describes restore points, which are written by machine from a
desktop that may have no wallpaper file to photograph. A Look reaches the
community index through this script, so this is the gate that has to hold.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from gtheme.preset.registry import build_index, write_index  # noqa: E402

THEMES_DIR = REPO_ROOT / "themes"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; exit 1 if the committed index is out of date",
    )
    parser.add_argument(
        "--themes-dir",
        type=Path,
        default=THEMES_DIR,
        help="folder of Looks to index (default: the repo's themes/)",
    )
    args = parser.parse_args(argv)

    document, skipped = build_index(args.themes_dir)
    for name, reason in skipped:
        print(f"skipped {name}: {reason}", file=sys.stderr)

    unpreviewable = [entry["name"] for entry in document["themes"] if not entry["screenshots"]]
    if unpreviewable:
        print(
            "refusing to publish: these Looks have no picture, so nobody could "
            "see what they do before applying them: " + ", ".join(sorted(unpreviewable)),
            file=sys.stderr,
        )
        print(
            "Add a screenshot to each Look's folder and list it under "
            "[meta] screenshots in its theme.toml.",
            file=sys.stderr,
        )
        return 1

    missing_files = []
    for entry in document["themes"]:
        for shot in entry["screenshots"]:
            if not (args.themes_dir / entry["name"] / shot).is_file():
                missing_files.append(f"{entry['name']}/{shot}")
    if missing_files:
        print(
            "refusing to publish: these pictures are listed but not there: "
            + ", ".join(sorted(missing_files)),
            file=sys.stderr,
        )
        return 1

    if args.check:
        target = args.themes_dir / "index.json"
        if not target.is_file():
            print(f"{target} does not exist — run tools/build_index.py", file=sys.stderr)
            return 1
        current = json.loads(target.read_text(encoding="utf-8"))
        if current != document:
            print(
                f"{target} is out of date — run tools/build_index.py",
                file=sys.stderr,
            )
            return 1
        print(f"{target} is up to date ({len(document['themes'])} Looks)")
        return 0

    out = write_index(args.themes_dir)
    print(f"wrote {out} ({len(document['themes'])} Looks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
