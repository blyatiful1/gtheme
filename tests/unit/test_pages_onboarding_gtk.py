"""The first-run introduction: four slides, skippable, ending in a real action.

Marked ``gtk``: the dialog is really built. It is never presented — the test
drives its buttons directly, so nothing appears on the developer's screen.
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
from gtheme.ui import jargon, onboarding  # noqa: E402
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
        self.pages: list[str] = []

    def toast(self, text: str) -> None:
        self.toasts.append(text)

    def show_page(self, page_id: str) -> None:
        self.pages.append(page_id)


@pytest.fixture
def window(config_dir):
    return FakeWindow(Prefs())


def test_the_safety_sentence_is_carried_verbatim():
    """DESIGN.md A4 and SECURITY.md say this letter for letter. So does slide 2."""
    assert (
        onboarding.SECURITY_SENTENCE
        == "Looks only change settings. They can't run programs on your computer."
    )
    assert onboarding.SECURITY_SENTENCE in onboarding.SLIDES[1].body


def test_there_are_four_slides_and_the_last_one_is_the_action():
    assert len(onboarding.SLIDES) == 4
    assert onboarding.SLIDES[3].title == onboarding.SAVE_LABEL


def test_every_word_of_the_introduction_is_jargon_free():
    assert jargon.check_all(onboarding.copy_strings()) == []


def test_it_shows_on_a_first_run_and_never_again(window):
    assert onboarding.should_show(window.prefs)
    onboarding.mark_finished(window.prefs)
    assert not onboarding.should_show(window.prefs)


def test_with_no_preferences_to_ask_it_stays_out_of_the_way():
    assert onboarding.should_show(None) is False


def test_next_walks_the_slides_and_the_last_one_finishes(window):
    dialog = onboarding.OnboardingDialog(window, on_save=lambda: None)
    assert dialog.index == 0
    for expected in (1, 2, 3):
        dialog.advance()
        assert dialog.index == expected
    assert dialog.next_button.get_label() == onboarding.DONE_LABEL

    dialog.advance()

    assert not onboarding.should_show(window.prefs)
    assert window.pages == ["looks"], "the tour ends on the page that is the whole app"


def test_skipping_counts_as_finishing(window):
    dialog = onboarding.OnboardingDialog(window, on_save=lambda: None)
    dialog.skip_button.emit("clicked")
    assert not onboarding.should_show(window.prefs)


def test_the_last_slide_really_saves_a_restore_point(window, tmp_path):
    backend = MemoryBackend()
    backend.set(ACCENT, "'green'")
    dialog = onboarding.OnboardingDialog(
        window,
        on_save=lambda: restore.create_restore_point(
            backend=backend, root=tmp_path, keys=[ACCENT]
        ),
    )

    point = dialog.save_first_restore_point()

    assert point is not None
    assert (tmp_path / point.id / "restore-point.json").is_file()
    assert dialog.save_status.get_label() == onboarding.SAVED_LABEL
    assert not dialog.save_button.get_sensitive(), "pressing it twice saves the same moment twice"


def test_a_save_that_fails_ends_in_a_sentence_not_a_traceback(window):
    def explode():
        raise OSError("no room")

    dialog = onboarding.OnboardingDialog(window, on_save=explode)
    assert dialog.save_first_restore_point() is None
    assert dialog.save_status.get_label() == onboarding.SAVE_FAILED_LABEL


def test_show_again_opens_it_even_after_it_has_been_seen(window):
    onboarding.mark_finished(window.prefs)
    assert onboarding.maybe_present(window) is None
    dialog = onboarding.show_again(window, on_save=lambda: None)
    assert isinstance(dialog, Adw.Dialog)
