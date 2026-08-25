"""The three hard row kinds, driven against real settings and a memory store.

Marked ``gtk`` where a widget is constructed. Nothing is ever presented, so
nothing appears on the screen of whoever runs this, and every value goes to an
in-memory settings backend, so nothing reaches the real desktop.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for the widget library")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from gtheme.core.settings_backend import MemoryBackend  # noqa: E402
from gtheme.panels.descriptor import Row  # noqa: E402
from gtheme.panels.schema_probe import Presence, SchemaProbe  # noqa: E402
from gtheme.panels.widgets import (  # noqa: E402
    KNOWN_CLAMPS,
    Capture,
    CaptureAction,
    Clamp,
    build_row,
    capture_for_key,
    clamp_violations,
    decode_accelerator,
    dict_number,
    dict_with_number,
    encode_accelerator,
)
from gtheme.ui.widgets.rows import key_for  # noqa: E402

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "schemas"
RWC = "org.gnome.shell.extensions.rounded-window-corners-reborn"
RADIUS = "global-rounded-corner-settings"


@pytest.fixture(scope="module")
def corpus_probe() -> SchemaProbe:
    return SchemaProbe([CORPUS], include_default=False)


@pytest.fixture
def rwc_backend(corpus_probe: SchemaProbe) -> MemoryBackend:
    """A real rounded-window-corners schema over a store that goes nowhere."""
    return MemoryBackend(schema_source=corpus_probe.source_for(RWC))


def _row(**overrides) -> Row:
    base = {
        "schema_id": RWC,
        "key": RADIUS,
        "title": "Corner roundness",
        "subtitle": "How rounded the corners of every window are.",
        "kind": "dict_slider",
        "dict_key": "borderRadius",
        "clamp_min": 0,
        "clamp_max": 32,
    }
    return Row.model_validate({**base, **overrides})


# -- the dictionary, without any widget at all -----------------------------


def test_a_number_is_found_inside_the_dictionary(rwc_backend: MemoryBackend):
    value, type_string = dict_number(rwc_backend.get(key_for(_row())), "borderRadius")
    assert (value, type_string) == (15.0, "u")


def test_replacing_a_number_keeps_its_type_and_everything_else(rwc_backend: MemoryBackend):
    """The corner radius is one entry among padding, shadow colour and flags."""
    before = rwc_backend.get(key_for(_row()))
    after = dict_with_number(before, "borderRadius", 8)

    assert dict_number(after, "borderRadius") == (8.0, "u")
    assert "uint32 8" in after
    for survivor in ("padding", "keepRoundedCorners", "borderColor", "smoothing", "enabled"):
        assert survivor in after
    assert "0.5, 0.5, 0.5, 1.0" in after


def test_a_double_inside_the_dictionary_stays_a_double(rwc_backend: MemoryBackend):
    text = "{'radius': <uint32 4>, 'strength': <0.25>}"
    assert dict_number(text, "strength") == (0.25, "d")
    assert dict_number(dict_with_number(text, "strength", 0.75), "strength") == (0.75, "d")


def test_an_entry_that_is_not_there_is_an_error(rwc_backend: MemoryBackend):
    with pytest.raises(KeyError):
        dict_number(rwc_backend.get(key_for(_row())), "notAnEntry")


def test_an_entry_that_is_not_a_number_is_an_error(rwc_backend: MemoryBackend):
    from gtheme.ui.widgets.rows import RowBuildError

    with pytest.raises(RowBuildError):
        dict_number("{'on': <true>}", "on")


# -- clamps ----------------------------------------------------------------


def test_the_night_light_keys_are_bounded_by_the_app():
    """GNOME's own settings accept a start hour of 40 and a temperature of 12."""
    assert set(KNOWN_CLAMPS) == {
        "org.gnome.settings-daemon.plugins.color:night-light-schedule-from",
        "org.gnome.settings-daemon.plugins.color:night-light-schedule-to",
        "org.gnome.settings-daemon.plugins.color:night-light-temperature",
    }


def test_a_descriptor_that_forgets_the_bounds_is_caught():
    unbounded = Row.model_validate(
        {
            "schema_id": "org.gnome.settings-daemon.plugins.color",
            "key": "night-light-temperature",
            "title": "Warmth",
            "subtitle": "How warm the screen looks at night.",
            "kind": "choice",
            "choices": [{"value": "3000", "label": "Warm"}],
        }
    )
    assert clamp_violations([unbounded]) != []


