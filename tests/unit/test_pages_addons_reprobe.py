"""Asking the desktop again, after it did not answer the first time.

The Add-ons page used to end its "GNOME is not answering" screen with "give it
a moment and open this page again", which could not work: the connection is
made once per window and the page's widgets are kept, so leaving the page and
coming back showed the same answer from the same failed attempt until the app
was quit (persona-report §3.3, E10).

Nothing here reaches a real desktop: the reconnection is scripted, exactly like
every other test in this suite.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for the page module")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from ego_fakes import FakeShellProxy  # noqa: E402
from gi.repository import Adw, Gtk  # noqa: E402

from gtheme.core.backends import set_backend  # noqa: E402
from gtheme.core.settings_backend import MemoryBackend  # noqa: E402
from gtheme.ego.shelldbus import ShellError, ShellErrorKind, ShellExtensions  # noqa: E402
from gtheme.prefs import Prefs  # noqa: E402
from gtheme.ui.pages import addons  # noqa: E402

pytestmark = pytest.mark.gtk

BLUR = "blur-my-shell@aunetx"


class Refusing(FakeShellProxy):
    """A desktop that is there but not answering yet — a fresh login."""

    def list_extensions(self) -> dict[str, Any]:
        raise ShellError(ShellErrorKind.UNAVAILABLE, "no desktop here")


class FakeWindow:
    """What the page uses the window for, plus the shared connection it keeps."""

    def __init__(self) -> None:
        self.toasts: list[str] = []
        self.adopted: list[Any] = []
        self.runner = None

    def toast(self, text: str) -> None:
        self.toasts.append(text)

    def adopt_shell(self, shell: Any) -> Any:
        self.adopted.append(shell)
        return shell


@pytest.fixture
def prefs(config_dir) -> Prefs:
    return Prefs()


@pytest.fixture
def page(prefs: Prefs):
    """A page that found no desktop when it was built."""
    set_backend(MemoryBackend())
    window = FakeWindow()
    built = addons.AddonsPage(
        window,
        shell=ShellExtensions(Refusing({})),
        client=None,
        prefs=prefs,
        panels=[],
    )
    try:
        yield built, window
    finally:
        built.teardown()
        set_backend(None)


def _status_pages(widget: Gtk.Widget) -> list[Adw.StatusPage]:
    found: list[Adw.StatusPage] = []

    def walk(parent: Gtk.Widget) -> None:
        child = parent.get_first_child()
        while child is not None:
            if isinstance(child, Adw.StatusPage):
                found.append(child)
            walk(child)
            child = child.get_next_sibling()

    walk(widget)
    return found


def _retry_buttons(widget: Gtk.Widget) -> list[Gtk.Button]:
    found: list[Gtk.Button] = []

    def walk(parent: Gtk.Widget) -> None:
        child = parent.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.Button) and child.get_label() == addons.COPY[
                "no-desktop-retry"
            ]:
                found.append(child)
            walk(child)
            child = child.get_next_sibling()

    walk(widget)
    return found


def test_the_screen_that_says_nothing_answered_carries_a_way_to_ask_again(page):
    built, _window = page
    assert built.available is False
    titles = [status.get_title() for status in _status_pages(built)]
    assert addons.COPY["no-desktop-title"] in titles
    assert _retry_buttons(built), "the sentence promises a way to ask again"


def test_the_copy_no_longer_tells_people_to_reopen_a_page_that_cannot_change():
    assert "open this page again" not in addons.COPY["no-desktop-body"]
    assert "ask again" in addons.COPY["no-desktop-body"]


def test_pressing_it_makes_a_new_connection_and_rebuilds_the_list(page, monkeypatch):
    built, window = page
    fresh = ShellExtensions(FakeShellProxy({BLUR: _info(BLUR)}))
    monkeypatch.setattr(built, "_connect_desktop", lambda _given: (fresh, True))

    _retry_buttons(built)[0].emit("clicked")

    assert built.shell is fresh
    assert built.available is True
    assert window.adopted == [fresh], "the window's shared connection is the new one"
    assert built._owns_shell is False, "the window owns it now; the page must not close it"
    assert window.toasts[-1] == addons.COPY["reprobe-worked"]
    titles = [status.get_title() for status in _status_pages(built.installed_view)]
    assert addons.COPY["no-desktop-title"] not in titles


def test_a_desktop_that_is_still_quiet_is_said_so_plainly(page, monkeypatch):
    built, window = page
    monkeypatch.setattr(built, "_connect_desktop", lambda _given: (None, False))

    _retry_buttons(built)[0].emit("clicked")

    assert built.available is False
    assert window.toasts[-1] == addons.COPY["reprobe-failed"]
    assert window.adopted == []
    # …and it can be asked again, as many times as somebody wants.
    assert built._reprobing is False
    assert _retry_buttons(built), "the way out is still on the screen"


def test_the_waiting_happens_off_the_click_handler(page, monkeypatch):
    """Reaching a desktop is a blocking call, so it goes through the runner."""
    from gtheme.ui.applyrunner import ApplyRunner

    built, window = page
    window.runner = ApplyRunner(threaded=False)
    fresh = ShellExtensions(FakeShellProxy({BLUR: _info(BLUR)}))
    seen: list[str] = []

    def answering(_given: Any) -> tuple[Any, bool]:
        seen.append(window.runner.dialog.get_heading())
        return fresh, True

    monkeypatch.setattr(built, "_connect_desktop", answering)
    _retry_buttons(built)[0].emit("clicked")

    assert seen == [addons.COPY["reprobe-heading"]]
    assert built.shell is fresh
    assert window.runner.dialog is None, "the dialog closes itself"


def test_two_presses_do_not_start_two_connections(page, monkeypatch):
    built, _window = page
    attempts: list[int] = []

    def slow(_given: Any) -> tuple[Any, bool]:
        attempts.append(1)
        built.ask_again()  # a second press while the first is still running
        return None, False

    monkeypatch.setattr(built, "_connect_desktop", slow)
    built.ask_again()
    assert attempts == [1]


def _info(uuid: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "uuid": uuid,
        "name": uuid.split("@")[0],
        "state": 1.0,
        "type": 2.0,
        "enabled": True,
        "version": 60.0,
    }
    payload.update(overrides)
    return payload
