"""More Settings — the floor. The page that makes "nothing was left out" true.

Every setting a GNOME 50 desktop has is dispositioned in
``data/domains/coverage.toml``. Most land on a page somebody designed. The rest
land *here*, and they land here automatically: :func:`gtheme.ui.search.floor_ids`
returns every key that no descriptor file describes, and this page draws a row
for each one from the desktop's own description of it.

That is the honest half of a promise the rest of the app makes by hand. The
coverage test proves nothing was forgotten; this page proves it to the person
sitting in front of the computer, who can find and change it.

Three rules the floor keeps.

**The words are not gtheme's, and it says so.** A floor row's title and
explanation come out of the system's own settings definitions, written by
developers for developers. They go through :func:`gtheme.ui.jargon.translate`
and then sit under a heading that tells the reader where they came from. That
is the difference between a plain-language app and one that pretends.

**Every group is explained, and every group is closed.** Two hundred and forty
rows in one list is not a page. They are grouped by the part of the desktop
they belong to, each group collapsed and each group carrying a sentence that
says what is inside — written by hand, and a test refuses a group without one.

**A setting gtheme cannot safely change is shown, not hidden.** A list of app
names or a pair of coordinates gets a row that displays the value and says it
cannot be edited here. Hiding it would break the promise; offering a text box
over it would break the desktop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...core.backends import get_backend
from ...core.settings_backend import BackendError
from ...panels import loader as corpus_loader
from ...panels.descriptor import Choice, Row, WidgetKind
from ...panels.schema_probe import SchemaProbe
from .. import jargon
from ..search import (
    ADVANCED_SUBTITLE,
    ADVANCED_TITLE,
    build_indexed_rows,
    escape_markup,
    floor_ids,
    page_rows,
    probe_built_rows,
    row_search_text,
)

__all__ = [
    "COPY",
    "GROUP_EXPLAINERS",
    "SCHEMA_EXPLAINERS",
    "SCHEMA_TITLES",
    "FloorKey",
    "build",
    "floor_keys",
    "humanise",
    "missing_explainers",
]

PAGE_ID = "more"

COPY: dict[str, str] = {
    "banner": (
        "This page holds everything that did not fit anywhere else. Most of it is "
        "described by your desktop rather than by gtheme, so the wording can be "
        "technical. Nothing here is needed for a good-looking desktop."
    ),
    "search-placeholder": "Search these settings",
    "floor-title": "Described by your desktop",
    "floor-description": (
        "The wording in these groups comes from your desktop itself, not from "
        "gtheme, which is why it reads the way it does. Each group is closed until "
        "you open it. Most people never need any of them."
    ),
    "system-text": "This explanation comes from your desktop itself.",
    "not-editable": "gtheme can show this but not change it here.",
    "unreadable": "gtheme could not read this on this computer.",
    "nothing-title": "Nothing matched",
    "nothing-body": "Try a different word, or clear the box to see everything again.",
}

#: One sentence per hand-written group on this page. Every group must have one:
#: :func:`missing_explainers` is what a test asks, and a group of switches with
#: no explanation is precisely the failure this app was written against.
GROUP_EXPLAINERS: dict[str, str] = {
    "lockdown": (
        "Things this computer is not allowed to do. Useful on a shared or a "
        "child's computer; on your own machine, leave them alone."
    ),
    "notifications": (
        "The little messages that slide in from the top of the screen when an app "
        "wants to tell you something."
    ),
    "peripherals": (
        "How your mouse, your touchpad and your keyboard behave — how fast the "
        "pointer moves, which way scrolling goes, how quickly a held key repeats."
    ),
    "privacy": (
        "What your computer remembers about what you have been doing, and what it "
        "throws away on its own."
    ),
    "searchproviders": (
        "Which apps are allowed to answer when you start typing in the app view."
    ),
    "wellbeing": (
        "Reminders to look away from the screen and to move about, and limits on "
        "how long the computer may be used."
    ),
}

#: A short heading for each part of the desktop the floor draws from.
SCHEMA_TITLES: dict[str, str] = {
    "org.gnome.desktop.a11y": "Making the desktop easier to use",
    "org.gnome.desktop.a11y.applications": "Reading the screen aloud, and magnifying it",
    "org.gnome.desktop.a11y.keyboard": "Typing help",
    "org.gnome.desktop.a11y.magnifier": "The magnifier",
    "org.gnome.desktop.a11y.mouse": "Pointer help",
    "org.gnome.desktop.default-applications.office.calendar": "Your calendar app",
    "org.gnome.desktop.default-applications.office.tasks": "Your to-do app",
    "org.gnome.desktop.default-applications.terminal": "Your command window app",
    "org.gnome.desktop.interface": "Odds and ends of how the desktop looks",
    "org.gnome.desktop.media-handling": "Discs, cameras and memory sticks",
    "org.gnome.desktop.notifications": "Messages that slide in",
    "org.gnome.desktop.peripherals.pointingstick": "The little stick between the keys",
    "org.gnome.desktop.peripherals.touchpad": "Touchpad extras",
    "org.gnome.desktop.peripherals.trackball": "Trackballs",
    "org.gnome.desktop.screensaver": "The lock screen",
    "org.gnome.desktop.search-providers": "Which apps answer your searches",
    "org.gnome.desktop.session": "Signing in and out",
    "org.gnome.desktop.thumbnail-cache": "Saved picture previews",
    "org.gnome.desktop.thumbnailers": "Making picture previews",
    "org.gnome.desktop.wm.keybindings": "Window shortcuts",
    "org.gnome.desktop.wm.preferences": "How windows behave",
    "org.gnome.mutter": "How windows are arranged",
    "org.gnome.mutter.wayland": "Running older apps",
    "org.gnome.settings-daemon.plugins.color": "Screen colour",
    "org.gnome.settings-daemon.plugins.media-keys": "The special keys on your keyboard",
    "org.gnome.settings-daemon.plugins.xsettings": "Settings older apps read",
    "org.gnome.shell": "The bar at the top and the app view",
    "org.gnome.system.location": "Where you are",
}

#: The mandatory sentence under each floor group's heading.
SCHEMA_EXPLAINERS: dict[str, str] = {
    "org.gnome.desktop.a11y": (
        "Small changes that help if you have trouble seeing the screen or using a "
        "mouse."
    ),
    "org.gnome.desktop.a11y.applications": (
        "Turns on the tools that read the screen out loud, magnify part of it, or "
        "put a keyboard on screen."
    ),
    "org.gnome.desktop.a11y.keyboard": (
        "Ways to make typing easier: ignoring repeated presses, holding a key "
        "instead of holding two at once, and beeping when a setting changes."
    ),
    "org.gnome.desktop.a11y.magnifier": (
        "How the on-screen magnifier behaves — how much it enlarges, where it "
        "follows, and how it colours what it shows."
    ),
    "org.gnome.desktop.a11y.mouse": (
        "Clicking without pressing a button: hovering to click, and holding still "
        "to click."
    ),
    "org.gnome.desktop.default-applications.office.calendar": (
        "Which app opens when something on your desktop wants to show you a date."
    ),
    "org.gnome.desktop.default-applications.office.tasks": (
        "Which app opens when something on your desktop wants to show you a list "
        "of things to do."
    ),
    "org.gnome.desktop.default-applications.terminal": (
        "The rest of the settings for the app that opens when something needs a "
        "command window."
    ),
    "org.gnome.desktop.interface": (
        "Leftovers from the desktop's own appearance settings that gtheme has not "
        "given a page of their own."
    ),
    "org.gnome.desktop.media-handling": (
        "What happens when you plug in a memory stick, put in a disc, or connect a "
        "camera."
    ),
    "org.gnome.desktop.notifications": (
        "The remaining settings for the messages apps slide in from the top of the "
        "screen."
    ),
    "org.gnome.desktop.peripherals.pointingstick": (
        "For laptops with a small pointing stick in the middle of the keyboard. "
        "Harmless to change if you do not have one."
    ),
    "org.gnome.desktop.peripherals.touchpad": (
        "The touchpad settings gtheme has not given a plainer name to."
    ),
    "org.gnome.desktop.peripherals.trackball": (
        "For a trackball — a mouse with a ball on top that you roll. Harmless to "
        "change if you do not have one."
    ),
    "org.gnome.desktop.screensaver": (
        "The screen you see when the computer is locked, and what it shows there."
    ),
    "org.gnome.desktop.search-providers": (
        "Which apps are asked, and in what order, when you type in the app view."
    ),
    "org.gnome.desktop.session": (
        "What counts as you having stopped using the computer, and what happens "
        "when you sign out."
    ),
    "org.gnome.desktop.thumbnail-cache": (
        "How long your computer keeps the small preview pictures it makes of your "
        "files before it clears them out."
    ),
    "org.gnome.desktop.thumbnailers": (
        "Whether your computer makes small preview pictures of your files, and for "
        "which kinds of file."
    ),
    "org.gnome.desktop.wm.keybindings": (
        "Key combinations for moving and resizing windows that are not on the "
        "Windows & Desktops page."
    ),
    "org.gnome.desktop.wm.preferences": (
        "The remaining rules for how windows open, focus and get out of the way."
    ),
    "org.gnome.mutter": (
        "How your desktop arranges windows: edge tiling, the way one screen "
        "becomes several, and how many desktops it keeps."
    ),
    "org.gnome.mutter.wayland": (
        "How older apps, written before your desktop worked the way it does now, "
        "are allowed to behave."
    ),
    "org.gnome.settings-daemon.plugins.color": (
        "The rest of the evening-warmth settings, including the position your "
        "computer worked out for sunset."
    ),
    "org.gnome.settings-daemon.plugins.media-keys": (
        "What the volume, brightness and play keys on your keyboard do. Press a "
        "row and then press the keys you want to use."
    ),
    "org.gnome.settings-daemon.plugins.xsettings": (
        "Settings that only older apps read. Modern apps ignore every one of them."
    ),
    "org.gnome.shell": (
        "Bits of the bar at the top and the app view that gtheme has not given a "
        "plainer name to."
    ),
    "org.gnome.system.location": (
        "Whether your computer may work out roughly where it is, which is what the "
        "evening warmth uses to find your sunset."
    ),
}

#: Settings groups whose text values are key combinations. Their rows get the
#: capture dialog rather than a box to type into: a shortcut is *pressed*, not
#: spelled.
KEYBINDING_SCHEMAS: tuple[str, ...] = (
    "org.gnome.settings-daemon.plugins.media-keys",
    "org.gnome.desktop.wm.keybindings",
    "org.gnome.mutter.keybindings",
    "org.gnome.shell.keybindings",
)


@dataclass(frozen=True)
class FloorKey:
    """One setting the floor draws, and how it decided to draw it.

    Args:
        schema_id: the part of the desktop it belongs to.
        key: the setting's own name.
        row: a descriptor built from the desktop's own words, or None when
            this is a value gtheme can show but must not offer to edit.
        title: what the row is headed, after translation.
        subtitle: the desktop's own explanation, after translation.
    """

    schema_id: str
    key: str
    title: str
    subtitle: str
    row: Row | None = None

    @property
    def id(self) -> str:
        return f"{self.schema_id}:{self.key}"


def humanise(key: str) -> str:
    """``show-battery-percentage`` becomes ``Show battery percentage``.

    The fallback for a setting whose own definition has no summary. Better than
    the raw name, and honest about being a machine translation of one.
    """
    words = key.replace("_", "-").split("-")
    if not words:
        return key
    return " ".join([words[0].capitalize(), *words[1:]])


def _key_metadata(probe: Any, schema_id: str, key: str) -> Any | None:
    """The desktop's own definition of one setting, or None if it has none."""
    try:
        schema = probe.lookup(schema_id)
    except Exception:  # noqa: BLE001 - a lookup must never take the page down
        return None
    if schema is None or not schema.has_key(key):
        return None
    try:
        return schema.get_key(key)
    except Exception:  # noqa: BLE001 - defensive
        return None


