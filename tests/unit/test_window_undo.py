"""The way back, from the window's side: the header button and Ctrl+Z.

Three findings that all live in the same few lines (persona-report §2.8,
review-report L6 and M15):

* the header's Undo was ``Gtk.Button(label=…, icon_name=…)``, where GTK4's
  ``set_icon_name`` replaces the label child — so the words were silently
  discarded and every screenshot shows a bare back-arrow sitting exactly where
  a Windows user reads "Back";
* it was built by the Home page and packed as a side effect of that page being
  opened, so a session that reopened on Wallpaper had no undo in the header at
  all;
* Ctrl+Z applied the newest saved moment outright — no preview, no
  confirmation, from anywhere in the app including inside four text entries —
  while the same action from the Undo page asked first;
* and ``Adw.Toast`` renders Pango markup, over titles that are routinely a
  Look's name or a name somebody typed.

Every test runs with the window's preferences in a temporary directory and
``ask_desktop=False``, so nothing here touches the desktop it runs on.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.gtk

from gi.repository import Adw, Gtk  # noqa: E402

from gtheme.core import restorepoints  # noqa: E402
from gtheme.core.settings_backend import MemoryBackend  # noqa: E402
from gtheme.prefs import Prefs  # noqa: E402
from gtheme.ui.search import escape_markup  # noqa: E402
from gtheme.window import COPY, Window, is_text_editing  # noqa: E402


@pytest.fixture
def prefs(tmp_path: Path) -> Prefs:
    return Prefs(tmp_path / "prefs.json")


@pytest.fixture
def window(prefs: Prefs) -> Window:
    return Window(prefs, ask_desktop=False, mirror=False)


class FakeRestorePage:
    """The Undo page's half of the shared contract, and nothing else."""

    def __init__(self) -> None:
        self.asked: list[Any] = []

    def confirm_undo_last(self, parent_window: Any | None = None) -> None:
        self.asked.append(parent_window)


def _undo_page(window: Window) -> FakeRestorePage:
    page = FakeRestorePage()
    window._pages["restore"] = page
    return page


# -- the button itself -----------------------------------------------------


def test_the_header_undo_shows_the_word_undo_next_to_its_icon(window: Window):
    """An icon and a label, not an icon that ate a label."""
    content = window.undo_button.get_child()

    assert isinstance(content, Adw.ButtonContent)
    assert content.get_label() == COPY["undo-button"]
    assert content.get_icon_name() == "edit-undo-symbolic"


def test_the_header_undo_belongs_to_the_window_not_to_the_home_page(prefs: Prefs):
    """A session that never opens Home still has a way back in the header.

    Pages are lazy and the window reopens on the page you were last on, so
    "the Home page happened to be built" was a condition the safety net was
    hanging from.
    """
    prefs.set("window/last-page", "wallpaper")
    window = Window(prefs, ask_desktop=False, mirror=False)

    assert "home" not in window._pages, "this session never opened Home"
    assert window.undo_button.get_ancestor(Adw.HeaderBar) is window.header


# -- Ctrl+Z and the button both ask first ----------------------------------


def test_ctrl_z_asks_before_it_puts_a_whole_desktop_back(window: Window, monkeypatch):
    """The same confirmation the Undo page shows, from the keyboard."""
    page = _undo_page(window)
    applied: list[str] = []
    monkeypatch.setattr(window, "undo_point", lambda point_id: applied.append(point_id))

    assert window.undo_shortcut() is True
    assert page.asked == [window], "the page is asked to confirm, with the window to show it on"
    assert applied == [], "nothing is applied before somebody says yes"


def test_the_header_button_goes_through_the_same_confirmation(window: Window):
    page = _undo_page(window)

    window.undo_button.emit("clicked")

    assert page.asked == [window]


def test_the_undo_page_is_built_on_demand_rather_than_navigated_to(window: Window):
    """Asked for by a window that has never opened it, and still answered.

    The real page, not a stand-in: this is the wiring that makes the header
    button work in a session that only ever looked at Colours.
    """
    assert "restore" not in window._pages
    page = window._undo_page()
    assert page is not None
    assert hasattr(page, "confirm_undo_last")
    assert window.content_page.get_title() != "Undo & Restore Points", (
        "confirming is a dialog over where you are, not a jump to another page"
    )


