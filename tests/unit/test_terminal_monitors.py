"""btop, cava and fastfetch: three heavily-commented files, edited in place."""

from __future__ import annotations

from pathlib import Path

import pytest
from terminal_write_helper import land

from gtheme.terminal.model import Palette, ReloadSemantics
from gtheme.terminal.monitors import (
    BtopAdapter,
    CavaAdapter,
    FastfetchAdapter,
    cava_gradient,
    render_btop_theme,
)

ANSI = tuple(f"#{i:02x}{i:02x}{i:02x}" for i in range(16))
LOOK = Palette(
    name="Nightbloom",
    background="#0A100C",
    foreground="#E8E4D6",
    cursor="#F5C04A",
    ansi=ANSI,
    opacity=0.82,
)

BTOP_CONF = """\
#? Config file for btop — hand written, keep my comments.

color_theme = "netrunner"
theme_background = True
truecolor = True
update_ms = 1000
"""

CAVA_CONF = """\
# ── my cava ──────────────────────────────────
[general]
framerate = 60
bars = 0

[color]
# The gradient climbs from moss to amber.
gradient = 1
gradient_count = 5
gradient_color_1 = '#111111'
gradient_color_2 = '#222222'
gradient_color_3 = '#333333'
gradient_color_4 = '#444444'
gradient_color_5 = '#555555'

[smoothing]
noise_reduction = 40
"""

FASTFETCH = """\
// My fastfetch config — the comments matter.
{
  "logo": {
    "type": "file",
    "source": "~/.config/fastfetch/logo.txt",
    "color": {
      "1": "38;2;1;1;1",   // stems
      "2": "38;2;2;2;2"    // pot
    },
    "padding": { "top": 1 }
  },
  "display": {
    "separator": "  ",
    "color": { "keys": "38;2;9;9;9", "output": "38;2;8;8;8" }
  },
  "modules": ["title", "os"]
}
"""


@pytest.fixture
def btop(tmp_dest_root: Path) -> BtopAdapter:
    directory = tmp_dest_root / ".config" / "btop"
    directory.mkdir(parents=True)
    (directory / "btop.conf").write_text(BTOP_CONF, encoding="utf-8")
    return BtopAdapter()


@pytest.fixture
def cava(tmp_dest_root: Path) -> CavaAdapter:
    directory = tmp_dest_root / ".config" / "cava"
    directory.mkdir(parents=True)
    (directory / "config").write_text(CAVA_CONF, encoding="utf-8")
    return CavaAdapter()


@pytest.fixture
def fastfetch(tmp_dest_root: Path) -> FastfetchAdapter:
    directory = tmp_dest_root / ".config" / "fastfetch"
    directory.mkdir(parents=True)
    (directory / "config.jsonc").write_text(FASTFETCH, encoding="utf-8")
    return FastfetchAdapter()


# -- restart semantics are the whole point of this module ------------------


def test_the_two_running_programs_say_the_change_needs_a_restart():
    for adapter in (BtopAdapter, CavaAdapter):
        assert adapter.reload_semantics is ReloadSemantics.RESTART


def test_fastfetch_is_one_shot_not_restart():
    """It is not a running program, so "close it and open it again" is a lie."""
    assert FastfetchAdapter.reload_semantics is ReloadSemantics.ONE_SHOT
    assert ReloadSemantics.ONE_SHOT.sentence() == "Run it again to see this."


@pytest.mark.mutating
def test_fastfetch_tells_the_user_the_one_shot_story(fastfetch: FastfetchAdapter):
    """The note comes from the vocabulary now, not from a hand-written aside."""
    assert fastfetch.detect().notes == [ReloadSemantics.ONE_SHOT.sentence()]


# -- btop ------------------------------------------------------------------


def test_btop_theme_uses_btops_own_format():
    text = render_btop_theme(LOOK)
    assert 'theme[main_bg]="#0A100C"' in text
    assert 'theme[main_fg]="#E8E4D6"' in text
    assert 'theme[hi_fg]="#F5C04A"' in text


@pytest.mark.mutating
def test_btop_apply_writes_the_theme_and_names_it(btop: BtopAdapter):
    land(btop, LOOK)
    assert (btop.themes_dir / "nightbloom.theme").is_file()
    text = btop.config_path.read_text()
    assert 'color_theme = "nightbloom"' in text
    assert "#? Config file for btop — hand written, keep my comments." in text
    assert "update_ms = 1000" in text


