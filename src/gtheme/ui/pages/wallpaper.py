"""The Wallpaper page: the picture behind everything.

DESIGN.md §C step 14. What this page renders, and why it is shaped the way
it is:

* **Two independent picture grids**, light and dark. GNOME's own picker sets
  both from one paired catalogue entry; ``coverage.toml`` dispositions
  ``picture-uri`` and ``picture-uri-dark`` as two separate ``surfaced(wallpaper)``
  rows on purpose, so gtheme lets someone choose a dark picture that has
  nothing to do with their light one rather than forcing the GNOME pairing.
* **``picker`` rows are not built by the frozen row library.** ``kind =
  "picker"`` is a deliberate gap in ``ui.widgets.rows`` (its own docstring
  says so): the content comes from scanning the system, which is this
  module's job, not the base library's. This page IS the picker for
  ``org.gnome.desktop.background picture-uri``/``picture-uri-dark``.
* **A catalogue entry's ``<filename>`` is written to the setting exactly as
  the catalogue stores it**, slideshow or not: GNOME's own background handler
  is what notices a ``.xml`` extension and runs the slideshow, so gtheme does
  not have to evaluate one. The grid only uses the slideshow's *first static
  frame* to have something to show as a thumbnail, and marks the tile so a
  novice does not wonder why "today's" picture does not match the tile later.
* **The style rows** (how the picture fills the screen, the fallback colour,
  the colour fade) come straight from ``data/domains/wallpaper.toml`` through
  the frozen ``panels.widgets.build_row`` — same reset button, same greying,
  same everything every other page gets. Only the two picker rows are hand
  built here.
* **The lock screen has no control on this page, on purpose.** GNOME 50's
  screensaver mirrors the light background picture and has nothing that
  corresponds to a dark version; the honest thing is one sentence saying so,
  not a control that would either do nothing or lie about what it changed.
* **A picture you choose yourself joins the catalogue.** It used to be copied
  in under a name like ``custom-9f2c1a7b3e05.png`` and never appear in the grid
  again: set once, then invisible for ever, unfindable even by the person who
  chose it (persona-report §3.2). Choosing one now also writes a catalogue
  entry naming it — the same ``gnome-background-properties`` mechanism every
  other picture in the grid arrives through, so it comes back on the next
  launch, and shows up in GNOME's own picker too. The name comes from the file
  the reader picked, not from the copy's collision-proof one.
* **Slideshows can be chosen, not only received.** Three of the four bundled
  Looks set a slideshow, and the picker offered picture formats only, so the
  one kind of background gtheme itself uses most was the one kind you could not
  pick.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gio", "2.0")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from ...core.atomic import atomic_write_bytes  # noqa: E402
from ...core.backends import get_backend  # noqa: E402
from ...core.confine import ConfinementError, confine_dest  # noqa: E402
from ...core.settings_backend import BackendError, SettingsBackend  # noqa: E402
from ...panels import widgets as panel_widgets  # noqa: E402
from ...panels.descriptor import DomainDescriptor, Row  # noqa: E402
from ...panels.loader import load_corpus  # noqa: E402
from ...panels.schema_probe import SchemaProbe  # noqa: E402
from ...system.thumbnails import lookup_cached_thumbnail, request_thumbnail_async  # noqa: E402
from ...system.wallpapers import (  # noqa: E402
    SlideshowEvent,
    WallpaperEntry,
    default_wallpaper_catalogue_roots,
    parse_slideshow,
    scan_wallpaper_catalogue,
)
from ...ui.widgets.recording import (  # noqa: E402
    NOT_CHANGED,
    WriteRefused,
    reason_for,
    recording,
)
from ...ui.widgets.rows import key_for, quote, set_plain_text, unquote  # noqa: E402
from ..search import ADVANCED_TITLE  # noqa: E402
from ..widgets import a11y  # noqa: E402
from ._style_common import get_probe  # noqa: E402

__all__ = [
    "CUSTOM_CATALOGUE",
    "TILE_HEIGHT",
    "TILE_WIDTH",
    "GridTile",
    "build",
    "catalogue_entry_xml",
    "custom_catalogue_path",
    "readable_name",
    "record_in_catalogue",
    "tile_name",
]

#: Where a custom picture is copied to, relative to the destination root
#: (``$HOME``, or ``GTHEME_DEST_ROOT`` under test) — see ``core.paths.dest_root``.
CUSTOM_DEST = "~/.local/share/backgrounds/gtheme/"

#: Where the entries naming those copies are written. This is the ordinary
#: desktop-wide catalogue directory rather than somewhere private to gtheme, and
#: on purpose: a picture somebody chose is theirs, so it belongs where every
#: picker on the machine — this one, and GNOME's own — will find it again.
CUSTOM_CATALOGUE = "~/.local/share/gnome-background-properties/gtheme.xml"

#: What a picture with nothing readable in its file name is called.
UNNAMED_PICTURE = "Your own picture"

#: What the caption under a slideshow tile adds, for a reader who cannot see
#: the badge in the corner of it.
SLIDESHOW_SUFFIX = "changes during the day"

#: Catalogue files carry a DOCTYPE line pointing at a DTD that is installed
#: nowhere; the scanner strips it before parsing and so does the reader here,
#: for the same reason — an XML parser told to fetch it would try.
_DOCTYPE = re.compile(r"<!DOCTYPE[^>]*>")

#: What a slideshow tile says, verbatim from the brief.
_SLIDESHOW_LABEL = "Changes during the day"

#: How big one tile in a picture grid is, 16:9 like the screen it stands for.
#:
#: A *fixed* size rather than a floor, and the reason is the single most
#: surprising thing on this page. ``Gtk.Picture`` can shrink, so its minimum
#: size is zero; ``Gtk.AspectFrame`` passes that straight through; and a
#: ``GtkViewport`` — which is what every scrolled preferences page puts around
#: its content — allocates its child the child's *minimum* height in the
#: direction it scrolls, not its natural one. Zero minimum plus a scroller is a
#: grid of 6px slivers, which is what this page photographed as: two bands of
#: empty grey where the wallpapers should be. So the tile states its size, and
#: :class:`GridTile` stops the thumbnail's own resolution from arguing with it.
TILE_WIDTH = 160
TILE_HEIGHT = 90

_STYLE_KEYS = ("picture-options", "primary-color", "secondary-color", "color-shading-type")


# --------------------------------------------------------------------------
# small pure helpers — safe to unit test with no display
# --------------------------------------------------------------------------


def _unquote(variant_text: str | None) -> str | None:
    """:func:`~gtheme.core.gvariant.unquote`, passing None straight through."""
    if variant_text is None:
        return None
    return unquote(variant_text)


def tile_source(entry: WallpaperEntry, *, dark: bool) -> tuple[Path, Path, bool]:
    """What one catalogue entry means for one grid.

    Args:
        entry: the catalogue entry.
        dark: which grid this is for.

    Returns:
        ``(value, thumbnail_source, is_slideshow)``. ``value`` is the exact
        path written to the setting when the tile is chosen. ``thumbnail_source``
        is what to render — the entry itself, or its slideshow's first static
        frame when ``value`` names a slideshow XML rather than a picture.
    """
    value = entry.filename_dark if (dark and entry.filename_dark is not None) else entry.filename
    if value.suffix.lower() != ".xml":
        return value, value, False
    _start, events = parse_slideshow(value)
    first_static = next((event for event in events if isinstance(event, SlideshowEvent)), None)
    return value, (first_static.file if first_static is not None else value), True


def custom_filename(source: Path) -> str:
    """A filesystem-safe name for a copied custom picture. Collision-proof."""
    suffix = source.suffix.lower()
    if not (1 < len(suffix) <= 6 and suffix[1:].isalnum()):
        suffix = ""
    return f"custom-{uuid.uuid4().hex[:12]}{suffix}"


def readable_name(source: Path) -> str:
    """What to call a picture somebody chose, from the name they chose it by.

    ``holiday_beach-2024.JPG`` is "Holiday beach 2024". The copy on disk keeps
    its collision-proof ``custom-<random>.jpg`` name — two people's
    ``photo.jpg`` must not become one file — but nobody should ever have to
    read that (persona-report §3.2).
    """
    words = " ".join(source.stem.replace("_", " ").replace("-", " ").split())
    if not words:
        return UNNAMED_PICTURE
    trimmed = words[:48].strip()
    return trimmed[0].upper() + trimmed[1:]


def tile_name(name: str, *, is_slideshow: bool) -> str:
    """What one tile is called out loud, badge and all.

    The slideshow badge is a picture of a sentence: it says "Changes during the
    day" in the corner of the thumbnail, where a screen reader cannot reach it.
    So the name a screen reader announces carries the same fact in words.
    """
    return f"{name} — {SLIDESHOW_SUFFIX}" if is_slideshow else name


def custom_catalogue_path() -> Path:
    """Where gtheme writes catalogue entries for pictures somebody chose."""
    return confine_dest(CUSTOM_CATALOGUE)


def catalogue_entry_xml(name: str, filename: Path) -> ElementTree.Element:
    """One ``<wallpaper>`` element, in the shape the scanner reads back.

    Built with :mod:`xml.etree` rather than by pasting strings together: a file
    name is somebody else's text and can hold ``&`` or ``<`` — and this file is
    read by every wallpaper picker on the machine, not only by gtheme.
    """
    element = ElementTree.Element("wallpaper", {"deleted": "false"})
    ElementTree.SubElement(element, "name").text = name
    ElementTree.SubElement(element, "filename").text = str(filename)
    ElementTree.SubElement(element, "options").text = "zoom"
    ElementTree.SubElement(element, "shade_type").text = "solid"
    ElementTree.SubElement(element, "pcolor").text = "#000000"
    ElementTree.SubElement(element, "scolor").text = "#000000"
    return element


def _existing_catalogue(path: Path) -> ElementTree.Element:
    """The catalogue as it stands, or an empty one.

    A file that will not parse is replaced rather than repaired. It is gtheme's
    own file, the alternative is refusing to remember the picture somebody just
    chose, and the pictures it named are still on disk to be chosen again.
    """
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ElementTree.Element("wallpapers")
    try:
        root = ElementTree.fromstring(_DOCTYPE.sub("", raw, count=1))
    except ElementTree.ParseError:
        return ElementTree.Element("wallpapers")
    return root if root.tag == "wallpapers" else ElementTree.Element("wallpapers")


def _unused_name(root: ElementTree.Element, wanted: str) -> str:
    """``Holiday``, or ``Holiday (2)`` when a Holiday is already listed."""
    taken = {(el.text or "").strip() for el in root.iterfind("wallpaper/name")}
    if wanted not in taken:
        return wanted
    for number in range(2, 1000):
        candidate = f"{wanted} ({number})"
        if candidate not in taken:
            return candidate
    return wanted


def record_in_catalogue(name: str, filename: Path) -> str:
    """Add a picture to the catalogue under a readable name. Returns the name.

    Raises:
        OSError: the catalogue could not be written.
        ConfinementError: the catalogue is not where it is supposed to be.
    """
    path = custom_catalogue_path()
    root = _existing_catalogue(path)
    unique = _unused_name(root, name)
    root.append(catalogue_entry_xml(unique, filename))
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(
        path,
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        + ElementTree.tostring(root, encoding="utf-8"),
    )
    return unique


def _search_text(row: Row) -> str:
    return " ".join([row.title, row.subtitle, *row.synonyms])


def _load_domain_rows(directory: Path | str | None = None) -> dict[str, Row]:
    """This page's rows from ``data/domains/wallpaper.toml``, by key."""
    corpus = load_corpus(directory)
    domain: DomainDescriptor | None = next(
        (d for d in corpus.domains if d.id == "wallpaper"), None
    )
    return {row.key: row for row in domain.rows} if domain is not None else {}


