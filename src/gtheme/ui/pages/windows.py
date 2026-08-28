"""Windows & Desktops — DESIGN.md A6/§C step 16.

Window buttons, focus behaviour, titlebar clicks, tiling, desktops, and every
keyboard shortcut the desktop itself watches for. The last two domains
(``shortcuts.toml``, ``mediakeys.toml``) are 175 rows between them — a flat
list of that size is unusable, so they do not render as a flat list.

**Two accordions were not enough** (persona-report §3.2). Folding 123 shortcuts
into one collapsed row and 52 into another moved the problem rather than
solving it: opening either one gave back the same corpus-ordered wall, with no
headings to steer by and no way to narrow it. Somebody looking for "move this
window to the next screen" had to read past ninety things they were not looking
for. So this page does three things instead:

* **Sections.** Each of the two domains is cut into named groups —
  :func:`shortcut_sections` — by what the shortcut *does*, not by which file it
  came from. The names are the page's, because the keys are GNOME's and are
  named for programmers (``move-to-monitor-up``, ``playback-rewind``).
* **A box to narrow them.** Type "screen" and everything else goes away,
  sections and all. It matches the same words the app-wide search matches, so
  the two never disagree about what a row is called.
* **A sentence saying Ctrl+F exists.** The real answer to "where is the
  shortcut for X" is the app's own search, and nothing on the page said so.

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

from typing import Any  # noqa: E402

from gi.repository import Adw, Gtk  # noqa: E402

from ...core.backends import get_backend  # noqa: E402
from ...panels.descriptor import DomainDescriptor, Row, WidgetKind  # noqa: E402
from ...panels.loader import load_domains  # noqa: E402
from ...panels.widgets import build_row, set_link_handler  # noqa: E402
from ...ui.widgets.rows import set_plain_text  # noqa: E402
from ..search import ADVANCED_SUBTITLE, ADVANCED_TITLE  # noqa: E402
from ..widgets.explainer import with_first_visit_banner  # noqa: E402
from ._style_common import get_probe  # noqa: E402

__all__ = ["COPY", "SECTIONS", "build", "shortcut_sections"]

PAGE_ID = "windows"
BANNER_ID = "first-visit-windows"

#: What the first-visit explainer says. Named rather than inlined so the
#: plain-language lint can read it without parsing the page.
BANNER_TEXT = "Window buttons, desktop switching and every keyboard shortcut live here."

#: Everything this page says that is not a descriptor's own words.
COPY: dict[str, str] = {
    "filter-placeholder": "Type to narrow this list",
    "filter-hint": (
        "There are {count} of these, in groups. Type in the box to narrow them "
        "down — or press Ctrl+F to search everything in gtheme at once."
    ),
    "filter-empty": "Nothing here matches “{text}”.",
}

#: The three files this page draws from, in the order they render.
_DOMAIN_IDS = ("windows", "shortcuts", "mediakeys")

#: How the two big domains are cut up, in the order the sections render.
#:
#: Matched on the setting's own key name by substring, first rule wins, and the
#: last entry of each list is the catch-all. Key names are the only thing that
#: groups these: the corpus has no notion of a section, GNOME's schemas have no
#: notion of one either, and hand-listing 175 ids would rot the first time
#: GNOME added a shortcut. The names on the left are this page's own words —
#: nobody outside a bug tracker calls it "rfkill".
SECTIONS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "shortcuts": (
        ("Desktops and screens", ("workspace", "monitor")),
        ("Pictures of your screen", ("screenshot", "screen-recording")),
        ("Screen brightness", ("brightness",)),
        ("Your apps", ("application-1", "application-2", "application-3", "application-4",
                       "application-5", "application-6", "application-7", "application-8",
                       "application-9")),
        (
            "The top bar, the overview and menus",
            (
                "overview",
                "application-view",
                "message-tray",
                "quick-settings",
                "notification",
                "panel",
                "show-desktop",
            ),
        ),
        ("Moving between windows", ("switch-applications", "switch-windows", "switch-group",
                                    "cycle-")),
        ("Typing", ("input-source", "input-capture")),
        ("The window you are using", ()),
    ),
    "mediakeys": (
        ("Sound", ("volume", "mic-mute")),
        # "rotate-video-lock" is not about video: it locks which way up the
        # screen is. Its own title says so, and it sits with the other hardware
        # switches rather than with the play button.
        ("Music and video", ("play", "pause", "stop", "next", "previous", "playback",
                             "eject")),
        (
            "Opening things",
            ("www", "email", "calculator", "home", "search", "help", "control-center",
             "media"),
        ),
        (
            "Ease of use",
            ("magnifier", "screenreader", "on-screen-keyboard", "contrast", "text-size"),
        ),
        (
            "The keyboard, the touchpad and the screen",
            ("touchpad", "keyboard-brightness", "rfkill", "rotate-video"),
        ),
        ("Turning the computer off", ("screensaver", "logout", "shutdown", "reboot",
                                      "suspend", "hibernate", "power", "battery")),
        ("Everything else", ()),
    ),
}

#: Where the impatience cross-link sits: right after the domain's own
#: animation-speed row, so the hint appears next to the control it extends.
_ANIMATION_ROW_ID = "org.gnome.desktop.interface:enable-animations"


def _search_text(row: Row) -> str:
    return " ".join([row.title, row.subtitle, *row.synonyms])


def shortcut_sections(domain: DomainDescriptor) -> list[tuple[str, list[Row]]]:
    """One domain's rows, cut into named sections, in rendering order.

    Every row lands in exactly one section, sections that would be empty are
    dropped, and a domain with no rules for it comes back as a single section
    under its own title — so this is safe to call on anything.
    """
    rules = SECTIONS.get(domain.id)
    if rules is None:
        return [(domain.title, list(domain.rows))]
    buckets: dict[str, list[Row]] = {title: [] for title, _patterns in rules}
    catch_all = rules[-1][0]
    for row in domain.rows:
        key = (row.key or "").lower()
        for title, patterns in rules:
            if patterns and any(pattern in key for pattern in patterns):
                buckets[title].append(row)
                break
        else:
            buckets[catch_all].append(row)
    return [(title, rows) for title, rows in buckets.items() if rows]


def _add_row(window, container, row: Row, *, backend, probe, into_expander: bool):
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
    return widget


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
        # The same words as every other page's collapsed tier. This page used
        # to say "Advanced" over its own sentence — a third wording for the
        # identical affordance, met by somebody who had already learned "More
        # options" on six other pages (review-report M29).
        expander = Adw.ExpanderRow()
        set_plain_text(expander, title=ADVANCED_TITLE, subtitle=ADVANCED_SUBTITLE)
        for row in advanced:
            _add_row(window, expander, row, backend=backend, probe=probe, into_expander=True)
        group.add(expander)
    page.add(group)


def _collapsed_group(
    window, page: Adw.PreferencesPage, domain: DomainDescriptor, *, backend, probe
) -> Adw.PreferencesGroup:
    """``shortcuts.toml`` / ``mediakeys.toml`` — many rows, in named sections.

    Each section is its own collapsed row, so the headings are readable without
    opening anything, and a box above them narrows the whole group at once.
    """
    noun = "keys" if domain.id == "mediakeys" else "shortcuts"
    group = Adw.PreferencesGroup()
    set_plain_text(
        group,
        title=domain.title,
        description=COPY["filter-hint"].format(count=f"{len(domain.rows)} {noun}"),
    )

    sections: list[tuple[Adw.ExpanderRow, list[tuple[Any, str]]]] = []
    for title, rows in shortcut_sections(domain):
        expander = Adw.ExpanderRow()
        set_plain_text(expander, title=title, subtitle=f"{len(rows)} of them")
        entries: list[tuple[Any, str]] = []
        for row in rows:
            widget = _add_row(
                window, expander, row, backend=backend, probe=probe, into_expander=True
            )
            entries.append((widget, _search_text(row).lower()))
        sections.append((expander, entries))

    nothing = Adw.ActionRow(visible=False)
    filter_row = _filter_row(domain, sections, nothing)
    group.add(filter_row)
    for expander, _entries in sections:
        group.add(expander)
    group.add(nothing)
    page.add(group)
    return group


def _filter_row(
    domain: DomainDescriptor,
    sections: list[tuple[Adw.ExpanderRow, list[tuple[Any, str]]]],
    nothing: Adw.ActionRow,
) -> Adw.PreferencesRow:
    """The box that narrows one group, and the sentence when nothing matches.

    Deliberately a plain filter over what is already on screen rather than a
    second search index: the app has one of those (Ctrl+F), it covers every
    page, and two searches that disagree about what a row is called would be
    worse than one search and one filter.
    """
    entry = Gtk.SearchEntry(
        placeholder_text=COPY["filter-placeholder"],
        name=f"gtheme-filter-{domain.id}",
        hexpand=True,
        margin_top=6,
        margin_bottom=6,
        margin_start=6,
        margin_end=6,
    )

    def apply_filter(*_args) -> None:
        needle = entry.get_text().strip().lower()
        matches = 0
        for expander, entries in sections:
            found = 0
            for widget, text in entries:
                hit = not needle or needle in text
                widget.set_visible(hit)
                found += bool(hit)
            expander.set_visible(bool(found))
            # Open what matched, close everything again when the box empties:
            # a filtered list nobody can see the results of is not a filter.
            expander.set_expanded(bool(needle) and bool(found))
            matches += found
        set_plain_text(nothing, title=COPY["filter-empty"].format(text=entry.get_text()))
        nothing.set_visible(bool(needle) and matches == 0)

    entry.connect("search-changed", apply_filter)
    row = Adw.PreferencesRow(activatable=False, focusable=False, child=entry)
    row.gtheme_filter = entry  # type: ignore[attr-defined]
    row.gtheme_apply_filter = apply_filter  # type: ignore[attr-defined]
    row.set_name(f"gtheme-filter-{domain.id}")
    return row


def build(window) -> Gtk.Widget:
    backend = get_backend()
    probe = get_probe(window)
    all_domains, problems = load_domains()
    domains = {domain.id: domain for domain in all_domains if domain.id in _DOMAIN_IDS}
    # One malformed file in ``data/domains/`` used to take this page down even
    # when the page never renders it — a version-skewed ``peripherals.toml``
    # and Windows & Desktops refused to open, throwing away 175 shortcut rows
    # that had loaded perfectly (review-report M30). Problems are the loader's,
    # one per file; only the ones naming a file this page draws from are this
    # page's, and each problem is prefixed with its file name, whose stem is
    # the domain id.
    mine = [
        problem
        for problem in problems
        if problem.split(":", 1)[0].removesuffix(".toml") in _DOMAIN_IDS
    ]
    if not domains:
        # Nothing at all to draw. An empty page would be a lie of omission, so
        # this is the one case that still refuses — and it says which file.
        raise RuntimeError(
            "the descriptor corpus did not load: "
            + ("; ".join(mine or problems) or "no descriptor files were found")
        )

    page = Adw.PreferencesPage()
    if "windows" in domains:
        _open_group(window, page, domains["windows"], backend=backend, probe=probe)
    for domain_id in ("shortcuts", "mediakeys"):
        if domain_id in domains:
            _collapsed_group(window, page, domains[domain_id], backend=backend, probe=probe)

    return with_first_visit_banner(
        page, getattr(window, "prefs", None), BANNER_ID, BANNER_TEXT
    )
