"""The Adw.Application. Everything graphical starts here.

Nothing else in gtheme may import this module at module scope — ``cli.py``
imports it inside the ``gui`` handler on purpose, so that ``gtheme rescue``
runs on a machine where GTK cannot even be loaded. That is the whole point of
the rescue path.

The application object is deliberately thin. It owns the process-wide things —
the app id, the two application actions, the preferences file — and hands
everything else to the window, which is where the app actually lives. The one
thing it does that the window cannot is decide whether this is somebody's first
run: :func:`~gtheme.ui.onboarding.maybe_present` is called after the window is
on screen, so the introduction appears over a real app rather than over grey.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, __version__  # noqa: E402
from .core import applog  # noqa: E402
from .prefs import Prefs  # noqa: E402
from .ui import onboarding  # noqa: E402
from .window import Window  # noqa: E402

__all__ = ["Application", "run"]

_log = applog.logger(__name__)


class Application(Adw.Application):
    """gtheme's application object."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
            **kwargs,
        )
        self.prefs = Prefs()
        self._action("quit", lambda *_: self.quit(), ["<primary>q"])
        self._action("about", lambda *_: self._on_about(), ["F1"])

    def do_activate(self) -> None:  # noqa: N802 - GObject vfunc name
        window = self.props.active_window or Window(self.prefs, application=self)
        window.present()
        # After present(), not before: the introduction is a dialog, and a
        # dialog belongs to a window that is on screen. Once somebody has
        # finished or skipped it, this is a no-op forever.
        if isinstance(window, Window) and window.verdict.ok:
            GLib.idle_add(_present_onboarding, window)

    def _action(self, name: str, callback: Callable[..., Any], accels: list[str] | None = None) -> None:
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if accels:
            self.set_accels_for_action(f"app.{name}", accels)

    def _on_about(self) -> None:
        window = self.props.active_window
        if isinstance(window, Window):
            window.show_about()


def _present_onboarding(window: Window) -> bool:
    onboarding.maybe_present(window)
    return GLib.SOURCE_REMOVE


def run(argv: list[str] | None = None) -> int:
    """Open the app. Returns the process exit code."""
    # Before anything graphical: a GTK signal handler that raises prints its
    # traceback through sys.excepthook, and the launcher sets Terminal=false,
    # so without this the traceback goes to a console nobody is watching.
    applog.start()
    _log.info("opening gtheme %s", __version__)
    Adw.init()
    Gtk.init()
    code = Application().run(argv or [])
    _log.info("the app closed with %s", code)
    return code
