"""The window: what it owns, what it lends, and what it refuses to open.

Wave 3's whole job was turning fifteen pages written against a duck-typed
``window`` into one application. These are the properties that turned out to
matter, each of them written down because getting it wrong is silent:

* **one probe, one desktop connection.** Fifteen probes means fifteen scans of
  every settings description on the machine. Two desktop connections means the
  Add-ons page and the Home page can disagree about what is switched on.
* **the borrower does not close what it borrowed.** The Add-ons page used to
  close the connection when it was torn down; when the window started lending
  one, that became "opening and closing Add-ons breaks the Home page".
* **a factory gets only what it asked for.** The pages were written in
  parallel and their factories genuinely differ. The window offers; the
  factory's own signature decides.
* **the wrong desktop gets a screen, not a broken app.** A dismissible dialog
  would leave a working-looking window behind that cannot work.

Everything here runs with the window's own preferences file pointed at a
temporary directory and with ``ask_desktop=False``, so no test in this file
touches the desktop it is running on.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.gtk

from gi.repository import Adw, Gtk  # noqa: E402

from gtheme import window as window_module  # noqa: E402
from gtheme.prefs import Prefs  # noqa: E402
from gtheme.ui import registry  # noqa: E402
from gtheme.window import COPY, MINIMUM_GNOME, Window, check_desktop  # noqa: E402


@pytest.fixture
def prefs(tmp_path: Path) -> Prefs:
    return Prefs(tmp_path / "prefs.json")


@pytest.fixture
def window(prefs: Prefs) -> Window:
    """A real window that has never heard of the desktop it is running on."""
    return Window(prefs, ask_desktop=False, mirror=False)


# -- what it is ------------------------------------------------------------


def test_the_sidebar_is_the_manifest(window: Window):
    assert [page.id for page in window._order] == list(registry.page_ids())
    assert len(window._order) == 15


def test_it_opens_on_a_page(window: Window):
    assert window.content_page.get_title() == registry.get("home").title
    assert isinstance(window.content_view.get_content(), Gtk.Widget)


def test_every_page_in_the_manifest_can_be_opened(window: Window):
    """The one test that would have caught any page failing to build."""
    broken: list[str] = []
    for page_id in registry.page_ids():
        window.show_page(page_id)
        widget = window._pages[page_id]
        description = getattr(widget, "get_description", lambda: "")()
        if isinstance(description, str) and COPY["page-broken"] in description:
            broken.append(f"{page_id}: {description}")
    assert broken == [], "\n".join(broken)


def test_there_is_exactly_one_probe_and_the_pages_find_it(window: Window):
    from gtheme.ui.pages import _style_common

    window.show_page("colors")
    window.show_page("fonts")
    assert _style_common.get_probe(window) is window.schema_probe


# -- what a factory is offered ---------------------------------------------


def test_a_factory_is_given_only_what_it_names(window: Window):
    def wants_probe(_window: Any, *, probe: Any = None) -> None: ...

    def wants_nothing(_window: Any) -> None: ...

    def wants_both(_window: Any, *, probe: Any = None, shell: Any = None) -> None: ...

    assert window._offer(wants_probe) == {"probe": window.schema_probe}
    assert window._offer(wants_nothing) == {}
    assert set(window._offer(wants_both)) == {"probe", "shell"}


def test_every_factory_in_the_manifest_takes_what_it_is_offered(window: Window):
    """Nothing in the manifest may name a keyword the window cannot supply.

    A factory that grew a required argument nobody hands it would fail at the
    moment somebody clicked its sidebar entry, which is the worst possible
    moment to find out.
    """
    import inspect

    problems = []
    for page in registry.MANIFEST:
        factory = registry.load_factory(page)
        parameters = list(inspect.signature(factory).parameters.values())
        required = [
            parameter.name
            for parameter in parameters[1:]
            if parameter.default is inspect.Parameter.empty
            and parameter.kind
            in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        ]
        if required:
            problems.append(f"{page.id}: needs {required}, which the window does not offer")
    assert problems == [], "\n".join(problems)


# -- the shared desktop connection -----------------------------------------


class FakeShell:
    def __init__(self) -> None:
        self.closed = 0
        self.listeners: list[Any] = []
        self.all: dict[str, Any] = {}

    def close(self) -> None:
        self.closed += 1

    def connect(self, listener: Any) -> None:
        self.listeners.append(listener)

    def disconnect(self, listener: Any) -> bool:
        if listener in self.listeners:
            self.listeners.remove(listener)
            return True
        return False

    def knows(self, _uuid: str) -> bool:
        return False

    def load(self) -> dict[str, Any]:
        return {}

    @property
    def proxy(self) -> Any:
        return self

    def shell_version(self) -> str:
        return "50.4"


def test_the_window_never_asks_the_desktop_when_told_not_to(window: Window):
    assert window.shell is None


def test_a_borrowed_connection_is_not_closed_by_the_page_that_borrowed_it(prefs: Prefs):
    """The Wave-2 lead, closed.

    ``AddonsPage.teardown`` closed the connection unconditionally. Once the
    window started lending one to both the Add-ons page and the Home page,
    that turned into "opening the Add-ons page once and leaving it breaks the
    add-on line on Home".
    """
    from gtheme.ui.pages import addons

    shell = FakeShell()
    page = addons.build(None, shell=shell)
    page.teardown()

    assert shell.closed == 0, "a borrowed connection was closed by the borrower"
    assert shell.listeners == [], "the borrower left its own callback behind"


def test_a_page_that_opened_its_own_connection_still_closes_it():
    from gtheme.ui.pages import addons

    shell = FakeShell()
    page = addons.AddonsPage(None, shell=shell, panels=[])
    page.teardown()
    assert shell.closed == 1


def test_closing_the_window_lets_go_of_the_desktop(prefs: Prefs):
    shell = FakeShell()
    window = Window(prefs, shell=shell, mirror=False)
    window.teardown()
    # Handed in, so the window is not its owner and must not close it.
    assert shell.closed == 0

    window = Window(prefs, ask_desktop=False, mirror=False)
    window._shell = shell
    window._shell_is_ours = True
    window.teardown()
    assert shell.closed == 1


# -- toasts, undo and refreshing -------------------------------------------


def test_a_toast_with_a_way_back_carries_the_button(window: Window):
    plain = window.toast("Something happened.")
    assert plain.get_button_label() in (None, "")

    undoable = window.toast("Something happened.", undo_point="2026-08-25T12-00-00")
    assert undoable.get_button_label() == COPY["undo"]


def test_after_a_change_everything_on_screen_re_reads_itself(window: Window, monkeypatch):
    seen: list[str] = []

    class Noticing:
        page_id = "colors"

        def run_notices(self) -> None:
            seen.append("notices")

    window.register_page_shell(Noticing())
    monkeypatch.setattr(window.rows, "refresh_all", lambda: seen.append("rows") or 0)
    monkeypatch.setattr(window, "rebuild_search_index", lambda: seen.append("search"))

    window.after_change()
    assert seen == ["rows", "notices", "search"]


def test_a_page_shell_that_went_away_is_not_asked_again(window: Window):
    class Noticing:
        page_id = "colors"

        def run_notices(self) -> None:
            raise AssertionError("this page is gone")

    shell = Noticing()
    window.register_page_shell(shell)
    window.unregister_page_shell(shell)
    window.after_change()


def test_rebuilding_the_search_index_keeps_the_object_ctrl_f_was_wired_to(window: Window):
    """Handing out a new index would leave the keyboard shortcut on the old one."""
    before = window.search_index()
    after = window.rebuild_search_index()
    assert after is before
    assert len(after) > 100


def test_search_lands_on_a_page_and_asks_for_the_row(window: Window, monkeypatch):
    landed: list[tuple[str, str | None]] = []
    monkeypatch.setattr(window, "show_page", lambda page_id: landed.append((page_id, None)))
    window.go_to("nightlight")
    assert landed == [("nightlight", None)]


# -- the desktop this is not for -------------------------------------------


def test_another_desktop_gets_a_screen_of_its_own(prefs: Prefs):
    verdict = check_desktop(current_desktop="KDE")
    assert not verdict.ok
    assert verdict.title == COPY["wrong-desktop-title"]

    window = Window(prefs, ask_desktop=False, mirror=False, verdict=verdict)
    assert window._root.get_visible_child_name() == "unsupported"
    # And nothing behind it pretending to work.
    assert not window._pages


def test_a_desktop_that_is_too_old_says_which_one_it_needs():
    verdict = check_desktop(current_desktop="GNOME", version=str(MINIMUM_GNOME - 1))
    assert not verdict.ok
    assert str(MINIMUM_GNOME) in verdict.body


def test_a_desktop_that_will_not_say_its_version_is_not_refused():
    """No answer is an ordinary state, not a wrong one."""
    assert check_desktop(current_desktop="GNOME", version=None).ok
    assert check_desktop(current_desktop="", version=None).ok
    assert check_desktop(current_desktop="ubuntu:GNOME", version="50.4").ok


def test_the_ordinary_desktop_gets_the_app(window: Window):
    assert window.verdict.ok
    assert window._root.get_visible_child_name() == "app"


# -- window state ----------------------------------------------------------


def test_the_window_remembers_its_size_and_the_page_you_were_on(prefs: Prefs):
    window = Window(prefs, ask_desktop=False, mirror=False)
    window.show_page("wallpaper")
    prefs.set("window/width", 1400)
    prefs.set("window/height", 900)
    prefs.save()

    again = Window(Prefs(prefs.path), ask_desktop=False, mirror=False)
    assert again.content_page.get_title() == registry.get("wallpaper").title
    assert again.get_default_size() == (1400, 900)


def test_a_remembered_page_that_no_longer_exists_is_ignored(prefs: Prefs):
    prefs.set("window/last-page", "a-page-from-a-future-version")
    window = Window(prefs, ask_desktop=False, mirror=False)
    assert window.content_page.get_title() == registry.get("home").title


# -- the menu and the about dialog -----------------------------------------


def test_the_main_menu_offers_the_introduction_again(window: Window):
    from gtheme.ui import onboarding

    model = window._menu_model()
    labels = _menu_labels(model)
    assert onboarding.MENU_LABEL in labels
    assert COPY["menu-about"] in labels
    assert COPY["menu-search"] in labels


def test_the_shortcuts_are_all_reachable_without_a_keyboard(window: Window):
    """Every key this window binds is also a thing you can click."""
    actions = set(window.list_actions())
    assert {"search", "undo", "onboarding"} <= actions
    labels = _menu_labels(window._menu_model())
    assert COPY["menu-undo"] in labels


def test_the_about_dialog_can_be_built(window: Window):
    dialog = window_module._about_from_appdata()
    assert dialog is None or isinstance(dialog, Adw.AboutDialog)


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
