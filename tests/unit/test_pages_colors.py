"""Colours & Style: the two-key dark change, the nine dots, the two pickers."""

from __future__ import annotations

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for the page library")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402
from test_pages_style_common import build_page, make_window  # noqa: E402

from gtheme.core.backends import use_backend  # noqa: E402
from gtheme.core.transaction import SettingWrite  # noqa: E402
from gtheme.ui import jargon  # noqa: E402
from gtheme.ui.pages import _style_common as common  # noqa: E402
from gtheme.ui.pages import colors  # noqa: E402

pytestmark = pytest.mark.gtk

INSTALLED = {"adw-gtk3", "adw-gtk3-dark", "Adwaita"}


# --------------------------------------------------------------------------
# the copy
# --------------------------------------------------------------------------


def test_every_sentence_this_page_says_is_plain_english():
    problems = jargon.check_all(
        [(f"colors.COPY[{k!r}]", v) for k, v in colors.COPY.items()]
    )
    assert problems == [], "\n".join(problems)


def test_the_page_is_honest_that_a_colour_of_your_own_is_not_possible():
    """GNOME's highlight colour is a fixed list. Silence there sends people hunting."""
    assert "a colour of your own" in colors.COPY["accent-description"]


def test_the_fix_button_offers_the_action_instead_of_naming_the_component():
    """The single worst string in GNOME Tweaks, replaced by a button that works."""
    assert colors.COPY["topbar-missing-addon"].startswith("To use this, gtheme needs to turn on")
    assert colors.COPY["topbar-turn-on"] == "Turn it on"


# --------------------------------------------------------------------------
# light and dark
# --------------------------------------------------------------------------


@pytest.mark.mutating
def test_turning_dark_on_writes_both_keys(memory_settings):
    memory_settings.set(colors.GTK_THEME_KEY, "'adw-gtk3'")
    ops = colors.dark_mode_ops(memory_settings, True, INSTALLED)
    assert ops == [
        SettingWrite(colors.COLOR_SCHEME_KEY, "'prefer-dark'", component="colors"),
        SettingWrite(colors.GTK_THEME_KEY, "'adw-gtk3-dark'", component="colors"),
    ]


@pytest.mark.mutating
def test_turning_dark_off_writes_both_keys_back(memory_settings):
    memory_settings.set(colors.GTK_THEME_KEY, "'adw-gtk3-dark'")
    ops = colors.dark_mode_ops(memory_settings, False, INSTALLED)
    assert ops[0] == SettingWrite(colors.COLOR_SCHEME_KEY, "'default'", component="colors")
    assert ops[1] == SettingWrite(colors.GTK_THEME_KEY, "'adw-gtk3'", component="colors")


@pytest.mark.mutating
def test_a_style_that_is_already_right_is_left_alone(memory_settings):
    """Nothing to change is not a reason to write the same value again."""
    memory_settings.set(colors.GTK_THEME_KEY, "'adw-gtk3-dark'")
    ops = colors.dark_mode_ops(memory_settings, True, INSTALLED)
    assert len(ops) == 1


@pytest.mark.mutating
def test_a_style_with_no_dark_version_installed_is_not_renamed(memory_settings):
    """Writing the name of a style that is not there breaks every older app."""
    memory_settings.set(colors.GTK_THEME_KEY, "'Some-Theme'")
    ops = colors.dark_mode_ops(memory_settings, True, {"Some-Theme"})
    assert ops == [
        SettingWrite(colors.COLOR_SCHEME_KEY, "'prefer-dark'", component="colors")
    ]


@pytest.mark.parametrize(
    ("stored", "expected"),
    [("'prefer-dark'", True), ("'default'", False), ("'prefer-light'", False), (None, False)],
)
def test_is_dark_reads_the_stored_value(stored, expected):
    assert colors.is_dark(stored) is expected


@pytest.mark.mutating
def test_the_light_and_dark_tiles_show_what_the_desktop_holds(tmp_path, memory_settings):
    memory_settings.set(colors.COLOR_SCHEME_KEY, "'prefer-dark'")
    window = make_window(tmp_path)
    with use_backend(memory_settings):
        chooser = colors._ModeChooser(window, memory_settings, common.PageShell(window, "colors"))
    assert chooser.dark.get_active() is True
    assert chooser.light.get_active() is False


# --------------------------------------------------------------------------
# the nine dots
# --------------------------------------------------------------------------


def test_there_are_exactly_the_nine_colours_gnome_offers():
    row = common.corpus_rows()["org.gnome.desktop.interface:accent-color"]
    offered = [common.unquote(choice.value) for choice in row.choices]
    assert [name for name, _label, _hex in colors.ACCENTS] == offered
    assert len(colors.ACCENTS) == 9


def test_every_dot_carries_the_colour_libadwaita_actually_paints():
    """research/gnome-domains.md §1.1, read out of the libadwaita binary."""
    expected = {
        "blue": "#3584e4",
        "teal": "#2190a4",
        "green": "#3a944a",
        "yellow": "#c88800",
        "orange": "#ed5b00",
        "red": "#e62d42",
        "pink": "#d56199",
        "purple": "#9141ac",
        "slate": "#6f8396",
    }
    assert {name: hex_value for name, _label, hex_value in colors.ACCENTS} == expected


def test_no_dot_is_labelled_with_a_word_nobody_uses_for_a_colour():
    labels = [label for _name, label, _hex in colors.ACCENTS]
    assert "Slate" not in labels
    assert "Grey" in labels


