"""The mock desktop card — what a Look looks like when there is no photo of it.

A Look is chosen by seeing it (competitor-ux P1: *a change the user cannot see
first is a bug*), and the honest way to show one is a real screenshot. Every
published Look must ship one — that is the publish rule, and the Looks page
enforces it for the community list.

But two kinds of Look legitimately have no picture. A Look the user just saved
from their own desktop has never been photographed, because gtheme cannot take
a screenshot of the session it is running inside. And a community entry, until
its picture has been downloaded, has only its words. Showing a grey box for
either one is the failure mode this module exists to avoid: an empty tile reads
as "broken", and a person who thinks a tile is broken does not click it.

So instead of a grey box, a Look draws itself from what it *does* have — its
palette. :class:`PreviewCard` paints a tiny abstract desktop in those colours:
the bar across the top, one window, and the palette itself as a row of dots.
It is not a promise about what the desktop will look like, and it is not
pretending to be a photo — it is the colours, arranged the way a desktop is
arranged, which is exactly as much as a palette can honestly claim.

The drawing is a plain function, :func:`paint_preview`, so that it can be
executed by a test against a bare :class:`Gtk.Snapshot` with no window, no
allocation and nothing on screen.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gdk, GLib, Graphene, Gsk, Gtk  # noqa: E402

__all__ = [
    "ASPECT_RATIO",
    "PreviewColors",
    "PreviewCard",
    "build_preview",
    "colors_from_palette",
    "load_texture",
    "paint_preview",
]

#: Every preview is the shape of a screen. Fixed, so a grid of tiles is a grid
#: rather than a ransom note.
ASPECT_RATIO = 16 / 9


def _rgba(spec: str, alpha: float = 1.0) -> Gdk.RGBA:
    colour = Gdk.RGBA()
    if not colour.parse(spec):
        colour.parse("#808080")
    colour.alpha = alpha
    return colour


def _is_colour(value: object) -> bool:
    return isinstance(value, str) and bool(Gdk.RGBA().parse(value))


#: Palette names that mean each role, best first. Looks are written by people,
#: and people call the darkest colour "bg", "void", "base" or "background"
#: depending on the day; guessing from the names they actually used beats
#: demanding one vocabulary from every Look author.
_ROLE_NAMES: dict[str, tuple[str, ...]] = {
    "background": ("bg", "background", "base", "void", "bg0", "surface0", "black"),
    "surface": ("surface", "surface1", "surface2", "panel", "moss", "bg1", "mantle"),
    "accent": ("accent", "primary", "highlight", "jade", "accent_bright", "cyan"),
    "text": ("fg", "foreground", "text", "bone", "fg_bright", "white"),
}

#: What a Look with no palette at all is drawn in. Deliberately neutral: it
#: says "no colours were declared", not "this Look is grey".
_FALLBACK = ("#242424", "#3a3a3a", "#3584e4", "#f6f5f4")


@dataclass(frozen=True)
class PreviewColors:
    """The four colours the mock desktop is drawn from, plus the palette row.

    Attributes:
        background: behind everything.
        surface: the bar at the top and the window.
        accent: the one colour the Look is *about*.
        text: what writing is drawn in.
        dots: up to five palette colours, shown as a row. Accent first.
    """

    background: str
    surface: str
    accent: str
    text: str
    dots: tuple[str, ...] = ()

    @classmethod
    def fallback(cls) -> PreviewColors:
        background, surface, accent, text = _FALLBACK
        return cls(background=background, surface=surface, accent=accent, text=text, dots=())


def colors_from_palette(palette: Mapping[str, str] | None) -> PreviewColors:
    """Pick the four roles out of a Look's palette.

    Anything that is not a colour is ignored rather than refused: a palette is
    author-written data, and one stray line in it must not cost the whole tile
    its picture.
    """
    usable = {
        name.lower(): value
        for name, value in (palette or {}).items()
        if _is_colour(value)
    }
    if not usable:
        return PreviewColors.fallback()

    ordered = list(usable.values())
    chosen: dict[str, str] = {}
    for role, names in _ROLE_NAMES.items():
        for name in names:
            if name in usable:
                chosen[role] = usable[name]
                break

    defaults = dict(
        zip(("background", "surface", "accent", "text"), _FALLBACK, strict=True)
    )
    for index, role in enumerate(("background", "surface", "accent", "text")):
        chosen.setdefault(role, ordered[index] if index < len(ordered) else defaults[role])

    dots: list[str] = [chosen["accent"]]
    for value in ordered:
        if len(dots) >= 5:
            break
        if value not in dots and value != chosen["background"]:
            dots.append(value)

    return PreviewColors(
        background=chosen["background"],
        surface=chosen["surface"],
        accent=chosen["accent"],
        text=chosen["text"],
        dots=tuple(dots),
    )


def load_texture(picture: str | Path | None) -> Gdk.Texture | None:
    """Load an image for a tile, or None when it cannot be shown.

    Never raises. A Look that names a picture it does not ship, or ships one in
    a form this machine cannot decode, falls back to the painted card — which
    is a worse preview but a working tile.
    """
    if picture is None:
        return None
    location = Path(picture)
    if not location.is_file():
        return None
    try:
        return Gdk.Texture.new_from_filename(str(location))
    except GLib.Error:
        return None


def _cover(texture: Gdk.Texture, width: float, height: float) -> Graphene.Rect:
    """Where to draw a texture so it fills the card without distorting it."""
    source_w = max(texture.get_width(), 1)
    source_h = max(texture.get_height(), 1)
    scale = max(width / source_w, height / source_h)
    drawn_w = source_w * scale
    drawn_h = source_h * scale
    return Graphene.Rect().init((width - drawn_w) / 2, (height - drawn_h) / 2, drawn_w, drawn_h)


def _rounded(rect: Graphene.Rect, radius: float) -> Gsk.RoundedRect:
    rounded = Gsk.RoundedRect()
    rounded.init_from_rect(rect, radius)
    return rounded


def paint_preview(
    snapshot: Gtk.Snapshot,
    colors: PreviewColors,
    width: float,
    height: float,
    *,
    texture: Gdk.Texture | None = None,
) -> None:
    """Draw the mock desktop into ``snapshot``.

    A free function on purpose: the widget below is three lines of glue around
    it, and a test can call this with a bare snapshot, which is the only way to
    exercise drawing code without putting a window on the developer's screen.
    """
    if width <= 0 or height <= 0:
        return

    whole = Graphene.Rect().init(0, 0, width, height)
    snapshot.append_color(_rgba(colors.background), whole)

    if texture is not None:
        snapshot.push_clip(whole)
        snapshot.append_texture(texture, _cover(texture, width, height))
        snapshot.pop()

    # The bar across the top. Translucent over the background, the way the real
    # one is, so a wallpaper behind it still reads as a wallpaper.
    bar_height = max(height * 0.09, 3.0)
    snapshot.append_color(
        _rgba(colors.surface, 0.92), Graphene.Rect().init(0, 0, width, bar_height)
    )
    dot = bar_height * 0.34
    snapshot.append_color(
        _rgba(colors.accent),
        Graphene.Rect().init(width - dot * 3, (bar_height - dot) / 2, dot, dot),
    )
    snapshot.append_color(
        _rgba(colors.text, 0.55),
        Graphene.Rect().init(width * 0.44, (bar_height - dot) / 2, width * 0.12, dot),
    )

    # One window, roughly where a window sits.
    window = Graphene.Rect().init(width * 0.17, height * 0.28, width * 0.62, height * 0.52)
    radius = min(width, height) * 0.05
    snapshot.push_rounded_clip(_rounded(window, radius))
    snapshot.append_color(_rgba(colors.surface), window)
    header = Graphene.Rect().init(
        window.get_x(), window.get_y(), window.get_width(), height * 0.11
    )
    snapshot.append_color(_rgba(colors.text, 0.10), header)
    snapshot.append_color(
        _rgba(colors.accent),
        Graphene.Rect().init(
            window.get_x() + window.get_width() * 0.06,
            window.get_y() + height * 0.14,
            window.get_width() * 0.30,
            height * 0.05,
        ),
    )
    for line in range(2):
        snapshot.append_color(
            _rgba(colors.text, 0.35),
            Graphene.Rect().init(
                window.get_x() + window.get_width() * 0.06,
                window.get_y() + height * (0.24 + 0.10 * line),
                window.get_width() * (0.72 if line == 0 else 0.50),
                height * 0.035,
            ),
        )
    snapshot.pop()

    # The palette itself, as a row of dots along the bottom. This is the part
    # that is literally true: these are the Look's colours.
    if colors.dots:
        size = min(height * 0.09, width * 0.05)
        gap = size * 0.55
        y = height - size - height * 0.06
        x = width * 0.17
        for value in colors.dots:
            snapshot.push_rounded_clip(
                _rounded(Graphene.Rect().init(x, y, size, size), size / 2)
            )
            snapshot.append_color(_rgba(value), Graphene.Rect().init(x, y, size, size))
            snapshot.pop()
            x += size + gap


class PreviewCard(Gtk.Widget):
    """A widget that draws :func:`paint_preview` at whatever size it is given."""

    __gtype_name__ = "GthemePreviewCard"

    def __init__(
        self,
        colors: PreviewColors | None = None,
        *,
        texture: Gdk.Texture | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._colors = colors or PreviewColors.fallback()
        self._texture = texture

    @property
    def colors(self) -> PreviewColors:
        return self._colors

    def set_colors(self, colors: PreviewColors) -> None:
        self._colors = colors
        self.queue_draw()

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:  # noqa: D102 - GTK vfunc
        paint_preview(
            snapshot,
            self._colors,
            float(self.get_width()),
            float(self.get_height()),
            texture=self._texture,
        )


def build_preview(
    *,
    palette: Mapping[str, str] | None = None,
    picture: str | Path | None = None,
    pictures: Sequence[str | Path] | None = None,
    width: int = 320,
) -> Gtk.Widget:
    """The picture for one tile: a real screenshot if there is one, else the card.

    Args:
        palette: the Look's colours, used when there is no picture.
        picture: a screenshot to show instead.
        pictures: several candidates; the first that loads wins. Looks list
            their screenshots in preference order.
        width: how wide the tile should ask to be. Height follows from
            :data:`ASPECT_RATIO`.

    Returns:
        A widget of fixed shape, ready to drop into a grid.
    """
    candidates = [picture, *(pictures or [])]
    texture = next((found for found in map(load_texture, candidates) if found is not None), None)

    child: Gtk.Widget
    if texture is not None:
        child = Gtk.Picture(paintable=texture, content_fit=Gtk.ContentFit.COVER)
    else:
        child = PreviewCard(colors_from_palette(palette))

    frame = Gtk.AspectFrame(ratio=ASPECT_RATIO, obey_child=False, child=child)
    frame.set_size_request(width, int(width / ASPECT_RATIO))
    frame.set_overflow(Gtk.Overflow.HIDDEN)
    frame.add_css_class("card")
    return frame
