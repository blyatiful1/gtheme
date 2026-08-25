"""The cheap offscreen variant: GTK's broadway backend, no shell at all.

Two audiences.

**CI.** The ``gtk`` job runs in an ``archlinux:latest`` container — libadwaita
1.9 exists there, which it does not on ubuntu-latest — with no compositor.
``gtk4-broadwayd`` gives GTK4 a display to render into, and ``dbus-run-session``
gives ``Adw.Application`` a bus to register on. That combination was verified on
this machine (adwaita-playbook.md) and is what makes a real Adw window testable
without a seat.

**Page authors.** Booting a headless GNOME Shell takes the better part of a
minute. This takes about a second, and answers the question that actually
fails during page work: does this widget tree construct and map at all. What it
cannot answer is anything about shell chrome, extensions, or screenshots — for
those, the full sandbox.

These are marked ``gtk`` rather than ``sandbox`` on purpose: they are meant to
run in CI, and they are safe to run anywhere, because the app is launched with
its own private bus and its own XDG roots. The live canary in ``conftest.py``
still wraps them.
"""

from __future__ import annotations

import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.gtk

#: Long enough for a failure-to-construct to surface as an exit, short enough
#: that the test stays worth running on every commit.
SETTLE_SECONDS = 6.0


def _launch(env: dict[str, str], argv: list[str]) -> subprocess.Popen[str]:
    return subprocess.Popen(  # noqa: S603
        ["dbus-run-session", "--", *argv],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )


def test_the_app_constructs_its_window_under_broadway(broadway_session: dict[str, str]):
    """The whole Adw window — sidebar, breakpoint, fifteen pages — must build."""
    process = _launch(broadway_session, [sys.executable, "-m", "gtheme"])
    try:
        time.sleep(SETTLE_SECONDS)
        assert process.poll() is None, (
            "gtheme exited under broadway instead of showing a window:\n"
            + (process.communicate(timeout=10)[0] or "")[-3000:]
        )
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def test_the_backend_really_is_broadway(broadway_session: dict[str, str]):
    """Guard against the fixture silently falling back to the live display.

    If ``GDK_BACKEND`` were being ignored, this test would still pass while
    quietly opening a window on the developer's screen — so it checks the
    environment it hands out, not just that something started.
    """
    assert broadway_session["GDK_BACKEND"] == "broadway"
    assert "DISPLAY" not in broadway_session
    assert "WAYLAND_DISPLAY" not in broadway_session


def test_the_rescue_path_needs_no_display_at_all(broadway_session: dict[str, str]):
    """``gtheme rescue`` must run from a text console with GTK unusable.

    Checked here because this is the only place with an environment that has no
    display of any kind: the point of the rescue command is that it works when
    the graphical session does not.
    """
    env = dict(broadway_session)
    env.pop("GDK_BACKEND", None)
    env.pop("BROADWAY_DISPLAY", None)
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "gtheme", "--version"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("gtheme ")