def _range_of(meta: Any) -> tuple[str, Any]:
    """``(kind, payload)`` of a setting's allowed values.

    ``kind`` is ``"enum"``, ``"flags"``, ``"range"`` or ``"type"`` — the four
    answers GSettings gives. ``"type"`` means "anything of the right shape",
    which is the usual answer and the one that decides nothing.
    """
    try:
        variant = meta.get_range()
        return variant.get_child_value(0).get_string(), variant.get_child_value(1).get_variant()
    except Exception:  # noqa: BLE001 - defensive
        return "type", None


def _choice_label(value: Any) -> str:
    """A readable label for one allowed value of a pick-one setting."""
    text = str(value)
    return jargon.translate(humanise(text.replace(".", "-")))


def floor_keys(
    probe: Any,
    *,
    ids: list[str] | None = None,
    corpus: corpus_loader.Corpus | None = None,
) -> list[FloorKey]:
    """Draw a row for every setting nobody wrote a description for.

    The desktop's own summary becomes the title and its own description the
    explanation, both passed through the plain-language translator. What kind
    of control to use is decided from the setting itself — its type and the
    values it will accept — rather than from anything committed here, so a
    setting that changes shape in a future GNOME draws itself correctly instead
    of drawing itself wrongly.
    """
    wanted = ids if ids is not None else floor_ids(corpus=corpus)
    drawn: list[FloorKey] = []
    for descriptor_id in wanted:
        schema_id, _, key = descriptor_id.partition(":")
        if not key:
            continue
        meta = _key_metadata(probe, schema_id, key)
        summary = (meta.get_summary() if meta is not None else None) or humanise(key)
        description = (meta.get_description() if meta is not None else None) or ""
        title = jargon.translate(summary).strip()
        subtitle = jargon.translate(description).strip() or COPY["system-text"]
        drawn.append(
            FloorKey(
                schema_id=schema_id,
                key=key,
                title=title,
                subtitle=subtitle,
                row=_floor_row(schema_id, key, title, subtitle, meta),
            )
        )
    return drawn


