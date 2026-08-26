#!/usr/bin/env python3
"""Drive the real gtheme window inside the sandbox, one page at a time.

Run *inside* the sandbox session, never from the test process: this opens the
actual application — the actual ``Adw.Application``, the actual ``Window``, the
actual fifteen page factories — against the private bus, the private settings
store and the private extensions folder the harness set up. That is the whole
point. A screenshot of a window built by a test helper proves that the test
helper works.

**Why a conversation rather than a script.** The screenshot has to be taken by
somebody else. The shell will not photograph a window on request from the
process that owns it (the name it wants is already taken), and the capture is a
separate D-Bus round trip that takes over a second. So this side does the
driving and the test side does the photographing, and they take turns:

    <- mode dark          set the colour scheme, settle, answer
    -> ok
    <- page wallpaper     open that page, settle, answer
    -> ok
                          ...the test takes its photograph here...
    <- quit
    -> bye

One line in, one line out, nothing overlapping. A screenshot taken while a page
is still laying itself out is the one dishonest picture this whole gate exists
to prevent, so "answer only when it has settled" is the entire protocol.
"""

from __future__ import annotations

import sys
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from gtheme.prefs import Prefs  # noqa: E402
from gtheme.window import Window  # noqa: E402

#: The window is photographed at its real size, so this is the size the
#: screenshots end up being. These are ``window.DEFAULT_WIDTH`` and
#: ``DEFAULT_HEIGHT`` — the size gtheme actually opens at — rather than numbers
#: this probe made up, so the README shows a first run and not a shape nobody's
#: window is. ``test_window.py`` asserts the two stay equal; when they drifted,
#: the pictures were 800px tall and cut the sidebar off mid-"Safety", and
#: scaling a narrower window up to the README's 1200 would be a blurry picture
#: of a sharp app.
WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 900

#: How long to let the toolkit finish after a command before answering. The
#: expensive page (More Settings, 243 rows) builds in about 1.4 s, and a
#: colour-scheme change repaints everything on screen.
SETTLE_MS = 900


def say(text: str) -> None:
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


class Driver:
    """The window, and the one command it is currently working through."""

    def __init__(self, app: Adw.Application) -> None:
        self.window = Window(Prefs(), application=app)
        self.window.set_default_size(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.window.present()
        self.style = Adw.StyleManager.get_default()
        GLib.unix_fd_add_full(GLib.PRIORITY_DEFAULT, 0, GLib.IOCondition.IN, self._on_stdin)
        self._answer_after(SETTLE_MS, "ready")

    # -- the conversation --------------------------------------------------

    def _on_stdin(self, _fd: int, _condition: int) -> bool:
        line = sys.stdin.readline()
        if not line:
            self.window.get_application().quit()
            return GLib.SOURCE_REMOVE
        verb, _, argument = line.strip().partition(" ")
        if verb == "quit":
            say("bye")
            self.window.get_application().quit()
            return GLib.SOURCE_REMOVE
        try:
            self._do(verb, argument.strip())
        except Exception as exc:  # noqa: BLE001 - a refusal is an answer too
            say(f"error {type(exc).__name__}: {exc}")
            return GLib.SOURCE_CONTINUE
        self._answer_after(SETTLE_MS, "ok")
        return GLib.SOURCE_CONTINUE

    def _do(self, verb: str, argument: str) -> None:
        if verb == "mode":
            # Forced, not preferred: the sandbox desktop has its own opinion,
            # and a screenshot pair that differs because the *desktop* changed
            # its mind halfway through is not a light/dark pair.
            self.style.set_color_scheme(
                Adw.ColorScheme.FORCE_DARK if argument == "dark" else Adw.ColorScheme.FORCE_LIGHT
            )
        elif verb == "page":
            self.window.show_page(argument)
            # Every page is reached from the sidebar in real use, which means
            # the content half is showing. Below the breakpoint it would not be.
            self.window.split.set_show_content(True)
        else:
            raise ValueError(f"unknown command {verb!r}")

    def _answer_after(self, milliseconds: int, answer: str) -> None:
        def settled() -> bool:
            # Drain first: a timeout fires on the main loop, and anything the
            # page put on idle time is still queued behind it.
            context = GLib.MainContext.default()
            for _ in range(200):
                if not context.iteration(False):
                    break
            say(answer)
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(milliseconds, settled)


def main() -> int:
    Adw.init()
    Gtk.init()
    app = Adw.Application(application_id="io.github.blyatiful1.Gtheme.PageWalk")
    driver: dict[str, Driver] = {}

    def activate(application: Adw.Application) -> None:
        if not driver:
            driver["it"] = Driver(application)

    app.connect("activate", activate)
    started = time.monotonic()
    code = app.run([])
    print(f"page walk ran for {time.monotonic() - started:.1f}s", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
