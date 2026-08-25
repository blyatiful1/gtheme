"""Boot smoke: gtheme starts inside a real GNOME Shell and shows its sidebar.

DESIGN.md step 10. The scope here is deliberately narrow — the app launches, a
window maps with real geometry, the sidebar lists all fifteen pages, and the
session can be screenshotted. Walking every page and producing the light/dark
screenshot pairs is Wave 3's ``test_app_pages.py``, once the pages exist; doing
it now would only photograph fifteen placeholders.

The screenshot check earns its place even so: it is the only thing that keeps
the two screenshot routes honest. Route A (a plain ``gdbus`` call) works only
while the sandbox extension has unsafe mode on, and route B (``shot.py``,
acquiring ``org.gnome.SettingsDaemon.MediaKeys`` and waiting ~1.2s for the
shell's name-watcher) is what a future shell that closes route A would fall back
to. If both ever break, Wave 3's screenshot gate breaks with them, and it is
better to find that out here.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from sandboxlib import SandboxSession

pytestmark = pytest.mark.sandbox

PROBE = Path(__file__).parent / "probes" / "sidebar_probe.py"

#: A 1920x1080 screenshot of a desktop with a window on it. The proof run
#: produced 1.8 MB; anything under this is a blank or truncated frame.
MIN_PNG_BYTES = 20_000


@pytest.fixture(scope="module")
def booted_app(sandbox_shared_data: SandboxSession) -> Iterator[dict]:
    """Launch ``python -m gtheme`` in the sandbox and wait for its window."""
    session = sandbox_shared_data
    process = session.spawn([sys.executable, "-m", "gtheme"])
    try:
        window = session.wait_for_window("gtheme")
        rect = session.wait_for_frame(int(window["id"]))
        session.hide_overview()
        # A settle beat so the compositor has painted the frame before anyone
        # photographs it.
        time.sleep(1.5)
        yield {"session": session, "process": process, "window": window, "rect": rect}
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


def _client_log(session: SandboxSession) -> str:
    """Whatever the launched app printed. Best effort: this is a failure message."""
    logs = sorted(session.root.glob("client-*.log"))
    return "".join(path.read_text(errors="replace")[-2000:] for path in logs) or "(no log)"


def test_the_app_starts_and_stays_up(booted_app: dict):
    process = booted_app["process"]
    assert process.poll() is None, (
        "gtheme exited during startup; client log:\n" + _client_log(booted_app["session"])
    )


def test_a_window_maps_with_real_geometry(booted_app: dict):
    """``GetFrameRect`` lies for the first 4-6 seconds; the helper polls it out."""
    rect = booted_app["rect"]
    assert rect["width"] > 0 and rect["height"] > 0
    # The window asks for 1000x720 and the virtual monitor is 1920x1080, so a
    # window filling the screen or collapsed to a strip means something is wrong
    # with how it was mapped, not merely with its size.
    assert 300 < rect["width"] <= 1920
    assert 200 < rect["height"] <= 1080


def test_the_window_belongs_to_gtheme(booted_app: dict):
    window = booted_app["window"]
    identity = " ".join(
        str(window.get(field, "")) for field in ("wm_class", "wm_class_instance", "title")
    ).lower()
    assert "gtheme" in identity, window


def test_the_sidebar_lists_all_fifteen_pages(booted_app: dict):
    """The manifest promises fifteen pages; the built sidebar must show them."""
    session: SandboxSession = booted_app["session"]
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(PROBE)],
        env=session.env(),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, f"sidebar probe failed:\n{result.stderr[-3000:]}"
    report = json.loads(result.stdout)

    assert report["count"] == 15, f"sidebar shows {report['count']} entries: {report['titles']}"
    assert report["count"] == len(report["manifest"])
    assert report["titles"] == report["manifest"], "sidebar order drifted from the manifest"
    assert report["sections"] == report["manifest_sections"]
    assert len(set(report["page_ids"])) == 15


def test_the_session_can_be_screenshotted(booted_app: dict, sandbox_run_dir: Path):
    """Both routes tried, whichever wins. Wave 3's gate depends on this working."""
    session: SandboxSession = booted_app["session"]
    shot = session.screenshot(sandbox_run_dir / "boot-smoke.png")
    size = shot.stat().st_size
    assert size > MIN_PNG_BYTES, f"screenshot is suspiciously small ({size} bytes)"
    assert shot.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_the_fallback_screenshot_route_still_works(booted_app: dict, sandbox_run_dir: Path):
    """``shot.py`` on its own, not as a fallback nobody ever reaches.

    Under unsafe mode the plain ``gdbus`` call succeeds, so
    :meth:`SandboxSession.screenshot` never gets as far as ``shot.py`` and the
    interesting code — acquire ``org.gnome.SettingsDaemon.MediaKeys``, wait
    ~1.2s for the shell's asynchronous name-watcher, then call — would rot
    untested until the day it was needed. Exercise it directly.

    Acquiring that name is safe here and nowhere else: this is a private bus
    with no real gnome-settings-daemon on it.
    """
    session: SandboxSession = booted_app["session"]
    target = sandbox_run_dir / "via-shot-py.png"
    result = session.run(
        [sys.executable, str(Path(__file__).parent / "shot.py"), str(target)], timeout=180
    )
    assert result.returncode == 0, (
        "the allow-listed-bus-name screenshot route failed. If gnome-shell "
        f"changed its SenderChecker allow-list, this is where it shows up.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "org.gnome.SettingsDaemon.MediaKeys" in result.stdout
    assert target.stat().st_size > MIN_PNG_BYTES
    assert target.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_unsafe_mode_is_on_and_the_overview_is_gone(booted_app: dict):
    """Without this the shell photographs its Overview forever."""
    session: SandboxSession = booted_app["session"]
    answer = session.shell_eval("Main.overview.visible")
    assert answer.startswith("(true,"), (
        "Eval is locked, which means the gtheme-sandbox extension did not load "
        f"and the harness cannot drive the shell: {answer}"
    )
    assert "'false'" in answer, f"the Overview is still up: {answer}"