# --------------------------------------------------------------------------
# the picker grids
# --------------------------------------------------------------------------


def _load_tile_image(picture: Gtk.Picture, source: Path) -> None:
    """Fill one tile's picture, cache-first, generating off-thread on a miss.

    Any failure — the file is not on this machine, the factory declines it,
    generation fails — just leaves the tile with no image rather than raising;
    a missing thumbnail is a cosmetic problem, not a reason to break the grid.
    """
    try:
        cached = lookup_cached_thumbnail(source)
    except OSError:
        cached = None
    if cached is not None:
        _set_picture(picture, cached)
        return

    def on_ready(path: Path | None, _error: Exception | None) -> None:
        if path is not None:
            _set_picture(picture, path)

    try:
        request_thumbnail_async(source, on_ready)
    except OSError:
        pass


def _set_picture(picture: Gtk.Picture, path: Path) -> None:
    try:
        texture = Gdk.Texture.new_from_filename(str(path))
    except GLib.Error:
        return
    picture.set_paintable(texture)


class GridTile(Gtk.Widget):
    """One picture in a grid: exactly :data:`TILE_WIDTH` wide, never more.

    A thumbnail is 256px across whatever the picture behind it is, and
    ``Gtk.Picture`` asks for the size of what it holds. Left alone, a row of
    them tells the FlowBox each tile naturally wants 456px, which is how a grid
    of twenty-three wallpapers decides it can fit one and a half of them across
    a preferences page. Capping the request is what makes the grid a grid; the
    tile still fills whatever column it is given, so nothing floats in the
    middle of empty space.
    """

    __gtype_name__ = "GthemeWallpaperGridTile"

    def __init__(self, child: Gtk.Widget) -> None:
        super().__init__(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self._child: Gtk.Widget | None = child
        child.set_parent(self)

    def do_measure(  # noqa: D102 - GTK vfunc
        self, orientation: Gtk.Orientation, for_size: int
    ) -> tuple[int, int, int, int]:
        if self._child is None:
            return 0, 0, -1, -1
        minimum, natural, min_baseline, nat_baseline = self._child.measure(
            orientation, for_size
        )
        limit = TILE_WIDTH if orientation == Gtk.Orientation.HORIZONTAL else TILE_HEIGHT
        return minimum, max(minimum, min(natural, limit)), min_baseline, nat_baseline

    def do_size_allocate(self, width: int, height: int, baseline: int) -> None:  # noqa: D102
        if self._child is not None:
            self._child.allocate(width, height, baseline, None)

    def do_dispose(self) -> None:  # noqa: D102 - GTK vfunc
        if self._child is not None:
            self._child.unparent()
            self._child = None
        Gtk.Widget.do_dispose(self)


def _make_tile(name: str, value: Path, thumb_source: Path, *, is_slideshow: bool) -> Gtk.FlowBoxChild:
    """One picture in a grid: the thumbnail, its name under it, and both said.

    Three things carry the name, because three different people need it. The
    caption is visible, so nobody has to hover to find out which picture this
    is — the Icons page has always done that and this grid did not
    (persona-report §2.10). The picture itself gets ``alternative-text``, which
    is what a screen reader falls back to. And the tile gets an accessible name,
    because the tooltip it used to rely on is a *description*: read after the
    name, and often not at all, so a tile whose only text was a tooltip was
    announced as nothing.
    """
    spoken = tile_name(name, is_slideshow=is_slideshow)
    picture = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, alternative_text=spoken)
    frame = Gtk.AspectFrame(ratio=16 / 9, obey_child=False, child=Gtk.GraphicsOffload(child=picture))
    frame.set_size_request(TILE_WIDTH, TILE_HEIGHT)
    overlay = Gtk.Overlay(child=frame)
    if is_slideshow:
        badge = Gtk.Label(
            label=_SLIDESHOW_LABEL,
            css_classes=["caption", "osd"],
            halign=Gtk.Align.END,
            valign=Gtk.Align.END,
            margin_end=6,
            margin_bottom=6,
        )
        overlay.add_overlay(badge)
    caption = Gtk.Label(
        label=name,
        css_classes=["caption"],
        ellipsize=Pango.EllipsizeMode.END,
        max_width_chars=18,
        margin_top=4,
    )
    # The caption repeats what the tile is already called out loud; announcing
    # it a second time after the name is noise.
    a11y.hide_from_screen_readers(caption)
    content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0, halign=Gtk.Align.CENTER)
    content.append(GridTile(overlay))
    content.append(caption)
    child = Gtk.FlowBoxChild(child=content, tooltip_text=name)
    a11y.name(child, spoken)
    child.wallpaper_value = value.as_uri()  # type: ignore[attr-defined]
    _load_tile_image(picture, thumb_source)
    return child


