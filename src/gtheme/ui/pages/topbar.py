"""Top Bar & Overview — DESIGN.md A6/§C step 16.

The clock, the date, the battery percentage, the hot corner and the calendar
options (``topbar.toml``) render as ordinary descriptor rows. The one row that
does not — the top bar's style (``topbarstyle.toml``) — is a ``picker``, a
kind the frozen row library deliberately leaves unbuilt: its content comes
from scanning installed shell themes, not from a setting's own schema, so
building it is this page's job (``panels.widgets`` docstring, "the picker
gap").

That row is also the one place on this page that needs the "fix-button" flow:
writing a style name does nothing at all while the desktop's User Themes
add-on is switched off (research/gnome-domains.md §4, "the extension must be
enabled" gotcha), and a control that visibly changes and silently does nothing
is the one failure this app exists to prevent.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ...core.backends import get_backend  # noqa: E402
from ...core.settings_backend import BackendError, SettingsBackend  # noqa: E402
from ...panels.descriptor import DomainDescriptor, Row  # noqa: E402
from ...panels.loader import load_domains  # noqa: E402
from ...panels.schema_probe import SchemaProbe  # noqa: E402
from ...panels.widgets import build_row, unavailable_row  # noqa: E402
from ...system.themescan import default_theme_roots, scan_themes, shell_themes  # noqa: E402
from ...ui.widgets.rows import attach_reset, key_for, set_plain_text  # noqa: E402

__all__ = ["build"]

PAGE_ID = "topbar"
BANNER_ID = "first-visit-topbar"

_DOMAIN_IDS = ("topbar", "topbarstyle")

#: The add-on that has to be switched on for a top bar style to do anything.
_USER_THEME_UUID = "user-theme@gnome-shell-extensions.gcampax.github.com"
_ENABLED_EXTENSIONS_KEY = "gsettings:org.gnome.shell enabled-extensions"

#: What an empty ``name`` means: the style the desktop ships with.
_BUILT_IN_LABEL = "The one your desktop comes with"


def _search_text(row: Row) -> str:
    return " ".join([row.title, row.subtitle, *row.synonyms])


def _add_row(window, group: Adw.PreferencesGroup, row: Row, *, backend, probe) -> None:
    widget, refresh = build_row(backend, row, probe=probe)
    group.add(widget)
    window.rows.register(PAGE_ID, row.id, widget, refresh=refresh, search_text=_search_text(row))


def _clock_group(window, page: Adw.PreferencesPage, domain: DomainDescriptor, *, backend, probe) -> None:
    group = Adw.PreferencesGroup()
    set_plain_text(group, title=domain.title)
    for row in domain.rows:
        _add_row(window, group, row, backend=backend, probe=probe)
    page.add(group)


# -- the extension-enabled check --------------------------------------------


def _enabled_uuids(backend: SettingsBackend) -> list[str] | None:
    """The desktop's own enabled-add-ons list, or None if it cannot be read."""
    try:
        raw = backend.get(_ENABLED_EXTENSIONS_KEY)
    except BackendError:
        return None
    try:
        return list(GLib.Variant.parse(GLib.VariantType("as"), raw, None, None).unpack())
    except GLib.Error:
        return None


def _enable_user_theme(backend: SettingsBackend) -> bool:
    """Turn the User Themes add-on on. Returns whether it changed anything."""
    current = _enabled_uuids(backend)
    if current is None or _USER_THEME_UUID in current:
        return False
    updated = [*current, _USER_THEME_UUID]
    try:
        backend.set(_ENABLED_EXTENSIONS_KEY, GLib.Variant("as", updated).print_(True))
    except BackendError:
        return False
    return True


# -- the shell-theme picker --------------------------------------------------


