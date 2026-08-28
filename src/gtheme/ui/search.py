"""The app's index: everything gtheme can show, joined in one place.

Two jobs live here, and they are one job seen from two sides.

**The join.** A page does not decide which settings it owns. ``ui.registry``
names the fifteen pages, ``data/domains/coverage.toml`` dispositions every
setting of the desktop onto one of them, and the descriptor corpus under
``data/domains/`` and ``data/panels/`` holds the rows themselves. Putting those
three together is :func:`page_rows`, and every page in the System section asks
it rather than listing its own settings — which is what makes adding a setting
to a page a data edit instead of a code edit.

**The search.** competitor-ux P7: one field, Ctrl+F, that matches setting
names, their plain-language explanations, the *synonyms a Windows or macOS
switcher would type* ("taskbar", "start menu", "make text bigger"), the page
names, the Looks and the add-ons — and then takes you to the exact row and
flashes it. For a person who does not know the app's structure, that removes
the need to know it at all.

The two are the same job because a row is findable only if it was indexed when
it was built. :func:`build_indexed_rows` is that seam: it builds a descriptor
row through the one blessed builder, registers it in the window's
:class:`~gtheme.ui.rowindex.RowIndex`, and hands back the widgets so the schema
probe can grey the ones this computer cannot honour.

GTK is imported lazily, inside the functions that draw. The join and the index
are ordinary data and are tested without a display.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..panels import loader as corpus_loader
from ..panels.descriptor import Row, WidgetKind
from . import registry

__all__ = [
    "ADVANCED_SUBTITLE",
    "ADVANCED_TITLE",
    "BANNER_DISMISS",
    "FLASH_CSS_CLASS",
    "FLASH_MILLISECONDS",
    "PANEL_ROW_SUBTITLE",
    "GroupSpec",
    "Hit",
    "SearchIndex",
    "build_indexed_rows",
    "build_search_dialog",
    "coverage_dispositions",
    "escape_markup",
    "flash",
    "floor_ids",
    "install_search",
    "page_rows",
    "present_search",
    "probe_built_rows",
    "row_search_text",
    "settings_page",
    "surfaced_ids",
]


# ---------------------------------------------------------------------------
# the join: coverage.toml -> pages -> rows
# ---------------------------------------------------------------------------

# The coverage manifest and the joins it feeds live in :mod:`gtheme.panels
# .loader` — the module that already owns reading the descriptor corpus off
# disk, and now owns reading the one file that says what each key of it is
# for. Re-exported here because this is where pages import them from and
# there is no second meaning of the names.
COVERAGE_FILENAME = corpus_loader.COVERAGE_FILENAME
coverage_dispositions = corpus_loader.load_dispositions
surfaced_ids = corpus_loader.surfaced_ids
page_rows = corpus_loader.page_rows
floor_ids = corpus_loader.floor_ids


def escape_markup(text: str) -> str:
    """Make text safe to hand a widget that renders it as markup.

    Titles and explanations on ``Adw`` rows, groups and banners go through
    Pango's markup parser, so an ampersand in "Mouse, Touchpad & Keyboard" or
    in a description the *system* wrote makes the widget silently render
    nothing at all — a heading that vanishes, with a warning on a console the
    user will never see. Every string this app puts into one of those goes
    through here first.
    """
    from gi.repository import GLib

    return GLib.markup_escape_text(text or "")


def row_search_text(row: Row) -> str:
    """Title, subtitle and synonyms of a row, joined for substring matching."""
    parts = [row.title, row.subtitle, *row.synonyms]
    if row.kind is WidgetKind.CHOICE:
        parts.extend(choice.label for choice in row.choices)
    return " ".join(part for part in parts if part).lower()


# ---------------------------------------------------------------------------
# the index
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Hit:
    """One thing the search box can find.

    Args:
        kind: ``"setting"``, ``"page"``, ``"look"`` or ``"add-on"``. Shown as
            the small label on the right of a result, so a person can tell a
            setting from a whole Look at a glance.
        title: what the result is called.
        subtitle: one line of context underneath.
        page_id: which page to open. Always set.
        descriptor_id: which row to scroll to and flash, when the hit is a row.
        haystack: everything matchable, lowercased. Built once.
    """

    kind: str
    title: str
    subtitle: str
    page_id: str
    descriptor_id: str | None = None
    haystack: str = ""

    def matches(self, needle: str) -> bool:
        return needle in self.haystack

    def rank(self, needle: str) -> tuple[int, int, str]:
        """Sort key: title matches first, earlier matches first, then by name.

        Someone typing "dark" wants the dark-mode row before a row whose
        *explanation* happens to mention the word dark.
        """
        title = self.title.lower()
        if title.startswith(needle):
            bucket = 0
        elif needle in title:
            bucket = 1
        else:
            bucket = 2
        position = title.find(needle)
        return (bucket, position if position >= 0 else 9999, title)


#: What a page result says underneath itself when the manifest has no subtitle.
PAGE_SUBTITLE_FALLBACK = "A page of this app."

#: What a setting that belongs to an add-on says underneath itself. Its own
#: controls live behind that add-on's settings button on the Add-ons page, so
#: the result says which add-on to open rather than pretending it can land on
#: the control itself.
PANEL_ROW_SUBTITLE = "A setting of the {name} add-on."


@dataclass
class SearchIndex:
    """Everything findable, as a flat list of :class:`Hit`.

    Built once and reused. Rebuilding on every keystroke would mean reading the
    Looks off disk sixty times a second; the index is cheap to keep and the
    things in it (which settings exist, which Looks are installed) change only
    when the user does something that rebuilds the page anyway.
    """

    hits: list[Hit] = field(default_factory=list)

    def search(self, text: str, *, limit: int = 60) -> list[Hit]:
        """Results for what has been typed so far, best first.

        Empty text gives no results rather than everything: a list of four
        hundred settings is not an answer to a question nobody asked yet.
        """
        needle = text.strip().lower()
        if not needle:
            return []
        found = [hit for hit in self.hits if hit.matches(needle)]
        found.sort(key=lambda hit: hit.rank(needle))
        return found[:limit]

    def __len__(self) -> int:
        return len(self.hits)

    # -- building ----------------------------------------------------------

    @classmethod
    def build(
        cls,
        *,
        corpus: corpus_loader.Corpus | None = None,
        dispositions: dict[str, str] | None = None,
        looks: Iterable[Any] | None = None,
    ) -> SearchIndex:
        """Index the settings, the pages, the Looks and the add-ons.

        Args:
            corpus: the descriptor corpus. Loaded from disk when omitted.
            dispositions: the coverage manifest. Read from disk when omitted.
            looks: ``LoadResult`` objects from ``preset.loader``. Loaded from
                disk when omitted; pass ``()`` to leave Looks out entirely,
                which is what a test that does not care about them does.
        """
        loaded = corpus if corpus is not None else corpus_loader.load_corpus()
        given = coverage_dispositions() if dispositions is None else dispositions
        hits: list[Hit] = []

        # -- pages. Findable by name, because "where is the wallpaper" is a
        # question people ask before they know what a setting is.
        for page in registry.MANIFEST:
            subtitle = page.subtitle or PAGE_SUBTITLE_FALLBACK
            hits.append(
                Hit(
                    kind="page",
                    title=page.title,
                    subtitle=subtitle,
                    page_id=page.id,
                    haystack=f"{page.title} {subtitle} {page.section}".lower(),
                )
            )

        # -- settings on a named page, or on the floor.
        try:
            resolved = registry.resolve_surfaced(given)
        except ValueError:
            # The manifest and the data disagree. Losing search entirely over
            # it would be a worse answer than searching everything else.
            resolved = {}
        page_of = {
            descriptor_id: page_id
            for page_id, ids in resolved.items()
            for descriptor_id in ids
        }
        for domain in loaded.domains:
            for row in domain.rows:
                page_id = page_of.get(row.id)
                if page_id is None:
                    continue
                hits.append(
                    Hit(
                        kind="setting",
                        title=row.title,
                        subtitle=row.subtitle,
                        page_id=page_id,
                        descriptor_id=row.id,
                        haystack=row_search_text(row),
                    )
                )

        # -- add-ons, and every setting a curated add-on offers. These are not
        # in the coverage manifest at all — an add-on's settings are not part
        # of the desktop's own — so they are indexed straight onto the Add-ons
        # page, which is where their controls live.
        for panel in loaded.panels:
            name = _addon_name(panel.id)
            hits.append(
                Hit(
                    kind="add-on",
                    title=name,
                    subtitle=panel.target.summary,
                    page_id="addons",
                    haystack=f"{name} {panel.target.summary} {panel.target.category}".lower(),
                )
            )
            # No descriptor_id on these. An add-on's settings are built inside
            # that add-on's own panel, which is a dialog that is not open when
            # a search result lands — so the row is in no row index and there
            # is nothing to scroll to or flash. Claiming otherwise gave a hit
            # that opened the Add-ons list and then did nothing at all. The
            # setting stays findable; what it says instead is where it lives.
            for row in panel.rows:
                hits.append(
                    Hit(
                        kind="setting",
                        title=row.title,
                        subtitle=PANEL_ROW_SUBTITLE.format(name=name),
                        page_id="addons",
                        haystack=f"{row_search_text(row)} {name.lower()}",
                    )
                )

        for result in _looks(looks):
            preset = getattr(result, "preset", None)
            if preset is None:
                continue
            meta = preset.meta
            hits.append(
                Hit(
                    kind="look",
                    title=meta.title,
                    subtitle=meta.description,
                    page_id="looks",
                    haystack=f"{meta.title} {meta.name} {meta.description}".lower(),
                )
            )

        return cls(hits=hits)


def _looks(given: Iterable[Any] | None) -> list[Any]:
    if given is not None:
        return list(given)
    try:
        from ..preset import loader as preset_loader

        return preset_loader.load_all()
    except Exception:  # noqa: BLE001 - a broken Look must not break search
        return []


def _addon_name(panel_id: str) -> str:
    """A display name for a curated add-on, from its panel id.

    These are other people's product names — "Blur My Shell", "Just Perfection"
    — and they are shown as their authors spell them. The plain-language lint
    is about the words *gtheme* chooses; renaming somebody's add-on would make
    it unfindable by the name printed on its own page.
    """
    return " ".join(part.capitalize() for part in panel_id.replace("_", "-").split("-"))


# ---------------------------------------------------------------------------
# building rows into a page, and indexing them as they go
# ---------------------------------------------------------------------------


def build_indexed_rows(
    window: Any,
    page_id: str,
    rows: Sequence[Row],
    *,
    backend: Any,
    probe: Any | None = None,
    into: Any = None,
    on_unsupported: Callable[[Row, Exception], Any] | None = None,
) -> list[tuple[Row, Any]]:
    """Build descriptor rows, add them somewhere, and register every one.

    Args:
        window: the application window. Its ``rows`` index is where the built
            widgets are registered so search, deep links and live mirroring can
            find them again. Anything without a ``rows`` attribute is accepted
            and simply not indexed, which is what lets a test call this with a
            stand-in.
        page_id: the page these rows belong to.
        rows: the descriptors, in the order they should appear.
        backend: the settings backend. Never constructed here — a page is
            handed one, so a test can hand it a memory backend.
        probe: the window's one schema probe, so a setting this computer does
            not have becomes a greyed row that says why.
        into: something with ``add()`` (an ``Adw.PreferencesGroup``) or
            ``add_row()`` (an ``Adw.ExpanderRow``). Omitted, the widgets are
            built and returned without being placed.
        on_unsupported: called with ``(row, error)`` for a descriptor kind that
            has no widget, and its return value is used as the widget. Omitted,
            such a row is skipped — silently dropping a control is worse than
            an honest stand-in, so pages that can produce one pass this.

    Returns:
        ``[(row, widget)]`` for everything that was built, in order.
    """
    from ..panels.widgets import build_row
    from ..ui.widgets.rows import UnsupportedRowKind

    index = getattr(window, "rows", None)
    built: list[tuple[Row, Any]] = []
    for row in rows:
        try:
            widget, refresh = build_row(backend, row, probe=probe)
        except UnsupportedRowKind as exc:
            replacement = on_unsupported(row, exc) if on_unsupported is not None else None
            if replacement is None:
                continue
            widget, refresh = replacement, None
        except Exception:  # noqa: BLE001 - one bad row must not empty a page
            continue
        _place(into, widget)
        if index is not None:
            index.register(
                page_id,
                row.id,
                widget,
                refresh=refresh,
                search_text=row_search_text(row),
            )
        built.append((row, widget))
    return built


def _place(into: Any, widget: Any) -> None:
    if into is None:
        return
    adder = getattr(into, "add", None) if hasattr(into, "add") else None
    if adder is None:
        adder = getattr(into, "add_row", None)
    if adder is not None:
        adder(widget)


def probe_built_rows(
    widget: Any,
    probe: Any,
    built: Sequence[tuple[Row, Any]],
    *,
    backend: Any = None,
) -> int | None:
    """Check the built rows on idle time and grey the unavailable ones.

    Rows are built first and checked afterwards (the Refine pattern), so
    opening a page is never delayed by reading directories off disk. The idle
    source is removed when the page goes away, because a callback that outlives
    its widgets is a crash waiting for a slow computer.

    Args:
        backend: handed straight to the probe. An add-on that keeps its
            settings in a file of its own cannot say which file is in use
            without one, so the probe answers the pessimistic way and greys a
            row that works. This used to be accepted here and quietly dropped,
            which made every caller that passed one wrong in the same way.

    Returns the GLib source id, or None when there was nothing to probe.
    """
    if probe is None or not built:
        return None
    from gi.repository import GLib

    from ..panels.schema_probe import probe_rows_idle

    by_id = {row.id: built_widget for row, built_widget in built}

    def on_result(row: Row, availability: Any) -> None:
        target = by_id.get(row.id)
        if target is None or availability.ok:
            return
        # The row was built optimistically and this computer cannot honour it.
        # Insensitive and saying why beats a control that writes into nothing.
        target.set_sensitive(False)
        if hasattr(target, "set_subtitle") and availability.reason:
            target.set_subtitle(availability.reason)

    holder: dict[str, int | None] = {"source": None}

    def finished() -> None:
        # The idle source removes itself when it runs out of rows. Forgetting
        # it here is what stops the teardown below from removing a source id
        # that has already gone — which is a warning on every page close.
        holder["source"] = None

    holder["source"] = probe_rows_idle(
        probe,
        [row for row, _ in built],
        on_result,
        backend=backend,
        on_done=finished,
    )

    def stop(*_args: Any) -> None:
        if holder["source"] is not None:
            GLib.source_remove(holder["source"])
            holder["source"] = None

    if hasattr(widget, "connect"):
        widget.connect("destroy", stop)
    return holder["source"]


#: The heading a page puts its rarely-wanted rows behind. Every descriptor
#: marked ``advanced`` in the corpus goes here, collapsed, on every page —
#: competitor-ux P8, and one wording so the tier means the same thing
#: everywhere.
ADVANCED_TITLE = "More options"
ADVANCED_SUBTITLE = "Settings most people never need to change."

#: What the dismiss button on a first-visit explainer says. One word for the
#: same button on all eleven of them.
#:
#: These three live here, in the module with no toolkit import, because they are
#: the app's *standing wording* rather than any one page's: the plain-language
#: lint already reads this module, and both page scaffolds and the shared
#: explainer widget take them from here. The scaffolds each used to carry their
#: own copy of the first two — both copies documented as "one wording so the
#: tier means the same thing everywhere" — and a third page hardcoded a fourth
#: (review-report M29).
BANNER_DISMISS = "Got it"


@dataclass(frozen=True)
class GroupSpec:
    """One headed group of rows on an ordinary settings page.

    Args:
        title: the heading. Plain language.
        description: one line under the heading saying what the group is for.
            Not optional in practice — a group of switches with no explanation
            is the Tweaks failure mode this app exists to replace.
        rows: the descriptors, in the order they should appear. Rows marked
            ``advanced`` are pulled out into a collapsed expander at the foot
            of the group, wherever they sit in this list.
    """

    title: str
    description: str
    rows: Sequence[Row] = ()


def settings_page(
    window: Any,
    page_id: str,
    groups: Sequence[GroupSpec],
    *,
    backend: Any,
    probe: Any = None,
    banner: tuple[str, str] | None = None,
    prefs: Any = None,
    on_unsupported: Callable[[Row, Exception], Any] | None = None,
    top: Sequence[Any] = (),
    extra: Sequence[Any] = (),
) -> Any:
    """An ordinary settings page: headed groups of descriptor rows, indexed.

    Three pages of the System section are exactly this and nothing else, and
    building them from one function is what keeps the promises identical: every
    control has an explanation, every ``advanced`` row is behind the same
    collapsed heading with the same wording, every row is registered so search
    can find it, and every row that this computer cannot honour greys itself
    and says why after the page is already on screen.

    Args:
        window: the application window.
        page_id: the page being built, from ``ui.registry``.
        groups: the headed groups, in order.
        backend: the settings backend. Handed in, never constructed here.
        probe: the window's one schema probe.
        banner: ``(banner_id, text)`` for the one-shot first-visit explainer.
            Shown only while ``prefs`` says it has not been dismissed.
        prefs: the app preferences, for the banner's dismissed state.
        on_unsupported: see :func:`build_indexed_rows`.
        top: widgets placed above the groups — a consequence banner belongs
            here, where it is read before the control it is about.
        extra: widgets appended after the groups — a page-specific card that is
            not a descriptor row.

    Returns:
        The page widget, ready to be shown.
    """
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw

    page = Adw.PreferencesPage(vexpand=True)
    built: list[tuple[Row, Any]] = []

    def add(widget: Any) -> None:
        # A preferences page holds groups and nothing else, so anything that is
        # not one gets a group of its own rather than a TypeError at run time.
        page.add(
            widget
            if isinstance(widget, Adw.PreferencesGroup)
            else _in_a_group(Adw, widget)
        )

    for widget in top:
        add(widget)

    for spec in groups:
        ordinary = [row for row in spec.rows if not row.advanced]
        advanced = [row for row in spec.rows if row.advanced]
        if not ordinary and not advanced:
            continue
        group = Adw.PreferencesGroup(
            title=escape_markup(spec.title),
            description=escape_markup(spec.description),
        )
        built += build_indexed_rows(
            window,
            page_id,
            ordinary,
            backend=backend,
            probe=probe,
            into=group,
            on_unsupported=on_unsupported,
        )
        if advanced:
            expander = Adw.ExpanderRow(
                title=escape_markup(ADVANCED_TITLE),
                subtitle=escape_markup(ADVANCED_SUBTITLE),
            )
            built += build_indexed_rows(
                window,
                page_id,
                advanced,
                backend=backend,
                probe=probe,
                into=expander,
                on_unsupported=on_unsupported,
            )
            group.add(expander)
        page.add(group)

    for widget in extra:
        add(widget)

    probe_built_rows(page, probe, built, backend=backend)

    if banner is None:
        return page
    banner_id, text = banner
    from .widgets.explainer import with_first_visit_banner

    return with_first_visit_banner(page, prefs, banner_id, text)


def _in_a_group(Adw: Any, widget: Any) -> Any:
    group = Adw.PreferencesGroup()
    group.add(widget)
    return group


# ---------------------------------------------------------------------------
# the overlay
# ---------------------------------------------------------------------------

#: The style class a deep-linked row wears for a moment so the eye finds it.
FLASH_CSS_CLASS = "accent"
#: How long it wears it. Long enough to see, short enough not to look broken.
FLASH_MILLISECONDS = 1400

#: Everything the overlay says, in one place so the plain-language lint can
#: read it and so no sentence is written twice in two ways.
COPY: dict[str, str] = {
    "title": "Search",
    "placeholder": "Search for anything — “make text bigger”, “dark”, “taskbar”",
    "empty-title": "Nothing matched",
    "empty-body": "Try a different word. You can search for what you want to change, not only what it is called.",
    "start-title": "What are you looking for?",
    "start-body": "Type what you want to change. Everything in this app is searchable, including the explanations.",
}

#: What the small label on the right of a result says, by hit kind.
KIND_LABELS: dict[str, str] = {
    "setting": "Setting",
    "page": "Page",
    "look": "Look",
    "add-on": "Add-on",
}


def flash(window: Any, descriptor_id: str) -> bool:
    """Draw the eye to one row. Returns whether the row was on screen.

    The row index is what makes this possible: a search result knows a
    descriptor id, and the index turns that back into the widget that was
    actually built.
    """
    index = getattr(window, "rows", None)
    if index is None:
        return False
    entry = index.lookup(descriptor_id)
    if entry is None or entry.widget is None:
        return False
    from gi.repository import GLib

    widget = entry.widget
    widget.add_css_class(FLASH_CSS_CLASS)
    if hasattr(widget, "grab_focus"):
        widget.grab_focus()

    def unflash() -> bool:
        widget.remove_css_class(FLASH_CSS_CLASS)
        return GLib.SOURCE_REMOVE

    GLib.timeout_add(FLASH_MILLISECONDS, unflash)
    return True


def build_search_dialog(
    window: Any,
    *,
    index: SearchIndex | None = None,
    on_activate: Callable[[str, str | None], None] | None = None,
) -> Any:
    """The search overlay, built and wired but not yet shown.

    Separate from :func:`present_search` so it can be constructed and driven in
    a test without a window ever being mapped — which is the rule this whole
    suite is run under, because the desktop being customised is the one the
    tests run on.

    Args:
        window: the application window. Also the default navigator: with no
            ``on_activate`` given, a result opens the page through
            ``window.show_page`` and flashes the row through
            :func:`flash`.
        index: the index to search. Built from disk when omitted.
        on_activate: ``(page_id, descriptor_id) -> None``, called when a result
            is chosen. This is the seam the integration wave fills in with real
            navigation; everything else about the overlay is finished.
    """
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk

    built_index = index if index is not None else SearchIndex.build()
    navigate = on_activate if on_activate is not None else _default_navigator(window)

    dialog = Adw.Dialog(title=COPY["title"], content_width=560, content_height=560)

    entry = Gtk.SearchEntry(
        search_delay=120,
        placeholder_text=COPY["placeholder"],
        hexpand=True,
    )
    header = Adw.HeaderBar(title_widget=entry)

    results = Gtk.ListBox(
        selection_mode=Gtk.SelectionMode.NONE,
        css_classes=["boxed-list"],
        valign=Gtk.Align.START,
    )
    scroller = Gtk.ScrolledWindow(
        hexpand=True,
        vexpand=True,
        child=Adw.Clamp(maximum_size=520, margin_top=12, margin_bottom=12, child=results),
    )
    empty = Adw.StatusPage(
        icon_name="system-search-symbolic",
        title=COPY["start-title"],
        description=COPY["start-body"],
        vexpand=True,
    )
    stack = Gtk.Stack()
    stack.add_named(empty, "empty")
    stack.add_named(scroller, "results")
    stack.set_visible_child_name("empty")

    view = Adw.ToolbarView(content=stack)
    view.add_top_bar(header)
    dialog.set_child(view)

    def choose(hit: Hit) -> None:
        dialog.close()
        navigate(hit.page_id, hit.descriptor_id)

    def rebuild(*_args: Any) -> None:
        while (child := results.get_first_child()) is not None:
            results.remove(child)
        text = entry.get_text()
        found = built_index.search(text)
        if not found:
            empty.set_title(COPY["start-title"] if not text.strip() else COPY["empty-title"])
            empty.set_description(
                COPY["start-body"] if not text.strip() else COPY["empty-body"]
            )
            stack.set_visible_child_name("empty")
            return
        for hit in found:
            row = Adw.ActionRow(
                title=escape_markup(hit.title),
                subtitle=escape_markup(hit.subtitle),
                activatable=True,
            )
            row.add_suffix(
                Gtk.Label(
                    label=KIND_LABELS.get(hit.kind, hit.kind),
                    css_classes=["dim-label", "caption"],
                    valign=Gtk.Align.CENTER,
                )
            )
            row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            row.connect("activated", lambda _row, hit=hit: choose(hit))
            results.append(row)
        stack.set_visible_child_name("results")

    entry.connect("search-changed", rebuild)
    entry.connect("activate", lambda *_a: _activate_first(results))
    rebuild()

    dialog.gtheme_entry = entry
    dialog.gtheme_results = results
    dialog.gtheme_stack = stack
    return dialog


def present_search(
    window: Any,
    *,
    index: SearchIndex | None = None,
    on_activate: Callable[[str, str | None], None] | None = None,
) -> Any:
    """Open the search overlay over ``window``. Returns the dialog."""
    dialog = build_search_dialog(window, index=index, on_activate=on_activate)
    dialog.present(window)
    dialog.gtheme_entry.grab_focus()
    return dialog


def _activate_first(results: Any) -> None:
    """Enter in the search box takes the first result. Keyboard-only path."""
    first = results.get_first_child()
    if first is not None:
        first.emit("activated")


def _default_navigator(window: Any) -> Callable[[str, str | None], None]:
    def navigate(page_id: str, descriptor_id: str | None) -> None:
        show = getattr(window, "show_page", None)
        if show is not None:
            show(page_id)
        if descriptor_id:
            flash(window, descriptor_id)

    return navigate


def install_search(
    window: Any,
    *,
    index: SearchIndex | None = None,
    on_activate: Callable[[str, str | None], None] | None = None,
) -> Any:
    """Give a window Ctrl+F. Returns the controller, so it can be removed.

    Deliberately a plain widget-scoped shortcut rather than an app accelerator:
    the overlay belongs to a window, and a second window (there is only one
    today, but that is not a promise) should get its own.
    """
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk

    controller = Gtk.ShortcutController(scope=Gtk.ShortcutScope.MANAGED)
    controller.add_shortcut(
        Gtk.Shortcut(
            trigger=Gtk.ShortcutTrigger.parse_string("<Control>f"),
            action=Gtk.CallbackAction.new(
                lambda *_a: bool(present_search(window, index=index, on_activate=on_activate))
            ),
        )
    )
    window.add_controller(controller)
    return controller


#: Re-exported from the corpus loader: a page or a test that wants to point the
#: whole join at a fixture directory sets exactly this variable.
DATA_DIR_ENV = corpus_loader.DATA_DIR_ENV
