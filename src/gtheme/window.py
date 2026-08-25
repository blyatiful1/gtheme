"""The application window: sidebar, content area, breakpoint.

The sidebar is built by walking ``ui.registry.MANIFEST``, never by hand. A page
therefore cannot exist without appearing here, and cannot appear here without
existing — which is the property that lets fifteen pages be written in
parallel by people who never read each other's code.

Page widgets are built lazily, the first time a page is selected, and then
cached. Fifteen eager imports would pull every scanner and network client the
app has into the path between clicking the launcher and seeing a window.
"""

from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from . import APP_ID, __version__  # noqa: E402
from .prefs import Prefs  # noqa: E402
from .ui import registry  # noqa: E402
from .ui.rowindex import RowIndex  # noqa: E402

__all__ = ["Window"]


class Window(Adw.ApplicationWindow):
    """The one window gtheme has."""

    __gtype_name__ = "GthemeWindow"

    def __init__(self, prefs: Prefs | None = None, **kwargs: Any) -> None:
        super().__init__(
            title="Gtheme",
            default_width=1000,
            default_height=720,
            width_request=360,
            height_request=294,
            **kwargs,
        )
        self.prefs = prefs if prefs is not None else Prefs()
        #: Where pages register their rows so search, deep links and live
        #: mirroring can find them again.
        self.rows = RowIndex()

        self._pages: dict[str, Gtk.Widget] = {}
        self._order: list[registry.PageDescriptor] = []

        registry.check_sections()

        self.sidebar = self._build_sidebar()

        sidebar_bar = Adw.HeaderBar()
        sidebar_bar.pack_end(
            Gtk.MenuButton(icon_name="open-menu-symbolic", primary=True, tooltip_text="Main menu")
        )
        sidebar_view = Adw.ToolbarView(content=self.sidebar)
        sidebar_view.add_top_bar(sidebar_bar)

        self.content_view = Adw.ToolbarView()
        self.content_view.add_top_bar(Adw.HeaderBar())
        self.content_page = Adw.NavigationPage(title="Home", child=self.content_view)

        self.split = Adw.NavigationSplitView(
            min_sidebar_width=220,
            max_sidebar_width=300,
            sidebar=Adw.NavigationPage(title="Gtheme", child=sidebar_view),
            content=self.content_page,
        )

        self.toasts = Adw.ToastOverlay(child=self.split)
        self.set_content(self.toasts)

        # Below this width the sidebar becomes a page of its own and the split
        # view navigates between the two, instead of squeezing both onto a
        # screen that cannot hold them.
        breakpoint_ = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 550sp"))
        breakpoint_.add_setter(self.split, "collapsed", True)
        breakpoint_.add_setter(self.sidebar, "mode", Adw.SidebarMode.PAGE)
        self.add_breakpoint(breakpoint_)

        self.show_page(self._order[0].id)

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

    # -- navigation --------------------------------------------------------

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

    def _page_widget(self, page: registry.PageDescriptor) -> Gtk.Widget:
        cached = self._pages.get(page.id)
        if cached is not None:
            return cached
        try:
            factory = registry.load_factory(page)
            widget = factory(self)
        except Exception as exc:  # noqa: BLE001 - a broken page must not kill the app
            widget = self._placeholder(page, exc)
        self._pages[page.id] = widget
        return widget

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
            description = f"This page could not be opened.\n\n{exc}"
        return Adw.StatusPage(
            icon_name=page.icon,
            title=page.title,
            description=description,
            vexpand=True,
        )

    # -- helpers for pages -------------------------------------------------

    def toast(self, text: str, **kwargs: Any) -> None:
        """Show a transient message."""
        self.toasts.add_toast(Adw.Toast(title=text, **kwargs))

    def show_about(self) -> None:
        Adw.AboutDialog(
            application_name="Gtheme",
            application_icon=APP_ID,
            developer_name="blyatiful1",
            version=__version__,
            website="https://github.com/blyatiful1/gtheme",
            issue_url="https://github.com/blyatiful1/gtheme/issues",
            license_type=Gtk.License.MIT_X11,
        ).present(self)
