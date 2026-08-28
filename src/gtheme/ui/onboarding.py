"""The first-run introduction: four slides, skippable, ending in a real action.

research/competitor-ux.md §6 argues this shape and rejects the alternative: a
wizard that drives someone through the live UI is brittle, expensive, and — the
real objection — it changes a person's desktop before they have any idea what
the app is. A carousel is the platform's own shape (GNOME Tour, Fractal,
Console), it is dismissible, and it can carry the two ideas that matter.

The four slides are fixed:

1. **What this is.** One sentence. No feature list.
2. **The safety promise** — the most important slide, and the one no competitor
   can show. It carries the security sentence verbatim from DESIGN.md A4 and
   SECURITY.md, because a promise that is reworded per surface is a promise
   nobody can check.
3. **Two ways to work.** Pick a whole look, or change one thing at a time.
4. **The first restore point.** A single button that really saves how the
   desktop looks now. The tour ends in an action, not in a "Get Started" no-op.

Skipping counts as finishing: an introduction that reappears because somebody
dismissed it "wrong" is worse than one nobody sees. The way back in is the
"Show the introduction again" entry the primary menu offers.

**The "Before gtheme" moment is taken here too, and not by the button.**
README and the Undo page both promise a row called "Before gtheme": how this
computer looked before this app ever changed anything. Until now that row could
only come from :func:`~gtheme.core.restorepoints.import_v1_baseline`, which
reads the old command-line gtheme's records — so on every fresh install, which
is everybody's install, the promise was empty (persona-report §2.3).
:func:`ensure_pristine_point` closes that: on a first run, before the reader has
touched anything, the desktop as it stands *is* "before gtheme", so it is
recorded under the same id, with the same label, as the imported one. It runs
once, it is never overwritten, and an upgrader still gets the richer v1 record
rather than a snapshot of a desktop v1 had already themed.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from ..core import applog, restorepoints  # noqa: E402
from ..core.restorepoints import PRISTINE_ID, RestorePoint  # noqa: E402
from ..core.settings_backend import SettingsBackend  # noqa: E402
from .applyrunner import ApplyRunner  # noqa: E402
from .pages import restore as restore_page  # noqa: E402

__all__ = [
    "COMPLETE_BANNER_ID",
    "MENU_LABEL",
    "PRISTINE_LABEL",
    "OnboardingDialog",
    "SECURITY_SENTENCE",
    "SLIDES",
    "Slide",
    "capture_pristine_point",
    "ensure_pristine_point",
    "mark_finished",
    "maybe_present",
    "should_show",
    "show_again",
]

_log = applog.logger(__name__)

#: Set once the introduction has been seen or skipped.
COMPLETE_BANNER_ID = "onboarding-complete"

#: The label the primary menu uses to bring the introduction back. The people
#: who need it most are the ones who pressed Skip.
MENU_LABEL = "Show the introduction again"

#: DESIGN.md A4, SECURITY.md, and this slide say the same sentence, letter for
#: letter. It is only true because the preset format has no way to run anything,
#: and it is the app's strongest single claim — so it is a constant, not a
#: string somebody can improve.
SECURITY_SENTENCE = (
    "Looks only change settings. They can't run programs on your computer."
)


@dataclass(frozen=True)
class Slide:
    """One page of the introduction."""

    icon: str
    title: str
    body: str


SLIDES: tuple[Slide, ...] = (
    Slide(
        icon="applications-graphics-symbolic",
        title="Change how your desktop looks",
        body=(
            "The background picture, the colours, the icons, the text — and "
            "extra features you can switch on. All in one place, in plain words."
        ),
    ),
    Slide(
        icon="edit-undo-symbolic",
        title="You can always go back",
        body=(
            "Before anything changes, gtheme saves how your desktop looks right "
            "now. One click puts it back.\n\n" + SECURITY_SENTENCE
        ),
    ),
    Slide(
        icon="view-grid-symbolic",
        title="Two ways to work",
        body=(
            "Pick a whole look and change everything at once — or change one "
            "thing at a time, from the list down the side."
        ),
    ),
    Slide(
        icon="document-save-symbolic",
        title="Save how it looks now",
        body=(
            "Start with a saved moment of your desktop exactly as it is. "
            "Then try anything you like."
        ),
    ),
)

#: What the moment taken on a first run is called, wherever it is listed. The
#: same words the Undo page uses for the one imported from the old command-line
#: gtheme, because they are the same thing: this desktop before this app
#: changed anything.
PRISTINE_LABEL = "Before gtheme"

#: What the last slide's button says, before and after it has been pressed.
SAVE_LABEL = "Save how it looks now"
SAVED_LABEL = "Saved. You can come back to this any time."
SAVE_FAILED_LABEL = "That could not be saved, but nothing was changed."
SKIP_LABEL = "Skip"
NEXT_LABEL = "Next"
DONE_LABEL = "Start using gtheme"


def should_show(prefs: Any | None) -> bool:
    """Whether this is a first run. False when there are no preferences to ask."""
    if prefs is None:
        return False
    return prefs.should_show_banner(COMPLETE_BANNER_ID)


def mark_finished(prefs: Any | None) -> None:
    """Record that the introduction has been seen. Skipping counts."""
    if prefs is not None:
        prefs.mark_banner_seen(COMPLETE_BANNER_ID)


# --------------------------------------------------------------------------
# "Before gtheme" — the moment that has to exist before anything else happens
# --------------------------------------------------------------------------


def capture_pristine_point(
    *,
    backend: SettingsBackend | None = None,
    root: str | Path | None = None,
    keys: Iterable[str] | None = None,
    dests: Iterable[str] | None = None,
) -> RestorePoint | None:
    """Make the "Before gtheme" moment exist. No widgets, no thread.

    Three answers, in this order, and the order is the whole design:

    1. **It already exists.** Nothing is written. The moment before gtheme
       arrived happened once and cannot happen again, so this function will
       never overwrite one — not on a second launch, not after a hundred Looks.
       That is the same guarantee
       :attr:`~gtheme.core.restorepoints.RestorePoint.kind` ``"pristine"``
       already had against pruning, extended to the writing side.
    2. **The old command-line gtheme ran here.** Then the honest record is v1's
       own baseline, not what this desktop looks like today — v1 had already
       themed it. :func:`~gtheme.core.restorepoints.import_v1_baseline` is
       tried first for exactly that reason, and an upgrader keeps the record
       they have always had.
    3. **Neither.** Then this desktop, right now, before the reader has pressed
       anything, *is* how it looked before gtheme. It is recorded over the same
       two lists a hand-saved moment covers — every setting gtheme knows how to
       change (:func:`~gtheme.ui.pages.restore.descriptor_keys`) and every file
       the ownership ledger claims — under the fixed id and the same label, so
       the Undo page draws it exactly like an imported one.

    Args:
        backend: where current values are read from. Defaults to the process
            backend.
        root: where saved moments live. Defaults to the real state directory.
        keys/dests: override what is covered. For tests that do not want to
            read five hundred real settings.

    Returns:
        The moment, or None when there already was one.
    """
    if restorepoints.load(PRISTINE_ID, root=root) is not None:
        return None
    imported = restorepoints.import_v1_baseline(root=root)
    if imported is not None:
        return imported
    covered = list(keys) if keys is not None else restore_page.descriptor_keys()
    files = list(dests) if dests is not None else restore_page.claimed_dests()
    return restorepoints.capture(
        covered,
        files,
        label=PRISTINE_LABEL,
        kind="pristine",
        backend=backend,
        root=root,
        point_id=PRISTINE_ID,
    )


def ensure_pristine_point(
    window: Any | None = None,
    *,
    backend: SettingsBackend | None = None,
    root: str | Path | None = None,
    keys: Iterable[str] | None = None,
    dests: Iterable[str] | None = None,
    runner: ApplyRunner | None = None,
) -> RestorePoint | None:
    """Do :func:`capture_pristine_point`, off the main loop, saying nothing.

    Reading five hundred settings and copying the files the ledger claims is
    the same work slide four does, and doing it in the handler that opens the
    introduction would freeze the first thing this app ever shows anybody
    (review-report M10). So it goes through an :class:`~gtheme.ui.applyrunner.ApplyRunner`
    like every other slow thing in the app.

    It goes through a runner of its own rather than the window's, and that
    runner is given no window, so no progress dialog is presented. This is the
    one piece of slow work in gtheme that changes *nothing a person can see* —
    it only writes gtheme's own record of a desktop it is not touching — and a
    modal dialog in front of the welcome screen, explaining a thing that is not
    happening to their computer, would be noise at the worst possible moment.
    A failure is logged rather than announced: what it costs is the "Before
    gtheme" row, and there is nothing the reader could do about it anyway.

    Returns:
        The moment when the work ran here (no runner, and no window to have
        one), None when it was handed to a runner or there was nothing to do.
    """

    def work(_narrate: Any = None) -> RestorePoint | None:
        return capture_pristine_point(backend=backend, root=root, keys=keys, dests=dests)

    def done(point: RestorePoint | None) -> None:
        if point is not None:
            _log.info("saved the %r moment (%d settings)", point.label, len(point.settings))

    def failed(error: Exception) -> None:
        _log.warning("could not save the %r moment: %s", PRISTINE_LABEL, error)

    active = runner if runner is not None else (ApplyRunner(None) if window is not None else None)
    if active is None:
        try:
            point = work()
        except Exception as error:  # noqa: BLE001 - a first run must never end in a traceback
            failed(error)
            return None
        done(point)
        return point
    active.run(
        work,
        heading=PRISTINE_LABEL,
        starting=restore_page.COPY["save-subtitle"],
        on_done=done,
        on_failed=failed,
    )
    return None


class OnboardingDialog(Adw.Dialog):
    """The four-slide introduction.

    Args:
        window: the app window. Used for its preferences, for a toast, and to
            drop the reader on the Looks page at the end. Every use is
            optional, so the dialog can be built in a test with no window at
            all.
        on_save: what the last slide's button does. Defaults to really saving a
            restore point; a test passes its own.
        backend/root: passed to the default save.
    """

    __gtype_name__ = "GthemeOnboardingDialog"

    def __init__(
        self,
        window: Any | None = None,
        *,
        on_save: Callable[[], Any] | None = None,
        backend: SettingsBackend | None = None,
        root: str | Path | None = None,
    ) -> None:
        super().__init__(content_width=520, content_height=560, title="Welcome")
        self.window = window
        self.backend = backend
        self.root = root
        self._on_save = on_save
        self.saved: Any = None

        self.carousel = Adw.Carousel(vexpand=True, allow_long_swipes=True)
        for slide in SLIDES:
            self.carousel.append(self._slide_widget(slide))

        self.skip_button = Gtk.Button(label=SKIP_LABEL)
        self.skip_button.connect("clicked", lambda *_a: self.finish())
        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        header.pack_start(self.skip_button)

        dots = Adw.CarouselIndicatorDots(carousel=self.carousel, margin_bottom=6)

        self.next_button = Gtk.Button(label=NEXT_LABEL, css_classes=["pill"], halign=Gtk.Align.CENTER)
        self.next_button.connect("clicked", lambda *_a: self.advance())

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_bottom=18)
        box.append(self.carousel)
        box.append(dots)
        box.append(self.next_button)

        view = Adw.ToolbarView(content=box)
        view.add_top_bar(header)
        self.set_child(view)

        self._index = 0
        self.carousel.connect("notify::position", lambda *_a: self._follow_position())
        self._sync_buttons()

    # -- slides ------------------------------------------------------------

    def _slide_widget(self, slide: Slide) -> Gtk.Widget:
        status = Adw.StatusPage(
            icon_name=slide.icon,
            title=slide.title,
            description=slide.body,
            vexpand=True,
        )
        if slide is not SLIDES[-1]:
            return status
        self.save_button = Gtk.Button(
            label=SAVE_LABEL,
            css_classes=["suggested-action", "pill"],
            halign=Gtk.Align.CENTER,
        )
        self.save_button.connect("clicked", lambda *_a: self.save_first_restore_point())
        self.save_status = Gtk.Label(label="", wrap=True, css_classes=["dim-label"])
        holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        holder.append(self.save_button)
        holder.append(self.save_status)
        status.set_child(holder)
        return status

    # -- navigation --------------------------------------------------------

    @property
    def index(self) -> int:
        """Which slide is showing.

        Tracked here rather than read back from the carousel's position on
        every question: the position only moves once the carousel has been laid
        out, so a carousel that has not been shown yet reports slide one however
        many times it has been told to scroll. Swiping is followed the other
        way, by :meth:`_follow_position`.
        """
        return self._index

    def _follow_position(self) -> None:
        """Keep :attr:`index` in step when the reader swipes instead of clicking."""
        moved = int(round(self.carousel.get_position()))
        if moved != self._index:
            self._index = moved
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        last = self.index >= len(SLIDES) - 1
        self.next_button.set_label(DONE_LABEL if last else NEXT_LABEL)
        self.skip_button.set_visible(not last)

    def advance(self) -> None:
        """Next slide, or finish when there is no next slide."""
        if self._index >= len(SLIDES) - 1:
            self.finish()
            return
        self._index += 1
        self.carousel.scroll_to(self.carousel.get_nth_page(self._index), True)
        self._sync_buttons()

    # -- the real action ---------------------------------------------------

    def save_first_restore_point(self) -> Any:
        """Slide four's button: really save how the desktop looks now.

        On the shared runner when there is one. Saving a moment reads every
        setting gtheme knows about — around five hundred of them — and copies
        every file the ownership ledger claims, and doing that in the click
        handler froze the introduction on its last slide, which is the first
        thing this app ever does in front of a new user (review-report M10).
        The same button on the Home page and on the Undo page has the same
        treatment.

        Returns:
            The saved moment when the work ran here, and None when it was
            handed to the runner (it lands in :attr:`saved` a moment later) or
            could not be done at all.
        """
        runner = self._runner()
        if runner is None:
            try:
                return self._saved_now(self._save())
            except Exception:  # noqa: BLE001 - the introduction must never end in a traceback
                self.save_status.set_label(SAVE_FAILED_LABEL)
                return None
        runner.run(
            lambda _narrate: self._save(),
            heading=restore_page.COPY["save-title"],
            starting=restore_page.COPY["save-subtitle"],
            on_done=self._saved_now,
            on_failed=lambda _error: self.save_status.set_label(SAVE_FAILED_LABEL),
        )
        return None

    def _runner(self) -> ApplyRunner | None:
        """The window's runner, or None when there is no window to have one."""
        runner = getattr(self.window, "runner", None)
        return runner if isinstance(runner, ApplyRunner) else None

    def _save(self) -> Any:
        """The engine half of slide four. No widgets, no thread."""
        if self._on_save is not None:
            return self._on_save()
        return restore_page.create_restore_point(backend=self.backend, root=self.root)

    def _saved_now(self, saved: Any) -> Any:
        """Back on the main loop: the moment is saved, so say so."""
        self.saved = saved
        self.save_button.set_sensitive(False)
        self.save_status.set_label(SAVED_LABEL)
        toast = getattr(self.window, "toast", None)
        if callable(toast):
            toast(restore_page.COPY["saved"])
        return saved

    def finish(self) -> None:
        """Remember that this has been seen, and get out of the way.

        The reader lands on Looks, which is the whole app for most people
        (research/competitor-ux.md P8, tier one).
        """
        mark_finished(getattr(self.window, "prefs", None))
        show_page = getattr(self.window, "show_page", None)
        if callable(show_page):
            show_page("looks")
        self.close()


