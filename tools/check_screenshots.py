#!/usr/bin/env python3
"""The screenshot honesty gate (DESIGN.md F15).

``verify.sh --full`` runs the page walk and then runs this. The page walk
writes thirty PNGs; this refuses to believe them.

The failure this exists to catch is not "the screenshots are missing" — that
one announces itself. It is the quiet one: the page walk ran, every command
answered "ok", thirty files were written, and every one of them is a picture of
the same thing. That happens for real reasons. A window that never got the
keyboard focus renders every page identically; a page that raised on import
shows a stand-in; a colour scheme that was requested and not applied gives
fifteen "dark" pictures that are the light ones again. Each of those produces a
green test run and a README full of lies.

So the checks are about what the pictures *are*, not about whether they exist:

* every one of them is newer than the run that claimed to take it;
* every one of them is a real PNG of a plausible size and the right width;
* the fifteen light pictures are all different from each other;
* each page's light and dark pictures differ;
* none of them is a flat rectangle — which is what a window that never painted
  produces, and the only one of these checks that looks inside the image.

Run with no arguments, from anywhere:

    python tools/check_screenshots.py
"""

from __future__ import annotations

import hashlib
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from gtheme.ui import registry  # noqa: E402

SHOTS = REPO_ROOT / "docs" / "media" / "screenshots"
RUN_MARKER = SHOTS / ".run-start"

#: Set by ``verify.sh`` before the sandbox tier runs. Every picture must be
#: newer than this, or they are left over from some earlier afternoon.
RUN_START_ENV = "GTHEME_SCREENSHOT_RUN_START"

#: A window-sized PNG is hundreds of kilobytes. Anything under this is a file,
#: not a picture.
MIN_BYTES = 20_000

#: What packaging.md §7 asks the README to show.
EXPECTED_WIDTH = 1200

#: A picture whose most common colour covers more than this is a flat
#: rectangle with a bit of noise: a window that never painted its content.
MAX_FLAT_SHARE = 0.97

MODES = ("light", "dark")


def main() -> int:
    problems: list[str] = []
    pages = registry.page_ids()

    since = _run_start()
    if since is None:
        return _fail(
            [
                "no screenshot run to check against.",
                f"  Neither {RUN_START_ENV} is set nor {_rel(RUN_MARKER)} exists,",
                "  so there is no way to tell a fresh picture from a stale one.",
                "  Run the page walk first:  ./verify.sh --full",
            ]
        )

    pictures: dict[tuple[str, str], Path] = {}
    for page_id in pages:
        for mode in MODES:
            path = SHOTS / f"{page_id}-{mode}.png"
            pictures[(page_id, mode)] = path
            problems.extend(_check_one(path, since))

    if problems:
        return _fail(problems)

    problems.extend(_check_all_different(pages, pictures))
    problems.extend(_check_light_differs_from_dark(pages, pictures))
    if problems:
        return _fail(problems)

    print(
        f"check_screenshots: {len(pictures)} fresh screenshots, "
        f"{len(pages)} pages, light and dark, all distinct"
    )
    return 0


# -- one picture at a time --------------------------------------------------


def _check_one(path: Path, since: float) -> list[str]:
    if not path.is_file():
        return [f"{_rel(path)}: missing — the page walk did not photograph this page"]

    problems: list[str] = []
    stat = path.stat()
    if stat.st_mtime < since:
        age = since - stat.st_mtime
        problems.append(
            f"{_rel(path)}: left over from an earlier run ({age / 60:.0f} minutes older "
            "than this one)"
        )
    if stat.st_size < MIN_BYTES:
        problems.append(f"{_rel(path)}: only {stat.st_size} bytes — that is not a window")
    header = path.read_bytes()[:8]
    if header != b"\x89PNG\r\n\x1a\n":
        return [*problems, f"{_rel(path)}: not a PNG at all"]

    picture = _load(path)
    if picture is None:
        return [*problems, f"{_rel(path)}: could not be opened as an image"]
    width, height, flat = picture
    if width != EXPECTED_WIDTH:
        problems.append(f"{_rel(path)}: {width}px wide, expected {EXPECTED_WIDTH}")
    if height < 300:
        problems.append(f"{_rel(path)}: {height}px tall — that is a strip, not a window")
    if flat > MAX_FLAT_SHARE:
        problems.append(
            f"{_rel(path)}: {flat:.0%} of it is one colour — the window never painted"
        )
    return problems


