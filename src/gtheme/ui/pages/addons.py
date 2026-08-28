"""Add-ons: what you have, what you could have, and what needs updating.

Three views behind one switcher, because that is the shape a person already
knows from every app store they have used: **Installed** is the list of add-ons
on this computer with a switch each, **Discover** is a search over the online
library, and **Updates** is the "there are three, apply them" page.

Four things in here are decided by facts about GNOME rather than by taste, and
each one is the reason a piece of this file looks the way it does.

**Nothing here ever shows an add-on's identifier.** The desktop hands them out
constantly — ``dash-to-dock@micxgx.gmail.com`` is the name of a folder, not the
name of a thing a person wants — and every competitor leaks them into error
messages. :func:`display_name` is the only place a name is decided, and it
falls back to a readable form rather than to the identifier.

**An add-on that was installed after this desktop session started cannot be
switched on.** The desktop scans its folders once, at start-up, and there is no
way to make it look again (``research/runtime-load-experiment.md``). So the
switch does not promise anything: it asks
:mod:`gtheme.ego.install`, which asks the desktop what it actually knows, and
whichever of the two sentences comes back is the one shown. "It's on now" and
"it starts working after you log out and back in" differ by one clause and by
the entire question of whether the app is telling the truth.

**Installing is the desktop's own job.** ``InstallRemoteExtension`` opens a
confirmation box *in the desktop*, in front of this window, and does not answer
until somebody clicks it — sometimes long after the call has given up waiting.
The rule that follows is absolute and lives here as well as in the installer:
one install request per add-on, ever. A second request while the first is still
being confirmed installs the add-on twice and leaves a state only a log-out
clears. :attr:`AddonsPage._installs` is what makes that impossible to do by
double-clicking.

**The settings behind the gear button are somebody else's.** Twenty-four
add-ons have a curated panel in ``data/panels/`` — rows written in plain words,
with bounds and warnings. Everything else gets a panel generated from what the
add-on itself declares, with a banner saying so, because the alternative is
either hiding half of what an add-on can do or pretending its author's wording
is ours.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from ...core.backends import get_backend, has_session_bus  # noqa: E402
from ...core.settings_backend import BackendError, SettingsBackend  # noqa: E402
from ...ego.client import DiskCache, EgoClient, EgoError, SoupTransport  # noqa: E402
from ...ego.install import (  # noqa: E402
    ExtensionInstaller,
    InstallOutcome,
    InstallReport,
)
from ...ego.models import ExtensionRecord, QueryPage  # noqa: E402
from ...ego.shelldbus import (  # noqa: E402
    ExtensionState,
    ExtensionType,
    GDBusShellProxy,
    InstalledExtension,
    ShellError,
    ShellExtensions,
    UninstallResult,
)
from ...ego.updates import COPY as UPDATE_COPY  # noqa: E402
from ...ego.updates import UpdateCandidate, UpdateChecker, UpdateVerdict  # noqa: E402
from ...panels import conflicts as conflicts_mod  # noqa: E402
from ...panels.descriptor import Choice, PanelDescriptor, Row, WidgetKind  # noqa: E402
from ...panels.loader import load_corpus  # noqa: E402
from ...panels.schema_probe import SchemaProbe, probe_rows_idle  # noqa: E402
from ...panels.widgets import build_row, set_link_handler  # noqa: E402
from ...prefs import Prefs  # noqa: E402
from ..jargon import translate  # noqa: E402
from ..widgets.explainer import first_visit_banner  # noqa: E402
from ..widgets.rows import UnsupportedRowKind, unquote, warn_banner  # noqa: E402

__all__ = [
    "CATEGORY_ORDER",
    "CATEGORY_TITLES",
    "COPY",
    "MAX_SCREENSHOT_BYTES",
    "OTHER_CATEGORY_TITLE",
    "SEARCH_DELAY_MS",
    "SORTS",
    "AddonsPage",
    "auto_rows",
    "backend_for_schema",
    "build",
    "display_name",
    "summary_of",
]


#: The two one-shot explainers this page can show. Both are listed in
#: :data:`gtheme.prefs.KNOWN_BANNERS`, and both are built by the one shared
#: :func:`~gtheme.ui.widgets.explainer.first_visit_banner` — the dismiss button
#: says what it says on every other page rather than out of this page's own
#: copy table (review-report M28).
BANNER_ID = "first-visit-addons"
AUTHOR_SETTINGS_BANNER_ID = "addon-settings-are-the-authors"


#: Every sentence this page says, in one place so the wording can be read as a
#: whole and linted as a whole. Sentences that already exist in
#: :mod:`gtheme.ego.install` or :mod:`gtheme.ego.updates` are used from there
#: verbatim and are deliberately NOT restated here: two wordings of "it starts
#: working after you log out and back in" is one wording too many.
COPY: dict[str, str] = {
    # -- the page itself
    "installed-tab": "Installed",
    "discover-tab": "Discover",
    "updates-tab": "Updates",
    "first-visit": (
        "These are add-ons — small extras that add features to your desktop. "
        "You can turn any of them off again."
    ),
    # -- no desktop to talk to
    "no-desktop-title": "Add-ons are not reachable right now",
    # This used to end "give it a moment and open this page again", which could
    # not work: the desktop connection is made once per window and this page's
    # widgets are kept, so leaving the page and coming back showed the same
    # answer from the same failed attempt until the app was quit
    # (persona-report §3.3, E10). The sentence now names a button that really
    # does ask again.
    "no-desktop-body": (
        "Add-ons are run by GNOME itself, and it is not answering. Everything "
        "else in this app still works. If you have just logged in, give it a "
        "moment and then ask again."
    ),
    "no-desktop-retry": "Ask again",
    "reprobe-heading": "Looking for your add-ons",
    "reprobe-starting": "Asking GNOME again…",
    "reprobe-failed": (
        "Still no answer. If you have just logged in, wait a few seconds and "
        "ask again."
    ),
    "reprobe-worked": "Found them.",
    # -- installed
    "installed-empty-title": "No add-ons yet",
    "installed-empty-body": (
        "Add-ons are small extras that add features to your desktop — a clock "
        "that shows the weather, a row of app icons that stays on screen. "
        "Look in Discover to find some."
    ),
    "installed-broken": "This add-on stopped working. Turning it off and on again often fixes it.",
    "installed-outdated": "This add-on was not made for your version of GNOME and is switched off.",
    "installed-system-wide": "Installed for everyone on this computer.",
    "turned-off": "Turned off.",
    "turn-off-failed": "That add-on could not be turned off.",
    "settings-button": "Settings for this add-on",
    "remove": "Remove",
    "remove-heading": "Remove {name}?",
    "remove-body": "You can add it again later from Discover.",
    "removed": "Removed.",
    "remove-system-wide": (
        "This add-on was installed for everyone on this computer, so it can only "
        "be removed by whoever looks after the machine."
    ),
    "remove-unknown": "That add-on is not on this computer any more.",
    "keep-both": "Keep both",
    "cancel": "Cancel",
    "turn-off-other": "Turn off {name}",
    # -- the gear panel
    "author-settings": (
        "These settings come from the person who wrote the add-on, so the "
        "wording is theirs, not ours."
    ),
    "author-settings-title": "Settings from the add-on",
    "panel-none": "This add-on has no settings to change.",
    "panel-own-window": "Open the add-on's own settings",
    "panel-own-window-subtitle": "A few of its settings only fit in the window its author wrote.",
    "panel-more-settings": "More settings",
    "panel-skipped": (
        "{count} more settings can only be changed in the add-on's own window."
    ),
    "panel-skipped-one": "One more setting can only be changed in the add-on's own window.",
    "panel-elsewhere": "{count} of this add-on's settings live on another page of this app.",
    "panel-elsewhere-one": "One of this add-on's settings lives on another page of this app.",
    "panel-open-failed": "The add-on's own settings would not open.",
    # -- discover
    "search-placeholder": "Search for add-ons",
    "discover-hint-title": "Find an add-on",
    "discover-hint-body": (
        "Type what you want your desktop to do — try “weather”, “clipboard”, "
        "“dock” or “battery”."
    ),
    "searching": "Looking…",
    "results-about": "About {count} to choose from",
    "no-results-title": "Nothing found",
    "no-results-body": "Nothing matched “{text}”. Try a shorter word.",
    "load-more": "Show more",
    "offline-title": "The add-on library is not reachable",
    "add": "Add",
    "adding": "Adding…",
    "added": "Added",
    "already-adding": "That one is already being added. Answer the box on your screen.",
    "not-compatible-badge": "Not made for your GNOME yet",
    "sort-label": "Sort by",
    "by-author": "by {author}",
    "downloads": "{count} downloads",
    "rating": "{stars} out of 5, from {count} people",
    "no-rating": "Nobody has rated this yet",
    "reviews": "What people say",
    "no-reviews": "Nobody has written about this one yet.",
    "no-picture": "This add-on has no picture to show.",
    # -- updates
    "check": "Check for updates",
    "checking": "Checking…",
    "update": "Update",
    "update-all": "Update everything",
    "up-to-date-title": "Everything is up to date",
    "updates-title": "Updates ready",
    "updates-body": (
        "Updates are put in place the next time you log in, so nothing changes "
        "under your desk while you work."
    ),
    "update-failed": "That update could not be downloaded.",
    "check-failed-title": "Could not check for updates",
}

#: The six groups the Installed list is divided into, in this order. The words
#: are the ones the panel descriptors already use, so a curated panel decides
#: where its add-on appears by declaring one field.
CATEGORY_ORDER: tuple[str, ...] = (
    "looks",
    "layout",
    "system",
    "system readings",
    "getting things done",
    "phones and devices",
)

CATEGORY_TITLES: dict[str, str] = {
    "looks": "Looks",
    "layout": "Layout",
    "system": "System",
    "system readings": "System readings",
    "getting things done": "Getting things done",
    "phones and devices": "Phones and devices",
}

#: Where an add-on with no curated panel goes. It is last, and it is not a
#: judgement: most of the library has no curated panel and never will.
OTHER_CATEGORY_TITLE = "Other add-ons"

#: Sort orders offered, as ``(what the library calls it, what we call it)``.
SORTS: tuple[tuple[str, str], ...] = (
    ("downloads", "Most downloaded"),
    ("popularity", "Most popular"),
    ("recent", "Newest"),
    ("name", "Name"),
)

#: How long to wait after the last keystroke before searching. Extension
#: Manager's number, and it is right: shorter turns every word typed into a
#: request, longer feels broken.
SEARCH_DELAY_MS = 750

#: Screenshots are downloaded whole, so there has to be a ceiling. Some of them
#: are animated and a few megabytes; past this the picture is simply not shown
#: rather than the app stalling on somebody's phone tethering.
MAX_SCREENSHOT_BYTES = 2 * 1024 * 1024

#: What to ask the library about when the desktop will not say which version
#: of GNOME this is. The app supports 49 and 50; asking about the newer one is
#: the answer that is right more often, and the install path checks the real
#: build list before anything is downloaded either way.
FALLBACK_GNOME_VERSION = "50"

#: How often to ask what became of an install whose confirmation box is still
#: on screen. Asking is free; installing again is not, and never happens.
PENDING_POLL_SECONDS = 2

#: And how many times, before giving up on a box nobody is going to answer.
#: Ten minutes: long enough for somebody to find the window the desktop put in
#: front of this one, short enough not to be a timer for the rest of the day.
PENDING_POLL_LIMIT = 300

#: A generated panel only draws the kinds of setting it can draw correctly.
#: Everything else — lists, dictionaries, numbers with no stated range — is
#: counted and named rather than rendered as a control that would write a
#: wrongly-typed value the moment it was touched.
_AUTO_NUMBER_TYPES = frozenset({"i", "u", "n", "q", "x", "t", "d"})

#: Past this many characters, an add-on author's one-line summary is a sentence
#: rather than a label, and belongs under the row instead of on it.
AUTO_TITLE_LIMIT = 60


# --------------------------------------------------------------------------
# small pure helpers — the parts worth testing without a window
# --------------------------------------------------------------------------


def display_name(uuid: str, name: str = "") -> str:
    """A name for an add-on that is never its identifier.

    The desktop returns the identifier as the name for anything it could not
    read a proper name from, and identifiers look like email addresses. So a
    name that *is* the identifier is turned back into words: the part in front
    of the ``@``, with its dashes opened out.
    """
    candidate = (name or "").strip()
    if not candidate or candidate == uuid:
        candidate = uuid.split("@")[0]
    if "@" in candidate:
        candidate = candidate.split("@")[0]
    if candidate == candidate.lower() and ("-" in candidate or "_" in candidate):
        words = candidate.replace("-", " ").replace("_", " ").split()
        candidate = " ".join(words)
        candidate = candidate[:1].upper() + candidate[1:]
    return candidate or "Add-on"


def summary_of(text: str, limit: int = 140) -> str:
    """One line of somebody else's description, fit for a row subtitle."""
    collapsed = " ".join((text or "").split())
    if len(collapsed) <= limit:
        return collapsed
    cut = collapsed[:limit].rsplit(" ", 1)[0]
    return f"{cut}…"


