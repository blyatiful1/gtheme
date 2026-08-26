"""The Home page, really constructed.

Marked ``gtk``: real libadwaita widgets are built. Nothing is presented, so
nothing appears on the developer's screen, and every value is read from an
in-memory settings backend, so the live desktop is neither read nor written.

The undo test needs one thing more than that. ``root=tmp_path`` aims the
*page* at a temporary directory, but undoing runs a real
:class:`~gtheme.core.transaction.Transaction`, whose automatic restore point,
ownership ledger and baseline all resolve from ``GTHEME_STATE_DIR`` — so that
test was writing into the real ``~/.local/state/gtheme/v2``.
:func:`_state_root` points the engine at the same directory the page uses.
"""

from __future__ import annotations

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for the page modules")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from gtheme.core.settings_backend import MemoryBackend  # noqa: E402
from gtheme.prefs import Prefs  # noqa: E402
from gtheme.ui.applyrunner import ApplyRunner  # noqa: E402
from gtheme.ui.pages import home  # noqa: E402
from gtheme.ui.pages import restore as restore_page  # noqa: E402

pytestmark = pytest.mark.gtk


@pytest.fixture(autouse=True, scope="module")
def _adw():
    if not Gtk.init_check():
        pytest.skip("no display is available for GTK — run under gtk4-broadwayd")
    Adw.init()


class FakeWindow:
    """What a page is allowed to expect of the window: three attributes."""

    def __init__(self, prefs: Prefs) -> None:
        self.prefs = prefs
        self.toasts: list[str] = []
        self.pages: list[str] = []

    def toast(self, text: str) -> None:
        self.toasts.append(text)

    def show_page(self, page_id: str) -> None:
        self.pages.append(page_id)


@pytest.fixture
def window(config_dir):
    return FakeWindow(Prefs())


@pytest.fixture
def backend():
    settings = MemoryBackend()
    settings.set("gsettings:org.gnome.desktop.interface color-scheme", "'prefer-dark'")
    settings.set("gsettings:org.gnome.desktop.interface accent-color", "'green'")
    settings.set("gsettings:org.gnome.desktop.interface icon-theme", "'Papirus-Dark'")
    return settings


@pytest.fixture(autouse=True)
def _state_root(tmp_path, monkeypatch):
    """The engine's state root is the same tmp_path the page is handed."""
    monkeypatch.setenv("GTHEME_STATE_DIR", str(tmp_path))


def _page(window, backend, tmp_path, **kwargs):
    return home.HomePage(
        window, backend=backend, root=tmp_path, thumbnails=False, shell=None, **kwargs
    )


def _subtitles(page: home.HomePage) -> dict[str, str]:
    return {name: row.get_subtitle() for name, row in page._rows.items()}


def test_the_card_reads_the_desktop_back_in_words(window, backend, tmp_path):
    page = _page(window, backend, tmp_path)
    shown = _subtitles(page)
    assert shown["light-or-dark"] == "Dark"
    assert shown["highlight"] == "Green"
    assert shown["icons"] == "Papirus-Dark"


def test_no_row_of_the_card_is_ever_blank(window, backend, tmp_path):
    """A blank row reads as a broken app; "not set" and "can't check" are answers."""
    page = _page(window, backend, tmp_path)
    for name, subtitle in _subtitles(page).items():
        assert subtitle, f"{name} showed nothing at all"


def test_the_add_on_row_is_honest_when_the_desktop_cannot_be_asked(window, backend, tmp_path):
    class Silent:
        def load(self):
            raise RuntimeError("no desktop to ask")

    page = home.HomePage(
        window, backend=backend, root=tmp_path, thumbnails=False, shell=Silent()
    )
    assert _subtitles(page)["addons"] == home.COPY["addons-unavailable"]


def test_the_first_visit_explainer_shows_once_and_stays_dismissed(window, backend, tmp_path):
    assert window.prefs.should_show_banner(home.BANNER_ID)
    _page(window, backend, tmp_path)
    window.prefs.mark_banner_seen(home.BANNER_ID)
    assert not window.prefs.should_show_banner(home.BANNER_ID)


def test_the_links_go_to_the_pages_that_own_each_thing(window, backend, tmp_path):
    page = _page(window, backend, tmp_path)
    page.open_page("colors")
    assert window.pages == ["colors"]


def test_saving_a_moment_really_saves_one_and_says_so(window, backend, tmp_path):
    page = _page(window, backend, tmp_path)
    point = page.save_restore_point()
    assert point is not None
    assert (tmp_path / point.id / "restore-point.json").is_file()
    assert window.toasts and "Saved" in window.toasts[-1]


