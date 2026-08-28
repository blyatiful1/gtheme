"""GNOME Terminal and Console — the two terminals stock GNOME and Ubuntu ship.

gtheme knew about neither, so the Terminal page said "No command window found"
to a person looking straight at their command window, directly above a dropdown
offering it by name (persona-report §3.2).

The schemas are compiled for the test rather than taken from the machine.
Neither program is installed on the one this was written on — which is the
normal case for at least one of them anywhere — and a test that depends on the
machine's real schemas is one step away from depending on its real settings.
"""

from __future__ import annotations

import pytest

from gtheme.core.settings_backend import MemoryBackend
from gtheme.terminal import console as console_module
from gtheme.terminal import gnometerminal as gnome_module
from gtheme.terminal.console import TRANSPARENCY_KEY, ConsoleAdapter
from gtheme.terminal.gnometerminal import GnomeTerminalAdapter, profile_key, profile_path
from gtheme.terminal.model import Palette, ReloadSemantics

UUID = "b1dcc9dd-5262-4d8d-a863-c897e6d979b9"

ANSI = tuple(f"#{i:02x}{i:02x}{i:02x}" for i in range(16))
LOOK = Palette(
    name="Nightbloom",
    background="#0A100C",
    foreground="#E8E4D6",
    cursor="#F5C04A",
    ansi=ANSI,
    opacity=0.75,
)

_COLOUR_KEYS = """
    <key name="visible-name" type="s"><default>'Unnamed'</default></key>
    <key name="foreground-color" type="s"><default>'#171421'</default></key>
    <key name="background-color" type="s"><default>'#ffffff'</default></key>
    <key name="bold-color-same-as-fg" type="b"><default>true</default></key>
    <key name="cursor-colors-set" type="b"><default>false</default></key>
    <key name="cursor-background-color" type="s"><default>'#171421'</default></key>
    <key name="cursor-foreground-color" type="s"><default>'#ffffff'</default></key>
    <key name="palette" type="as"><default>[]</default></key>
    <key name="use-theme-colors" type="b"><default>true</default></key>
"""

_TRANSPARENCY_KEYS = """
    <key name="use-transparent-background" type="b"><default>false</default></key>
    <key name="background-transparency-percent" type="i"><default>0</default></key>
"""


def _terminal_schemas(*, transparency: bool = True) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<schemalist>
  <schema id="org.gnome.Terminal.ProfilesList" path="/org/gnome/terminal/legacy/profiles:/">
    <key name="default" type="s"><default>'{UUID}'</default></key>
    <key name="list" type="as"><default>['{UUID}']</default></key>
  </schema>
  <schema id="org.gnome.Terminal.Legacy.Profile">
    {_COLOUR_KEYS}
    {_TRANSPARENCY_KEYS if transparency else ""}
  </schema>
</schemalist>
"""

CONSOLE_SCHEMA = """<?xml version="1.0" encoding="UTF-8"?>
<schemalist>
  <schema id="org.gnome.Console" path="/org/gnome/Console/">
    <key name="transparency" type="b"><default>false</default></key>
    <key name="font-scale" type="d"><default>1.0</default></key>
  </schema>
