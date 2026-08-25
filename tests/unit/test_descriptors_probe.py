"""The schema probe, against the committed corpus of real add-on settings.

Every fact asserted here was a trap the research found in the wild: a missing
``settings-schema`` field, a settings file named after a different add-on, an
add-on that keeps its values in a file of its own. Hand-written fixtures would
prove none of it, so the corpus is the real downloaded files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for schema lookups")

from gtheme.panels.descriptor import Row  # noqa: E402
from gtheme.panels.schema_probe import (  # noqa: E402
    KEPT_IN_OWN_FILE,
    REASONS,
    Availability,
    Presence,
    SchemaProbe,
    extension_roots,
    probe_rows_idle,
    schema_ids_in,
)
from gtheme.ui import jargon  # noqa: E402

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "schemas"


@pytest.fixture
def probe() -> SchemaProbe:
    """A probe that sees only the committed corpus, never the real machine."""
    return SchemaProbe([CORPUS], include_default=False)


def _row(schema_id: str, key: str, **overrides) -> Row:
    base = {
        "schema_id": schema_id,
        "key": key,
        "title": "A setting",
        "subtitle": "Does a thing you can see.",
        "kind": "toggle",
    }
    return Row.model_validate({**base, **overrides})


# -- scanning --------------------------------------------------------------


def test_the_whole_curated_corpus_is_found(probe: SchemaProbe):
    assert len(probe.extensions) == len(list(CORPUS.glob("*@*")))
    assert "blur-my-shell@aunetx" in probe.extensions


def test_every_corpus_entry_has_readable_settings(probe: SchemaProbe):
    """A fixture without a compiled blob would silently grey out real rows."""
    uncompiled = [uuid for uuid, ext in probe.extensions.items() if not ext.compiled]
    assert uncompiled == []


def test_ids_come_from_the_xml_not_from_metadata(probe: SchemaProbe):
    """dash-to-dock has no ``settings-schema`` field at all, and still resolves."""
    metadata = json.loads(
        (CORPUS / "dash-to-dock@micxgx.gmail.com" / "metadata.json").read_text(encoding="utf-8")
    )
    assert "settings-schema" not in metadata
    assert probe.owner_of("org.gnome.shell.extensions.dash-to-dock") == (
        "dash-to-dock@micxgx.gmail.com"
    )


def test_ids_come_from_the_xml_not_from_file_names(probe: SchemaProbe):
    """clipboard-history ships its settings in a file named for clipboard-indicator."""
    directory = CORPUS / "clipboard-history@alexsaveau.dev" / "schemas"
    names = [path.name for path in directory.glob("*.gschema.xml")]
    assert any("clipboard-indicator" in name for name in names)
    assert probe.owner_of("org.gnome.shell.extensions.clipboard-history") == (
        "clipboard-history@alexsaveau.dev"
    )


def test_child_schemas_are_addressed_separately(probe: SchemaProbe):
    """blur-my-shell splits its settings across one child per component."""
    blur = probe.extensions["blur-my-shell@aunetx"]
    assert "org.gnome.shell.extensions.blur-my-shell.panel" in blur.schema_ids
    assert "org.gnome.shell.extensions.blur-my-shell.overview" in blur.schema_ids


def test_a_relocatable_schema_is_recognised(tmp_path: Path):
    """A schema with no path of its own can only be read against one."""
    directory = tmp_path / "schemas"
    directory.mkdir()
    (directory / "x.gschema.xml").write_text(
        """<?xml version="1.0"?>
        <schemalist>
          <schema id="io.test.Fixed" path="/io/test/fixed/"/>
          <schema id="io.test.Loose"/>
        </schemalist>
        """,
        encoding="utf-8",
    )
    fixed, relocatable = schema_ids_in(directory)
    assert fixed == ("io.test.Fixed",)
    assert relocatable == ("io.test.Loose",)


def test_a_directory_with_no_settings_is_not_an_add_on(tmp_path: Path):
    (tmp_path / "nothing@example.com" / "schemas").mkdir(parents=True)
    assert SchemaProbe([tmp_path]).extensions == {}


def test_the_search_path_starts_with_the_user_s_own_add_ons(monkeypatch):
    monkeypatch.delenv("GTHEME_EXTENSION_ROOTS", raising=False)
    roots = extension_roots()
    assert roots[0] == Path.home() / ".local" / "share" / "gnome-shell" / "extensions"
    assert any(str(root).startswith("/usr/share") for root in roots)


def test_the_search_path_can_be_pointed_at_a_corpus(monkeypatch):
    monkeypatch.setenv("GTHEME_EXTENSION_ROOTS", str(CORPUS))
    assert extension_roots() == [CORPUS]


# -- verdicts --------------------------------------------------------------


def test_a_real_setting_is_available(probe: SchemaProbe):
    row = _row("org.gnome.shell.extensions.blur-my-shell.panel", "blur")
    assert probe.availability(row) == Availability.of(Presence.AVAILABLE)
    assert probe.availability(row).ok


def test_a_missing_add_on_says_an_add_on_is_missing(probe: SchemaProbe):
    verdict = probe.availability(_row("org.gnome.shell.extensions.not-installed", "thing"))
    assert verdict.presence is Presence.MISSING_ADDON
    assert not verdict.ok
    assert "isn't installed" in verdict.reason


def test_a_renamed_key_says_the_version_is_different(probe: SchemaProbe):
    """The failure when an add-on renames a key between versions."""
    verdict = probe.availability(
        _row("org.gnome.shell.extensions.blur-my-shell.panel", "blur-but-renamed")
    )
    assert verdict.presence is Presence.MISSING_SETTING
    assert "version" in verdict.reason


def test_settings_an_add_on_keeps_in_its_own_file_are_not_pretended_to_work(probe: SchemaProbe):
    """burn-my-windows profiles look ordinary and live in a keyfile.

    Its per-profile schema declares a fixed path, so a write would appear to
    succeed and land in a place the add-on never reads. Verified on this
    machine: the profile ``.conf`` holds the real values while the settings
    store under that path is empty.
    """
    row = _row("org.gnome.shell.extensions.burn-my-windows-profile", "fire-enable-effect")
    verdict = probe.availability(row)
    assert verdict.presence is Presence.STORED_ELSEWHERE
    assert row.schema_id in KEPT_IN_OWN_FILE
    # gtheme opens that file itself now, so the reason has to be about the file
    # being absent — not about the setting being out of reach.
    assert verdict.reason == KEPT_IN_OWN_FILE[row.schema_id].explain


def test_every_reason_is_in_plain_words():
    """A greyed row is exactly where jargon does the most damage."""
    for presence, reason in REASONS.items():
        assert jargon.check(reason, where=str(presence)) == []


def test_a_missing_add_on_is_looked_up_once(probe: SchemaProbe):
    row = _row("org.gnome.shell.extensions.absent", "thing")
    probe.availability(row)
    assert "org.gnome.shell.extensions.absent" in probe._schemas


def test_a_source_is_built_once_per_add_on(probe: SchemaProbe):
    first = probe.source_for("org.gnome.shell.extensions.blur-my-shell.panel")
    second = probe.source_for("org.gnome.shell.extensions.blur-my-shell.overview")
    assert first is second


def test_an_add_on_whose_settings_cannot_be_compiled_is_readable_but_not_read(tmp_path: Path):
    """Ids parse from the XML even with no compiled blob; values do not."""
    directory = tmp_path / "broken@example.com" / "schemas"
    directory.mkdir(parents=True)
    (directory / "x.gschema.xml").write_text(
        '<?xml version="1.0"?><schemalist>'
        '<schema id="io.test.Broken" path="/io/test/broken/">'
        '<key name="a-flag" type="b"><default>false</default></key>'
        "</schema></schemalist>",
        encoding="utf-8",
    )
    probe = SchemaProbe([tmp_path], include_default=False)
    assert probe.owner_of("io.test.Broken") == "broken@example.com"
    assert probe.extensions["broken@example.com"].compiled is False
    assert probe.availability(_row("io.test.Broken", "a-flag")).presence is Presence.UNREADABLE


# -- the deferred probe ----------------------------------------------------


def test_rows_are_probed_on_idle_time_and_all_of_them_arrive(probe: SchemaProbe):
    """Rows are built first and checked afterwards; nothing is dropped."""
    from gi.repository import GLib

    rows = [
        _row("org.gnome.shell.extensions.blur-my-shell.panel", "blur"),
        _row("org.gnome.shell.extensions.blur-my-shell.panel", "sigma"),
        _row("org.gnome.shell.extensions.not-installed", "thing"),
        _row("org.gnome.shell.extensions.caffeine", "user-enabled"),
    ]
    seen: list[tuple[str, Presence]] = []
    loop = GLib.MainLoop()
    probe_rows_idle(
        probe,
        rows,
        lambda row, verdict: seen.append((row.id, verdict.presence)),
        on_done=loop.quit,
        chunk=2,
    )
    GLib.timeout_add(5000, loop.quit)
    loop.run()

    assert [row_id for row_id, _ in seen] == [row.id for row in rows]
    assert seen[2][1] is Presence.MISSING_ADDON


# -- add-ons that keep their settings in a file of their own ---------------
#
# The greying above is what happens when nobody can say WHICH file. Given the
# file, gtheme opens it, and the rows are live.


BMW_UUID = "burn-my-windows@schneegans.github.com"
BMW_PROFILE = "org.gnome.shell.extensions.burn-my-windows-profile"
BMW_ACTIVE = "gsettings:org.gnome.shell.extensions.burn-my-windows active-profile"


@pytest.fixture
def bmw_backend():
    """A memory backend that can read burn-my-windows' main schema."""
    pytest.importorskip("gi")
    from gi.repository import Gio

    from gtheme.core.settings_backend import MemoryBackend

    source = Gio.SettingsSchemaSource.new_from_directory(
        str(CORPUS / BMW_UUID / "schemas"), Gio.SettingsSchemaSource.get_default(), False
    )
    return MemoryBackend(schema_source=source)


