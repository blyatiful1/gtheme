"""Fonts & Text: the weight suffix that must survive, and the two-key writes."""

from __future__ import annotations

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for the page library")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402
from test_pages_style_common import build_page, make_window  # noqa: E402

from gtheme.core.transaction import SettingWrite  # noqa: E402
from gtheme.ui import jargon  # noqa: E402
from gtheme.ui.pages import _style_common as common  # noqa: E402
from gtheme.ui.pages import fonts  # noqa: E402

pytestmark = pytest.mark.gtk

#: What this desktop actually holds, verified in research/competitor-ux.md §0.
LIVE_FONT = "Adwaita Sans 11 @wght=460"


def _walk(widget: Gtk.Widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from _walk(child)
        child = child.get_next_sibling()


# --------------------------------------------------------------------------
# the copy
# --------------------------------------------------------------------------


def test_every_sentence_this_page_says_is_plain_english():
    problems = jargon.check_all([(f"fonts.COPY[{k!r}]", v) for k, v in fonts.COPY.items()])
    assert problems == [], "\n".join(problems)


def test_the_page_never_writes_its_own_version_of_the_consent_sentence():
    """Those sentences come from the descriptor, word for word, or they drift."""
    for text in fonts.COPY.values():
        assert "gtheme also has to" not in text
        assert "gtheme also needs" not in text


# --------------------------------------------------------------------------
# the variable-weight suffix
# --------------------------------------------------------------------------


def test_picking_the_same_font_back_out_of_the_chooser_changes_nothing():
    """The round trip. A chooser that drops '@wght=460' silently reweights the desktop."""
    assert fonts.font_choice(LIVE_FONT, "Adwaita Sans 11") == LIVE_FONT


def test_changing_only_the_size_keeps_the_weight():
    assert fonts.font_choice(LIVE_FONT, "Adwaita Sans 13") == "Adwaita Sans 13 @wght=460"


def test_a_weight_the_chooser_did_hand_back_wins():
    assert (
        fonts.font_choice(LIVE_FONT, "Adwaita Sans 11 @wght=700")
        == "Adwaita Sans 11 @wght=700"
    )


def test_a_weight_is_not_carried_across_to_a_different_font():
    """A weight pinned for one family means nothing in another."""
    assert fonts.font_choice(LIVE_FONT, "Cantarell 11") == "Cantarell 11"


def test_a_font_with_no_weight_suffix_is_left_exactly_as_chosen():
    assert fonts.font_choice("Cantarell 11", "Cantarell 12") == "Cantarell 12"


def test_a_setting_that_could_not_be_read_does_not_invent_a_value():
    assert fonts.font_choice(None, "Cantarell 11") == "Cantarell 11"


# --------------------------------------------------------------------------
# the two-key writes
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stored", "expected"),
    [("'automatic'", True), ("'manual'", False), (None, False)],
)
def test_the_notice_appears_only_while_the_desktop_is_choosing_for_itself(stored, expected):
    assert fonts.needs_manual_rendering(stored) is expected


def test_the_window_heading_font_stops_the_headings_following_first():
    """Order matters: the second write does nothing until the first has landed."""
    ops = fonts.window_heading_font_ops("Cantarell 11")
    assert ops == [
        SettingWrite(fonts.TITLEBAR_USES_SYSTEM_FONT_KEY, "false", component="fonts"),
        SettingWrite(fonts.TITLEBAR_FONT_KEY, "'Cantarell 11'", component="fonts"),
    ]


# --------------------------------------------------------------------------
# the previews
# --------------------------------------------------------------------------


def test_a_preview_is_drawn_in_the_lettering_it_is_about():
    label = fonts.preview_label(LIVE_FONT)
    assert label.get_attributes() is not None


def test_a_preview_with_nothing_to_show_falls_back_rather_than_failing():
    assert fonts.preview_label(None).get_attributes() is None


# --------------------------------------------------------------------------
# the page
# --------------------------------------------------------------------------


@pytest.mark.mutating
def test_the_page_shows_every_setting_it_was_made_responsible_for(tmp_path, memory_settings):
    window = make_window(tmp_path)
    build_page(fonts, window, memory_settings)
    for descriptor_id in common.surfaced_ids("fonts"):
        assert descriptor_id in window.rows, f"{descriptor_id} was not rendered"


@pytest.mark.mutating
def test_the_consent_notice_is_the_descriptor_s_own_sentence(tmp_path, memory_settings):
    """Word for word: the page and the data cannot say two different things."""
    explain = common.corpus_rows()[
        "org.gnome.desktop.interface:font-hinting"
    ].requires_first[0].explain
    memory_settings.set(fonts.FONT_RENDERING_KEY, "'automatic'")
    window = make_window(tmp_path)
    page = build_page(fonts, window, memory_settings)
    banners = [w for w in _walk(page) if isinstance(w, Adw.Banner)]
    shown = [b.get_title() for b in banners if b.get_revealed()]
    assert explain in shown


@pytest.mark.mutating
def test_the_consent_notice_is_gone_once_it_no_longer_applies(tmp_path, memory_settings):
    memory_settings.set(fonts.FONT_RENDERING_KEY, "'manual'")
    window = make_window(tmp_path)
    page = build_page(fonts, window, memory_settings)
    explain = common.corpus_rows()[
        "org.gnome.desktop.interface:font-hinting"
    ].requires_first[0].explain
    revealed = [
        b.get_title() for b in _walk(page) if isinstance(b, Adw.Banner) and b.get_revealed()
    ]
    assert explain not in revealed


@pytest.mark.mutating
def test_the_rarely_wanted_settings_are_behind_the_expander(tmp_path, memory_settings):
    window = make_window(tmp_path)
    build_page(fonts, window, memory_settings)
    for descriptor_id in (
        "org.gnome.desktop.interface:font-rgba-order",
        "org.gnome.desktop.wm.preferences:titlebar-font",
    ):
        entry = window.rows.lookup(descriptor_id)
        assert entry is not None, descriptor_id
        parent = entry.widget.get_parent()
        while parent is not None and not isinstance(parent, Adw.ExpanderRow):
            parent = parent.get_parent()
        assert isinstance(parent, Adw.ExpanderRow), f"{descriptor_id} is on the main surface"


@pytest.mark.mutating
def test_the_words_a_person_would_type_find_the_right_rows(tmp_path, memory_settings):
    window = make_window(tmp_path)
    build_page(fonts, window, memory_settings)
    assert window.rows.search("make text bigger")
    assert window.rows.search("blurry text")
    assert window.rows.search("code font")


@pytest.mark.mutating
def test_the_text_size_row_is_bounded_the_way_the_descriptor_promises(
    tmp_path, memory_settings
):
    window = make_window(tmp_path)
    build_page(fonts, window, memory_settings)
    entry = window.rows.lookup("org.gnome.desktop.interface:text-scaling-factor")
    assert entry is not None
    adjustment = entry.widget.get_adjustment()
    assert (adjustment.get_lower(), adjustment.get_upper()) == (0.5, 3.0)