def backend_for_schema(probe: SchemaProbe, schema_id: str) -> SettingsBackend:
    """The backend an add-on's own settings can be read and written through.

    An add-on keeps the description of its settings inside its own folder, and
    the system knows nothing about it — a backend without that description in
    hand reports every one of its settings as missing. So this asks the probe
    where the add-on's descriptions are and asks
    :func:`~gtheme.core.backends.get_backend` for a backend scoped to them.

    The rule that a forced backend wins regardless lives there now rather than
    here. It is what keeps the tests off the real desktop, it was written out
    twice in this app, and it is exactly the rule a page is likeliest to walk
    past while reaching for a schema.
    """
    return get_backend(schema_source=probe.source_for(schema_id))


#: Add-on authors write their own one-line summaries for programmers, and a
#: good half of them start by naming the kind of value. Nobody reading a
#: settings window needs to be told that an on/off setting is a boolean.
_TYPE_PREFIX = re.compile(
    r"^(boolean|string|integer|int|float|double|number|array|list|enum|dict|dictionary)\s*[,:]\s*",
    re.IGNORECASE,
)


def _clean_summary(text: str) -> str:
    """One of somebody else's summaries, with the type word off the front."""
    return _TYPE_PREFIX.sub("", (text or "").strip())


def _humanise(value: str) -> str:
    """``"'top-left'"`` -> ``"Top left"``. For options nobody wrote labels for."""
    text = unquote(value).replace("-", " ").replace("_", " ").strip()
    return text[:1].upper() + text[1:] if text else value


def auto_rows(probe: SchemaProbe, schema_id: str) -> tuple[list[Row], int]:
    """Rows generated from what an add-on says about its own settings.

    Returns ``(rows, skipped)``. This is the fallback for the add-ons that have
    no curated panel, and it is deliberately conservative: on/off settings,
    numbers that state their own range, a fixed list of options, and plain
    text. A setting whose value is a list, a dictionary, or a number with no
    stated range is counted in ``skipped`` and named on the panel instead of
    being drawn — a control that writes the wrong shape of value into somebody
    else's settings is worse than no control at all.

    The words are the add-on author's, passed through the plain-language
    translation table so at least the vocabulary the app bans does not reappear
    here, and labelled on the panel as coming from them.
    """
    schema = probe.lookup(schema_id)
    if schema is None:
        return [], 0
    rows: list[Row] = []
    skipped = 0
    for key in sorted(schema.list_keys()):
        try:
            schema_key = schema.get_key(key)
            type_string = schema_key.get_value_type().dup_string()
            summary = schema_key.get_summary() or ""
            description = schema_key.get_description() or ""
            range_kind, range_values = _key_range(schema_key)
        except Exception:  # noqa: BLE001 - a hostile schema must not kill the panel
            skipped += 1
            continue

        # An author's summary is sometimes a label and sometimes a whole
        # sentence. A sentence makes a terrible row title and a perfectly good
        # explanation, so a long one is moved down a line and the setting's own
        # name is opened out into words for the title.
        headline = translate(_clean_summary(summary))
        explanation = translate(summary_of(_clean_summary(description)))
        if not headline or len(headline) > AUTO_TITLE_LIMIT:
            explanation = explanation or headline
            headline = _humanise(key)
        common: dict[str, Any] = {
            "schema_id": schema_id,
            "key": key,
            "title": headline[:1].upper() + headline[1:],
            "subtitle": explanation or COPY["author-settings"],
            "reset": True,
        }

        if range_kind == "enum" and range_values:
            rows.append(
                Row(
                    **common,
                    kind=WidgetKind.CHOICE,
                    choices=[
                        Choice(value=value, label=_humanise(value)) for value in range_values
                    ],
                )
            )
        elif type_string == "b":
            rows.append(Row(**common, kind=WidgetKind.TOGGLE))
        elif type_string in _AUTO_NUMBER_TYPES and range_kind == "range":
            low, high = range_values
            rows.append(
                Row(
                    **common,
                    kind=WidgetKind.SLIDER,
                    clamp_min=float(low),
                    clamp_max=float(high),
                    step=1 if type_string != "d" else 0.1,
                )
            )
        elif type_string == "s" and range_kind is None:
            rows.append(Row(**common, kind=WidgetKind.TEXT))
        else:
            skipped += 1
    return rows, skipped


