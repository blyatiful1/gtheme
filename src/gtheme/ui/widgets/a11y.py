"""Names for the parts of the app that are pictures.

persona-report §2.10, the whole of it in one sentence: a grep for
``alternative_text`` or ``AccessibleProperty`` over ``src/`` returned exactly
one line — the nine accent dots on the Colours page. Every other picture in
gtheme, and this is an app whose entire premise is "choose by looking", was a
bare :class:`Gtk.Picture` or a :class:`Gtk.Image` inside a button with a
tooltip on it.

Three rules are worth saying out loud, because getting them wrong is what makes
a page *look* accessible while reading as noise:

* **A tooltip is a description, not a name.** GTK maps ``tooltip-text`` to the
  accessible *description*, which a screen reader reads after the name, and
  often not at all. A tile whose only text was its tooltip had no name.
* **A picture that repeats what the label already says should be quiet.** Four
  sample icons in front of every icon-set tile are the tile's picture, not four
  more things to announce.
* **The name says what choosing it does, not what it is called.** "Papirus" is
  a word; "Papirus icon set" is a choice.

Deliberately three one-line functions rather than a policy engine: what makes
this hard is remembering to do it, not doing it.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk  # noqa: E402

__all__ = ["describe", "hide_from_screen_readers", "name"]


def name(widget: Gtk.Widget, text: str) -> None:
    """Give a widget the name a screen reader announces it by.

    Use for anything whose visible identity is a picture, or whose label is
    ellipsised, or that carries only a tooltip.
    """
    widget.update_property([Gtk.AccessibleProperty.LABEL], [text])


def describe(widget: Gtk.Widget, text: str) -> None:
    """Add the sentence that comes *after* the name — never instead of it."""
    widget.update_property([Gtk.AccessibleProperty.DESCRIPTION], [text])


def hide_from_screen_readers(widget: Gtk.Widget) -> None:
    """Take a decorative picture out of the accessibility tree.

    For pictures that illustrate a control which already has a name: the swatch
    beside a colour whose name is in the row, the sample icons inside a tile
    that is named after the set they came from.
    """
    widget.update_state([Gtk.AccessibleState.HIDDEN], [True])
