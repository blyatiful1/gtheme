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


# -- link rows -------------------------------------------------------------


def _link_row() -> Row:
    return Row.model_validate(
        {
            "title": "Open the add-on's own settings",
            "subtitle": "The rest of the taskbar's settings open in the add-on's own window.",
            "kind": "link",
            "link_target": "extension-prefs:dash-to-panel@jderose9.github.com",
        }
    )


@pytest.mark.gtk
def test_a_link_row_is_a_row_with_an_arrow(rwc_backend: MemoryBackend):
    widget, refresh = build_row(rwc_backend, _link_row())
    assert isinstance(widget, Adw.ActionRow)
    assert widget.get_activatable()
    refresh()  # a link has no value to re-read; this must not blow up


@pytest.mark.gtk
def test_a_link_row_gets_no_reset_button(rwc_backend: MemoryBackend):
    """There is nothing to put back: the row does not hold a setting."""
    widget, _refresh = build_row(rwc_backend, _link_row())
    buttons = []
    child = widget.get_first_child()
    while child is not None:
        buttons.extend(_descend_for_buttons(child))
        child = child.get_next_sibling()
    assert not [b for b in buttons if b.get_icon_name() == "edit-undo-symbolic"]


def _descend_for_buttons(widget) -> list:
    found = []
    if isinstance(widget, Gtk.Button):
        found.append(widget)
    child = widget.get_first_child()
    while child is not None:
        found.extend(_descend_for_buttons(child))
        child = child.get_next_sibling()
    return found


@pytest.mark.gtk
def test_activating_a_link_row_hands_over_its_destination(rwc_backend: MemoryBackend):
    """Opening the destination is Wave 2's job; carrying it is this row's."""
    from gtheme.panels.widgets import set_link_handler

    row = _link_row()
    widget, _refresh = build_row(rwc_backend, row)
    widget.emit("activated")  # nothing wired yet: must be a no-op, not a crash

    seen: list[str | None] = []
    set_link_handler(widget, row, seen.append)
    widget.emit("activated")
    assert seen == ["extension-prefs:dash-to-panel@jderose9.github.com"]


@pytest.mark.gtk
def test_a_link_row_is_never_greyed_by_the_probe(corpus_probe: SchemaProbe):
    """It reads no setting, so no setting can be missing."""
    assert corpus_probe.availability(_link_row()).ok


# -- burn-my-windows: one picker instead of twenty-six switches -------------

BMW_UUID = "burn-my-windows@schneegans.github.com"
BMW_PROFILE = "org.gnome.shell.extensions.burn-my-windows-profile"
CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "schemas"


@pytest.fixture
def bmw_backend():
    """A memory backend over the committed burn-my-windows profile schema."""
    from gi.repository import Gio

    source = Gio.SettingsSchemaSource.new_from_directory(
        str(CORPUS / BMW_UUID / "schemas"), Gio.SettingsSchemaSource.get_default(), False
    )
    return MemoryBackend(schema_source=source)


@pytest.fixture
def bmw_panel(repo_root):
    from gtheme.panels.loader import load_panels

    panels, problems = load_panels(repo_root / "data" / "panels")
    assert problems == []
    return next(p for p in panels if p.id == "burn-my-windows")


def _effect_key(name: str) -> str:
    return f"gsettings:{BMW_PROFILE} {name}-enable-effect"


@pytest.mark.gtk
def test_the_effect_picker_offers_every_effect_the_add_on_has(bmw_backend, bmw_panel):
    from gtheme.panels.descriptor import WidgetKind

    row = next(r for r in bmw_panel.rows if r.kind is WidgetKind.EFFECT_PICKER)
    widget, _refresh = build_row(bmw_backend, row)
    assert isinstance(widget, Adw.ComboRow)
    model = widget.get_model()
    assert model.get_n_items() == 27, "26 effects in the corpus, plus 'Nothing'"
    assert model.get_string(0) == "Nothing"


@pytest.mark.gtk
def test_the_picker_shows_whichever_effect_is_switched_on(bmw_backend, bmw_panel):
    from gtheme.panels.descriptor import WidgetKind

    row = next(r for r in bmw_panel.rows if r.kind is WidgetKind.EFFECT_PICKER)
    bmw_backend.set(_effect_key("fire"), "false")
    bmw_backend.set(_effect_key("hexagon"), "true")
    widget, _refresh = build_row(bmw_backend, row)
    labels = widget.get_model()
    assert labels.get_string(widget.get_selected()) == "Dissolve into hexagons"


@pytest.mark.gtk
def test_choosing_an_effect_turns_every_other_one_off(bmw_backend, bmw_panel):
    """The whole point: one action, one effect on, the rest off."""
    from gtheme.panels.descriptor import WidgetKind

    row = next(r for r in bmw_panel.rows if r.kind is WidgetKind.EFFECT_PICKER)
    widget, _refresh = build_row(bmw_backend, row)

    labels = widget.get_model()
    target = next(
        i for i in range(labels.get_n_items()) if labels.get_string(i) == "Rain of green letters"
    )
    widget.set_selected(target)

    on = [
        choice.value
        for choice in row.choices
        if bmw_backend.get(f"gsettings:{BMW_PROFILE} {choice.value}").strip() == "true"
    ]
    assert on == ["matrix-enable-effect"]


