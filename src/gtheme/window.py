"""The application window: sidebar, content area, and everything shared.

The sidebar is built by walking ``ui.registry.MANIFEST``, never by hand. A page
therefore cannot exist without appearing here, and cannot appear here without
existing — which is the property that lets fifteen pages be written in
parallel by people who never read each other's code.

Page widgets are built lazily, the first time a page is selected, and then
cached. Fifteen eager imports would pull every scanner and network client the
app has into the path between clicking the launcher and seeing a window.

**What the window owns, that pages borrow.** Every page was written against a
duck-typed window and works without one; this class is the real thing they were
written for.

* ``rows`` — the :class:`~gtheme.ui.rowindex.RowIndex`. Pages register rows into
  it as they build them; search deep-links through it and the live-mirroring
  below refreshes through it.
* ``schema_probe`` — ONE probe per window. Building a second one throws away a
  memoised scan of every schema on the machine, and there are fifteen pages.
* ``shell`` — ONE connection to the running desktop's add-on service, shared by
  the Add-ons page and the Home page's add-on summary. The page that used to
  own it also used to close it; a shared object is closed by its owner, which
  is now this window.
* ``prefs``, ``toasts``, ``toast()``, ``show_page()`` — the four things pages
  reach for by name.

**Live mirroring.** If somebody changes the accent colour in GNOME's own
Settings while gtheme is open, gtheme's row follows. Every schema that has a
row on screen gets a ``changed`` subscription, and a change turns back into the
one row that shows it. Nothing here writes a setting: a mirror that writes is a
feedback loop.
"""

from __future__ import annotations

import inspect
import json
import os
import platform
import sys
import threading
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, __version__  # noqa: E402
from .prefs import Prefs  # noqa: E402
from .ui import onboarding, registry  # noqa: E402
from .ui import search as ui_search  # noqa: E402
from .ui.applyrunner import ApplyRunner  # noqa: E402
from .ui.rowindex import RowIndex  # noqa: E402

__all__ = [
    "ASK_DESKTOP",
    "ASK_LIBADWAITA",
    "COPY",
    "DEFAULT_HEIGHT",
    "DEFAULT_WIDTH",
    "MINIMUM_GNOME",
    "MINIMUM_LIBADWAITA",
    "DesktopVerdict",
    "Window",
    "check_desktop",
    "details_text",
    "fit_to_monitor",
    "is_text_editing",
    "libadwaita_version",
    "monitor_size",
    "unfinished_changes",
]


#: Every sentence this window says, in one place, so the wording can be
#: reviewed as a whole and linted as a whole.
COPY: dict[str, str] = {
    "undo-button": "Undo last change",
    "search-tooltip": "Search everything in this app (Ctrl+F)",
    "menu-tooltip": "Main menu",
    "menu-search": "Search",
    "menu-undo": "Undo last change",
    "menu-details": "Copy details for a bug report",
    "menu-shortcuts": "Keyboard shortcuts",
    "menu-about": "About Gtheme",
    "menu-quit": "Quit",
    # -- the "this is not the desktop I am for" screen
    "wrong-desktop-title": "gtheme is made for the GNOME desktop",
    "wrong-desktop-body": (
        "This computer is running something else, so gtheme cannot change how it "
        "looks. Nothing has been altered. You can close this window safely."
    ),
    "old-desktop-title": "This version of GNOME is older than gtheme expects",
    "old-desktop-body": (
        "gtheme needs GNOME {minimum} or newer. On an older one it would offer "
        "settings your computer does not have. Nothing has been altered, and you "
        "can close this window safely."
    ),
    # "Too old" and "could not tell" are different answers and get different
    # sentences. Saying "too old" to somebody whose desktop simply did not
    # answer sends them looking for an upgrade they do not need.
    "unknown-desktop-title": "gtheme could not tell what this computer is running",
    "unknown-desktop-body": (
        "gtheme asks the desktop what it is before it changes anything, and this "
        "time nothing answered. Rather than guess and risk changing the wrong "
        "thing, it has stopped. Nothing has been altered. If you are logged in to "
        "a GNOME desktop, open gtheme again from your list of apps."
    ),
    # -- copying the details a bug report asks for
    "details-copied": "Details copied. Paste them into your bug report.",
    "details-failed": "The details could not be copied.",
    # -- the change that was interrupted last time
    "unfinished-title": "The last change did not finish",
    "unfinished-body": (
        "gtheme was in the middle of changing your desktop when it stopped. Part "
        "of the change may have gone through. You can put things back the way "
        "they were before it started."
    ),
    "unfinished-dismiss": "Leave it",
    "unfinished-restore": "Put things back",
    # -- the keyboard list
    "shortcuts-window-title": "Keyboard Shortcuts",
    "shortcuts-group": "Getting around",
    "shortcut-search": "Search everything",
    "shortcut-undo": "Undo the last change",
    "shortcut-sidebar": "Jump to the list on the left",
    "shortcut-help": "Show this list",
    "shortcut-about": "About Gtheme",
    "shortcut-quit": "Close Gtheme",
    # -- shared outcomes
    "page-broken": "This page could not be opened.",
    "undo": "Undo",
    "undo-tooltip": "Go back to “{moment}”",
    "undo-unavailable": (
        "Undo could not be opened. Open Undo & Restore Points from the list on the left."
    ),
    "undo-nothing": "There is no saved moment to go back to yet.",
    # There is deliberately no "undo-done" here any more. It said "Put back how
    # it was." and did not say what "it" was; the sentence now comes from
    # ``restore.done_sentence``, which names the moment and is the same sentence
    # the Undo page and the Home card say about the same event (U8).
    "undo-failed": "gtheme could not put everything back. Open Undo & Restore Points.",
    "undo-heading": "Putting your desktop back",
    "undo-starting": "Going back to how it was…",
}

#: The oldest GNOME gtheme is willing to describe. Below this the descriptor
#: corpus offers settings the desktop does not have, which is worse than saying
#: no: it is a list of promises that quietly do nothing.
#:
#: 49, not 47. The sidebar of this window is built out of ``Adw.Sidebar``,
#: ``Adw.SidebarSection``, ``Adw.SidebarItem`` and ``Adw.SidebarMode``, every
#: one of which arrived in libadwaita 1.9 — which is what GNOME 49 and 50 ship
#: and what README states as the floor. A gate of 47 was a promise the window
#: could not keep: on a GNOME 47 or 48 desktop the verdict said "yes" and the
#: window then died on a missing widget. The gate now says no, and the screen
#: that says so is built out of widgets that have existed for years.
MINIMUM_GNOME = 49

#: The libadwaita the sidebar is built out of, as (major, minor).
#:
#: This is the question the gate actually wants answered, and unlike the
#: desktop's version it can always be answered: libadwaita is linked into this
#: process, so ``Adw.get_major_version()`` cannot time out, cannot need a
#: session bus and cannot be absent. The GNOME version over D-Bus was only ever
#: a *proxy* for it — and a proxy that returns nothing on a slow login, in a
#: terminal, or over ssh, where the old gate read "no answer" as "go ahead" and
#: walked straight back into the ``Adw.Sidebar`` crash its own comment said was
#: fixed (persona-report §3.1, X2).
MINIMUM_LIBADWAITA = (1, 9)

#: How small the window is allowed to go. Also the floor every clamp stops at.
MINIMUM_WIDTH = 360
MINIMUM_HEIGHT = 294