</schemalist>
"""


@pytest.fixture
def terminal(memory_settings, schema_source_factory) -> GnomeTerminalAdapter:
    memory_settings.schema_source = schema_source_factory(_terminal_schemas())
    return GnomeTerminalAdapter(memory_settings)


@pytest.fixture
def console(memory_settings, schema_source_factory) -> ConsoleAdapter:
    memory_settings.schema_source = schema_source_factory(CONSOLE_SCHEMA)
    return ConsoleAdapter(memory_settings)


def _plan(adapter, palette=LOOK) -> dict[str, str]:
    return {change.key: change.value for change in adapter.plan(palette).settings}


# -- GNOME Terminal: the key grammar ---------------------------------------


def test_the_profile_path_is_gnome_terminals_own_spelling():
    assert profile_path(UUID) == f"/org/gnome/terminal/legacy/profiles:/:{UUID}/"


def test_the_key_grammar_accepts_what_this_module_builds():
    from gtheme.core.settings_backend import KeyKind, parse_key

    parsed = parse_key(profile_key(UUID, "background-color"))
    assert parsed.kind is KeyKind.GSETTINGS_PATH
    assert parsed.path == profile_path(UUID)
    assert parsed.key == "background-color"


def test_a_profile_that_is_not_a_uuid_is_refused(memory_settings, schema_source_factory):
    """It is read out of the store and pasted into a settings path."""
    memory_settings.schema_source = schema_source_factory(_terminal_schemas())
    memory_settings.set("gsettings:org.gnome.Terminal.ProfilesList default", "'../../etc'")
    adapter = GnomeTerminalAdapter(memory_settings)

    assert adapter.default_profile_uuid() is None
    with pytest.raises(PermissionError, match="has not changed anything"):
        adapter.plan(LOOK)


# -- GNOME Terminal: what it plans -----------------------------------------


@pytest.mark.mutating
def test_the_look_lands_on_the_default_profile(terminal):
    planned = _plan(terminal)

    assert planned[profile_key(UUID, "background-color")] == "'#0a100c'"
    assert planned[profile_key(UUID, "foreground-color")] == "'#e8e4d6'"
    assert planned[profile_key(UUID, "cursor-background-color")] == "'#f5c04a'"
    assert planned[profile_key(UUID, "palette")].startswith("['#000000'")


@pytest.mark.mutating
def test_the_profile_is_told_to_use_the_colours_it_was_given(terminal):
    """``use-theme-colors`` is true by default: without this nothing is seen."""
    planned = _plan(terminal)
    assert planned[profile_key(UUID, "use-theme-colors")] == "false"


@pytest.mark.mutating
def test_a_see_through_look_asks_for_the_matching_transparency(terminal):
    planned = _plan(terminal)
    assert planned[profile_key(UUID, "use-transparent-background")] == "true"
    assert planned[profile_key(UUID, "background-transparency-percent")] == "25"


@pytest.mark.mutating
def test_a_solid_look_turns_the_see_through_background_off(terminal):
    solid = Palette(name="Solid", background="#000000", foreground="#ffffff")
    planned = _plan(terminal, solid)

    assert planned[profile_key(UUID, "use-transparent-background")] == "false"
    assert profile_key(UUID, "background-transparency-percent") not in planned


@pytest.mark.mutating
def test_a_palette_without_sixteen_colours_writes_none_of_them(terminal):
    plain = Palette(name="Plain", background="#000000", foreground="#ffffff")
    assert profile_key(UUID, "palette") not in _plan(terminal, plain)


@pytest.mark.mutating
def test_a_key_this_version_does_not_have_is_left_out(memory_settings, schema_source_factory):
    """The transparency pair has moved between versions and distributions.

    Planning a key the schema does not have would fail the whole batch — and
    take the colour keys, which every version does have, down with it.
    """
    memory_settings.schema_source = schema_source_factory(_terminal_schemas(transparency=False))
    planned = _plan(GnomeTerminalAdapter(memory_settings))

    assert profile_key(UUID, "use-transparent-background") not in planned
    assert planned[profile_key(UUID, "background-color")] == "'#0a100c'"


@pytest.mark.mutating
def test_a_schema_with_no_colour_keys_at_all_refuses(memory_settings, schema_source_factory):
    empty = f"""<?xml version="1.0" encoding="UTF-8"?>
    <schemalist>
      <schema id="org.gnome.Terminal.ProfilesList" path="/org/gnome/terminal/legacy/profiles:/">
        <key name="default" type="s"><default>'{UUID}'</default></key>
      </schema>
      <schema id="org.gnome.Terminal.Legacy.Profile">
        <key name="audible-bell" type="b"><default>true</default></key>
      </schema>
    </schemalist>
    """
    memory_settings.schema_source = schema_source_factory(empty)

    with pytest.raises(PermissionError, match="has not changed anything"):
        GnomeTerminalAdapter(memory_settings).plan(LOOK)


# -- GNOME Terminal: what it reads back ------------------------------------


@pytest.mark.mutating
def test_a_profile_following_the_desktop_theme_is_an_honest_unknown(terminal):
    """While ``use-theme-colors`` is on, the stored colours are not on screen."""
    assert terminal.current() is None


@pytest.mark.mutating
def test_current_round_trips_what_the_plan_would_write(terminal):
    for change in terminal.plan(LOOK).settings:
        terminal.backend.set(change.key, change.value)

    read_back = terminal.current()
    assert read_back is not None
    assert read_back.background == "#0a100c"
    assert read_back.ansi == ANSI
    assert read_back.opacity == pytest.approx(0.75)


@pytest.mark.mutating
def test_it_is_not_there_when_the_program_is_not(terminal, monkeypatch):
    monkeypatch.setattr(gnome_module.shutil, "which", lambda _name: None)
    state = terminal.detect()
    assert not state.installed
    assert state.current is None


@pytest.mark.mutating
def test_it_says_so_when_the_settings_cannot_be_read(
    memory_settings, schema_source_factory, monkeypatch
):
    monkeypatch.setattr(gnome_module.shutil, "which", lambda name: f"/usr/bin/{name}")
    memory_settings.schema_source = schema_source_factory(CONSOLE_SCHEMA)
    state = GnomeTerminalAdapter(memory_settings).detect()

    assert state.installed
    assert any("could not read" in note for note in state.notes)


# -- Console ---------------------------------------------------------------


@pytest.mark.mutating
def test_console_matches_the_see_through_background_and_nothing_else(console):
    planned = _plan(console)
    assert planned == {TRANSPARENCY_KEY: "true"}

    solid = Palette(name="Solid", background="#000000", foreground="#ffffff")
    assert _plan(console, solid) == {TRANSPARENCY_KEY: "false"}


@pytest.mark.mutating
def test_console_says_out_loud_which_part_of_the_look_it_will_not_take(console, monkeypatch):
    monkeypatch.setattr(console_module.shutil, "which", lambda name: f"/usr/bin/{name}")
    notes = console.detect().notes

    assert any("chooses its own colours" in note for note in notes)
    assert console.reload_semantics is ReloadSemantics.LIVE


@pytest.mark.mutating
def test_console_never_claims_to_know_which_colours_it_is_wearing(console):
    assert console.current() is None


@pytest.mark.mutating
def test_console_without_its_setting_refuses_rather_than_writing_blind(memory_settings):
    """A Console whose settings are not readable here — a sandboxed one, say."""
    adapter = ConsoleAdapter(MemoryBackend())
    del memory_settings  # requested for the seam

    with pytest.raises(PermissionError, match="has not changed anything"):
        adapter.plan(LOOK)


@pytest.mark.mutating
def test_console_is_not_there_when_the_program_is_not(console, monkeypatch):
    monkeypatch.setattr(console_module.shutil, "which", lambda _name: None)
    assert not console.detect().installed


# -- both, on the page -----------------------------------------------------


def test_both_are_offered_once_there_is_a_settings_seam(memory_settings):
    from gtheme.terminal import adapters

    ids = {adapter.id for adapter in adapters(memory_settings)}
    assert {"gnome-terminal", "console"} <= ids
    assert not {"gnome-terminal", "console"} & {adapter.id for adapter in adapters()}


@pytest.mark.mutating
def test_nothing_either_of_them_says_out_loud_is_jargon(terminal, console, monkeypatch):
    from gtheme.ui.jargon import find_banned

    monkeypatch.setattr(gnome_module.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(console_module.shutil, "which", lambda name: f"/usr/bin/{name}")
    for adapter in (terminal, console):
        assert find_banned(adapter.name) == [], adapter.name
        for note in adapter.detect().notes:
            assert find_banned(note) == [], f"{adapter.id}: {note}"