@pytest.mark.mutating
def test_btop_lets_the_terminals_glass_show_through_a_see_through_look(btop: BtopAdapter):
    land(btop, LOOK)
    assert "theme_background = False" in btop.config_path.read_text()


@pytest.mark.mutating
def test_btop_leaves_the_background_alone_for_a_solid_look(btop: BtopAdapter):
    land(btop, Palette(name="Solid", background="#000000", foreground="#ffffff"))
    assert "theme_background = True" in btop.config_path.read_text()


@pytest.mark.mutating
def test_btop_current_reads_back_the_named_theme(btop: BtopAdapter):
    land(btop, LOOK)
    read_back = btop.current()
    assert read_back is not None
    assert (read_back.background, read_back.foreground) == (LOOK.background, LOOK.foreground)


# -- cava ------------------------------------------------------------------


def test_the_gradient_climbs_through_the_palette():
    assert cava_gradient(LOOK) == [ANSI[2], ANSI[6], ANSI[4], ANSI[5], ANSI[3]]


def test_a_palette_without_ansi_still_yields_a_gradient():
    plain = Palette(name="plain", background="#000000", foreground="#ffffff")
    assert cava_gradient(plain) == ["#ffffff", "#ffffff"]


@pytest.mark.mutating
def test_cava_apply_replaces_the_gradient_and_keeps_the_rest(cava: CavaAdapter):
    land(cava, LOOK)
    text = cava.config_path.read_text()
    assert "# ── my cava ──────────────────────────────────" in text
    assert "# The gradient climbs from moss to amber." in text
    assert "noise_reduction = 40" in text
    assert "framerate = 60" in text
    assert cava.gradient() == list(cava_gradient(LOOK))


@pytest.mark.mutating
def test_a_shorter_gradient_leaves_no_stale_colour_on_top(cava: CavaAdapter):
    land(cava, Palette(name="plain", background="#000000", foreground="#ffffff"))
    text = cava.config_path.read_text()
    assert "gradient_count = 2" in text
    assert "gradient_color_3" not in text
    assert "#555555" not in text


@pytest.mark.mutating
def test_cava_writes_a_section_into_a_config_that_had_none(tmp_dest_root: Path):
    path = tmp_dest_root / ".config" / "cava" / "config"
    path.parent.mkdir(parents=True)
    path.write_text("[general]\nframerate = 60\n", encoding="utf-8")
    adapter = CavaAdapter()
    land(adapter, LOOK)
    assert "[color]" in path.read_text()
    assert adapter.gradient() == list(cava_gradient(LOOK))


# -- fastfetch -------------------------------------------------------------


@pytest.mark.mutating
def test_fastfetch_recolours_the_slots_and_keeps_its_comments(fastfetch: FastfetchAdapter):
    land(fastfetch, LOOK)
    text = fastfetch.config_path.read_text()
    assert "// My fastfetch config — the comments matter." in text
    assert "// stems" in text
    assert '"modules": ["title", "os"]' in text
    assert '"source": "~/.config/fastfetch/logo.txt"' in text
    assert '"padding": { "top": 1 }' in text
    assert "38;2;1;1;1" not in text
    assert '"separator": "  "' in text


@pytest.mark.mutating
def test_fastfetch_only_touches_colours_inside_the_blocks_it_owns(
    fastfetch: FastfetchAdapter,
):
    land(fastfetch, LOOK)
    import json
    import re

    stripped = re.sub(r"//[^\n]*", "", fastfetch.config_path.read_text())
    data = json.loads(stripped)
    assert set(data["logo"]["color"]) == {"1", "2"}
    assert data["logo"]["color"]["1"].startswith("38;2;")
    assert data["display"]["color"]["output"] == "38;2;232;228;214"
    assert data["display"]["separator"] == "  "


@pytest.mark.mutating
def test_fastfetch_says_so_instead_of_inventing_a_config(tmp_dest_root: Path):
    adapter = FastfetchAdapter()
    with pytest.raises(PermissionError, match="nothing to recolour"):
        land(adapter, LOOK)


@pytest.mark.mutating
def test_fastfetch_refuses_a_config_with_no_colours_to_change(tmp_dest_root: Path):
    path = tmp_dest_root / ".config" / "fastfetch" / "config.jsonc"
    path.parent.mkdir(parents=True)
    path.write_text('{ "modules": ["title"] }\n', encoding="utf-8")
    adapter = FastfetchAdapter()
    with pytest.raises(PermissionError, match="no colours gtheme knows"):
        land(adapter, LOOK)
    assert path.read_text() == '{ "modules": ["title"] }\n'
