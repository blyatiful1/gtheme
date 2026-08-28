"""A Look's colours are untrusted text, and both locks on that door.

Every test here pins the confirmed review finding at
``src/gtheme/terminal/prompt.py:240``: a community Look's ``[palette]`` table is
``dict[str, str]`` with no validation, and the terminal adapters used to
interpolate those strings straight into other programs' settings files with
plain f-strings. Because a TOML basic string decodes ``\\n`` and ``\\"``, a
crafted colour could close gtheme's quote and open a table of its own —
concretely ``[custom.pwn]`` in ``~/.config/starship.toml``, whose ``command``
starship runs on every prompt draw. A Look that passes install validation
*because the format cannot hold code* would then have run code, which is the
one guarantee the whole preset format exists to make.

The fix has two layers and both are pinned here:

1. :class:`~gtheme.terminal.model.Palette` refuses anything that is not a
   colour, so no adapter ever receives the payload.
2. Every writer escapes (TOML) or refuses (the line-shaped files) a second
   time, so a value that reached it anyway still cannot become a setting.

Layer 2 is tested by smuggling a value past layer 1 with
``object.__setattr__`` — the only way to get one into a frozen dataclass — which
is exactly the "if it somehow reached the writer" case.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
from terminal_write_helper import land

from gtheme.terminal import apply_all
from gtheme.terminal.alacritty import AlacrittyAdapter, render_colors_toml
from gtheme.terminal.ghostty import GhosttyAdapter
from gtheme.terminal.model import Palette
from gtheme.terminal.monitors import CavaAdapter, render_btop_theme
from gtheme.terminal.prompt import StarshipAdapter
from gtheme.terminal.ptyxis import render_palette_file

#: The payload from the finding, verbatim. The adapter used to append the
#: closing quote itself, which is what made the result valid TOML.
STARSHIP_PAYLOAD = '#fff"\n[custom.pwn]\ncommand = "id > /tmp/pwned"\nwhen = "true"\nformat = "$output'

ANSI = tuple(f"#{i:02x}{i:02x}{i:02x}" for i in range(16))
GOOD = Palette(
    name="Nightbloom",
    background="#0A100C",
    foreground="#E8E4D6",
    cursor="#F5C04A",
    ansi=ANSI,
)


def smuggle(field: str, value: str, base: Palette = GOOD) -> Palette:
    """A palette carrying ``value``, past the validation that refuses it.

    Frozen dataclasses are not a security boundary; this is how a future code
    path that skipped ``Palette`` would look to a writer.
    """
    palette = Palette(
        name=base.name,
        background=base.background,
        foreground=base.foreground,
        cursor=base.cursor,
        ansi=base.ansi,
        opacity=base.opacity,
    )
    object.__setattr__(palette, field, value)
    return palette


def _opens_a_table(text: str) -> bool:
    """Whether any line of ``text`` is a ``[custom…]`` table header.

    The payload's characters may well appear inside a properly escaped string —
    that is what escaping looks like. What must never appear is a line that
    *starts a table*, because that is the difference between a colour nobody
    can read and a starship module that runs a command.
    """
    return any(re.match(r"[ \t]*\[custom", line) for line in text.splitlines())


# -- layer 1: the palette refuses it ---------------------------------------


def test_the_starship_payload_is_refused_when_the_palette_is_built():
    """FINDING prompt.py:240 — the crafted Look never becomes a Palette."""
    with pytest.raises(ValueError, match="not a colour"):
        Palette(
            name="Pwned",
            background="#0A100C",
            foreground="#E8E4D6",
            ansi=ANSI[:15] + (STARSHIP_PAYLOAD,),
        )


@pytest.mark.parametrize(
    "field",
    ["background", "foreground", "cursor"],
)
def test_every_colour_field_is_checked_not_just_the_ansi_list(field: str):
    """FINDING prompt.py:240 — background and cursor reach configs too."""
    fields = {"name": "Pwned", "background": "#0A100C", "foreground": "#E8E4D6"}
    fields[field] = STARSHIP_PAYLOAD
    with pytest.raises(ValueError, match="not a colour"):
        Palette(**fields)


def test_a_look_name_that_could_start_a_second_line_is_refused():
    """FINDING prompt.py:240 — the name is interpolated as well as the colours.

    ghostty's theme file and Ptyxis's palette file both write the look's name
    into a line of their own, and ghostty's config can name a program to run.
    """
    with pytest.raises(ValueError, match="will not write"):
        Palette(name="ok\ncommand = /bin/sh", background="#000000", foreground="#ffffff")


def test_the_colours_a_real_look_ships_are_all_accepted():
    """The refusal must not cost the spellings bundled Looks actually use."""
    for colour in ("#0A100C", "#fff", "#0a100cff", "0A100C"):
        Palette(name="ok", background=colour, foreground=colour)


def test_a_palette_refused_this_way_is_reported_not_raised(tmp_dest_root: Path):
    """apply_all turns the refusal into a sentence, one program at a time."""
    report = apply_all(smuggle("background", STARSHIP_PAYLOAD), [GhosttyAdapter()])
    assert report.problems["ghostty"] is not None
    assert "settings file" in report.problems["ghostty"]


# -- layer 2: the writers cannot be made to emit it ------------------------


@pytest.mark.mutating
def test_starship_never_grows_a_table_even_from_an_unvalidated_value(tmp_dest_root: Path):
    """FINDING prompt.py:240 — the payload lands as a string, not a module."""
    config = tmp_dest_root / ".config" / "starship.toml"
    config.parent.mkdir(parents=True)
    config.write_text("# mine\nadd_newline = false\n", encoding="utf-8")

    land(StarshipAdapter(), smuggle("background", STARSHIP_PAYLOAD))

    text = config.read_text(encoding="utf-8")
    assert not _opens_a_table(text), "the payload became a table of its own"
    data = tomllib.loads(text)
    assert "custom" not in data
    assert data["palettes"]["gtheme"]["background"] == STARSHIP_PAYLOAD


def test_the_alacritty_colours_file_escapes_rather_than_opens_a_table():
    """FINDING prompt.py:240 — same payload, the other TOML writer."""
    text = render_colors_toml(smuggle("foreground", STARSHIP_PAYLOAD))
    assert not _opens_a_table(text), "the payload became a table of its own"
    data = tomllib.loads(text)
    assert "custom" not in data
    assert data["colors"]["primary"]["foreground"] == STARSHIP_PAYLOAD


def test_ghostty_refuses_a_value_that_would_become_a_second_setting():
    """FINDING prompt.py:240 — a line-shaped file has nothing to escape into."""
    adapter = GhosttyAdapter()
    with pytest.raises(ValueError, match="settings file"):
        adapter._render_theme(smuggle("background", "#fff\ncommand = /bin/sh"))


def test_the_ptyxis_palette_file_refuses_the_same_thing():
    """FINDING prompt.py:240 — Ptyxis palettes are INI, one setting per line."""
    with pytest.raises(ValueError, match="settings file"):
        render_palette_file(smuggle("foreground", "#fff\nBackground=#ff0000"))


def test_the_btop_theme_refuses_a_value_carrying_its_own_quote():
    """FINDING prompt.py:240 — btop reads the text between the quotes as-is."""
    with pytest.raises(ValueError, match="settings file"):
        render_btop_theme(smuggle("foreground", '#fff"\ntheme[main_bg]="#ff0000'))


@pytest.mark.mutating
def test_cava_refuses_a_value_carrying_its_own_apostrophe(tmp_dest_root: Path):
    """FINDING prompt.py:240 — cava wraps gradient colours in apostrophes."""
    config = tmp_dest_root / ".config" / "cava" / "config"
    config.parent.mkdir(parents=True)
    config.write_text("[color]\ngradient = 0\n", encoding="utf-8")
    payload = "#fff'\nforeground = 'red"
    with pytest.raises(ValueError, match="settings file"):
        land(CavaAdapter(), smuggle("ansi", (payload,) * 16))
    assert "custom" not in config.read_text(encoding="utf-8")


# -- reading a config back is not a reason to refuse -----------------------


@pytest.mark.mutating
def test_a_hand_written_colour_gtheme_does_not_speak_reads_as_unknown(
    tmp_dest_root: Path,
):
    """Validation must not turn someone's own config into a traceback.

    A config naming its colours in words is not an attack and not gtheme's to
    fix; the honest answer to "what look is this wearing?" is "cannot tell".
    """
    directory = tmp_dest_root / ".config" / "alacritty"
    directory.mkdir(parents=True)
    (directory / "alacritty.toml").write_text(
        '[general]\nimport = ["~/.config/alacritty/gtheme-x.toml"]\n', encoding="utf-8"
    )
    (directory / "gtheme-x.toml").write_text(
        '[colors.primary]\nbackground = "CornflowerBlue"\nforeground = "white"\n',
        encoding="utf-8",
    )
    assert AlacrittyAdapter().current() is None
    assert AlacrittyAdapter().detect().installed is True
