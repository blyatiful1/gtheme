"""The base row library, driven against a memory backend.

Marked ``gtk`` because it constructs real libadwaita widgets. Nothing here
presents a window, so nothing appears on the developer's screen; and every
value goes to an in-memory settings backend, so nothing reaches a real store.
"""

from __future__ import annotations

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for the widget library")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from gtheme.core.settings_backend import MemoryBackend  # noqa: E402
from gtheme.panels.descriptor import Row, WidgetKind  # noqa: E402
from gtheme.ui.widgets.rows import (  # noqa: E402
    FOREIGN_CHOICE_SUFFIX,
    UnsupportedRowKind,
    build_row,
    key_for,
    warn_banner,
)

pytestmark = pytest.mark.gtk

SCHEMA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<schemalist>
  <schema id="io.github.blyatiful1.GthemeRowTest" path="/io/github/blyatiful1/gtheme-row-test/">
    <key name="a-flag" type="b"><default>false</default></key>
    <key name="a-name" type="s"><default>'Adwaita'</default></key>
    <key name="a-count" type="i"><default>3</default></key>
    <key name="a-mode" type="s"><default>'default'</default></key>
    <key name="needs-manual" type="s"><default>'automatic'</default></key>
    <key name="a-dict" type="a{sv}"><default>{'radius': &lt;8&gt;}</default></key>
    <key name="a-delay" type="u"><default>300</default></key>
  </schema>
</schemalist>
"""

ID = "io.github.blyatiful1.GthemeRowTest"


@pytest.fixture(autouse=True, scope="module")
def _adw():
    if not Gtk.init_check():
        pytest.skip("no display is available for GTK — run under gtk4-broadwayd")
    Adw.init()


@pytest.fixture
def backend(schema_source_factory):
    return MemoryBackend(schema_source=schema_source_factory(SCHEMA_XML))


def _row(**overrides) -> Row:
    base = {
        "schema_id": ID,
        "key": "a-flag",
        "title": "A flag",
        "subtitle": "Turns the thing on.",
        "kind": "toggle",
    }
    return Row.model_validate({**base, **overrides})


# -- key building ----------------------------------------------------------


def test_key_for_uses_the_plain_form_by_default():
    assert key_for(_row()) == f"gsettings:{ID} a-flag"


def test_key_for_uses_the_relocatable_form_when_there_is_a_path():
    row = _row(path="/org/a/b/1/")
    assert key_for(row) == f"gsettings-path:{ID}:/org/a/b/1/ a-flag"


# -- toggle ----------------------------------------------------------------


def test_toggle_shows_the_current_value(backend):
    widget, _ = build_row(backend, _row())
    assert isinstance(widget, Adw.SwitchRow)
    assert widget.get_active() is False

    backend.set(f"gsettings:{ID} a-flag", "true")
    widget2, _ = build_row(backend, _row())
    assert widget2.get_active() is True


def test_toggle_writes_when_flipped(backend):
    widget, _ = build_row(backend, _row())
    widget.set_active(True)
    assert backend.get(f"gsettings:{ID} a-flag") == "true"


def test_toggle_carries_title_and_subtitle(backend):
    widget, _ = build_row(backend, _row())
    assert widget.get_title() == "A flag"
    assert widget.get_subtitle() == "Turns the thing on."


def test_refresh_updates_without_writing_back(backend):
    widget, refresh = build_row(backend, _row())
    backend.set(f"gsettings:{ID} a-flag", "true")
    refresh()
    assert widget.get_active() is True
    assert backend.get(f"gsettings:{ID} a-flag") == "true"


# -- slider ----------------------------------------------------------------


def test_slider_reads_and_clamps(backend):
    row = _row(key="a-count", kind="slider", clamp_min=0, clamp_max=10, step=1)
    widget, _ = build_row(backend, row)
    assert isinstance(widget, Adw.SpinRow)
    assert widget.get_value() == pytest.approx(3)


def test_slider_writes_an_integer_not_a_float(backend):
    """An 'i' key rejects "5.0"; the row must not hand GVariant a float."""
    row = _row(key="a-count", kind="slider", clamp_min=0, clamp_max=10, step=1)
    widget, _ = build_row(backend, row)
    widget.set_value(5)
    assert backend.get(f"gsettings:{ID} a-count") == "5"


def test_slider_clamps_a_value_outside_its_range(backend):
    """GNOME's night-light keys are unbounded upstream; the app bounds them."""
    backend.set(f"gsettings:{ID} a-count", "9999")
    row = _row(key="a-count", kind="slider", clamp_min=0, clamp_max=10, step=1)
    widget, _ = build_row(backend, row)
    assert widget.get_value() <= 10


# -- choice ----------------------------------------------------------------


def _choice_row():
    return _row(
        key="a-mode",
        kind="choice",
        choices=[
            {"value": "'default'", "label": "Normal"},
            {"value": "'fancy'", "label": "Fancy"},
        ],
    )