def test_bounds_wider_than_the_promise_are_caught():
    too_wide = Row.model_validate(
        {
            "schema_id": "org.gnome.settings-daemon.plugins.color",
            "key": "night-light-temperature",
            "title": "Warmth",
            "subtitle": "How warm the screen looks at night.",
            "kind": "slider",
            "clamp_min": 1000,
            "clamp_max": 10000,
        }
    )
    assert clamp_violations([too_wide]) != []


def test_bounds_inside_the_promise_are_accepted():
    good = Row.model_validate(
        {
            "schema_id": "org.gnome.settings-daemon.plugins.color",
            "key": "night-light-schedule-from",
            "title": "Starts at",
            "subtitle": "When the screen starts getting warmer.",
            "kind": "slider",
            "clamp_min": 0,
            "clamp_max": 23.75,
            "step": 0.25,
        }
    )
    assert clamp_violations([good]) == []


def test_midnight_is_not_twenty_four_o_clock():
    """The hours run up to but never reach 24: 24:00 is 0:00 the next day."""
    hours = KNOWN_CLAMPS["org.gnome.settings-daemon.plugins.color:night-light-schedule-from"]
    assert hours.exclusive_maximum
    assert not hours.accepts(0.0, 24.0)
    assert hours.accepts(0.0, 23.75)


def test_a_clamp_pulls_a_value_into_range():
    assert Clamp(1700, 4700).clamp(12) == 1700
    assert Clamp(1700, 4700).clamp(99999) == 4700


# -- shortcut capture, without any widget ----------------------------------


def test_a_modifier_on_its_own_is_not_an_answer():
    assert capture_for_key(Gdk.KEY_Control_L, Gdk.ModifierType(0)) == Capture(CaptureAction.IGNORE)


def test_escape_leaves_the_shortcut_alone():
    assert capture_for_key(Gdk.KEY_Escape, Gdk.ModifierType(0)).action is CaptureAction.CANCEL


def test_backspace_removes_the_shortcut():
    assert capture_for_key(Gdk.KEY_BackSpace, Gdk.ModifierType(0)).action is CaptureAction.CLEAR


def test_a_real_combination_is_accepted():
    result = capture_for_key(Gdk.KEY_v, Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SUPER_MASK)
    assert result.action is CaptureAction.ACCEPT
    assert "v" in result.accelerator
    parsed = Gtk.accelerator_parse(result.accelerator)
    keyval, mods = parsed[-2], parsed[-1]
    assert keyval == Gdk.KEY_v
    assert mods & Gdk.ModifierType.CONTROL_MASK
    assert mods & Gdk.ModifierType.SUPER_MASK


def test_a_shortcut_is_stored_the_way_the_setting_holds_it():
    """GNOME's window shortcuts hold a list; add-ons usually hold one string."""
    assert encode_accelerator("as", "<Control>v") == "['<Control>v']"
    assert encode_accelerator("s", "<Control>v") == "'<Control>v'"
    assert encode_accelerator("as", "") == "@as []"
    assert encode_accelerator("s", "") == "''"


def test_a_stored_shortcut_reads_back():
    for text in ("['<Control>v']", "'<Control>v'"):
        assert decode_accelerator(text) == "<Control>v"
    for empty in ("@as []", "''", "[]"):
        assert decode_accelerator(empty) == ""


# -- the widgets -----------------------------------------------------------


@pytest.fixture(autouse=True, scope="module")
def _adw():
    if not Gtk.init_check():
        pytest.skip("no display is available for GTK — run under gtk4-broadwayd")
    Adw.init()


SHORTCUT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<schemalist>
  <schema id="io.github.blyatiful1.GthemeShortcutTest"
          path="/io/github/blyatiful1/gtheme-shortcut-test/">
    <key name="open-thing" type="as"><default>['&lt;Super&gt;k']</default></key>
    <key name="one-thing" type="s"><default>'&lt;Super&gt;j'</default></key>
  </schema>
