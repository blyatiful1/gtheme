"""The Adw.Application. Everything graphical starts here.

Nothing else in gtheme may import this module at module scope — ``cli.py``
imports it inside the ``gui`` handler on purpose, so that ``gtheme rescue``
runs on a machine where GTK cannot even be loaded. That is the whole point of
the rescue path.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, Gtk  # noqa: E402

from . import APP_ID  # noqa: E402
from .prefs import Prefs  # noqa: E402
from .window import Window  # noqa: E402

__all__ = ["Application", "run"]


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
        self._action("about", lambda *_: self._on_about())

    def do_activate(self) -> None:  # noqa: N802 - GObject vfunc name
        window = self.props.active_window or Window(self.prefs, application=self)
        window.present()

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


def run(argv: list[str] | None = None) -> int:
    """Open the app. Returns the process exit code."""
    Adw.init()
    Gtk.init()
    return Application().run(argv or [])
