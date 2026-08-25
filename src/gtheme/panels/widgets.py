"""The row kinds the base library deliberately left unbuilt.

``gtheme.ui.widgets.rows`` is frozen and builds the four ordinary kinds. Three
kinds in the descriptor format are harder than a switch and a spin button, and
this module is where they land:

* **``dict_slider``** — rounded-window-corners keeps the corner radius *inside*
  an ``a{sv}`` dictionary, next to padding, shadow colour and two booleans.
  Writing the radius means unpacking the dictionary, replacing one entry
  **with a value of the same type it already had**, and writing the whole
  dictionary back. Getting the type wrong there does not fail loudly; it
  replaces the user's entire corner configuration with a differently-shaped
  one.
* **``shortcut``** — a key combination has to be *captured*, not typed. The
  capture is a small dialog with a key controller; everything else in this
  module is pure enough to test without one.
* **``picker``** — still unbuilt here on purpose. A picker's content comes from
  scanning the system (themes, cursors, fonts, sound themes), which belongs to
  the enumeration modules, so it stays a base-library gap rather than a
  half-answer here.

The entry point is :func:`build_row`, which is the frozen builder plus these.
Pages call this one and get every kind.

**Clamps.** Several GNOME keys have no bounds in their own settings: the night
light times and the colour temperature will accept a start hour of 40 and a
temperature of 12. The descriptor is what bounds them, and :data:`KNOWN_CLAMPS`
records the bounds the app promises so a test can catch a descriptor that
forgot them or widened them.
"""

from __future__ import annotations

import enum
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from ..core.settings_backend import BackendError, SettingsBackend  # noqa: E402
from ..ui.widgets.rows import RowBuildError, key_for  # noqa: E402
from ..ui.widgets.rows import build_row as build_base_row  # noqa: E402
from .descriptor import Row, WidgetKind  # noqa: E402
from .schema_probe import Availability, SchemaProbe  # noqa: E402

__all__ = [
    "CLEARED",
    "Capture",
    "CaptureAction",
    "Clamp",
    "KNOWN_CLAMPS",
    "build_row",
    "capture_for_key",
    "clamp_violations",
    "decode_accelerator",
    "dict_number",
    "dict_with_number",
    "encode_accelerator",
    "unavailable_row",
]


# --------------------------------------------------------------------------
# clamps
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Clamp:
    """Bounds the app imposes on a key whose own settings impose none."""

    minimum: float
    maximum: float
    #: True when the top of the range is the value just below :attr:`maximum`.
    #: The night light hours run to 24, and 24:00 is not a time — it is 0:00
    #: the next day.
    exclusive_maximum: bool = False

    def accepts(self, minimum: float | None, maximum: float | None) -> bool:
        """Whether a descriptor's own clamps are inside these bounds."""
        if minimum is None or maximum is None:
            return False
        if minimum < self.minimum:
            return False
        return maximum < self.maximum if self.exclusive_maximum else maximum <= self.maximum

    def clamp(self, value: float) -> float:
        return min(max(value, self.minimum), self.maximum)


#: Bounds for the keys the research found unbounded upstream, by descriptor id.
KNOWN_CLAMPS: dict[str, Clamp] = {
    "org.gnome.settings-daemon.plugins.color:night-light-schedule-from": Clamp(
        0.0, 24.0, exclusive_maximum=True
    ),
    "org.gnome.settings-daemon.plugins.color:night-light-schedule-to": Clamp(
        0.0, 24.0, exclusive_maximum=True
    ),
    "org.gnome.settings-daemon.plugins.color:night-light-temperature": Clamp(1700.0, 4700.0),
}