#: Room left around the window when the screen is smaller than the size it
#: wants. Horizontal is a margin; vertical also has to clear the top bar, which
#: a window opening at the full height of the screen would sit under.
SCREEN_MARGIN_X = 32
SCREEN_MARGIN_Y = 96

#: Where somebody who is stuck is sent. The metainfo names the same page as its
#: ``<url type="help">``; About never showed it, because the appdata route
#: needs a GResource this project does not build (persona-report §3.1).
SUPPORT_URL = "https://github.com/blyatiful1/gtheme/blob/main/docs/start-here.md"

#: How much of the log the "copy details" button takes. Enough to hold the
#: launch line and what happened after it; short enough to paste into a form.
LOG_TAIL_LINES = 40
LOG_TAIL_CHARS = 8000

#: The name ``core.transaction`` gives the temporary directory it records a
#: change into before making it. Left behind, it is the one durable sign that a
#: gtheme was killed in the middle of an apply — every path that runs Python,
#: including the interrupt path, deletes it (E6). A test pins this constant
#: against the engine's own spelling, because a rename over there would
#: otherwise turn this notice off in silence.
JOURNAL_PREFIX = "gtheme-rollback-"

#: Preference holding the journals already answered for, newest last.
DISMISSED_UNFINISHED_KEY = "unfinished/dismissed"
DISMISSED_LIMIT = 10

#: What size the window opens at the first time, before anyone has resized it.
#:
#: The old default was 1000x720, which cut the sidebar off in the middle of its
#: last section: "Safety" — the one holding Undo & Restore Points — was the
#: heading a first-time user could not see. The sidebar asks for 826px of
#: content plus its header bar, so the height is what actually matters here;
#: 900 clears it with room to spare, and 1200 is the width the README's
#: screenshots are taken at (``packaging.md`` §7), so a first run and a picture
#: of a first run are the same shape. Neither is a *minimum* — ``width_request``
#: and ``height_request`` still let the window go down to 360x294, and a size
#: the user chose is restored over this by :meth:`Window._restore_window_state`.
#:
#: It is a *wish*, not a size: :func:`fit_to_monitor` shrinks it to whatever
#: screen the window is opening on. 1200x900 is bigger than a 1920x1080 screen
#: at 200% scaling, which reports 960x540 in the units a window is measured in
#: — so the app that exists to make a desktop usable opened off the bottom of
#: the screen for the person most likely to be scaling it up (persona-report
#: §2.10).
DEFAULT_WIDTH = 1200
DEFAULT_HEIGHT = 900


class DesktopVerdict:
    """Whether gtheme can run here, and what to say if not.

    A tiny class rather than a tuple because the "not here" case has two
    genuinely different sentences and the caller must not have to remember
    which order they came in.
    """

    __slots__ = ("body", "ok", "title")

    def __init__(self, ok: bool, title: str = "", body: str = "") -> None:
        self.ok = ok
        self.title = title
        self.body = body

    def __repr__(self) -> str:  # pragma: no cover - debugging only
        return f"DesktopVerdict(ok={self.ok!r}, title={self.title!r})"


class _AskLibadwaita:
    """Sentinel: work the answer out from the libadwaita in this process."""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging only
        return "ASK_LIBADWAITA"


#: Default for ``check_desktop(adw_version=…)``. A test passes a tuple to
#: describe a machine it is not running on, or ``None`` to describe one whose
#: desktop pieces could not be identified at all.
ASK_LIBADWAITA = _AskLibadwaita()


def libadwaita_version() -> tuple[int, int] | None:
    """The libadwaita this process is linked against, as (major, minor).

    None only if the question itself fails, which would mean a broken install
    rather than an old one — and that is a different sentence, not a shrug.
    """
    try:
        return int(Adw.get_major_version()), int(Adw.get_minor_version())
    except Exception:  # noqa: BLE001 - an answer that will not come is not an answer
        return None


def check_desktop(
    *,
    current_desktop: str | None = None,
    version: str | None = None,
    adw_version: tuple[int, int] | None | _AskLibadwaita = ASK_LIBADWAITA,
) -> DesktopVerdict:
    """Can gtheme honestly do anything on this computer?

    Three answers, not two, because "this desktop is too old" and "this desktop
    would not say what it is" are different things to be told and lead to
    different next steps.

    The version that decides is libadwaita's, not the desktop's. Everything the
    window is built out of — ``Adw.Sidebar`` and its three companions — arrived
    in libadwaita 1.9, and libadwaita is linked into this process, so the
    question always gets an answer. The desktop's own version comes over D-Bus
    and does not: on a slow login, in a terminal or over ssh it is simply
    absent. Treating that absence as permission to proceed is what put the
    ``Adw.Sidebar`` ``AttributeError`` back in front of exactly the people the
    polite screen was written for (persona-report §3.1, X2).

    Args:
        current_desktop: what the session calls itself. None reads the
            environment, which is what the real window does.
        version: the desktop's version, if it could be asked. None means it
            could not be — ordinary, and on its own not a refusal.
        adw_version: the libadwaita to judge against. Left alone this is read
            from the running one; ``None`` means it could not be read.

    Returns:
        A verdict. ``ok`` false carries the whole screen to show instead.
    """
    session = current_desktop if current_desktop is not None else os.environ.get(
        "XDG_CURRENT_DESKTOP", ""
    )
    if session and "gnome" not in session.lower():
        return DesktopVerdict(
            False, COPY["wrong-desktop-title"], COPY["wrong-desktop-body"]
        )

    pieces = libadwaita_version() if isinstance(adw_version, _AskLibadwaita) else adw_version
    major = _major(version)

    too_old = (major is not None and major < MINIMUM_GNOME) or (
        pieces is not None and pieces < MINIMUM_LIBADWAITA
    )
    if too_old:
        return DesktopVerdict(
            False,
            COPY["old-desktop-title"],
            COPY["old-desktop-body"].format(minimum=MINIMUM_GNOME),
        )
    if pieces is None and major is None:
        # Nothing here can be checked: the desktop said nothing and the pieces
        # this window is made of could not be identified either. The sidebar
        # would be built on a guess, and the guess is the crash.
        return DesktopVerdict(
            False, COPY["unknown-desktop-title"], COPY["unknown-desktop-body"]
        )
    return DesktopVerdict(True)


def _major(version: str | None) -> int | None:
    if not version:
        return None
    head = str(version).split(".", 1)[0].strip()
    return int(head) if head.isdigit() else None


