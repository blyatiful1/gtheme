"""The page walk: open every page of the real app and photograph it.

DESIGN.md step 19 and F15. This is the test that produces the thirty PNGs the
README is built out of, and it is deliberately the *only* thing that produces
them: a screenshot that was not taken by a run of the actual application, in a
session where the actual desktop was running, is a drawing.

What makes it honest rather than decorative:

* It runs the real ``Adw.Application`` and the real ``Window``, inside the
  private session the harness starts — private bus, private settings store,
  private extensions folder. ``tools/check_screenshots.py`` then refuses the
  result if the fifteen light pictures are not all different from each other,
  if a page's light and dark pictures match, or if any of them is older than
  the run that was supposed to have just taken them.
* It uses ``sandbox_private_data``, which seeds the fixture extension set, so
  the Add-ons page has real add-ons to list. An empty Add-ons page would pass
  every check above while showing nothing.
* It gives the app a sandbox ``HOME``. The Terminal page asks whether this
  computer's terminal settings are managed by something else, and on the
  machine this suite runs on the honest answer is yes — ``~/.config/ghostty``
  is a link into a live rice repository. Without this, the screenshot would be
  a picture of the developer's machine rather than of the app.
* It gives that sandbox a **wallpaper catalogue of its own** —
  :func:`_seed_wallpapers` — and warms the thumbnail cache before the app
  starts. Both are about the same failure: the Wallpaper page's grid draws
  ``Gtk.Picture`` tiles that have no size at all until their thumbnail exists,
  and thumbnails are generated on a worker thread, so a cold cache photographs
  as half a frame of empty grey no matter how many pictures the machine has.
  Warming it is not dressing the page up — it is the steady state of any
  machine somebody has browsed their wallpapers on once. The seeded pictures
  are generated here rather than borrowed from the machine so the grid has
  something in it on a box with no ``gnome-backgrounds`` installed, and the
  page itself is left alone: on a genuinely empty computer it should still
  render an empty grid, honestly.

Nothing here activates the "take them over" offer on the Terminal page, and
nothing here writes to the real desktop. The isolation canary in ``conftest``
proves the second part on every single test in this directory.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from sandboxlib import SandboxSession

pytestmark = pytest.mark.sandbox

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE = Path(__file__).parent / "probes" / "page_walk_probe.py"
SHOTS = REPO_ROOT / "docs" / "media" / "screenshots"

#: Written before the first picture is taken, read by
#: ``tools/check_screenshots.py`` to answer "are these from *this* run".
RUN_MARKER = SHOTS / ".run-start"

#: What the finished pictures are, on the nose. packaging.md §7 and the brief.
TARGET_WIDTH = 1200

#: A full-window PNG is well over this. The floor is here to catch a capture
#: that produced a file but not a picture.
MIN_PNG_BYTES = 20_000

#: How long one command may take before the walk is declared stuck. The
#: expensive page builds 243 rows; the first page also pays for the corpus.
REPLY_TIMEOUT = 120.0

#: How long the thumbnail warm-up may take. Roughly 7s for the 46 stock GNOME
#: 50 pictures on the machine this was measured on; the ceiling is for a slower
#: one, not for a hang, and a warm-up that overruns is skipped rather than
#: failed — a grid short a few thumbnails is a worse picture, not a wrong one.
WARM_TIMEOUT = 240.0

#: The wallpapers the sandbox is given, as ``(name, light, dark)`` where each
#: colour pair is the top and bottom of a vertical gradient. Four, because that
#: is enough to fill a grid line and show that the grid *is* a grid, and small
#: because they exist to be thumbnails.
SEEDED_WALLPAPERS: tuple[tuple[str, tuple[str, str], tuple[str, str]], ...] = (
    ("Sandbox Dawn", ("#f6c177", "#eb6f92"), ("#3a2a3f", "#1f1420")),
    ("Sandbox Dusk", ("#9ccfd8", "#31748f"), ("#1f3b47", "#0d1b22")),
    ("Sandbox Meadow", ("#a3d9a5", "#2e7d5b"), ("#1f4034", "#0c1a15")),
    ("Sandbox Slate", ("#cbd5e0", "#4a5568"), ("#2d3748", "#12161f")),
)

#: How big a seeded picture is. 16:9 so it fills the grid's aspect frames, and
#: a few hundred pixels because a thumbnail is 256 wide.
SEED_WIDTH = 480
SEED_HEIGHT = 270

#: Warms the thumbnail cache for everything the catalogue in *this* environment
#: offers — the seeded pictures and whatever the machine ships. Run in the
#: sandbox's own environment as a subprocess, because ``XDG_CACHE_HOME`` is read
#: once per process by GLib and the test process has the real one.
_WARM_SCRIPT = """
from gtheme.system.thumbnails import generate_thumbnail_sync, lookup_cached_thumbnail
from gtheme.system.wallpapers import (
    SlideshowEvent,
    default_wallpaper_catalogue_roots,
    parse_slideshow,
    scan_wallpaper_catalogue,
)


