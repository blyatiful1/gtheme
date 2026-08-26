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