def test_with_no_profile_file_the_row_is_still_honestly_greyed(probe, bmw_backend):
    from gtheme.panels.schema_probe import settings_file_for

    assert settings_file_for(BMW_PROFILE, bmw_backend) is None
    row = _row(BMW_PROFILE, "fire-enable-effect")
    verdict = probe.availability(row, bmw_backend)
    assert verdict.presence is Presence.STORED_ELSEWHERE
    assert verdict.reason, "a greyed row that does not say why is worse than no row"


def test_with_a_profile_file_the_row_becomes_available(probe, bmw_backend, tmp_path):
    profile = tmp_path / "1787167433969725.conf"
    profile.write_text("[burn-my-windows-profile]\n", encoding="utf-8")
    bmw_backend.set(BMW_ACTIVE, f"'{profile}'")

    row = _row(BMW_PROFILE, "fire-enable-effect")
    assert probe.availability(row, bmw_backend).presence is Presence.AVAILABLE


def test_a_named_profile_that_is_not_there_stays_greyed(probe, bmw_backend, tmp_path):
    """Naming a file is not the same as having one."""
    bmw_backend.set(BMW_ACTIVE, f"'{tmp_path / 'never-created.conf'}'")
    row = _row(BMW_PROFILE, "fire-enable-effect")
    assert probe.availability(row, bmw_backend).presence is Presence.STORED_ELSEWHERE