def sources(entry):
    for path in (entry.filename, entry.filename_dark):
        if path is None:
            continue
        if path.suffix.lower() != ".xml":
            yield path
            continue
        # A slideshow entry's tile shows the slideshow's first static frame.
        _start, events = parse_slideshow(path)
        first = next((event for event in events if isinstance(event, SlideshowEvent)), None)
        if first is not None:
            yield first.file


seen = set()
warm = 0
for entry in scan_wallpaper_catalogue(default_wallpaper_catalogue_roots()):
    for source in sources(entry):
        if source in seen:
            continue
        seen.add(source)
        try:
            if lookup_cached_thumbnail(source) is None:
                generate_thumbnail_sync(source)
            warm += 1
        except Exception:
            pass  # one picture this machine cannot decode is one empty tile
print(warm)
"""


class Walk:
    """The running app, and the way to ask it to show something."""

    def __init__(
        self, session: SandboxSession, process: subprocess.Popen[str], home: Path
    ) -> None:
        self.session = session
        self.process = process
        #: The throwaway home directory the app was given. Not the real one,
        #: which is the whole point of it existing.
        self.home = home
        self.rect: dict[str, int] = {}

    def command(self, text: str) -> str:
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        self.process.stdin.write(text + "\n")
        self.process.stdin.flush()
        return self.reply()

    def reply(self) -> str:
        assert self.process.stdout is not None
        deadline = time.monotonic() + REPLY_TIMEOUT
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise AssertionError(f"the app exited early:\n{self._log()}")
            line = self.process.stdout.readline()
            if not line:
                raise AssertionError(f"the app said nothing:\n{self._log()}")
            answer = line.strip()
            if answer:
                assert not answer.startswith("error "), f"{answer}\n{self._log()}"
                return answer
        raise AssertionError(f"the app did not answer in {REPLY_TIMEOUT}s:\n{self._log()}")

    def _log(self) -> str:
        return (self.session.log() or "")[-3000:]


def _gradient_png(target: Path, top: str, bottom: str) -> None:
    """Write one small vertical-gradient PNG. GdkPixbuf, because GTK is here anyway."""
    import gi

    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf

    def channels(spec: str) -> tuple[int, int, int]:
        return int(spec[1:3], 16), int(spec[3:5], 16), int(spec[5:7], 16)

    start, end = channels(top), channels(bottom)
    picture = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, SEED_WIDTH, SEED_HEIGHT)
    for y in range(SEED_HEIGHT):
        ratio = y / (SEED_HEIGHT - 1)
        red, green, blue = (
            round(start[index] + (end[index] - start[index]) * ratio) for index in range(3)
        )
        # A sub-pixbuf shares the parent's pixels, so filling it fills the row.
        picture.new_subpixbuf(0, y, SEED_WIDTH, 1).fill(
            (red << 24) | (green << 16) | (blue << 8) | 0xFF
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    picture.savev(str(target), "png", [], [])


def _seed_wallpapers(session: SandboxSession) -> Path:
    """Give the sandbox a wallpaper catalogue of its own. Returns the XML written.

    Into the sandbox's private ``XDG_DATA_HOME``, which is the first root
    ``system.wallpapers.default_wallpaper_catalogue_roots`` looks in — so these
    are the first tiles in both grids. The assertion is not paranoia: the same
    property in SHARED mode is the user's real ``~/.local/share``, and this
    fixture must never be pointed at that one by a copied line.
    """
    data_home = session.data_home
    assert session.root in data_home.parents, f"refusing to seed {data_home}"

    pictures = data_home / "backgrounds" / "gtheme-sandbox"
    entries: list[str] = []
    for name, light, dark in SEEDED_WALLPAPERS:
        slug = name.lower().replace(" ", "-")
        light_path = pictures / f"{slug}-l.png"
        dark_path = pictures / f"{slug}-d.png"
        _gradient_png(light_path, *light)
        _gradient_png(dark_path, *dark)
        entries.append(
            "  <wallpaper deleted=\"false\">\n"
            f"    <name>{name}</name>\n"
            f"    <filename>{light_path}</filename>\n"
            f"    <filename-dark>{dark_path}</filename-dark>\n"
            "    <options>zoom</options>\n"
            "    <shade_type>solid</shade_type>\n"
            f"    <pcolor>{light[0]}</pcolor>\n"
            f"    <scolor>{light[1]}</scolor>\n"
            "  </wallpaper>"
        )

    catalogue = data_home / "gnome-background-properties" / "gtheme-sandbox.xml"
    catalogue.parent.mkdir(parents=True, exist_ok=True)
    catalogue.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE wallpapers SYSTEM "gnome-wp-list.dtd">\n'
        "<wallpapers>\n" + "\n".join(entries) + "\n</wallpapers>\n",
        encoding="utf-8",
    )
    return catalogue


def _warm_thumbnails(session: SandboxSession, environment: dict[str, str]) -> int:
    """Generate the grid's thumbnails before the app asks for them.

    Best effort by design: this makes a picture of the Wallpaper page truthful
    rather than making it pass, so a warm-up that fails leaves emptier tiles
    and a walk that still runs.
    """
    try:
        finished = subprocess.run(  # noqa: S603
            [sys.executable, "-c", _WARM_SCRIPT],
            env=environment,
            capture_output=True,
            text=True,
            timeout=WARM_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 0
    if finished.returncode != 0:
        return 0
    try:
        return int(finished.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return 0


@pytest.fixture(scope="module")
def walk(
    sandbox_private_data: SandboxSession, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Walk]:
    """Launch the app in the sandbox and wait until its window is on screen."""
    session = sandbox_private_data
    home = tmp_path_factory.mktemp("page-walk-home")
    (home / ".config").mkdir(parents=True, exist_ok=True)

    environment = session.env({"HOME": str(home), "PYTHONUNBUFFERED": "1"})
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(REPO_ROOT / "src"), environment.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)

    _seed_wallpapers(session)
    _warm_thumbnails(session, environment)

    process = subprocess.Popen(  # noqa: S603
        [sys.executable, str(PROBE)],
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=(session.root / "page-walk.err").open("wb"),
        text=True,
        bufsize=1,
    )
    running = Walk(session, process, home)
    try:
        assert running.reply() == "ready"
        window = session.wait_for_window("gtheme")
        running.rect = session.wait_for_frame(int(window["id"]))
        session.hide_overview()
        # A settle beat so the compositor has painted the frame before anyone
        # photographs it.
        time.sleep(1.5)
        yield running
    finally:
        if process.poll() is None:
            try:
                assert process.stdin is not None
                process.stdin.write("quit\n")
                process.stdin.flush()
                process.wait(timeout=15)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()


def test_every_page_opens_and_is_photographed(walk: Walk):
    """The whole walk: fifteen pages, light and dark, thirty pictures.

    One test rather than thirty parametrised ones on purpose. The app is
    started once and driven through a conversation; splitting that into thirty
    tests would either restart it thirty times or make each test depend on the
    order the others ran in, and both of those are worse than one test whose
    failure message names the page it stopped on.
    """
    from gtheme.ui import registry

    SHOTS.mkdir(parents=True, exist_ok=True)
    RUN_MARKER.write_text(f"{time.time()}\n", encoding="utf-8")

    taken: list[Path] = []
    for mode in ("light", "dark"):
        assert walk.command(f"mode {mode}") == "ok"
        for page_id in registry.page_ids():
            assert walk.command(f"page {page_id}") == "ok", page_id
            target = SHOTS / f"{page_id}-{mode}.png"
            _photograph(walk, target)
            size = target.stat().st_size
            assert size > MIN_PNG_BYTES, f"{target.name} is suspiciously small ({size} bytes)"
            assert target.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", target.name
            taken.append(target)

    assert len(taken) == 2 * len(registry.page_ids()) == 30


def test_the_pictures_are_of_different_pages(walk: Walk):
    """The honesty check, in the tier that produced the pictures.

    ``tools/check_screenshots.py`` says the same thing to the canonical check.
    Saying it here as well means a page walk that silently photographed one
    placeholder fifteen times fails in the run that did it, naming the pages,
    rather than in a separate tool afterwards.
    """
    import hashlib

    from gtheme.ui import registry

    by_hash: dict[str, list[str]] = {}
    for page_id in registry.page_ids():
        picture = SHOTS / f"{page_id}-light.png"
        assert picture.is_file(), f"no light picture for {page_id}"
        digest = hashlib.sha256(picture.read_bytes()).hexdigest()
        by_hash.setdefault(digest, []).append(page_id)

    duplicates = {digest: pages for digest, pages in by_hash.items() if len(pages) > 1}
    assert not duplicates, f"these pages produced identical pictures: {duplicates}"

    for page_id in registry.page_ids():
        light = (SHOTS / f"{page_id}-light.png").read_bytes()
        dark = (SHOTS / f"{page_id}-dark.png").read_bytes()
        assert light != dark, f"{page_id}: the light and dark pictures are the same file"


def test_the_terminal_page_was_not_asked_to_take_anything_over(walk: Walk):
    """The one thing this walk must never do.

    ``~/.config/ghostty`` on the machine this suite runs on is a link into a
    live rice repository, and the Terminal page offers to take it over. The
    walk gives the app a sandbox HOME so the offer is about an empty folder,
    and it never answers the offer. This asserts the second half: the sandbox
    HOME still has no terminal configuration in it, so nothing was written
    anywhere on the strength of that banner.
    """
    home = walk.home
    assert home != Path.home(), "the walk must not run against the real home directory"
    assert not (home / ".config" / "ghostty" / "config").exists()
    assert not (Path.home() / ".config" / "ghostty" / "config.gtheme-backup").exists()


def test_the_wallpaper_page_had_pictures_to_photograph(walk: Walk):
    """The seeding, asserted where it is used.

    ``wallpaper-light.png`` used to be half a frame of empty grey, and nothing
    in the walk noticed: an empty grid is a perfectly good PNG, different from
    every other page's, and different in dark mode. So the two things that make
    it not empty are checked here rather than trusted — the catalogue this
    fixture wrote, and a thumbnail on disk for every picture in it, which is
    what a ``Gtk.Picture`` needs before it has any size at all.
    """
    from gtheme.system.wallpapers import scan_wallpaper_catalogue

    catalogue = walk.session.data_home / "gnome-background-properties"
    entries = scan_wallpaper_catalogue([catalogue])
    assert len(entries) == len(SEEDED_WALLPAPERS)

    pictures = [entry.filename for entry in entries]
    pictures += [entry.filename_dark for entry in entries if entry.filename_dark]
    missing = [str(path) for path in pictures if not path.is_file()]
    assert not missing, f"the catalogue names pictures that were never written: {missing}"

    thumbnails = list((walk.session.root / "cache" / "thumbnails").rglob("*.png"))
    assert len(thumbnails) >= len(pictures), (
        f"{len(thumbnails)} thumbnails for {len(pictures)} seeded pictures — the "
        "grid would photograph as empty tiles"
    )


def _photograph(walk: Walk, target: Path) -> None:
    """Photograph the whole screen, then keep the window out of it."""
    full = walk.session.root / "full-frame.png"
    if full.exists():
        full.unlink()
    walk.session.screenshot(full)
    _crop_to_window(full, walk.rect, target)


def _crop_to_window(full: Path, rect: dict[str, int], target: Path) -> None:
    """Cut the window out of the monitor and write it at the README's width.

    ``GdkPixbuf`` rather than an image library: it is already here, because
    every one of these processes has GTK loaded anyway.
    """
    import gi

    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf

    whole = GdkPixbuf.Pixbuf.new_from_file(str(full))
    x = max(0, int(rect.get("x", 0)))
    y = max(0, int(rect.get("y", 0)))
    width = min(int(rect.get("width", 0)) or whole.get_width(), whole.get_width() - x)
    height = min(int(rect.get("height", 0)) or whole.get_height(), whole.get_height() - y)
    assert width > 200 and height > 200, f"the window rect is not a window: {rect}"

    cropped = whole.new_subpixbuf(x, y, width, height)
    if cropped.get_width() != TARGET_WIDTH:
        scale = TARGET_WIDTH / cropped.get_width()
        cropped = cropped.scale_simple(
            TARGET_WIDTH,
            max(1, round(cropped.get_height() * scale)),
            GdkPixbuf.InterpType.BILINEAR,
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    cropped.savev(str(target), "png", [], [])
