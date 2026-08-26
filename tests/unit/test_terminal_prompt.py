"""fish and starship: a shell-out behind a seam, and a file kept intact."""

from __future__ import annotations

import tomllib
from collections.abc import Sequence
from pathlib import Path

import pytest

from gtheme.terminal.model import Palette, ReloadSemantics
from gtheme.terminal.prompt import FISH_COLOR_MAP, FishAdapter, StarshipAdapter, fish_env

ANSI = tuple(f"#{i:02x}{i:02x}{i:02x}" for i in range(16))
LOOK = Palette(
    name="Nightbloom",
    background="#0A100C",
    foreground="#E8E4D6",
    cursor="#F5C04A",
    ansi=ANSI,
)


class Recorder:
    """Stands in for running fish. Nothing is executed."""

    def __init__(self, output: str = "") -> None:
        self.calls: list[list[str]] = []
        self.output = output

    def __call__(self, argv: Sequence[str]) -> str:
        self.calls.append(list(argv))
        return self.output


# -- fish ------------------------------------------------------------------


def test_apply_sets_every_mapped_colour_in_one_invocation():
    recorder = Recorder()
    FishAdapter(recorder).apply(LOOK)
    assert len(recorder.calls) == 1
    argv = recorder.calls[0]
    assert argv[:2] == ["fish", "-c"]
    script = argv[2]
    for variable in FISH_COLOR_MAP:
        assert f"set --universal {variable} " in script


def test_colours_reach_fish_without_a_hash():
    script = FishAdapter(Recorder()).script(LOOK)
    assert "set --universal fish_color_normal e8e4d6" in script
    assert "#" not in script


def test_a_colour_that_is_not_a_colour_is_refused_before_anything_runs():
    """These values are interpolated into a shell command; refuse, never escape.

    CONTRACT CHANGED (review finding src/gtheme/terminal/prompt.py:240). The
    refusal used to happen inside the fish adapter, so this test used to build
    the bad Palette happily and expect ``apply`` to raise. Validation now lives
    in ``Palette`` itself, because fish was the *only* adapter that checked and
    the others were writing the same values into starship and ghostty configs
    that can name a command to run. So the construction is what raises now —
    and the adapter is still expected to refuse a value that got past it, which
    is what the second half of this test pins.
    """
    with pytest.raises(ValueError, match="not a colour"):
        Palette(name="bad", background="#000000", foreground="$(rm -rf ~)")

    recorder = Recorder()
    smuggled = Palette(name="bad", background="#000000", foreground="#ffffff")
    object.__setattr__(smuggled, "foreground", "$(rm -rf ~)")
    with pytest.raises(ValueError, match="not a colour"):
        FishAdapter(recorder).apply(smuggled)
    assert recorder.calls == []


def test_missing_ansi_slots_are_skipped_rather_than_guessed():
    script = FishAdapter(Recorder()).script(
        Palette(name="plain", background="#000000", foreground="#ffffff")
    )
    assert script == "set --universal fish_color_normal ffffff"


def test_colors_reads_back_what_fish_reports():
    recorder = Recorder("fish_color_normal e8e4d6\nfish_greeting \nfish_color_error e05a47\n")
    assert FishAdapter(recorder).colors() == {
        "fish_color_normal": "e8e4d6",
        "fish_color_error": "e05a47",
    }


def test_current_is_none_because_fish_has_no_background():
    assert FishAdapter(Recorder()).current() is None


@pytest.mark.mutating
def test_the_default_runner_reroots_fishs_own_config_home(tmp_dest_root: Path):
    """A real fish under a test root writes its variables into the test root."""
    assert fish_env()["XDG_CONFIG_HOME"] == str(tmp_dest_root / ".config")


# -- starship --------------------------------------------------------------

HAND_WRITTEN = """\
# My starship config.
add_newline = false
format = "$directory$git_branch$character"

[directory]
truncation_length = 3

[palettes.solarized]
background = "#002b36"
foreground = "#839496"
"""


@pytest.fixture
def starship(tmp_dest_root: Path) -> StarshipAdapter:
    (tmp_dest_root / ".config").mkdir(parents=True)
    (tmp_dest_root / ".config" / "starship.toml").write_text(HAND_WRITTEN, encoding="utf-8")
    return StarshipAdapter()


def test_starship_is_live():
    assert StarshipAdapter.reload_semantics is ReloadSemantics.LIVE


@pytest.mark.mutating
def test_apply_keeps_everything_the_user_wrote(starship: StarshipAdapter):
    starship.apply(LOOK)
    text = starship.config_path.read_text()
    data = tomllib.loads(text)
    assert "# My starship config." in text
    assert data["add_newline"] is False
    assert data["format"] == "$directory$git_branch$character"
    assert data["directory"]["truncation_length"] == 3
    assert data["palettes"]["solarized"]["background"] == "#002b36"


@pytest.mark.mutating
def test_apply_adds_its_own_palette_and_selects_it(starship: StarshipAdapter):
    starship.apply(LOOK)
    data = tomllib.loads(starship.config_path.read_text())
    assert data["palette"] == "gtheme"
    assert data["palettes"]["gtheme"]["background"] == "#0A100C"
    assert data["palettes"]["gtheme"]["color15"] == ANSI[15]


@pytest.mark.mutating
def test_applying_twice_replaces_rather_than_duplicates(starship: StarshipAdapter):
    starship.apply(LOOK)
    starship.apply(Palette(name="Other", background="#111111", foreground="#eeeeee"))
    text = starship.config_path.read_text()
    assert text.count("[palettes.gtheme]") == 1
    assert text.count("palette = ") == 1
    data = tomllib.loads(text)
    assert data["palettes"]["gtheme"]["background"] == "#111111"
    assert "color0" not in data["palettes"]["gtheme"]


@pytest.mark.mutating
def test_current_round_trips(starship: StarshipAdapter):
    starship.apply(LOOK)
    read_back = starship.current()
    assert read_back is not None
    assert read_back.name == "gtheme"
    assert read_back.foreground == LOOK.foreground
    assert read_back.ansi == ANSI


@pytest.mark.mutating
def test_a_missing_file_is_created(tmp_dest_root: Path):
    adapter = StarshipAdapter()
    adapter.apply(LOOK)
    data = tomllib.loads(adapter.config_path.read_text())
    assert data["palette"] == "gtheme"
