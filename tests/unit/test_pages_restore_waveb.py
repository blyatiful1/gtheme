"""Undo & Restore Points, after the audit: what it saves, and what it admits.

Marked ``gtk``: the page is really built. Nothing is presented — the tests
drive the page's own methods and the dialogs it returns — so running this
suite puts nothing on the screen of whoever runs it. Saved moments go to a
temporary directory, settings to an in-memory backend, and ``GTHEME_STATE_DIR``
points at the same temporary directory as the page's ``root``, so the engine's
own ledger and baseline cannot reach the desktop this is running on.

Each test below names the review finding it pins, and each one fails on the
code as it was before this wave:

* **H2** — both failure handlers threw the error away and toasted "Nothing was
  changed. Your desktop is exactly as it was." over a desktop nobody had
  checked.
* **L1** — ``RestoreResult`` carries ``rolled_back`` and the page ignored it.
* **M10** — "Save how it looks now" read five hundred settings in the click
  handler, two lines below an Undo button that does not.
* **L7** — the no-runner branch reported twice.
* **U8** — the header button and Ctrl+Z applied the newest moment with no
  confirmation and no preview; this is the dialog they go through now.
* **H11** — a hand-saved moment recorded no files at all.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for the page modules")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from gtheme.core import ledger, restorepoints  # noqa: E402
from gtheme.core.settings_backend import MemoryBackend  # noqa: E402
from gtheme.core.transaction import TransactionError  # noqa: E402
from gtheme.prefs import Prefs  # noqa: E402
from gtheme.ui import jargon, onboarding  # noqa: E402
from gtheme.ui.applyrunner import ApplyRunner  # noqa: E402
from gtheme.ui.pages import restore  # noqa: E402

pytestmark = pytest.mark.gtk

ACCENT = "gsettings:org.gnome.desktop.interface accent-color"


@pytest.fixture(autouse=True, scope="module")
def _adw():
    if not Gtk.init_check():
        pytest.skip("no display is available for GTK — run under gtk4-broadwayd")
    Adw.init()


class Recording(ApplyRunner):
    """The window's runner, remembering what it was asked to call things."""

    def __init__(self) -> None:
        super().__init__(None, threaded=False)
        self.headings: list[str] = []

    def run(self, work, *, heading, starting, on_done, on_failed=None):
        self.headings.append(heading)
        return super().run(
            work, heading=heading, starting=starting, on_done=on_done, on_failed=on_failed
        )


class FakeWindow:
    def __init__(self, prefs: Prefs | None = None) -> None:
        self.prefs = prefs
        self.toasts: list[str] = []
        self.changes = 0

    def toast(self, text: str) -> None:
        self.toasts.append(text)

    def after_change(self) -> None:
        self.changes += 1


@pytest.fixture
def window() -> FakeWindow:
    return FakeWindow()


@pytest.fixture
def backend() -> MemoryBackend:
    settings = MemoryBackend()
    settings.set(ACCENT, "'green'")
    return settings


@pytest.fixture(autouse=True)
def _state_root(tmp_path, monkeypatch):
    """The engine's state root is the same tmp_path the page is handed."""
    monkeypatch.setenv("GTHEME_STATE_DIR", str(tmp_path))


def _page(window: FakeWindow, backend: MemoryBackend, tmp_path) -> restore.RestorePage:
    return restore.RestorePage(
        window, backend=backend, root=tmp_path, keys=[ACCENT], import_v1=False
    )


# -- H2: the two sentences, and which one is honest -------------------------


def _exploding(error: Exception):
    def raise_it(*_args: Any, **_kwargs: Any):
        raise error

    return raise_it


def test_a_half_written_undo_is_never_reported_as_nothing_was_changed(
    window, backend, tmp_path
):
    """Pins restore.py:572 — ``on_failed`` discarded the error entirely.

    Both runner handlers on this page were ``lambda _error: toast(COPY["failed"])``,
    so the one failure that really can leave a half-restored desktop — the
    engine raising with ``rolled_back=False`` — was announced as "Nothing was
    changed. Your desktop is exactly as it was." (review-report H2).
    """
    window.runner = Recording()
    page = _page(window, backend, tmp_path)
    page._on_save()
    page.apply_point = _exploding(
        TransactionError("the settings store went away", rolled_back=False)
    )

    page.start_apply(page.points()[0])

    said = window.toasts[-1]
    assert "Some of it may have been changed anyway." in said
    assert "Nothing was changed" not in said
    assert "The settings store went away." in said, "the reason is carried, not dropped"


