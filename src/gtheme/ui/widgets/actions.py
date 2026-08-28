"""A row that does something: a sentence, and a button that does it.

Home and Undo & Restore Points both open with the app's safety pair — "save
this moment" and "undo the last change" — and each of them had its own
byte-identical copy of the row that draws one (review-report L16, ``home
._action_row`` and ``restore._button_row``). They are the two rows this app is
most careful about, and a busy state, a mnemonic or an accessible label added
to one of them would have landed on one page only.

The row is deliberately activatable through its button: pressing Enter on the
row does what the button does, so the safety actions are reachable without a
pointer.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from .rows import set_plain_text  # noqa: E402

__all__ = ["action_row"]


def action_row(
    title: str,
    subtitle: str,
    button_label: str,
    callback: Callable[[], Any],
    *,
    suggested: bool = False,
) -> Adw.ActionRow:
    """One thing a person can do, said in words and offered as a button.

    Args:
        title: what this does. Set as text, not markup.
        subtitle: the sentence under it, saying what will happen.
        button_label: what the button says. A verb, never "OK".
        callback: called with no arguments when the button is pressed. Its
            return value is ignored, so a handler that returns something is
            not a mistake here.
        suggested: whether this is the action the page is recommending. At
            most one row on a page should say yes.
    """
    row = Adw.ActionRow()
    set_plain_text(row, title=title, subtitle=subtitle)
    button = Gtk.Button(label=button_label, valign=Gtk.Align.CENTER)
    if suggested:
        button.add_css_class("suggested-action")
    button.connect("clicked", lambda *_a: callback())
    row.add_suffix(button)
    row.set_activatable_widget(button)
    return row
