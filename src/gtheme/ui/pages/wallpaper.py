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
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gio", "2.0")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

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
from ...ui.widgets.rows import key_for  # noqa: E402
from ._style_common import get_probe  # noqa: E402

__all__ = ["TILE_HEIGHT", "TILE_WIDTH", "GridTile", "build"]

#: Where a custom picture is copied to, relative to the destination root
#: (``$HOME``, or ``GTHEME_DEST_ROOT`` under test) — see ``core.paths.dest_root``.
CUSTOM_DEST = "~/.local/share/backgrounds/gtheme/"

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
    """Strip GVariant string quoting. ``"'x'"`` -> ``x``, ``None`` -> ``None``."""
    if variant_text is None:
        return None
    text = variant_text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        return text[1:-1]
    return text


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
    picture = Gtk.Picture(content_fit=Gtk.ContentFit.COVER)
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
    child = Gtk.FlowBoxChild(child=GridTile(overlay), tooltip_text=name)
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
    for entry in catalogue:
        value, thumb_source, is_slideshow = tile_source(entry, dark=dark)
        uri = value.as_uri()
        if uri in seen_values:
            continue  # the same picture offered by more than one catalogue file
        seen_values.add(uri)
        tile = _make_tile(entry.name, value, thumb_source, is_slideshow=is_slideshow)
        tiles.append(tile)
        flow.append(tile)

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
                key_for(row), GLib.Variant("s", value).print_(True)
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
    custom_row.connect("activated", lambda *_a: _choose_custom_file(window, backend, row, refresh))
    group.add(custom_row)

    refresh()
    window.rows.register("wallpaper", row.id, flow, refresh=refresh, search_text=_search_text(row))
    return group


def _choose_custom_file(window: Any, backend: SettingsBackend, row: Row, on_done: Any) -> None:
    dialog = Gtk.FileDialog(title="Choose a picture")
    picture_filter = Gtk.FileFilter(name="Pictures")
    picture_filter.add_pixbuf_formats()
    filters = Gio.ListStore.new(Gtk.FileFilter)
    filters.append(picture_filter)
    dialog.set_filters(filters)
    dialog.set_default_filter(picture_filter)

    def on_response(dlg: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            gfile = dlg.open_finish(result)
        except GLib.Error:
            return  # cancelled, or the platform's own dialog already explained itself
        path = gfile.get_path() if gfile is not None else None
        if path:
            _install_custom_wallpaper(window, backend, row, Path(path), on_done)

    dialog.open(window, None, on_response)


def _install_custom_wallpaper(
    window: Any, backend: SettingsBackend, row: Row, source: Path, on_done: Any
) -> None:
    """Copy ``source`` in, prove it is a real picture, then write the setting.

    GSettings will happily store a path to nothing, or to a file that is not
    a picture at all — nothing about writing the key fails. So the order here
    is deliberate: copy, decode, *then* write, and undo the copy the moment
    any step short of the last one goes wrong.
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

    try:
        Gdk.Texture.new_from_filename(str(dest))
    except GLib.Error:
        dest.unlink(missing_ok=True)
        window.toast("That file doesn't look like a picture gtheme can use.")
        return

    try:
        recording(backend, component=row.id).set(
            key_for(row), GLib.Variant("s", dest.as_uri()).print_(True)
        )
    except (BackendError, WriteRefused) as exc:
        window.toast(NOT_CHANGED.format(why=reason_for(exc)))
        return

    on_done()
    window.toast("Background picture updated.")


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
        expander = Adw.ExpanderRow(
            title="More options",
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
