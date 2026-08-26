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
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

__all__ = ["ApplyRunner", "Narrate", "Work"]

#: What the work calls to say what it is doing. Safe from a worker thread — the
#: runner is what moves the sentence onto the main loop.
Narrate = Callable[[str], None]

#: The slow half of a change. Runs off the main loop; gets a narrator.
Work = Callable[[Narrate], Any]


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
        self.dialog: Adw.AlertDialog | None = None

    def run(
        self,
        work: Work,
        *,
        heading: str,
        starting: str,
        on_done: Callable[[Any], None],
        on_failed: Callable[[Exception], None] | None = None,
    ) -> Adw.AlertDialog:
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

        Returns:
            The progress dialog, so a caller can look at it. It closes itself.
        """
        dialog = Adw.AlertDialog(heading=heading, body=starting)
        self.dialog = dialog
        if isinstance(self.window, Gtk.Widget):
            dialog.present(self.window)

        def narrate(text: str) -> None:
            if not text:
                return
            GLib.idle_add(_set_body, dialog, text)

        def settle(outcome: Any, error: Exception | None) -> bool:
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


def _set_body(dialog: Adw.AlertDialog, text: str) -> bool:
    dialog.set_body(text)
    return GLib.SOURCE_REMOVE
