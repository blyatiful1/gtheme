"""What the Terminal page decides before it draws anything.

Where the colours come from, which Look is in use, and which command-window
apps are worth offering are all answerable without a widget, so they are
answered here — and that keeps the GTK tier down to "does it construct".
"""

from __future__ import annotations

import pytest

from gtheme.terminal.model import Palette
from gtheme.ui.pages import terminal


class _Meta:
    def __init__(self, name: str = "magma", title: str = "MAGMA") -> None:
        self.name = name
        self.title = title


class _Preset:
    def __init__(self, palette: dict[str, str], name: str = "magma") -> None:
        self.palette = palette
        self.meta = _Meta(name)


class _Look:
    def __init__(self, preset, name: str) -> None:
        self.preset = preset
        self.name = name


_SIXTEEN = {
    "ansi_black": "#000000",
    "ansi_red": "#ff0000",
    "ansi_green": "#00ff00",
    "ansi_yellow": "#ffff00",
    "ansi_blue": "#0000ff",
    "ansi_magenta": "#ff00ff",
    "ansi_cyan": "#00ffff",
    "ansi_white": "#ffffff",
    "ansi_bright_black": "#111111",
    "ansi_bright_red": "#ff1111",
    "ansi_bright_green": "#11ff11",
    "ansi_bright_yellow": "#ffff11",
    "ansi_bright_blue": "#1111ff",
    "ansi_bright_magenta": "#ff11ff",
    "ansi_bright_cyan": "#11ffff",
    "ansi_bright_white": "#f1f1f1",
}


# -- palettes ---------------------------------------------------------------


def test_a_look_with_no_colours_offers_no_palette():
    assert terminal.palette_from_look(_Preset({})) is None


def test_a_look_with_only_a_background_offers_no_palette():
    """Half a palette written into a terminal is worse than none."""
    assert terminal.palette_from_look(_Preset({"bg": "#000000"})) is None


def test_both_spellings_of_an_ansi_palette_are_read():
    """Looks say ``red``/``bright_red`` or ``ansi_red``/``ansi_bright_red``."""
    plain = {
        "bg": "#000000",
        "fg": "#ffffff",
        **{key.removeprefix("ansi_"): value for key, value in _SIXTEEN.items()},
    }
    prefixed = {"bg": "#000000", "fg": "#ffffff", **_SIXTEEN}
    assert terminal.palette_from_look(_Preset(plain)).ansi == (
        terminal.palette_from_look(_Preset(prefixed)).ansi
    )


def test_one_missing_ansi_colour_means_no_ansi_colours_at_all():
    incomplete = {"bg": "#000000", "fg": "#ffffff", **_SIXTEEN}
    del incomplete["ansi_bright_cyan"]
    palette = terminal.palette_from_look(_Preset(incomplete))
    assert palette is not None and palette.ansi == ()


def test_background_and_text_fall_back_to_the_palettes_own_black_and_white():
    """A Look that names its colours for itself still yields a terminal look."""
    palette = terminal.palette_from_look(_Preset(dict(_SIXTEEN)))
    assert palette is not None
    assert palette.background == "#000000"
    assert palette.foreground == "#ffffff"


def test_opacity_is_read_when_offered_and_clamped_when_silly():
    assert terminal.palette_from_look(_Preset({**_SIXTEEN, "opacity": "0.82"})).opacity == 0.82
    assert terminal.palette_from_look(_Preset({**_SIXTEEN, "opacity": "4"})).opacity == 1.0
    assert terminal.palette_from_look(_Preset({**_SIXTEEN, "opacity": "nope"})).opacity == 1.0


def test_every_bundled_look_converts_to_a_usable_terminal_palette():
    """The four Looks that ship are the ones a first-time user will apply."""
    from gtheme.preset import loader

    results = [result for result in loader.load_all() if result.preset is not None]
    assert len(results) >= 4
    for result in results:
        palette = terminal.palette_from_look(result.preset)
        assert palette is not None, f"{result.name} yields no terminal colours"
        assert len(palette.ansi) == 16, f"{result.name} lost its sixteen colours"
        # Constructing the Palette is what validates it; this is the guard that
        # the conversion cannot produce one the adapters would reject.
        Palette(
            name=palette.name,
            background=palette.background,
            foreground=palette.foreground,
            ansi=palette.ansi,
            opacity=palette.opacity,
        )


# -- which Look is in use ---------------------------------------------------
#
# CONTRACT CHANGED BY RULING (Wave-2 gate, R12): this was guessed by
# intersecting the ownership ledger's keys with the list of installed Looks.
# The guess was wrong three ways at once -- the ledger is keyed by a Look's
# title and the match was against its folder name, saved moments are ledger
# owners too, and a Look that still owns one leftover file is not the Look you
# are using. It is recorded when a Look is applied now, and read back.


def test_no_look_is_applied_when_nothing_recorded_one(state_dir):
    assert terminal.applied_look() is None


