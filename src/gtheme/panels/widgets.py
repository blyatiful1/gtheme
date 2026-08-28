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

The entry point is :func:`build_row`, which is the frozen builder plus the
schema probe. The kinds themselves are handed to the frozen builder through
:func:`~gtheme.ui.widgets.rows.register_kind` at import time, so a registered
kind is a first-class row: same entry point, same reset button, same warning
tooltip, same greying.
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
from ..ui.widgets.recording import WriteRefused, reason_for, recording  # noqa: E402
from ..ui.widgets.rows import (  # noqa: E402
    RowBuildError,
    key_for,
    register_kind,
    report_refusal,
    set_plain_text,
    write_value,
)
from ..ui.widgets.rows import build_row as build_base_row  # noqa: E402
from .descriptor import Row, WidgetKind  # noqa: E402
from .schema_probe import Availability, SchemaProbe, resolve_row  # noqa: E402

__all__ = [
    "CLASH_COPY",
    "CLEARED",
    "Capture",
    "CaptureAction",
    "Clamp",
    "KNOWN_CLAMPS",
    "NO_EFFECT_LABEL",
    "ShortcutClash",
    "build_effect_picker",
    "build_effect_speed",
    "build_link_row",
    "build_row",
    "capture_for_key",
    "clamp_violations",
    "clash_sentence",
    "confirm_replace",
    "decode_accelerator",
    "dict_number",
    "dict_with_number",
    "encode_accelerator",
    "find_clashes",
    "same_keys",
    "set_link_handler",
    "shortcut_keys_label",
    "shortcut_rows",
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
    widget = Adw.ActionRow(sensitive=False)
    set_plain_text(widget, title=row.title, subtitle=availability.reason)
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
    set_plain_text(widget, title=row.title, subtitle=row.subtitle)
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
        write_value(backend, key, updated, widget=widget, refresh=refresh, component=row.id)

    refresh()
    widget.connect("notify::value", on_changed)
    return widget, refresh


def build_effect_picker(
    backend: SettingsBackend, row: Row
) -> tuple[Adw.PreferencesRow, Callable[[], None]]:
    """One-of-N over a run of separate on/off settings.

    burn-my-windows keeps 26 animations as 26 independent booleans and plays
    whichever is on. Shown as switches, that is six controls in the app that
    silently fight each other: turning one on leaves the previous one on too,
    and the add-on picks between them by rules nobody can see. Shown as a
    picker, choosing an effect turns that one on and every other one off, in
    one action, which is what the person meant.

    ``row.choices`` carry the sibling key names, not values. The key strings
    are built from the row itself, so a profile row resolved to the add-on's
    own settings file writes into that file — see
    :func:`gtheme.panels.schema_probe.resolve_row`.
    """
    known = set(_effect_names(backend, row))
    # "None" first, and it is a real answer rather than a placeholder: with
    # every effect switched off the add-on plays nothing, which is a thing
    # people choose. Without it, a profile with nothing on would show the first
    # effect as though it were in use — Adw.ComboRow has no empty selection.
    options: list[tuple[str | None, str, str | None]] = [
        (None, NO_EFFECT_LABEL, "Windows just open and close, with no animation.")
    ]
    options += [
        (choice.value, choice.label, choice.subtitle)
        for choice in row.choices
        # An effect this version of the add-on does not have would be an option
        # that does nothing. When the schema cannot be read at all, offer
        # everything rather than nothing.
        if not known or choice.value.removesuffix(_EFFECT_ENABLE_SUFFIX) in known
    ]
    widget = Adw.ComboRow()
    set_plain_text(widget, title=row.title, subtitle=row.subtitle)
    widget.set_model(Gtk.StringList.new([label for _key, label, _sub in options]))
    guard = {"busy": False}

    def key_of(name: str) -> str:
        return key_for(row.model_copy(update={"key": name}))

    def refresh() -> None:
        guard["busy"] = True
        try:
            for index, (name, _label, _sub) in enumerate(options):
                if name is None:
                    continue
                try:
                    if backend.get(key_of(name)).strip() == "true":
                        widget.set_selected(index)
                        return
                except BackendError:
                    continue
            widget.set_selected(0)  # "None"
        finally:
            guard["busy"] = False

    def on_selected(*_args: Any) -> None:
        if guard["busy"]:
            return
        index = widget.get_selected()
        if index == Gtk.INVALID_LIST_POSITION or index >= len(options):
            return
        chosen = options[index][0]
        recorder = recording(backend, component=row.id)
        for name, _label, _sub in options:
            if name is None:
                continue
            try:
                recorder.set(key_of(name), "true" if name == chosen else "false")
            except BackendError:
                # An effect this version of the add-on does not have is not a
                # reason to abandon the rest of the change.
                continue
            except WriteRefused as exc:
                # This one is not per-effect: the lock is held by an apply, or
                # nothing can be written down first. It is true of all
                # twenty-six keys, so it is said once and the row goes back to
                # showing what is really playing (review-report M7).
                refresh()
                report_refusal(widget, reason_for(exc))
                return

    refresh()
    widget.connect("notify::selected", on_selected)
    return widget, refresh


#: What the effect picker calls "play no animation at all".
NO_EFFECT_LABEL = "Nothing"

#: How an effect's on/off setting is named, and how its duration is named.
_EFFECT_ENABLE_SUFFIX = "-enable-effect"
_EFFECT_TIME_SUFFIX = "-animation-time"


def _effect_names(backend: SettingsBackend, row: Row) -> list[str]:
    """Every effect the installed add-on knows about, read from its schema.

    Read rather than listed, so a new effect in a newer version of the add-on
    is picked up without a data change here — and so an effect that a version
    does NOT have cannot be offered.
    """
    try:
        from gi.repository import Gio

        source = backend.schema_source or Gio.SettingsSchemaSource.get_default()
        schema = source.lookup(row.schema_id, True) if source is not None else None
        if schema is None:
            return []
        return sorted(
            key.removesuffix(_EFFECT_ENABLE_SUFFIX)
            for key in schema.list_keys()
            if key.endswith(_EFFECT_ENABLE_SUFFIX)
        )
    except Exception:  # pragma: no cover - defensive; never fatal
        return []


def _chosen_effect(backend: SettingsBackend, row: Row, names: Iterable[str]) -> str | None:
    """Which effect is switched on, if any."""
    for name in names:
        key = key_for(row.model_copy(update={"key": name + _EFFECT_ENABLE_SUFFIX}))
        try:
            if backend.get(key).strip() == "true":
                return name
        except BackendError:
            continue
    return None


def build_effect_speed(
    backend: SettingsBackend, row: Row
) -> tuple[Adw.PreferencesRow, Callable[[], None]]:
    """The duration of whichever effect is currently chosen.

    burn-my-windows gives every effect its own duration setting. Rendering all
    of them means twenty-six sliders of which twenty-five do nothing; picking
    one at authoring time means the slider is wrong as soon as the person
    changes the effect. So the row follows the picker: it reads and writes
    ``<chosen>-animation-time``, and greys itself when nothing is chosen.
    """
    if row.clamp_min is None or row.clamp_max is None:
        raise RowBuildError(f"{row.id}: an effect speed still needs clamp_min and clamp_max")
    widget = Adw.SpinRow.new_with_range(row.clamp_min, row.clamp_max, row.step or 50)
    set_plain_text(widget, title=row.title, subtitle=row.subtitle)
    guard = {"busy": False}
    state: dict[str, str | None] = {"key": None}

    def refresh() -> None:
        guard["busy"] = True
        try:
            chosen = _chosen_effect(backend, row, _effect_names(backend, row))
            if chosen is None:
                state["key"] = None
                widget.set_sensitive(False)
                return
            key = key_for(row.model_copy(update={"key": chosen + _EFFECT_TIME_SUFFIX}))
            state["key"] = key
            try:
                value = float(backend.get(key).strip())
            except (BackendError, ValueError):
                widget.set_sensitive(False)
                return
            widget.set_sensitive(True)
            widget.set_value(min(max(value, row.clamp_min), row.clamp_max))
        finally:
            guard["busy"] = False

    def on_changed(*_args: Any) -> None:
        if guard["busy"] or state["key"] is None:
            return
        value = int(min(max(widget.get_value(), row.clamp_min), row.clamp_max))
        write_value(
            backend,
            state["key"],
            str(value),
            widget=widget,
            refresh=refresh,
            component=row.id,
        )

    refresh()
    widget.connect("notify::value", on_changed)
    return widget, refresh


def build_link_row(
    _backend: SettingsBackend, row: Row
) -> tuple[Adw.PreferencesRow, Callable[[], None]]:
    """A way through to somewhere else: a row with an arrow, and nothing else.

    Where it goes is :attr:`Row.link_target`. *Opening* the destination is not
    this library's business — an add-on's own preferences window is opened by
    the Add-ons page, which owns the D-Bus call, and another page of this app
    is reached through the window. So the widget carries an activatable
    callback slot instead, set with :func:`set_link_handler`, and does nothing
    until something fills it in.

    Deliberately not greyed when unset: a row that looks broken because the
    page that wires it up has not been written yet would be a lie about the
    add-on rather than about us.
    """
    widget = Adw.ActionRow()
    set_plain_text(widget, title=row.title, subtitle=row.subtitle)
    widget.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
    widget.set_activatable(True)
    widget.connect("activated", _on_link_activated)
    return widget, (lambda: None)


#: Set on a link row's widget by :func:`set_link_handler`.
_LINK_HANDLER = "_gtheme_link_handler"
_LINK_TARGET = "_gtheme_link_target"


def _on_link_activated(widget: Adw.ActionRow) -> None:
    handler = getattr(widget, _LINK_HANDLER, None)
    if handler is not None:
        handler(getattr(widget, _LINK_TARGET, None))


def set_link_handler(
    widget: Adw.PreferencesRow, row: Row, handler: Callable[[str | None], None]
) -> None:
    """Say what activating a link row should do.

    Args:
        widget: the row built by :func:`build_link_row`.
        row: the descriptor it came from.
        handler: called with :attr:`Row.link_target` when the row is clicked.
    """
    setattr(widget, _LINK_TARGET, row.link_target)
    setattr(widget, _LINK_HANDLER, handler)


# --------------------------------------------------------------------------
# shortcut clashes (persona-report §3.2)
#
# GNOME's own Settings stops you when the keys you just pressed already belong
# to something else, and offers to move them. gtheme — which exists to be the
# safer of the two — wrote whatever was pressed and left two shortcuts fighting
# over one combination, with nothing on screen to say which one would win.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ShortcutClash:
    """Another shortcut that already answers to the keys just pressed."""

    row: Row
    accelerator: str


def same_keys(first: str, second: str) -> bool:
    """Whether two written combinations are the same combination.

    Compared through the toolkit rather than as text: ``<Primary>t``,
    ``<Control>T`` and ``<Ctrl>t`` are one shortcut spelled three ways, and all
    three spellings are in GNOME's own defaults.
    """
    if not first or not second:
        return False
    parsed_first = Gtk.accelerator_parse(first)
    parsed_second = Gtk.accelerator_parse(second)
    if not parsed_first[0] or not parsed_second[0]:
        return first.strip().lower() == second.strip().lower()
    return parsed_first[1:] == parsed_second[1:]


def shortcut_keys_label(accelerator: str) -> str:
    """``<Super>m`` as a person reads it: "Super+M"."""
    ok, keyval, mods = Gtk.accelerator_parse(accelerator)
    if not ok:
        return accelerator
    return Gtk.accelerator_get_label(keyval, mods)


def shortcut_rows(corpus: Any = None) -> list[Row]:
    """Every row in the app that holds a key combination.

    All of them, not only the ones on the page being edited: the shortcuts and
    the media keys are two files and one keyboard, and a clash between them is
    exactly the clash a person cannot see coming.
    """
    from .loader import load_corpus

    loaded = corpus if corpus is not None else load_corpus()
    return [row for row in loaded.rows if row.kind is WidgetKind.SHORTCUT and row.key]


def find_clashes(
    backend: SettingsBackend,
    accelerator: str,
    *,
    exclude_key: str,
    rows: Iterable[Row] | None = None,
) -> list[ShortcutClash]:
    """Which other shortcuts already use these keys.

    Only the first combination of a setting that holds several is compared —
    that is the one the row shows and the one this app can write, so it is the
    one it can honestly offer to take away.
    """
    if not accelerator:
        return []
    clashes: list[ShortcutClash] = []
    for other in rows if rows is not None else shortcut_rows():
        other_key = key_for(other)
        if other_key == exclude_key:
            continue
        try:
            current = decode_accelerator(backend.get(other_key))
        except BackendError:
            continue
        if same_keys(current, accelerator):
            clashes.append(ShortcutClash(row=other, accelerator=current))
    return clashes


def clash_sentence(clashes: Iterable[ShortcutClash], accelerator: str) -> str:
    """What the dialog says, in the order a person needs to hear it."""
    titles = [f"“{clash.row.title}”" for clash in clashes]
    if len(titles) > 2:
        named = ", ".join(titles[:-1]) + f" and {titles[-1]}"
    else:
        named = " and ".join(titles)
    verb = "uses" if len(titles) == 1 else "use"
    subject = "That shortcut" if len(titles) == 1 else "Those shortcuts"
    return (
        f"{named} already {verb} {shortcut_keys_label(accelerator)}. "
        f"{subject} will be left with no keys at all if you use them here."
    )


#: What the clash dialog says. Named so the plain-language lint can read it.
CLASH_COPY: dict[str, str] = {
    "heading": "Those keys are already used",
    "cancel": "Keep it as it was",
    "replace": "Use them here",
}


def confirm_replace(
    origin: Gtk.Widget,
    accelerator: str,
    clashes: list[ShortcutClash],
    on_replace: Callable[[], None],
) -> Adw.AlertDialog:
    """Offer the choice GNOME's own Settings offers: replace, or keep.

    Returned so a test can press either response without a pointer.
    """
    dialog = Adw.AlertDialog(
        heading=CLASH_COPY["heading"], body=clash_sentence(clashes, accelerator)
    )
    dialog.add_response("cancel", CLASH_COPY["cancel"])
    dialog.add_response("replace", CLASH_COPY["replace"])
    dialog.set_response_appearance("replace", Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.set_default_response("cancel")
    dialog.set_close_response("cancel")

    def answered(_dialog: Adw.AlertDialog, response: str) -> None:
        if response == "replace":
            on_replace()

    dialog.connect("response", answered)
    root = origin.get_root()
    if root is not None:
        dialog.present(root)
    return dialog


def _build_shortcut(
    backend: SettingsBackend, row: Row
) -> tuple[Adw.PreferencesRow, Callable[[], None]]:
    widget = Adw.ActionRow()
    set_plain_text(widget, title=row.title, subtitle=row.subtitle)
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

    def put(encoded: str) -> None:
        if write_value(
            backend, key_for(row), encoded, widget=widget, refresh=refresh, component=row.id
        ):
            refresh()

    def take_from(clashes: list[ShortcutClash]) -> None:
        """Leave the other shortcuts with no keys, so this one really works.

        Two settings holding one combination is not a state the desktop
        resolves in anybody's favour; it is the state where pressing the keys
        does whichever of the two the shell happened to bind last.
        """
        for clash in clashes:
            other_type = _value_type(backend, clash.row) or "as"
            try:
                cleared = encode_accelerator(other_type, CLEARED)
            except RowBuildError:  # pragma: no cover - defensive
                continue
            write_value(
                backend,
                key_for(clash.row),
                cleared,
                widget=widget,
                refresh=refresh,
                component=clash.row.id,
            )

    def store(accelerator: str) -> None:
        try:
            encoded = encode_accelerator(type_string, accelerator)
        except RowBuildError:
            # A key combination this setting cannot hold. Nothing was written,
            # and the label still shows what really is set.
            return
        clashes = find_clashes(backend, accelerator, exclude_key=key_for(row))
        if clashes:
            # Nothing is written yet. The question is asked first, and both
            # answers are honest: "Use them here" takes the keys away from the
            # others, and anything else leaves the desktop exactly as it is.
            def replace() -> None:
                take_from(clashes)
                put(encoded)

            confirm_replace(button, accelerator, clashes, replace)
            return
        put(encoded)

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


# Register the two hard kinds with the base library rather than dispatching
# around it. Going around it is how they ended up as the only rows in the app
# with no "put this back" button: that button is attached by the base
# ``build_row``, and a builder it never sees never gets one.
register_kind(WidgetKind.DICT_SLIDER, _build_dict_slider)
register_kind(WidgetKind.SHORTCUT, _build_shortcut)
register_kind(WidgetKind.LINK, build_link_row)
register_kind(WidgetKind.EFFECT_PICKER, build_effect_picker)
register_kind(WidgetKind.EFFECT_SPEED, build_effect_speed)


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
    # Some add-ons keep their settings in a file of their own rather than in
    # the desktop's settings store. Resolving the row first is what makes those
    # rows live rather than a control that reports success and changes nothing.
    row = resolve_row(row, backend)
    if probe is not None:
        availability = probe.availability(row, backend)
        if not availability.ok:
            return unavailable_row(row, availability), (lambda: None)
    return build_base_row(backend, row)
