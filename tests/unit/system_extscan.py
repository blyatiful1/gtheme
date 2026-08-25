"""Tests for gtheme.system.extscan — plain filesystem fixture trees, no gi."""

from __future__ import annotations

from pathlib import Path

from gtheme.system.extscan import scan_extensions

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "system" / "extensions"


def test_scan_finds_every_extension_with_metadata() -> None:
    entries = scan_extensions([FIXTURES])
    uuids = {e.uuid for e in entries}
    assert uuids == {
        "dash-to-dock@micxgx.gmail.com",
        "blur-my-shell@aunetx",
        "clipboard-history@alexsaveau.dev",
        "broken-metadata@example.com",
    }


def test_uuid_comes_from_directory_name_never_metadata() -> None:
    entries = scan_extensions([FIXTURES])
    by_uuid = {e.uuid: e for e in entries}
    assert by_uuid["dash-to-dock@micxgx.gmail.com"].name == "Dash to Dock"


def test_schema_id_omitted_from_metadata_is_still_found() -> None:
    # dash-to-dock omits "settings-schema" entirely in real metadata.json.
    entries = scan_extensions([FIXTURES])
    by_uuid = {e.uuid: e for e in entries}
    entry = by_uuid["dash-to-dock@micxgx.gmail.com"]
    assert entry.declared_settings_schema is None
    assert entry.schema_ids == ("org.gnome.shell.extensions.dash-to-dock",)


def test_multiple_child_schemas_all_collected() -> None:
    entries = scan_extensions([FIXTURES])
    by_uuid = {e.uuid: e for e in entries}
    entry = by_uuid["blur-my-shell@aunetx"]
    assert entry.schema_ids == (
        "org.gnome.shell.extensions.blur-my-shell",
        "org.gnome.shell.extensions.blur-my-shell.panel",
    )


def test_clipboard_history_filename_trap_resolved_by_content_not_name() -> None:
    # The schema *file* is named after clipboard-indicator, and metadata.json
    # even *claims* settings-schema=clipboard-indicator; the true id, read
    # from inside the file, is clipboard-history.
    entries = scan_extensions([FIXTURES])
    by_uuid = {e.uuid: e for e in entries}
    entry = by_uuid["clipboard-history@alexsaveau.dev"]

    assert entry.declared_settings_schema == "org.gnome.shell.extensions.clipboard-indicator"
    assert entry.schema_ids == ("org.gnome.shell.extensions.clipboard-history",)


def test_broken_metadata_json_does_not_crash_the_scan() -> None:
    entries = scan_extensions([FIXTURES])
    by_uuid = {e.uuid: e for e in entries}
    entry = by_uuid["broken-metadata@example.com"]

    assert entry.name == "broken-metadata@example.com"  # falls back to uuid
    assert entry.schema_ids == ()
    assert entry.shell_versions == ()


def test_directory_without_metadata_json_is_not_an_extension(tmp_path: Path) -> None:
    (tmp_path / "not-an-extension").mkdir()
    assert scan_extensions([tmp_path]) == []


def test_earlier_root_shadows_later_root(tmp_path: Path) -> None:
    user_root = tmp_path / "user"
    system_root = tmp_path / "system"
    for root, name in ((user_root, "User Copy"), (system_root, "System Copy")):
        d = root / "window-calls@domandoman.xyz"
        d.mkdir(parents=True)
        (d / "metadata.json").write_text(f'{{"name": "{name}"}}', encoding="utf-8")

    entries = scan_extensions([user_root, system_root])
    assert len(entries) == 1
    assert entries[0].name == "User Copy"
