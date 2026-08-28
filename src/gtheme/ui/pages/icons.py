"""Icons & Pointer — the small pictures, and the arrow you move with the mouse.

Both choices are made by looking, not by reading a list of names: an icon set is
shown as a row of its own icons, and the pointer styles are shown as tiles. A
name in a dropdown tells a person nothing about what they are about to get,
which is the single most-repeated failure in every settings app this one was
measured against.

Two honesty notes are built into the page rather than left to a README:

* **Most computers have exactly one pointer style installed.** A grid with one
  entry looks broken unless it says why, so it does.
* **A pointer style cannot be drawn from inside an app.** Its images are not
  icons and no toolkit will render them into a preview, so the tile shows the
  style's name and an arrow, and does not pretend to be a preview of it.
"""

from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gtk, Pango  # noqa: E402

from ...core.settings_backend import SettingsBackend  # noqa: E402
from ...panels.descriptor import Row  # noqa: E402
from ...system.iconscan import (  # noqa: E402
    IconThemeEntry,
    cursor_themes,
    default_icon_roots,
    scan_icon_themes,
)
from ..widgets import a11y  # noqa: E402
from ..widgets.rows import attach_reset, key_for, write_value  # noqa: E402
from ._style_common import PageShell, quote, unquote, value_or_none  # noqa: E402

__all__ = [
    "COPY",
    "SAMPLE_ICONS",
    "build",
    "icon_grid",
    "icon_set_description",
    "icon_sets",
    "pointer_description",
    "sample_images",
]


#: Every sentence this page says, in one place, so it can be read and linted as
#: a whole.
COPY: dict[str, str] = {
    "banner": (
        "Pick by looking. Every choice here takes effect straight away, and "
        "Undo & Restore Points puts any of it back."
    ),
    "icons-group": "Icon set",
    "icons-description": (
        "The small pictures used for apps, folders and files. Each tile below "
        "shows that set's own pictures."
    ),
    # The pointer group has said this since it was written; the icon group did
    # not, so a fresh Fedora showed one tile and left the reader to guess
    # whether that was all there is (persona-report §3.2). Same shape, same
    # promise, different noun.
    "icons-only-one": (
        "Only one icon set is installed on this computer. More can be added "
        "from your software app, and a Look can bring one with it."
    ),
    "icons-none": (
        "gtheme could not find any icon sets on this computer, which is "
        "unusual. The ones in use still work."
    ),
    "pointer-group": "Mouse pointer",
    "pointer-description": (
        "How the arrow you move with the mouse looks, and how big it is."
    ),
    "pointer-only-one": (
        "Only one pointer style is installed on this computer. More can be "
        "added from your software app, and a Look can bring one with it."
    ),
    "pointer-none": (
        "gtheme could not find any pointer styles on this computer, which is "
        "unusual. The one in use still works."
    ),
    "pointer-not-drawable": (
        "A pointer cannot be drawn inside a window, so these show the name "
        "rather than the shape. Pick one and look at your own pointer."
    ),
}

#: The four icons every tile shows. Chosen because every icon set in existence
#: draws all four, and because they are the four a person recognises: their
#: files, their pictures, their music, their settings.
SAMPLE_ICONS: tuple[str, ...] = (
    "folder",
    "text-x-generic",
    "audio-x-generic",
    "applications-system",
)

ICON_THEME_ID = "org.gnome.desktop.interface:icon-theme"
CURSOR_THEME_ID = "org.gnome.desktop.interface:cursor-theme"

_TILE_CSS = """
.gtheme-icon-tile { padding: 8px; border-radius: 12px; }
.gtheme-icon-tile-name { font-size: 0.9em; }
"""

_CSS_INSTALLED = False