def _floor_row(
    schema_id: str, key: str, title: str, subtitle: str, meta: Any
) -> Row | None:
    """A descriptor for a floor setting, or None when it must stay read-only."""
    if meta is None:
        return None
    try:
        type_string = meta.get_value_type().dup_string()
    except Exception:  # noqa: BLE001 - defensive
        return None
    kind_of_range, payload = _range_of(meta)

    common: dict[str, Any] = {
        "schema_id": schema_id,
        "key": key,
        "title": title,
        "subtitle": subtitle,
        "synonyms": [key.replace("-", " ")],
        "advanced": False,
        "reset": True,
    }

    if kind_of_range == "enum" and payload is not None:
        values = list(payload.unpack() or ())
        if values:
            return Row(
                **common,
                kind=WidgetKind.CHOICE,
                choices=[
                    Choice(value=_variant_text(type_string, value), label=_choice_label(value))
                    for value in values
                ],
            )
        return None
    if type_string == "b":
        return Row(**common, kind=WidgetKind.TOGGLE)
    if type_string == "as" and schema_id in KEYBINDING_SCHEMAS:
        return Row(**common, kind=WidgetKind.SHORTCUT)
    if type_string in ("i", "u", "d") and kind_of_range == "range" and payload is not None:
        low, high = payload.unpack()
        return Row(
            **common,
            kind=WidgetKind.SLIDER,
            clamp_min=float(low),
            clamp_max=float(high),
            step=1 if type_string in ("i", "u") else 0.1,
        )
    if type_string == "s":
        return Row(**common, kind=WidgetKind.TEXT)
    # Lists of app names, coordinates, dictionaries. Shown, never edited here.
    return None