def clamp_violations(rows: Iterable[Row]) -> list[str]:
    """Descriptors that took an unbounded key without bounding it properly.

    Returns one sentence per offending row, empty when everything is in order.
    Used by the descriptor tests: an unbounded key reaching the user is a
    control that can put the desktop into a state GNOME's own Settings cannot
    produce and the user cannot undo by hand.
    """
    problems: list[str] = []
    for row in rows:
        expected = KNOWN_CLAMPS.get(row.id)
        if expected is None:
            continue
        if row.kind is not WidgetKind.SLIDER:
            problems.append(f"{row.id}: is unbounded upstream and must be a slider with bounds")
            continue
        if not expected.accepts(row.clamp_min, row.clamp_max):
            top = "below" if expected.exclusive_maximum else "at most"
            problems.append(
                f"{row.id}: bounds ({row.clamp_min}, {row.clamp_max}) are outside the "
                f"promised range {expected.minimum} to {top} {expected.maximum}"
            )
    return problems


# --------------------------------------------------------------------------
# a{sv} dictionaries
# --------------------------------------------------------------------------

_DICT_TYPE = "a{sv}"


def _parse_dict(text: str) -> Any:
    try:
        return GLib.Variant.parse(GLib.VariantType(_DICT_TYPE), text, None, None)
    except GLib.Error as exc:
        raise RowBuildError(f"not a settings dictionary: {text!r} ({exc})") from exc


def dict_number(text: str, dict_key: str) -> tuple[float, str]:
    """``(number, type)`` of one entry of an ``a{sv}`` value.

    The type string comes back so the write can put a value of the *same* type
    into the same slot. rounded-window-corners stores its radius as a ``uint32``
    and its smoothing as a double, in the same dictionary.

    Raises:
        KeyError: the dictionary has no such entry.
        RowBuildError: the value is not a number.
    """
    variant = _parse_dict(text)
    inner = variant.lookup_value(dict_key, None)
    if inner is None:
        raise KeyError(dict_key)
    value = inner.unpack()
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RowBuildError(f"{dict_key!r} is not a number")
    return float(value), inner.get_type_string()


def dict_with_number(text: str, dict_key: str, number: float) -> str:
    """The same dictionary with one number replaced. Everything else survives.

    The replacement keeps the entry's original type, and every other entry is
    carried across untouched — including the nested dictionaries and the colour
    array that the corner-radius panel never shows.
    """
    variant = _parse_dict(text)
    current = variant.lookup_value(dict_key, None)
    if current is None:
        raise KeyError(dict_key)
    type_string = current.get_type_string()
    if type_string in ("d",):
        replacement = GLib.Variant(type_string, float(number))
    else:
        replacement = GLib.Variant(type_string, int(round(number)))

    entries: dict[str, Any] = {}
    for index in range(variant.n_children()):
        entry = variant.get_child_value(index)
        name = entry.get_child_value(0).get_string()
        entries[name] = entry.get_child_value(1).get_variant()
    entries[dict_key] = replacement
    return GLib.Variant(_DICT_TYPE, entries).print_(True)


# --------------------------------------------------------------------------
# key capture
# --------------------------------------------------------------------------


class CaptureAction(enum.StrEnum):
    """What one key press during a shortcut capture means."""

    #: A modifier on its own, or a combination that is not usable. Keep waiting.
    IGNORE = "ignore"
    #: Escape. Leave the shortcut as it was.
    CANCEL = "cancel"
    #: Backspace or Delete. Remove the shortcut.
    CLEAR = "clear"
    #: A real combination.
    ACCEPT = "accept"


#: The value that means "no shortcut". Written as an empty list or an empty
#: string depending on what the setting holds.
CLEARED = ""


@dataclass(frozen=True)
class Capture:
    """The result of one key press during a capture."""

    action: CaptureAction
    accelerator: str = CLEARED


_MODIFIER_KEYVALS = frozenset(
    {
        Gdk.KEY_Shift_L,
        Gdk.KEY_Shift_R,
        Gdk.KEY_Control_L,
        Gdk.KEY_Control_R,
        Gdk.KEY_Alt_L,
        Gdk.KEY_Alt_R,
        Gdk.KEY_Super_L,
        Gdk.KEY_Super_R,
        Gdk.KEY_Meta_L,
        Gdk.KEY_Meta_R,
        Gdk.KEY_Hyper_L,
        Gdk.KEY_Hyper_R,
        Gdk.KEY_ISO_Level3_Shift,
        Gdk.KEY_Caps_Lock,
        Gdk.KEY_Num_Lock,
    }
)


