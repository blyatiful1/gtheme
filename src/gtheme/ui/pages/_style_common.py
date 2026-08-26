"""Shared scaffolding for the three "how it looks" pages.

Colours & Style, Icons & Pointer and Fonts & Text are one job split three ways:
each renders a handful of descriptor rows from ``data/domains/``, a few
hand-built controls the row library deliberately does not offer (a picker's
content comes from scanning the system, not from a setting), and one first-visit
explainer. Writing that scaffolding three times would mean three slightly
different answers to "what happens when the probe says a setting is missing",
which is exactly the kind of drift the frozen row library exists to prevent.

Nothing here is a second row library. :func:`~gtheme.panels.widgets.build_row`
builds every descriptor row; this module only decides where rows go, registers
them so search and live mirroring can find them again, and runs the idle probe
afterwards.

Three rules this module encodes once, for all three pages:

* **Rows are built first and probed afterwards.** Opening a page never waits on
  disk. The probe pass then greys anything that is not really there, with a
  sentence saying why — see :func:`~gtheme.panels.schema_probe.probe_rows_idle`.
* **The idle source is remembered and removed on teardown.** A page torn down
  mid-probe would otherwise leave a callback holding dead widgets.
* **Pickers are hand-built but not hand-rolled.** A picker still gets the same
  per-row "put this back" button every other row gets, through the public
  :func:`~gtheme.ui.widgets.rows.attach_reset`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ...core.backends import get_backend  # noqa: E402
from ...core.settings_backend import BackendError, SettingsBackend  # noqa: E402
from ...core.transaction import Op, Transaction, TransactionError  # noqa: E402
from ...panels.descriptor import Row  # noqa: E402
from ...panels.loader import load_corpus, load_dispositions  # noqa: E402
from ...panels.loader import surfaced_ids as loader_surfaced_ids  # noqa: E402
from ...panels.schema_probe import Availability, SchemaProbe, probe_rows_idle  # noqa: E402
from ...panels.widgets import build_row  # noqa: E402
from ..widgets.rows import RowBuildError, attach_reset, key_for  # noqa: E402

__all__ = [
    "ADVANCED_SUBTITLE",
    "ADVANCED_TITLE",
    "PageShell",
    "apply_ops",
    "corpus_rows",
    "coverage_dispositions",
    "get_probe",
    "search_text",
    "surfaced_ids",
    "unquote",
    "value_or_none",
]


#: The expander every page hides its rarely-wanted rows behind. One wording, so
#: a person who found it on one page recognises it on the next.
ADVANCED_TITLE = "More options"
ADVANCED_SUBTITLE = "Settings most people never need to change."


def unquote(variant_text: str) -> str:
    """Strip GVariant string quoting for display. ``"'x'"`` -> ``x``."""
    text = variant_text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        return text[1:-1]
    return text


def quote(text: str) -> str:
    """The GVariant text for a plain string."""
    return GLib.Variant("s", text).print_(True)


def value_or_none(backend: SettingsBackend, key: str) -> str | None:
    """Read a setting, or None when this computer does not have it.

    Every caller here wants "show what is there, and cope when nothing is" —
    never a traceback, and never a guess.
    """
    try:
        return backend.get(key)
    except BackendError:
        return None


def search_text(row: Row) -> str:
    """Title, subtitle and synonyms, joined for the row index's search."""
    return " ".join([row.title, row.subtitle, *row.synonyms])


# --------------------------------------------------------------------------
# the descriptor corpus, joined to the page manifest
# --------------------------------------------------------------------------


#: ``{descriptor_id: disposition}`` from ``data/domains/coverage.toml``. This
#: module used to carry its own reader for that file, character-for-character
#: the same as the one in ``ui.search``. One file, one reader.
coverage_dispositions = load_dispositions


def surfaced_ids(page_id: str, directory: Path | str | None = None) -> list[str]:
    """Every descriptor this page is responsible for showing.

    The join is the one DESIGN.md F8 froze: ``coverage.toml`` says which page a
    setting belongs on, ``ui.registry.resolve_surfaced`` inverts that into a
    per-page list, and the page renders what it is handed. A page therefore
    cannot quietly drop a setting — a test compares this list against what the
    page actually built.

    Keeps the ``directory`` argument the three style pages pass; the shared
    join takes dispositions rather than a directory, so it is read here.
    """
    return loader_surfaced_ids(page_id, load_dispositions(directory))


def corpus_rows(directory: Path | str | None = None) -> dict[str, Row]:
    """``{descriptor_id: Row}`` for the whole descriptor corpus.

    Panels first, then domains, matching :attr:`gtheme.panels.loader.Corpus.rows`
    — the core-GNOME description of a setting wins over an add-on's, which
    matters for nothing today and would matter loudly the day it did.
    """
    corpus = load_corpus(directory)
    return {row.id: row for row in corpus.rows}


