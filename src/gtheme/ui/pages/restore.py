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

from gi.repository import Adw, Gtk  # noqa: E402

from ...core import restorepoints  # noqa: E402
from ...core.backends import get_backend  # noqa: E402
from ...core.restorepoints import RestorePoint  # noqa: E402
from ...core.settings_backend import SettingsBackend  # noqa: E402
from ...panels.loader import load_corpus  # noqa: E402
from ..widgets.rows import key_for  # noqa: E402

__all__ = [
    "BANNER_ID",
    "COPY",
    "RestorePage",
    "absence_sentence",
    "build",
    "create_restore_point",
    "default_label",
    "coverage_keys",
    "descriptor_keys",
    "describe_point",
    "preview_lines",
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
    "confirm-body": "Here is what will change on your desktop:",
    "confirm-cancel": "Keep things as they are",
    "confirm-accept": "Go back",
    "done": "Your desktop is back the way it was.",
    "saved": "Saved how your desktop looks right now. You can come back to it any time.",
    "failed": "Nothing was changed. Your desktop is exactly as it was.",
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


#: Dispositions whose keys gtheme can write, and which a restore point must
#: therefore cover. ``excluded`` and ``delegated`` keys are never written.
_CAPTURED_DISPOSITIONS = ("surfaced", "compound", "floor")


def coverage_keys(directory: Path | str | None = None) -> list[str]:
    """The settings named in ``coverage.toml`` that gtheme is allowed to write.

    Read here rather than taken from :func:`gtheme.ui.registry.resolve_surfaced`
    because that function answers a different question — which page shows which
    row — and deliberately drops the ``compound`` keys. A restore point that
    dropped them would not record light-or-dark or which add-ons were on, which
    are the two things people undo most.
    """
    from ...panels.loader import data_dir

    base = data_dir(directory)
    if base is None:
        return []
    manifest = base / "domains" / "coverage.toml"
    if not manifest.is_file():
        return []
    import tomllib

    try:
        with manifest.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):  # pragma: no cover - a broken file is Wave 1's
        return []
    keys: list[str] = []
    for descriptor_id, disposition in (data.get("dispositions") or {}).items():
        verb = str(disposition).partition("(")[0].strip()
        if verb not in _CAPTURED_DISPOSITIONS:
            continue
        schema, _, key = str(descriptor_id).partition(":")
        if schema and key:
            keys.append(f"gsettings:{schema} {key}")
    return keys


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
) -> RestorePoint:
    """Save how the desktop looks right now, and return the saved moment.

    Args:
        label: what to call it. Defaults to :func:`default_label`.
        backend: where the current values are read from.
        root: where saved moments live. Defaults to the real state directory.
        corpus: the descriptor corpus, when it has already been loaded.
        keys: the exact keys to record. Overrides ``corpus``; used by tests
            that do not want to read the whole shipped corpus.
    """
    covered = list(keys) if keys is not None else descriptor_keys(corpus)
    return restorepoints.capture(
        covered,
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
        banner = self._banner()
        if banner is not None:
            group = Adw.PreferencesGroup()
            group.add(banner)
            self._page.add(group)

        actions = Adw.PreferencesGroup()
        actions.add(
            self._button_row(
                COPY["save-title"],
                COPY["save-subtitle"],
                COPY["save-button"],
                self._on_save,
                suggested=True,
            )
        )
        actions.add(
            self._button_row(
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

    def _banner(self) -> Adw.Banner | None:
        prefs = getattr(self.window, "prefs", None)
        if prefs is None or not prefs.should_show_banner(BANNER_ID):
            return None
        banner = Adw.Banner(title=COPY["banner"], button_label="Got it", revealed=True)

        def dismiss(*_args: Any) -> None:
            banner.set_revealed(False)
            prefs.mark_banner_seen(BANNER_ID)

        banner.connect("button-clicked", dismiss)
        return banner

    def _button_row(
        self,
        title: str,
        subtitle: str,
        button_label: str,
        callback: Callable[[], None],
        *,
        suggested: bool = False,
    ) -> Adw.ActionRow:
        row = Adw.ActionRow(title=title, subtitle=subtitle)
        button = Gtk.Button(label=button_label, valign=Gtk.Align.CENTER)
        if suggested:
            button.add_css_class("suggested-action")
        button.connect("clicked", lambda *_a: callback())
        row.add_suffix(button)
        row.set_activatable_widget(button)
        return row

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
        title = COPY["pristine-title"] if pristine else point.label
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
        try:
            create_restore_point(
                backend=self.backend, root=self.root, corpus=self.corpus, keys=self.keys
            )
        except OSError as exc:
            self._toast(f"Could not save how your desktop looks: {exc.strerror or exc}")
            return
        self.refresh()
        self._toast(COPY["saved"])

    def _on_undo(self) -> None:
        point, result = undo_last_change(
            root=self.root, backend=self.backend, dest_root=self.dest_root
        )
        if point is None:
            self._toast(COPY["undo-nothing"])
            return
        self._report(result)

    def _on_forget(self, point: RestorePoint) -> None:
        restorepoints.delete(point.id, root=self.root)
        self.refresh()

    def confirm_apply(self, point: RestorePoint) -> Adw.AlertDialog:
        """Ask before going back, showing what would change. Returns the dialog.

        Returned rather than merely presented so a test can drive the response
        without a pointer, and so the caller can keep it alive.
        """
        lines = preview_lines(point, backend=self.backend, dest_root=self.dest_root)
        body = COPY["confirm-body"] + "\n\n" + (
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
        root = self.window if isinstance(self.window, Gtk.Widget) else self.get_root()
        if root is not None:
            dialog.present(root)
        return dialog

    def _on_response(self, response: str, point: RestorePoint) -> None:
        if response != "apply":
            return
        self.apply_point(point)

    def apply_point(self, point: RestorePoint) -> restorepoints.RestoreResult:
        """Go back to a saved moment and say what happened."""
        result = restorepoints.apply_point(
            point.id,
            self._progress,
            root=self.root,
            backend=self.backend,
            dest_root=self.dest_root,
        )
        self._report(result)
        self.refresh()
        return result

    def _progress(self, *_args: Any) -> None:
        """Narration hook. Wave 3 owns the shared progress surface."""

    def _report(self, result: restorepoints.RestoreResult | None) -> None:
        if result is None:
            self._toast(COPY["undo-nothing"])
            return
        if result.warnings and result.transaction is None:
            self._toast(result.warnings[0] or COPY["failed"])
            return
        self._toast(COPY["done"])


def build(window: Any | None = None, **kwargs: Any) -> Gtk.Widget:
    """Factory named by ``ui.registry``: the Undo & Restore Points page."""
    return RestorePage(window, **kwargs)


def copy_strings() -> Iterable[tuple[str, str]]:
    """``(where, text)`` pairs for the jargon lint."""
    return [(f"restore.{name}", text) for name, text in COPY.items()]