def capture_for_key(keyval: int, state: Gdk.ModifierType) -> Capture:
    """Turn one key press into a decision. Pure — no widget involved.

    Escape backs out, Backspace and Delete clear, a modifier held on its own is
    not an answer yet, and anything else becomes a combination if the toolkit
    considers it usable.
    """
    mask = state & Gtk.accelerator_get_default_mod_mask()
    if keyval in _MODIFIER_KEYVALS:
        return Capture(CaptureAction.IGNORE)
    if keyval == Gdk.KEY_Escape and not mask:
        return Capture(CaptureAction.CANCEL)
    if keyval in (Gdk.KEY_BackSpace, Gdk.KEY_Delete) and not mask:
        return Capture(CaptureAction.CLEAR)
    if not Gtk.accelerator_valid(keyval, mask):
        return Capture(CaptureAction.IGNORE)
    return Capture(CaptureAction.ACCEPT, Gtk.accelerator_name(keyval, mask))


def encode_accelerator(type_string: str, accelerator: str) -> str:
    """The stored value for a captured combination.

    GNOME's own window shortcuts hold a *list* of combinations; most add-ons
    hold a single string. Both are written here, and an empty accelerator
    becomes an empty list or an empty string, never a missing key.
    """
    if type_string == "as":
        return GLib.Variant("as", [accelerator] if accelerator else []).print_(True)
    if type_string == "s":
        return GLib.Variant("s", accelerator).print_(True)
    raise RowBuildError(f"a shortcut cannot be stored as {type_string!r}")


def decode_accelerator(text: str) -> str:
    """The combination in a stored value, or ``""`` when there is none."""
    stripped = text.strip()
    if stripped in ("@as []", "[]", "''", '""'):
        return CLEARED
    try:
        variant = GLib.Variant.parse(None, stripped, None, None)
    except GLib.Error:
        return CLEARED
    unpacked = variant.unpack()
    if isinstance(unpacked, str):
        return unpacked
    if isinstance(unpacked, (list, tuple)):
        return str(unpacked[0]) if unpacked else CLEARED
    return CLEARED


# --------------------------------------------------------------------------
# rows
# --------------------------------------------------------------------------


def unavailable_row(row: Row, availability: Availability) -> Adw.ActionRow:
    """The honest greyed row: present, insensitive, and it says why."""
    widget = Adw.ActionRow(title=row.title, subtitle=availability.reason, sensitive=False)
    widget.add_suffix(Gtk.Image(icon_name="action-unavailable-symbolic"))
    return widget


def _value_type(backend: SettingsBackend, row: Row) -> str | None:
    """The type a key holds, or None when it cannot be looked up."""
    try:
        from gi.repository import Gio

        source = backend.schema_source or Gio.SettingsSchemaSource.get_default()
        schema = source.lookup(row.schema_id, True) if source else None
        if schema is None or not schema.has_key(row.key):
            return None
        return schema.get_key(row.key).get_value_type().dup_string()
    except Exception:  # pragma: no cover - defensive
        return None


def _build_dict_slider(
    backend: SettingsBackend, row: Row
) -> tuple[Adw.PreferencesRow, Callable[[], None]]:
    if row.clamp_min is None or row.clamp_max is None:
        raise RowBuildError(
            f"{row.id}: a number inside a dictionary still needs clamp_min and clamp_max"
        )
    step = row.step or 1
    widget = Adw.SpinRow.new_with_range(row.clamp_min, row.clamp_max, step)
    widget.set_title(row.title)
    widget.set_subtitle(row.subtitle)
    guard = {"busy": False}

    def refresh() -> None:
        guard["busy"] = True
        try:
            try:
                number, _type = dict_number(backend.get(key_for(row)), row.dict_key or "")
            except (KeyError, RowBuildError):
                widget.set_sensitive(False)
                return
            widget.set_sensitive(True)
            widget.set_value(min(max(number, row.clamp_min), row.clamp_max))
        finally:
            guard["busy"] = False

    def on_changed(*_args: Any) -> None:
        if guard["busy"]:
            return
        value = min(max(widget.get_value(), row.clamp_min), row.clamp_max)
        key = key_for(row)
        try:
            updated = dict_with_number(backend.get(key), row.dict_key or "", value)
        except (KeyError, RowBuildError, BackendError):
            return
        backend.set(key, updated)

    refresh()
    widget.connect("notify::value", on_changed)
    return widget, refresh