def test_choice_selects_the_current_value(backend):
    widget, _ = build_row(backend, _choice_row())
    assert isinstance(widget, Adw.ComboRow)
    assert widget.get_selected() == 0


def test_choice_writes_the_selected_value(backend):
    widget, _ = build_row(backend, _choice_row())
    widget.set_selected(1)
    assert backend.get(f"gsettings:{ID} a-mode") == "'fancy'"


def test_a_value_outside_the_offered_set_is_shown_not_hidden(backend):
    """Someone else's value is real and must not be silently overwritten.

    ``Adw.ComboRow`` cannot show "nothing selected" — it clamps an invalid
    index to zero — so a foreign value is added to the list, labelled as
    coming from elsewhere, and selected. Anything else would display the wrong
    option and then write it.
    """
    backend.set(f"gsettings:{ID} a-mode", "'something-else'")
    widget, _ = build_row(backend, _choice_row())

    model = widget.get_model()
    assert model.get_n_items() == 3
    shown = model.get_string(widget.get_selected())
    assert shown == "something-else" + FOREIGN_CHOICE_SUFFIX
    assert backend.get(f"gsettings:{ID} a-mode") == "'something-else'"


def test_picking_a_real_option_retires_the_foreign_entry(backend):
    backend.set(f"gsettings:{ID} a-mode", "'something-else'")
    widget, _ = build_row(backend, _choice_row())
    assert widget.get_model().get_n_items() == 3

    widget.set_selected(1)
    assert backend.get(f"gsettings:{ID} a-mode") == "'fancy'"
    assert widget.get_model().get_n_items() == 2
    assert widget.get_selected() == 1


def test_a_foreign_value_does_not_pile_up_across_refreshes(backend):
    backend.set(f"gsettings:{ID} a-mode", "'something-else'")
    widget, refresh = build_row(backend, _choice_row())
    for _ in range(3):
        refresh()
    assert widget.get_model().get_n_items() == 3

    backend.set(f"gsettings:{ID} a-mode", "'another-one'")
    refresh()
    assert widget.get_model().get_n_items() == 3
    assert widget.get_model().get_string(widget.get_selected()).startswith("another-one")


# -- text and colour -------------------------------------------------------


def test_text_row_strips_variant_quoting_for_display(backend):
    widget, _ = build_row(backend, _row(key="a-name", kind="text"))
    assert isinstance(widget, Adw.EntryRow)
    assert widget.get_text() == "Adwaita"


def test_text_row_writes_quoted_variant_text(backend):
    widget, _ = build_row(backend, _row(key="a-name", kind="text"))
    widget.set_text("Yaru")
    widget.emit("apply")
    assert backend.get(f"gsettings:{ID} a-name") == "'Yaru'"


def test_colour_row_shows_the_stored_value(backend):
    widget, _ = build_row(backend, _row(key="a-name", kind="color"))
    assert isinstance(widget, Adw.ActionRow)


# -- requires_first --------------------------------------------------------


def test_requires_first_is_written_before_the_row_value(backend):
    """Font sharpness does nothing until rendering is set to manual."""
    row = _row(
        requires_first=[
            {
                "schema_id": ID,
                "key": "needs-manual",
                "value": "'manual'",
                "explain": "gtheme also stops the system choosing this for itself.",
            }
        ]
    )
    widget, _ = build_row(backend, row)
    widget.set_active(True)
    assert backend.get(f"gsettings:{ID} needs-manual") == "'manual'"
    assert backend.get(f"gsettings:{ID} a-flag") == "true"


# -- unavailable rows ------------------------------------------------------


def test_a_missing_schema_produces_an_honest_disabled_row(backend):
    row = _row(schema_id="io.github.blyatiful1.NotInstalled")
    widget, refresh = build_row(backend, row)
    assert widget.get_sensitive() is False
    assert "isn't installed" in widget.get_subtitle()
    refresh()  # must be callable and harmless


def test_a_missing_key_says_the_version_differs(backend):
    widget, _ = build_row(backend, _row(key="no-such-key"))
    assert widget.get_sensitive() is False
    assert "different version" in widget.get_subtitle()


# -- reset -----------------------------------------------------------------


def test_reset_button_is_insensitive_at_the_default(backend):
    widget, _ = build_row(backend, _row())
    button = _find_reset_button(widget)
    assert button is not None
    assert button.get_sensitive() is False


def test_reset_button_wakes_up_once_the_value_differs(backend):
    widget, refresh = build_row(backend, _row())
    widget.set_active(True)
    refresh()
    assert _find_reset_button(widget).get_sensitive() is True


def test_reset_button_puts_the_value_back(backend):
    widget, refresh = build_row(backend, _row())
    widget.set_active(True)
    _find_reset_button(widget).emit("clicked")
    assert backend.get(f"gsettings:{ID} a-flag") == "false"
    assert widget.get_active() is False


