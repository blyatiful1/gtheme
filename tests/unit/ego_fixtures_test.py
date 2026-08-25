"""The recorded answers are what they say they are.

Fixtures that drift from what the site actually returns are worse than no
fixtures: the suite goes green against a shape the site stopped using. So the
recorded bytes are checked against the record of where they came from, and the
whole ego package is checked for anything that could open a socket by itself.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tomllib
from pathlib import Path

from ego_fakes import FIXTURES

MANIFEST = FIXTURES / "MANIFEST.toml"
EGO_PACKAGE = Path(__file__).resolve().parents[2] / "src" / "gtheme" / "ego"


def manifest() -> dict:
    return tomllib.loads(MANIFEST.read_text(encoding="utf-8"))


def test_every_recorded_answer_matches_its_record():
    entries = {k: v for k, v in manifest().items() if isinstance(v, dict)}
    assert entries, "the manifest lists no fixtures"
    for name, entry in entries.items():
        body = (FIXTURES / entry["file"]).read_bytes()
        assert hashlib.sha256(body).hexdigest() == entry["sha256"], name
        assert len(body) == entry["bytes"], name


def test_every_recorded_answer_says_where_it_came_from():
    for name, entry in manifest().items():
        if not isinstance(entry, dict):
            continue
        assert entry["url"].startswith("https://extensions.gnome.org/"), name
        assert entry["method"] in ("GET", "POST"), name


def test_every_fixture_file_is_accounted_for():
    listed = {
        entry["file"] for entry in manifest().values() if isinstance(entry, dict)
    }
    on_disk = {
        path.name
        for path in FIXTURES.iterdir()
        if path.suffix == ".json" and path.name != "MANIFEST.toml"
    }
    assert on_disk == listed


def test_the_recorder_is_committed_beside_what_it_recorded():
    """Fixtures nobody can regenerate rot silently."""
    assert (FIXTURES / "record_fixtures.py").is_file()


def test_no_module_in_the_ego_package_reaches_for_the_network_by_itself():
    """Every request goes through an injected transport. That is the test seam."""
    forbidden = ("urllib.request", "http.client", "import requests", "socket.socket")
    for module in EGO_PACKAGE.glob("*.py"):
        text = module.read_text(encoding="utf-8")
        for needle in forbidden:
            assert needle not in text, f"{module.name} mentions {needle}"


def test_importing_the_client_does_not_pull_in_the_desktop_libraries():
    """The unit tier has to run on a machine with no desktop libraries, and does.

    Checked in a fresh interpreter: another test in the same run may well have
    imported them already, and a check against this process's module table
    would pass or fail on collection order.
    """
    probe = (
        "import sys; import gtheme.ego.client, gtheme.ego.install, "
        "gtheme.ego.shelldbus, gtheme.ego.updates; "
        "print([n for n in sys.modules if n.startswith('gi.repository.')])"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]", result.stdout