def _key_range(schema_key: Any) -> tuple[str | None, Any]:
    """``("enum", ["'a'", "'b'"])`` / ``("range", (lo, hi))`` / ``(None, None)``.

    ``Gio.SettingsSchemaKey.get_range`` answers a two-part value whose first
    part names the kind. Anything that is not an enumeration or a stated range
    carries no bounds gtheme can honour, and the caller declines to draw it.
    """
    try:
        variant = schema_key.get_range()
    except Exception:  # noqa: BLE001 - defensive; never fatal
        return None, None
    if variant is None:
        return None, None
    try:
        kind = variant.get_child_value(0).get_string()
        payload = variant.get_child_value(1).get_variant()
    except Exception:  # noqa: BLE001 - defensive
        return None, None
    if kind == "enum":
        return "enum", [payload.get_child_value(i).print_(True) for i in range(payload.n_children())]
    if kind == "range":
        try:
            low = payload.get_child_value(0).unpack()
            high = payload.get_child_value(1).unpack()
        except Exception:  # noqa: BLE001 - defensive
            return None, None
        return "range", (low, high)
    return None, None


# --------------------------------------------------------------------------
# the page
# --------------------------------------------------------------------------


def build(
    window: Any = None,
    *,
    shell: ShellExtensions | None = None,
    probe: SchemaProbe | None = None,
) -> Gtk.Widget:
    """The factory named by ``ui.registry``'s manifest.

    ``shell`` and ``probe`` are named here on purpose: the window offers
    exactly the things it owns one of, and a factory receives the ones it says
    it can take. Left out, this page builds its own — which is what every test
    that constructs it by hand relies on.
    """
    return AddonsPage(window, shell=shell, probe=probe, owns_shell=shell is None)