def test_undo_with_nothing_saved_says_there_is_nothing_to_undo(window, backend, tmp_path):
    page = _page(window, backend, tmp_path)
    assert page.undo_last_change() is None
    assert window.toasts[-1].startswith("Nothing has changed yet")


def test_undo_puts_the_value_back_and_the_card_follows(window, backend, tmp_path):
    key = "gsettings:org.gnome.desktop.interface accent-color"
    page = _page(window, backend, tmp_path)
    page.save_restore_point()
    backend.set(key, "'purple'")
    page.refresh()
    assert _subtitles(page)["highlight"] == "Purple"

    page.undo_last_change()

    assert backend.get(key) == "'green'"
    assert _subtitles(page)["highlight"] == "Green"


def test_the_header_button_runs_the_same_undo(window, backend, tmp_path):
    page = _page(window, backend, tmp_path)
    button = home.header_button(page)
    button.emit("clicked")
    assert window.toasts[-1].startswith("Nothing has changed yet")


def test_build_is_the_factory_the_manifest_names(window, backend, tmp_path):
    widget = home.build(window, backend=backend, root=tmp_path, thumbnails=False)
    assert isinstance(widget, Gtk.Widget)


def test_the_card_says_which_look_you_are_using(window, backend, tmp_path):
    """Named the way the person picking it saw it named — its title, not its
    folder name."""
    from gtheme.core.ledger import set_current_look

    set_current_look("magma", label="MAGMA — Molten Glass")
    page = _page(window, backend, tmp_path)
    assert _subtitles(page)["look"] == "MAGMA — Molten Glass"


def test_the_card_says_so_when_there_is_no_look_rather_than_going_blank(
    window, backend, tmp_path
):
    """A desktop changed one thing at a time has no Look, and that is a state."""
    page = _page(window, backend, tmp_path)
    assert _subtitles(page)["look"] == home.COPY["no-look"]


# -- regression: the confirmed review finding on this page ------------------


class RecordingRunner(ApplyRunner):
    """A real runner that also writes down what it was asked to run.

    ``threaded=False`` so the work happens inline and the result is there when
    ``run`` returns — the runner's own documented shape for a test.
    """

    def __init__(self) -> None:
        super().__init__(None, threaded=False)
        self.headings: list[str] = []

    def run(self, work, *, heading, starting, on_done, on_failed=None):
        self.headings.append(heading)
        return super().run(
            work, heading=heading, starting=starting, on_done=on_done, on_failed=on_failed
        )


def test_home_save_and_undo_go_through_the_shared_runner(window, backend, tmp_path):
    """Pins home.py:536 — Home's Save/Undo ran the engine on the main loop.

    ``HomePage.save_restore_point`` and ``HomePage.undo_last_change`` back both
    the two rows under the card and the header-bar Undo button, and both called
    the engine straight from the click handler — the exact pattern
    ``ui.applyrunner`` exists to remove, while Ctrl+Z ran the identical work on
    the runner with a narrated dialog. Both now go through the window's runner.
    """
    key = "gsettings:org.gnome.desktop.interface accent-color"
    window.runner = RecordingRunner()
    page = _page(window, backend, tmp_path)

    page.save_restore_point()
    assert window.runner.headings == [restore_page.COPY["save-title"]]

    backend.set(key, "'purple'")
    page.undo_last_change()

    assert window.runner.headings[-1] == restore_page.COPY["working-heading"]
    assert backend.get(key) == "'green'", "the undo itself must still work"
    assert window.toasts[-1] == restore_page.COPY["done"]


def test_the_header_undo_button_uses_the_runner_too(window, backend, tmp_path):
    """The header button is the most prominent undo in the app; same path."""
    window.runner = RecordingRunner()
    page = _page(window, backend, tmp_path)
    page.save_restore_point()
    window.runner.headings.clear()

    home.header_button(page).emit("clicked")

    assert window.runner.headings == [restore_page.COPY["working-heading"]]


def test_a_page_with_no_runner_still_saves_and_undoes_inline(window, backend, tmp_path):
    """No window, no runner, no thread — and the work still happens."""
    key = "gsettings:org.gnome.desktop.interface accent-color"
    page = _page(window, backend, tmp_path)
    assert page.save_restore_point() is not None
    backend.set(key, "'purple'")
    page.undo_last_change()
    assert backend.get(key) == "'green'"