def test_a_failure_the_engine_did_roll_back_still_says_so(window, backend, tmp_path):
    """The reassuring sentence is still said when it is true."""
    window.runner = Recording()
    page = _page(window, backend, tmp_path)
    page._on_save()
    page.apply_point = _exploding(TransactionError("the lock was busy", rolled_back=True))

    page.start_apply(page.points()[0])

    said = window.toasts[-1]
    assert "Nothing was changed. Your desktop is exactly as it was." in said
    assert "may have been changed anyway" not in said


def test_an_unknown_failure_is_an_unknown_desktop(window, backend, tmp_path):
    """An error that cannot say whether it rolled back does not get the benefit."""
    window.runner = Recording()
    page = _page(window, backend, tmp_path)
    page._on_save()
    page.apply_point = _exploding(OSError("no room on the disk"))

    page.start_apply(page.points()[0])

    assert "Some of it may have been changed anyway." in window.toasts[-1]


def test_undoing_the_last_change_says_the_same_two_sentences(window, backend, tmp_path):
    """The Undo row's handler had the identical defect, two lines apart."""
    window.runner = Recording()
    page = _page(window, backend, tmp_path)
    page._on_save()
    page._undo_now = _exploding(TransactionError("half of it landed", rolled_back=False))

    page._on_undo()

    assert "Some of it may have been changed anyway." in window.toasts[-1]


# -- L1: the engine's own answer, carried to the page -----------------------


def test_a_restore_that_did_not_roll_back_is_reported_as_such(window, backend, tmp_path):
    """Pins restore.py:626 — ``_report`` ignored ``RestoreResult.rolled_back``.

    Wave A gave the result the field (review-report L1); this is the page
    branching on it. A restore that failed with part of the moment written is
    the one place in this app where the reassuring sentence would do the most
    damage.
    """
    page = _page(window, backend, tmp_path)
    half = restorepoints.RestoreResult(
        warnings=["one file could not be put back"], rolled_back=False
    )

    page._report(half)

    assert "Some of it may have been changed anyway." in window.toasts[-1]
    assert "One file could not be put back." in window.toasts[-1]


def test_a_restore_that_did_roll_back_is_reported_as_such(window, backend, tmp_path):
    page = _page(window, backend, tmp_path)
    clean = restorepoints.RestoreResult(warnings=["that saved moment is no longer there"])

    page._report(clean)

    assert "That saved moment is no longer there." in window.toasts[-1]
    assert "Nothing was changed. Your desktop is exactly as it was." in window.toasts[-1]


# -- M10: saving is slow work, and slow work goes on the runner -------------


def test_saving_a_moment_goes_through_the_shared_runner(window, backend, tmp_path):
    """Pins restore.py:467 — ``_on_save`` read ~515 settings in the click handler.

    Its neighbour ``_on_undo`` uses the runner and says in its own docstring
    why; the identical button on the Home page has always used it
    (review-report M10).
    """
    window.runner = Recording()
    page = _page(window, backend, tmp_path)

    page._on_save()

    assert window.runner.headings == [restore.COPY["save-title"]]
    assert window.toasts[-1] == restore.COPY["saved"]
    assert page.points(), "the moment really was saved"


def test_saving_without_a_runner_still_saves_and_still_reports(window, backend, tmp_path):
    page = _page(window, backend, tmp_path)
    page._on_save()
    assert page.points()
    assert window.toasts == [restore.COPY["saved"]]


def test_a_save_that_fails_says_so_in_words_about_the_desktop(window, backend, tmp_path):
    window.runner = Recording()
    page = _page(window, backend, tmp_path)
    page._save_now = _exploding(OSError(28, "No space left on device"))

    page._on_save()

    said = window.toasts[-1]
    assert said.startswith(restore.COPY["save-failed"])
    assert "No space left on device." in said


def test_the_introduction_saves_its_first_moment_on_the_runner(window, backend, tmp_path):
    """The same finding on the first-run introduction (review-report M10)."""
    window.runner = Recording()
    saved: list[Any] = []
    dialog = onboarding.OnboardingDialog(
        window,
        on_save=lambda: saved.append(
            restore.create_restore_point(backend=backend, root=tmp_path, keys=[ACCENT])
        ),
    )

    dialog.save_first_restore_point()

    assert window.runner.headings == [restore.COPY["save-title"]]
    assert saved, "the moment really was saved"
    assert dialog.save_status.get_label() == onboarding.SAVED_LABEL
    assert not dialog.save_button.get_sensitive()


def test_the_introduction_without_a_window_still_saves_inline(backend, tmp_path):
    dialog = onboarding.OnboardingDialog(
        None,
        on_save=lambda: restore.create_restore_point(
            backend=backend, root=tmp_path, keys=[ACCENT]
        ),
    )
    assert dialog.save_first_restore_point() is not None


# -- L7: one change, one report ---------------------------------------------