def _build_picture_group(
    window: Any,
    backend: SettingsBackend,
    row: Row,
    catalogue: list[WallpaperEntry],
    *,
    dark: bool,
) -> Adw.PreferencesGroup:
    group = Adw.PreferencesGroup(title=row.title, description=row.subtitle)

    flow = Gtk.FlowBox(
        valign=Gtk.Align.START,
        homogeneous=True,
        max_children_per_line=6,
        min_children_per_line=2,
        selection_mode=Gtk.SelectionMode.SINGLE,
        row_spacing=12,
        column_spacing=12,
        margin_top=6,
        margin_bottom=6,
    )

    tiles: list[Gtk.FlowBoxChild] = []
    seen_values: set[str] = set()

    def add_tile(entry: WallpaperEntry) -> Gtk.FlowBoxChild | None:
        value, thumb_source, is_slideshow = tile_source(entry, dark=dark)
        uri = value.as_uri()
        if uri in seen_values:
            return None  # the same picture offered by more than one catalogue file
        seen_values.add(uri)
        tile = _make_tile(entry.name, value, thumb_source, is_slideshow=is_slideshow)
        tiles.append(tile)
        flow.append(tile)
        return tile

    for entry in catalogue:
        add_tile(entry)

    # The same callable the "choose a picture" row hands to the installer,
    # published on the grid so a test can drive the real one rather than a
    # stand-in that only looks like it.
    flow.gtheme_add_tile = add_tile  # type: ignore[attr-defined]

    def refresh() -> None:
        try:
            current = _unquote(backend.get(key_for(row)))
        except BackendError:
            current = None
        for tile in tiles:
            if getattr(tile, "wallpaper_value", None) == current:
                flow.select_child(tile)
                return
        flow.unselect_all()

    def on_child_activated(_flow: Gtk.FlowBox, tile: Gtk.FlowBoxChild) -> None:
        value = getattr(tile, "wallpaper_value", None)
        if value is None:
            return
        try:
            recording(backend, component=row.id).set(
                key_for(row), quote(value)
            )
        except (BackendError, WriteRefused) as exc:
            # Back to whichever picture is really on the desktop, and a sentence
            # saying why this one is not (review-report M7).
            refresh()
            window.toast(NOT_CHANGED.format(why=reason_for(exc)))
            return
        refresh()

    flow.connect("child-activated", on_child_activated)
    group.add(flow)

    custom_row = Adw.ButtonRow(
        title="Choose a picture from your computer…",
        start_icon_name="folder-pictures-symbolic",
    )
    # ``add_tile`` puts the chosen picture in the grid straight away and
    # ``refresh`` then selects it, so the tile appears under the reader's
    # cursor instead of only after the next launch. Rebuilding the page would
    # do the same and would throw away their scroll position.
    custom_row.connect(
        "activated",
        lambda *_a: _choose_custom_file(window, backend, row, refresh, on_added=add_tile),
    )
    group.add(custom_row)

    refresh()
    window.rows.register("wallpaper", row.id, flow, refresh=refresh, search_text=_search_text(row))
    return group


