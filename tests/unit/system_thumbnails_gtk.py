"""GTK-marked tests for gtheme.system.thumbnails — needs GnomeDesktop + GdkPixbuf."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.gtk


@pytest.fixture(scope="module")
def thumbnailer_can_spawn_its_helper() -> None:
    """Skip unless bubblewrap can actually build a sandbox on this machine.

    A GNOME thumbnail is not decoded in-process: the factory spawns the
    ``.thumbnailer`` helper the MIME type names, and both gnome-desktop and
    glycin run that helper inside ``bwrap``. bwrap needs an unprivileged user
    namespace, which an unprivileged docker container does not have — the CI
    container fails at the spawn with ``g-spawn-exit-error-quark: Child process
    exited with code 1`` before a single pixel is read, and no amount of
    installing packages changes that.

    This is a capability probe, not a platform guess: it runs bwrap exactly as
    those callers do and skips only when bwrap is present and cannot do its
    job. Where there is no bwrap at all the helper runs unwrapped, so there is
    nothing to skip for. On every machine with a working sandbox — every real
    desktop, and the local canonical check — the two tests below run in full.
    """
    bwrap = shutil.which("bwrap")
    if bwrap is None:
        return
    try:
        probe = subprocess.run(
            [bwrap, "--ro-bind", "/", "/", "--dev", "/dev", "--unshare-all", "true"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover - probe failed
        pytest.skip(f"bwrap could not be run at all ({exc}), so no thumbnail can be generated")
    if probe.returncode != 0:
        pytest.skip(
            "bwrap cannot create a sandbox here, so the thumbnailer's helper cannot be "
            "spawned — an unprivileged container has no user namespaces to give it: "
            f"{probe.stderr.strip() or f'exit {probe.returncode}'}"
        )


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
    sample_png: Path, monkeypatch: pytest.MonkeyPatch, thumbnailer_can_spawn_its_helper
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
    sample_png: Path, monkeypatch: pytest.MonkeyPatch, thumbnailer_can_spawn_its_helper
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
