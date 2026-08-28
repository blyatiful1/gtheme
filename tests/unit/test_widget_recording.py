"""What a page edit writes down, and what it says when it cannot.

Three findings meet here, and every test below fails against the code as it was
(review-report H3, H3's reset half, and M7):

* **H3** — a row wrote straight to the settings store. Nothing recorded the
  pristine value, nothing claimed the change, and no saved moment covered it,
  so Undo and ``gtheme rescue`` could not reach it and a Look applied later
  recorded the *already edited* value as "before gtheme".
* **H3, the reset half** — "Put this back the way it was" installed the schema
  default, which is a different thing and wrong for anybody who had chosen
  something else before gtheme existed.
* **M7** — a refused write left the switch flipped and said nothing.

Everything runs against a memory backend and a throwaway state directory, so no
setting and no saved moment on the real desktop is touched.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for the widget library")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from gtheme.core import ledger as ledger_store  # noqa: E402
from gtheme.core import restorepoints  # noqa: E402
from gtheme.core.baseline import Baseline  # noqa: E402
from gtheme.core.ledger import MANUAL_OWNER  # noqa: E402
from gtheme.core.lock import process_lock  # noqa: E402
from gtheme.core.settings_backend import (  # noqa: E402
    BackendError,
    BackendErrorKind,
    MemoryBackend,
)
from gtheme.panels.descriptor import Row  # noqa: E402
from gtheme.ui import jargon  # noqa: E402
from gtheme.ui.widgets import recording  # noqa: E402
from gtheme.ui.widgets.rows import (  # noqa: E402
    PUT_BACK_DEFAULT,
    PUT_BACK_RECORDED,
    build_row,
)

pytestmark = pytest.mark.gtk

SCHEMA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<schemalist>
  <schema id="io.github.blyatiful1.GthemeRecordingTest"
          path="/io/github/blyatiful1/gtheme-recording-test/">
    <key name="a-flag" type="b"><default>false</default></key>
    <key name="b-flag" type="b"><default>false</default></key>
    <key name="a-name" type="s"><default>'Adwaita'</default></key>
  </schema>
</schemalist>
"""

ID = "io.github.blyatiful1.GthemeRecordingTest"
FLAG = f"gsettings:{ID} a-flag"
OTHER = f"gsettings:{ID} b-flag"
NAME = f"gsettings:{ID} a-name"


@pytest.fixture(autouse=True, scope="module")
def _adw():
    if not Gtk.init_check():
        pytest.skip("no display is available for GTK — run under gtk4-broadwayd")
    Adw.init()


@pytest.fixture(autouse=True)
def _fresh_burst():
    """Every test starts its own run of edits, and leaves none behind."""
    recording.forget_burst()
    yield
    recording.forget_burst()


@pytest.fixture
def backend(schema_source_factory):
    return MemoryBackend(schema_source=schema_source_factory(SCHEMA_XML))


class RefusingBackend(MemoryBackend):
    """Reads like any store; refuses every write, the way a locked one does.

    This is the machine the M7 finding is about: a dconf lock profile, where
    ``set`` raises and the row used to let the exception escape a GTK signal
    handler with the switch left showing a change that never happened.
    """

    def __init__(self, schema_source: Any = None, kind: Any = None) -> None:
        super().__init__(schema_source)
        self.kind = kind or BackendErrorKind.COMMIT_FAILED

    def set(self, key: str, value: str) -> None:
        raise BackendError(self.kind, f"refused {key}", key=key)

    def reset(self, key: str) -> None:
        raise BackendError(self.kind, f"refused {key}", key=key)


def _row(**overrides) -> Row:
    base = {
        "schema_id": ID,
        "key": "a-flag",
        "title": "A flag",
        "subtitle": "Turns the thing on.",
        "kind": "toggle",
    }
    return Row.model_validate({**base, **overrides})


def _points() -> list[restorepoints.RestorePoint]:
    return restorepoints.list_restore_points()


# --------------------------------------------------------------------------
# H3 — a page edit is written down like everything else
# --------------------------------------------------------------------------


def test_flipping_a_switch_records_what_was_there_before(backend):
    widget, _ = build_row(backend, _row())
    widget.set_active(True)

    saved = Baseline(backend=backend).load().settings
    assert FLAG in saved, "a page edit must reach the pristine recording (H3)"
    assert saved[FLAG]["saved"] == "false"


def test_flipping_a_switch_claims_the_change_for_the_person(backend):
    widget, _ = build_row(backend, _row())
    widget.set_active(True)

    ledger = ledger_store.read_ledger()
    assert FLAG in ledger.get(MANUAL_OWNER, {}).get("settings", []), (
        "an unclaimed change is one nothing will ever undo (H3, and the "
        "uninstall guard in M21 reads this file)"
    )