def custom_file_filters() -> Gio.ListStore:
    """What the "choose a picture" dialog will let somebody pick.

    Pictures, and slideshows. The second one was missing and mattered more than
    it sounds: a slideshow is a small file listing pictures and the times of day
    to show them, three of the six Looks gtheme ships set one, and the picker
    offered ``add_pixbuf_formats()`` only — so the kind of background this app
    hands out was the one kind it would not accept back (persona-report §3.2).
    """
    pictures_and_slideshows = Gtk.FileFilter(name="Pictures and slideshows")
    pictures_and_slideshows.add_pixbuf_formats()
    pictures_and_slideshows.add_suffix("xml")
    slideshows = Gtk.FileFilter(name="Slideshows")
    slideshows.add_suffix("xml")
    filters = Gio.ListStore.new(Gtk.FileFilter)
    filters.append(pictures_and_slideshows)
    filters.append(slideshows)
    return filters


def _choose_custom_file(
    window: Any,
    backend: SettingsBackend,
    row: Row,
    on_done: Any,
    *,
    on_added: Any = None,
) -> None:
    dialog = Gtk.FileDialog(title="Choose a picture")
    filters = custom_file_filters()
    dialog.set_filters(filters)
    dialog.set_default_filter(filters.get_item(0))

    def on_response(dlg: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            gfile = dlg.open_finish(result)
        except GLib.Error:
            return  # cancelled, or the platform's own dialog already explained itself
        path = gfile.get_path() if gfile is not None else None
        if path:
            _install_custom_wallpaper(
                window, backend, row, Path(path), on_done, on_added=on_added
            )

    dialog.open(window, None, on_response)


def _first_frame(slideshow: Path) -> Path | None:
    """The first still picture a slideshow shows, or None if it has none."""
    _start, events = parse_slideshow(slideshow)
    first = next((event for event in events if isinstance(event, SlideshowEvent)), None)
    return first.file if first is not None else None


def _readable_picture(candidate: Path) -> bool:
    """Whether this really is a picture something can draw."""
    try:
        Gdk.Texture.new_from_filename(str(candidate))
    except GLib.Error:
        return False
    return True


def _install_custom_wallpaper(
    window: Any,
    backend: SettingsBackend,
    row: Row,
    source: Path,
    on_done: Any,
    *,
    on_added: Any = None,
) -> None:
    """Copy ``source`` in, prove it works, name it, then write the setting.

    GSettings will happily store a path to nothing, or to a file that is not
    a picture at all — nothing about writing the key fails. So the order here
    is deliberate: copy, decode, *then* write, and undo the copy the moment
    any step short of the last one goes wrong.

    A slideshow is proved a different way, because it is not a picture: it is
    read, and the first still frame it names has to be a picture that is really
    there. A slideshow whose pictures have been moved away would otherwise be
    accepted and leave somebody with a blank desktop and nothing to read.

    Args:
        on_added: given the catalogue entry for the picture, so the grid it was
            chosen from can show it immediately. The entry is written to the
            catalogue either way, so it is in the grid on the next launch even
            when nobody is listening here.
    """
    try:
        data = source.read_bytes()
    except OSError as exc:
        window.toast(f"That file couldn't be read: {exc.strerror or exc}")
        return

    try:
        dest = confine_dest(CUSTOM_DEST + custom_filename(source))
    except ConfinementError as exc:
        window.toast(str(exc))
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        atomic_write_bytes(dest, data)
    except OSError as exc:
        window.toast(f"That picture couldn't be saved: {exc.strerror or exc}")
        return

    if not dest.is_file():
        window.toast("That picture couldn't be saved.")
        return

    is_slideshow = dest.suffix.lower() == ".xml"
    if is_slideshow:
        frame = _first_frame(dest)
        if frame is None or not frame.is_file() or not _readable_picture(frame):
            dest.unlink(missing_ok=True)
            window.toast(
                "That file lists pictures to show through the day, but gtheme "
                "could not find the pictures themselves."
            )
            return
    elif not _readable_picture(dest):
        dest.unlink(missing_ok=True)
        window.toast("That file doesn't look like a picture gtheme can use.")
        return

    try:
        recording(backend, component=row.id).set(
            key_for(row), quote(dest.as_uri())
        )
    except (BackendError, WriteRefused) as exc:
        window.toast(NOT_CHANGED.format(why=reason_for(exc)))
        return

    # Naming it comes last, and its failure is not the reader's problem: the
    # picture is already on their desktop. All a failure here costs is the tile,
    # so it is said in the same sentence rather than as an alarm.
    named: str | None = None
    try:
        named = record_in_catalogue(readable_name(source), dest)
    except (OSError, ConfinementError):
        named = None

    if named is not None and on_added is not None:
        on_added(
            WallpaperEntry(
                name=named,
                filename=dest,
                filename_dark=None,
                options="zoom",
                shade_type="solid",
                primary_color=None,
                secondary_color=None,
                source_xml=custom_catalogue_path(),
            )
        )
    on_done()
    window.toast(
        f"Background picture updated. It is in the list above now, as “{named}”."
        if named is not None
        else "Background picture updated, but gtheme could not add it to the list above."
    )


# --------------------------------------------------------------------------
# the style rows and the lock-screen note
# --------------------------------------------------------------------------


def _add_data_row(
    window: Any, backend: SettingsBackend, probe: SchemaProbe, row: Row
) -> Adw.PreferencesRow:
    widget, refresh = panel_widgets.build_row(backend, row, probe=probe)
    window.rows.register("wallpaper", row.id, widget, refresh=refresh, search_text=_search_text(row))
    return widget


def _build_style_group(
    window: Any, backend: SettingsBackend, probe: SchemaProbe, rows: list[Row]
) -> Adw.PreferencesGroup:
    group = Adw.PreferencesGroup(
        title="How your picture looks",
        description="How it fills the screen, and the colour behind it.",
    )
    advanced = [row for row in rows if row.advanced]
    for row in rows:
        if row.advanced:
            continue
        group.add(_add_data_row(window, backend, probe, row))
    if advanced:
        # The tier is called the same thing on every page (review-report M29);
        # what is *inside* it is this page's own sentence, because here it is
        # one specific thing rather than "settings most people never change".
        expander = Adw.ExpanderRow()
        set_plain_text(
            expander,
            title=ADVANCED_TITLE,
            subtitle="A second colour, for a fade instead of one flat colour.",
        )
        for row in advanced:
            expander.add_row(_add_data_row(window, backend, probe, row))
        group.add(expander)
    return group


def _build_lock_screen_group() -> Adw.PreferencesGroup:
    group = Adw.PreferencesGroup(title="Lock screen picture")
    row = Adw.ActionRow(
        title="Always follows your light background picture",
        subtitle=(
            "There's no separate lock screen picture to choose, and no dark version of "
            "it — this is how your version of GNOME works, not something gtheme is "
            "leaving out."
        ),
    )
    row.add_prefix(Gtk.Image(icon_name="dialog-information-symbolic", valign=Gtk.Align.CENTER))
    group.add(row)
    return group


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def build(window: Any) -> Gtk.Widget:
    """Build the Wallpaper page. See ``ui.registry`` for the factory contract."""
    backend = get_backend()
    probe = get_probe(window)
    rows_by_key = _load_domain_rows()
    catalogue = scan_wallpaper_catalogue(default_wallpaper_catalogue_roots())

    page = Adw.PreferencesPage()

    for key, dark in (("picture-uri", False), ("picture-uri-dark", True)):
        row = rows_by_key.get(key)
        if row is not None:
            page.add(_build_picture_group(window, backend, row, catalogue, dark=dark))

    style_rows = [rows_by_key[key] for key in _STYLE_KEYS if key in rows_by_key]
    if style_rows:
        page.add(_build_style_group(window, backend, probe, style_rows))

    page.add(_build_lock_screen_group())

    return page
