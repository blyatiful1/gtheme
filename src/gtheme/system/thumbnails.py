"""Wallpaper thumbnails: cache lookup first, off-thread generation second.

The wallpaper grid has to render 20+ images, and GNOME 50's stock wallpapers
are 4096×4096 JPEG-XL (research/adwaita-playbook.md §7) — decoding one on the
main thread measured well over a hundred milliseconds, which is a stall a
user feels. The shape this module follows (§7b of the playbook):

1. :func:`lookup_cached_thumbnail` first — ``DesktopThumbnailFactory.lookup()``
   is a cache-hit path, effectively free, and covers every stock wallpaper
   after the first run.
2. On a miss, :func:`request_thumbnail_async` generates on a worker thread and
   hops back to the main loop with ``GLib.idle_add`` — never blocking the UI
   — then calls ``on_ready`` exactly once, on the main thread. The idle
   callback returns ``GLib.SOURCE_REMOVE`` so it never re-runs.

**Never use glycin's ``set_scale`` for this.** It is a verified no-op in
glycin 2.1.5 — asking for a 96×96 frame returns the image at its native
resolution regardless, silently. Nothing in this module touches glycin.

Every ``gi`` import lives inside the functions that need one, so importing
this module costs nothing without a display; :func:`guess_content_type` and
:func:`thumbnail_uri_for_path` need no ``gi`` at all and are safe to call from
plain unit tests. Everything else here is exercised under the ``gtk`` marker.
"""

from __future__ import annotations

import mimetypes
import threading
from collections.abc import Callable
from pathlib import Path

__all__ = [
    "ThumbnailError",
    "generate_thumbnail_sync",
    "guess_content_type",
    "lookup_cached_thumbnail",
    "request_thumbnail_async",
    "thumbnail_uri_for_path",
]

_SIZE_NAMES = ("normal", "large", "x-large", "xx-large")


class ThumbnailError(Exception):
    """The factory could not produce a thumbnail for a path."""


def thumbnail_uri_for_path(path: Path) -> str:
    """The ``file://`` URI a thumbnail is cached under. Keyed by URI, per the API."""
    return path.resolve().as_uri()


def guess_content_type(path: Path) -> str:
    """Best-effort MIME type, with the one stock-wallpaper case ``mimetypes`` misses."""
    guess, _ = mimetypes.guess_type(str(path))
    if guess:
        return guess
    if path.suffix.lower() == ".jxl":
        return "image/jxl"
    return "application/octet-stream"


def _thumbnail_size(name: str):
    import gi

    gi.require_version("GnomeDesktop", "4.0")
    from gi.repository import GnomeDesktop

    mapping = {
        "normal": GnomeDesktop.DesktopThumbnailSize.NORMAL,
        "large": GnomeDesktop.DesktopThumbnailSize.LARGE,
        "x-large": GnomeDesktop.DesktopThumbnailSize.XLARGE,
        "xx-large": GnomeDesktop.DesktopThumbnailSize.XXLARGE,
    }
    if name not in mapping:
        raise ValueError(f"unknown thumbnail size {name!r}, expected one of {_SIZE_NAMES}")
    return mapping[name]


def _factory(size: str):
    import gi

    gi.require_version("GnomeDesktop", "4.0")
    from gi.repository import GnomeDesktop

    return GnomeDesktop.DesktopThumbnailFactory.new(_thumbnail_size(size))


def lookup_cached_thumbnail(path: Path, size: str = "large") -> Path | None:
    """Return the cached thumbnail path if one already exists, else ``None``.

    Safe to call on the main thread — this is a stat-and-hash cache lookup,
    not decoding.
    """
    factory = _factory(size)
    uri = thumbnail_uri_for_path(path)
    mtime = int(path.stat().st_mtime)
    cached = factory.lookup(uri, mtime)
    return Path(cached) if cached else None


def generate_thumbnail_sync(path: Path, size: str = "large") -> Path:
    """Generate and save a thumbnail, returning its cache path.

    This decodes the source image and must be called off the main thread —
    :func:`request_thumbnail_async` is the entry point that does that for
    you. Raises :class:`ThumbnailError` if the factory declines the file or
    generation fails.
    """
    factory = _factory(size)
    uri = thumbnail_uri_for_path(path)
    mtime = int(path.stat().st_mtime)
    content_type = guess_content_type(path)

    if not factory.can_thumbnail(uri, content_type, mtime):
        raise ThumbnailError(f"factory declined to thumbnail {path} ({content_type})")

    pixbuf = factory.generate_thumbnail(uri, content_type)
    if pixbuf is None:
        raise ThumbnailError(f"thumbnail generation returned nothing for {path}")

    factory.save_thumbnail(pixbuf, uri, mtime)
    cached = factory.lookup(uri, mtime)
    if cached is None:
        raise ThumbnailError(f"thumbnail was saved but not found in the cache for {path}")
    return Path(cached)


def request_thumbnail_async(
    path: Path,
    on_ready: Callable[[Path | None, Exception | None], None],
    size: str = "large",
) -> None:
    """Get a thumbnail for ``path`` without blocking the caller.

    Checks the cache synchronously first (fast enough for the main thread);
    on a miss, generates on a background thread and delivers the result via
    ``GLib.idle_add`` so ``on_ready`` always runs on the main thread, exactly
    once. ``on_ready`` receives ``(path, None)`` on success or
    ``(None, exception)`` on failure — it never raises into the caller.
    """
    cached = lookup_cached_thumbnail(path, size)
    if cached is not None:
        on_ready(cached, None)
        return

    def worker() -> None:
        from gi.repository import GLib

        try:
            result = generate_thumbnail_sync(path, size)
        except Exception as exc:  # noqa: BLE001 - handed to on_ready, not raised here
            # `as exc` is deleted when the except block ends (PEP 3110), so it
            # has to be rebound to a plain local before the closure below can
            # still see it once GLib.idle_add calls it later.
            error = exc

            def deliver_error() -> bool:
                on_ready(None, error)
                return GLib.SOURCE_REMOVE

            GLib.idle_add(deliver_error)
            return

        def deliver() -> bool:
            on_ready(result, None)
            return GLib.SOURCE_REMOVE

        GLib.idle_add(deliver)

    threading.Thread(target=worker, daemon=True).start()