class Window(Adw.ApplicationWindow):
    """The one window gtheme has."""

    __gtype_name__ = "GthemeWindow"

    def __init__(
        self,
        prefs: Prefs | None = None,
        *,
        probe: Any = None,
        shell: Any = None,
        ask_desktop: bool = True,
        verdict: DesktopVerdict | None = None,
        mirror: bool = True,
        **kwargs: Any,
    ) -> None:
        width, height = fit_to_monitor(DEFAULT_WIDTH, DEFAULT_HEIGHT, monitor_size())
        super().__init__(
            title="Gtheme",
            default_width=width,
            default_height=height,
            width_request=MINIMUM_WIDTH,
            height_request=MINIMUM_HEIGHT,
            **kwargs,
        )
        self.prefs = prefs if prefs is not None else Prefs()
        #: Where pages register their rows so search, deep links and live
        #: mirroring can find them again.
        self.rows = RowIndex()
        #: One probe per window (see the module docstring). ``_style_common``
        #: looks for exactly this attribute name.
        self.schema_probe = probe if probe is not None else _build_probe()
        #: One connection to the running desktop's add-on service, or None when
        #: there is no desktop answering. Built on first use, because most
        #: sessions never open the Add-ons page.
        self._shell = shell
        #: ``ask_desktop=False`` means never reach for the session bus at all.
        #: The tests use it: a unit test that quietly opens a connection to the
        #: developer's running desktop is a unit test that behaves differently
        #: on the machine that wrote it than anywhere else.
        self._shell_asked = shell is not None or not ask_desktop
        self._shell_is_ours = shell is None
        #: The connection is now built from a worker thread as well as from the
        #: main loop — the Home page's add-on count asks for it off the main
        #: loop so the window is never held up by ``ListExtensions``
        #: (review-report M26). Two threads racing the "not asked yet" check
        #: would build two connections, which is two subscriptions to the same
        #: signal and one of them leaked.
        self._shell_lock = threading.Lock()
        #: Kept apart from ``_shell_asked``: the version read below is allowed
        #: to touch the bus without *building* the shared connection, and it
        #: has to know whether it is allowed to touch it at all.
        self._ask_desktop = ask_desktop

        self.runner = ApplyRunner(self)

        self._pages: dict[str, Gtk.Widget] = {}
        self._shells: dict[str, Any] = {}
        self._order: list[registry.PageDescriptor] = []
        self._watchers: dict[str, Gio.Settings] = {}
        self._mirror = mirror
        self._mirror_pending = False
        self._search_index: ui_search.SearchIndex | None = None
        self._home: Any = None

        registry.check_sections()

        self.verdict = verdict if verdict is not None else check_desktop(
            version=self._shell_version()
        )

        # The app half of the window is built only when there is a desktop to
        # build it for. Its sidebar needs libadwaita 1.9, which is exactly what
        # a desktop below MINIMUM_GNOME does not have — so building it anyway
        # replaced the polite "this is too old" screen with a traceback, for
        # precisely the audience that screen was written for.
        self.sidebar: Adw.Sidebar | None = None
        self.split: Adw.NavigationSplitView | None = None
        #: The header's way back. Built with the header, not by whichever page
        #: happens to be opened first (review-report L6). None on the "not
        #: here" screen, which has nothing to undo.
        self.undo_button: Gtk.Button | None = None

        self._root = Gtk.Stack()
        if self.verdict.ok:
            self.sidebar = self._build_sidebar()
            self.split = self._build_split()
            self._root.add_named(self.split, "app")
        self._root.add_named(self._build_unsupported(), "unsupported")
        self._root.set_visible_child_name("app" if self.verdict.ok else "unsupported")

        self.toasts = Adw.ToastOverlay(child=self._root)
        self.set_content(self.toasts)

        if self.verdict.ok:
            # Below this width the sidebar becomes a page of its own and the
            # split view navigates between the two, instead of squeezing both
            # onto a screen that cannot hold them.
            breakpoint_ = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 550sp"))
            breakpoint_.add_setter(self.split, "collapsed", True)
            breakpoint_.add_setter(self.sidebar, "mode", Adw.SidebarMode.PAGE)
            self.add_breakpoint(breakpoint_)

        self._restore_window_state()
        self.connect("close-request", self._on_close)

        if self.verdict.ok:
            self._install_shortcuts()
            self.show_page(self._first_page())

    # -- construction ------------------------------------------------------

    def _build_sidebar(self) -> Adw.Sidebar:
        sidebar = Adw.Sidebar()
        for section_title in registry.SECTIONS:
            pages = registry.pages_in_section(section_title)
            if not pages:
                continue
            section = Adw.SidebarSection(title=section_title)
            for page in pages:
                section.append(
                    Adw.SidebarItem(
                        title=page.title,
                        subtitle=page.subtitle or "",
                        icon_name=page.icon,
                        tooltip=page.subtitle or page.title,
                    )
                )
                self._order.append(page)
            sidebar.append(section)
        sidebar.connect("activated", self._on_sidebar_activated)
        return sidebar

    def _build_split(self) -> Adw.NavigationSplitView:
        sidebar_bar = Adw.HeaderBar()
        sidebar_bar.pack_end(
            Gtk.MenuButton(
                icon_name="open-menu-symbolic",
                primary=True,
                tooltip_text=COPY["menu-tooltip"],
                menu_model=self._menu_model(),
            )
        )
        sidebar_view = Adw.ToolbarView(content=self.sidebar)
        sidebar_view.add_top_bar(sidebar_bar)

        self.header = Adw.HeaderBar()
        self.undo_button = self._build_undo_button()
        self.header.pack_start(self.undo_button)
        self.header.pack_end(
            Gtk.Button(
                icon_name="system-search-symbolic",
                tooltip_text=COPY["search-tooltip"],
                action_name="win.search",
            )
        )
        self.content_view = Adw.ToolbarView()
        self.content_view.add_top_bar(self.header)
        self.content_page = Adw.NavigationPage(title="Home", child=self.content_view)

        return Adw.NavigationSplitView(
            min_sidebar_width=220,
            max_sidebar_width=300,
            sidebar=Adw.NavigationPage(title="Gtheme", child=sidebar_view),
            content=self.content_page,
        )

    def _build_undo_button(self) -> Gtk.Button:
        """The header's way back: an icon **and** the word, built by the window.

        Two defects, one button (review-report L6, persona-report §2.8). It
        used to be built by the Home page and packed as a side effect of that
        page happening to be opened — so somebody whose last session ended on
        Wallpaper reopened gtheme with no undo in the header at all, for the
        whole session. And it was built as ``Gtk.Button(label=…,
        icon_name=…)``, where the icon silently replaces the label: every
        screenshot shows a bare back-arrow in the position a Windows user reads
        as "Back". ``Adw.ButtonContent`` is the widget that shows both, and the
        window builds its own header.
        """
        button = Gtk.Button(has_tooltip=True)
        button.set_child(
            Adw.ButtonContent(icon_name="edit-undo-symbolic", label=COPY["undo-button"])
        )
        # Not ``action_name``: the shortcut has to let a text box being typed
        # in keep its own Ctrl+Z (see :meth:`undo_shortcut`), and a click on
        # this button is never ambiguous in that way.
        button.connect("clicked", lambda *_a: self.undo_last_change())
        button.connect("query-tooltip", self._on_undo_tooltip)
        return button

    def _on_undo_tooltip(self, _button: Gtk.Widget, _x: int, _y: int, _kb: bool, tooltip: Any) -> bool:
        """Name the moment, and only when somebody is actually looking.

        Read on hover rather than kept up to date: the answer costs a directory
        listing, and computing it at startup or after every change would spend
        that on the overwhelming majority of sessions where nobody ever points
        at this button.
        """
        tooltip.set_text(self.undo_tooltip_text())
        return True

    def undo_tooltip_text(self) -> str:
        """"Go back to <the moment>", or the honest sentence when there is none."""
        from .core import restorepoints

        try:
            points = [p for p in restorepoints.list_restore_points() if p.kind != "pristine"]
        except Exception:  # noqa: BLE001 - a tooltip is never worth an error
            points = []
        if not points:
            return COPY["undo-nothing"]
        return COPY["undo-tooltip"].format(moment=points[0].label)

    def _menu_model(self) -> Gio.Menu:
        menu = Gio.Menu()
        first = Gio.Menu()
        first.append(COPY["menu-search"], "win.search")
        first.append(COPY["menu-undo"], "win.undo")
        menu.append_section(None, first)

        second = Gio.Menu()
        second.append(onboarding.MENU_LABEL, "win.onboarding")
        second.append(COPY["menu-shortcuts"], "win.show-help-overlay")
        # The one button that answers "what do I send them?" for somebody
        # helping a relative over the phone. In the menu as well as in About,
        # because that is where a person hunting for help looks first
        # (persona-report §2.5).
        second.append(COPY["menu-details"], "win.copy-details")
        menu.append_section(None, second)

        third = Gio.Menu()
        third.append(COPY["menu-about"], "app.about")
        third.append(COPY["menu-quit"], "app.quit")
        menu.append_section(None, third)
        return menu

    def _build_unsupported(self) -> Gtk.Widget:
        """The "not here" screen, as a page of the window rather than a dialog.

        A dialog would be dismissible, and behind it would sit a working-looking
        app that cannot work. This is the whole window instead: the sidebar is
        not there, because none of it would do anything.
        """
        page = Adw.StatusPage(
            icon_name="dialog-information-symbolic",
            title=self.verdict.title or COPY["wrong-desktop-title"],
            description=self.verdict.body or COPY["wrong-desktop-body"],
            vexpand=True,
        )
        view = Adw.ToolbarView(content=page)
        view.add_top_bar(Adw.HeaderBar())
        return view

    # -- keyboard ----------------------------------------------------------

    def _install_shortcuts(self) -> None:
        """Actions first, keys second — every shortcut is also a menu entry.

        A shortcut nobody can discover is a shortcut for the person who wrote
        it. Each of these is reachable from the main menu as well, and the menu
        shows the key beside it because both name the same action.
        """
        self._action("search", lambda *_a: self.open_search())
        self._action("undo", lambda *_a: self.undo_shortcut())
        self._action("onboarding", lambda *_a: onboarding.show_again(self))
        self._action("focus-sidebar", lambda *_a: self.focus_sidebar())
        self._action("copy-details", lambda *_a: self.copy_details())

        # The list of keys, and the key that shows the list. ``set_help_overlay``
        # is what installs ``win.show-help-overlay``, which is the action every
        # GNOME app answers Ctrl+? with — so this is the standard door rather
        # than one of gtheme's own (persona-report §2.10, U10).
        self.set_help_overlay(self._build_shortcuts_window())

        application = self.get_application()
        if application is not None:
            application.set_accels_for_action("win.search", ["<primary>f"])
            application.set_accels_for_action("win.undo", ["<primary>z"])
            application.set_accels_for_action("win.focus-sidebar", ["F6"])
            application.set_accels_for_action(
                "win.show-help-overlay", ["<primary>question"]
            )

        # Ctrl+F also works with no application object at all — a window built
        # by a test or a probe still answers the shortcut.
        ui_search.install_search(self, index=self.search_index(), on_activate=self.go_to)

    def _action(self, name: str, callback: Callable[..., Any]) -> Gio.SimpleAction:
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        return action

    def _build_shortcuts_window(self) -> Gtk.ShortcutsWindow | None:
        """Every key this app answers, in the window GNOME shows on Ctrl+?.

        There was no such list, and no key that reached the sidebar at all —
        so somebody working without a mouse could open gtheme and never get
        into the list of pages (persona-report §2.10). Every entry below is a
        key this window really binds; a list that names one it does not is
        worse than no list.

        ``Gtk.ShortcutsWindow`` is deprecated as of GTK 4.22 with no successor
        in that release (``Gtk.ShortcutsDialog`` is not there yet), and it is
        still what ``set_help_overlay`` takes. Building it defensively means a
        GTK that finally drops it costs the app its shortcut list, not its
        window.
        """
        try:
            group = Gtk.ShortcutsGroup(title=COPY["shortcuts-group"])
            for accelerator, title in (
                ("<primary>f", COPY["shortcut-search"]),
                ("<primary>z", COPY["shortcut-undo"]),
                ("F6", COPY["shortcut-sidebar"]),
                ("<primary>question", COPY["shortcut-help"]),
                ("F1", COPY["shortcut-about"]),
                ("<primary>q", COPY["shortcut-quit"]),
            ):
                group.add_shortcut(
                    Gtk.ShortcutsShortcut(accelerator=accelerator, title=title)
                )
            section = Gtk.ShortcutsSection(section_name="shortcuts", max_height=10)
            section.add_group(group)
            window = Gtk.ShortcutsWindow(
                title=COPY["shortcuts-window-title"], modal=True
            )
            window.add_section(section)
        except Exception:  # noqa: BLE001 - no list is survivable; no window is not
            return None
        return window

    def focus_sidebar(self) -> bool:
        """F6: put the keyboard in the list of pages.

        On a narrow window the sidebar is a page of its own behind the content,
        so getting there is two moves — show it, then focus it — and a
        keyboard-only user could do neither before this existed.
        """
        if self.sidebar is None or self.split is None:
            return False
        self.split.set_show_content(False)
        return bool(self.sidebar.grab_focus())

    # -- navigation --------------------------------------------------------

    def _first_page(self) -> str:
        """Where to open. Where they were last time, if that page still exists."""
        last = self.prefs.get("window/last-page")
        if isinstance(last, str) and last in registry.page_ids():
            return last
        return self._order[0].id

    def _on_sidebar_activated(self, _sidebar: Adw.Sidebar, index: int) -> None:
        if 0 <= index < len(self._order):
            self.show_page(self._order[index].id)
            self.split.set_show_content(True)

    def show_page(self, page_id: str) -> None:
        """Select a page by id, building it the first time it is shown."""
        page = registry.get(page_id)
        self.content_page.set_title(page.title)
        self.content_view.set_content(self._page_widget(page))
        index = next((i for i, p in enumerate(self._order) if p.id == page_id), None)
        if index is not None and self.sidebar.get_selected() != index:
            self.sidebar.set_selected(index)
        # ``save=False``: which page was open matters at the *next* launch and
        # nowhere else, and ``Prefs.save`` is a mkstemp + write + fsync +
        # rename on the main loop. Clicking down the fifteen-item sidebar used
        # to issue fifteen durable-write barriers, one per click, between the
        # click and the page appearing (review-report L14). The one write is
        # done by ``_save_window_state`` when the window closes, which is where
        # the size and the maximised flag are already batched to.
        self.prefs.set("window/last-page", page_id, save=False)
        self._watch_schemas()

    def go_to(self, page_id: str, descriptor_id: str | None = None) -> None:
        """Open a page and, if a row was named, land on that row.

        The navigator the search overlay is given. Flashing happens after the
        page has been built and laid out, which is why it is on an idle rather
        than on the line after :meth:`show_page`.
        """
        self.show_page(page_id)
        self.split.set_show_content(True)
        if descriptor_id:
            GLib.idle_add(self._land_on, descriptor_id)

    def _land_on(self, descriptor_id: str) -> bool:
        entry = self.rows.lookup(descriptor_id)
        if entry is not None and entry.widget is not None:
            _scroll_into_view(entry.widget)
        ui_search.flash(self, descriptor_id)
        return GLib.SOURCE_REMOVE

    def _page_widget(self, page: registry.PageDescriptor) -> Gtk.Widget:
        cached = self._pages.get(page.id)
        if cached is not None:
            return cached
        try:
            factory = registry.load_factory(page)
            widget = factory(self, **self._offer(factory))
        except Exception as exc:  # noqa: BLE001 - a broken page must not kill the app
            widget = self._placeholder(page, exc)
        else:
            if page.id == "home":
                self._home = widget
        self._pages[page.id] = widget
        return widget

    #: What the window has to give a page, by the name a factory would use.
    #: A factory gets exactly the ones it names in its own signature — which is
    #: why every page can still be built by hand, with none of them.
    def _offer(self, factory: Callable[..., Any]) -> dict[str, Any]:
        # Each one is fetched only if the factory names it. ``shell`` is the
        # reason: reading it *builds* the desktop connection, and this method
        # runs for all fifteen pages — so asking for it up front made every
        # page, including the fourteen that never touch the desktop, pay for a
        # ``ListExtensions`` round trip (review-report M26).
        available: dict[str, Callable[[], Any]] = {
            "probe": lambda: self.schema_probe,
            "shell": lambda: self.shell,
        }
        try:
            parameters = inspect.signature(factory).parameters
        except (TypeError, ValueError):  # pragma: no cover - not introspectable
            return {}
        return {
            name: fetch()
            for name, fetch in available.items()
            if name in parameters and parameters[name].kind is not inspect.Parameter.POSITIONAL_ONLY
        }

    def _placeholder(self, page: registry.PageDescriptor, exc: Exception | None = None) -> Gtk.Widget:
        """The stand-in shown for a page whose module is not written yet.

        Distinct per page — icon, title and description all differ — so a
        screenshot of one placeholder is never mistaken for a screenshot of
        another, which is what the screenshot-honesty gate relies on.
        """
        if isinstance(exc, ModuleNotFoundError | AttributeError) or exc is None:
            description = page.subtitle or "This part of gtheme is still being built."
            description = f"{description}\n\nThis page isn't finished yet."
        else:
            description = f"{COPY['page-broken']}\n\n{exc}"
        return Adw.StatusPage(
            icon_name=page.icon,
            title=page.title,
            description=description,
            vexpand=True,
        )

    # -- the shared desktop connection -------------------------------------

    @property
    def shell(self) -> Any:
        """The running desktop's add-on service, or None if it is not there.

        Asked for once. A second connection would mean two ``changed``
        subscriptions to the same signal and two answers to "is it running",
        which is how the Add-ons page and the Home page end up disagreeing.

        "Once" is now enforced with a lock rather than by everything happening
        on the main loop: the Home page asks for this from a worker thread so
        that counting add-ons cannot hold up the window (review-report M26).
        """
        with self._shell_lock:
            if not self._shell_asked:
                self._shell_asked = True
                self._shell = _connect_shell()
            return self._shell

    def adopt_shell(self, shell: Any) -> Any:
        """Take a freshly-made desktop connection as the window's shared one.

        The Add-ons page's "Ask again" is what calls this: it does the slow
        part off the main loop, and hands the answer here so that the *window's*
        memoised connection is the new one too. Without this the page would
        recover and the Home page's add-on line would go on reporting the
        desktop that was not answering ten seconds ago (persona-report §3.3,
        E10).

        The old connection is closed only if the window owned it. The new one
        is the window's from now on, whoever built it — a connection with two
        owners is closed twice, and the second close is on somebody else's
        object.

        Returns:
            The connection now in force, so a caller can carry on with it.
        """
        with self._shell_lock:
            previous, was_ours = self._shell, self._shell_is_ours
            self._shell = shell
            self._shell_asked = True
            self._shell_is_ours = True
        if previous is not None and previous is not shell and was_ours:
            try:
                previous.close()
            except Exception:  # noqa: BLE001 - it was already unreachable
                pass
        home = self._pages.get("home")
        if home is not None:
            # The Home page was handed whatever the answer was when it was
            # built. Handing it the new one is the difference between "add-ons:
            # not reachable" until the app is restarted and a line that follows
            # the same recovery the Add-ons page just did.
            if hasattr(home, "shell"):
                home.shell = shell
            refresh = getattr(home, "refresh", None)
            if callable(refresh):
                refresh()
        return shell

    def _shell_version(self) -> str | None:
        """The desktop's version, read the cheap way (review-report M26).

        This runs inside ``__init__``, before the window is presented, so what
        it must never do is what it used to do: touch :attr:`shell`, whose
        ``_connect_shell()`` calls ``ShellExtensions.load()`` → a blocking
        ``ListExtensions`` with GDBus's 25-second default timeout. Launching
        while the desktop was busy meant nothing was drawn at all, for a
        property — ``ShellVersion`` — that is cached on the proxy and needs no
        call. It also contradicted :attr:`shell`'s own docstring, which
        promises the connection is built on first *use*.

        A connection that already exists is asked (there is no reason to build
        a second proxy); otherwise a bare proxy is made for the one property
        and the shared connection stays unbuilt.
        """
        shell = self._shell
        if shell is not None:
            try:
                return shell.proxy.shell_version() or None
            except Exception:  # noqa: BLE001 - the desktop answered nothing useful
                return None
        if not self._ask_desktop:
            return None
        return _bare_shell_version()

    # -- what pages call back into -----------------------------------------

    def register_page_shell(self, shell: Any) -> None:
        """A style page announcing itself, so mirroring can re-run its notices."""
        page_id = getattr(shell, "page_id", None)
        if isinstance(page_id, str):
            self._shells[page_id] = shell

    def unregister_page_shell(self, shell: Any) -> None:
        page_id = getattr(shell, "page_id", None)
        if isinstance(page_id, str) and self._shells.get(page_id) is shell:
            del self._shells[page_id]

    def toast(self, text: str, *, undo_point: str | None = None, **kwargs: Any) -> Adw.Toast:
        """Show a transient message, optionally with the way back attached.

        Every toast that follows a change carries its Undo, and every one of
        them is built here, so "there is always a way back" is one line of code
        rather than a rule five pages have to remember.
        """
        kwargs.setdefault("timeout", 8 if undo_point else 5)
        # ``Adw.Toast:title`` renders Pango markup, and what lands here is
        # routinely a Look's title or a name somebody typed: an ampersand made
        # the whole confirmation render as nothing, and markup in a title could
        # make it say something else entirely (review-report M15).
        toast = Adw.Toast(title=ui_search.escape_markup(text), **kwargs)
        if undo_point:
            toast.set_button_label(COPY["undo"])
            toast.connect("button-clicked", lambda _t, p=undo_point: self.undo_point(p))
        self.toasts.add_toast(toast)
        return toast

    def after_change(self) -> None:
        """Everything on screen re-reads itself. Writes nothing.

        Called by any page that has just changed the desktop. The alternative
        is each page refreshing the parts of the app it happens to know about,
        which is how the Home page ends up showing yesterday's Look.
        """
        self.rows.refresh_all()
        for shell in list(self._shells.values()):
            run = getattr(shell, "run_notices", None)
            if callable(run):
                run()
        for page_id, method in (
            ("home", "refresh"),
            ("restore", "refresh"),
            ("looks", "reload"),
        ):
            page = self._pages.get(page_id)
            call = getattr(page, method, None)
            if callable(call):
                call()
        self.rebuild_search_index()

    # -- search ------------------------------------------------------------

    def search_index(self) -> ui_search.SearchIndex:
        """The index Ctrl+F searches. One object, for its whole lifetime."""
        if self._search_index is None:
            self._search_index = ui_search.SearchIndex.build()
        return self._search_index

    def rebuild_search_index(self) -> ui_search.SearchIndex:
        """Read the Looks on disk again. A downloaded Look is searchable at once.

        The contents are replaced, not the object. Ctrl+F was wired to *this*
        index when the window was built, so handing out a new one would leave
        the keyboard shortcut searching a snapshot from before the download.
        """
        index = self.search_index()
        index.hits[:] = ui_search.SearchIndex.build().hits
        return index

    def open_search(self) -> Any:
        return ui_search.present_search(self, index=self.search_index(), on_activate=self.go_to)

    # -- undo --------------------------------------------------------------

    def undo_shortcut(self) -> bool:
        """Ctrl+Z, and the menu entry beside it.

        A window-wide accelerator over four text entries had no guard on it: a
        person editing the name of a Look they are saving pressed the undo they
        have pressed in every other program of their life and got their whole
        desktop put back instead of their last word (persona-report §2.8). A
        text box that is being typed in keeps its own undo — and gets it
        forwarded, so the key does what it was pressed for rather than nothing.

        Returns:
            True when this was the desktop's undo, False when the keystroke
            belonged to whatever has focus.
        """
        focus = self.get_focus()
        if is_text_editing(focus):
            _forward_text_undo(focus)
            return False
        self.undo_last_change()
        return True

    def undo_last_change(self) -> None:
        """The header button, the menu entry and Ctrl+Z.

        Goes through the Undo page's own confirmation, which names the moment
        and lists what going back would change. It used to apply the newest
        restore point outright — no preview, no confirmation, from anywhere in
        the app — while the identical action started from the Undo page asked
        first (persona-report §2.8). One of the two was wrong, and it was not
        the one with the dialog.
        """
        page = self._undo_page()
        confirm = getattr(page, "confirm_undo_last", None)
        if not callable(confirm):
            self.toast(COPY["undo-unavailable"])
            return
        confirm(self)

    def _undo_page(self) -> Any:
        """The Undo & Restore Points page, built if this session never opened it.

        Built rather than shown: the confirmation is a dialog over whatever the
        person is looking at, and yanking them to another page before they have
        agreed to anything answers a question they have not been asked yet.
        """
        try:
            return self._page_widget(registry.get("restore"))
        except Exception:  # noqa: BLE001 - a page that will not build is said out loud
            return None

    def undo_point(self, point_id: str) -> None:
        """Go back to one saved moment, narrating it on the shared runner.

        This is what the Undo button on a toast does, so the person who presses
        it is by definition not looking at the list of saved moments — which is
        why the sentence at the end names the one that ran (U8). The moment is
        read *before* the work rather than after it, because going back takes a
        restore point of its own: read afterwards, "the newest moment" is the
        one this undo just created, not the one it went back to.
        """
        from .core import restorepoints
        from .ui.pages import restore as restore_page

        try:
            point = restorepoints.load(point_id)
        except OSError:  # pragma: no cover - defensive; a name is never worth a crash
            point = None

        def work(narrate: Any) -> Any:
            return restorepoints.apply_point(point_id, lambda *a: narrate(_narration(a)))

        def done(result: Any) -> None:
            warnings = list(getattr(result, "warnings", []) or [])
            failed = warnings and getattr(result, "transaction", None) is None
            self.toast(
                COPY["undo-failed"] if failed else restore_page.done_sentence(point)
            )
            self.after_change()

        self.runner.run(
            work,
            heading=COPY["undo-heading"],
            starting=COPY["undo-starting"],
            on_done=done,
            on_failed=lambda _exc: self.toast(COPY["undo-failed"]),
        )

    # -- live mirroring ----------------------------------------------------

    def _watch_schemas(self) -> None:
        """Subscribe to every schema that now has a row on screen.

        Called after a page is built rather than once at startup, because rows
        arrive when their page is first opened. Subscribing twice to the same
        schema is prevented by the dictionary, not by remembering to check.
        """
        if not self._mirror:
            return
        for schema_id in sorted(_schemas_of(self.rows)):
            if schema_id in self._watchers:
                continue
            settings = _settings_for(schema_id)
            if settings is None:
                # Relocatable schemas (one per add-on profile) have no single
                # path to watch, and a wrong guess would watch the wrong
                # profile. They refresh when their page is rebuilt instead.
                self._watchers[schema_id] = None  # type: ignore[assignment]
                continue
            settings.connect("changed", self._on_external_change, schema_id)
            self._watchers[schema_id] = settings

    def _on_external_change(self, _settings: Gio.Settings, key: str, schema_id: str) -> None:
        entry = self.rows.lookup_key(schema_id, key)
        if entry is not None and entry.refresh is not None:
            entry.refresh()
        if self._mirror_pending:
            return
        # Several keys often move together — a Look applied from a terminal, a
        # theme switched in GNOME Settings. One pass at the end says the same
        # thing as twenty, and says it once.
        self._mirror_pending = True
        GLib.idle_add(self._mirror_settled)

    def _mirror_settled(self) -> bool:
        self._mirror_pending = False
        for shell in list(self._shells.values()):
            run = getattr(shell, "run_notices", None)
            if callable(run):
                run()
        home = self._pages.get("home")
        refresh = getattr(home, "refresh", None)
        if callable(refresh):
            refresh()
        return GLib.SOURCE_REMOVE

    # -- window state ------------------------------------------------------

    def _restore_window_state(self) -> None:
        width = self.prefs.get("window/width")
        height = self.prefs.get("window/height")
        if (
            isinstance(width, int)
            and isinstance(height, int)
            and width > MINIMUM_WIDTH
            and height > MINIMUM_HEIGHT
        ):
            # Fitted like the default is, and for a case the default does not
            # cover: a size chosen on a docked 4K screen, restored on the
            # laptop panel it is now the only screen of.
            self.set_default_size(*fit_to_monitor(width, height, monitor_size()))
        if self.prefs.get("window/maximized") is True:
            self.maximize()

    def _on_close(self, *_args: Any) -> bool:
        self._save_window_state()
        self.teardown()
        return False

    def _save_window_state(self) -> None:
        maximized = bool(self.is_maximized())
        self.prefs.set("window/maximized", maximized, save=False)
        if not maximized:
            self.prefs.set("window/width", int(self.get_width()), save=False)
            self.prefs.set("window/height", int(self.get_height()), save=False)
        self.prefs.save()

    def teardown(self) -> None:
        """Let go of the desktop. Safe to call twice.

        The window owns the add-on connection now, so the window closes it —
        the Add-ons page used to, which meant closing that page cut the Home
        page's connection out from under it.
        """
        for settings in list(self._watchers.values()):
            if settings is not None:
                _disconnect(settings, self._on_external_change)
        self._watchers.clear()
        with self._shell_lock:
            # ``_shell_asked`` is set inside the lock so that a background
            # add-on count still in flight cannot build a connection nothing
            # will ever close (review-report M26).
            if self._shell is not None and self._shell_is_ours:
                try:
                    self._shell.close()
                except Exception:  # noqa: BLE001 - going away anyway
                    pass
            self._shell = None
            self._shell_asked = True

    # -- about -------------------------------------------------------------

    def show_about(self) -> Adw.AboutDialog:
        """:meth:`about_dialog`, shown."""
        dialog = self.about_dialog()
        dialog.present(self)
        return dialog

    def about_dialog(self) -> Adw.AboutDialog:
        """The About dialog, read from the packaged description of the app.

        ``new_from_appdata`` means the version, the licence, the description
        and the release notes come from ``data/*.metainfo.xml`` — the same file
        the software centre reads — instead of being typed out a second time
        here and drifting.

        Two things are added on top of whichever dialog was built, because they
        are the two things somebody in trouble came here for (persona-report
        §2.5, §3.1): where to get help, and the details a bug report asks for.
        The details go in as ``debug_info``, which is libadwaita's own
        troubleshooting page with its own copy button — and they are also one
        click away in the main menu, for people who would never think to look
        inside About.
        """
        dialog = _about_from_appdata()
        if dialog is None:
            dialog = Adw.AboutDialog(
                application_name="Gtheme",
                application_icon=APP_ID,
                developer_name="blyatiful1",
                version=__version__,
                website="https://github.com/blyatiful1/gtheme",
                issue_url="https://github.com/blyatiful1/gtheme/issues",
                license_type=Gtk.License.MIT_X11,
            )
        dialog.set_support_url(SUPPORT_URL)
        dialog.set_debug_info(details_text(version=self._shell_version()))
        dialog.set_debug_info_filename("gtheme-details.txt")
        return dialog

    def copy_details(self) -> str:
        """Put the details a bug report asks for on the clipboard.

        Version, desktop version and the tail of the log — never the value of
        a setting: :mod:`gtheme.core.applog` records *which* key changed and
        not what it changed to, precisely so that this button can exist.
        """
        text = details_text(version=self._shell_version())
        if _to_clipboard(self, text):
            self.toast(COPY["details-copied"])
        else:
            self.toast(COPY["details-failed"])
        return text

    # -- the change that did not finish ------------------------------------

    def unfinished_notice(self) -> Adw.AlertDialog | None:
        """The notice for a change a previous gtheme was killed in the middle of.

        Nothing used to notice. The apply worker is a daemon thread and the
        progress dialog can be closed, so a machine that lost power — or a
        person who closed the window during a three-minute add-on download —
        came back to a desktop that was half changed and an app with nothing to
        say about it (persona-report §3.3, E6).

        What is looked at is the transaction's own rollback journal: the engine
        makes one per apply and deletes it on every path that runs Python,
        including the interrupt path. One that is still there recorded a change
        nothing unwound.

        Returns:
            The dialog to show, or None when there is nothing to say — which
            is the overwhelmingly common case, so this is cheap and quiet.
        """
        leftovers = [
            journal for journal in unfinished_changes() if journal not in self._dismissed()
        ]
        if not leftovers or _change_in_progress():
            return None

        dialog = Adw.AlertDialog(
            heading=COPY["unfinished-title"], body=COPY["unfinished-body"]
        )
        dialog.add_response("dismiss", COPY["unfinished-dismiss"])
        dialog.add_response("restore", COPY["unfinished-restore"])
        dialog.set_response_appearance("restore", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("restore")
        dialog.set_close_response("dismiss")
        dialog.connect("response", self._on_unfinished, leftovers)
        return dialog

    def present_unfinished_notice(self) -> Adw.AlertDialog | None:
        """:meth:`unfinished_notice`, shown. What the application calls."""
        dialog = self.unfinished_notice()
        if dialog is not None:
            dialog.present(self)
        return dialog

    def _on_unfinished(self, _dialog: Any, response: str, leftovers: list[str]) -> None:
        # Answered either way, the question is not asked about these journals
        # again: a notice that comes back every launch is one people learn to
        # click past, which is the opposite of what it is for.
        self._dismiss(leftovers)
        if response == "restore":
            # Straight into the machinery that already exists for this: the
            # Undo page's confirmation, which names the moment it would go back
            # to and lists what that changes before anything happens.
            self.undo_last_change()

    def _dismissed(self) -> list[str]:
        seen = self.prefs.get(DISMISSED_UNFINISHED_KEY, [])
        return [item for item in seen if isinstance(item, str)] if isinstance(seen, list) else []

    def _dismiss(self, journals: Iterable[str]) -> None:
        remembered = [*self._dismissed(), *journals]
        self.prefs.set(DISMISSED_UNFINISHED_KEY, remembered[-DISMISSED_LIMIT:])


# --------------------------------------------------------------------------
# the parts with no window in them
# --------------------------------------------------------------------------


def is_text_editing(widget: Any) -> bool:
    """Is this widget a text box somebody could be typing in?

    The question Ctrl+Z has to ask before it undoes a desktop. ``Gtk.Editable``
    covers every entry in the app — the search box, the Look name, the two
    filters — because ``Gtk.Text`` (the widget focus actually lands on inside a
    ``Gtk.Entry``) implements it; ``Gtk.TextView`` is checked separately
    because it does not. A box that cannot be edited is not being typed in and
    has no undo of its own to protect.
    """
    if widget is None:
        return False
    if isinstance(widget, Gtk.TextView):
        return bool(widget.get_editable())
    if isinstance(widget, Gtk.Editable):
        return bool(widget.get_editable())
    return False


def _forward_text_undo(widget: Any) -> None:
    """Give the keystroke to the text box it was meant for.

    ``text.undo`` is the action GTK's own entries and text views install for
    exactly this key. Handing it over is the difference between "your undo went
    somewhere else" and "your undo did nothing".
    """
    try:
        widget.activate_action("text.undo", None)
    except Exception:  # noqa: BLE001 - a widget without one keeps its own behaviour
        return


def _narration(args: Iterable[Any]) -> str:
    """Whatever the engine said, as one sentence to show."""
    for value in args:
        if isinstance(value, str) and value:
            return value
    return ""


def _schemas_of(rows: Iterable[Any]) -> set[str]:
    """Every schema id with a row on screen, from ``schema:key`` row ids."""
    found: set[str] = set()
    for entry in rows:
        descriptor_id = getattr(entry, "descriptor_id", "")
        schema_id, sep, key = str(descriptor_id).rpartition(":")
        if sep and schema_id and key and "." in schema_id:
            found.add(schema_id)
    return found


def _settings_for(schema_id: str) -> Gio.Settings | None:
    """A watchable settings object, or None for one that cannot be watched."""
    try:
        source = Gio.SettingsSchemaSource.get_default()
        if source is None:
            return None
        schema = source.lookup(schema_id, True)
        if schema is None or schema.get_path() is None:
            return None
        return Gio.Settings.new(schema_id)
    except Exception:  # noqa: BLE001 - a schema that will not open is one to skip
        return None


def _disconnect(settings: Gio.Settings, handler: Callable[..., Any]) -> None:
    try:
        settings.disconnect_by_func(handler)
    except Exception:  # pragma: no cover - already gone
        pass


def _build_probe() -> Any:
    from .panels.schema_probe import SchemaProbe

    return SchemaProbe()


def monitor_size(display: Any = None) -> tuple[int, int] | None:
    """The size of the smallest screen attached, or None if nothing answers.

    The smallest rather than the first: a window is opened by the compositor on
    whichever screen it likes, and a default that fits the smallest fits
    everywhere. Sizes come back in the same units a window is measured in, so a
    1920x1080 screen at 200% correctly reports 960x540 — which is the case that
    made this necessary.
    """
    try:
        from gi.repository import Gdk

        display = display if display is not None else Gdk.Display.get_default()
        if display is None:
            return None
        monitors = display.get_monitors()
        sizes: list[tuple[int, int]] = []
        for index in range(monitors.get_n_items()):
            geometry = monitors.get_item(index).get_geometry()
            if geometry.width > 0 and geometry.height > 0:
                sizes.append((geometry.width, geometry.height))
    except Exception:  # noqa: BLE001 - no display is not a reason to refuse a size
        return None
    return min(sizes, key=lambda size: size[0] * size[1]) if sizes else None


def fit_to_monitor(
    width: int, height: int, monitor: tuple[int, int] | None
) -> tuple[int, int]:
    """Shrink a wanted window size until it fits on the screen it will open on.

    Never grows it, and never goes below the window's own minimum — a window
    that will not fit at all is better shown too big than shown as a stump.
    """
    if monitor is None:
        return width, height
    monitor_width, monitor_height = monitor
    if monitor_width > 0:
        width = max(MINIMUM_WIDTH, min(width, monitor_width - SCREEN_MARGIN_X))
    if monitor_height > 0:
        height = max(MINIMUM_HEIGHT, min(height, monitor_height - SCREEN_MARGIN_Y))
    return width, height


class _AskDesktop:
    """Sentinel: read the desktop's version rather than being told it."""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging only
        return "ASK_DESKTOP"


#: Default for ``details_text(version=…)``. The window passes what it already
#: read at launch instead, so opening About costs no traffic of its own.
ASK_DESKTOP = _AskDesktop()


def details_text(
    *, version: str | None | _AskDesktop = ASK_DESKTOP, lines: int = LOG_TAIL_LINES
) -> str:
    """The details a bug report asks for, as text somebody can paste.

    Deliberately technical — a maintainer reads this, and precision is the
    whole point of a version string. The plain-language half of this feature is
    the button that produces it, not its payload.

    **No setting values, ever.** The versions are versions and the log records
    which key changed rather than what it changed to (see
    :mod:`gtheme.core.applog`). Somebody pasting this into a public issue is
    not publishing their home directory, their terminal profile or their
    wallpaper's name.
    """
    from .core import applog

    parts = [f"gtheme {__version__}"]

    desktop = _desktop_version_for_details() if isinstance(version, _AskDesktop) else version
    parts.append(f"GNOME {desktop}" if desktop else "GNOME version: no answer")
    pieces = libadwaita_version()
    parts.append(
        "libadwaita {}.{}, GTK {}.{}".format(
            *(pieces or ("?", "?")),
            Gtk.get_major_version(),
            Gtk.get_minor_version(),
        )
    )
    parts.append(f"Python {sys.version.split()[0]} on {platform.platform()}")

    log = applog.log_file()
    parts.append(f"\nLog ({log}), last {lines} lines:")
    parts.append(_log_tail(log, lines=lines))
    return "\n".join(parts)


def _desktop_version_for_details() -> str:
    """The desktop's version for the details blob. Never raises, never stalls."""
    try:
        return _bare_shell_version() or ""
    except Exception:  # noqa: BLE001 - a detail nobody has is still a detail
        return ""


def _log_tail(path: Any, *, lines: int) -> str:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "(no log file yet)"
    tail = "\n".join(text.splitlines()[-lines:])
    return tail[-LOG_TAIL_CHARS:] if tail else "(the log is empty)"


def _to_clipboard(widget: Any, text: str) -> bool:
    """Put text on the clipboard. False when there is no display to put it on."""
    try:
        clipboard = widget.get_clipboard()
        if clipboard is None:
            return False
        clipboard.set(text)
    except Exception:  # noqa: BLE001 - a clipboard that refuses is said out loud
        return False
    return True


def unfinished_changes(*, temp_dir: Any = None) -> list[str]:
    """Rollback journals a killed gtheme left behind, oldest first.

    A journal that recorded nothing is not reported: the change was interrupted
    before it touched anything, so there is nothing to put back and nothing
    worth saying. Recording happens *before* the change it describes, so this
    errs towards asking about a change that did not quite land — the same
    direction the engine's own ledger errs in, and the cheap one.

    Directories belonging to another user are skipped rather than read.
    """
    import tempfile

    root = Path(temp_dir) if temp_dir is not None else Path(tempfile.gettempdir())
    found: list[str] = []
    try:
        candidates = sorted(root.glob(f"{JOURNAL_PREFIX}*"))
    except OSError:  # pragma: no cover - an unreadable temp directory
        return []
    for candidate in candidates:
        try:
            if not candidate.is_dir() or candidate.stat().st_uid != os.getuid():
                continue
            if not _journal_recorded_something(candidate):
                continue
        except OSError:  # pragma: no cover - it went away while we looked
            continue
        found.append(str(candidate))
    return found


def _journal_recorded_something(journal: Path) -> bool:
    for name in ("files.json", "settings.json"):
        try:
            recorded = json.loads((journal / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if recorded:
            return True
    return False


def _change_in_progress() -> bool:
    """Is another gtheme applying something right now?

    Asked before the "it did not finish" notice, so that a second window
    opening while the first one is mid-apply says nothing rather than
    announcing a crash that is not happening.
    """
    from .core.lock import LockBusy, process_lock

    try:
        with process_lock():
            return False
    except LockBusy:
        return True
    except OSError:  # pragma: no cover - no state directory to lock in
        return False


def _bare_shell_version() -> str | None:
    """``ShellVersion`` off a proxy of its own, with no add-on listing behind it.

    The property is cached on the proxy — it arrives with the proxy and costs
    no call. What this deliberately does *not* do is build the window's shared
    connection, whose ``load()`` is the 25-second-capable ``ListExtensions``
    round trip that used to sit between the launcher and the first frame
    (review-report M26).
    """
    from .core.backends import has_session_bus
    from .ego.shelldbus import GDBusShellProxy

    if not has_session_bus():
        return None
    try:
        return GDBusShellProxy().shell_version() or None
    except Exception:  # noqa: BLE001 - no bus, no desktop, no typelib: no version
        return None


def _connect_shell() -> Any:
    """One connection to the desktop's add-on service, or None if it is absent.

    A desktop that is not there is an ordinary state — gtheme runs on a machine
    where somebody has just logged into a different session, or under a display
    manager, or in a terminal. It gets None, not a traceback.
    """
    from .core.backends import has_session_bus
    from .ego.shelldbus import GDBusShellProxy, ShellError, ShellExtensions

    if not has_session_bus():
        return None
    shell = ShellExtensions(GDBusShellProxy())
    try:
        shell.load()
    except ShellError:
        return shell
    except Exception:  # noqa: BLE001 - no typelib, no bus, no desktop
        return None
    return shell


def _about_from_appdata() -> Adw.AboutDialog | None:
    """The About dialog built from the installed description of this app.

    ``new_from_appdata`` reads the same file the software centre reads, so the
    version, the licence and the description are written down once instead of
    twice. It also **aborts the process** when the resource is not there —
    ``g_error``, not an exception, so there is nothing to catch. Running from a
    checkout is exactly that case. So the resource is looked up first, through
    a call that fails politely, and the appdata path is taken only when there
    is appdata to take it from.
    """
    resource = f"/io/github/blyatiful1/Gtheme/{APP_ID}.metainfo.xml"
    try:
        Gio.resources_get_info(resource, Gio.ResourceLookupFlags.NONE)
    except GLib.Error:
        return None
    try:
        return Adw.AboutDialog.new_from_appdata(resource, __version__)
    except Exception:  # noqa: BLE001 - present but unreadable; type it out instead
        return None


def _scroll_into_view(widget: Any) -> None:
    """Bring a row into view inside whatever is scrolling it.

    ``grab_focus`` alone usually scrolls, but a row that cannot take focus —
    a label row, a group heading — would flash somewhere off-screen. Asking
    the scrolled window directly works for both.
    """
    try:
        parent = widget.get_parent()
        while parent is not None and not isinstance(parent, Gtk.ScrolledWindow):
            parent = parent.get_parent()
        if parent is None:
            return
        ok, rect = widget.compute_bounds(parent.get_child() or parent)
        if not ok:
            return
        adjustment = parent.get_vadjustment()
        if adjustment is None:
            return
        target = max(0.0, rect.origin.y - adjustment.get_page_size() / 3)
        adjustment.set_value(min(target, max(0.0, adjustment.get_upper() - adjustment.get_page_size())))
    except Exception:  # noqa: BLE001 - a row that will not scroll still flashes
        return
