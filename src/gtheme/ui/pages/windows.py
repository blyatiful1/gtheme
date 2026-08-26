"""Windows & Desktops — DESIGN.md A6/§C step 16.

Window buttons, focus behaviour, titlebar clicks, tiling, desktops, and every
keyboard shortcut the desktop itself watches for. The last two domains
(``shortcuts.toml``, ``mediakeys.toml``) are 175 rows between them — a flat
list of that size is unusable, so they render inside one collapsed
:class:`Adw.ExpanderRow` each rather than as 175 rows a person has to scroll
past to find "snap windows to the sides".

The button-layout row (``windows.toml``) already offers exactly the five
curated layouts the descriptor was authored with — DESIGN.md is explicit that
the visual drag-and-drop builder is deferred, so this page renders it as the
ordinary ``choice`` row it is and builds nothing extra for it.

The workspace-count row's ``requires_first`` (turning off automatic desktops)
is handled entirely by the frozen row library — this page does not special
case it.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from ...core.backends import get_backend  # noqa: E402
from ...panels.descriptor import DomainDescriptor, Row, WidgetKind  # noqa: E402
from ...panels.loader import load_domains  # noqa: E402
from ...panels.widgets import build_row, set_link_handler  # noqa: E402
from ...ui.widgets.rows import set_plain_text  # noqa: E402
from ._style_common import get_probe  # noqa: E402

__all__ = ["build"]

PAGE_ID = "windows"
BANNER_ID = "first-visit-windows"

#: The three files this page draws from, in the order they render.
_DOMAIN_IDS = ("windows", "shortcuts", "mediakeys")

#: Where the impatience cross-link sits: right after the domain's own
#: animation-speed row, so the hint appears next to the control it extends.
_ANIMATION_ROW_ID = "org.gnome.desktop.interface:enable-animations"


def _search_text(row: Row) -> str:
    return " ".join([row.title, row.subtitle, *row.synonyms])


def _add_row(window, container, row: Row, *, backend, probe, into_expander: bool) -> None:
    widget, refresh = build_row(backend, row, probe=probe)
    if into_expander:
        container.add_row(widget)
    else:
        container.add(widget)
    window.rows.register(PAGE_ID, row.id, widget, refresh=refresh, search_text=_search_text(row))
    if row.id == _ANIMATION_ROW_ID:
        link = _build_impatience_link(window, backend)
        if into_expander:
            container.add_row(link)
        else:
            container.add(link)


def _build_impatience_link(window, backend) -> Adw.ActionRow:
    """A way through to finer animation-speed control, not a control itself.

    Authored on the page rather than in ``data/domains``: this row addresses
    no setting, so it is a hand-placed hint next to one specific control, not
    a descriptor of core GNOME. It still goes through :func:`build_row` and
    the LINK kind's own handler slot, so it looks and behaves exactly like a
    descriptor-driven link row — moving to the Add-ons page is one call to
    :meth:`window.show_page`.
    """
    row = Row(
        title="Want finer control over how fast things move?",
        subtitle="The Impatience add-on lets you set an exact speed instead of just on or off.",
        kind=WidgetKind.LINK,
        link_target="page:addons",
        reset=False,
    )
    widget, _refresh = build_row(backend, row)
    set_link_handler(widget, row, lambda target: window.show_page(target.removeprefix("page:")))
    window.rows.register(PAGE_ID, row.id, widget, search_text=_search_text(row))
    return widget


def _basic_and_advanced(domain: DomainDescriptor) -> tuple[list[Row], list[Row]]:
    basic = [row for row in domain.rows if not row.advanced]
    advanced = [row for row in domain.rows if row.advanced]
    return basic, advanced


def _open_group(window, page: Adw.PreferencesPage, domain: DomainDescriptor, *, backend, probe) -> None:
    """``windows.toml`` — rendered directly, since this is the main event."""
    # Three of the five domain files this page renders have a literal "&" in
    # their title. set_plain_text turns Pango markup off where the widget can
    # (a row) and escapes where it cannot (a group), so neither one vanishes.
    group = Adw.PreferencesGroup()
    set_plain_text(group, title=domain.title)
    basic, advanced = _basic_and_advanced(domain)
    for row in basic:
        _add_row(window, group, row, backend=backend, probe=probe, into_expander=False)
    if advanced:
        expander = Adw.ExpanderRow(
            title="Advanced",
            subtitle=f"{len(advanced)} more controls most people never need to touch",
        )
        for row in advanced:
            _add_row(window, expander, row, backend=backend, probe=probe, into_expander=True)
        group.add(expander)
    page.add(group)


def _collapsed_group(
    window, page: Adw.PreferencesPage, domain: DomainDescriptor, *, backend, probe
) -> None:
    """``shortcuts.toml`` / ``mediakeys.toml`` — a folded list of many rows."""
    noun = "keys" if domain.id == "mediakeys" else "shortcuts"
    group = Adw.PreferencesGroup()
    expander = Adw.ExpanderRow()
    set_plain_text(
        expander,
        title=domain.title,
        subtitle=f"{len(domain.rows)} {noun} you can set or change",
    )
    for row in domain.rows:
        _add_row(window, expander, row, backend=backend, probe=probe, into_expander=True)
    group.add(expander)
    page.add(group)


def build(window) -> Gtk.Widget:
    backend = get_backend()
    probe = get_probe(window)
    all_domains, problems = load_domains()
    if problems:
        raise RuntimeError("the descriptor corpus did not load: " + "; ".join(problems))
    domains = {domain.id: domain for domain in all_domains if domain.id in _DOMAIN_IDS}

    page = Adw.PreferencesPage()
    if "windows" in domains:
        _open_group(window, page, domains["windows"], backend=backend, probe=probe)
    for domain_id in ("shortcuts", "mediakeys"):
        if domain_id in domains:
            _collapsed_group(window, page, domains[domain_id], backend=backend, probe=probe)

    if window.prefs.should_show_banner(BANNER_ID):
        banner = Adw.Banner(
            title="Window buttons, desktop switching and every keyboard shortcut live here.",
            revealed=True,
        )
        banner.set_button_label("Got it")

        def _dismiss(*_args: object) -> None:
            window.prefs.mark_banner_seen(BANNER_ID)
            banner.set_revealed(False)

        banner.connect("button-clicked", _dismiss)
        wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        wrapper.append(banner)
        page.set_vexpand(True)
        wrapper.append(page)
        return wrapper

    return page