# --------------------------------------------------------------------------
# the window's shared objects
# --------------------------------------------------------------------------

#: Where the window keeps its schema probe. One probe per window is the
#: contract; until the integration wave hands one down, a page takes the
#: window's if it has one and leaves its own there if it does not, so the second
#: page to open reuses the first page's directory scan rather than repeating it.
PROBE_ATTR = "schema_probe"


def get_probe(window: Any) -> SchemaProbe:
    """The window's schema probe, building it once if nobody has yet."""
    probe = getattr(window, PROBE_ATTR, None)
    if isinstance(probe, SchemaProbe):
        return probe
    probe = SchemaProbe()
    try:
        setattr(window, PROBE_ATTR, probe)
    except AttributeError:  # pragma: no cover - a window that refuses attributes
        pass
    return probe


def _row_index(window: Any) -> Any | None:
    return getattr(window, "rows", None)


def _prefs(window: Any) -> Any | None:
    return getattr(window, "prefs", None)


def toast(window: Any, text: str) -> None:
    """Say something to the person, if there is a window able to say it."""
    speak = getattr(window, "toast", None)
    if callable(speak):
        speak(text)


# --------------------------------------------------------------------------
# applying a compound change
# --------------------------------------------------------------------------


def apply_ops(window: Any, ops: Iterable[Op], *, done: str) -> bool:
    """Apply a hand-built compound change as one transaction.

    Used by the controls that have to write **more than one key at once** —
    dark mode writes the colour scheme and the style for older apps together,
    and the window-heading font has to stop the headings following the main
    text style before it can set one. Splitting those into separate writes is
    how a desktop ends up half-changed.

    No label is passed. A label means "a whole Look was applied" and triggers
    the tidy-up that switching Looks needs; a page changing one thing must not
    tidy up after anything.

    Returns:
        Whether it worked. On failure the person is told, in words about their
        desktop, and the transaction has already put back whatever it managed
        to change.
    """
    ops = list(ops)
    if not ops:
        return True
    try:
        Transaction(ops).apply()
    except TransactionError as exc:
        rolled = "" if exc.rolled_back else " Some of it may have been changed anyway."
        toast(window, f"That change could not be made.{rolled}")
        return False
    toast(window, done)
    return True


# --------------------------------------------------------------------------
# the page scaffold
# --------------------------------------------------------------------------


