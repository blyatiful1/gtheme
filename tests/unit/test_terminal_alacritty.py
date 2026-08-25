"""Alacritty: an owned colours file, imported from a config the user keeps."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from gtheme.terminal.alacritty import AlacrittyAdapter, render_colors_toml
from gtheme.terminal.model import Palette, ReloadSemantics

ANSI = tuple(f"#{i:02x}{i:02x}{i:02x}" for i in range(16))
LOOK = Palette(
    name="Nightbloom",
    background="#0A100C",
    foreground="#E8E4D6",
    cursor="#F5C04A",
    ansi=ANSI,
    opacity=0.82,
)

HAND_WRITTEN = """\
# My alacritty config. Do not lose my comments.
[general]
import = [
  "~/.config/alacritty/keys.toml",
  "~/.config/alacritty/gtheme-oldlook.toml",
]
live_config_reload = true

[window]
padding = { x = 12, y = 10 }
decorations = "None"

[font]
size = 11.0
"""


@pytest.fixture
def alacritty(tmp_dest_root: Path) -> AlacrittyAdapter:
    directory = tmp_dest_root / ".config" / "alacritty"
    directory.mkdir(parents=True)
    (directory / "alacritty.toml").write_text(HAND_WRITTEN, encoding="utf-8")
    return AlacrittyAdapter()


def test_reload_semantics_say_it_reloads_itself():
    assert AlacrittyAdapter.reload_semantics is ReloadSemantics.AUTO_RELOAD


def test_colours_file_is_valid_toml_with_all_sixteen():
    data = tomllib.loads(render_colors_toml(LOOK))
    colours = data["colors"]
    assert colours["primary"]["background"] == "#0A100C"
    assert colours["normal"]["black"] == ANSI[0]
    assert colours["bright"]["white"] == ANSI[15]
    assert colours["cursor"]["cursor"] == "#F5C04A"


@pytest.mark.mutating
def test_apply_leaves_a_config_that_still_parses_and_keeps_its_settings(
    alacritty: AlacrittyAdapter,
):
    alacritty.apply(LOOK)
    text = alacritty.config_path.read_text()
    data = tomllib.loads(text)
    assert "# My alacritty config. Do not lose my comments." in text
    assert data["general"]["live_config_reload"] is True
    assert data["window"]["padding"] == {"x": 12, "y": 10}
    assert data["window"]["decorations"] == "None"
    assert data["font"]["size"] == 11.0


@pytest.mark.mutating
def test_apply_adds_its_import_and_drops_the_previous_look(alacritty: AlacrittyAdapter):
    alacritty.apply(LOOK)
    imports = tomllib.loads(alacritty.config_path.read_text())["general"]["import"]
    assert "~/.config/alacritty/keys.toml" in imports
    assert "~/.config/alacritty/gtheme-nightbloom.toml" in imports
    assert not any("gtheme-oldlook" in entry for entry in imports)


@pytest.mark.mutating
def test_apply_sets_opacity_and_asks_for_real_blur(alacritty: AlacrittyAdapter):
    """Alacritty's blur, unlike ghostty's, is a real request on this desktop."""
    alacritty.apply(LOOK)
    window = tomllib.loads(alacritty.config_path.read_text())["window"]
    assert window["opacity"] == pytest.approx(0.82)
    assert window["blur"] is True


@pytest.mark.mutating
def test_a_solid_look_does_not_ask_for_blur(alacritty: AlacrittyAdapter):
    alacritty.apply(Palette(name="Solid", background="#000000", foreground="#ffffff"))
    window = tomllib.loads(alacritty.config_path.read_text())["window"]
    assert window["opacity"] == pytest.approx(1.0)
    assert window["blur"] is False


@pytest.mark.mutating
def test_current_round_trips(alacritty: AlacrittyAdapter):
    alacritty.apply(LOOK)
    read_back = alacritty.current()
    assert read_back is not None
    assert read_back.background == LOOK.background
    assert read_back.ansi == ANSI
    assert read_back.opacity == pytest.approx(0.82)


@pytest.mark.mutating
def test_applying_twice_does_not_grow_the_import_list(alacritty: AlacrittyAdapter):
    alacritty.apply(LOOK)
    alacritty.apply(LOOK)
    imports = tomllib.loads(alacritty.config_path.read_text())["general"]["import"]
    assert imports.count("~/.config/alacritty/gtheme-nightbloom.toml") == 1


@pytest.mark.mutating
def test_a_missing_config_is_created_from_nothing(tmp_dest_root: Path):
    adapter = AlacrittyAdapter()
    adapter.apply(LOOK)
    data = tomllib.loads(adapter.config_path.read_text())
    assert data["general"]["import"] == ["~/.config/alacritty/gtheme-nightbloom.toml"]
    assert data["window"]["opacity"] == pytest.approx(0.82)