def test_an_undo_page_that_will_not_build_is_said_out_loud(window: Window):
    """No confirmation available means no silent whole-desktop restore either."""
    window._pages["restore"] = object()

    said: list[str] = []
    original = Adw.ToastOverlay.add_toast
    Adw.ToastOverlay.add_toast = lambda _self, toast: said.append(toast.get_title())
    try:
        window.undo_last_change()
    finally:
        Adw.ToastOverlay.add_toast = original

    assert said == [escape_markup(COPY["undo-unavailable"])]


# -- the editable guard ----------------------------------------------------


def test_a_text_box_being_typed_in_is_recognised():
    entry = Gtk.Entry()
    assert is_text_editing(entry) is True
    entry.set_editable(False)
    assert is_text_editing(entry) is False

    view = Gtk.TextView()
    assert is_text_editing(view) is True

    assert is_text_editing(Gtk.Label(label="not a box")) is False
    assert is_text_editing(None) is False


def test_ctrl_z_in_a_text_box_leaves_the_desktop_alone(window: Window, monkeypatch):
    """Somebody naming a Look presses the undo they know. It undoes their word."""
    page = _undo_page(window)
    entry = Gtk.Entry()
    forwarded: list[str] = []
    monkeypatch.setattr(window, "get_focus", lambda: entry)
    monkeypatch.setattr(
        entry, "activate_action", lambda name, _target=None: forwarded.append(name)
    )

    assert window.undo_shortcut() is False
    assert page.asked == [], "the desktop's undo never fires from inside a text box"
    assert forwarded == ["text.undo"], "the keystroke goes where it was aimed"


# -- what the button says it will do ---------------------------------------


def test_the_tooltip_names_the_moment_it_would_go_back_to(window: Window, state_dir):
    restorepoints.capture(
        ["gsettings:org.gnome.desktop.interface icon-theme"],
        label="My desktop, 25 August",
        backend=MemoryBackend(),
    )

    assert window.undo_tooltip_text() == COPY["undo-tooltip"].format(
        moment="My desktop, 25 August"
    )


def test_the_tooltip_is_honest_when_there_is_no_moment_yet(window: Window, state_dir):
    assert window.undo_tooltip_text() == COPY["undo-nothing"]


# -- U8, the other half: the sentence at the end names the moment too -------


@pytest.mark.mutating
def test_the_toast_after_a_toast_undo_names_the_moment(
    window: Window, state_dir, memory_settings, tmp_dest_root
):
    """U8's acceptance line ends "toast names the moment". This is that.

    The tooltip above answers "back to what?" *before* the press. Afterwards
    the window said "Put back how it was." and named nothing — and this is the
    undo furthest from the list of saved moments: it is the button on the toast
    that follows applying a Look, pressed by somebody looking at the Looks
    page. The sentence is now the same one the Undo page and the Home card say,
    which is why it is asserted through ``done_sentence`` rather than by
    copying the wording here.
    """
    from gtheme.core import backends
    from gtheme.ui.applyrunner import ApplyRunner
    from gtheme.ui.pages import restore as restore_page

    window.runner = ApplyRunner(threaded=False)
    said: list[str] = []
    original = Adw.ToastOverlay.add_toast
    with backends.use_backend(memory_settings):
        point = restorepoints.capture(
            ["gsettings:org.gnome.desktop.interface icon-theme"],
            label="My desktop, 25 August",
            backend=memory_settings,
        )
        Adw.ToastOverlay.add_toast = lambda _self, toast: said.append(toast.get_title())
        try:
            window.undo_point(point.id)
        finally:
            Adw.ToastOverlay.add_toast = original

    assert said == [escape_markup(restore_page.done_sentence(point))]
    assert "My desktop, 25 August" in said[-1], "the moment, by name"


# -- M15 -------------------------------------------------------------------


def test_a_toast_never_lets_a_name_become_markup(window: Window):
    """A Look called "Black & Gold" made the whole confirmation render empty."""
    toast = window.toast("Black & Gold is on now.")
    assert toast.get_title() == "Black &amp; Gold is on now."

    hostile = window.toast('<span size="xx-large">Nothing was changed.</span>')
    assert "<span" not in hostile.get_title()