def _variant_text(type_string: str, value: Any) -> str:
    """The stored form of one allowed value. Strings are quoted, numbers not."""
    if type_string == "s" or isinstance(value, str):
        return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"
    return str(value)


def missing_explainers(schemas: list[str], domains: list[str]) -> list[str]:
    """Groups that would appear on this page with nothing said about them.

    Every group on the floor page carries a hand-written sentence. This is what
    a test asks, because the failure it guards against — a heading with forty
    switches under it and no word of explanation — is invisible in a diff and
    obvious to the person who has to use it.
    """
    problems = [
        f"{schema}: no group explanation"
        for schema in sorted(set(schemas))
        if schema not in SCHEMA_EXPLAINERS or schema not in SCHEMA_TITLES
    ]
    problems += [
        f"{domain}: no group explanation"
        for domain in sorted(set(domains))
        if domain not in GROUP_EXPLAINERS
    ]
    return problems


# ---------------------------------------------------------------------------
# the page
# ---------------------------------------------------------------------------


def build(window: Any, *, backend: Any = None, probe: SchemaProbe | None = None) -> Any:
    """The More Settings page.

    Args:
        window: the application window.
        backend: the settings backend. Defaults to the app's.
        probe: the window's schema probe. Also what reads the desktop's own
            descriptions of the floor settings.
    """
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk

    settings = backend if backend is not None else get_backend()
    scanner = probe if probe is not None else SchemaProbe()
    prefs = getattr(window, "prefs", None)
    corpus = corpus_loader.load_corpus()

    page = Adw.PreferencesPage(vexpand=True)
    built: list[tuple[Row, Any]] = []
    #: ``(widget, haystack, owner)`` for the local filter.
    filterable: list[tuple[Any, str, Any]] = []
    groups: list[Any] = []

    # -- the parts somebody did write descriptions for.
    authored = {row.id: row for row in page_rows(PAGE_ID, corpus=corpus)}
    for domain in corpus.domains:
        rows = [row for row in domain.rows if row.id in authored]
        if not rows:
            continue
        group = Adw.PreferencesGroup(
            title=escape_markup(domain.title),
            description=escape_markup(GROUP_EXPLAINERS.get(domain.id, "")),
        )
        ordinary = [row for row in rows if not row.advanced]
        advanced = [row for row in rows if row.advanced]
        made = build_indexed_rows(
            window, PAGE_ID, ordinary, backend=settings, probe=scanner, into=group
        )
        if advanced:
            expander = Adw.ExpanderRow(
                title=escape_markup(ADVANCED_TITLE),
                subtitle=escape_markup(ADVANCED_SUBTITLE),
            )
            made += build_indexed_rows(
                window, PAGE_ID, advanced, backend=settings, probe=scanner, into=expander
            )
            group.add(expander)
        built += made
        for row, widget in made:
            filterable.append((widget, row_search_text(row), group))
        page.add(group)
        groups.append(group)

    # -- the floor itself.
    # Which groups hold which other groups, for the filter. The floor's own
    # heading and blurb are a group whose children are groups, and only its
    # children were ever hidden — so a search matching nothing in the floor
    # left "Described by your desktop" and its three-line explanation sitting
    # over an empty space (review-report L5).
    nested: dict[int, list[Any]] = {}
    floor = floor_keys(scanner, corpus=corpus)
    if floor:
        group = Adw.PreferencesGroup(
            title=escape_markup(COPY["floor-title"]),
            description=escape_markup(COPY["floor-description"]),
        )
        nested[id(group)] = []
        for schema_id in sorted({entry.schema_id for entry in floor}):
            expander = Adw.ExpanderRow(
                title=escape_markup(
                    SCHEMA_TITLES.get(schema_id, humanise(schema_id.rsplit(".", 1)[-1]))
                ),
                subtitle=escape_markup(SCHEMA_EXPLAINERS.get(schema_id, COPY["system-text"])),
            )
            for entry in [e for e in floor if e.schema_id == schema_id]:
                widget = _floor_widget(window, entry, settings, scanner, expander, built)
                if widget is not None:
                    filterable.append((widget, f"{entry.title} {entry.subtitle} {entry.key}".lower(), expander))
            group.add(expander)
            groups.append(expander)
            nested[id(group)].append(expander)
        page.add(group)
        groups.append(group)

    probe_built_rows(page, scanner, built, backend=settings)

    header = _filter_bar(Gtk, Adw, filterable, groups, nested)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, vexpand=True)
    if prefs is not None and prefs.should_show_banner("first-visit-more"):
        box.append(_banner(Adw, prefs))
    box.append(header)
    box.append(page)
    return box