class AddonsPage(Adw.Bin):
    """Installed / Discover / Updates.

    Everything the page talks to can be handed in, which is how the tests drive
    the whole page against a desktop and a library that do not exist. Left
    alone, it builds the real ones — and survives their absence: with no
    desktop answering, all three views show one honest screen rather than three
    broken ones.
    """

    __gtype_name__ = "GthemeAddonsPage"

    def __init__(
        self,
        window: Any = None,
        *,
        shell: ShellExtensions | None = None,
        client: EgoClient | None = None,
        installer: ExtensionInstaller | None = None,
        checker: UpdateChecker | None = None,
        probe: SchemaProbe | None = None,
        prefs: Prefs | None = None,
        panels: Sequence[PanelDescriptor] | None = None,
        owns_shell: bool = True,
    ) -> None:
        super().__init__()
        self.window = window
        self.prefs = prefs or getattr(window, "prefs", None) or Prefs()
        self.probe = probe or SchemaProbe()

        #: Whether closing this page closes the desktop connection with it.
        #: False when the window lent one: the window keeps a single connection
        #: for this page and the Home page's add-on line, and a shared object
        #: closed by a borrower is exactly how the Home page ends up talking to
        #: a connection that was shut behind its back. The default is True
        #: because a page that built its own connection must close it.
        self._owns_shell = owns_shell
        self.shell, self.available = self._connect_desktop(shell)
        self.client = client if client is not None else self._build_client()
        self.installer = installer or (
            ExtensionInstaller(self.shell, self.client) if self.shell is not None else None
        )
        self.checker = checker or (
            UpdateChecker(self.client, self.shell)
            if self.client is not None and self.shell is not None
            else None
        )
        self.panels: list[PanelDescriptor] = (
            list(panels) if panels is not None else load_corpus().panels
        )
        self._extra_conflicts = conflicts_mod.from_panels(self.panels)

        #: Add-ons whose install has been asked for and not yet finished. The
        #: single reason a second request can never be sent.
        self._installs: dict[str, Any] = {}
        #: Every GLib source this page owns, so teardown can take them all out.
        self._sources: list[int] = []
        self._backends: dict[str, SettingsBackend] = {}
        self._installed_rows: dict[str, Adw.SwitchRow] = {}
        #: Switches this page is moving itself. A switch that moves because the
        #: desktop said so must not be mistaken for one the user flipped.
        self._suppress: set[str] = set()
        self._load_more: Adw.PreferencesGroup | None = None
        self._polls: dict[str, int] = {}
        self._query: QueryPage | None = None
        self._search_text = ""
        self._sort = SORTS[0][0]
        self._rebuild_queued = False
        #: True while "Ask again" is waiting for the desktop, so a second press
        #: cannot start a second connection attempt beside the first.
        self._reprobing = False

        self._build_ui()
        if self.shell is not None:
            # Follow the desktop rather than asking it repeatedly: the signal
            # carries the same answer that asking would, and arrives sooner.
            self.shell.connect(self._on_extension_changed)
        self._fill_installed()
        self.connect("destroy", lambda *_a: self.teardown())

    # -- services ----------------------------------------------------------

    def _connect_desktop(
        self, given: ShellExtensions | None
    ) -> tuple[ShellExtensions | None, bool]:
        """Ask the desktop what it has loaded. Once, and never again by polling.

        A desktop that is not there is an ordinary state — gtheme runs on a
        machine where somebody has just logged into a different session, or
        under a display manager, or in a terminal. It gets a screen, not a
        traceback.
        """
        if given is not None:
            try:
                given.load()
            except ShellError:
                return given, False
            return given, True
        if not has_session_bus():
            return None, False
        shell = ShellExtensions(GDBusShellProxy())
        try:
            shell.load()
        except ShellError:
            return shell, False
        except Exception:  # noqa: BLE001 - no PyGObject typelib, no bus, no desktop
            return None, False
        return shell, True

    def _build_client(self) -> EgoClient | None:
        if self.shell is None:
            return None
        try:
            version = self.shell.proxy.shell_version() or FALLBACK_GNOME_VERSION
        except Exception:  # noqa: BLE001 - the desktop answered nothing useful
            version = FALLBACK_GNOME_VERSION
        return EgoClient(SoupTransport("gtheme"), version, DiskCache())

    def _backend_for(self, schema_id: str) -> SettingsBackend:
        """One backend per add-on, kept, because building them is not free."""
        owner = self.probe.owner_of(schema_id) or schema_id
        backend = self._backends.get(owner)
        if backend is None:
            backend = backend_for_schema(self.probe, schema_id)
            self._backends[owner] = backend
        return backend

    # -- construction ------------------------------------------------------

    def _build_ui(self) -> None:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        banner = first_visit_banner(self.prefs, BANNER_ID, COPY["first-visit"])
        if banner is not None:
            outer.append(banner)

        self.stack = Adw.ViewStack(vexpand=True)
        self.installed_view = self._empty_box()
        self.discover_view = self._build_discover()
        self.updates_view = self._empty_box()
        self.stack.add_titled(
            self._scrolled(self.installed_view), "installed", COPY["installed-tab"]
        )
        self.stack.add_titled(self.discover_view, "discover", COPY["discover-tab"])
        self.stack.add_titled(self._scrolled(self.updates_view), "updates", COPY["updates-tab"])

        switcher_row = Gtk.Box(halign=Gtk.Align.CENTER, margin_top=12, margin_bottom=6)
        switcher_row.append(Adw.InlineViewSwitcher(stack=self.stack))
        outer.append(switcher_row)
        outer.append(self.stack)
        self.set_child(outer)

        self._fill_updates_idle_state()

    @staticmethod
    def _empty_box() -> Gtk.Box:
        return Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=18,
            margin_top=12,
            margin_bottom=24,
            margin_start=12,
            margin_end=12,
        )

    @staticmethod
    def _scrolled(child: Gtk.Widget) -> Gtk.ScrolledWindow:
        clamp = Adw.Clamp(child=child, maximum_size=760, tightening_threshold=600)
        return Gtk.ScrolledWindow(
            child=clamp, hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True
        )

    def _unavailable_page(self) -> Adw.StatusPage:
        """The "GNOME is not answering" screen, with the way out on it.

        The button is the whole point (E10): the sentence beside it used to
        tell people to come back to a page that would give the same answer
        forever, because the connection is memoised for the life of the window.
        """
        page = Adw.StatusPage(
            icon_name="application-x-addon-symbolic",
            title=COPY["no-desktop-title"],
            description=COPY["no-desktop-body"],
            vexpand=True,
        )
        button = Gtk.Button(
            label=COPY["no-desktop-retry"],
            halign=Gtk.Align.CENTER,
            css_classes=["pill", "suggested-action"],
        )
        button.connect("clicked", lambda *_a: self.ask_again())
        page.set_child(button)
        return page

    # -- asking the desktop again ------------------------------------------

    def ask_again(self) -> None:
        """Make a new connection to the desktop and rebuild what depends on it.

        The slow half — building a proxy and listing what is installed — runs
        on the shared runner, because it is a blocking call that can take as
        long as the desktop takes to answer, and doing it in a click handler is
        the freeze this app has a runner to avoid.

        The answer is handed to the window as well as kept here: the window's
        connection is the one the Home page's add-on line reads, and a page
        that recovered on its own would leave the rest of the app reporting a
        desktop that answered fine ten seconds ago.
        """
        if self._reprobing:
            return
        self._reprobing = True
        runner = self._apply_runner()
        if runner is None:
            self._reconnected(self._reconnect())
            return
        runner.run(
            lambda _narrate: self._reconnect(),
            heading=COPY["reprobe-heading"],
            starting=COPY["reprobe-starting"],
            on_done=self._reconnected,
            on_failed=lambda _error: self._reconnected((None, False)),
        )

    def _reconnect(self) -> tuple[ShellExtensions | None, bool]:
        """The slow half. No widgets — this runs off the main loop."""
        return self._connect_desktop(None)

    def _reconnected(self, answer: tuple[ShellExtensions | None, bool]) -> None:
        """Take the new connection, or say plainly that there still is none."""
        self._reprobing = False
        shell, available = answer
        if shell is None or not available:
            self._toast(COPY["reprobe-failed"])
            return

        previous = self.shell
        if previous is not None:
            previous.disconnect(self._on_extension_changed)
        adopt = getattr(self.window, "adopt_shell", None)
        if callable(adopt):
            adopt(shell)
            # The window owns the shared connection, so this page must not
            # close it — the same rule the borrowed connection has always had.
            self._owns_shell = False
        elif previous is not None and self._owns_shell:
            try:
                previous.close()
            except Exception:  # noqa: BLE001 - it was already unreachable
                pass

        self.shell = shell
        self.available = available
        self.shell.connect(self._on_extension_changed)
        if self.client is None:
            self.client = self._build_client()
        self.installer = ExtensionInstaller(self.shell, self.client)
        self.checker = (
            UpdateChecker(self.client, self.shell) if self.client is not None else None
        )

        self._fill_installed()
        self._fill_updates_idle_state()
        if self.client is not None:
            self._run_query(page=1)
        self._toast(COPY["reprobe-worked"])

    def _apply_runner(self) -> Any:
        """The window's runner, or None when this page is not in a window."""
        from ..applyrunner import ApplyRunner

        runner = getattr(self.window, "runner", None)
        return runner if isinstance(runner, ApplyRunner) else None

    # -- installed ---------------------------------------------------------

    def _fill_installed(self) -> None:
        """Rebuild the Installed list from what the desktop currently reports."""
        box = self.installed_view
        self._clear(box)
        self._installed_rows.clear()

        if not self.available or self.shell is None:
            box.append(self._unavailable_page())
            return

        extensions = sorted(
            self.shell.all.values(), key=lambda e: display_name(e.uuid, e.name).lower()
        )
        if not extensions:
            box.append(
                Adw.StatusPage(
                    icon_name="application-x-addon-symbolic",
                    title=COPY["installed-empty-title"],
                    description=COPY["installed-empty-body"],
                    vexpand=True,
                )
            )
            return

        for text in self._hazard_texts():
            box.append(warn_banner(text))
        for widget in self._conflict_banners():
            box.append(widget)

        grouped: dict[str, list[InstalledExtension]] = {}
        for extension in extensions:
            panel = self._panel_for(extension.uuid)
            category = panel.target.category if panel is not None else ""
            grouped.setdefault(category, []).append(extension)

        for category in (*CATEGORY_ORDER, ""):
            members = grouped.get(category)
            if not members:
                continue
            title = CATEGORY_TITLES.get(category, OTHER_CATEGORY_TITLE)
            group = Adw.PreferencesGroup(title=title)
            for extension in members:
                group.add(self._installed_row(extension))
            box.append(group)

    def _installed_row(self, extension: InstalledExtension) -> Adw.SwitchRow:
        panel = self._panel_for(extension.uuid)
        name = display_name(extension.uuid, extension.name)
        if extension.state is ExtensionState.ERROR:
            subtitle = COPY["installed-broken"]
        elif extension.state is ExtensionState.OUT_OF_DATE:
            subtitle = COPY["installed-outdated"]
        elif panel is not None:
            subtitle = summary_of(panel.target.summary)
        else:
            subtitle = summary_of(extension.description) or COPY["installed-system-wide"]

        # ``use_markup`` is turned off BEFORE the words go in. Half of these
        # names and summaries are somebody else's, some of them contain an
        # ampersand, and a row renders marked-up text by default — an add-on
        # called "Numlock & Capslock" comes out blank with a warning.
        row = Adw.SwitchRow(use_markup=False)
        row.set_title(name)
        row.set_subtitle(subtitle)
        row.set_active(extension.is_running or extension.enabled)
        row.set_sensitive(extension.can_change)

        gear = Gtk.Button(
            icon_name="emblem-system-symbolic",
            valign=Gtk.Align.CENTER,
            css_classes=["flat"],
            tooltip_text=COPY["settings-button"],
        )
        gear.connect("clicked", lambda *_a, e=extension: self._open_panel(e))
        row.add_suffix(gear)

        row.connect("notify::active", self._on_switch_toggled, extension.uuid)
        self._installed_rows[extension.uuid] = row
        return row

    def _on_switch_toggled(self, row: Adw.SwitchRow, _param: Any, uuid: str) -> None:
        # A switch the page moved itself is not a request. The claim is taken
        # here rather than lifted by whoever made it, because the notification
        # does not always arrive while they are still running — see
        # :meth:`_set_switch`.
        if uuid in self._suppress:
            self._suppress.discard(uuid)
            return
        if self.shell is None:
            return
        if row.get_active():
            other = self._conflicting_enabled(uuid)
            if other is not None:
                self._ask_about_conflict(uuid, other, row)
                return
            self._turn_on(uuid)
        else:
            if self.shell.disable(uuid):
                self._toast(COPY["turned-off"])
            else:
                self._toast(COPY["turn-off-failed"])

    def _turn_on(self, uuid: str) -> None:
        """Switch an add-on on, and leave the switch showing what happened.

        The desktop can refuse. When it does, ``turn_on`` says so in a toast
        and returns — and the switch was left reading ON over an add-on that
        is off, with no ``ExtensionStateChanged`` signal coming to correct it,
        because nothing changed (review-report M5). A switch is a statement
        about the desktop, so it is moved back to what the desktop actually
        did.

        ``NEEDS_RELOGIN`` is the one failure-looking outcome where ON is
        honest: the add-on *is* enabled, and starts doing its job at the next
        log-in. Turning the switch off there would be the lie in the other
        direction.
        """
        if self.installer is None:
            return
        report = self.installer.turn_on(uuid)
        self._toast(report.message)
        self._set_switch(
            uuid, report.outcome in (InstallOutcome.ACTIVE, InstallOutcome.NEEDS_RELOGIN)
        )

    def _set_switch(self, uuid: str, active: bool) -> None:
        """Move a switch without pretending the user did it.

        The claim is left standing for ``notify::active`` to take, rather than
        lifted in a ``finally`` here, because the notification does not always
        arrive inside this call: moving a switch from *inside* another
        ``notify::active`` handler — which is exactly what putting a refused
        switch back does — queues the new notification until the outer one has
        finished. Lifting the claim here left nothing to suppress by then, so
        the page read its own correction as the user switching the add-on off
        and asked the desktop to disable it again, with a toast saying so.

        The value is compared first, so a claim is only ever made when a
        notification is really coming.
        """
        row = self._installed_rows.get(uuid)
        if row is None or row.get_active() == active:
            return
        self._suppress.add(uuid)
        row.set_active(active)

    # -- conflicts and hazards --------------------------------------------

    def _conflicting_enabled(self, uuid: str) -> str | None:
        """An add-on that is on and does the same job as this one."""
        if self.shell is None:
            return None
        running = {e.uuid for e in self.shell.all.values() if e.is_running or e.enabled}
        for other in conflicts_mod.conflicts_with(uuid, self._extra_conflicts):
            if other in running and other != uuid:
                return other
        return None

    def _ask_about_conflict(self, uuid: str, other: str, row: Adw.SwitchRow) -> Adw.AlertDialog:
        """Either/or, in the user's words, before anything is on twice."""
        chosen = display_name(uuid, self._name_of(uuid))
        other_name = display_name(other, self._name_of(other))
        explain = ""
        for conflict in (*conflicts_mod.CONFLICTS, *self._extra_conflicts):
            if conflict.other(uuid) == other:
                explain = conflict.explain
                break
        dialog = Adw.AlertDialog(
            heading=conflicts_mod.replacement_question(chosen, other_name),
            body=explain,
        )
        dialog.add_response("keep", COPY["keep-both"])
        dialog.add_response("replace", COPY["turn-off-other"].format(name=other_name))
        dialog.set_response_appearance("replace", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("replace")
        dialog.set_close_response("keep")

        def _answered(_dialog: Adw.AlertDialog, response: str) -> None:
            if response == "replace" and self.shell is not None:
                self.shell.disable(other)
                self._set_switch(other, False)
            # The switch comes back on inside ``_turn_on``, and only if the
            # desktop really did switch the add-on on. Setting it here as well
            # is what used to put it back on over a refusal.
            self._turn_on(uuid)

        dialog.connect("response", _answered)
        self._present(dialog)
        # The switch goes back until the question is answered: a switch that is
        # already on while a dialog asks whether to turn it on is a lie.
        self._set_switch(uuid, False)
        return dialog

    def _hazard_texts(self) -> list[str]:
        """The combinations that are on right now and worth a sentence."""
        if self.shell is None:
            return []
        running = [e.uuid for e in self.shell.all.values() if e.is_running or e.enabled]
        return [
            hazard.explain
            for hazard in conflicts_mod.active_hazards(running, is_true=self._setting_is_true)
        ]

    def _setting_is_true(self, descriptor_id: str) -> bool:
        """Whether one setting is switched on, for the hazard check.

        A setting that cannot be read counts as on. The one hazard this
        machine knows about breaks screen recording silently, and being told
        about a risk that turned out not to apply costs a person nothing —
        while staying quiet because a lookup failed costs them the recording
        they were about to make.
        """
        schema_id, _, key = descriptor_id.rpartition(":")
        if not schema_id or not key:
            return True
        try:
            return self._backend_for(schema_id).get(f"gsettings:{schema_id} {key}").strip() == "true"
        except BackendError:
            return True

    def _conflict_banners(self) -> list[Gtk.Widget]:
        """Pairs that are BOTH on already — the state the switch tries to avoid."""
        if self.shell is None:
            return []
        running = [e.uuid for e in self.shell.all.values() if e.is_running or e.enabled]
        widgets: list[Gtk.Widget] = []
        for conflict in conflicts_mod.active_conflicts(running, self._extra_conflicts):
            name_b = display_name(conflict.b, self._name_of(conflict.b))
            banner = Adw.Banner(
                title=conflict.explain,
                button_label=COPY["turn-off-other"].format(name=name_b),
                revealed=True,
            )
            banner.connect("button-clicked", lambda *_a, uuid=conflict.b: self._turn_off(uuid))
            widgets.append(banner)
        return widgets

    def _turn_off(self, uuid: str) -> None:
        if self.shell is None:
            return
        if self.shell.disable(uuid):
            self._set_switch(uuid, False)
            self._toast(COPY["turned-off"])
        else:
            self._toast(COPY["turn-off-failed"])

    def _name_of(self, uuid: str) -> str:
        if self.shell is None:
            return ""
        found = self.shell.all.get(uuid)
        return found.name if found is not None else ""

    # -- live refresh ------------------------------------------------------

    def _on_extension_changed(self, extension: InstalledExtension) -> None:
        """The desktop said an add-on changed. Never asked for; always followed."""
        row = self._installed_rows.get(extension.uuid)
        if row is not None and extension.state is not ExtensionState.UNINSTALLED:
            self._set_switch(extension.uuid, extension.is_running or extension.enabled)
            return
        # Something arrived or left: the grouping changes, so the list is rebuilt
        # — once, on idle, however many signals arrive in a burst.
        if self._rebuild_queued:
            return
        self._rebuild_queued = True

        def _rebuild() -> bool:
            self._rebuild_queued = False
            self._fill_installed()
            return GLib.SOURCE_REMOVE

        self._sources.append(GLib.idle_add(_rebuild))

    # -- the gear panel ----------------------------------------------------

    def _panel_for(self, uuid: str) -> PanelDescriptor | None:
        for panel in self.panels:
            if uuid in panel.target.uuids:
                return panel
        return None

    def _open_panel(self, extension: InstalledExtension) -> Adw.Dialog:
        """The settings for one add-on: ours if we curated it, theirs if not."""
        panel = self._panel_for(extension.uuid)
        name = display_name(extension.uuid, extension.name)

        content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=18,
            margin_top=12,
            margin_bottom=24,
            margin_start=12,
            margin_end=12,
        )
        rows: list[Row] = []
        widgets: dict[str, Adw.PreferencesRow] = {}
        # Settings this panel does not draw. Two different reasons, two
        # different sentences: one is "the author's own window has it", the
        # other is "another page of this app has it", and telling somebody to
        # go and look in the wrong place is worse than saying nothing.
        skipped = 0
        elsewhere = 0

        if panel is not None:
            schema_id = panel.target.schema_for(extension.uuid)
            rows = panel.rows_for(extension.uuid)
            if panel.target.warn:
                content.append(warn_banner(panel.target.warn))
        else:
            schema_id = extension.settings_schema or self._guess_schema(extension.uuid)
            rows, skipped = (
                auto_rows(self.probe, schema_id) if schema_id else ([], 0)
            )
            banner = first_visit_banner(
                self.prefs, AUTHOR_SETTINGS_BANNER_ID, COPY["author-settings"]
            )
            if banner is not None:
                content.append(banner)

        seen_warnings: list[str] = []
        for row in rows:
            if row.warn and row.warn not in seen_warnings:
                seen_warnings.append(row.warn)
        for text in seen_warnings:
            content.append(warn_banner(text))

        backend = self._backend_for(schema_id) if schema_id else get_backend()
        # A curated panel needs no group title: the dialog is already called
        # after the add-on. A generated one says whose words these are.
        plain = Adw.PreferencesGroup(
            title="" if panel is not None else COPY["author-settings-title"]
        )
        advanced = Adw.PreferencesGroup(title=COPY["panel-more-settings"])
        has_advanced = False

        for row in rows:
            try:
                widget, _refresh = build_row(backend, row, probe=self.probe)
            except UnsupportedRowKind:
                # A kind whose content comes from scanning the computer — the
                # list of top bar styles, say. Those rows belong to the page
                # that owns the scan, not to an add-on's settings box.
                elsewhere += 1
                continue
            except Exception:  # noqa: BLE001 - one impossible row is not a broken panel
                skipped += 1
                continue
            if row.kind is WidgetKind.LINK:
                set_link_handler(widget, row, self._follow_link)
            widgets[row.id] = widget
            if row.advanced:
                advanced.add(widget)
                has_advanced = True
            else:
                plain.add(widget)

        if not widgets and not elsewhere and not skipped:
            plain.add(
                Adw.ActionRow(title=COPY["panel-none"], subtitle="", sensitive=False)
            )
        content.append(plain)
        if has_advanced:
            content.append(advanced)

        extras = Adw.PreferencesGroup()
        if elsewhere:
            extras.add(
                Adw.ActionRow(
                    title=(
                        COPY["panel-elsewhere-one"]
                        if elsewhere == 1
                        else COPY["panel-elsewhere"].format(count=elsewhere)
                    ),
                    sensitive=False,
                )
            )
        if skipped or extension.has_prefs:
            if extension.has_prefs:
                own = Adw.ButtonRow(
                    title=COPY["panel-own-window"], start_icon_name="external-link-symbolic"
                )
                own.connect("activated", lambda *_a: self._open_own_prefs(extension.uuid))
                extras.add(own)
            if skipped:
                title = (
                    COPY["panel-skipped-one"]
                    if skipped == 1
                    else COPY["panel-skipped"].format(count=skipped)
                )
                extras.add(
                    Adw.ActionRow(
                        title=title,
                        subtitle=COPY["panel-own-window-subtitle"],
                        sensitive=False,
                    )
                )
        if extension.type is ExtensionType.PER_USER:
            remove = Adw.ButtonRow(title=COPY["remove"], start_icon_name="user-trash-symbolic")
            remove.add_css_class("destructive-action")
            remove.connect("activated", lambda *_a, e=extension: self._ask_to_remove(e))
            extras.add(remove)
        content.append(extras)

        header = Adw.HeaderBar()
        view = Adw.ToolbarView(content=self._scrolled(content))
        view.add_top_bar(header)
        dialog = Adw.Dialog(
            title=name, content_width=560, content_height=680, child=view
        )

        # Built first, checked afterwards: opening the panel is never delayed by
        # looking at what is on disk, and a setting this version of the add-on
        # does not have goes grey a frame later instead of holding the window.
        if rows:
            source = probe_rows_idle(
                self.probe, rows, self._grey_if_missing(widgets), backend=backend
            )
            self._sources.append(source)
            dialog.connect("closed", lambda *_a, s=source: self._drop_source(s))

        return self._present(dialog)

    def _grey_if_missing(
        self, widgets: dict[str, Adw.PreferencesRow]
    ) -> Callable[[Row, Any], None]:
        """Turn a probe verdict into a row that is visibly, honestly off.

        The verdict arrives already made. This used to throw it away and ask
        again with the backend in hand, because the idle probe could not be
        given one — and without one, an add-on that keeps its settings in a
        file of its own has no way to say which file is in use and comes back
        "cannot be read", which would grey the one panel on this machine that
        works hardest to be live. ``probe_rows_idle`` takes a backend now, so
        the verdict it hands over is the one to act on.
        """

        def _on_result(row: Row, availability: Any) -> None:
            verdict = availability
            if verdict.ok:
                return
            widget = widgets.get(row.id)
            if widget is None:
                return
            widget.set_sensitive(False)
            if hasattr(widget, "set_subtitle") and verdict.reason:
                widget.set_subtitle(verdict.reason)

        return _on_result

    def _guess_schema(self, uuid: str) -> str | None:
        """Which settings group an add-on owns, read from the add-on itself.

        Never from its description file and never from a file name: four of the
        popular add-ons leave the field out entirely, and one ships its
        settings in a file named after a different add-on.
        """
        found = self.probe.extensions.get(uuid)
        if found is None or not found.fixed:
            return None
        return sorted(found.fixed, key=len)[0]

    def _follow_link(self, target: str | None) -> None:
        """A link row went somewhere. Two destinations, both spelled out."""
        if not target:
            return
        if target.startswith("extension-prefs:"):
            self._open_own_prefs(target.split(":", 1)[1])
        elif target.startswith("page:") and hasattr(self.window, "show_page"):
            self.window.show_page(target.split(":", 1)[1])

    def _open_own_prefs(self, uuid: str) -> None:
        if self.shell is None:
            return
        try:
            self.shell.proxy.open_prefs(uuid, "")
        except ShellError:
            self._toast(COPY["panel-open-failed"])

    def _ask_to_remove(self, extension: InstalledExtension) -> Adw.AlertDialog:
        name = display_name(extension.uuid, extension.name)
        dialog = Adw.AlertDialog(
            heading=COPY["remove-heading"].format(name=name), body=COPY["remove-body"]
        )
        dialog.add_response("keep", COPY["cancel"])
        dialog.add_response("remove", COPY["remove"])
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_close_response("keep")

        def _answered(_dialog: Adw.AlertDialog, response: str) -> None:
            if response != "remove" or self.shell is None:
                return
            outcome = self.shell.uninstall(extension.uuid)
            if outcome is UninstallResult.REMOVED:
                self._toast(COPY["removed"])
                self._fill_installed()
            elif outcome is UninstallResult.SYSTEM_WIDE:
                self._toast(COPY["remove-system-wide"])
            else:
                self._toast(COPY["remove-unknown"])

        dialog.connect("response", _answered)
        return self._present(dialog)

    # -- discover ----------------------------------------------------------

    def _build_discover(self) -> Gtk.Widget:
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )

        self.search = Gtk.SearchEntry(
            placeholder_text=COPY["search-placeholder"], hexpand=True
        )
        self.search.set_search_delay(SEARCH_DELAY_MS)
        self.search.connect("search-changed", self._on_search_changed)

        self.sort = Gtk.DropDown.new_from_strings([label for _value, label in SORTS])
        self.sort.set_tooltip_text(COPY["sort-label"])
        self.sort.connect("notify::selected", self._on_sort_changed)

        controls = Gtk.Box(spacing=6)
        controls.append(self.search)
        controls.append(self.sort)
        box.append(controls)

        self.results_box = self._empty_box()
        self.results_scroll = self._scrolled(self.results_box)
        spinner_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, vexpand=True
        )
        spinner_box.append(Adw.Spinner(width_request=48, height_request=48))
        spinner_box.append(Gtk.Label(label=COPY["searching"], css_classes=["dimmed"]))

        self.discover_stack = Gtk.Stack(vexpand=True)
        self.discover_stack.add_named(spinner_box, "spinner")
        self.discover_stack.add_named(self.results_scroll, "results")
        self.discover_stack.add_named(
            Adw.StatusPage(
                icon_name="system-search-symbolic",
                title=COPY["discover-hint-title"],
                description=COPY["discover-hint-body"],
                vexpand=True,
            ),
            "empty",
        )
        self.discover_stack.set_visible_child_name("empty")
        box.append(self.discover_stack)

        if self.client is not None and self.available:
            self._run_query(page=1)
        return box

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self._search_text = entry.get_text().strip()
        self._run_query(page=1)

    def _on_sort_changed(self, *_args: Any) -> None:
        index = self.sort.get_selected()
        if index == Gtk.INVALID_LIST_POSITION or index >= len(SORTS):
            return
        self._sort = SORTS[index][0]
        self._run_query(page=1)

    def _run_query(self, *, page: int) -> None:
        """One page of results. Paging follows the page count, never a hunch."""
        if self.client is None or not self.available:
            # The same screen as the other two tabs, button and all: whichever
            # tab somebody is looking at when the desktop goes quiet is the tab
            # they need the way out on.
            self._show_status(self.discover_stack, self._unavailable_page())
            return
        if page == 1:
            self.discover_stack.set_visible_child_name("spinner")
        keep_scroll = self.results_scroll.get_vadjustment().get_value() if page > 1 else 0.0

        def _answered(result: QueryPage | None, error: EgoError | None) -> None:
            self._on_results(result, error, page=page, keep_scroll=keep_scroll)

        self.client.query(
            _answered, search=self._search_text or None, sort=self._sort, page=page
        )

    def _on_results(
        self,
        result: QueryPage | None,
        error: EgoError | None,
        *,
        page: int,
        keep_scroll: float,
    ) -> None:
        if error is not None or result is None:
            self._show_status(
                self.discover_stack,
                Adw.StatusPage(
                    icon_name="network-offline-symbolic",
                    title=COPY["offline-title"],
                    description=error.user_text() if error else COPY["offline-title"],
                    vexpand=True,
                ),
            )
            return
        self._query = result
        if page == 1:
            self._clear(self.results_box)
            self._load_more = None
            if not result.extensions:
                self._show_status(
                    self.discover_stack,
                    Adw.StatusPage(
                        icon_name="system-search-symbolic",
                        title=COPY["no-results-title"],
                        description=COPY["no-results-body"].format(
                            text=self._search_text
                        ),
                        vexpand=True,
                    ),
                )
                return
            header = Gtk.Label(
                label=COPY["results-about"].format(count=f"{result.estimated_count:,}"),
                css_classes=["dimmed"],
                halign=Gtk.Align.START,
            )
            self.results_box.append(header)
        else:
            self._drop_load_more()

        group = Adw.PreferencesGroup()
        for record in result.extensions:
            group.add(self._result_row(record))
        self.results_box.append(group)

        if result.has_next:
            more_group = Adw.PreferencesGroup()
            more = Adw.ButtonRow(title=COPY["load-more"], start_icon_name="view-more-symbolic")
            more.connect("activated", lambda *_a, p=result.page + 1: self._run_query(page=p))
            more_group.add(more)
            self._load_more = more_group
            self.results_box.append(more_group)
        else:
            self._load_more = None

        self.discover_stack.set_visible_child_name("results")
        if page > 1:
            # Appending moves the view; putting it back is the difference
            # between "more results" and "the page jumped".
            def _restore() -> bool:
                self.results_scroll.get_vadjustment().set_value(keep_scroll)
                return GLib.SOURCE_REMOVE

            self._sources.append(GLib.idle_add(_restore))

    def _drop_load_more(self) -> None:
        existing = getattr(self, "_load_more", None)
        if existing is not None:
            self.results_box.remove(existing)
            self._load_more = None

    def _result_row(self, record: ExtensionRecord) -> Adw.ActionRow:
        row = Adw.ActionRow(activatable=True, use_markup=False)
        row.set_title(display_name(record.uuid, record.name))
        row.set_subtitle(summary_of(record.description))
        icon = Gtk.Image(icon_name="application-x-addon-symbolic", pixel_size=32)
        row.add_prefix(icon)
        if record.icon:
            self._load_picture(record.icon, icon, size=32)

        if self.shell is not None and record.uuid in self.shell.all:
            # Already here. The useful action for this one is a switch, and
            # that lives in Installed; offering "Add" again would be a button
            # that either does nothing or asks the desktop to add it twice.
            row.add_suffix(
                Gtk.Label(
                    label=COPY["added"],
                    css_classes=["dimmed", "caption"],
                    valign=Gtk.Align.CENTER,
                )
            )
        elif not self._supports(record):
            row.add_suffix(
                Gtk.Label(
                    label=COPY["not-compatible-badge"],
                    css_classes=["dimmed", "caption"],
                    valign=Gtk.Align.CENTER,
                )
            )
        else:
            button = Gtk.Button(
                label=COPY["add"], valign=Gtk.Align.CENTER, css_classes=["suggested-action"]
            )
            button.connect("clicked", lambda *_a, r=record, b=button: self._add(r, b))
            row.add_suffix(button)
        row.connect("activated", lambda *_a, r=record: self._show_details(r))
        return row

    def _supports(self, record: ExtensionRecord) -> bool:
        """Compatibility, decided from the library's own list of builds.

        A page of search results carries no build list at all, so an add-on
        whose compatibility is simply unknown is offered rather than refused —
        the install path checks again with the full entry in hand before
        anything is downloaded.
        """
        if not record.shell_version_map:
            return True
        return record.supports(self._shell_version())

    def _shell_version(self) -> str:
        if self.shell is None:
            return FALLBACK_GNOME_VERSION
        try:
            return self.shell.proxy.shell_version() or FALLBACK_GNOME_VERSION
        except Exception:  # noqa: BLE001 - the desktop stopped answering
            return FALLBACK_GNOME_VERSION

    # -- adding ------------------------------------------------------------

    def _add(self, record: ExtensionRecord, button: Gtk.Button) -> None:
        """Ask the desktop to add an add-on. Once. Ever.

        A second request for an add-on already being confirmed re-imports code
        the desktop has already loaded, and the resulting state is only cleared
        by logging out. So a request that is still outstanding is answered with
        a sentence, not with another request.
        """
        if self.installer is None:
            return
        if record.uuid in self._installs:
            self._toast(COPY["already-adding"])
            return
        button.set_sensitive(False)
        button.set_label(COPY["adding"])
        self._installs[record.uuid] = None

        watcher = self.installer.install_live(
            record.uuid,
            lambda report, b=button: self._install_answered(report, b),
            record=record,
            on_dialog=self._toast,
        )
        if watcher is None:
            # Nothing was asked for: the add-on is already running, or it has
            # no build for this GNOME. Either way the installer has already
            # called back with the sentence, and the button is already right.
            self._installs.pop(record.uuid, None)
            return
        self._installs[record.uuid] = watcher
        watcher.on_active = lambda _ext, u=record.uuid, b=button: self._resolve_pending(u, b)

    def _install_answered(self, report: InstallReport, button: Gtk.Button) -> None:
        if report.outcome is InstallOutcome.WAITING_FOR_CONFIRMATION:
            # The confirmation box is still on screen. Wait for it — by asking
            # what happened, never by asking again for the install.
            self._toast(report.message)
            self._polls[report.uuid] = 0
            source = GLib.timeout_add_seconds(
                PENDING_POLL_SECONDS,
                lambda u=report.uuid, b=button: self._poll_pending(u, b),
            )
            self._sources.append(source)
            return
        self._finish_install(report, button)

    def _poll_pending(self, uuid: str, button: Gtk.Button) -> bool:
        """Ask what became of a confirmation box that is still on screen.

        Only ever asks. The install request itself is never repeated, and the
        asking stops after a while so that a box nobody ever answers does not
        leave a timer running for the rest of the session.
        """
        watcher = self._installs.get(uuid)
        if watcher is None or self.installer is None:
            return GLib.SOURCE_REMOVE
        self._polls[uuid] = self._polls.get(uuid, 0) + 1
        report = self.installer.resolve_pending(uuid, watcher)
        if report.outcome is InstallOutcome.WAITING_FOR_CONFIRMATION:
            if self._polls[uuid] >= PENDING_POLL_LIMIT:
                self._installs.pop(uuid, None)
                watcher.disarm()
                button.set_label(COPY["add"])
                button.set_sensitive(True)
                return GLib.SOURCE_REMOVE
            return GLib.SOURCE_CONTINUE
        self._finish_install(report, button)
        return GLib.SOURCE_REMOVE

    def _resolve_pending(self, uuid: str, button: Gtk.Button) -> None:
        watcher = self._installs.get(uuid)
        if watcher is None or self.installer is None:
            return
        self._finish_install(self.installer.resolve_pending(uuid, watcher), button)

    def _finish_install(self, report: InstallReport, button: Gtk.Button) -> None:
        self._installs.pop(report.uuid, None)
        self._toast(report.message)
        if report.transaction is not None:
            # The package path plans the switching-on rather than doing it, so
            # that a Look adding three add-ons is one change and not three.
            # Here there is one, and applying it is this page's job.
            try:
                report.transaction.apply()
            except Exception:  # noqa: BLE001 - the sentence above already told the truth
                pass
        if report.ok:
            button.set_label(COPY["added"])
            button.set_sensitive(False)
        else:
            button.set_label(COPY["add"])
            button.set_sensitive(True)

    # -- details -----------------------------------------------------------

    def _show_details(self, record: ExtensionRecord) -> Adw.Dialog:
        """Everything known about one add-on, including what people said."""
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=12,
            margin_bottom=24,
            margin_start=12,
            margin_end=12,
        )

        picture = Gtk.Picture(
            content_fit=Gtk.ContentFit.CONTAIN, height_request=220, css_classes=["card"]
        )
        box.append(picture)
        if record.screenshot:
            self._load_picture(record.screenshot, picture)
        else:
            picture.set_visible(False)
            box.append(Gtk.Label(label=COPY["no-picture"], css_classes=["dimmed"]))

        title = Gtk.Label(
            label=display_name(record.uuid, record.name),
            css_classes=["title-2"],
            halign=Gtk.Align.START,
            wrap=True,
        )
        box.append(title)
        if record.creator:
            box.append(
                Gtk.Label(
                    label=COPY["by-author"].format(author=record.creator),
                    css_classes=["dimmed"],
                    halign=Gtk.Align.START,
                )
            )
        if record.downloads:
            box.append(
                Gtk.Label(
                    label=COPY["downloads"].format(count=f"{record.downloads:,}"),
                    css_classes=["dimmed"],
                    halign=Gtk.Align.START,
                )
            )

        rating_label = Gtk.Label(
            label=COPY["no-rating"], css_classes=["dimmed"], halign=Gtk.Align.START
        )
        box.append(rating_label)
        box.append(
            Gtk.Label(
                label=" ".join((record.description or "").split()),
                wrap=True,
                halign=Gtk.Align.START,
                xalign=0.0,
            )
        )

        reviews = Adw.PreferencesGroup(title=COPY["reviews"])
        box.append(reviews)

        header = Adw.HeaderBar()
        view = Adw.ToolbarView(content=self._scrolled(box))
        view.add_top_bar(header)
        dialog = Adw.Dialog(
            title=display_name(record.uuid, record.name),
            content_width=620,
            content_height=720,
            child=view,
        )

        if self.client is not None:
            self.client.rating(record.uuid, lambda r, e: self._fill_rating(rating_label, r, e))
            if record.pk:
                self.client.comments(
                    record.pk, lambda c, e: self._fill_comments(reviews, c, e)
                )

        return self._present(dialog)

    @staticmethod
    def _fill_rating(label: Gtk.Label, rating: Any, error: Any) -> None:
        if error is not None or rating is None or rating.stars is None:
            return
        label.set_label(
            COPY["rating"].format(stars=f"{rating.stars:g}", count=f"{rating.rated:,}")
        )

    @staticmethod
    def _fill_comments(group: Adw.PreferencesGroup, comments: Any, error: Any) -> None:
        """Reviews, as text. The library sends markup it built from what people
        typed, and this app never hands that to anything that would render it.
        """
        if error is not None or not comments:
            group.add(Adw.ActionRow(title=COPY["no-reviews"], sensitive=False))
            return
        for comment in list(comments)[:5]:
            row = Adw.ActionRow(use_markup=False)
            row.set_title(comment.author or "Someone")
            row.set_subtitle(comment.plain_text)
            row.set_subtitle_lines(0)
            group.add(row)

    def _load_picture(self, url: str, target: Gtk.Widget, *, size: int | None = None) -> None:
        """Fetch one picture and put it in one widget, or quietly do neither.

        A picture is decoration. Nothing here retries, and nothing here reports
        a failure to the user: an add-on with a broken screenshot is still an
        add-on they can read about and install.
        """
        if self.client is None:
            return

        def _got(body: bytes | None, error: Any) -> None:
            if error is not None or not body or len(body) > MAX_SCREENSHOT_BYTES:
                return
            try:
                texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(body))
            except GLib.Error:
                return
            if isinstance(target, Gtk.Image):
                target.set_from_paintable(texture)
                if size:
                    target.set_pixel_size(size)
            elif isinstance(target, Gtk.Picture):
                target.set_paintable(texture)

        self.client.transport.get(url, _got)

    # -- updates -----------------------------------------------------------

    def _fill_updates_idle_state(self) -> None:
        box = self.updates_view
        self._clear(box)
        if not self.available or self.checker is None:
            box.append(self._unavailable_page())
            return
        box.append(self._check_button())
        box.append(
            Gtk.Label(
                label=COPY["updates-body"],
                css_classes=["dimmed"],
                wrap=True,
                halign=Gtk.Align.START,
            )
        )

    def _check_button(self) -> Adw.PreferencesGroup:
        """The "look again" button. Shown before a check and after every one."""
        group = Adw.PreferencesGroup()
        button = Adw.ButtonRow(title=COPY["check"], start_icon_name="view-refresh-symbolic")
        button.connect("activated", lambda *_a: self._check_updates())
        group.add(button)
        return group

    def _check_updates(self) -> None:
        if self.checker is None:
            return
        self._clear(self.updates_view)
        spinner = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, vexpand=True
        )
        spinner.append(Adw.Spinner(width_request=48, height_request=48))
        spinner.append(Gtk.Label(label=COPY["checking"], css_classes=["dimmed"]))
        self.updates_view.append(spinner)
        self.checker.check(self._on_update_list)

    def _on_update_list(
        self, candidates: list[UpdateCandidate] | None, error: EgoError | None
    ) -> None:
        box = self.updates_view
        self._clear(box)
        if error is not None or candidates is None:
            box.append(
                Adw.StatusPage(
                    icon_name="network-offline-symbolic",
                    title=COPY["check-failed-title"],
                    description=UPDATE_COPY["check-failed"],
                    vexpand=True,
                )
            )
            box.append(self._check_button())
            return
        if not candidates:
            box.append(
                Adw.StatusPage(
                    icon_name="object-select-symbolic",
                    title=COPY["up-to-date-title"],
                    description=UPDATE_COPY["up-to-date"],
                    vexpand=True,
                )
            )
            box.append(self._check_button())
            self._badge(0)
            return

        real = [c for c in candidates if c.verdict is not UpdateVerdict.WITHDRAWN]
        self._badge(len(real))
        group = Adw.PreferencesGroup(
            title=COPY["updates-title"], description=COPY["updates-body"]
        )
        if real:
            all_button = Gtk.Button(
                label=COPY["update-all"],
                valign=Gtk.Align.CENTER,
                css_classes=["suggested-action"],
            )
            all_button.connect("clicked", lambda *_a, c=list(real): self._update_all(c))
            group.set_header_suffix(all_button)

        for candidate in candidates:
            group.add(self._update_row(candidate))
        box.append(group)
        box.append(self._check_button())

    def _update_row(self, candidate: UpdateCandidate) -> Adw.ActionRow:
        name = display_name(candidate.uuid, self._name_of(candidate.uuid))
        if candidate.verdict is UpdateVerdict.WITHDRAWN:
            withdrawn = Adw.ActionRow(sensitive=False, use_markup=False)
            withdrawn.set_title(name)
            withdrawn.set_subtitle(UPDATE_COPY["withdrawn"])
            return withdrawn
        row = Adw.ActionRow(use_markup=False)
        row.set_title(name)
        button = Gtk.Button(label=COPY["update"], valign=Gtk.Align.CENTER)
        button.connect(
            "clicked", lambda *_a, c=candidate, r=row, b=button: self._update_one(c, r, b)
        )
        row.add_suffix(button)
        return row

    def _update_all(self, candidates: Iterable[UpdateCandidate]) -> None:
        for candidate in candidates:
            self._update_one(candidate, None, None)

    def _update_one(
        self,
        candidate: UpdateCandidate,
        row: Adw.ActionRow | None,
        button: Gtk.Button | None,
    ) -> None:
        """Look the exact build up, fetch it, and leave it where the desktop
        looks at the next log-in. Nothing is put over a running add-on.
        """
        if self.checker is None:
            return
        if button is not None:
            button.set_sensitive(False)

        def _staged(path: Any, error: Exception | None) -> None:
            if error is not None or path is None:
                self._toast(COPY["update-failed"])
                if button is not None:
                    button.set_sensitive(True)
                return
            self._toast(UPDATE_COPY["staged"])
            if row is not None:
                row.set_subtitle(UPDATE_COPY["staged"])
            if button is not None:
                button.set_visible(False)

        def _resolved(resolved: UpdateCandidate | None, error: EgoError | None) -> None:
            if error is not None or resolved is None:
                self._toast(COPY["update-failed"])
                if button is not None:
                    button.set_sensitive(True)
                return
            if resolved.verdict is UpdateVerdict.WITHDRAWN:
                if row is not None:
                    row.set_subtitle(UPDATE_COPY["withdrawn"])
                if button is not None:
                    button.set_visible(False)
                return
            if self.checker is not None:
                self.checker.download_and_stage(resolved, _staged)

        self.checker.resolve(candidate, _resolved)

    def _badge(self, count: int) -> None:
        page = self.stack.get_page(self.stack.get_child_by_name("updates"))
        if page is not None:
            page.set_badge_number(count)

    # -- odds and ends -----------------------------------------------------

    @staticmethod
    def _clear(box: Gtk.Box) -> None:
        child = box.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            box.remove(child)
            child = following

    def _present(self, dialog: Adw.Dialog) -> Adw.Dialog:
        """Show a dialog, if there is a window for it to appear in.

        A dialog belongs to a window. When this page is not in one — which is
        the case in the test suite, and only there — the dialog is built and
        handed back unshown, so that a test can look at what a click produced
        without anything appearing on the screen of whoever is running it.
        """
        root = self.get_root()
        if isinstance(root, Gtk.Window):
            dialog.present(root)
        return dialog

    def _show_status(self, stack: Gtk.Stack, page: Adw.StatusPage) -> None:
        existing = stack.get_child_by_name("empty")
        if existing is not None:
            stack.remove(existing)
        stack.add_named(page, "empty")
        stack.set_visible_child_name("empty")

    def _toast(self, text: str) -> None:
        toast = getattr(self.window, "toast", None)
        if callable(toast):
            toast(text)

    def _drop_source(self, source: int) -> None:
        """Take one idle or timer out, if it has not already finished.

        A source that ran to completion has taken itself out, and asking for it
        again logs a critical warning about an id that was not found. Looking
        first is the difference between a clean teardown and a page that
        complains on the way out.
        """
        if source in self._sources:
            self._sources.remove(source)
        found = GLib.MainContext.default().find_source_by_id(source)
        if found is not None and not found.is_destroyed():
            GLib.source_remove(source)

    def teardown(self) -> None:
        """Stop listening to everything. Safe to call twice.

        Called when the page is destroyed, and callable by hand — a page that
        left a timer and a bus subscription behind would keep asking the
        desktop about an add-on nobody is looking at any more.
        """
        for source in list(self._sources):
            self._drop_source(source)
        self._sources.clear()
        for watcher in list(self._installs.values()):
            if watcher is not None:
                watcher.disarm()
        self._installs.clear()
        if self.shell is None:
            return
        if self._owns_shell:
            self.shell.close()
        else:
            # Borrowed. Take back only what this page put in.
            self.shell.disconnect(self._on_extension_changed)