def _unquote(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        return text[1:-1]
    return text


def _scoped_backend(backend: SettingsBackend, probe: SchemaProbe, row: Row) -> SettingsBackend:
    """A backend that can actually see this row's schema.

    The top bar style lives in the User Themes add-on's own ``schemas/``
    directory, not in the system store (research/gnome-domains.md §4) — the
    exact case :meth:`SchemaProbe.source_for_row` exists for. A plain
    ``get_backend()`` only knows the system source, so a second instance of
    the same backend class is built, scoped to the source the probe already
    found. Same store (GioBackend still talks to the real dconf, a fresh
    ``MemoryBackend`` still writes nowhere); the schema is just visible now.
    """
    source = probe.source_for_row(row)
    if source is None or source is backend.schema_source:
        return backend
    return type(backend)(schema_source=source)


def _build_style_picker(
    window, backend: SettingsBackend, probe: SchemaProbe, row: Row
) -> Adw.PreferencesRow:
    """The picker: every installed shell theme, plus the one already in use."""
    backend = _scoped_backend(backend, probe, row)
    names = sorted({entry.name for entry in shell_themes(scan_themes(default_theme_roots()))})
    values = ["", *names]
    labels = [_BUILT_IN_LABEL, *names]

    model = Gtk.StringList.new(labels)
    picker = Adw.ComboRow(title=row.title, subtitle=row.subtitle, model=model)
    if row.warn:
        picker.set_tooltip_text(row.warn)
    guard = {"busy": False}
    foreign: dict[str, str | None] = {"value": None}

    def drop_foreign() -> None:
        if foreign["value"] is not None:
            model.remove(len(values))
            foreign["value"] = None

    def refresh() -> None:
        guard["busy"] = True
        try:
            try:
                current = _unquote(backend.get(key_for(row)))
            except BackendError:
                current = ""
            if current in values:
                drop_foreign()
                picker.set_selected(values.index(current))
                return
            if foreign["value"] != current:
                drop_foreign()
                model.append(f"{current} — not one gtheme found installed")
                foreign["value"] = current
            picker.set_selected(len(values))
        finally:
            guard["busy"] = False

    def on_selected(*_args: object) -> None:
        if guard["busy"]:
            return
        index = picker.get_selected()
        if index == Gtk.INVALID_LIST_POSITION or index >= len(values):
            return
        try:
            backend.set(key_for(row), GLib.Variant("s", values[index]).print_(True))
        except BackendError:
            return
        refresh()

    refresh()
    picker.connect("notify::selected", on_selected)
    refresh_with_reset = attach_reset(backend, row, picker, refresh) if row.reset else refresh
    window.rows.register(
        PAGE_ID, row.id, picker, refresh=refresh_with_reset, search_text=_search_text(row)
    )
    return picker


def _style_group(window, page: Adw.PreferencesPage, domain: DomainDescriptor, *, backend, probe) -> None:
    row = domain.rows[0]
    availability = probe.availability(row, backend)
    if not availability.ok:
        group = Adw.PreferencesGroup()
        set_plain_text(group, title=domain.title)
        widget = unavailable_row(row, availability)
        group.add(widget)
        window.rows.register(PAGE_ID, row.id, widget, search_text=_search_text(row))
        page.add(group)
        return

    # The caveat that always applies (a style is one fixed design, light and
    # dark alike) is the group's description; the "turn it on" fix — needed
    # only while the add-on that makes this row do anything is switched off
    # — replaces it for as long as that is true.
    group = Adw.PreferencesGroup()
    set_plain_text(group, title=domain.title, description=row.warn or "")

    def _refresh_enabled_state() -> None:
        enabled = _enabled_uuids(backend)
        if enabled is not None and _USER_THEME_UUID not in enabled:
            group.set_description("To use this, gtheme needs to turn on one add-on.")
            button = Gtk.Button(label="Turn it on", css_classes=["suggested-action"])

            def _turn_on(*_args: object) -> None:
                _enable_user_theme(backend)
                _refresh_enabled_state()

            button.connect("clicked", _turn_on)
            group.set_header_suffix(button)
        else:
            group.set_description(row.warn or "")
            group.set_header_suffix(None)

    _refresh_enabled_state()
    page.add(group)
    group.add(_build_style_picker(window, backend, probe, row))


def build(window) -> Gtk.Widget:
    backend = get_backend()
    probe = SchemaProbe()
    all_domains, problems = load_domains()
    if problems:
        raise RuntimeError("the descriptor corpus did not load: " + "; ".join(problems))
    domains = {domain.id: domain for domain in all_domains if domain.id in _DOMAIN_IDS}

    page = Adw.PreferencesPage()
    if "topbar" in domains:
        _clock_group(window, page, domains["topbar"], backend=backend, probe=probe)
    if "topbarstyle" in domains:
        _style_group(window, page, domains["topbarstyle"], backend=backend, probe=probe)

    if window.prefs.should_show_banner(BANNER_ID):
        intro = Adw.Banner(
            title="The clock, the date, the app view and the top bar's own style live here.",
            revealed=True,
        )
        intro.set_button_label("Got it")

        def _dismiss(*_args: object) -> None:
            window.prefs.mark_banner_seen(BANNER_ID)
            intro.set_revealed(False)

        intro.connect("button-clicked", _dismiss)
        wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        wrapper.append(intro)
        page.set_vexpand(True)
        wrapper.append(page)
        return wrapper

    return page