def _build_shortcut(
    backend: SettingsBackend, row: Row
) -> tuple[Adw.PreferencesRow, Callable[[], None]]:
    widget = Adw.ActionRow(title=row.title, subtitle=row.subtitle)
    label = Adw.ShortcutLabel(disabled_text="Not set", valign=Gtk.Align.CENTER)
    button = Gtk.Button(child=label, css_classes=["flat"], valign=Gtk.Align.CENTER)
    button.set_tooltip_text("Press this, then press the keys you want to use")
    widget.add_suffix(button)
    widget.set_activatable_widget(button)
    type_string = _value_type(backend, row) or "as"

    def refresh() -> None:
        try:
            label.set_accelerator(decode_accelerator(backend.get(key_for(row))))
        except BackendError:
            label.set_accelerator("")

    def store(accelerator: str) -> None:
        try:
            backend.set(key_for(row), encode_accelerator(type_string, accelerator))
        except (BackendError, RowBuildError):
            return
        refresh()

    button.connect("clicked", lambda *_a: present_capture_dialog(button, row, store))
    refresh()
    return widget, refresh


def present_capture_dialog(
    origin: Gtk.Widget,
    row: Row,
    on_accelerator: Callable[[str], None],
) -> Adw.AlertDialog:
    """Ask for a key combination and hand back what was pressed.

    Deliberately small: a dialog that says what to do, a key controller that
    decides with :func:`capture_for_key`, and one callback. It is returned so a
    caller (or a test) can drive it without going through the button.
    """
    dialog = Adw.AlertDialog(
        heading=row.title,
        body="Press the keys you want to use. Press Escape to keep the current one, "
        "or Backspace to remove it.",
    )
    dialog.add_response("cancel", "Cancel")

    controller = Gtk.EventControllerKey()

    def on_key(_controller: Gtk.EventControllerKey, keyval: int, _code: int, state: Any) -> bool:
        result = capture_for_key(keyval, state)
        if result.action is CaptureAction.IGNORE:
            return Gdk.EVENT_STOP
        if result.action is not CaptureAction.CANCEL:
            on_accelerator(result.accelerator)
        dialog.close()
        return Gdk.EVENT_STOP

    controller.connect("key-pressed", on_key)
    dialog.add_controller(controller)
    root = origin.get_root()
    if root is not None:
        dialog.present(root)
    return dialog


_ADVANCED: dict[WidgetKind, Callable[..., tuple[Adw.PreferencesRow, Callable[[], None]]]] = {
    WidgetKind.DICT_SLIDER: _build_dict_slider,
    WidgetKind.SHORTCUT: _build_shortcut,
}


def build_row(
    backend: SettingsBackend,
    row: Row,
    *,
    probe: SchemaProbe | None = None,
) -> tuple[Adw.PreferencesRow, Callable[[], None]]:
    """Build any descriptor row. The frozen base library, plus the hard kinds.

    Args:
        backend: where values are read and written.
        row: the descriptor.
        probe: when given, the row is checked first and an unavailable setting
            becomes a greyed row that says why, instead of being attempted.

    Returns:
        ``(widget, refresh)``, exactly as the base library does, so the row
        index and the page code cannot tell which builder produced a row.

    Raises:
        UnsupportedRowKind: ``picker`` rows, whose content comes from scanning
            the system rather than from a setting.
    """
    if probe is not None:
        availability = probe.availability(row)
        if not availability.ok:
            return unavailable_row(row, availability), (lambda: None)

    builder = _ADVANCED.get(row.kind)
    if builder is not None:
        return builder(backend, row)
    return build_base_row(backend, row)
