"""Generated artefacts: the JSON Schemas, the fixture corpus, the universe.

All three are produced by tools and committed. Committed generated data goes
stale silently, which is the failure these tests exist to make loud.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import gen_schema  # noqa: E402

# -- JSON Schemas ----------------------------------------------------------


def test_the_published_schemas_are_up_to_date():
    """``tools/gen_schema.py`` output must match what is committed.

    If this fails, the pydantic models changed and the docs did not. Run
    ``python tools/gen_schema.py``.
    """
    stale = []
    for path, text in gen_schema.expected().items():
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        if current != text:
            stale.append(path.relative_to(REPO_ROOT))
    assert stale == [], f"stale schemas: {stale} — run python tools/gen_schema.py"


def test_a_schema_is_published_for_every_authored_format():
    assert set(gen_schema.MODELS) == {
        "preset-v2.schema.json",
        "panel.schema.json",
        "domain.schema.json",
    }


def test_the_preset_schema_forbids_unknown_keys():
    """``additionalProperties: false`` is how the hooks removal is published."""
    import json

    schema = json.loads(
        (REPO_ROOT / "docs" / "schema" / "preset-v2.schema.json").read_text(encoding="utf-8")
    )
    assert schema.get("additionalProperties") is False
    assert "hooks" not in json.dumps(schema)


# -- schema fixture corpus -------------------------------------------------

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "schemas"
LOCAL_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "schemas-local"


@pytest.fixture(scope="module")
def manifest() -> dict:
    path = FIXTURES / "MANIFEST.toml"
    assert path.is_file(), "the fixture corpus has not been fetched"
    return tomllib.loads(path.read_text(encoding="utf-8"))


def test_the_corpus_covers_the_curated_set(manifest):
    """DESIGN.md A9 curates 24 add-ons; gtk4-ding rides along on ding's panel."""
    fetched = [e for e in manifest["extension"] if "skipped" not in e]
    assert len(fetched) >= 24, f"only {len(fetched)} add-ons in the corpus"


def test_the_rejected_add_ons_are_absent(manifest):
    """forge and quick-settings-tweaks do not support GNOME Shell 50.

    extensions.gnome.org serves a zip for an unsupported shell without
    complaining, so their absence has to be asserted rather than assumed.
    """
    uuids = {e["uuid"] for e in manifest["extension"]}
    assert "forge@jmmaranan.com" not in uuids
    assert "quick-settings-tweaks@qwreey" not in uuids


def test_every_fetched_add_on_has_its_files_on_disk(manifest):
    for entry in manifest["extension"]:
        if "skipped" in entry:
            continue
        directory = FIXTURES / entry["uuid"]
        assert directory.is_dir(), f"{entry['uuid']}: no fixture directory"
        assert (directory / "metadata.json").is_file(), f"{entry['uuid']}: no metadata.json"


def test_add_ons_that_have_settings_ship_compiled_schemas(manifest):
    """``SettingsSchemaSource.new_from_directory`` throws without the compiled file."""
    for entry in manifest["extension"]:
        if "skipped" in entry or not entry.get("schema_ids"):
            continue
        compiled = FIXTURES / entry["uuid"] / "schemas" / "gschemas.compiled"
        assert compiled.is_file(), f"{entry['uuid']}: schemas were not compiled"


def test_nothing_failed_to_compile(manifest):
    broken = [e["uuid"] for e in manifest["extension"] if "compile_error" in e]
    assert broken == []


def test_provenance_is_recorded_for_every_entry(manifest):
    for entry in manifest["extension"]:
        assert entry["provenance"] == "ego"
        if "skipped" not in entry:
            assert entry["sha256"]
            assert entry["version_tag"]


def test_the_locally_installed_overlaps_are_recorded(manifest):
    """The version on this machine is not always the version the site serves."""
    local = manifest.get("local", [])
    assert len(local) >= 10, f"only {len(local)} local copies"
    for entry in local:
        assert entry["provenance"] == "local"
        assert (LOCAL_FIXTURES / entry["uuid"]).is_dir()


def test_schema_ids_come_from_the_xml_not_from_metadata(manifest):
    """Four curated add-ons omit ``settings-schema`` entirely; one lies in a filename."""
    import json

    by_uuid = {e["uuid"]: e for e in manifest["extension"]}

    for uuid in (
        "dash-to-dock@micxgx.gmail.com",
        "dash-to-panel@jderose9.github.com",
        "ding@rastersoft.com",
        "gsconnect@andyholmes.github.io",
    ):
        entry = by_uuid.get(uuid)
        if entry is None or "skipped" in entry:
            pytest.skip(f"{uuid} is not in the corpus")
        metadata = json.loads(
            (FIXTURES / uuid / "metadata.json").read_text(encoding="utf-8")
        )
        assert entry["schema_ids"], f"{uuid}: no schema ids were parsed out of the XML"
        assert "settings-schema" not in metadata or metadata.get("settings-schema") is not None