def test_flipping_a_switch_leaves_a_moment_to_go_back_to(backend):
    widget, _ = build_row(backend, _row())
    widget.set_active(True)

    points = _points()
    assert len(points) == 1
    assert points[0].kind == "auto"
    assert points[0].label == recording.COPY["moment"]
    assert points[0].settings == {FLAG: "false"}


def test_a_run_of_edits_is_one_moment_not_one_per_toggle(backend):
    """The cap-eviction trap: ten moments is the cap, and a person nudging six
    settings must not quietly evict the moment taken before this morning's Look.
    """
    first, _ = build_row(backend, _row())
    second, _ = build_row(backend, _row(key="b-flag", title="B flag"))
    first.set_active(True)
    second.set_active(True)

    points = _points()
    assert len(points) == 1, "one burst of edits is one saved moment"
    assert points[0].settings == {FLAG: "false", OTHER: "false"}


def test_the_moment_holds_the_values_from_before_the_burst(backend):
    """Not the edited ones — a moment that saved the new value restores nothing."""
    widget, _ = build_row(backend, _row())
    widget.set_active(True)
    widget.set_active(False)
    widget.set_active(True)

    assert _points()[0].settings == {FLAG: "false"}


def test_the_next_run_of_edits_gets_its_own_moment(backend, monkeypatch):
    widget, _ = build_row(backend, _row())
    widget.set_active(True)

    started = recording._burst.started  # noqa: SLF001 - reaching in to age the burst
    monkeypatch.setattr(
        recording, "_now", lambda: started + recording.BURST_WINDOW + timedelta(minutes=1)
    )
    other, _ = build_row(backend, _row(key="b-flag", title="B flag"))
    other.set_active(True)

    assert len(_points()) == 2, "coming back later is a new moment, not the same one"


def test_a_page_edit_does_not_poison_what_before_gtheme_means(backend):
    """The permanent half of H3.

    A Look records the pristine value the first time it touches a setting. If a
    page edit reached the store without recording, the Look recorded the
    *edited* value, and "what your desktop looked like before gtheme" was wrong
    for that setting for good. Recording on first touch is what closes it: the
    later recording finds the setting already known and leaves it alone.
    """
    widget, _ = build_row(backend, _row(key="a-name", kind="text", title="A name"))
    widget.set_text("Nightbloom")
    widget.emit("apply")

    baseline = Baseline(backend=backend).load()
    assert baseline.settings[NAME]["saved"] == "'Adwaita'"

    # Whatever runs next — a Look, a saved moment being put back — records the
    # same setting again and must not overwrite the pristine value.
    baseline.record_setting(NAME, "colours", "NIGHTBLOOM")
    assert Baseline(backend=backend).load().settings[NAME]["saved"] == "'Adwaita'"


def test_an_apply_in_progress_refuses_the_edit_politely(backend):
    """Somebody else holds the lock: the row does not crash, and says why."""
    widget, _ = build_row(backend, _row())
    with process_lock():
        widget.set_active(True)

    assert backend.get(FLAG) == "false", "the write must not have happened"
    assert widget.get_active() is False, "the switch goes back to the truth"
    assert "Something else is changing your desktop" in widget.get_subtitle()
    assert not _points(), "a refused edit leaves no moment behind"


def test_nothing_is_written_when_it_cannot_be_written_down(backend, monkeypatch):
    """A full or read-only state directory refuses the edit rather than
    changing the desktop with nothing recording it."""

    def no_room(*_args: Any, **_kwargs: Any):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(recording.restorepoints, "capture", no_room)
    widget, _ = build_row(backend, _row())
    widget.set_active(True)

    assert backend.get(FLAG) == "false"
    assert widget.get_active() is False
    assert "could not write down" in widget.get_subtitle()


def test_the_reset_button_is_recorded_too(backend):
    """It is a write like any other, and used not to be recorded at all."""
    backend.set(NAME, "'HighContrast'")
    widget, _ = build_row(backend, _row(key="a-name", kind="text", title="A name", reset=True))
    button = _reset_button(widget)
    assert button is not None
    button.emit("clicked")

    assert Baseline(backend=backend).load().settings[NAME]["saved"] == "'HighContrast'"
    assert NAME in ledger_store.read_ledger().get(MANUAL_OWNER, {}).get("settings", [])


# --------------------------------------------------------------------------
# H3 — "put this back the way it was" means the way it was
# --------------------------------------------------------------------------


def _reset_button(widget: Any) -> Gtk.Button | None:
    def walk(w: Any):
        child = w.get_first_child()
        while child is not None:
            yield child
            yield from walk(child)
            child = child.get_next_sibling()

    for child in walk(widget):
        if isinstance(child, Gtk.Button) and child.get_tooltip_text() in (
            PUT_BACK_RECORDED,
            PUT_BACK_DEFAULT,
        ):
            return child
    return None


