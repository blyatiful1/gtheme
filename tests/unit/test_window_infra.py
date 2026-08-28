"""What the window does around the app: the gate, the launch, the keyboard.

Each test here pins one finding from the audit, and each one is written so that
it fails against the code as it was:

* **M26** — the version the gate needs is a cached property. Reading it used to
  go through the shared desktop connection, whose ``load()`` is a
  ``ListExtensions`` call with GDBus's 25-second default timeout, inside
  ``Window(...)`` and therefore before anything was drawn.
* **X2** — a desktop that would not say its version was treated as permission
  to proceed, which put the ``Adw.Sidebar`` ``AttributeError`` back in front of
  the people the polite screen exists for.
* **L14** — every sidebar click wrote ``prefs.json`` with an ``fsync`` on the
  main loop.
* **X4/U5** — About had no help link and nothing anywhere copied the details a
  bug report asks for.
* **U10** — the window opened at 1200x900 whatever the screen was, and there
  was no list of keyboard shortcuts and no key that reached the sidebar.
* **E6** — a change interrupted by a crash or a power cut was noticed by
  nothing at all on the next launch.

Nothing here is ever presented, and every window is built with
``ask_desktop=False`` unless the test is specifically about asking.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.gtk

from gi.repository import Adw, Gtk  # noqa: E402

from gtheme import __version__  # noqa: E402
from gtheme import window as window_module  # noqa: E402
from gtheme.prefs import Prefs  # noqa: E402
from gtheme.window import (  # noqa: E402
    COPY,
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    MINIMUM_GNOME,
    MINIMUM_HEIGHT,
    MINIMUM_WIDTH,
    Window,
    check_desktop,
    fit_to_monitor,
)


@pytest.fixture
def prefs(tmp_path: Path) -> Prefs:
    return Prefs(tmp_path / "prefs.json")


@pytest.fixture
def window(prefs: Prefs) -> Window:
    return Window(prefs, ask_desktop=False, mirror=False)


class OldLibadwaita:
    """libadwaita as GNOME 47 and 48 ship it: no 1.9 sidebar widgets.

    Reports its own version as well as refusing the four names, because the
    version is now what the gate asks — the whole point of X2.
    """

    _MISSING = frozenset({"Sidebar", "SidebarSection", "SidebarItem", "SidebarMode"})

    @staticmethod
    def get_major_version() -> int:
        return 1

    @staticmethod
    def get_minor_version() -> int:
        return 5

    def __getattr__(self, name: str) -> Any:
        if name in self._MISSING:
            raise AttributeError(f"module 'gi.repository.Adw' has no attribute {name!r}")
        return getattr(Adw, name)


# -- M26: the version costs a property, not a round trip --------------------


def test_the_version_is_read_without_listing_every_add_on(prefs: Prefs, monkeypatch):
    """The gate reads ``ShellVersion`` off a bare proxy, and connects to nothing.

    ``_connect_shell`` is the shared connection, and building it calls
    ``ShellExtensions.load()``. Nothing in a window's construction may reach it
    any more: the fifteen pages that do not ask for the desktop must not pay
    for one, and the gate must not pay for one at all.
    """
    from gtheme.core import backends
    from gtheme.ego import shelldbus

    asked: list[str] = []

    class BareProxy:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            asked.append("proxy")

        def shell_version(self) -> str:
            return "50.4"

    def never() -> Any:
        raise AssertionError("the shared connection was built before the window was shown")

    monkeypatch.setattr(backends, "has_session_bus", lambda: True)
    monkeypatch.setattr(shelldbus, "GDBusShellProxy", BareProxy)
    monkeypatch.setattr(window_module, "_connect_shell", never)
    # A page that does not want the desktop, so nothing else asks for it either.
    prefs.set("window/last-page", "colors")

    built = Window(prefs, mirror=False)

    assert asked == ["proxy"], "the version should cost one bare proxy and nothing else"
    assert built.verdict.ok
    assert built._shell is None
    assert built._shell_asked is False, "the shared connection must still be unbuilt"


def test_the_page_a_fresh_machine_opens_first_lists_nothing_either(
    prefs: Prefs, monkeypatch
):
    """The same promise, on the page the window actually opens (M26, residual).

    The test above presets ``window/last-page``, so it only ever proved the
    *gate* half. On a machine with no remembered page the first page is Home,
    whose add-on line asked the desktop while it was being built — two blocking
    ``ListExtensions`` round trips inside ``Window(...)``, before ``present()``.
    """
    from gtheme.core import backends
    from gtheme.ego import shelldbus

    calls: list[str] = []

    class CountingProxy:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            calls.append("proxy")

        def shell_version(self) -> str:
            return "50.4"

        def list_extensions(self) -> dict[str, Any]:
            calls.append("ListExtensions")
            return {}

        def connect_state_changed(self, _handler: Any) -> int:
            return 1

        def disconnect_state_changed(self, _token: int) -> None:
            pass

    def never() -> Any:
        raise AssertionError("the shared connection was built before the window was shown")

    monkeypatch.setattr(backends, "has_session_bus", lambda: True)
    monkeypatch.setattr(shelldbus, "GDBusShellProxy", CountingProxy)
    monkeypatch.setattr(window_module, "_connect_shell", never)

    built = Window(prefs, mirror=False)

    assert built._first_page() == "home", "the finding is about the default first page"
    assert "ListExtensions" not in calls, (
        "listing the add-ons must not happen while the window is being built"
    )
    assert calls == ["proxy"], "the version's bare proxy, and nothing else"
    assert built._shell_asked is False, "the shared connection must still be unbuilt"


def test_a_connection_that_already_exists_is_asked_rather_than_a_second_one(
    prefs: Prefs, monkeypatch
):
    from gtheme.ego import shelldbus

    class Loud:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            raise AssertionError("a second proxy was built")

    class Existing:
        def __init__(self) -> None:
            self.all: dict[str, Any] = {}

        @property
        def proxy(self) -> Any:
            return self

        def shell_version(self) -> str:
            return "50.4"

        def close(self) -> None:
            pass

    monkeypatch.setattr(shelldbus, "GDBusShellProxy", Loud)
    built = Window(prefs, shell=Existing(), mirror=False)
    assert built.verdict.ok


def test_a_page_that_does_not_want_the_desktop_does_not_get_one_built_for_it(
    window: Window,
):
    """``_offer`` used to build the connection for every page, wanted or not."""

    def wants_probe(_window: Any, *, probe: Any = None) -> None: ...

    offered = window._offer(wants_probe)
    assert set(offered) == {"probe"}
    assert window._shell_asked is False or window._shell is None


# -- X2: "could not tell" is not "go ahead" ---------------------------------


def test_an_unreadable_version_is_judged_on_the_pieces_the_window_is_made_of():
    # No answer from the desktop, but the widgets the sidebar needs are here.
    assert check_desktop(current_desktop="GNOME", version=None, adw_version=(1, 9)).ok
    assert check_desktop(current_desktop="GNOME", version=None, adw_version=(1, 12)).ok

    # No answer, and the widgets are not here: the polite screen, not a crash.
    too_old = check_desktop(current_desktop="GNOME", version=None, adw_version=(1, 5))
    assert not too_old.ok
    assert too_old.title == COPY["old-desktop-title"]
    assert str(MINIMUM_GNOME) in too_old.body


def test_could_not_tell_says_so_instead_of_saying_too_old():
    verdict = check_desktop(current_desktop="GNOME", version=None, adw_version=None)
    assert not verdict.ok
    assert verdict.title == COPY["unknown-desktop-title"]
    assert verdict.title != COPY["old-desktop-title"]
    # And it does not send anybody looking for an upgrade they may not need.
    assert str(MINIMUM_GNOME) not in verdict.body


def test_a_desktop_that_answers_is_still_believed():
    assert check_desktop(current_desktop="GNOME", version="50.4", adw_version=None).ok
    assert not check_desktop(
        current_desktop="GNOME", version="48.6", adw_version=(1, 9)
    ).ok


def test_the_window_reaches_the_polite_screen_on_an_old_desktop_that_says_nothing(
    prefs: Prefs, monkeypatch
):
    """The crash the old gate's own comment claimed was fixed.

    With libadwaita 1.5 and a desktop that will not say its version, the old
    gate returned "ok" and the window then built ``Adw.Sidebar`` — which is not
    in that libadwaita. The window is built here with no verdict handed in on
    purpose: working the verdict out is the thing under test.
    """
    monkeypatch.setattr(window_module, "Adw", OldLibadwaita())

    built = Window(prefs, ask_desktop=False, mirror=False)

    assert not built.verdict.ok
    assert built._root.get_visible_child_name() == "unsupported"
    assert built.sidebar is None and built.split is None
    assert not built._pages


# -- L14: one durable write, not one per click ------------------------------


def test_walking_the_sidebar_does_not_fsync_once_per_click(prefs: Prefs, monkeypatch):
    built = Window(prefs, ask_desktop=False, mirror=False)
    saves: list[int] = []
    real_save = prefs.save

    def counted() -> None:
        saves.append(1)
        real_save()

    monkeypatch.setattr(prefs, "save", counted)

    for page_id in ("colors", "fonts", "wallpaper", "icons", "looks"):
        built.show_page(page_id)
    assert saves == [], "a page change is not worth a write barrier"
    assert prefs.get("window/last-page") == "looks"

    built._on_close()
    assert len(saves) == 1, "closing writes once, for everything at once"
    assert Prefs(prefs.path).get("window/last-page") == "looks"


# -- X4 / U5: help, and the details a bug report asks for -------------------


def test_the_details_carry_the_version_the_desktop_and_the_log(state_dir: Path, monkeypatch):
    from gtheme.core import applog

    monkeypatch.setattr(window_module, "_bare_shell_version", lambda: "50.4")
    applog.configure(force=True)
    try:
        applog.logger("test").info("a sentence from an earlier run")
        text = window_module.details_text()
    finally:
        applog.shutdown()

    assert __version__ in text
    assert "GNOME 50.4" in text
    assert "a sentence from an earlier run" in text
    assert str(applog.log_file()) in text


def test_a_desktop_that_says_nothing_is_said_to_have_said_nothing(
    state_dir: Path, monkeypatch
):
    monkeypatch.setattr(window_module, "_bare_shell_version", lambda: None)
    text = window_module.details_text()
    assert "no answer" in text
    assert "(no log file yet)" in text or "Log (" in text


def test_the_about_dialog_offers_help_and_the_details(window: Window, monkeypatch):
    monkeypatch.setattr(window_module, "_bare_shell_version", lambda: None)
    dialog = window.about_dialog()
    assert dialog.get_support_url() == window_module.SUPPORT_URL
    assert __version__ in dialog.get_debug_info()
    assert dialog.get_debug_info_filename()


def test_copying_the_details_says_whether_it_worked(window: Window, monkeypatch):
    monkeypatch.setattr(window_module, "_bare_shell_version", lambda: None)
    said: list[str] = []
    monkeypatch.setattr(window, "toast", lambda text, **_k: said.append(text))

    monkeypatch.setattr(window_module, "_to_clipboard", lambda *_a: True)
    text = window.copy_details()
    assert __version__ in text
    assert said == [COPY["details-copied"]]

    monkeypatch.setattr(window_module, "_to_clipboard", lambda *_a: False)
    window.copy_details()
    assert said[-1] == COPY["details-failed"]


def test_the_menu_offers_the_details_and_the_shortcuts(window: Window):
    labels = _menu_labels(window._menu_model())
    assert COPY["menu-details"] in labels
    assert COPY["menu-shortcuts"] in labels
    assert "copy-details" in set(window.list_actions())


# -- U10: a window that fits, and a keyboard that reaches everything --------


def test_a_wanted_size_is_cut_down_to_the_screen_it_will_open_on():
    # 1920x1080 at 200% reports 960x540 in the units a window is measured in.
    assert fit_to_monitor(1200, 900, (960, 540)) == (
        960 - window_module.SCREEN_MARGIN_X,
        540 - window_module.SCREEN_MARGIN_Y,
    )
    # A screen with room to spare changes nothing…
    assert fit_to_monitor(1200, 900, (2560, 1440)) == (1200, 900)
    # …and neither does having no screen to ask about.
    assert fit_to_monitor(1200, 900, None) == (1200, 900)
    # Never below the window's own minimum, and never larger than asked for.
    assert fit_to_monitor(1200, 900, (200, 200)) == (MINIMUM_WIDTH, MINIMUM_HEIGHT)
    assert fit_to_monitor(800, 600, (2560, 1440)) == (800, 600)


def test_the_window_opens_at_a_size_that_fits_the_screen(prefs: Prefs, monkeypatch):
    monkeypatch.setattr(window_module, "monitor_size", lambda *_a: (960, 540))
    built = Window(prefs, ask_desktop=False, mirror=False)
    assert built.get_default_size() == fit_to_monitor(
        DEFAULT_WIDTH, DEFAULT_HEIGHT, (960, 540)
    )
    assert built.get_default_size() != (DEFAULT_WIDTH, DEFAULT_HEIGHT)


def test_a_remembered_size_is_fitted_too(prefs: Prefs, monkeypatch):
    monkeypatch.setattr(window_module, "monitor_size", lambda *_a: (960, 540))
    prefs.set("window/width", 1400, save=False)
    prefs.set("window/height", 900)
    built = Window(prefs, ask_desktop=False, mirror=False)
    assert built.get_default_size() == fit_to_monitor(1400, 900, (960, 540))


def test_there_is_a_list_of_keyboard_shortcuts_on_the_standard_key(window: Window):
    assert "show-help-overlay" in set(window.list_actions())
    overlay = window.get_help_overlay()
    assert isinstance(overlay, Gtk.ShortcutsWindow)


def test_f6_shows_the_list_on_the_left_and_asks_for_focus(window: Window):
    assert "focus-sidebar" in set(window.list_actions())
    window.split.set_show_content(True)
    window.focus_sidebar()
    assert window.split.get_show_content() is False


def test_the_keys_are_bound_when_there_is_an_application(prefs: Prefs):
    app = Adw.Application(application_id="io.github.blyatiful1.GthemeShortcutTest")
    built = Window(prefs, ask_desktop=False, mirror=False, application=app)
    try:
        assert app.get_accels_for_action("win.focus-sidebar") == ["F6"]
        # GTK stores what it parsed, not the spelling it was given: "<primary>"
        # comes back as "<Control>". Compare the keys, not the strings.
        wanted = Gtk.accelerator_parse("<primary>question")[1:]
        assert any(
            Gtk.accelerator_parse(key)[1:] == wanted
            for key in app.get_accels_for_action("win.show-help-overlay")
        )
    finally:
        built.destroy()


# -- E6: the change that did not finish -------------------------------------


def _journal(root: Path, name: str, *, recorded: bool = True) -> Path:
    made = root / f"{window_module.JOURNAL_PREFIX}{name}"
    made.mkdir()
    payload = {"org.gnome.desktop.interface.gtk-theme": {"value": None}} if recorded else {}
    (made / "settings.json").write_text(json.dumps(payload), encoding="utf-8")
    return made


def test_a_journal_the_engine_left_behind_is_what_is_looked_for(tmp_path: Path):
    left = _journal(tmp_path, "aaa")
    _journal(tmp_path, "bbb", recorded=False)
    (tmp_path / "something-else").mkdir()

    found = window_module.unfinished_changes(temp_dir=tmp_path)

    assert found == [str(left)], "only a journal that recorded a change counts"


def test_the_prefix_is_the_one_the_engine_actually_uses():
    """A rename in the engine would turn this notice off in silence."""
    from gtheme.core import transaction

    source = Path(transaction.__file__).read_text(encoding="utf-8")
    assert f'mkdtemp(prefix="{window_module.JOURNAL_PREFIX}")' in source


def test_an_unfinished_change_is_noticed_and_offers_the_way_back(
    prefs: Prefs, tmp_path: Path, monkeypatch
):
    left = _journal(tmp_path, "ccc")
    monkeypatch.setattr(
        window_module, "unfinished_changes", lambda: [str(left)]
    )
    built = Window(prefs, ask_desktop=False, mirror=False)

    dialog = built.unfinished_notice()
    assert dialog is not None
    assert dialog.get_heading() == COPY["unfinished-title"]
    assert [dialog.get_response_label(r) for r in ("dismiss", "restore")] == [
        COPY["unfinished-dismiss"],
        COPY["unfinished-restore"],
    ]

    asked: list[int] = []
    monkeypatch.setattr(built, "undo_last_change", lambda: asked.append(1))
    built._on_unfinished(dialog, "restore", [str(left)])

    assert asked == [1], "the answer goes through the machinery that already exists"
    assert built.unfinished_notice() is None, "and it is not asked a second time"


def test_leaving_it_alone_also_stops_the_asking(prefs: Prefs, tmp_path: Path, monkeypatch):
    left = _journal(tmp_path, "ddd")
    monkeypatch.setattr(window_module, "unfinished_changes", lambda: [str(left)])
    built = Window(prefs, ask_desktop=False, mirror=False)

    dialog = built.unfinished_notice()
    assert dialog is not None
    built._on_unfinished(dialog, "dismiss", [str(left)])
    assert built.unfinished_notice() is None
    # And the answer survives the app being closed and opened again.
    prefs.save()
    again = Window(Prefs(prefs.path), ask_desktop=False, mirror=False)
    assert again.unfinished_notice() is None


def test_nothing_is_said_while_another_gtheme_is_still_changing_things(
    prefs: Prefs, tmp_path: Path, monkeypatch
):
    """A second window opening mid-apply must not announce a crash."""
    from gtheme.core.lock import process_lock

    left = _journal(tmp_path, "eee")
    monkeypatch.setattr(window_module, "unfinished_changes", lambda: [str(left)])
    built = Window(prefs, ask_desktop=False, mirror=False)

    with process_lock():
        assert built.unfinished_notice() is None
    assert built.unfinished_notice() is not None


def test_a_tidy_machine_is_asked_nothing(prefs: Prefs, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(window_module, "unfinished_changes", lambda: [])
    built = Window(prefs, ask_desktop=False, mirror=False)
    assert built.unfinished_notice() is None


def _menu_labels(model: Any) -> list[str]:
    from gi.repository import Gio

    labels: list[str] = []
    for index in range(model.get_n_items()):
        label = model.get_item_attribute_value(index, "label", None)
        if label is not None:
            labels.append(label.get_string())
        for link in ("section", "submenu"):
            child = model.get_item_link(index, link)
            if isinstance(child, Gio.MenuModel):
                labels.extend(_menu_labels(child))
    return labels


def test_the_words_this_window_says_are_plain():
    """The house rule, applied to the sentences this file adds."""
    from gtheme.ui import jargon

    assert jargon.check_all([(f"window.COPY[{k!r}]", v) for k, v in COPY.items()]) == []


def test_the_launch_asks_the_window_about_an_unfinished_change(prefs: Prefs, monkeypatch):
    """E6's wiring: the application asks, once, after the window is on screen."""
    from gi.repository import GLib

    from gtheme import app as app_module

    built = Window(prefs, ask_desktop=False, mirror=False)
    asked: list[int] = []
    monkeypatch.setattr(built, "present_unfinished_notice", lambda: asked.append(1))

    assert app_module._present_unfinished(built) == GLib.SOURCE_REMOVE
    assert asked == [1]


def test_a_notice_that_cannot_be_worked_out_never_costs_the_window(
    prefs: Prefs, monkeypatch
):
    from gi.repository import GLib

    from gtheme import app as app_module

    built = Window(prefs, ask_desktop=False, mirror=False)

    def boom() -> None:
        raise OSError("the temporary directory is not readable")

    monkeypatch.setattr(built, "present_unfinished_notice", boom)
    assert app_module._present_unfinished(built) == GLib.SOURCE_REMOVE
