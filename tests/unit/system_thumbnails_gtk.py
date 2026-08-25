"""GTK-marked tests for gtheme.system.thumbnails — needs GnomeDesktop + GdkPixbuf."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.gtk


@pytest.fixture
def sample_png(tmp_path: Path) -> Path:
    pytest.importorskip("gi", reason="PyGObject is needed to build a sample image")
    import gi

    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf

    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 32, 32)
    pixbuf.fill(0xFF00FFFF)
    path = tmp_path / "sample.png"
    pixbuf.savev(str(path), "png", [], [])
    return path


def test_lookup_misses_for_a_never_thumbnailed_file(sample_png: Path) -> None:
    from gtheme.system.thumbnails import lookup_cached_thumbnail

    assert lookup_cached_thumbnail(sample_png) is None


def test_generate_then_lookup_hits_the_cache(
    sample_png: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Keep the thumbnail cache this test writes to out of the real ~/.cache.
    import os
    import tempfile

    cache_dir = tempfile.mkdtemp(prefix="gtheme-thumb-test-")
    monkeypatch.setenv("XDG_CACHE_HOME", cache_dir)
    os.environ["XDG_CACHE_HOME"] = cache_dir  # GLib reads env at call time, not import time

    from gtheme.system.thumbnails import generate_thumbnail_sync, lookup_cached_thumbnail

    generated = generate_thumbnail_sync(sample_png)
    assert generated.is_file()

    cached = lookup_cached_thumbnail(sample_png)
    assert cached == generated


def test_request_thumbnail_async_delivers_on_ready(
    sample_png: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os
    import tempfile

    from gi.repository import GLib

    cache_dir = tempfile.mkdtemp(prefix="gtheme-thumb-test-async-")
    monkeypatch.setenv("XDG_CACHE_HOME", cache_dir)
    os.environ["XDG_CACHE_HOME"] = cache_dir

    from gtheme.system.thumbnails import request_thumbnail_async

    results: list[tuple[Path | None, Exception | None]] = []

    def on_ready(path: Path | None, error: Exception | None) -> None:
        results.append((path, error))

    request_thumbnail_async(sample_png, on_ready)

    context = GLib.MainContext.default()
    for _ in range(2000):
        if results:
            break
        context.iteration(True)

    assert len(results) == 1
    path, error = results[0]
    assert error is None
    assert path is not None and path.is_file()
