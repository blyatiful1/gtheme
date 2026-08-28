"""Ptyxis: a palette file plus two settings, one of them relocatable.

The schemas are compiled for the test rather than taken from the machine. Ptyxis
may not be installed on whatever runs this — and more importantly, a test that
depends on the machine's real schemas is one step away from depending on the
machine's real settings.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from terminal_write_helper import land

from gtheme.terminal.model import Palette, ReloadSemantics
from gtheme.terminal.ptyxis import (
    PROFILE_PLACEHOLDER,
    PtyxisAdapter,
    palette_file_name,
    profile_key,
    profile_path,
    render_palette_file,
    resolve_placeholders,
)

UUID = "86994fa57bfbe7ca68edf3bf6a4cc13d"

SCHEMAS = f"""<?xml version="1.0" encoding="UTF-8"?>
<schemalist>
  <schema id="org.gnome.Ptyxis" path="/org/gnome/Ptyxis/">
    <key name="default-profile-uuid" type="s"><default>'{UUID}'</default></key>
    <key name="use-system-font" type="b"><default>true</default></key>
  </schema>
  <schema id="org.gnome.Ptyxis.Profile">
    <key name="palette" type="s"><default>'gnome'</default></key>
    <key name="opacity" type="d"><default>1.0</default></key>
  </schema>
</schemalist>
"""

ANSI = tuple(f"#{i:02x}{i:02x}{i:02x}" for i in range(16))
LOOK = Palette(
    name="Nightbloom",
    background="#0A100C",
    foreground="#E8E4D6",
    cursor="#F5C04A",
    ansi=ANSI,
    opacity=0.88,
)


@pytest.fixture
def ptyxis(tmp_dest_root: Path, memory_settings, schema_source_factory) -> PtyxisAdapter:
    memory_settings.schema_source = schema_source_factory(SCHEMAS)
    return PtyxisAdapter(memory_settings)


# -- the key grammar -------------------------------------------------------


def test_profile_keys_use_the_relocatable_form():
    assert profile_path(UUID) == f"/org/gnome/Ptyxis/Profiles/{UUID}/"
    assert profile_key(UUID, "palette") == (
        f"gsettings-path:org.gnome.Ptyxis.Profile:/org/gnome/Ptyxis/Profiles/{UUID}/ palette"
    )


def test_the_key_grammar_accepts_what_this_module_builds():
    from gtheme.core.settings_backend import KeyKind, parse_key

    parsed = parse_key(profile_key(UUID, "opacity"))
    assert parsed.kind is KeyKind.GSETTINGS_PATH
    assert parsed.path == profile_path(UUID)
    assert parsed.key == "opacity"


def test_the_v1_placeholder_is_still_honoured():
    template = f"/org/gnome/Ptyxis/Profiles/{PROFILE_PLACEHOLDER}/palette"
    assert resolve_placeholders(template, UUID).endswith(f"Profiles/{UUID}/palette")
    assert resolve_placeholders("{{ptyxis_default_profile}}", UUID) == UUID


def test_a_palette_name_cannot_become_a_path():
    assert palette_file_name("../../etc/shadow") == "etcshadow"
    assert palette_file_name("Nightbloom") == "Nightbloom"


# -- the palette file ------------------------------------------------------


def test_palette_file_has_both_sections_ptyxis_switches_between():
    text = render_palette_file(LOOK)
    assert "[Palette]" in text and "Name=Nightbloom" in text
    assert "[Dark]" in text and "[Light]" in text
    assert text.count("Background=#0A100C") == 2
    assert "Color15=#0f0f0f" in text


# -- applying --------------------------------------------------------------


@pytest.mark.mutating
def test_apply_writes_the_file_then_selects_it(ptyxis: PtyxisAdapter):
    land(ptyxis, LOOK, ptyxis.backend)
    written = ptyxis.palettes_dir / "Nightbloom.palette"
    assert written.is_file()
    assert ptyxis.backend.get(profile_key(UUID, "palette")) == "'Nightbloom'"
    assert float(ptyxis.backend.get(profile_key(UUID, "opacity"))) == pytest.approx(0.88)


@pytest.mark.mutating
def test_current_round_trips_the_applied_look(ptyxis: PtyxisAdapter):
    land(ptyxis, LOOK, ptyxis.backend)
    read_back = ptyxis.current()
    assert read_back is not None
    assert read_back.name == "Nightbloom"
    assert read_back.background == LOOK.background
    assert read_back.ansi == ANSI
    assert read_back.opacity == pytest.approx(0.88)


@pytest.mark.mutating
def test_reload_semantics_say_it_is_immediate(ptyxis: PtyxisAdapter):
    assert ptyxis.reload_semantics is ReloadSemantics.LIVE
    assert "straight away" in ptyxis.detect().notes[0]


@pytest.mark.mutating
def test_without_a_readable_profile_nothing_is_written(
    tmp_dest_root: Path, memory_settings, schema_source_factory
):
    """No profile means no safe target — so it refuses instead of guessing."""
    empty = """<?xml version="1.0" encoding="UTF-8"?>
    <schemalist>
      <schema id="org.gnome.Other" path="/org/gnome/Other/">
        <key name="x" type="b"><default>false</default></key>
      </schema>
    </schemalist>
    """
    memory_settings.schema_source = schema_source_factory(empty)
    adapter = PtyxisAdapter(memory_settings)
    assert adapter.default_profile_uuid() is None
    with pytest.raises(PermissionError, match="has not changed anything"):
        land(adapter, LOOK, memory_settings)
    assert not adapter.palettes_dir.exists()


@pytest.mark.mutating
def test_current_is_none_before_anything_is_applied(ptyxis: PtyxisAdapter):
    """The schema default names a palette whose file does not exist."""
    assert ptyxis.current() is None