def test_the_button_says_what_it_can_actually_do(backend):
    """Nothing recorded yet, so it cannot promise "the way it was"."""
    widget, _ = build_row(backend, _row(key="a-name", kind="text", title="A name", reset=True))
    assert _reset_button(widget).get_tooltip_text() == PUT_BACK_DEFAULT


def test_the_button_changes_its_promise_once_there_is_a_record(backend):
    widget, refresh = build_row(
        backend, _row(key="a-name", kind="text", title="A name", reset=True)
    )
    widget.set_text("Nightbloom")
    widget.emit("apply")
    refresh()

    assert _reset_button(widget).get_tooltip_text() == PUT_BACK_RECORDED


def test_putting_it_back_puts_back_the_value_that_was_there(backend):
    """Not the schema default. The whole finding in one test.

    The person had chosen ``HighContrast`` long before gtheme was installed.
    The old button wrote the schema's ``Adwaita`` and called that putting it
    back.
    """
    backend.set(NAME, "'HighContrast'")
    widget, refresh = build_row(
        backend, _row(key="a-name", kind="text", title="A name", reset=True)
    )
    widget.set_text("Nightbloom")
    widget.emit("apply")
    assert backend.get(NAME) == "'Nightbloom'"

    refresh()
    _reset_button(widget).emit("clicked")

    assert backend.get(NAME) == "'HighContrast'"


def test_putting_it_back_clears_a_setting_that_had_no_value(backend):
    """"There was nothing here" is a state, and it is put back by unsetting."""
    widget, refresh = build_row(
        backend, _row(key="a-name", kind="text", title="A name", reset=True)
    )
    widget.set_text("Nightbloom")
    widget.emit("apply")
    refresh()
    _reset_button(widget).emit("clicked")

    assert backend.get(NAME) == "'Adwaita'", "back to having no value of its own"


# --------------------------------------------------------------------------
# M7 — a refused write is never silent
# --------------------------------------------------------------------------


def test_a_refused_switch_goes_back_and_says_why(schema_source_factory):
    backend = RefusingBackend(schema_source_factory(SCHEMA_XML))
    widget, _ = build_row(backend, _row())
    widget.set_active(True)

    assert widget.get_active() is False, "the row shows what the desktop really has"
    assert widget.get_subtitle().startswith("Not changed.")


def test_a_refused_slider_goes_back_and_says_why(schema_source_factory):
    backend = RefusingBackend(schema_source_factory(SCHEMA_XML))
    row = _row(key="a-flag", kind="slider", clamp_min=0, clamp_max=10, step=1)
    widget, _ = build_row(backend, row)
    widget.set_value(4)

    assert widget.get_subtitle().startswith("Not changed.")


def test_a_refused_write_says_it_in_words_a_person_knows(schema_source_factory):
    backend = RefusingBackend(schema_source_factory(SCHEMA_XML), BackendErrorKind.NO_SCHEMA)
    widget, _ = build_row(backend, _row())
    widget.set_active(True)

    assert widget.get_subtitle() == "Not changed. This needs an add-on that isn't installed."
    assert "refused gsettings" not in widget.get_subtitle(), (
        "never the settings machinery's own message"
    )


class ToastWindow(Gtk.Window):
    """A window that can speak, which is what the real one does with this."""

    def __init__(self) -> None:
        super().__init__()
        self.said: list[str] = []

    def toast(self, text: str, **_kwargs: Any) -> None:
        self.said.append(text)


def test_a_refused_write_reaches_the_window_that_can_say_it(schema_source_factory):
    """The row finds its window the way every other page does: ``get_root``."""
    backend = RefusingBackend(schema_source_factory(SCHEMA_XML))
    widget, _ = build_row(backend, _row())
    window = ToastWindow()
    listbox = Gtk.ListBox()
    listbox.append(widget)
    window.set_child(listbox)
    try:
        widget.set_active(True)
        assert window.said, "a refused write must not be silent in a real window"
        assert window.said[-1].startswith("Not changed.")
    finally:
        window.destroy()


def test_the_row_stops_explaining_itself_once_a_write_works(backend, monkeypatch):
    widget, _ = build_row(backend, _row())
    with process_lock():
        widget.set_active(True)
    assert widget.get_subtitle().startswith("Not changed.")

    widget.set_active(True)
    assert widget.get_subtitle() == "Turns the thing on."
    assert backend.get(FLAG) == "true"


# --------------------------------------------------------------------------
# the words themselves
# --------------------------------------------------------------------------


def test_every_sentence_the_recorder_says_is_plain_english():
    problems = jargon.check_all(
        [
            *[(f"recording.COPY[{key!r}]", text) for key, text in recording.COPY.items()],
            ("recording.NOT_CHANGED", recording.NOT_CHANGED),
            ("PUT_BACK_RECORDED", PUT_BACK_RECORDED),
            ("PUT_BACK_DEFAULT", PUT_BACK_DEFAULT),
        ]
    )
    assert problems == [], "\n".join(problems)