def test_resolving_a_row_addresses_the_file_the_add_on_is_using(bmw_backend, tmp_path):
    from gtheme.panels.schema_probe import resolve_row
    from gtheme.ui.widgets.rows import key_for

    profile = tmp_path / "1787167433969725.conf"
    profile.write_text("[burn-my-windows-profile]\n", encoding="utf-8")
    bmw_backend.set(BMW_ACTIVE, f"'{profile}'")

    resolved = resolve_row(_row(BMW_PROFILE, "fire-enable-effect"), bmw_backend)
    assert resolved.keyfile == str(profile)
    assert resolved.path == "/org/gnome/shell/extensions/"
    assert key_for(resolved) == (
        f"keyfile:{profile}:{BMW_PROFILE}:/org/gnome/shell/extensions/ fire-enable-effect"
    )


def test_a_bare_profile_name_is_resolved_under_the_add_ons_own_folder(
    bmw_backend, tmp_dest_root
):
    """On this machine the setting holds a full location; older ones held a name."""
    from gtheme.panels.schema_probe import settings_file_for

    profiles = tmp_dest_root / ".config" / "burn-my-windows" / "profiles"
    profiles.mkdir(parents=True)
    (profiles / "123.conf").write_text("[burn-my-windows-profile]\n", encoding="utf-8")
    bmw_backend.set(BMW_ACTIVE, "'123.conf'")
    assert settings_file_for(BMW_PROFILE, bmw_backend) == profiles / "123.conf"


def test_an_ordinary_row_is_never_rewritten(bmw_backend):
    from gtheme.panels.schema_probe import resolve_row

    row = _row("org.gnome.desktop.interface", "color-scheme")
    assert resolve_row(row, bmw_backend) is row