def test_clipboard_history_schema_is_resolved_by_id_not_filename(manifest):
    """Its schema file is named after a *different* extension."""
    uuid = "clipboard-history@alexsaveau.dev"
    entry = next((e for e in manifest["extension"] if e["uuid"] == uuid), None)
    if entry is None or "skipped" in entry:
        pytest.skip(f"{uuid} is not in the corpus")
    assert "org.gnome.shell.extensions.clipboard-history" in entry["schema_ids"]


def test_a_fixture_schema_actually_loads():
    """The corpus is only useful if GIO can read it."""
    pytest.importorskip("gi", reason="PyGObject is needed to load a schema source")
    from gi.repository import Gio

    directory = FIXTURES / "impatience@gfxmonk.net" / "schemas"
    if not (directory / "gschemas.compiled").is_file():
        pytest.skip("impatience is not in the corpus")
    source = Gio.SettingsSchemaSource.new_from_directory(
        str(directory), Gio.SettingsSchemaSource.get_default(), False
    )
    schema = source.lookup("org.gnome.shell.extensions.net.gfxmonk.impatience", False)
    assert schema is not None
    assert "speed-factor" in schema.list_keys()


# -- coverage universe -----------------------------------------------------

UNIVERSE = REPO_ROOT / "data" / "domains" / "universe.txt"


def _universe_rows() -> list[tuple[str, str, str]]:
    rows = []
    for line in UNIVERSE.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        assert len(parts) == 3, f"malformed universe line: {line!r}"
        rows.append(tuple(parts))
    return rows


def test_the_universe_exists_and_is_substantial():
    assert UNIVERSE.is_file(), "run python tools/gen_coverage_universe.py"
    rows = _universe_rows()
    # 33 desktop schemas plus shell, mutter and the settings-daemon plugins.
    assert len(rows) > 400, f"only {len(rows)} keys — the sweep looks truncated"


def test_every_universe_key_has_a_known_type():
    """``gsettings range`` prints ``range d -1.0 1.0`` on one line, not two.

    Matching only a bare ``range`` left 31 keys typed ``?`` — every bounded
    key in the magnifier and power schemas — which would have handed the
    descriptor authors "unknown" for exactly the keys that most need clamps.
    """
    unknown = [(s, k) for s, k, t in _universe_rows() if t == "?"]
    assert unknown == []


def test_universe_types_are_types_or_the_two_choice_markers():
    """``enum`` and ``flags`` are kept as such: they decide how a row is drawn."""
    for schema, key, type_ in _universe_rows():
        assert type_, f"{schema} {key} has an empty type"
        assert type_ in {"enum", "flags"} or not type_[0].isalpha() or type_[0] in "absdinuqxthmvygo(@{", (
            f"{schema} {key} has an implausible type {type_!r}"
        )


def test_universe_entries_are_unique_and_sorted():
    rows = _universe_rows()
    assert rows == sorted(rows)
    assert len(set(rows)) == len(rows)


def test_the_universe_contains_the_keys_the_app_is_built_around():
    """A spot check against gnome-domains.md's headline keys."""
    pairs = {(schema, key) for schema, key, _ in _universe_rows()}
    for schema, key in (
        ("org.gnome.desktop.interface", "color-scheme"),
        ("org.gnome.desktop.interface", "accent-color"),
        ("org.gnome.desktop.interface", "gtk-theme"),
        ("org.gnome.desktop.interface", "font-rendering"),
        ("org.gnome.desktop.background", "picture-uri"),
        ("org.gnome.desktop.background", "picture-uri-dark"),
        ("org.gnome.desktop.screensaver", "picture-uri"),
        ("org.gnome.desktop.a11y.interface", "high-contrast"),
        ("org.gnome.desktop.wm.preferences", "button-layout"),
        ("org.gnome.mutter", "dynamic-workspaces"),
        ("org.gnome.shell", "enabled-extensions"),
        ("org.gnome.settings-daemon.plugins.color", "night-light-enabled"),
    ):
        assert (schema, key) in pairs, f"{schema} {key} is missing from the universe"


def test_the_screensaver_really_has_no_dark_variant():
    """The app must never promise a separate lock-screen picture. It cannot."""
    pairs = {(schema, key) for schema, key, _ in _universe_rows()}
    assert ("org.gnome.desktop.screensaver", "picture-uri") in pairs
    assert ("org.gnome.desktop.screensaver", "picture-uri-dark") not in pairs