@pytest.mark.gtk
def test_nothing_switched_on_shows_as_nothing_chosen(bmw_backend, bmw_panel):
    """With every effect off the add-on plays nothing, and the row says so.

    Adw.ComboRow has no empty selection: without a "Nothing" option it would
    fall back to showing the first effect as though it were in use.
    """
    from gtheme.panels.descriptor import WidgetKind

    row = next(r for r in bmw_panel.rows if r.kind is WidgetKind.EFFECT_PICKER)
    bmw_backend.set(_effect_key("fire"), "false")
    widget, _refresh = build_row(bmw_backend, row)
    assert widget.get_model().get_string(widget.get_selected()) == "Nothing"


@pytest.mark.gtk
def test_choosing_nothing_turns_every_effect_off(bmw_backend, bmw_panel):
    from gtheme.panels.descriptor import WidgetKind

    row = next(r for r in bmw_panel.rows if r.kind is WidgetKind.EFFECT_PICKER)
    widget, _refresh = build_row(bmw_backend, row)
    widget.set_selected(0)
    assert not [
        choice.value
        for choice in row.choices
        if bmw_backend.get(f"gsettings:{BMW_PROFILE} {choice.value}").strip() == "true"
    ]


@pytest.mark.gtk
def test_the_speed_row_follows_the_chosen_effect(bmw_backend, bmw_panel):
    """One speed control, not twenty-six of which twenty-five do nothing."""
    from gtheme.panels.descriptor import WidgetKind

    row = next(r for r in bmw_panel.rows if r.kind is WidgetKind.EFFECT_SPEED)
    bmw_backend.set(_effect_key("fire"), "false")
    bmw_backend.set(_effect_key("tv"), "true")
    bmw_backend.set(f"gsettings:{BMW_PROFILE} tv-animation-time", "1500")

    widget, refresh = build_row(bmw_backend, row)
    assert widget.get_sensitive()
    assert widget.get_value() == 1500

    widget.set_value(900)
    assert bmw_backend.get(f"gsettings:{BMW_PROFILE} tv-animation-time") == "900"
    # ... and the fire duration was not touched.
    assert bmw_backend.get(f"gsettings:{BMW_PROFILE} fire-animation-time") != "900"

    # Switch effect; the same row now addresses the other duration.
    bmw_backend.set(_effect_key("tv"), "false")
    bmw_backend.set(_effect_key("matrix"), "true")
    bmw_backend.set(f"gsettings:{BMW_PROFILE} matrix-animation-time", "2000")
    refresh()
    assert widget.get_value() == 2000


@pytest.mark.gtk
def test_the_speed_row_greys_when_no_effect_is_chosen(bmw_backend, bmw_panel):
    from gtheme.panels.descriptor import WidgetKind

    row = next(r for r in bmw_panel.rows if r.kind is WidgetKind.EFFECT_SPEED)
    bmw_backend.set(_effect_key("fire"), "false")
    widget, _refresh = build_row(bmw_backend, row)
    assert not widget.get_sensitive()


@pytest.mark.gtk
@pytest.mark.mutating
def test_the_picker_writes_into_the_add_ons_own_file(bmw_panel, tmp_path, tmp_dest_root):
    """End to end: the picker, through the keyfile form, into a real file.

    The builder is called directly rather than through ``panels.build_row``.
    That entry point resolves the row against the LIVE ``active-profile``
    setting, which on a real desktop names a real profile — going through it
    here writes into the machine's own burn-my-windows configuration. (It did,
    once, while this was being written. Hence :func:`resolve_row` leaving an
    already-addressed row alone, and hence this note.)
    """
    from gi.repository import Gio

    from gtheme.core.settings_backend import GioBackend
    from gtheme.panels.descriptor import WidgetKind
    from gtheme.panels.widgets import build_effect_picker

    source = Gio.SettingsSchemaSource.new_from_directory(
        str(CORPUS / BMW_UUID / "schemas"), Gio.SettingsSchemaSource.get_default(), False
    )
    backend = GioBackend(schema_source=source)
    profile = tmp_path / "1787167433969725.conf"
    row = next(r for r in bmw_panel.rows if r.kind is WidgetKind.EFFECT_PICKER)
    resolved = row.model_copy(
        update={"keyfile": str(profile), "path": "/org/gnome/shell/extensions/"}
    )
    widget, _refresh = build_effect_picker(backend, resolved)

    labels = widget.get_model()
    target = next(
        i for i in range(labels.get_n_items()) if labels.get_string(i) == "Shatter like glass"
    )
    widget.set_selected(target)

    written = profile.read_text(encoding="utf-8")
    assert "[burn-my-windows-profile]" in written
    assert "broken-glass-enable-effect=true" in written
    assert "fire-enable-effect=false" in written


@pytest.mark.gtk
def test_an_already_addressed_row_is_never_redirected(bmw_backend, tmp_path):
    """The guard that stops a test writing into the real desktop.

    ``resolve_row`` points a burn-my-windows row at whichever profile file the
    machine is using. A row that already names a file must be left alone, or an
    explicit address silently becomes the live one.
    """
    from gtheme.panels.schema_probe import resolve_row

    row = Row.model_validate(
        {
            "schema_id": BMW_PROFILE,
            "key": "fire-enable-effect",
            "title": "Burn away",
            "subtitle": "The window goes up in flames when it closes.",
            "kind": "toggle",
            "keyfile": str(tmp_path / "explicit.conf"),
            "path": "/org/gnome/shell/extensions/",
        }
    )
    assert resolve_row(row, bmw_backend) is row
