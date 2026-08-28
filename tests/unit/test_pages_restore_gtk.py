"""The Undo & Restore Points page, really constructed.

Marked ``gtk``: real libadwaita widgets. Nothing is presented; saved moments go
to a temporary directory and settings to an in-memory backend, so the desktop
this suite runs on is neither read nor written.

That last sentence used to be false. ``root=tmp_path`` tells the *page* where
to read and write saved moments, but applying one runs a real
:class:`~gtheme.core.transaction.Transaction`, and the automatic restore point
it takes first resolves :func:`gtheme.core.paths.restore_points_dir` from the
environment — so two tests in this file were writing junk restore points into
the real ``~/.local/state/gtheme/v2``. :func:`_state_root` closes that: one
temporary directory, agreed on by the page argument and by the engine.
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


@pytest.fixture(autouse=True)
def _state_root(tmp_path, monkeypatch):
    """The engine's state root is the same tmp_path the page is handed.

    Without this the page's ``root=`` is only half a seam: the automatic
    restore point a transaction takes lands wherever ``GTHEME_STATE_DIR``
    points, and on a developer's machine that is the real desktop's.
    """
    monkeypatch.setenv("GTHEME_STATE_DIR", str(tmp_path))


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

    point = page.points()[0]
    page.apply_point(point)

    assert backend.get(ACCENT) == "'green'"
    # U8: the toast names the moment. This assertion used to read
    # ``restore.COPY["done"]`` — the unnamed sentence — and is changed here
    # deliberately, because the requirement was "the toast names the moment"
    # and the old wording was what failed it, not what proved it.
    assert window.toasts[-1] == restore.done_sentence(point)
    assert point.label in window.toasts[-1]


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


def test_going_back_narrates_into_the_shared_progress_dialog(window, backend, tmp_path):
    """The seam Wave 2 left empty.

    The engine narrates each step of going back; the runner owns the only
    surface in the app that can say so. ``_progress`` is the one line joining
    them, and it used to be a docstring.
    """
    from gtheme.ui.applyrunner import ApplyRunner

    window.runner = ApplyRunner(threaded=False)
    page = _page(window, backend, tmp_path)
    page._on_save()
    backend.set(ACCENT, "'purple'")

    said: list[str] = []
    original = page._progress

    def watching(*args):
        said.append(next((a for a in args if isinstance(a, str) and a), ""))
        original(*args)

    page._progress = watching
    point = page.points()[0]
    page.start_apply(point)

    assert backend.get(ACCENT) == "'green'"
    assert any(said), "the engine narrated nothing at all"
    # U8, through the runner's own callback rather than the inline branch.
    assert window.toasts[-1] == restore.done_sentence(point)


def test_going_back_without_a_window_still_works(window, backend, tmp_path):
    """A page with no runner narrates to nobody, which is the right answer."""
    page = _page(window, backend, tmp_path)
    page._on_save()
    backend.set(ACCENT, "'purple'")
    page.start_apply(page.points()[0])
    assert backend.get(ACCENT) == "'green'"


def test_a_change_tells_the_rest_of_the_app_rather_than_just_this_page(
    window, backend, tmp_path
):
    told = []
    window.after_change = lambda: told.append("told")
    page = _page(window, backend, tmp_path)
    page._on_save()
    assert told == ["told"]


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


# -- regression: the confirmed review finding on this page ------------------


def test_undo_the_last_change_goes_through_the_shared_runner(window, backend, tmp_path):
    """Pins restore.py:478 — the Undo button ran the restore on the main loop.

    ``_on_undo`` called the module-level ``undo_last_change`` inline, so the
    whole restore — file copies plus several dozen settings writes — happened
    in the click handler while the window could not repaint. Its neighbour
    ``start_apply`` runs the identical work on the shared runner and says in
    its own docstring why. Both do now, and this checks the work still lands.
    """
    from gtheme.ui.applyrunner import ApplyRunner

    class Recording(ApplyRunner):
        def __init__(self) -> None:
            super().__init__(None, threaded=False)
            self.headings: list[str] = []

        def run(self, work, *, heading, starting, on_done, on_failed=None):
            self.headings.append(heading)
            return super().run(
                work, heading=heading, starting=starting, on_done=on_done, on_failed=on_failed
            )

    window.runner = Recording()
    page = _page(window, backend, tmp_path)
    page._on_save()
    backend.set(ACCENT, "'purple'")
    # Read before the undo runs: going back takes a restore point of its own,
    # so the newest moment afterwards is not the one that was applied.
    newest = page.points()[0]

    page._on_undo()

    # Two headings, not one: "Save how it looks now" goes through the runner
    # too now (review-report M10), and this test's save is what set the moment
    # up. The undo is the second, and it is the one being pinned here.
    assert window.runner.headings == [
        restore.COPY["save-title"],
        restore.COPY["working-heading"],
    ]
    assert backend.get(ACCENT) == "'green'"
    # U8: "undo the last change" ends by saying which moment it landed on, the
    # same way pressing "Go back to this" on that moment does.
    assert window.toasts[-1] == restore.done_sentence(newest)


def test_undo_with_nothing_saved_still_says_so_on_the_runner(window, backend, tmp_path):
    from gtheme.ui.applyrunner import ApplyRunner

    window.runner = ApplyRunner(threaded=False)
    page = _page(window, backend, tmp_path)
    page._on_undo()
    assert window.toasts[-1] == restore.COPY["undo-nothing"]


def test_undo_without_a_runner_still_undoes(window, backend, tmp_path):
    page = _page(window, backend, tmp_path)
    page._on_save()
    backend.set(ACCENT, "'purple'")
    page._on_undo()
    assert backend.get(ACCENT) == "'green'"
