"""The page manifest — the app's whole information architecture, as data.

THE CONTRACT IS FROZEN (DESIGN.md A6, F8). All fifteen pages are listed here,
in order, before any of them is written. Two consequences, both deliberate:

* **No agent building a page ever edits this file.** The manifest already names
  the module and the function; the page author implements what it names. There
  is no import line to add, so there is no merge conflict to have.
* **The sidebar is not written by hand anywhere.** ``window.py`` builds it by
  walking :data:`MANIFEST`, so a page cannot exist without appearing in the
  sidebar, and cannot appear in the sidebar without existing.

Factories are *strings*, not imports: ``"gtheme.ui.pages.home:build"`` is
resolved by :func:`load_factory` the first time a page is shown. Importing
fifteen page modules at startup would pull in every scanner and client the app
has before the window appears.

**Where descriptor ids live.** They are not in this file. The manifest stores
page identity only; which settings appear on which page is decided in
``data/domains/coverage.toml``, where each key of the coverage universe is
dispositioned ``surfaced(<page>)``, ``compound(<op>)``, ``floor``,
``excluded(<reason>)`` or ``delegated(<target>)``. :func:`resolve_surfaced`
inverts those dispositions into ``{page_id: [descriptor_id, ...]}`` at runtime.
So adding a setting to a page is a data edit, never a code edit, and
:func:`resolve_surfaced` raising on an unknown page id is what keeps the data
and this manifest from drifting apart.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

__all__ = [
    "MANIFEST",
    "SECTIONS",
    "FLOOR_PAGE_ID",
    "PageDescriptor",
    "get",
    "load_factory",
    "page_ids",
    "pages_in_section",
    "resolve_surfaced",
]


@dataclass(frozen=True)
class PageDescriptor:
    """One entry in the sidebar.

    Args:
        id: stable identifier. Used by ``coverage.toml``, by deep links, and as
            the screenshot filename stem. Never shown to the user.
        title: the sidebar label. Plain language; the jargon lint checks it.
        subtitle: one short line under the title, or None.
        icon: a symbolic icon name from the system icon theme.
        section: which sidebar group this sits in. Must be in :data:`SECTIONS`.
        factory: ``"module.path:function"``. The function takes the app window
            and returns a ``Gtk.Widget``.
    """

    id: str
    title: str
    subtitle: str | None
    icon: str
    section: str
    factory: str


#: Sidebar groups, in order. Four of them, and the names are the user's words:
#: nobody has to know what a "setting" is to understand "Change one thing".
SECTIONS: tuple[str, ...] = (
    "Welcome",
    "Change one thing",
    "System",
    "Safety",
)

#: The page that catches everything not placed on a named page. Every key of
#: the coverage universe dispositioned ``floor`` renders here as an
#: auto-generated row, so "nothing was left out" holds even for settings nobody
#: got around to designing a home for.
FLOOR_PAGE_ID = "more"


MANIFEST: tuple[PageDescriptor, ...] = (
    # ---- Welcome ---------------------------------------------------------
    PageDescriptor(
        id="home",
        title="Home",
        subtitle="How your desktop looks right now",
        icon="go-home-symbolic",
        section="Welcome",
        factory="gtheme.ui.pages.home:build",
    ),
    PageDescriptor(
        id="looks",
        title="Looks",
        subtitle="Change everything at once",
        icon="starred-symbolic",
        section="Welcome",
        factory="gtheme.ui.pages.looks:build",
    ),
    # ---- Change one thing -------------------------------------------------
    PageDescriptor(
        id="wallpaper",
        title="Wallpaper",
        subtitle="The picture behind everything",
        icon="image-x-generic-symbolic",
        section="Change one thing",
        factory="gtheme.ui.pages.wallpaper:build",
    ),
    PageDescriptor(
        id="colors",
        title="Colours & Style",
        subtitle="Light or dark, and the highlight colour",
        icon="applications-graphics-symbolic",
        section="Change one thing",
        factory="gtheme.ui.pages.colors:build",
    ),
    PageDescriptor(
        id="icons",
        title="Icons & Pointer",
        subtitle="App icons and the mouse pointer",
        icon="view-grid-symbolic",
        section="Change one thing",
        factory="gtheme.ui.pages.icons:build",
    ),
    PageDescriptor(
        id="fonts",
        title="Fonts & Text",
        subtitle="Which text, and how big",
        icon="font-x-generic-symbolic",
        section="Change one thing",
        factory="gtheme.ui.pages.fonts:build",
    ),
    PageDescriptor(
        id="topbar",
        title="Top Bar & Overview",
        subtitle="The bar across the top, and the app view",
        icon="view-continuous-symbolic",
        section="Change one thing",
        factory="gtheme.ui.pages.topbar:build",
    ),
    PageDescriptor(
        id="windows",
        title="Windows & Desktops",
        subtitle="Window buttons, workspaces and shortcuts",
        icon="view-restore-symbolic",
        section="Change one thing",
        factory="gtheme.ui.pages.windows:build",
    ),
    PageDescriptor(
        id="addons",
        title="Add-ons",
        subtitle="Extra features you can switch on",
        icon="application-x-addon-symbolic",
        section="Change one thing",
        factory="gtheme.ui.pages.addons:build",
    ),
    PageDescriptor(
        id="terminal",
        title="Terminal",
        subtitle="The look of your command window",
        icon="utilities-terminal-symbolic",
        section="Change one thing",
        factory="gtheme.ui.pages.terminal:build",
    ),
    # ---- System -----------------------------------------------------------
    PageDescriptor(
        id="nightlight",
        title="Night Light & Timing",
        subtitle="Warmer colours in the evening",
        icon="weather-clear-night-symbolic",
        section="System",
        factory="gtheme.ui.pages.nightlight:build",
    ),
    PageDescriptor(
        id="sound",
        title="Sound",
        subtitle="The noises your desktop makes",
        icon="audio-speakers-symbolic",
        section="System",
        factory="gtheme.ui.pages.sound:build",
    ),
    PageDescriptor(
        id="power",
        title="Power & Screen",
        subtitle="When the screen dims and sleeps",
        icon="preferences-system-power-symbolic",
        section="System",
        factory="gtheme.ui.pages.power:build",
    ),
    PageDescriptor(
        id=FLOOR_PAGE_ID,
        title="More Settings",
        subtitle="Everything else, searchable",
        icon="view-more-symbolic",
        section="System",
        factory="gtheme.ui.pages.more:build",
    ),
    # ---- Safety -----------------------------------------------------------
    PageDescriptor(
        id="restore",
        title="Undo & Restore Points",
        subtitle="Go back to how it was",
        icon="edit-undo-symbolic",
        section="Safety",
        factory="gtheme.ui.pages.restore:build",
    ),
)

_BY_ID = {page.id: page for page in MANIFEST}


def page_ids() -> tuple[str, ...]:
    """Every page id, in sidebar order."""
    return tuple(page.id for page in MANIFEST)


def get(page_id: str) -> PageDescriptor:
    """Look a page up by id.

    Raises:
        KeyError: no such page. Callers should not catch this — an unknown page
            id means data and manifest have drifted, which is a bug to fix and
            not a condition to handle.
    """
    try:
        return _BY_ID[page_id]
    except KeyError:
        raise KeyError(
            f"no page {page_id!r}; known pages: {', '.join(page_ids())}"
        ) from None


def pages_in_section(section: str) -> tuple[PageDescriptor, ...]:
    """The pages of one sidebar group, in order."""
    return tuple(page for page in MANIFEST if page.section == section)


def load_factory(page: PageDescriptor | str) -> Callable[..., object]:
    """Import and return a page's build function.

    Raises:
        ImportError: the module named in the manifest does not exist.
        AttributeError: it exists but has no such function.
    """
    descriptor = page if isinstance(page, PageDescriptor) else get(page)
    module_path, _, attr = descriptor.factory.partition(":")
    if not attr:
        raise ValueError(f"{descriptor.id}: factory must be 'module:function', got {descriptor.factory!r}")
    module = importlib.import_module(module_path)
    return getattr(module, attr)


def resolve_surfaced(dispositions: Mapping[str, str]) -> dict[str, list[str]]:
    """Invert coverage dispositions into per-page descriptor id lists.

    Args:
        dispositions: ``{descriptor_id: disposition}`` as read from
            ``data/domains/coverage.toml``. Recognised dispositions are
            ``surfaced(<page>)``, ``compound(<op>)``, ``floor``,
            ``excluded(<reason>)`` and ``delegated(<target>)``.

    Returns:
        ``{page_id: [descriptor_id, ...]}`` covering every page in the
        manifest, empty lists included. Keys dispositioned ``floor`` land on
        :data:`FLOOR_PAGE_ID`; the other dispositions do not produce rows here
        (``compound`` rows are hand-built two-key controls, ``excluded`` and
        ``delegated`` keys are deliberately not shown).

    Raises:
        ValueError: a ``surfaced(...)`` disposition names a page that is not in
            the manifest, or a disposition is not one of the five recognised
            forms. Both mean the data and this file have drifted apart, and
            failing loudly here is the whole point of the check.
    """
    out: dict[str, list[str]] = {page.id: [] for page in MANIFEST}
    for key, raw in dispositions.items():
        verb, _, arg = raw.partition("(")
        verb = verb.strip()
        arg = arg.rstrip(")").strip() if arg else ""
        if verb == "surfaced":
            if arg not in out:
                raise ValueError(
                    f"{key}: surfaced({arg}) names no page in the manifest; "
                    f"known pages: {', '.join(page_ids())}"
                )
            out[arg].append(key)
        elif verb == "floor":
            out[FLOOR_PAGE_ID].append(key)
        elif verb in {"compound", "excluded", "delegated"}:
            continue
        else:
            raise ValueError(
                f"{key}: {raw!r} is not a disposition; expected one of "
                "surfaced(page), compound(op), floor, excluded(reason), delegated(target)"
            )
    return out


def check_sections(pages: Iterable[PageDescriptor] = MANIFEST) -> None:
    """Raise if any page claims a section that is not in :data:`SECTIONS`."""
    for page in pages:
        if page.section not in SECTIONS:
            raise ValueError(f"{page.id}: unknown section {page.section!r}")