def _install_css() -> None:
    global _CSS_INSTALLED
    if _CSS_INSTALLED:
        return
    display = Gdk.Display.get_default()
    if display is None:  # pragma: no cover - no display, no styling to do
        return
    provider = Gtk.CssProvider()
    provider.load_from_string(_TILE_CSS)
    Gtk.StyleContext.add_provider_for_display(
        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    _CSS_INSTALLED = True


# --------------------------------------------------------------------------
# rendered samples
# --------------------------------------------------------------------------


def sample_images(
    entry: IconThemeEntry,
    names: tuple[str, ...] = SAMPLE_ICONS,
    *,
    size: int = 32,
) -> Gtk.Box:
    """A row of one icon set's own icons, at real size.

    A private :class:`Gtk.IconTheme` is built per set, rather than the
    display's: asking the display's theme for an icon would answer with the
    icon set currently *in use*, so every tile would look identical and picking
    one would be a coin toss.
    """
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    theme = Gtk.IconTheme()
    theme.set_search_path([str(root) for root in default_icon_roots()])
    theme.set_theme_name(entry.directory_name)
    for name in names:
        paintable = theme.lookup_icon(
            name, None, size, 1, Gtk.TextDirection.LTR, Gtk.IconLookupFlags.FORCE_REGULAR
        )
        image = Gtk.Image.new_from_paintable(paintable)
        image.set_pixel_size(size)
        box.append(image)
    return box


def _pointer_sample(size: int = 32) -> Gtk.Image:
    """The stand-in for a pointer style. Deliberately not a claim of preview."""
    image = Gtk.Image.new_from_icon_name("input-mouse-symbolic")
    image.set_pixel_size(size)
    return image


# --------------------------------------------------------------------------
# the grids
# --------------------------------------------------------------------------


def icon_grid(
    backend: SettingsBackend,
    row: Row,
    entries: list[IconThemeEntry],
    *,
    sample: Any = None,
    noun: str = "icon set",
) -> tuple[Gtk.FlowBox, Any]:
    """A grid of tiles, one per installed set, with the current one checked.

    Args:
        backend: where the choice is read and written.
        row: the descriptor being chosen — the icon set or the pointer style.
        entries: what is installed, in the order to show.
        sample: builds the picture part of a tile from an entry. Defaults to
            that set's own icons.
        noun: what one tile *is*, for somebody who cannot see the grid it is
            in. A tile called "Papirus" tells a screen reader nothing about
            what choosing it would do; "Papirus icon set" does. The group
            heading carries that word for everyone else.

    Returns:
        ``(grid, refresh)``, so the grid can be refreshed like any row when the
        value changes somewhere else.
    """
    _install_css()
    build_sample = sample if sample is not None else sample_images
    grid = Gtk.FlowBox(
        valign=Gtk.Align.START,
        homogeneous=True,
        max_children_per_line=4,
        min_children_per_line=1,
        selection_mode=Gtk.SelectionMode.NONE,
        row_spacing=6,
        column_spacing=6,
    )
    key = key_for(row)
    guard = {"busy": False}
    buttons: dict[str, Gtk.ToggleButton] = {}
    first: Gtk.ToggleButton | None = None

    def choose(name: str) -> None:
        if guard["busy"]:
            return
        if not write_value(
            backend, key, quote(name), widget=grid, refresh=refresh, component=row.id
        ):
            return
        refresh()

    for entry in entries:
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        pictures = build_sample(entry)
        # The sample icons are the tile's picture, not its name: four pictures
        # announced one after another ("folder, text, audio, settings") in front
        # of every tile would bury the one word that distinguishes them. The
        # tile itself carries the name, below.
        a11y.hide_from_screen_readers(pictures)
        content.append(pictures)
        content.append(
            Gtk.Label(
                label=entry.display_name,
                css_classes=["gtheme-icon-tile-name"],
                ellipsize=Pango.EllipsizeMode.END,
                max_width_chars=16,
            )
        )
        button = Gtk.ToggleButton(
            child=content,
            css_classes=["flat", "gtheme-icon-tile"],
            tooltip_text=entry.display_name,
        )
        # The visible label is ellipsised at sixteen characters, and a tooltip
        # is a *description* to a screen reader, never a name — so a tile whose
        # name did not fit had no readable name at all (persona-report §2.10).
        a11y.name(button, f"{entry.display_name} {noun}")
        if first is None:
            first = button
        else:
            button.set_group(first)
        button.connect(
            "toggled",
            lambda b, n=entry.directory_name: choose(n) if b.get_active() else None,
        )
        buttons[entry.directory_name] = button
        grid.append(button)

    def refresh() -> None:
        guard["busy"] = True
        try:
            raw = value_or_none(backend, key)
            current = unquote(raw) if raw is not None else ""
            for name, button in buttons.items():
                button.set_active(name == current)
        finally:
            guard["busy"] = False

    refresh()
    return grid, refresh


def _grid_group(
    shell: PageShell,
    descriptor_id: str,
    title: str,
    description: str,
    entries: list[IconThemeEntry],
    *,
    sample: Any = None,
    noun: str = "icon set",
) -> Adw.PreferencesGroup | None:
    """A titled group holding one grid, with the row's own explainer above it.

    The grid is the control, but a grid cannot carry a title, a subtitle or the
    "put this back" button. So the group holds two rows: an ordinary row that
    says what this changes and carries the reset button — built by the frozen
    row library's own :func:`~gtheme.ui.widgets.rows.attach_reset`, not a copy
    of it — and the grid itself beneath.
    """
    row = shell.descriptor(descriptor_id)
    if row is None:  # pragma: no cover - the corpus always has these
        return None
    group = shell.group(title, description)
    grid, refresh = icon_grid(shell.backend, row, entries, sample=sample, noun=noun)
    label_row = Adw.ActionRow(title=row.title, subtitle=row.subtitle)
    group.add(label_row)
    group.add(Adw.PreferencesRow(activatable=False, focusable=False, child=grid))
    if row.reset:
        refresh = attach_reset(shell.backend, row, label_row, refresh)
    shell.register(row, grid, refresh)
    return group


# --------------------------------------------------------------------------
# the page
# --------------------------------------------------------------------------


def icon_set_description(count: int) -> str:
    """What the icon-set group says, given how many sets are installed.

    The same courtesy the pointer group has always paid: a grid with one tile
    in it looks broken, and on a bare Arch or a fresh Fedora one tile is the
    normal state. Saying so is the difference between "this app cannot see my
    icon sets" and "this computer has one".
    """
    if count == 0:
        return COPY["icons-none"]
    if count == 1:
        return f"{COPY['icons-description']} {COPY['icons-only-one']}"
    return COPY["icons-description"]


def pointer_description(count: int) -> str:
    """What the pointer group says, given how many styles are installed.

    A grid with one tile in it looks broken. On a stock GNOME install that is
    the normal state — exactly one pointer style ships — so the group says so
    instead of leaving a person wondering what went wrong.
    """
    if count == 0:
        return COPY["pointer-none"]
    if count == 1:
        return f"{COPY['pointer-description']} {COPY['pointer-only-one']}"
    return f"{COPY['pointer-description']} {COPY['pointer-not-drawable']}"


def _has_icon_directories(entry: IconThemeEntry) -> bool:
    """Does this directory hold any icons, or only a pointer?

    The scanner calls anything with an ``index.theme`` and a ``Name=`` an icon
    theme, which is right for what it is for — but a pointer style such as
    Bibata has exactly that and nothing else: one ``cursors`` folder and no
    icon folders at all. Structure is the only thing that tells them apart,
    which is the same test the scanner uses to find pointer styles, inverted.
    """
    try:
        return any(
            child.is_dir() and child.name != "cursors" for child in entry.path.iterdir()
        )
    except OSError:  # pragma: no cover - a directory that went away mid-scan
        return True


def icon_sets(entries: list[IconThemeEntry]) -> list[IconThemeEntry]:
    """Entries usable as ``interface icon-theme`` — pointer-only ones dropped.

    Offering a pointer style as an icon set gave tiles with no pictures in
    them, and choosing one wrote a pointer style's name into the icon setting:
    nothing visible changed, and nothing said why. A theme that is both — the
    desktop's own Adwaita is both — stays in both grids, because it really is
    both.
    """
    return [e for e in entries if not e.is_cursor_theme or _has_icon_directories(e)]


def build(window: Any) -> Gtk.Widget:
    """Build the Icons & Pointer page."""
    _install_css()
    shell = PageShell(
        window,
        "icons",
        banner_id="first-visit-icons",
        banner_text=COPY["banner"],
    )
    entries = scan_icon_themes(default_icon_roots())
    pointers = cursor_themes(entries)
    sets = icon_sets(entries)

    _grid_group(
        shell,
        ICON_THEME_ID,
        COPY["icons-group"],
        icon_set_description(len(sets)),
        sets,
    )

    pointer_group = _grid_group(
        shell,
        CURSOR_THEME_ID,
        COPY["pointer-group"],
        pointer_description(len(pointers)),
        pointers,
        sample=lambda _entry: _pointer_sample(),
        noun="pointer style",
    )
    if pointer_group is not None:
        shell.add_descriptor_row(pointer_group, "org.gnome.desktop.interface:cursor-size")
        shell.add_descriptor_row(pointer_group, "org.gnome.desktop.interface:locate-pointer")

    return shell.finish()