class PageShell:
    """One page under construction: groups, rows, the probe, and teardown.

    Args:
        window: the application window. Only ever asked for the things a page
            genuinely needs — its row index, its preferences and its toast
            area — so a test can hand in a stand-in.
        page_id: the id from ``ui.registry``. Rows are registered under it, and
            it is what a search hit deep-links to.
        banner_id: the one-shot explainer key in ``prefs.json``, or None.
        banner_text: what that explainer says.
    """

    def __init__(
        self,
        window: Any,
        page_id: str,
        *,
        banner_id: str | None = None,
        banner_text: str | None = None,
    ) -> None:
        self.window = window
        self.page_id = page_id
        self.backend: SettingsBackend = get_backend()
        self.probe = get_probe(window)
        self.rows = corpus_rows()

        self.page = Adw.PreferencesPage(vexpand=True)
        self.container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.banner: Adw.Banner | None = None
        if banner_id and banner_text:
            self.banner = self._build_banner(banner_id, banner_text)
            if self.banner is not None:
                self.container.append(self.banner)
        self.container.append(self.page)

        #: Things that watch a value they do not own: the notice that appears
        #: while the desktop is still choosing text rendering for itself, the
        #: preview line that follows the text-size slider. They are re-run
        #: whenever anything on the page changes, which is the closest a page
        #: can get to live mirroring before the integration wave wires the real
        #: change signals up.
        self.notices: list[Callable[[], None]] = []

        #: Descriptor rows that were built live, with the widget to grey if the
        #: idle probe disagrees with the quick check made at build time.
        self._probe_targets: list[tuple[Row, Adw.PreferencesRow]] = []
        self._source_id: int | None = None
        self._built: list[str] = []

        # Announce this page to the window, if the window keeps a list. That is
        # how live mirroring re-runs the notices above when a value moves
        # *outside* gtheme: a notice watches something it does not own, and the
        # only thing that knows a value moved is the window's changed-signal
        # subscription. Optional in both directions — a test's stand-in window
        # has no such method, and nothing here depends on one.
        announce = getattr(window, "register_page_shell", None)
        if callable(announce):
            announce(self)

    # -- the first-visit explainer ----------------------------------------

    def _build_banner(self, banner_id: str, text: str) -> Adw.Banner | None:
        prefs = _prefs(self.window)
        if prefs is not None and not prefs.should_show_banner(banner_id):
            return None
        banner = Adw.Banner(title=text, button_label="Got it", revealed=True)

        def dismissed(*_args: Any) -> None:
            banner.set_revealed(False)
            if prefs is not None:
                prefs.mark_banner_seen(banner_id)

        banner.connect("button-clicked", dismissed)
        return banner

    # -- groups and rows ---------------------------------------------------

    def group(self, title: str, description: str | None = None) -> Adw.PreferencesGroup:
        """Add a group to the page and return it."""
        group = Adw.PreferencesGroup(title=title)
        if description:
            group.set_description(description)
        self.page.add(group)
        return group

    def advanced(self, group: Adw.PreferencesGroup) -> Adw.ExpanderRow:
        """The collapsed "More options" row inside a group.

        Advanced settings are real and are never hidden outright — they are one
        click away, behind a row that says what is inside it.
        """
        expander = Adw.ExpanderRow(title=ADVANCED_TITLE, subtitle=ADVANCED_SUBTITLE)
        group.add(expander)
        return expander

    def descriptor(self, descriptor_id: str) -> Row | None:
        """One row of the corpus by id, or None if the corpus lacks it."""
        return self.rows.get(descriptor_id)

    def add_descriptor_row(
        self,
        parent: Adw.PreferencesGroup | Adw.ExpanderRow,
        descriptor_id: str,
    ) -> Adw.PreferencesRow | None:
        """Build one descriptor row, place it, and register it.

        Returns None when the corpus has no such descriptor — a data problem,
        and one that must not take the rest of the page down with it.
        """
        row = self.descriptor(descriptor_id)
        if row is None:
            return None
        try:
            widget, refresh = build_row(self.backend, row, probe=self.probe)
        except RowBuildError:
            # A kind this page cannot draw (a picker) reaching here is a
            # placement mistake, not a user's problem: say so honestly rather
            # than showing nothing.
            widget = Adw.ActionRow(
                title=row.title,
                subtitle="This one isn't ready in gtheme yet.",
                sensitive=False,
            )
            refresh = _nothing
        self.place(parent, widget)
        self.register(row, widget, refresh, probe=True)
        return widget

    def place(
        self,
        parent: Adw.PreferencesGroup | Adw.ExpanderRow,
        widget: Gtk.Widget,
    ) -> None:
        """Put a row into a group or into an expander, whichever this is."""
        if isinstance(parent, Adw.ExpanderRow):
            parent.add_row(widget)
        else:
            parent.add(widget)

    def register(
        self,
        row: Row,
        widget: Any,
        refresh: Callable[[], None] | None = None,
        *,
        probe: bool = False,
    ) -> None:
        """Record a built row so search, deep links and mirroring find it."""
        self._built.append(row.id)
        index = _row_index(self.window)
        if index is not None:
            index.register(
                self.page_id,
                row.id,
                widget,
                refresh=refresh,
                search_text=search_text(row),
            )
        if probe and isinstance(widget, Adw.PreferencesRow):
            self._probe_targets.append((row, widget))
        self._follow_changes(widget)

    def run_notices(self) -> None:
        """Re-run everything that watches a value it does not own."""
        for notice in self.notices:
            notice()

    #: Which "the value moved" signal each row kind emits. A page cannot ask a
    #: row what changed — the row library owns that — but it can listen for the
    #: fact that something did, which is all a notice needs.
    _CHANGE_SIGNALS: tuple[tuple[type, str], ...] = (
        (Adw.ComboRow, "notify::selected"),
        (Adw.SwitchRow, "notify::active"),
        (Adw.SpinRow, "notify::value"),
        (Adw.EntryRow, "apply"),
    )

    def _follow_changes(self, widget: Any) -> None:
        for kind, signal in self._CHANGE_SIGNALS:
            if isinstance(widget, kind):
                widget.connect(signal, lambda *_a: self.run_notices())
                return

    @property
    def built_ids(self) -> list[str]:
        """Every descriptor id this page put on screen, in build order."""
        return list(self._built)

    def refresh(self, descriptor_id: str) -> None:
        """Re-read one row that something else just changed underneath it."""
        index = _row_index(self.window)
        if index is not None:
            index.refresh(descriptor_id)

    # -- the probe ---------------------------------------------------------

    def start_probe(self) -> int | None:
        """Check every built row on idle time, greying what is not really here.

        The rows were already checked once, at build time, against a probe that
        memoises its answers. This second pass is what covers the rows built
        before the probe had scanned anything — and it is where the honest
        sentence lands on a row that turned out not to exist.
        """
        if not self._probe_targets:
            return None
        rows = [row for row, _widget in self._probe_targets]
        by_id = {row.id: widget for row, widget in self._probe_targets}

        def on_result(row: Row, availability: Availability) -> None:
            widget = by_id.get(row.id)
            if widget is None or availability.ok:
                return
            widget.set_sensitive(False)
            setter = getattr(widget, "set_subtitle", None)
            if callable(setter):
                setter(availability.reason)

        def on_done() -> None:
            self._source_id = None

        # The backend goes with it: without one, a row whose add-on keeps its
        # settings in a file of its own comes back "cannot be read" and is
        # greyed even though it works.
        self._source_id = probe_rows_idle(
            self.probe, rows, on_result, backend=self.backend, on_done=on_done
        )
        return self._source_id

    def _teardown(self, *_args: Any) -> None:
        if self._source_id is not None:
            GLib.source_remove(self._source_id)
            self._source_id = None
        index = _row_index(self.window)
        if index is not None:
            index.unregister_page(self.page_id)
        forget = getattr(self.window, "unregister_page_shell", None)
        if callable(forget):
            forget(self)

    def finish(self) -> Gtk.Widget:
        """Start the probe, wire teardown, and hand back the page widget."""
        self.run_notices()
        self.start_probe()
        self.container.connect("destroy", self._teardown)
        return self.container


