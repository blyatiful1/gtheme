"""The wallpaper catalogue, and the slideshow XML format it can point at.

Two separate XML formats are involved (gnome-domains.md §3.4/§3.5):

* the **catalogue** — ``*.xml`` files under ``gnome-background-properties``
  directories, one ``<wallpaper>`` entry per offering, with absolute
  ``<filename>``/``<filename-dark>`` paths (not URIs, unlike the gsettings
  keys) plus the options/shading to apply it with;
* the **slideshow** format — what a catalogue entry's ``<filename>`` points at
  when the wallpaper changes over the day (GNOME's ``adwaita.xml`` and most of
  this app's bundled Looks use this). A catalogue entry's kind is
  discriminated purely by that filename's extension: ``.xml`` means
  "resolve this file for the current image", anything else means "this is
  the image".

The DOCTYPE line in every catalogue file references a DTD that is not
installed anywhere (verified on the research machine) — it is decorative, so
the parser strips it rather than letting an XML parser try to fetch it.

No ``gi`` import: plain ``pathlib`` and :mod:`xml.etree.ElementTree`, safe to
unit-test without a display.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

__all__ = [
    "SlideshowEvent",
    "SlideshowStart",
    "SlideshowTransition",
    "WallpaperEntry",
    "default_wallpaper_catalogue_roots",
    "parse_slideshow",
    "scan_wallpaper_catalogue",
]

_DOCTYPE_RE = re.compile(r"<!DOCTYPE[^>]*>")


@dataclass(frozen=True)
class WallpaperEntry:
    """One ``<wallpaper>`` offering from the catalogue."""

    name: str
    #: Absolute path (the XML stores these as paths, not ``file://`` URIs).
    filename: Path
    filename_dark: Path | None
    #: The ``org.gnome.desktop.background picture-options`` enum value.
    options: str
    #: The ``color-shading-type`` enum value.
    shade_type: str
    primary_color: str | None
    secondary_color: str | None
    #: Which catalogue file this came from — useful for provenance/debugging.
    source_xml: Path

    @property
    def is_slideshow(self) -> bool:
        """Whether ``filename`` names a slideshow XML rather than an image."""
        return self.filename.suffix.lower() == ".xml"


def default_wallpaper_catalogue_roots() -> list[Path]:
    """Real search order: XDG data home, then each XDG data dir."""
    home = Path(os.environ.get("HOME", str(Path.home())))
    data_home = Path(os.environ.get("XDG_DATA_HOME", str(home / ".local" / "share")))
    data_dirs_env = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share")
    data_dirs = [Path(p) for p in data_dirs_env.split(":") if p]
    roots = [data_home / "gnome-background-properties"]
    roots.extend(d / "gnome-background-properties" for d in data_dirs)
    return roots


def _parse_catalogue_file(xml_path: Path) -> list[WallpaperEntry]:
    try:
        raw = xml_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    raw = _DOCTYPE_RE.sub("", raw, count=1)
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        return []

    entries: list[WallpaperEntry] = []
    for wp in root.findall("wallpaper"):
        name_el = wp.find("name")
        filename_el = wp.find("filename")
        if name_el is None or filename_el is None or not (filename_el.text or "").strip():
            continue
        filename_dark_el = wp.find("filename-dark")
        options_el = wp.find("options")
        shade_el = wp.find("shade_type")
        pcolor_el = wp.find("pcolor")
        scolor_el = wp.find("scolor")
        entries.append(
            WallpaperEntry(
                name=(name_el.text or "").strip(),
                filename=Path(filename_el.text.strip()),
                filename_dark=(
                    Path(filename_dark_el.text.strip())
                    if filename_dark_el is not None and (filename_dark_el.text or "").strip()
                    else None
                ),
                options=(options_el.text or "zoom").strip() if options_el is not None else "zoom",
                shade_type=(
                    (shade_el.text or "solid").strip() if shade_el is not None else "solid"
                ),
                primary_color=(pcolor_el.text or "").strip() or None
                if pcolor_el is not None
                else None,
                secondary_color=(scolor_el.text or "").strip() or None
                if scolor_el is not None
                else None,
                source_xml=xml_path,
            )
        )
    return entries


def scan_wallpaper_catalogue(roots: list[Path]) -> list[WallpaperEntry]:
    """Parse every catalogue ``*.xml`` file under each root, in order."""
    entries: list[WallpaperEntry] = []
    for root in roots:
        if not root.is_dir():
            continue
        for xml_path in sorted(root.glob("*.xml")):
            entries.extend(_parse_catalogue_file(xml_path))
    return entries


# --- Slideshow XML (research/gnome-domains.md §3.5) -----------------------


@dataclass(frozen=True)
class SlideshowStart:
    year: int
    month: int
    day: int
    hour: int
    minute: int
    second: int


@dataclass(frozen=True)
class SlideshowEvent:
    """A ``<static>`` segment: show one file for ``duration`` seconds."""

    duration: float
    file: Path


@dataclass(frozen=True)
class SlideshowTransition:
    """A ``<transition>`` segment: cross-fade between two files."""

    kind: str
    duration: float
    from_file: Path
    to_file: Path


def _int_text(el: ElementTree.Element | None, tag: str, default: int = 0) -> int:
    child = el.find(tag) if el is not None else None
    return int((child.text or "0").strip()) if child is not None and child.text else default


_SlideshowSegment = SlideshowEvent | SlideshowTransition


def parse_slideshow(xml_path: Path) -> tuple[SlideshowStart, list[_SlideshowSegment]]:
    """Parse a slideshow XML file (what a catalogue entry's filename may point at).

    Returns the start time and the ordered sequence of static/transition
    segments. Malformed or unreadable files return an all-zero start and an
    empty sequence rather than raising — callers treat that the same as "not
    a slideshow".
    """
    try:
        raw = xml_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return SlideshowStart(0, 0, 0, 0, 0, 0), []
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        return SlideshowStart(0, 0, 0, 0, 0, 0), []

    start_el = root.find("starttime")
    start = SlideshowStart(
        year=_int_text(start_el, "year"),
        month=_int_text(start_el, "month"),
        day=_int_text(start_el, "day"),
        hour=_int_text(start_el, "hour"),
        minute=_int_text(start_el, "minute"),
        second=_int_text(start_el, "second"),
    )

    events: list[_SlideshowSegment] = []
    for el in root:
        if el.tag == "static":
            duration_el = el.find("duration")
            file_el = el.find("file")
            if duration_el is None or file_el is None or not (file_el.text or "").strip():
                continue
            events.append(
                SlideshowEvent(
                    duration=float((duration_el.text or "0").strip()),
                    file=Path(file_el.text.strip()),
                )
            )
        elif el.tag == "transition":
            duration_el = el.find("duration")
            from_el = el.find("from")
            to_el = el.find("to")
            if (
                duration_el is None
                or from_el is None
                or to_el is None
                or not (from_el.text or "").strip()
                or not (to_el.text or "").strip()
            ):
                continue
            events.append(
                SlideshowTransition(
                    kind=el.get("type", "overlay"),
                    duration=float((duration_el.text or "0").strip()),
                    from_file=Path(from_el.text.strip()),
                    to_file=Path(to_el.text.strip()),
                )
            )
    return start, events
