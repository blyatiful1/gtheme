"""Descriptor-to-widget construction. The one place a row is built.

THE CONTRACT IS FROZEN (DESIGN.md F3). Wave-2 page agents consume this and
never fork it: if every page builds its own switch row, then "every control has
an explainer" and "every control has a reset button" become fifteen separate
promises instead of one, and one of them will be broken.

What a row here always has:

* a **title and a subtitle**, both from the descriptor, both mandatory,
* a **reset affordance** that is only sensitive when the value differs from the
  schema default — the pattern Refine uses, and the reason a user can tell at a
  glance which of forty settings they have actually changed,
* an **honest disabled state**: when the schema is missing (the add-on is not
  installed) the row is insensitive and *says why*, rather than silently
  disappearing or, worse, appearing to work,
* **``requires_first`` handling**: settings that are inert until another key is
  written write that key first, and say so.

Everything reads and writes through a :class:`~gtheme.core.settings_backend
.SettingsBackend`, so the whole library is exercised in tests against
``MemoryBackend`` with no desktop involved.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ...core.settings_backend import BackendError, BackendErrorKind, SettingsBackend  # noqa: E402
from ...panels.descriptor import Row, WidgetKind  # noqa: E402

__all__ = [
    "RowBuildError",
    "UnsupportedRowKind",
    "attach_reset",
    "build_row",
    "key_for",
    "register_kind",
    "warn_banner",
]


class RowBuildError(Exception):
    """A descriptor cannot be turned into a widget."""


class UnsupportedRowKind(RowBuildError, NotImplementedError):
    """A row kind that exists in the format but has no widget yet.

    Deliberately both a build error and a ``NotImplementedError``: a page can
    catch it and render an honest "not available yet" row, and a test can
    assert the kind is named in the message.
    """

    def __init__(self, kind: WidgetKind) -> None:
        super().__init__(f"row kind {kind.value!r} is not built yet")
        self.kind = kind


def key_for(row: Row) -> str:
    """The backend key string for a descriptor row.

    A row whose value lives in the add-on's own settings file takes the
    four-part ``keyfile:`` form; relocatable schemas take the three-part form;
    everything else the two-part one. Rows never build key strings themselves.
    """
    if row.keyfile:
        return f"keyfile:{row.keyfile}:{row.schema_id}:{row.path} {row.key}"
    if row.path:
        return f"gsettings-path:{row.schema_id}:{row.path} {row.key}"
    return f"gsettings:{row.schema_id} {row.key}"


def warn_banner(text: str) -> Adw.Banner:
    """The consequence banner shown above a row or group.

    Phrased as what will happen, never as a warning triangle with a shrug.
    """
    banner = Adw.Banner(title=text, revealed=True)
    banner.add_css_class("warning")
    return banner


# --------------------------------------------------------------------------
# value helpers
# --------------------------------------------------------------------------


def _unavailable(row: Row, exc: BackendError) -> Adw.ActionRow:
    """The honest greyed-out row for a setting that is not present here."""
    if exc.kind is BackendErrorKind.NO_SCHEMA:
        reason = "This needs an add-on that isn't installed."
    elif exc.kind is BackendErrorKind.NO_KEY:
        reason = "The add-on on this computer is a different version and doesn't have this."
    else:
        reason = "This setting can't be read on this computer."
    action = Adw.ActionRow(title=row.title, subtitle=reason, sensitive=False)
    action.add_suffix(Gtk.Image(icon_name="action-unavailable-symbolic"))
    return action


def _default_text(backend: SettingsBackend, row: Row) -> str | None:
    """The schema default as GVariant text, or None if it cannot be read.

    Used only to decide whether the per-row reset button is sensitive, so a
    failure here degrades the button rather than the row.
    """
    try:
        from gi.repository import Gio

        source = backend.schema_source or Gio.SettingsSchemaSource.get_default()
        schema = source.lookup(row.schema_id, True) if source else None
        if schema is None or not schema.has_key(row.key):
            return None
        return schema.get_key(row.key).get_default_value().print_(True)
    except Exception:  # pragma: no cover - defensive; never fatal
        return None


def _write(backend: SettingsBackend, row: Row, value: str) -> None:
    """Write a row's value, honouring ``requires_first`` first.

    The ordering is the whole point: writing "sharper text" while the system is
    still choosing text rendering for itself produces a control that visibly
    moves and changes nothing.
    """
    for prerequisite in row.requires_first:
        key = f"gsettings:{prerequisite.schema_id} {prerequisite.key}"
        try:
            if backend.get(key) != prerequisite.value:
                backend.set(key, prerequisite.value)
        except BackendError:
            # The prerequisite key is missing on this system. Writing the main
            # key anyway is the lesser evil: it is what the user asked for, and
            # the prerequisite only exists on systems that have it.
            pass
    backend.set(key_for(row), value)


# --------------------------------------------------------------------------
# per-kind builders
# --------------------------------------------------------------------------


def _build_toggle(backend: SettingsBackend, row: Row) -> tuple[Adw.PreferencesRow, Callable[[], None]]:
    widget = Adw.SwitchRow(title=row.title, subtitle=row.subtitle)
    guard = {"busy": False}

    def refresh() -> None:
        guard["busy"] = True
        try:
            widget.set_active(backend.get(key_for(row)) == "true")
        finally:
            guard["busy"] = False

    def on_toggled(*_args: Any) -> None:
        if guard["busy"]:
            return
        _write(backend, row, "true" if widget.get_active() else "false")

    refresh()
    widget.connect("notify::active", on_toggled)
    return widget, refresh


def _build_slider(backend: SettingsBackend, row: Row) -> tuple[Adw.PreferencesRow, Callable[[], None]]:
    step = row.step or 1
    widget = Adw.SpinRow.new_with_range(row.clamp_min, row.clamp_max, step)
    widget.set_title(row.title)
    widget.set_subtitle(row.subtitle)
    if step < 1:
        widget.set_digits(2)
    guard = {"busy": False}

    def refresh() -> None:
        guard["busy"] = True
        try:
            raw = backend.get(key_for(row))
            try:
                current = float(raw)
            except ValueError:
                current = row.clamp_min
            widget.set_value(min(max(current, row.clamp_min), row.clamp_max))
        finally:
            guard["busy"] = False

    def on_changed(*_args: Any) -> None:
        if guard["busy"]:
            return
        value = min(max(widget.get_value(), row.clamp_min), row.clamp_max)
        # An integer key must not be handed "3.0" — GVariant rejects it.
        text = str(int(round(value))) if step >= 1 and float(step).is_integer() else repr(value)
        _write(backend, row, text)

    refresh()
    widget.connect("notify::value", on_changed)
    return widget, refresh


#: Appended to a choice row when the stored value is not one gtheme offers.
FOREIGN_CHOICE_SUFFIX = " — set somewhere else"


def _build_choice(backend: SettingsBackend, row: Row) -> tuple[Adw.PreferencesRow, Callable[[], None]]:
    """A pick-one row.

    The hard case is a stored value that is not among the offered options —
    something GNOME's own Settings wrote, or a value from a newer version of an
    add-on. Neither ``Adw.ComboRow`` nor ``Gtk.DropDown`` can show "nothing
    selected": both clamp an invalid index back to zero, which would display
    the *first* option while the desktop actually holds something else, and
    then write that first option the moment the user touched anything nearby.

    So the foreign value is appended to the list as a real, selected entry,
    labelled as coming from elsewhere. The user sees the truth, the value is
    not overwritten, and picking a real option retires the extra entry.
    """
    labels = Gtk.StringList()
    for choice in row.choices:
        labels.append(choice.label)
    widget = Adw.ComboRow(title=row.title, subtitle=row.subtitle, model=labels)
    values = [choice.value for choice in row.choices]
    guard = {"busy": False}
    foreign: dict[str, str | None] = {"value": None}

    def drop_foreign() -> None:
        if foreign["value"] is not None:
            labels.remove(len(values))
            foreign["value"] = None

    def refresh() -> None:
        guard["busy"] = True
        try:
            current = backend.get(key_for(row))
            if current in values:
                drop_foreign()
                widget.set_selected(values.index(current))
                return
            if foreign["value"] != current:
                drop_foreign()
                labels.append(_unquote(current) + FOREIGN_CHOICE_SUFFIX)
                foreign["value"] = current
            widget.set_selected(len(values))
        finally:
            guard["busy"] = False

    def on_selected(*_args: Any) -> None:
        if guard["busy"]:
            return
        index = widget.get_selected()
        if index < len(values):
            _write(backend, row, values[index])
            refresh()

    refresh()
    widget.connect("notify::selected", on_selected)
    return widget, refresh


def _build_text(backend: SettingsBackend, row: Row) -> tuple[Adw.PreferencesRow, Callable[[], None]]:
    widget = Adw.EntryRow(title=row.title)
    guard = {"busy": False}

    def refresh() -> None:
        guard["busy"] = True
        try:
            raw = backend.get(key_for(row))
            widget.set_text(_unquote(raw))
        finally:
            guard["busy"] = False

    def on_apply(*_args: Any) -> None:
        if guard["busy"]:
            return
        _write(backend, row, GLib.Variant("s", widget.get_text()).print_(True))

    refresh()
    widget.connect("apply", on_apply)
    return widget, refresh


def _build_color(backend: SettingsBackend, row: Row) -> tuple[Adw.PreferencesRow, Callable[[], None]]:
    """Colour row placeholder.

    Deliberately not a colour picker yet: the schemas disagree about what a
    colour is (some store ``"#rrggbb"``, some a ``(dddd)`` tuple) and picking
    one representation here would bake the wrong one in. Renders the stored
    value read-only so the row exists, is honest, and is replaceable.
    """
    widget = Adw.ActionRow(title=row.title, subtitle=row.subtitle)
    label = Gtk.Label(css_classes=["dim-label"])
    widget.add_suffix(label)

    def refresh() -> None:
        try:
            label.set_text(_unquote(backend.get(key_for(row))))
        except BackendError:
            label.set_text("")

    refresh()
    return widget, refresh


def _unquote(variant_text: str) -> str:
    """Strip GVariant string quoting for display. ``"'x'"`` -> ``x``."""
    text = variant_text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        return text[1:-1]
    return text


RowBuilder = Callable[..., tuple[Adw.PreferencesRow, Callable[[], None]]]

_BUILDERS: dict[WidgetKind, RowBuilder] = {
    WidgetKind.TOGGLE: _build_toggle,
    WidgetKind.SLIDER: _build_slider,
    WidgetKind.CHOICE: _build_choice,
    WidgetKind.TEXT: _build_text,
    WidgetKind.COLOR: _build_color,
}


def register_kind(kind: WidgetKind, builder: RowBuilder) -> None:
    """Teach :func:`build_row` how to draw one more kind of row.

    The five kinds above are the ones every page needs. The rest — a dictionary
    slider for one add-on's ``a{sv}`` blob, a keyboard-shortcut capture, an
    add-on's own one-of-N effect picker — are specialised enough that building
    them here would drag their domain into the base library. They register
    instead, from the module that owns the domain (see
    :mod:`gtheme.panels.widgets`).

    A registered kind gets everything a built-in kind gets, the reset button
    included: :func:`build_row` is the only entry point either way.

    Args:
        kind: which row kind this builder answers for.
        builder: ``(backend, row) -> (widget, refresh)``, the same contract the
            built-in builders honour. ``refresh`` re-reads the value and
            updates the widget without firing a write.

    Raises:
        ValueError: something already answers for this kind. Two builders for
            one kind means whichever module imported last wins, which is not a
            thing to discover at runtime.
    """
    existing = _BUILDERS.get(kind)
    if existing is not None and existing is not builder:
        raise ValueError(
            f"row kind {kind.value!r} already has a builder ({existing.__name__}); "
            "registering a second one would make the result depend on import order"
        )
    _BUILDERS[kind] = builder


def build_row(
    backend: SettingsBackend,
    row: Row,
) -> tuple[Adw.PreferencesRow, Callable[[], None]]:
    """Build the widget for one descriptor row.

    Args:
        backend: where the value is read from and written to.
        row: the descriptor.

    Returns:
        ``(widget, refresh)``. ``refresh`` re-reads the current value and
        updates the widget without firing a write; register it with the
        :class:`~gtheme.ui.rowindex.RowIndex` so external changes and per-row
        resets can drive it.

    Raises:
        UnsupportedRowKind: kinds that exist in the descriptor format but have
            no widget yet (``dict_slider``, ``shortcut``, ``picker``). The kind
            is named in the message and on the exception.
    """
    builder = _BUILDERS.get(row.kind)
    if builder is None:
        raise UnsupportedRowKind(row.kind)

    try:
        widget, refresh = builder(backend, row)
    except BackendError as exc:
        if exc.kind in (BackendErrorKind.NO_SCHEMA, BackendErrorKind.NO_KEY):
            unavailable = _unavailable(row, exc)
            return unavailable, lambda: None
        raise

    # A row with no setting behind it — a link through to somewhere else —
    # has nothing to put back, so it gets no reset button however the
    # descriptor is written.
    if row.reset and row.key is not None:
        refresh = attach_reset(backend, row, widget, refresh)
    if row.warn:
        widget.set_tooltip_text(row.warn)
    return widget, refresh


def attach_reset(
    backend: SettingsBackend,
    row: Row,
    widget: Adw.PreferencesRow,
    refresh: Callable[[], None],
) -> Callable[[], None]:
    """Add the per-row "put this back" button, sensitive only when changed.

    Public, because rows registered through :func:`register_kind` want it too
    and there is no second correct way to write it. :func:`build_row` calls
    this for every ``reset`` row itself, so a builder only needs it directly
    when it is composing something :func:`build_row` does not drive.

    Returns a refresh callable that also updates the button, so the caller has
    one function that keeps the whole row consistent.
    """
    default = _default_text(backend, row)
    button = Gtk.Button(
        icon_name="edit-undo-symbolic",
        tooltip_text="Put this back the way it was",
        valign=Gtk.Align.CENTER,
        css_classes=["flat"],
    )

    def update_sensitivity() -> None:
        if default is None:
            button.set_visible(False)
            return
        try:
            button.set_sensitive(backend.get(key_for(row)) != default)
        except BackendError:
            button.set_sensitive(False)

    def on_clicked(*_args: Any) -> None:
        try:
            backend.reset(key_for(row))
        except BackendError:
            return
        refresh()
        update_sensitivity()

    button.connect("clicked", on_clicked)
    update_sensitivity()
    widget.add_suffix(button)

    # Wrap refresh so the button's sensitivity follows every value change,
    # including ones that came from outside the app.
    def wrapped() -> None:
        refresh()
        update_sensitivity()

    return wrapped
