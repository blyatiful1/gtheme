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
from collections.abc import Callable, Iterable
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
    "COPY",
    "DEFAULT_HEIGHT",
    "DEFAULT_WIDTH",
    "MINIMUM_GNOME",
    "DesktopVerdict",
    "Window",
    "check_desktop",
]


#: Every sentence this window says, in one place, so the wording can be
#: reviewed as a whole and linted as a whole.
COPY: dict[str, str] = {
    "undo-button": "Undo last change",
    "search-tooltip": "Search everything in this app (Ctrl+F)",
    "menu-tooltip": "Main menu",
    "menu-search": "Search",
    "menu-undo": "Undo last change",
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
    # -- shared outcomes
    "page-broken": "This page could not be opened.",
    "undo": "Undo",
    "undo-nothing": "There is no saved moment to go back to yet.",
    "undo-done": "Put back how it was.",
    "undo-failed": "gtheme could not put everything back. Open Undo & Restore Points.",
    "undo-heading": "Putting your desktop back",
    "undo-starting": "Going back to how it was…",
}

#: The oldest GNOME gtheme is willing to describe. Below this the descriptor
#: corpus offers settings the desktop does not have, which is worse than saying
#: no: it is a list of promises that quietly do nothing.
MINIMUM_GNOME = 47

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


def check_desktop(
    *,
    current_desktop: str | None = None,
    version: str | None = None,
) -> DesktopVerdict:
    """Can gtheme honestly do anything on this computer?

    Args:
        current_desktop: what the session calls itself. None reads the
            environment, which is what the real window does.
        version: the desktop's version, if it could be asked. None means it
            could not be — a perfectly ordinary state, and NOT a reason to
            refuse: gtheme opened from a terminal on a machine that is not
            logged in has no version to read and still has settings to show.

    Returns:
        A verdict. ``ok`` false carries the whole screen to show instead.
    """
    import os

    session = current_desktop if current_desktop is not None else os.environ.get(
        "XDG_CURRENT_DESKTOP", ""
    )
    if session and "gnome" not in session.lower():
        return DesktopVerdict(
            False, COPY["wrong-desktop-title"], COPY["wrong-desktop-body"]
        )

    major = _major(version)
    if major is not None and major < MINIMUM_GNOME:
        return DesktopVerdict(
            False,
            COPY["old-desktop-title"],
            COPY["old-desktop-body"].format(minimum=MINIMUM_GNOME),
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
        super().__init__(
            title="Gtheme",
            default_width=DEFAULT_WIDTH,
            default_height=DEFAULT_HEIGHT,
            width_request=360,
            height_request=294,
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

        self.sidebar = self._build_sidebar()
        self.split = self._build_split()

        self._root = Gtk.Stack()
        self._root.add_named(self.split, "app")
        self._root.add_named(self._build_unsupported(), "unsupported")
        self._root.set_visible_child_name("app" if self.verdict.ok else "unsupported")

        self.toasts = Adw.ToastOverlay(child=self._root)
        self.set_content(self.toasts)

        # Below this width the sidebar becomes a page of its own and the split
        # view navigates between the two, instead of squeezing both onto a
        # screen that cannot hold them.
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

    def _menu_model(self) -> Gio.Menu:
        menu = Gio.Menu()
        first = Gio.Menu()
        first.append(COPY["menu-search"], "win.search")
        first.append(COPY["menu-undo"], "win.undo")
        menu.append_section(None, first)

        second = Gio.Menu()
        second.append(onboarding.MENU_LABEL, "win.onboarding")
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
        self._action("undo", lambda *_a: self.undo_last_change())
        self._action("onboarding", lambda *_a: onboarding.show_again(self))

        application = self.get_application()
        if application is not None:
            application.set_accels_for_action("win.search", ["<primary>f"])
            application.set_accels_for_action("win.undo", ["<primary>z"])

        # Ctrl+F also works with no application object at all — a window built
        # by a test or a probe still answers the shortcut.
        ui_search.install_search(self, index=self.search_index(), on_activate=self.go_to)

    def _action(self, name: str, callback: Callable[..., Any]) -> Gio.SimpleAction:
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        return action

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
        self.prefs.set("window/last-page", page_id)
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
                self._pack_undo_button(widget)
        self._pages[page.id] = widget
        return widget

    #: What the window has to give a page, by the name a factory would use.
    #: A factory gets exactly the ones it names in its own signature — which is
    #: why every page can still be built by hand, with none of them.
    def _offer(self, factory: Callable[..., Any]) -> dict[str, Any]:
        available = {
            "probe": self.schema_probe,
            "shell": self.shell,
        }
        try:
            parameters = inspect.signature(factory).parameters
        except (TypeError, ValueError):  # pragma: no cover - not introspectable
            return {}
        return {
            name: value
            for name, value in available.items()
            if name in parameters and parameters[name].kind is not inspect.Parameter.POSITIONAL_ONLY
        }

    def _pack_undo_button(self, home: Any) -> None:
        """Put the Home page's undo button in the header bar, once."""
        from .ui.pages import home as home_page

        if not isinstance(home, home_page.HomePage):
            return
        button = home_page.header_button(home)
        button.set_tooltip_text(COPY["undo-button"])
        self.header.pack_start(button)

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
        """
        if not self._shell_asked:
            self._shell_asked = True
            self._shell = _connect_shell()
        return self._shell

    def _shell_version(self) -> str | None:
        shell = self.shell
        if shell is None:
            return None
        try:
            return shell.proxy.shell_version()
        except Exception:  # noqa: BLE001 - the desktop answered nothing useful
            return None

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
        toast = Adw.Toast(title=text, **kwargs)
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

    def undo_last_change(self) -> None:
        """The header button and Ctrl+Z. Goes back to the most recent moment."""
        from .core import restorepoints

        points = [p for p in restorepoints.list_restore_points() if p.kind != "pristine"]
        if not points:
            self.toast(COPY["undo-nothing"])
            return
        self.undo_point(points[0].id)

    def undo_point(self, point_id: str) -> None:
        """Go back to one saved moment, narrating it on the shared runner."""
        from .core import restorepoints

        def work(narrate: Any) -> Any:
            return restorepoints.apply_point(point_id, lambda *a: narrate(_narration(a)))

        def done(result: Any) -> None:
            warnings = list(getattr(result, "warnings", []) or [])
            failed = warnings and getattr(result, "transaction", None) is None
            self.toast(COPY["undo-failed"] if failed else COPY["undo-done"])
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
        if isinstance(width, int) and isinstance(height, int) and width > 360 and height > 294:
            self.set_default_size(width, height)
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
        if self._shell is not None and self._shell_is_ours:
            try:
                self._shell.close()
            except Exception:  # noqa: BLE001 - going away anyway
                pass
        self._shell = None
        self._shell_asked = True

    # -- about -------------------------------------------------------------

    def show_about(self) -> None:
        """The About dialog, read from the packaged description of the app.

        ``new_from_appdata`` means the version, the licence, the description
        and the release notes come from ``data/*.metainfo.xml`` — the same file
        the software centre reads — instead of being typed out a second time
        here and drifting.
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
        dialog.present(self)


# --------------------------------------------------------------------------
# the parts with no window in them
# --------------------------------------------------------------------------


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
