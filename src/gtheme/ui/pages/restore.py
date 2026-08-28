"""Undo & Restore Points — the page that makes the rest of the app safe to touch.

Every other page in gtheme changes the desktop. This one is the promise that
those changes are not permanent, and it is the single feature no competing GNOME
customisation tool has (research/competitor-ux.md §2: "no undo / no restore
point — **all eight**"). So it is written to be understood by someone who has
never used a computer as anything but a computer:

* a saved moment is called what it is — "My desktop, 25 August" — and is dated
  in words, never in a timestamp;
* the page says how much of putting things back is *removal*, because a restore
  that switches things off again surprises people who expect only additions;
* "Before gtheme" sits at the bottom, on its own, labelled with the Look that
  was on before this app ever ran.

**One apply path.** Going back to a moment is
:func:`gtheme.core.restorepoints.apply_point`, never a transaction assembled
here. That function's transaction carries the confinement preflight, the
pristine baseline, the ownership ledger and the all-or-nothing rollback; a
second implementation on a UI page would carry none of them and would be the
most dangerous code in the application.

The preview shown before an undo is the *plan* of that same transaction, read
through :meth:`gtheme.core.transaction.Diff.to_novice_lines`, so what the dialog
promises and what the engine does are the same object.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ...core import restorepoints  # noqa: E402
from ...core.backends import get_backend  # noqa: E402
from ...core.restorepoints import RestorePoint  # noqa: E402
from ...core.settings_backend import SettingsBackend  # noqa: E402
from ...panels.loader import load_corpus  # noqa: E402
from ..applyrunner import ApplyRunner  # noqa: E402
from ..widgets.actions import action_row  # noqa: E402
from ..widgets.explainer import first_visit_banner  # noqa: E402
from ..widgets.rows import key_for  # noqa: E402

__all__ = [
    "BANNER_ID",
    "COPY",
    "RestorePage",
    "absence_sentence",
    "build",
    "claimed_dests",
    "create_restore_point",
    "default_label",
    "coverage_keys",
    "descriptor_keys",
    "describe_point",
    "done_sentence",
    "failure_sentence",
    "point_title",
    "preview_lines",
    "save_failed_sentence",
    "undo_last_change",
]

#: The one-shot explainer shown the first time this page is opened.
BANNER_ID = "first-visit-restore"


#: Every sentence this page can say, in one place — so the jargon lint can read
#: them all, and so nobody has to hunt through widget code to change a word.
COPY: dict[str, str] = {
    "banner": (
        "A saved moment is how your whole desktop looked at one point in time. "
        "Going back to one puts the background picture, the colours and the "
        "add-ons back the way they were."
    ),
    "save-title": "Save how it looks now",
    "save-subtitle": (
        "Keeps a copy of your current look so you can come back to it later."
    ),
    "save-button": "Save",
    "undo-title": "Undo the last change",
    "undo-subtitle": "Goes back to how things were just before your most recent change.",
    "undo-button": "Undo",
    "undo-nothing": "Nothing has changed yet, so there is nothing to undo.",
    "list-title": "Saved moments",
    "list-empty-title": "No saved moments yet",
    "list-empty-body": (
        "gtheme saves one automatically before it changes anything. "
        "You can also save one yourself, any time."
    ),
    "pristine-title": "Before gtheme",
    "pristine-subtitle": "How this desktop looked before you ever used this app.",
    "apply-button": "Go back to this",
    "forget-button": "Forget this one",
    "confirm-heading": "Go back to this moment?",
    "confirm-named": "Going back to “{label}”.",
    "confirm-body": "Here is what will change on your desktop:",
    "confirm-cancel": "Keep things as they are",
    "confirm-accept": "Go back",
    "working-heading": "Putting your desktop back",
    "working": "Going back to how it was…",
    "done": "Your desktop is back the way it was.",
    # The same news, with the answer to "back to *what*?" in it. Going back can
    # be started from four places — this page's list, its Undo button, the Home
    # card and the header button that Ctrl+Z lands on — and three of those show
    # no list at the moment they finish, so "back the way it was" left the
    # person to work out which moment they had just landed on (persona-report
    # §2.8 / U8). The unnamed sentence above is still what a caller says when it
    # genuinely does not know which moment ran.
    "done-named": "Your desktop is back to “{label}”.",
    "saved": "Saved how your desktop looks right now. You can come back to it any time.",
    "save-failed": "Could not save how your desktop looks.",
    "failed": "Nothing was changed. Your desktop is exactly as it was.",
    # The other half of "it did not work", and the reason both sentences are
    # written out here: an app that says "Nothing was changed" over a desktop
    # that was half put back has told the person the one lie this page exists
    # to prevent (review-report H2). "Some of it may have been changed anyway."
    # is the same clause the compound page writes, word for word.
    # Two sentences, not three: this is a toast, and the list of saved moments
    # to try again from is already on screen behind it.
    "failed-half": "Going back did not finish. Some of it may have been changed anyway.",
    "gone": "That saved moment is no longer there.",
}

#: How many saved moments the list renders at once. The engine keeps ten.
LIST_LIMIT = 12


# --------------------------------------------------------------------------
# what a restore point covers, and how to say it
# --------------------------------------------------------------------------


def descriptor_keys(corpus: Any | None = None) -> list[str]:
    """Every setting gtheme knows how to change, as backend key strings.

    What is not captured cannot be put back, so the list that is saved and the
    list of settings the app can change are deliberately the same list. That is
    two sources, not one, and missing either leaves a hole a person would only
    find by pressing Undo and watching it not work:

    * the **descriptor corpus** — every hand-written row, including the add-on
      panels, whose values may live in a relocatable place or in the add-on's
      own settings file rather than under a plain schema;
    * the **coverage manifest** — the settings that have no row of their own but
      that the app still changes: the ``compound`` keys written two at a time by
      one control (light-or-dark writes two; switching an add-on on merges into
      a list), and the ``floor`` keys the More Settings page renders from the
      system's own descriptions.

    Only ``excluded`` and ``delegated`` keys are left out, which is exactly the
    set gtheme never writes.
    """
    loaded = corpus if corpus is not None else load_corpus()
    keys: list[str] = []
    seen: set[str] = set()
    for row in loaded.rows:
        if not row.key:
            continue
        key = key_for(row)
        if key not in seen:
            seen.add(key)
            keys.append(key)
    for key in coverage_keys():
        if key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


def coverage_keys(directory: Path | str | None = None) -> list[str]:
    """The settings named in ``coverage.toml`` that gtheme is allowed to write.

    A different question from :func:`gtheme.ui.registry.resolve_surfaced`,
    which answers "which page shows which row" and deliberately drops the
    ``compound`` keys. A saved moment that dropped them would not record
    light-or-dark or which add-ons were on, which are the two things people
    undo most.

    This page used to open and parse ``coverage.toml`` itself to keep that
    difference. The difference is a function name now, and the file has one
    reader.
    """
    from ...panels.loader import captured_keys

    return captured_keys(directory)


def claimed_dests(path: str | Path | None = None) -> list[str]:
    """Every file the ownership ledger currently claims, as absolute paths.

    A hand-saved moment used to record no files at all, because nothing passed
    ``dests`` to :func:`gtheme.core.restorepoints.capture` — so "how my whole
    desktop looked" covered the settings and none of the files, and going back
    to it left every file a Look had installed exactly as the Look wrote it
    (review-report H11). The four shipped Looks write between 15 and 20 files
    each, one of them the user's own ``starship.toml``.

    The ledger is the honest answer to "which files could differ between now
    and the moment being restored?": it is written before every change, it is
    keyed by owner rather than by anything a corpus knows, and the user's own
    page edits are in it too under ``MANUAL_OWNER``. It is read through the
    ledger module's own API, never by parsing its file here — the same rule
    :func:`gtheme.core.restorepoints._claimed_settings` follows for keys.

    A claimed destination that is not there right now is not skipped: "there
    was nothing here" is a state, and recording it is what lets going back
    remove a file that was installed over nothing.
    """
    from ...core.ledger import read_ledger

    dests: list[str] = []
    for owned in read_ledger(path).values():
        if not isinstance(owned, dict):
            continue
        dests.extend(dest for dest in owned.get("files", []) if isinstance(dest, str))
    return sorted(set(dests))


def point_title(point: RestorePoint) -> str:
    """What a saved moment is called on screen.

    "Before gtheme" is a title this page gives, not a label the engine stores,
    so every surface that names a moment — the list, the confirmation, the
    header button's dialog — has to give the pristine one the same name or two
    parts of the app end up calling one thing two things.
    """
    return COPY["pristine-title"] if point.kind == "pristine" else point.label


def done_sentence(point: RestorePoint | None) -> str:
    """What to say when going back worked, naming the moment it went back to.

    The counterpart of :func:`failure_sentence`, and the reason both live here
    rather than at the four call sites: every surface that can start an undo —
    this page's list, its own Undo button, the Home card and the header button
    Ctrl+Z lands on — has to say the same thing about the same event, and three
    of the four have no list on screen when they say it.

    ``None`` is a real answer, not a defensive default: it means the caller
    genuinely could not say which moment ran (a saved moment deleted between
    the click and the finish), and inventing a name for it would be worse than
    the plainer sentence.
    """
    if point is None:
        return COPY["done"]
    return COPY["done-named"].format(label=point_title(point))


def failure_sentence(reason: str, *, rolled_back: bool) -> str:
    """What to say when going back did not happen: why, and where that leaves it.

    Two outcomes, two different things to say, and only one of them is
    reassuring. Rolled back means the desktop really is exactly as it was. Not
    rolled back means part of the moment was written and part was not, and
    saying "Nothing was changed" over that is the failure this page exists to
    prevent (review-report H2/L1).
    """
    state = COPY["failed"] if rolled_back else COPY["failed-half"]
    said = _sentence(reason)
    return f"{said} {state}" if said else state


def save_failed_sentence(error: BaseException) -> str:
    """What to say when a moment could not be saved, wherever it was asked for.

    The Home page has the same button and used to compose its own version of
    this sentence two words differently. One wording, one place, both buttons.
    """
    detail = _sentence(str(getattr(error, "strerror", None) or error))
    return f"{COPY['save-failed']} {detail}" if detail else COPY["save-failed"]


def _sentence(text: str) -> str:
    """A fragment written somewhere else, said as a sentence.

    Engine warnings are phrases meant to be dropped into somebody else's
    sentence ("that saved moment is no longer there"). A toast is not somebody
    else's sentence, so they get a capital and a full stop rather than being
    shown as the fragment they are.
    """
    said = (text or "").strip().rstrip(".")
    return f"{said[0].upper()}{said[1:]}." if said else ""


def default_label(when: datetime | None = None) -> str:
    """"My desktop, 25 August" — what a saved moment is called by default."""
    moment = when or datetime.now()
    return f"My desktop, {moment.strftime('%-d %B')}"


def create_restore_point(
    label: str | None = None,
    *,
    backend: SettingsBackend | None = None,
    root: str | Path | None = None,
    corpus: Any | None = None,
    keys: Sequence[str] | None = None,
    dests: Sequence[str] | None = None,
) -> RestorePoint:
    """Save how the desktop looks right now, and return the saved moment.

    Args:
        label: what to call it. Defaults to :func:`default_label`.
        backend: where the current values are read from.
        root: where saved moments live. Defaults to the real state directory.
        corpus: the descriptor corpus, when it has already been loaded.
        keys: the exact keys to record. Overrides ``corpus``; used by tests
            that do not want to read the whole shipped corpus.
        dests: the exact files to copy. Defaults to :func:`claimed_dests` —
            everything the ownership ledger says gtheme is responsible for
            right now, which is the set that can differ between now and the
            moment being restored. Passing nothing at all here is what made a
            hand-saved moment cover no files (review-report H11).
    """
    covered = list(keys) if keys is not None else descriptor_keys(corpus)
    files = list(dests) if dests is not None else claimed_dests()
    return restorepoints.capture(
        covered,
        files,
        label=label or default_label(),
        kind="manual",
        backend=backend if backend is not None else get_backend(),
        root=root,
    )


def absence_sentence(point: RestorePoint) -> str | None:
    """How much of going back to this moment is *removing* things.

    Two thirds of the "Before gtheme" point on the machine this was written on
    is absence: settings that had no value, and files that were not there.
    Saying "12 things go back" while silently switching six add-ons off is how
    an undo button loses somebody's trust the first time they press it.
    """
    unset = len(point.keys_to_unset)
    removed = len(point.files_to_remove)
    if not unset and not removed:
        return None
    parts = []
    if unset:
        parts.append(f"{unset} setting{'s' if unset != 1 else ''} that had never been changed")
    if removed:
        parts.append(f"{removed} file{'s' if removed != 1 else ''} that was not there")
    return "Going back to this also undoes " + " and ".join(parts) + "."


def describe_point(point: RestorePoint) -> str:
    """The subtitle under a saved moment: when it was, and how big it is."""
    covered = len(point.settings) + len(point.files)
    if covered:
        return f"{point.human_date()} · covers {covered} setting{'s' if covered != 1 else ''}"
    return point.human_date()


def preview_lines(
    point: RestorePoint,
    *,
    backend: SettingsBackend | None = None,
    dest_root: str | Path | None = None,
) -> list[str]:
    """What going back to this moment would change, in the user's own words.

    The plan of the very transaction :func:`restorepoints.apply_point` will run
    — not a second description of it. When the plan cannot be worked out (a
    saved moment whose files have gone missing, no settings store to read), the
    answer is an honest empty list and the dialog says so, rather than a
    confident sentence nobody checked.
    """
    try:
        transaction = point.to_transaction()
        if backend is not None:
            transaction.backend = backend
        if dest_root is not None:
            transaction.dest_root = str(dest_root)
        return transaction.plan().to_novice_lines()
    except Exception:  # noqa: BLE001 - a preview that fails must not block the undo
        return []


def undo_last_change(
    *,
    root: str | Path | None = None,
    backend: SettingsBackend | None = None,
    dest_root: str | Path | None = None,
    progress_cb: Callable[..., Any] | None = None,
) -> tuple[RestorePoint | None, restorepoints.RestoreResult | None]:
    """Go back to the most recent saved moment. Backs the header button.

    Returns ``(point, result)``; ``(None, None)`` when nothing has been saved
    yet, which is the honest answer on a desktop nobody has changed.
    """
    points = [p for p in restorepoints.list_restore_points(root) if p.kind != "pristine"]
    if not points:
        return None, None
    newest = points[0]
    result = restorepoints.apply_point(
        newest.id, progress_cb, root=root, backend=backend, dest_root=dest_root
    )
    return newest, result


# --------------------------------------------------------------------------
# the page
# --------------------------------------------------------------------------


class RestorePage(Adw.Bin):
    """The Undo & Restore Points page.

    Everything the page needs from the outside is an argument, so the whole
    page can be constructed in a test against an in-memory settings backend and
    a temporary directory, with nothing on this machine's desktop at risk.
    """

    __gtype_name__ = "GthemeRestorePage"

    def __init__(
        self,
        window: Any | None = None,
        *,
        backend: SettingsBackend | None = None,
        root: str | Path | None = None,
        corpus: Any | None = None,
        keys: Sequence[str] | None = None,
        dest_root: str | Path | None = None,
        import_v1: bool = True,
    ) -> None:
        super().__init__()
        self.window = window
        self.backend = backend
        self.root = root
        self.corpus = corpus
        self.keys = list(keys) if keys is not None else None
        self.dest_root = dest_root

        if import_v1:
            # Idempotent, and None on a fresh install — which is normal, not an
            # error. Doing it here means the "Before gtheme" row exists the
            # first time somebody looks for it rather than after a restart.
            try:
                restorepoints.import_v1_baseline(root=root)
            except OSError:
                pass

        self._page = Adw.PreferencesPage()
        self.set_child(self._page)
        self._list_group: Adw.PreferencesGroup | None = None
        self._rows: list[Gtk.Widget] = []
        self._build()

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        banner = first_visit_banner(
            getattr(self.window, "prefs", None), BANNER_ID, COPY["banner"]
        )
        if banner is not None:
            group = Adw.PreferencesGroup()
            group.add(banner)
            self._page.add(group)

        actions = Adw.PreferencesGroup()
        actions.add(
            action_row(
                COPY["save-title"],
                COPY["save-subtitle"],
                COPY["save-button"],
                self._on_save,
                suggested=True,
            )
        )
        actions.add(
            action_row(
                COPY["undo-title"],
                COPY["undo-subtitle"],
                COPY["undo-button"],
                self._on_undo,
            )
        )
        self._page.add(actions)

        self._list_group = Adw.PreferencesGroup(title=COPY["list-title"])
        self._page.add(self._list_group)
        self.refresh()

    # -- the list ----------------------------------------------------------

    def points(self) -> list[RestorePoint]:
        """The saved moments to show, newest first, "Before gtheme" last."""
        return restorepoints.list_restore_points(self.root)[:LIST_LIMIT]

    def refresh(self) -> None:
        """Rebuild the list of saved moments from disk."""
        group = self._list_group
        if group is None:
            return
        for child in list(self._rows):
            group.remove(child)
        self._rows.clear()

        points = self.points()
        if not points:
            empty = Adw.ActionRow(
                title=COPY["list-empty-title"],
                subtitle=COPY["list-empty-body"],
                sensitive=False,
            )
            group.add(empty)
            self._rows.append(empty)
            return

        for point in points:
            row = self._point_row(point)
            group.add(row)
            self._rows.append(row)

    def _point_row(self, point: RestorePoint) -> Adw.ActionRow:
        pristine = point.kind == "pristine"
        title = point_title(point)
        subtitle = self._pristine_subtitle() if pristine else describe_point(point)
        absence = absence_sentence(point)
        if absence:
            subtitle = f"{subtitle}\n{absence}"
        row = Adw.ActionRow(title=title, subtitle=subtitle, subtitle_lines=3)

        if not pristine:
            forget = Gtk.Button(
                icon_name="user-trash-symbolic",
                valign=Gtk.Align.CENTER,
                tooltip_text=COPY["forget-button"],
                css_classes=["flat"],
            )
            forget.connect("clicked", lambda *_a, p=point: self._on_forget(p))
            row.add_suffix(forget)

        apply_button = Gtk.Button(label=COPY["apply-button"], valign=Gtk.Align.CENTER)
        apply_button.connect("clicked", lambda *_a, p=point: self.confirm_apply(p))
        row.add_suffix(apply_button)
        row.set_activatable_widget(apply_button)
        return row

    def _pristine_subtitle(self) -> str:
        base = COPY["pristine-subtitle"]
        try:
            previous = restorepoints.read_v1_current()
        except OSError:  # pragma: no cover - defensive
            previous = None
        if previous:
            return f"{base} You were using {previous.upper()} then."
        return base

    # -- actions -----------------------------------------------------------

    def _toast(self, text: str) -> None:
        toast = getattr(self.window, "toast", None)
        if callable(toast):
            toast(text)

    def _on_save(self) -> None:
        """"Save how it looks now", on the shared runner.

        Saving a moment reads every setting gtheme knows about — some five
        hundred of them — and copies every file the ledger claims. Doing that
        in the click handler froze the window for the whole of it, two lines
        above an Undo button that had already been fixed to use the runner and
        says in its own docstring why (review-report M10). The same button on
        the Home page has always done it this way.
        """
        runner = self._runner()
        if runner is None:
            try:
                saved = self._save_now()
            except Exception as error:  # noqa: BLE001 - reported, never a traceback
                self._save_failed(error)
                return
            self._save_finished(saved)
            return
        runner.run(
            lambda _narrate: self._save_now(),
            heading=COPY["save-title"],
            starting=COPY["save-subtitle"],
            on_done=self._save_finished,
            on_failed=self._save_failed,
        )

    def _save_now(self) -> RestorePoint:
        """The engine half of "save how it looks now". No widgets, no thread."""
        return create_restore_point(
            backend=self.backend, root=self.root, corpus=self.corpus, keys=self.keys
        )

    def _save_finished(self, _point: RestorePoint | None = None) -> None:
        self._changed()
        self._toast(COPY["saved"])

    def _save_failed(self, error: BaseException) -> None:
        self._toast(save_failed_sentence(error))

    def _on_undo(self) -> None:
        """"Undo the last change", on the shared runner.

        Going back is the same work whichever button starts it — file copies
        and several dozen settings writes — so it belongs on the same runner
        :meth:`start_apply` uses. Running it in the click handler is what
        :mod:`gtheme.ui.applyrunner` exists to stop: the window stops
        repainting during the one operation the user is most anxious about.
        """
        runner = self._runner()
        if runner is None:
            self._undo_finished(self._undo_now())
            return
        runner.run(
            lambda _narrate: self._undo_now(),
            heading=COPY["working-heading"],
            starting=COPY["working"],
            on_done=self._undo_finished,
            on_failed=self._failed,
        )

    def _undo_now(self) -> tuple[RestorePoint | None, restorepoints.RestoreResult | None]:
        """The engine half of "undo the last change". No widgets, no thread."""
        return undo_last_change(
            root=self.root,
            backend=self.backend,
            dest_root=self.dest_root,
            progress_cb=self._progress,
        )

    def _undo_finished(
        self, landed: tuple[RestorePoint | None, restorepoints.RestoreResult | None]
    ) -> None:
        point, result = landed
        if point is None:
            self._toast(COPY["undo-nothing"])
            return
        self._finish_apply(result, point)

    def _on_forget(self, point: RestorePoint) -> None:
        restorepoints.delete(point.id, root=self.root)
        self.refresh()

    def confirm_apply(
        self, point: RestorePoint, *, parent: Any | None = None
    ) -> Adw.AlertDialog:
        """Ask before going back, showing what would change. Returns the dialog.

        Returned rather than merely presented so a test can drive the response
        without a pointer, and so the caller can keep it alive.

        Args:
            point: the moment to go back to. It is named in the dialog: a
                confirmation that says "this moment" without saying which one
                is not a confirmation, and the header button and Ctrl+Z can
                both land here without the list on screen.
            parent: what to present on. Defaults to this page's window, which
                is the right answer whenever the page is the one asking; the
                header button passes the window itself, because the page it
                asks through may have been built a moment ago and not yet be
                anywhere on screen.
        """
        lines = preview_lines(point, backend=self.backend, dest_root=self.dest_root)
        named = COPY["confirm-named"].format(label=point_title(point))
        body = f"{named}\n\n{COPY['confirm-body']}" + "\n\n" + (
            "\n".join(f"• {line}" for line in lines)
            if lines
            else "• Everything this moment covers goes back to how it was."
        )
        absence = absence_sentence(point)
        if absence:
            body = f"{body}\n\n{absence}"
        dialog = Adw.AlertDialog(heading=COPY["confirm-heading"], body=body)
        dialog.add_response("cancel", COPY["confirm-cancel"])
        dialog.add_response("apply", COPY["confirm-accept"])
        dialog.set_response_appearance("apply", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda _d, response: self._on_response(response, point))
        root = parent if isinstance(parent, Gtk.Widget) else None
        if root is None:
            root = self.window if isinstance(self.window, Gtk.Widget) else self.get_root()
        if root is not None:
            dialog.present(root)
        return dialog

    def confirm_undo_last(self, parent_window: Any | None = None) -> Adw.AlertDialog | None:
        """Ask before undoing the last change — the one path for every caller.

        The header bar's Undo button and Ctrl+Z used to apply the newest saved
        moment with no confirmation and no preview, while pressing "Go back to
        this" on the very same moment one page over showed the full plan first
        (persona-report §2.8). The dialog already existed; nothing routed the
        two fast paths through it. This is that route, and it names the moment
        so the answer to "go back to what?" is on screen before anything moves.

        Returns the dialog, or None when there is no saved moment to go back to
        — which is the honest answer on a desktop nobody has changed, and is
        said in a toast rather than in an empty confirmation.
        """
        points = [p for p in restorepoints.list_restore_points(self.root) if p.kind != "pristine"]
        if not points:
            self._toast(COPY["undo-nothing"])
            return None
        return self.confirm_apply(points[0], parent=parent_window)

    def _on_response(self, response: str, point: RestorePoint) -> None:
        if response != "apply":
            return
        self.start_apply(point)

    def start_apply(self, point: RestorePoint) -> None:
        """Go back to a saved moment, on the shared runner.

        Going back copies files and writes several dozen settings — the
        "Before gtheme" moment on this machine has forty-six of them — and
        doing that on the main loop is how a window stops repainting halfway
        through the one operation the user is most anxious about. So the click
        handler comes here, and :meth:`apply_point` is the same work with no
        window around it, which is what a test drives.
        """
        runner = self._runner()
        if runner is None:
            # ``report=False`` for the same reason the threaded branch passes
            # it: ``apply_point`` reports for itself, so letting it report and
            # then reporting again raised two toasts and sent two
            # ``after_change()`` cascades through every page in the window
            # (review-report L7).
            self._finish_apply(self.apply_point(point, report=False), point)
            return
        runner.run(
            lambda _narrate: self.apply_point(point, report=False),
            heading=COPY["working-heading"],
            starting=COPY["working"],
            on_done=lambda result: self._finish_apply(result, point),
            on_failed=self._failed,
        )

    def apply_point(
        self, point: RestorePoint, *, report: bool = True
    ) -> restorepoints.RestoreResult:
        """Go back to a saved moment and say what happened."""
        result = restorepoints.apply_point(
            point.id,
            self._progress,
            root=self.root,
            backend=self.backend,
            dest_root=self.dest_root,
        )
        if report:
            self._finish_apply(result, point)
        return result

    def _finish_apply(
        self,
        result: restorepoints.RestoreResult | None,
        point: RestorePoint | None = None,
    ) -> None:
        self._report(result, point)
        self._changed()

    def _progress(self, *args: Any) -> None:
        """Narration. The shared runner's dialog is where it lands.

        This was the empty seam Wave 2 left. The engine narrates each step of
        going back; the runner owns the only surface in the app that can say
        so, and this is the one line joining them. With no runner — a page
        built by a test — the engine still narrates and nothing listens, which
        is exactly what should happen.
        """
        runner = self._runner()
        dialog = getattr(runner, "dialog", None)
        text = next((value for value in args if isinstance(value, str) and value), "")
        if dialog is not None and text:
            GLib.idle_add(_narrate, dialog, text)

    def _runner(self) -> ApplyRunner | None:
        """The window's runner, or None when this page is not in a window."""
        runner = getattr(self.window, "runner", None)
        return runner if isinstance(runner, ApplyRunner) else None

    def _changed(self) -> None:
        """The desktop moved. Everything on screen re-reads itself."""
        after = getattr(self.window, "after_change", None)
        if callable(after):
            after()
        else:
            self.refresh()

    def _report(
        self,
        result: restorepoints.RestoreResult | None,
        point: RestorePoint | None = None,
    ) -> None:
        if result is None:
            self._toast(COPY["undo-nothing"])
            return
        if result.warnings and result.transaction is None:
            # Going back did not happen. Whether the desktop came back with it
            # is the engine's answer to give, and it now gives it
            # (review-report L1) — a half-written undo is the one place in this
            # app where "Nothing was changed" would be the most damaging thing
            # it could say.
            self._toast(failure_sentence(result.warnings[0], rolled_back=result.rolled_back))
            return
        self._toast(done_sentence(point))

    def _failed(self, error: BaseException) -> None:
        """What to say when going back raised instead of reporting.

        Everything the engine refuses in an orderly way comes back as a
        :class:`~gtheme.core.restorepoints.RestoreResult` with warnings, so an
        exception that reaches here is by definition the *un*orderly kind and
        nothing knows what state the desktop is in — unless the error itself
        says, which is exactly what ``TransactionError.rolled_back`` is for.
        Assuming the reassuring answer here is how an app comes to say "Nothing
        was changed" over a half-restored desktop (review-report H2), so the
        assumption runs the other way.
        """
        self._toast(
            failure_sentence(str(error), rolled_back=bool(getattr(error, "rolled_back", False)))
        )


def _narrate(dialog: Adw.AlertDialog, text: str) -> bool:
    """Put one sentence into the progress dialog. Always on the main loop."""
    dialog.set_body(text)
    return GLib.SOURCE_REMOVE


def build(window: Any | None = None, **kwargs: Any) -> Gtk.Widget:
    """Factory named by ``ui.registry``: the Undo & Restore Points page."""
    return RestorePage(window, **kwargs)


def copy_strings() -> Iterable[tuple[str, str]]:
    """``(where, text)`` pairs for the jargon lint."""
    return [(f"restore.{name}", text) for name, text in COPY.items()]