def test_the_recorded_look_is_the_applied_one(state_dir):
    from gtheme.core import ledger

    ledger.set_current_look("magma", label="MAGMA — Molten Glass")
    looks = [_Look(_Preset(dict(_SIXTEEN)), "magma"), _Look(_Preset({}), "netrunner")]
    assert terminal.applied_look(looks).name == "magma"


def test_a_look_whose_title_differs_from_its_name_is_still_found(state_dir):
    """The bug the guess had. A Look's ledger key is its *title*.

    Every bundled Look has a title unlike its folder name, so the old
    intersection matched none of them and the Terminal page offered nobody's
    colours on a desktop that had a Look applied.
    """
    from gtheme.core import ledger

    ledger.set_current_look("magma", label="MAGMA — Molten Glass")
    assert ledger.read_ledger() == {}, "no ledger entry at all, and it still works"
    assert terminal.applied_look([_Look(_Preset({}), "magma")]).name == "magma"


def test_a_look_that_owns_something_but_is_not_current_is_not_the_applied_one(state_dir):
    """Owning a leftover file is not the same as being the Look in use."""
    from gtheme.core import ledger

    ledger.write_entry("magma", [], [])
    ledger.write_entry("netrunner", [], [])
    looks = [_Look(_Preset({}), "magma"), _Look(_Preset({}), "netrunner")]
    assert terminal.applied_look(looks) is None


def test_a_saved_moment_is_not_a_look(state_dir):
    """Saved moments are ledger owners too, and were never Looks."""
    from gtheme.core import ledger

    ledger.write_entry("before", [], [])
    ledger.set_current_look("before")
    assert terminal.applied_look([_Look(_Preset({}), "magma")]) is None


def test_a_recorded_look_that_is_no_longer_installed_is_an_honest_none(state_dir):
    from gtheme.core import ledger

    ledger.set_current_look("uninstalled-since")
    assert terminal.applied_look([_Look(_Preset({}), "magma")]) is None


# -- which command window opens ---------------------------------------------


def test_only_apps_that_are_here_are_offered(monkeypatch):
    monkeypatch.setattr(
        terminal.shutil, "which", lambda name: "/usr/bin/" + name if name == "kitty" else None
    )
    assert terminal.installed_terminal_apps() == [("kitty", "Kitty")]


def test_the_app_row_becomes_a_pick_one_over_what_is_installed(memory_settings, monkeypatch):
    from gtheme.ui.search import page_rows

    monkeypatch.setattr(
        terminal.shutil, "which", lambda name: "/usr/bin/" + name if name == "foot" else None
    )
    row = page_rows("terminal")[0]
    turned = terminal.terminal_app_row(row, memory_settings)
    assert turned.kind.value == "choice"
    assert "'foot'" in [choice.value for choice in turned.choices]
    assert "'kitty'" not in [choice.value for choice in turned.choices]


def test_an_app_the_desktop_already_names_is_kept_in_the_list(memory_settings, monkeypatch):
    """Never quietly propose changing something the row cannot even show."""
    from gtheme.ui.search import page_rows
    from gtheme.ui.widgets.rows import key_for

    monkeypatch.setattr(terminal.shutil, "which", lambda _name: None)
    row = page_rows("terminal")[0]
    memory_settings.set(key_for(row), "'some-terminal-nobody-has'")
    turned = terminal.terminal_app_row(row, memory_settings)
    assert "'some-terminal-nobody-has'" in [choice.value for choice in turned.choices]


def test_the_app_row_stays_a_scan_row_when_there_is_nothing_to_offer(
    memory_settings, monkeypatch
):
    """No apps and nothing named: a pick-one with no options would be a lie."""
    from gtheme.panels.descriptor import Row, WidgetKind

    monkeypatch.setattr(terminal.shutil, "which", lambda _name: None)
    row = Row(
        schema_id="io.github.blyatiful1.NoSuchSettingsGroup",
        key="exec",
        title="Command window app",
        subtitle="The app that opens when something needs a command window.",
        kind=WidgetKind.PICKER,
    )
    assert terminal.terminal_app_row(row, memory_settings).kind is WidgetKind.PICKER


# -- the copy ---------------------------------------------------------------


def test_the_page_says_out_loud_what_it_does_not_manage():
    """DESIGN.md C18: spicetify is out of scope and the page admits it."""
    assert "not managed by this app" in terminal.COPY["spicetify"]


@pytest.mark.parametrize("key", ["colours-none", "apply", "take-over", "undo-take-over"])
def test_the_load_bearing_sentences_exist(key):
    assert terminal.COPY[key].strip()


def test_nothing_this_page_says_out_loud_is_jargon():
    """Every other page's copy is linted; this one's was not linted anywhere."""
    from gtheme.ui import jargon

    assert (
        jargon.check_all([(f"terminal.COPY[{key!r}]", text) for key, text in terminal.COPY.items()])
        == []
    )


def test_nothing_the_terminal_machinery_says_out_loud_is_jargon():
    """``apply_all`` reports failures in its own words; they reach a card."""
    from gtheme import terminal as package
    from gtheme.ui import jargon

    assert (
        jargon.check_all([(f"terminal.COPY[{key!r}]", text) for key, text in package.COPY.items()])
        == []
    )