def test_a_row_can_opt_out_of_reset(backend):
    widget, _ = build_row(backend, _row(reset=False))
    assert _find_reset_button(widget) is None


def _find_reset_button(widget) -> Gtk.Button | None:
    stack = [widget]
    while stack:
        node = stack.pop()
        child = node.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.Button) and child.get_icon_name() == "edit-undo-symbolic":
                return child
            stack.append(child)
            child = child.get_next_sibling()
    return None


# -- warn banner and unsupported kinds -------------------------------------


def test_warn_banner_says_the_consequence():
    banner = warn_banner("This can stop screen recording from working.")
    assert isinstance(banner, Adw.Banner)
    assert banner.get_revealed() is True


def test_a_row_warning_becomes_a_tooltip(backend):
    widget, _ = build_row(backend, _row(warn="This can slow older computers down."))
    assert widget.get_tooltip_text() == "This can slow older computers down."


@pytest.mark.parametrize(("kind", "extra"), [("picker", {})])
def test_unbuilt_kinds_name_themselves(backend, kind, extra):
    """``picker`` is the last kind with no builder: its content comes from
    scanning the machine, not from reading a setting.

    ``dict_slider`` and ``shortcut`` used to be here. They are built now, by
    :mod:`gtheme.panels.widgets`, which hands them to this library through
    :func:`register_kind` — so this library builds them like anything else and
    they get the reset button they were missing.
    """
    with pytest.raises(UnsupportedRowKind) as caught:
        build_row(backend, _row(kind=kind, **extra))
    assert kind in str(caught.value)
    assert isinstance(caught.value, NotImplementedError)


def test_a_registered_kind_becomes_a_first_class_row(backend):
    """The point of the registry: a registered builder is not a second path."""
    from gtheme.panels.widgets import _build_dict_slider
    from gtheme.ui.widgets.rows import _BUILDERS, register_kind

    assert _BUILDERS[WidgetKind.DICT_SLIDER] is _build_dict_slider

    row = _row(
        key="a-dict",
        kind="dict_slider",
        dict_key="radius",
        clamp_min=0,
        clamp_max=32,
        reset=True,
    )
    widget, _refresh = build_row(backend, row)
    assert _find_reset_button(widget) is not None, (
        "a registered kind must get the reset button too"
    )

    # Registering the same builder twice is a no-op; a different one is a bug.
    register_kind(WidgetKind.DICT_SLIDER, _build_dict_slider)
    with pytest.raises(ValueError, match="already has a builder"):
        register_kind(WidgetKind.DICT_SLIDER, lambda _b, _r: (None, lambda: None))


# -- the type word GVariant prints in front of a number --------------------
#
# Twenty settings on a GNOME 50 desktop are uint32, and GLib prints one as
# "uint32 300". Both of these were live bugs on the System pages, and both had
# the same cause: a widget read that text as if it were a number. The fix is in
# the library rather than in a view wrapped around the backend, so a page that
# calls build_row directly gets it too -- which is what these two prove.


def _delay_key() -> str:
    return f"gsettings:{ID} a-delay"


def test_a_slider_shows_the_uint_value_it_actually_holds(backend):
    """It used to fall back to its own minimum, then write that on a nudge."""
    backend.set(_delay_key(), "900")
    assert backend.get(_delay_key()) == "uint32 900", "the premise of this test changed"

    row = _row(key="a-delay", kind="slider", clamp_min=60, clamp_max=3600, step=60)
    widget, _refresh = build_row(backend, row)
    assert widget.get_value() == 900


def test_a_pick_one_row_does_not_call_its_own_uint_value_foreign(backend):
    """The authored option is ``300``; the desktop reads back ``uint32 300``."""
    backend.set(_delay_key(), "300")
    row = _row(
        key="a-delay",
        kind="choice",
        choices=[
            {"value": "300", "label": "After 5 minutes"},
            {"value": "900", "label": "After 15 minutes"},
        ],
    )
    widget, _refresh = build_row(backend, row)

    model = widget.get_model()
    labels = [model.get_string(i) for i in range(model.get_n_items())]
    assert not any(FOREIGN_CHOICE_SUFFIX in label for label in labels), labels
    assert labels[widget.get_selected()] == "After 5 minutes"


def test_a_genuinely_foreign_uint_value_is_still_reported_as_foreign(backend):
    """Baring must not turn the honest "set somewhere else" row into a lie."""
    backend.set(_delay_key(), "1234")
    row = _row(
        key="a-delay",
        kind="choice",
        choices=[
            {"value": "300", "label": "After 5 minutes"},
            {"value": "900", "label": "After 15 minutes"},
        ],
    )
    widget, _refresh = build_row(backend, row)
    model = widget.get_model()
    shown = model.get_string(widget.get_selected())
    assert shown == "1234" + FOREIGN_CHOICE_SUFFIX
