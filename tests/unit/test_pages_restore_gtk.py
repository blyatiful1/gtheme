"""The Undo & Restore Points page, really constructed.

Marked ``gtk``: real libadwaita widgets. Nothing is presented; saved moments go
to a temporary directory and settings to an in-memory backend, so the desktop
this suite runs on is neither read nor written.
"""

from __future__ import annotations

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for the page modules")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from gtheme.core import restorepoints  # noqa: E402
from gtheme.core.settings_backend import MemoryBackend  # noqa: E402
from gtheme.prefs import Prefs  # noqa: E402
from gtheme.ui.pages import restore  # noqa: E402

pytestmark = pytest.mark.gtk

ACCENT = "gsettings:org.gnome.desktop.interface accent-color"


@pytest.fixture(autouse=True, scope="module")
def _adw():
    if not Gtk.init_check():
        pytest.skip("no display is available for GTK — run under gtk4-broadwayd")
    Adw.init()


class FakeWindow:
    def __init__(self, prefs: Prefs) -> None:
        self.prefs = prefs
        self.toasts: list[str] = []

    def toast(self, text: str) -> None:
        self.toasts.append(text)


@pytest.fixture
def window(config_dir):
    return FakeWindow(Prefs())


@pytest.fixture
def backend():
    settings = MemoryBackend()
    settings.set(ACCENT, "'green'")
    return settings


def _page(window, backend, tmp_path):
    return restore.RestorePage(
        window,
        backend=backend,
        root=tmp_path,
        keys=[ACCENT],
        import_v1=False,
    )


def _row_titles(page: restore.RestorePage) -> list[str]:
    return [row.get_title() for row in page._rows]


def test_an_empty_list_teaches_instead_of_being_blank(window, backend, tmp_path):
    page = _page(window, backend, tmp_path)
    assert _row_titles(page) == [restore.COPY["list-empty-title"]]


def test_saving_adds_a_moment_to_the_list(window, backend, tmp_path):
    page = _page(window, backend, tmp_path)
    page._on_save()
    assert _row_titles(page) == [restore.default_label()]
    assert window.toasts[-1] == restore.COPY["saved"]


def test_forgetting_a_moment_removes_it_from_disk_and_from_the_list(window, backend, tmp_path):
    page = _page(window, backend, tmp_path)
    page._on_save()
    point = page.points()[0]

    page._on_forget(point)

    assert restorepoints.load(point.id, root=tmp_path) is None
    assert _row_titles(page) == [restore.COPY["list-empty-title"]]


def test_going_back_to_a_moment_puts_the_value_back(window, backend, tmp_path):
    page = _page(window, backend, tmp_path)
    page._on_save()
    backend.set(ACCENT, "'purple'")

    page.apply_point(page.points()[0])

    assert backend.get(ACCENT) == "'green'"
    assert window.toasts[-1] == restore.COPY["done"]


def test_the_confirmation_shows_what_would_change_before_it_changes_it(
    window, backend, tmp_path
):
    page = _page(window, backend, tmp_path)
    page._on_save()
    backend.set(ACCENT, "'purple'")

    dialog = page.confirm_apply(page.points()[0])

    assert dialog.get_heading() == restore.COPY["confirm-heading"]
    assert restore.COPY["confirm-body"] in dialog.get_body()
    # Nothing happened yet: a preview that applies is not a preview.
    assert backend.get(ACCENT) == "'purple'"

    dialog.emit("response", "cancel")
    assert backend.get(ACCENT) == "'purple'"

    dialog.emit("response", "apply")
    assert backend.get(ACCENT) == "'green'"


def test_a_moment_that_has_gone_is_reported_rather_than_raised(window, backend, tmp_path):
    page = _page(window, backend, tmp_path)
    page._on_save()
    point = page.points()[0]
    restorepoints.delete(point.id, root=tmp_path)

    result = page.apply_point(point)

    assert result.warnings
    assert window.toasts[-1]


def test_the_before_gtheme_row_is_last_and_is_not_forgettable(window, backend, tmp_path):
    restorepoints.capture(
        [ACCENT],
        label="Before gtheme",
        kind="pristine",
        backend=backend,
        root=tmp_path,
        point_id=restorepoints.PRISTINE_ID,
    )
    page = _page(window, backend, tmp_path)
    page._on_save()

    titles = _row_titles(page)
    assert titles[-1] == restore.COPY["pristine-title"]
    # Two suffixes on an ordinary moment (forget, go back); one on the pristine.
    ordinary, pristine = page._rows[0], page._rows[-1]
    assert _suffix_count(ordinary) == 2
    assert _suffix_count(pristine) == 1


def _suffix_count(row: Adw.ActionRow) -> int:
    return sum(1 for _ in _buttons(row))


def _buttons(row: Adw.ActionRow):
    child = row.get_first_child()
    stack = [child]
    while stack:
        widget = stack.pop()
        if widget is None:
            continue
        if isinstance(widget, Gtk.Button):
            yield widget
        stack.append(widget.get_next_sibling())
        stack.append(widget.get_first_child())


def test_build_is_the_factory_the_manifest_names(window, backend, tmp_path):
    widget = restore.build(window, backend=backend, root=tmp_path, keys=[ACCENT], import_v1=False)
    assert isinstance(widget, Gtk.Widget)