def show_again(window: Any | None = None, **kwargs: Any) -> OnboardingDialog:
    """Open the introduction, whether or not it has been seen. The menu entry."""
    dialog = OnboardingDialog(window, **kwargs)
    if isinstance(window, Gtk.Widget):
        dialog.present(window)
    return dialog


def maybe_present(window: Any | None = None, **kwargs: Any) -> OnboardingDialog | None:
    """Show the introduction if this is a first run. Returns it if it was shown.

    A first run is also the one moment at which "Before gtheme" can honestly be
    recorded, so it is recorded here — in the background, before the reader has
    pressed anything. Deliberately tied to the first run rather than to "there
    is no pristine moment yet": on the tenth launch this desktop has already
    been changed, and calling a snapshot of it "Before gtheme" would be a lie in
    the one place the app cannot afford one.
    """
    if not should_show(getattr(window, "prefs", None)):
        return None
    ensure_pristine_point(
        window, backend=kwargs.get("backend"), root=kwargs.get("root")
    )
    return show_again(window, **kwargs)


def copy_strings() -> Iterable[tuple[str, str]]:
    """``(where, text)`` pairs for the jargon lint."""
    pairs = [
        ("onboarding.menu", MENU_LABEL),
        ("onboarding.security", SECURITY_SENTENCE),
        ("onboarding.save", SAVE_LABEL),
        ("onboarding.saved", SAVED_LABEL),
        ("onboarding.save-failed", SAVE_FAILED_LABEL),
        ("onboarding.done", DONE_LABEL),
    ]
    for number, slide in enumerate(SLIDES, start=1):
        pairs.append((f"onboarding.slide{number}.title", slide.title))
        pairs.append((f"onboarding.slide{number}.body", slide.body))
    return pairs
