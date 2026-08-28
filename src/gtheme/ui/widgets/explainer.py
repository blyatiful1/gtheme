"""The first-visit explainer. One banner, every page.

Eleven pages open with a dismissible sentence saying what the page is for, and
until this module existed each of them built its own. They had already drifted
in three ways at once (review-report M28), and every one of the three is a way
a user notices:

* **Wording.** ``BANNER_DISMISS`` existed and three sites used it; the rest
  wrote ``"Got it"`` by hand. Changing the word would have changed it on three
  pages and left the other eight saying something else.
* **Markup.** Two sites escaped the sentence and seven did not — and the two
  were the wrong ones. ``Adw.Banner:use-markup`` defaults to **off** (measured
  against libadwaita 1.9.3), so an escaped sentence renders its own escape: a
  banner mentioning "Fonts & Text" would have read "Fonts &amp;amp; Text" on
  screen. The seven raw ones rendered correctly and printed a markup-parse
  warning on the way, because the internal label parses the title before the
  property is applied. Turning markup off first and then setting the text —
  which is what :func:`~gtheme.ui.widgets.rows.set_plain_text` does — is the
  only one of the three that is right on both counts.
* **The missing preferences file.** Four sites checked for it, two dereferenced
  it, and two disagreed about what to do without one.

So there is one answer to each here, and pages ask for a banner rather than
building one.

**Without a preferences store there is no banner.** "Seen" is sticky because a
banner that comes back reads as a bug (``prefs`` module docstring); with nowhere
to record the dismissal, showing it would mean showing it on every single visit
forever. Not showing it is the smaller loss, and it is what most of the pages
already did.

The dismiss wording itself is not defined here. It sits with the app's other
standing wording in :mod:`gtheme.ui.search`, which imports no toolkit and is
already read by the plain-language lint.
"""

from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from ..search import BANNER_DISMISS  # noqa: E402
from .rows import set_plain_text  # noqa: E402

__all__ = [
    "BANNER_DISMISS",
    "first_visit_banner",
    "with_first_visit_banner",
]


def first_visit_banner(
    prefs: Any,
    banner_id: str,
    text: str,
    *,
    keep_hidden: bool = False,
) -> Adw.Banner | None:
    """The one-shot explainer for a page, or None when it is not wanted.

    Args:
        prefs: the app preferences, which remember the dismissal. None — a
            window with nowhere to write — means no banner at all.
        banner_id: the key in ``prefs.json``. Every one of them is listed in
            :data:`gtheme.prefs.KNOWN_BANNERS`, and a test holds those two
            lists to each other in both directions.
        text: the sentence. Set as text, never as markup, and never escaped —
            an escaped ``&`` in a banner is read out loud as ``&amp;``.
        keep_hidden: build the banner even when it has already been dismissed,
            revealed=False. For the one page that keeps the widget as a member
            and reveals it later; everywhere else, a page that is not showing
            an explainer should not be holding one.

    Returns:
        The banner, already wired to remember its own dismissal, or None.
    """
    show = prefs is not None and prefs.should_show_banner(banner_id)
    if not show and not keep_hidden:
        return None

    banner = Adw.Banner(button_label=BANNER_DISMISS, revealed=show)
    set_plain_text(banner, title=text)

    def dismissed(*_args: Any) -> None:
        banner.set_revealed(False)
        if prefs is not None:
            prefs.mark_banner_seen(banner_id)

    banner.connect("button-clicked", dismissed)
    return banner


def with_first_visit_banner(
    page: Gtk.Widget,
    prefs: Any,
    banner_id: str,
    text: str,
) -> Gtk.Widget:
    """``page`` with its explainer above it — or ``page`` itself, untouched.

    The banner is stacked above the page rather than placed inside it because a
    page is often an ``Adw.PreferencesPage``, which holds groups and nothing
    else. Returning the page unchanged when there is no banner matters: a
    wrapper box left behind on every later visit is a widget in the tree that
    the test asking "is the explainer gone?" would have to know to look past.
    """
    banner = first_visit_banner(prefs, banner_id, text)
    if banner is None:
        return page
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, vexpand=True)
    box.append(banner)
    page.set_vexpand(True)
    box.append(page)
    return box
