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

from gi.repository import Adw, Gtk  # noqa: E402

from ...core.backends import get_backend  # noqa: E402
from ...panels.descriptor import DomainDescriptor, Row, WidgetKind  # noqa: E402
from ...panels.loader import load_domains  # noqa: E402
from ...panels.widgets import build_row, set_link_handler  # noqa: E402
from ...ui.widgets.rows import set_plain_text  # noqa: E402
from ..widgets.explainer import with_first_visit_banner  # noqa: E402
from ._style_common import get_probe  # noqa: E402

__all__ = ["build"]

PAGE_ID = "topbar"
BANNER_ID = "first-visit-topbar"

#: What the first-visit explainer says. Named rather than inlined so the
#: plain-language lint can read it without parsing the page.
BANNER_TEXT = "The clock, the date, the app view and the top bar's own style live here."

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


# -- the top bar's own style lives on Colours & Style -------------------------


def _style_group(window, page: Adw.PreferencesPage, domain: DomainDescriptor, *, backend, probe) -> None:
    """A way through to the style picker, not a second copy of it.

    This page used to build its own picker for
    ``org.gnome.shell.extensions.user-theme name``, and so does Colours &
    Style. Two pickers on one setting is two of everything: two lists of
    installed styles that can disagree about what is installed, two "the value
    is not one gtheme found" fallbacks, and — the one that actually hurts —
    only one of the two knew that the setting does nothing at all until the
    User Themes add-on is switched on, and offered to switch it on.

    A person who changes the top bar's style here and sees nothing happen has
    been told a lie by the control. So there is one owner now, and it is the
    one with the fix in it. This is a signpost: it says where the setting
    lives and takes you there.
    """
    row = Row(
        title="The top bar's style",
        subtitle="Set on the Colours & Style page, along with everything else that changes how the desktop looks.",
        kind=WidgetKind.LINK,
        link_target="page:colors",
        reset=False,
    )
    group = Adw.PreferencesGroup()
    set_plain_text(group, title=domain.title)
    widget, _refresh = build_row(backend, row)
    set_link_handler(widget, row, lambda target: window.show_page(target.removeprefix("page:")))
    group.add(widget)
    window.rows.register(PAGE_ID, row.id, widget, search_text=_search_text(row))
    page.add(group)


def build(window) -> Gtk.Widget:
    backend = get_backend()
    probe = get_probe(window)
    all_domains, problems = load_domains()
    domains = {domain.id: domain for domain in all_domains if domain.id in _DOMAIN_IDS}
    # One malformed file in ``data/domains/`` used to take this page down even
    # when the page never renders it — a version-skewed ``peripherals.toml``
    # and the top bar refused to open, while the other thirteen pages degraded
    # gracefully (review-report M30). Problems are the loader's, one per file;
    # only the ones naming a file this page draws from are this page's, and
    # each problem is prefixed with its file name, whose stem is the domain id.
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
    if "topbar" in domains:
        _clock_group(window, page, domains["topbar"], backend=backend, probe=probe)
    if "topbarstyle" in domains:
        _style_group(window, page, domains["topbarstyle"], backend=backend, probe=probe)

    return with_first_visit_banner(
        page, getattr(window, "prefs", None), BANNER_ID, BANNER_TEXT
    )