def _banner(Adw: Any, prefs: Any) -> Any:
    from ..search import BANNER_DISMISS

    banner = Adw.Banner(
        title=escape_markup(COPY["banner"]), button_label=BANNER_DISMISS, revealed=True
    )

    def dismiss(*_args: Any) -> None:
        banner.set_revealed(False)
        prefs.mark_banner_seen("first-visit-more")

    banner.connect("button-clicked", dismiss)
    return banner


def _floor_widget(
    window: Any,
    entry: FloorKey,
    backend: Any,
    probe: Any,
    expander: Any,
    built: list[tuple[Row, Any]],
) -> Any:
    """One floor row, editable or not, registered either way."""
    if entry.row is not None:
        made = build_indexed_rows(
            window, PAGE_ID, [entry.row], backend=backend, probe=probe, into=expander
        )
        if made:
            built.extend(made)
            return made[0][1]
        return None
    return _readonly_row(window, entry, backend, expander)


def _readonly_row(window: Any, entry: FloorKey, backend: Any, expander: Any) -> Any:
    """A setting gtheme shows and does not offer to change.

    Some values are lists of app names, a pair of coordinates, or a dictionary.
    A text box over one of those is a way to break the desktop by typing, and
    hiding it would make "nothing was left out" false. So it is shown, with the
    value, and it says plainly that it is not editable here.
    """
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk, Pango

    from ..widgets.rows import key_for

    row = Adw.ActionRow(
        title=escape_markup(entry.title),
        subtitle=escape_markup(f"{entry.subtitle} {COPY['not-editable']}"),
    )
    label = Gtk.Label(
        css_classes=["dim-label", "numeric"],
        valign=Gtk.Align.CENTER,
        max_width_chars=28,
        ellipsize=Pango.EllipsizeMode.END,
    )
    row.add_suffix(label)
    key = key_for(
        Row(
            schema_id=entry.schema_id,
            key=entry.key,
            title=entry.title,
            subtitle=entry.subtitle,
            kind=WidgetKind.TEXT,
        )
    )

    def refresh() -> None:
        try:
            label.set_text(backend.get(key))
        except BackendError:
            label.set_text("")
            row.set_subtitle(escape_markup(COPY["unreadable"]))

    refresh()
    expander.add_row(row)
    index = getattr(window, "rows", None)
    if index is not None:
        index.register(
            PAGE_ID,
            entry.id,
            row,
            refresh=refresh,
            search_text=f"{entry.title} {entry.subtitle}",
        )
    return row


