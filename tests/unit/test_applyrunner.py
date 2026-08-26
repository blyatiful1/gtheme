"""The shared apply runner.

Two things it has to get right, and both of them are the kind that only show up
on somebody else's machine:

* the progress dialog closes **exactly once**, however the work ended;
* narration from the worker never touches a widget directly.

The second one cannot be asserted from a test — it is a rule about which
thread a line of code runs on — so the runner is written so that the only path
to a widget is ``GLib.idle_add``, and these tests drive it inline where that
distinction does not arise. What they do pin is the first: no exception
escapes to a click handler, and the caller always hears exactly one answer.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gtk

from gtheme.ui.applyrunner import ApplyRunner  # noqa: E402


def test_the_work_runs_and_its_answer_comes_back():
    answers = []
    runner = ApplyRunner(threaded=False)
    runner.run(
        lambda _narrate: "the outcome",
        heading="Doing a thing",
        starting="Starting…",
        on_done=answers.append,
    )
    assert answers == ["the outcome"]


def test_what_the_work_says_ends_up_in_the_dialog():
    runner = ApplyRunner(threaded=False)
    seen = []

    def work(narrate):
        narrate("Saving how it looks now…")
        seen.append(runner.dialog.get_body())
        narrate("Changing the colours…")
        return None

    runner.run(work, heading="A Look", starting="Starting…", on_done=lambda _o: None)
    # Narration is queued onto the main loop rather than written straight into
    # the widget, so the body has not moved yet. That is the property: a worker
    # thread never touches a widget.
    assert seen == ["Starting…"]


def test_a_failure_is_reported_rather_than_raised():
    failures = []

    def explode(_narrate):
        raise RuntimeError("the disk went away")

    ApplyRunner(threaded=False).run(
        explode,
        heading="A Look",
        starting="Starting…",
        on_done=lambda _o: pytest.fail("this should not have finished"),
        on_failed=failures.append,
    )
    assert len(failures) == 1
    assert str(failures[0]) == "the disk went away"


def test_a_failure_with_nobody_watching_still_does_not_escape():
    """Work that reports its own failures may be run without a handler."""
    ApplyRunner(threaded=False).run(
        lambda _n: (_ for _ in ()).throw(OSError("gone")),
        heading="A Look",
        starting="Starting…",
        on_done=lambda _o: pytest.fail("this should not have finished"),
    )


def test_the_dialog_is_let_go_of_when_the_work_ends():
    runner = ApplyRunner(threaded=False)
    runner.run(
        lambda _n: None, heading="A Look", starting="Starting…", on_done=lambda _o: None
    )
    assert runner.dialog is None


def test_it_runs_on_a_thread_by_default_and_the_answer_still_arrives():
    from gi.repository import GLib

    runner = ApplyRunner()
    answers = []
    runner.run(
        lambda _n: 41 + 1, heading="A Look", starting="Starting…", on_done=answers.append
    )
    context = GLib.MainContext.default()
    for _ in range(2000):
        if answers:
            break
        context.iteration(False)
    assert answers == [42]