</schemalist>
"""


@pytest.mark.gtk
def test_a_dictionary_slider_shows_the_number_from_inside_the_dictionary(
    rwc_backend: MemoryBackend,
):
    widget, _refresh = build_row(rwc_backend, _row())
    assert isinstance(widget, Adw.SpinRow)
    assert widget.get_value() == 15


@pytest.mark.gtk
def test_moving_a_dictionary_slider_rewrites_only_that_entry(rwc_backend: MemoryBackend):
    row = _row()
    widget, _refresh = build_row(rwc_backend, row)
    widget.set_value(6)
    while GLib.MainContext.default().pending():
        GLib.MainContext.default().iteration(False)

    stored = rwc_backend.get(key_for(row))
    assert dict_number(stored, "borderRadius") == (6.0, "u")
    assert "'enabled': <true>" in stored
    assert "0.5, 0.5, 0.5, 1.0" in stored


@pytest.mark.gtk
def test_a_dictionary_slider_without_bounds_is_refused(rwc_backend: MemoryBackend):
    from gtheme.ui.widgets.rows import RowBuildError

    row = Row.model_validate(
        {
            "schema_id": RWC,
            "key": RADIUS,
            "title": "Corner roundness",
            "subtitle": "How rounded the corners of every window are.",
            "kind": "dict_slider",
            "dict_key": "borderRadius",
        }
    )
    with pytest.raises(RowBuildError):
        build_row(rwc_backend, row)


@pytest.mark.gtk
def test_a_missing_dictionary_entry_greys_the_row_instead_of_crashing(
    rwc_backend: MemoryBackend,
):
    widget, _refresh = build_row(rwc_backend, _row(dict_key="notAnEntry"))
    assert widget.get_sensitive() is False


@pytest.mark.gtk
def test_a_shortcut_row_shows_what_is_stored(schema_source_factory):
    backend = MemoryBackend(schema_source=schema_source_factory(SHORTCUT_XML))
    row = Row.model_validate(
        {
            "schema_id": "io.github.blyatiful1.GthemeShortcutTest",
            "key": "open-thing",
            "title": "Open the thing",
            "subtitle": "The keys you press to open it.",
            "kind": "shortcut",
        }
    )
    widget, _refresh = build_row(backend, row)
    assert isinstance(widget, Adw.ActionRow)
    label = widget.get_activatable_widget().get_child()
    assert isinstance(label, Adw.ShortcutLabel)
    assert label.get_accelerator() == "<Super>k"


@pytest.mark.gtk
def test_a_captured_shortcut_is_written_in_the_shape_the_setting_wants(schema_source_factory):
    backend = MemoryBackend(schema_source=schema_source_factory(SHORTCUT_XML))
    for key, expected in (("open-thing", "['<Control>y']"), ("one-thing", "'<Control>y'")):
        row = Row.model_validate(
            {
                "schema_id": "io.github.blyatiful1.GthemeShortcutTest",
                "key": key,
                "title": "Open the thing",
                "subtitle": "The keys you press to open it.",
                "kind": "shortcut",
            }
        )
        widget, _refresh = build_row(backend, row)
        capture = capture_for_key(Gdk.KEY_y, Gdk.ModifierType.CONTROL_MASK)
        assert capture.action is CaptureAction.ACCEPT
        backend.set(key_for(row), encode_accelerator("as" if key == "open-thing" else "s", capture.accelerator))
        assert backend.get(key_for(row)) == expected


@pytest.mark.gtk
def test_an_unavailable_setting_becomes_a_row_that_says_why(
    corpus_probe: SchemaProbe, rwc_backend: MemoryBackend
):
    row = Row.model_validate(
        {
            "schema_id": "org.gnome.shell.extensions.not-installed",
            "key": "a-flag",
            "title": "Something",
            "subtitle": "From an add-on you don't have.",
            "kind": "toggle",
        }
    )
    assert corpus_probe.availability(row).presence is Presence.MISSING_ADDON
    widget, refresh = build_row(rwc_backend, row, probe=corpus_probe)
    assert widget.get_sensitive() is False
    assert "isn't installed" in widget.get_subtitle()
    refresh()  # a greyed row still has a refresh that does nothing


@pytest.mark.gtk
def test_the_ordinary_kinds_still_come_from_the_frozen_library(schema_source_factory):
    backend = MemoryBackend(schema_source=schema_source_factory(SHORTCUT_XML))
    row = Row.model_validate(
        {
            "schema_id": "io.github.blyatiful1.GthemeShortcutTest",
            "key": "one-thing",
            "title": "A name",
            "subtitle": "Some text you can type.",
            "kind": "text",
        }
    )
    widget, _refresh = build_row(backend, row)
    assert isinstance(widget, Adw.EntryRow)


@pytest.mark.gtk
def test_a_picker_is_still_an_honest_gap(rwc_backend: MemoryBackend):
    """Pickers show what is installed, which is the enumeration modules' job."""
    from gtheme.ui.widgets.rows import UnsupportedRowKind

    row = Row.model_validate(
        {
            "schema_id": "org.gnome.desktop.interface",
            "key": "icon-theme",
            "title": "Icons",
            "subtitle": "The pictures used for apps and files.",
            "kind": "picker",
        }
    )
    with pytest.raises(UnsupportedRowKind):
        build_row(rwc_backend, row)
