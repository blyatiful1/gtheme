"""The progress dialog: what it shows while a change runs, and its Stop.

Applying a Look with eleven add-ons is up to three minutes. What that looked
like was one sentence being replaced in a dialog with no bar, no list of what
had happened, and no way out (persona-report §3.3, E5). These tests pin the
three properties that answer it, and the safety rule underneath the third:

* every step the work narrates is kept and shown, whichever route it arrives by;
* the Stop appears only for work that has proved there is a moment to stop at;
* the stop is raised **once** — the engine narrates while it rolls back, and a
  stop raised inside a rollback would abandon the desktop halfway home;
* and, because there is only one raise, nothing between the narrator and the
  engine's failure path may swallow it. The add-on download used to (E5), which
  is what the last two tests here pin, driving the real ``LookAddons`` and the
  real ``Transaction._install_extensions``.

Everything runs inline with no window, so no dialog is ever shown.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gtk

from gi.repository import GLib  # noqa: E402

from gtheme.ui.applyrunner import COPY, ApplyRunner, ProgressDialog, Stopped  # noqa: E402


def pump() -> None:
    """Run whatever narration has been queued onto the main loop."""
    context = GLib.MainContext.default()
    for _ in range(200):
        if not context.pending():
            return
        context.iteration(False)


# -- what it shows ---------------------------------------------------------


def test_every_step_is_kept_and_the_latest_one_is_the_headline():
    runner = ApplyRunner(threaded=False)

    def work(narrate):
        narrate("Saving how things look right now")
        narrate("Copying 20 file(s) into place")
        narrate("Turning on 11 add-on(s)")
        return "done"

    dialog = runner.run(
        work, heading="MAGMA", starting="Starting…", on_done=lambda _o: None
    )
    pump()

    assert dialog.steps == [
        "Saving how things look right now",
        "Copying 20 file(s) into place",
        "Turning on 11 add-on(s)",
    ]
    assert dialog.get_body() == "Turning on 11 add-on(s)"
    assert dialog.history.get_visible()
    assert "Saving how things look right now" in dialog.history.get_label()


def test_a_sentence_written_straight_into_the_dialog_is_a_step_too():
    """The Undo page narrates by setting the body itself, and was here first."""
    dialog = ProgressDialog("Putting your desktop back", "Going back…")
    dialog.set_body("Putting 12 setting(s) back")

    assert dialog.steps == ["Putting 12 setting(s) back"]
    assert dialog.get_body() == "Putting 12 setting(s) back"


def test_narration_still_never_touches_a_widget_from_the_work():
    """The existing rule, kept: the worker queues, the main loop writes."""
    runner = ApplyRunner(threaded=False)
    seen = []

    def work(narrate):
        narrate("Saving how it looks now…")
        seen.append((runner.dialog.get_body(), list(runner.dialog.steps)))
        return None

    runner.run(work, heading="A Look", starting="Starting…", on_done=lambda _o: None)
    assert seen == [("Starting…", [])]


# -- the Stop --------------------------------------------------------------


def test_no_stop_is_offered_to_work_that_never_says_anything():
    runner = ApplyRunner(threaded=False)
    dialog = runner.run(
        lambda _n: None, heading="A moment", starting="Saving…", on_done=lambda _o: None
    )
    pump()
    assert not dialog.stop_button.get_visible(), (
        "a button that could not stop anything is worse than no button"
    )


def test_the_stop_is_offered_once_the_work_has_narrated():
    runner = ApplyRunner(threaded=False)

    def work(narrate):
        narrate("Working out what will change")
        pump()
        assert runner.dialog.stop_button.get_visible()
        assert runner.dialog.stop_note.get_visible()
        return "done"

    runner.run(work, heading="MAGMA", starting="Starting…", on_done=lambda _o: None)


def test_stopping_lands_between_two_steps_and_never_inside_one():
    runner = ApplyRunner(threaded=False)
    happened: list[str] = []
    failures: list[Exception] = []

    def work(narrate):
        narrate("Copying 20 file(s) into place")
        pump()
        runner.dialog.stop_button.emit("clicked")
        # The step that was running when Stop was pressed finishes.
        happened.append("the step in flight finished")
        narrate("Changing 40 setting(s)")
        happened.append("this never runs")
        return "applied"

    runner.run(
        work,
        heading="MAGMA",
        starting="Starting…",
        on_done=lambda outcome: happened.append(outcome),
        on_failed=failures.append,
    )

    assert happened == ["the step in flight finished"]
    assert isinstance(failures[0], Stopped)
    assert str(failures[0]) == COPY["stopped"]


def test_pressing_stop_says_what_stopping_is_doing():
    runner = ApplyRunner(threaded=False)

    def work(narrate):
        narrate("Copying 20 file(s) into place")
        pump()
        dialog = runner.dialog
        assert dialog.stop_note.get_label() == COPY["stop-note"]
        dialog.stop_button.emit("clicked")
        assert dialog.stop_note.get_label() == COPY["stopping"]
        assert not dialog.stop_button.get_sensitive()
        return "applied"

    runner.run(work, heading="MAGMA", starting="Starting…", on_done=lambda _o: None)


def test_pressing_stop_does_not_claim_a_rollback_that_has_not_happened():
    """What the label says is what is certain at the moment it is pressed.

    It used to say "Putting back anything that had already changed…" the
    instant Stop was pressed — before the stop had reached the engine, and in
    one case (E5) when it never would. The putting back is the engine's own
    narration and arrives in this same dialog when it really happens.
    """
    assert "put" not in COPY["stopping"].lower()
    assert "back" not in COPY["stopping"].lower()


def test_the_stop_is_raised_only_once_so_a_rollback_can_finish():
    """The safety rule. The engine narrates its rollback through the same call.

    A stop raised a second time would come out of ``_roll_back`` before it had
    put anything back, which is the one outcome worse than not stopping. This
    is the shape ``Transaction.apply`` really has: the stop comes out of the
    narrator, the failure arm catches it, and everything the rollback says is
    said from inside that arm.
    """
    runner = ApplyRunner(threaded=False)
    caught: list[Exception] = []
    failures: list[Exception] = []

    def work(narrate):
        narrate("Getting 11 add-on(s)")
        pump()
        runner.dialog.stop_button.emit("clicked")
        try:
            narrate("Changing 40 setting(s)")
        except Stopped as stopped:
            caught.append(stopped)
            # Exactly where ``Transaction._failed`` narrates from.
            narrate("Putting everything back the way it was")
            narrate("Nothing was changed")
            raise
        return "applied"

    runner.run(
        work,
        heading="MAGMA",
        starting="Starting…",
        on_done=lambda _o: pytest.fail("the stop was lost"),
        on_failed=failures.append,
    )

    assert [str(error) for error in caught] == [COPY["stopped"]]
    assert failures == caught, "the rollback finished and the stop still came out"
    assert runner.dialog is None


def test_work_that_must_not_be_interrupted_is_never_offered_a_stop():
    runner = ApplyRunner(threaded=False)

    def work(narrate):
        narrate("Saving how things look right now")
        pump()
        assert not runner.dialog.stop_button.get_visible()
        return "saved"

    runner.run(
        work,
        heading="A moment",
        starting="Saving…",
        on_done=lambda _o: None,
        stoppable=False,
    )


# -- nothing between the narrator and the rollback may swallow it (E5) ------


class _Batch:
    """Stands in for ``AddonBatch``: narrates, then says the add-on arrived.

    Stop is pressed while the *first* add-on is downloading, which is the phase
    the button exists for and the phase that used to eat it.
    """

    def __init__(self, press) -> None:
        self.calls: list[str] = []
        self.press = press

    def run_and_wait(self, wanted, *, on_progress=None, timeout=None):
        self.calls.append(wanted[0][0])
        if on_progress is not None:
            on_progress("Getting add-ons…")
        if len(self.calls) == 1:
            self.press()
        return None, []


def _install_phase(runner, monkeypatch):
    """Drive the real install phase of a three-add-on Look, stopping mid-way.

    Returns ``(addons, result, outcomes, failures, batch)``.
    """
    from gtheme.core import transaction as engine
    from gtheme.core.transaction import Diff, ExtensionInstall, Transaction, TransactionResult
    from gtheme.ui.pages.looks import LookAddons

    monkeypatch.setattr(engine, "installed_extension_uuids", lambda: set())

    def press():
        pump()
        runner.dialog.stop_button.emit("clicked")

    batch = _Batch(press)
    addons = LookAddons(batch)
    transaction = Transaction(
        [
            ExtensionInstall(uuid="blur-my-shell@aunetx"),
            ExtensionInstall(uuid="just-perfection-desktop@just-perfection"),
            ExtensionInstall(uuid="dash-to-dock@micxgx.gmail.com"),
        ]
    )
    transaction.installer = addons
    result = TransactionResult(diff=Diff())
    outcomes: list[object] = []
    failures: list[Exception] = []
    reached: list[str] = []

    def work(narrate):
        addons.on_progress = narrate
        narrate("Saving how things look right now")
        transaction._install_extensions(result, lambda _stage, text: narrate(text))
        reached.append("the settings phase")
        narrate("Changing 40 setting(s)")
        return "applied"

    runner.run(
        work,
        heading="MAGMA",
        starting="Starting…",
        on_done=outcomes.append,
        on_failed=failures.append,
    )
    pump()
    return addons, reached, outcomes, failures, batch


def test_a_stop_during_a_download_stops_the_apply(monkeypatch):
    """It used to be swallowed twice over, and the Look landed anyway (E5)."""
    runner = ApplyRunner(threaded=False)
    _addons, reached, outcomes, failures, batch = _install_phase(runner, monkeypatch)

    assert reached == [], "the apply carried on past the phase that was stopped"
    assert outcomes == [], "a stopped apply must not be reported as a success"
    assert isinstance(failures[0], Stopped)
    assert batch.calls == [
        "blur-my-shell@aunetx",
        "just-perfection-desktop@just-perfection",
    ], "the third add-on was never started"


def test_a_stop_is_never_reported_as_a_download_that_failed(monkeypatch):
    """The reason shown blamed the reader's internet for their own decision."""
    runner = ApplyRunner(threaded=False)
    addons, _reached, _outcomes, _failures, _batch = _install_phase(runner, monkeypatch)

    assert addons.problems == [], (
        "a stop is not a download that failed, and must not be worded as one"
    )


# -- the rules that were already true, still true ---------------------------


def test_the_dialog_is_let_go_of_however_the_work_ends():
    runner = ApplyRunner(threaded=False)
    runner.run(
        lambda _n: None, heading="A Look", starting="Starting…", on_done=lambda _o: None
    )
    assert runner.dialog is None

    runner.run(
        lambda _n: (_ for _ in ()).throw(OSError("gone")),
        heading="A Look",
        starting="Starting…",
        on_done=lambda _o: pytest.fail("this should not have finished"),
    )
    assert runner.dialog is None


def test_the_words_the_dialog_says_are_plain():
    from gtheme.ui import jargon

    assert jargon.check_all([(f"applyrunner.COPY[{k!r}]", v) for k, v in COPY.items()]) == []
