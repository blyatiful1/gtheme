"""One place where a long change is run, narrated, and reported.

Before this existed there were two answers to "how does gtheme apply something
slow". The Looks page started a worker thread and pushed narration back through
``GLib.idle_add``; the Undo page called the engine straight from the click
handler and had an empty ``_progress`` method waiting for somebody to fill in.
The second one is the bug: applying a restore point copies files and writes
several dozen settings, and doing that on the main loop is how a window stops
repainting halfway through the one operation the user is most anxious about.

So there is one runner. It owns the thread, the progress dialog, the rule that
narration only ever touches widgets on the main loop, and the rule that the
dialog closes exactly once however the work ends. Pages hand it a function and
say what to call the change; they no longer each own a thread.

The runner deliberately does **not** know what a transaction is. It is given a
callable and a way to say what that callable is doing, which is why the Looks
page can use it for applying a Look and the Undo page can use it for going back
to a moment without either of them learning about the other.

**What the dialog shows, and why it can be stopped** (persona-report §3.3, E5).
Eleven add-ons over slow broadband is up to three minutes; what that used to
look like was one sentence being replaced, with no bar, no list and no way out.
Now the steps accumulate, a bar moves as each one arrives, and there is a Stop.

The Stop is honest about a real limit. Nothing here can interrupt an operation
that is running: a file is copied or it is not, an add-on is installed or it is
not. What it can do is refuse to start the next one — so the stop is raised out
of the narrator, which the engine calls *between* operations, and the engine
then unwinds the same way it unwinds any other failure: what had already landed
is put back. That is why the button appears only once the work has narrated at
least once. Work that never narrates has no moment where stopping is safe, and
a button that would do nothing is worse than no button.

**It is raised exactly once, and that is deliberate.** The engine narrates
while it rolls *back* too, and a stop raised inside a rollback would abandon
the desktop halfway home — the one outcome worse than not stopping. So the
first raise is the only one.

**Which is why nothing between here and the rollback may swallow it.** That
one raise has to reach the engine's failure path or it is simply lost. A Look
that fetches add-ons runs the download through an installer seam, and both
``LookAddons.__call__`` and ``Transaction._install_extensions`` wrap that call
in ``except Exception`` — correctly, because one add-on failing must not lose
the Look. Those two arms used to catch the stop as well, so a Stop pressed
during the download — the longest phase of the longest apply, and the phase
this button exists for — was recorded as "this add-on could not be downloaded",
blaming the reader's internet for their own decision, and the apply then ran to
the end and reported success under a dialog that had just said it was putting
things back (review-report E5). Both arms now name
:class:`~gtheme.core.stop.Stopped` and re-raise it, and that module carries the
argument for why it is an ordinary exception rather than a ``BaseException``.

**What the dialog says once Stop is pressed is only what is certain.** It says
the change is stopping, and not that anything is being put back: the putting
back is the engine's own narration, which arrives in this same dialog when it
really happens. Pressed during the last step of all, a Stop lands too late to
stop anything, and a label that had already announced a rollback would be the
same lie in a smaller font.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ..core.stop import Stopped  # noqa: E402

__all__ = ["COPY", "ApplyRunner", "Narrate", "Stopped", "Work"]

#: What the work calls to say what it is doing. Safe from a worker thread — the
#: runner is what moves the sentence onto the main loop.
Narrate = Callable[[str], None]

#: The slow half of a change. Runs off the main loop; gets a narrator.
Work = Callable[[Narrate], Any]

#: Every sentence the progress dialog says, in one place.
COPY: dict[str, str] = {
    "stop": "Stop",
    "stop-note": (
        "Stopping takes effect between steps, never in the middle of one. "
        "Anything that had already been changed is put back."
    ),
    # Only what is true the instant Stop is pressed. The step that is running
    # cannot be interrupted, and whether anything is put back depends on there
    # being a next step to refuse — so the rollback is announced by the engine
    # narrating it into this same dialog, not promised here in advance (E5).
    "stopping": "Stopping as soon as the step that is running has finished…",
    "stopped": "You stopped this change.",
}

#: How many finished steps stay on screen. Enough to see the shape of what
#: happened; not so many that the dialog grows down the screen.
HISTORY_LINES = 6

#: How often the bar moves while a single long step is running. The bar also
#: moves on every step, so this is only about the three-minute one.
PULSE_MS = 700


class _Stop:
    """The state of one Stop button, shared between the two threads."""

    __slots__ = ("offered", "raised", "requested")

    def __init__(self) -> None:
        self.requested = threading.Event()
        #: Raised exactly once. The rollback narrates too, and stopping the
        #: rollback would leave the desktop where the failure left it.
        self.raised = False
        self.offered = False


class ProgressDialog(Adw.AlertDialog):
    """The dialog a long change is watched through.

    ``set_body`` is overridden rather than left alone because narration reaches
    this dialog two ways: through the runner's narrator, and — from the Undo
    page, which was here first — by writing the sentence straight into the
    dialog. Catching both here means the bar and the list of steps are fed by
    whichever route the caller happens to use, instead of only by the newer
    one.
    """

    __gtype_name__ = "GthemeApplyProgressDialog"

    def __init__(self, heading: str, starting: str) -> None:
        super().__init__(heading=heading, body=starting)
        #: Every step narrated so far, in order, for tests and for the label.
        self.steps: list[str] = []

        self.bar = Gtk.ProgressBar(show_text=False, hexpand=True)
        self.history = Gtk.Label(
            label="",
            xalign=0,
            wrap=True,
            visible=False,
            css_classes=["dimmed", "caption"],
        )
        self.stop_button = Gtk.Button(
            label=COPY["stop"],
            halign=Gtk.Align.CENTER,
            visible=False,
            css_classes=["destructive-action"],
        )
        self.stop_note = Gtk.Label(
            label=COPY["stop-note"],
            xalign=0,
            wrap=True,
            visible=False,
            css_classes=["dimmed", "caption"],
        )

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.append(self.bar)
        box.append(self.history)
        box.append(self.stop_button)
        box.append(self.stop_note)
        self.set_extra_child(box)

    # -- narration ---------------------------------------------------------

    def set_body(self, text: str) -> None:  # noqa: D102 - see the class docstring
        self.step(text)

    def step(self, text: str) -> None:
        """Record a step and show it. Main loop only."""
        if not text:
            return
        self.steps.append(text)
        # ``props.body`` rather than ``set_body``: this *is* set_body's
        # implementation, and calling the overridden name would recurse.
        self.props.body = text
        previous = self.steps[:-1][-HISTORY_LINES:]
        self.history.set_label("\n".join(previous))
        self.history.set_visible(bool(previous))
        self.bar.pulse()

    def pulse(self) -> None:
        self.bar.pulse()

    # -- stopping ----------------------------------------------------------

    def offer_stop(self, on_stop: Callable[[], None]) -> None:
        """Show the Stop button. Called once the work has proved it narrates."""
        if self.stop_button.get_visible():
            return
        self.stop_button.connect("clicked", lambda *_a: on_stop())
        self.stop_button.set_visible(True)
        self.stop_note.set_visible(True)

    def stopping(self) -> None:
        """Say what pressing Stop is now doing, and that it cannot be pressed twice.

        It does not say the desktop is being put back. That happens when the
        stop reaches the engine, and the engine says so itself, in this dialog,
        one step later (E5).
        """
        self.stop_button.set_sensitive(False)
        self.stop_note.set_label(COPY["stopping"])


class ApplyRunner:
    """Runs one change at a time, with a dialog that says what is happening.

    Args:
        window: what a dialog belongs to. Anything that is not a real widget —
            which is the case in every unit test — means the dialog is built
            and never shown, so a test can drive a whole apply without anything
            appearing on the screen of whoever is running it.
        threaded: run the work on a worker thread. False runs it inline, which
            is what a test wants: the result is there when :meth:`run` returns,
            with no main loop to pump.
    """

    def __init__(self, window: Any = None, *, threaded: bool = True) -> None:
        self.window = window
        self.threaded = threaded
        #: The dialog of the change currently running, for tests to look at.
        self.dialog: ProgressDialog | None = None

    def run(
        self,
        work: Work,
        *,
        heading: str,
        starting: str,
        on_done: Callable[[Any], None],
        on_failed: Callable[[Exception], None] | None = None,
        stoppable: bool = True,
    ) -> ProgressDialog:
        """Do something slow, saying so while it happens.

        Args:
            work: the slow half. Called with a narrator it may call as often as
                it likes; whatever it returns is handed to ``on_done``.
            heading: what the change is called — the Look's title, the moment's
                name. Shown as the dialog heading.
            starting: the first sentence, before the work has narrated anything.
            on_done: called on the main loop with the work's return value.
            on_failed: called on the main loop with whatever the work raised.
                Omitted means a failure is swallowed after the dialog closes,
                which is only ever right when the work reports its own failures.
            stoppable: whether a Stop may be offered once the work narrates.
                False for work that must not be interrupted between its own
                steps — the runner cannot know that, so the caller says.

        Returns:
            The progress dialog, so a caller can look at it. It closes itself.
        """
        dialog = ProgressDialog(heading, starting)
        self.dialog = dialog
        if isinstance(self.window, Gtk.Widget):
            dialog.present(self.window)

        stop = _Stop()
        pulse = GLib.timeout_add(PULSE_MS, _pulse, dialog)

        def request_stop() -> None:
            stop.requested.set()
            dialog.stopping()

        def narrate(text: str = "") -> None:
            # The stop is raised here, and only here: this is the one place the
            # runner is given control between two of the engine's operations.
            if stop.requested.is_set() and not stop.raised:
                stop.raised = True
                raise Stopped(COPY["stopped"])
            if not text:
                return
            if stoppable and not stop.offered:
                stop.offered = True
                GLib.idle_add(_offer_stop, dialog, request_stop)
            GLib.idle_add(_step, dialog, text)

        def settle(outcome: Any, error: Exception | None) -> bool:
            _drop(pulse)
            dialog.close()
            if self.dialog is dialog:
                self.dialog = None
            if error is not None:
                if on_failed is not None:
                    on_failed(error)
            else:
                on_done(outcome)
            return GLib.SOURCE_REMOVE

        def attempt() -> tuple[Any, Exception | None]:
            try:
                return work(narrate), None
            except Exception as error:  # noqa: BLE001 - never leave a dialog spinning
                return None, error

        if not self.threaded:
            outcome, error = attempt()
            settle(outcome, error)
            return dialog

        def worker() -> None:
            outcome, error = attempt()
            GLib.idle_add(settle, outcome, error)

        threading.Thread(target=worker, daemon=True, name="gtheme-apply").start()
        return dialog


def _step(dialog: ProgressDialog, text: str) -> bool:
    dialog.step(text)
    return GLib.SOURCE_REMOVE


def _offer_stop(dialog: ProgressDialog, on_stop: Callable[[], None]) -> bool:
    dialog.offer_stop(on_stop)
    return GLib.SOURCE_REMOVE


def _pulse(dialog: ProgressDialog) -> bool:
    dialog.pulse()
    return GLib.SOURCE_CONTINUE


def _drop(source: int) -> None:
    """Take the pulse timer out. A source that already went is not an error."""
    try:
        GLib.source_remove(source)
    except Exception:  # pragma: no cover - already gone
        pass