def test_going_back_without_a_runner_reports_exactly_once(window, backend, tmp_path):
    """Pins restore.py:565 — the no-runner branch toasted and refreshed twice.

    ``apply_point`` reports for itself unless told not to, and the branch let
    it and then reported again: two toasts, and two ``after_change()`` cascades
    through every page in the window (review-report L7).
    """
    page = _page(window, backend, tmp_path)
    page._on_save()
    backend.set(ACCENT, "'purple'")
    window.toasts.clear()
    before = window.changes

    page.start_apply(page.points()[0])

    assert backend.get(ACCENT) == "'green'"
    assert window.toasts == [restore.COPY["done"]]
    assert window.changes - before == 1


# -- U8: one way back, and it asks first ------------------------------------


def test_the_header_undo_asks_before_it_undoes_and_names_the_moment(
    window, backend, tmp_path
):
    """Pins persona-report §2.8 — Ctrl+Z applied with no confirmation at all.

    The header button and the accel now go through the same confirm-with-plan
    dialog the list's own "Go back to this" button shows, and it says which
    moment it means.
    """
    page = _page(window, backend, tmp_path)
    page._on_save()
    backend.set(ACCENT, "'purple'")

    dialog = page.confirm_undo_last()

    assert isinstance(dialog, Adw.AlertDialog)
    assert restore.default_label() in dialog.get_body(), "the moment is named"
    assert restore.COPY["confirm-body"] in dialog.get_body(), "the plan is shown"
    assert backend.get(ACCENT) == "'purple'", "a preview that applies is not a preview"

    dialog.emit("response", "apply")
    assert backend.get(ACCENT) == "'green'"


def test_the_header_undo_reaches_for_the_newest_moment_and_never_the_pristine_one(
    window, backend, tmp_path
):
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

    dialog = page.confirm_undo_last()

    assert dialog is not None
    assert restore.default_label() in dialog.get_body()
    assert restore.COPY["pristine-title"] not in dialog.get_body()


def test_the_header_undo_with_nothing_saved_says_so_instead_of_asking(
    window, backend, tmp_path
):
    page = _page(window, backend, tmp_path)
    assert page.confirm_undo_last() is None
    assert window.toasts == [restore.COPY["undo-nothing"]]


def test_the_header_undo_can_be_asked_from_a_window_the_page_is_not_in(
    window, backend, tmp_path
):
    """The button lives in the header bar, which the page is not inside.

    A page built a moment ago to answer the header button is not in the widget
    tree yet, so the dialog is given something to be presented on.
    """
    page = _page(window, backend, tmp_path)
    page._on_save()
    parent = Adw.ApplicationWindow()
    try:
        dialog = page.confirm_undo_last(parent)
        assert dialog is not None
    finally:
        parent.destroy()


# -- H11: a hand-saved moment covers files ----------------------------------


def test_a_hand_saved_moment_covers_the_files_the_ledger_claims(
    window, backend, tmp_path
):
    """Pins restore.py:197 — ``create_restore_point`` never passed ``dests``.

    ``capture`` guards its whole file loop with ``if dests:``, so every
    hand-saved moment recorded settings and not one file — while the page's
    own banner says a saved moment is "how your whole desktop looked"
    (review-report H11).
    """
    owned = tmp_path / "style.css"
    owned.write_text("what the look installed", encoding="utf-8")
    ledger.write_entry("magma", [str(owned)], [ACCENT])

    point = restore.create_restore_point(
        "My desktop, today", backend=backend, root=tmp_path, keys=[ACCENT]
    )

    assert str(owned) in point.files, "the claimed file is covered"
    saved = point.files[str(owned)]
    assert isinstance(saved, str) and (point.path / "files" / saved).is_file()


def test_a_claimed_file_that_is_not_there_is_covered_as_absence(
    window, backend, tmp_path
):
    """"There was nothing here" is a state, and restoring it is a removal."""
    missing = tmp_path / "not-here.conf"
    ledger.write_entry("magma", [str(missing)], [])

    point = restore.create_restore_point(
        "My desktop, today", backend=backend, root=tmp_path, keys=[ACCENT]
    )

    assert point.files[str(missing)] is None
    assert str(missing) in point.files_to_remove


def test_the_claimed_files_come_from_the_ledgers_own_reader(tmp_path):
    """Every owner is walked, not just the current Look, and nothing repeats."""
    ledger.write_entry("magma", ["/a", "/b"], [])
    ledger.write_entry(ledger.MANUAL_OWNER, ["/b", "/c"], [])
    assert restore.claimed_dests() == ["/a", "/b", "/c"]


def test_no_ledger_at_all_is_an_empty_list_not_a_failure(tmp_path):
    assert restore.claimed_dests() == []


# -- the wording itself ------------------------------------------------------


def test_every_new_sentence_on_this_page_is_plain_language():
    assert jargon.check_all(restore.copy_strings()) == []