def _filter_bar(
    Gtk: Any,
    Adw: Any,
    filterable: list[tuple[Any, str, Any]],
    groups: list[Any],
    nested: dict[int, list[Any]] | None = None,
) -> Any:
    """A box that narrows two hundred rows to the ones being looked for.

    The app-wide Ctrl+F search takes a person to a row on any page; this is the
    other half — once you are *on* the page with two hundred rows, you need to
    narrow it without leaving.

    Args:
        filterable: ``(widget, haystack, owner)`` per row; the owner is the
            group whose count that row is part of.
        groups: everything that hides when nothing inside it matches.
        nested: which of those groups hold other groups, so a heading over
            twenty-eight closed expanders hides when every one of them does.
    """
    holds = nested or {}
    entry = Gtk.SearchEntry(
        search_delay=150,
        placeholder_text=COPY["search-placeholder"],
        hexpand=True,
        margin_top=12,
        margin_bottom=6,
        margin_start=18,
        margin_end=18,
    )

    def apply_filter(*_args: Any) -> None:
        needle = entry.get_text().strip().lower()
        shown: dict[int, int] = {}
        for widget, haystack, owner in filterable:
            visible = not needle or needle in haystack
            widget.set_visible(visible)
            shown[id(owner)] = shown.get(id(owner), 0) + (1 if visible else 0)
        for group in groups:
            matched = shown.get(id(group), 0) + sum(
                shown.get(id(child), 0) for child in holds.get(id(group), ())
            )
            group.set_visible(bool(matched))
            if needle and hasattr(group, "set_expanded"):
                group.set_expanded(bool(matched))

    entry.connect("search-changed", apply_filter)
    clamp = Adw.Clamp(maximum_size=640, child=entry)
    return clamp