@pytest.mark.mutating
def test_picking_a_dot_writes_that_colour(tmp_path, memory_settings):
    window = make_window(tmp_path)
    row = common.corpus_rows()["org.gnome.desktop.interface:accent-color"]
    with use_backend(memory_settings):
        widget, _refresh = colors._accent_row(memory_settings, row)
    dots = [w for w in _walk(widget) if isinstance(w, Gtk.ToggleButton)]
    assert len(dots) == 9
    dots[5].set_active(True)  # red
    assert memory_settings.get("gsettings:org.gnome.desktop.interface accent-color") == "'red'"
    assert window.said == []


def _walk(widget: Gtk.Widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from _walk(child)
        child = child.get_next_sibling()


# --------------------------------------------------------------------------
# the page
# --------------------------------------------------------------------------


@pytest.mark.mutating
def test_the_page_shows_every_setting_it_was_made_responsible_for(
    tmp_path, memory_settings
):
    """The nothing-was-left-out promise, per page."""
    window = make_window(tmp_path)
    build_page(colors, window, memory_settings)
    for descriptor_id in common.surfaced_ids("colors"):
        assert descriptor_id in window.rows, f"{descriptor_id} was not rendered"


@pytest.mark.mutating
def test_the_page_shows_the_top_bar_style_too(tmp_path, memory_settings):
    """It has no coverage entry of its own — it belongs to an add-on — and is
    still the whole reason a person comes to this page."""
    window = make_window(tmp_path)
    build_page(colors, window, memory_settings)
    assert "org.gnome.shell.extensions.user-theme:name" in window.rows


@pytest.mark.mutating
def test_the_turn_it_on_banner_appears_while_the_add_on_is_off(tmp_path, memory_settings):
    window = make_window(tmp_path)
    page = build_page(colors, window, memory_settings)
    banners = [w for w in _walk(page) if isinstance(w, Adw.Banner)]
    titles = [b.get_title() for b in banners]
    assert colors.COPY["topbar-missing-addon"] in titles


@pytest.mark.mutating
def test_the_single_design_caveat_is_shown_word_for_word(tmp_path, memory_settings):
    """The descriptor's warning, on screen, not buried in a tooltip."""
    row = common.corpus_rows()["org.gnome.shell.extensions.user-theme:name"]
    window = make_window(tmp_path)
    page = build_page(colors, window, memory_settings)
    descriptions = [
        w.get_description()
        for w in _walk(page)
        if isinstance(w, Adw.PreferencesGroup)
    ]
    assert row.warn in descriptions


@pytest.mark.mutating
def test_the_rarely_wanted_setting_is_behind_the_expander(tmp_path, memory_settings):
    window = make_window(tmp_path)
    build_page(colors, window, memory_settings)
    entry = window.rows.lookup("org.gnome.desktop.interface:overlay-scrolling")
    assert entry is not None
    parent = entry.widget.get_parent()
    while parent is not None and not isinstance(parent, Adw.ExpanderRow):
        parent = parent.get_parent()
    assert isinstance(parent, Adw.ExpanderRow), "an advanced row must not sit on the main surface"


@pytest.mark.mutating
def test_every_row_is_findable_by_the_words_a_person_would_type(tmp_path, memory_settings):
    window = make_window(tmp_path)
    build_page(colors, window, memory_settings)
    assert window.rows.search("accent")  # the word they know
    assert window.rows.search("high contrast")


# -- regression: the confirmed review finding on this page ------------------


@pytest.mark.mutating
def test_the_light_and_dark_tiles_follow_a_change_they_did_not_make(
    tmp_path, memory_settings
):
    """Pins colors.py:263 — the mode tiles were wired to no refresh path.

    ``_ModeChooser`` registers no row and added nothing to the shell's notices,
    so neither ``Window.after_change`` (run after every Look apply and undo)
    nor the live-mirroring pass ever re-read it. Applying a dark Look, or
    flipping dark mode in the desktop's own Settings, left the Light tile
    selected on a dark desktop. Both paths end in ``run_notices``.
    """
    memory_settings.set(colors.COLOR_SCHEME_KEY, "'default'")
    window = make_window(tmp_path)
    with use_backend(memory_settings):
        shell = common.PageShell(window, "colors")
        chooser = colors._ModeChooser(window, memory_settings, shell)
    assert chooser.light.get_active() is True

    # something else changed it: a Look, or GNOME Settings
    memory_settings.set(colors.COLOR_SCHEME_KEY, "'prefer-dark'")
    shell.run_notices()

    assert chooser.dark.get_active() is True, "the tiles never re-read the desktop"
    assert chooser.light.get_active() is False


@pytest.mark.mutating
def test_the_built_page_puts_the_mode_tiles_on_a_refresh_path(tmp_path, memory_settings):
    """The whole page, not just a chooser built by hand.

    The window is the thing that runs the notices — ``after_change`` after a
    Look, ``_mirror_settled`` after an external change — so this checks the
    page really hands its shell over with the tiles' refresh on it.
    """
    shells = []
    window = make_window(tmp_path)
    window.register_page_shell = shells.append

    memory_settings.set(colors.COLOR_SCHEME_KEY, "'default'")
    build_page(colors, window, memory_settings)
    shell = next(s for s in shells if s.page_id == "colors")
    chooser = next(
        notice.__self__
        for notice in shell.notices
        if isinstance(getattr(notice, "__self__", None), colors._ModeChooser)
    )
    assert chooser.light.get_active() is True

    memory_settings.set(colors.COLOR_SCHEME_KEY, "'prefer-dark'")
    shell.run_notices()

    assert chooser.dark.get_active() is True