def _load(path: Path) -> tuple[int, int, float] | None:
    """``(width, height, share of the single most common colour)``.

    GdkPixbuf rather than an image library, for the same reason the page walk
    uses it: PyGObject is a hard dependency of this project already, and adding
    a second way to read a PNG is a second thing to keep installed.
    """
    try:
        import gi

        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
    except (ImportError, ValueError):  # pragma: no cover - PyGObject is required
        return None

    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(path))
    except Exception:  # noqa: BLE001 - a picture that will not open is the finding
        return None

    width = pixbuf.get_width()
    height = pixbuf.get_height()
    return width, height, _flat_share(pixbuf)


def _flat_share(pixbuf: object) -> float:
    """How much of the picture is its single most common colour.

    Sampled on a grid rather than read pixel by pixel: a 1200x800 window is
    nearly a million pixels and this question does not need all of them.
    """
    get_pixels = getattr(pixbuf, "get_pixels", None)
    if get_pixels is None:  # pragma: no cover - not a pixbuf
        return 0.0
    data = get_pixels()
    stride = pixbuf.get_rowstride()  # type: ignore[attr-defined]
    channels = pixbuf.get_n_channels()  # type: ignore[attr-defined]
    width = pixbuf.get_width()  # type: ignore[attr-defined]
    height = pixbuf.get_height()  # type: ignore[attr-defined]

    counts: dict[bytes, int] = {}
    total = 0
    step_x = max(1, width // 120)
    step_y = max(1, height // 120)
    for y in range(0, height, step_y):
        row = y * stride
        for x in range(0, width, step_x):
            start = row + x * channels
            pixel = bytes(data[start : start + 3])
            if len(pixel) < 3:
                continue
            counts[pixel] = counts.get(pixel, 0) + 1
            total += 1
    if not total:
        return 0.0
    return max(counts.values()) / total


# -- the pictures against each other ----------------------------------------


def _check_all_different(pages: tuple[str, ...], pictures: dict[tuple[str, str], Path]) -> list[str]:
    by_digest: dict[str, list[str]] = {}
    for page_id in pages:
        digest = hashlib.sha256(pictures[(page_id, "light")].read_bytes()).hexdigest()
        by_digest.setdefault(digest, []).append(page_id)
    return [
        f"these pages are the same picture: {', '.join(sorted(shared))} — "
        "the walk photographed one screen several times"
        for shared in by_digest.values()
        if len(shared) > 1
    ]


def _check_light_differs_from_dark(
    pages: tuple[str, ...], pictures: dict[tuple[str, str], Path]
) -> list[str]:
    problems = []
    for page_id in pages:
        light = pictures[(page_id, "light")].read_bytes()
        dark = pictures[(page_id, "dark")].read_bytes()
        if light == dark:
            problems.append(
                f"{page_id}: the light and dark pictures are identical — "
                "the colour scheme was never forced"
            )
    return problems


# -- odds and ends ----------------------------------------------------------


def _run_start() -> float | None:
    raw = os.environ.get(RUN_START_ENV)
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    if RUN_MARKER.is_file():
        try:
            return float(RUN_MARKER.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None
    return None


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:  # pragma: no cover - always inside the repo
        return str(path)


def _fail(problems: list[str]) -> int:
    print("check_screenshots: the screenshots are not honest", file=sys.stderr)
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
    print(
        f"\n  (checked against a run starting {time.strftime('%H:%M:%S')}; "
        "the page walk is tests/sandbox/test_app_pages.py)",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