def _nothing() -> None:
    """A refresh for a row that cannot go stale."""


# --------------------------------------------------------------------------
# hand-built pickers
# --------------------------------------------------------------------------


def picker_row(
    backend: SettingsBackend,
    row: Row,
    options: list[tuple[str, str]],
    *,
    empty_label: str | None = None,
) -> tuple[Adw.ComboRow, Callable[[], None]]:
    """A pick-one row whose options came from scanning the computer.

    The row library builds every kind of row that is backed by a *setting*.
    A picker is backed by what is installed — themes, icon sets, pointer
    styles, fonts — so its content comes from the enumeration modules and the
    widget is built here. Everything else about it is the same as any other
    row, the "put this back" button included.

    Args:
        backend: where the value is read and written.
        row: the descriptor. Its ``title`` and ``subtitle`` are used as-is.
        options: ``(stored value, label)`` pairs, in the order to show them.
            The stored value is the plain string, not GVariant text.
        empty_label: what to call the empty value, when an empty string is a
            real answer (the top bar style, where empty means "the one the
            desktop came with"). None leaves it out.

    Returns:
        ``(widget, refresh)``, the same shape every row builder returns.
    """
    entries: list[tuple[str, str]] = []
    if empty_label is not None:
        entries.append(("", empty_label))
    entries.extend(options)

    labels = Gtk.StringList()
    for _value, label in entries:
        labels.append(label)
    widget = Adw.ComboRow(title=row.title, subtitle=row.subtitle, model=labels)
    values = [value for value, _label in entries]
    guard = {"busy": False}
    foreign = {"value": None}

    def drop_foreign() -> None:
        if foreign["value"] is not None:
            labels.remove(len(values))
            foreign["value"] = None

    def refresh() -> None:
        guard["busy"] = True
        try:
            raw = value_or_none(backend, key_for(row))
            current = unquote(raw) if raw is not None else ""
            if current in values:
                drop_foreign()
                widget.set_selected(values.index(current))
                return
            # Something not installed here, or set by another app. Showing the
            # first entry instead would be a lie, and would overwrite the real
            # value the moment anything nearby was touched.
            if foreign["value"] != current:
                drop_foreign()
                labels.append(f"{current} — not on this computer")
                foreign["value"] = current
            widget.set_selected(len(values))
        finally:
            guard["busy"] = False

    # The reset button wraps ``refresh`` so that its own sensitivity follows
    # every value change. Writing a picker has to call the WRAPPED one, or the
    # "put this back" button stays lit after the value has been put back by
    # hand — so the current refresh is held in a cell rather than captured.
    current: list[Callable[[], None]] = [refresh]

    def on_selected(*_args: Any) -> None:
        if guard["busy"]:
            return
        index = widget.get_selected()
        if index == Gtk.INVALID_LIST_POSITION or index >= len(values):
            return
        try:
            backend.set(key_for(row), quote(values[index]))
        except BackendError:
            return
        current[0]()

    refresh()
    widget.connect("notify::selected", on_selected)
    if row.reset:
        current[0] = attach_reset(backend, row, widget, refresh)
    return widget, current[0]
