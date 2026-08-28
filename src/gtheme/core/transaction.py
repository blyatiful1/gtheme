"""The transaction layer — every change to the desktop goes through here.

THE CONTRACT IS FROZEN (DESIGN.md F4). The operation dataclasses, the
``Transaction.plan() -> Diff`` shape, ``Diff.to_novice_lines()`` and
``apply(progress_cb)`` are what the preset compiler, the extension installer
and every UI page code against. Bodies land with the core engine port (Wave 1
Agent A); the signatures do not move under them.

Five properties this layer owes its callers, all of them lessons paid for in
v1 (the defect tags in the legacy ``engine/apply.py`` are the receipts):

* **One code path for preview and apply.** The preview dialog and the
  after-the-fact summary both render the same :class:`Diff` that ``apply``
  consumes. A preview that is computed differently from the apply is a lie
  waiting to happen.
* **Confinement is checked for every operation before the first byte is
  written.** Not per-op as it goes: a transaction that writes three files and
  then discovers the fourth escapes its destination root has already done
  damage.
* **The pristine baseline is captured before the first mutation**, and the
  ownership ledger entry is written *before* the change it describes, never
  after. A crash between the two must leave a ledger that over-claims, not one
  that under-claims — over-claiming restores something already correct, which
  is harmless; under-claiming orphans a change forever.
* **Files are applied before settings.** Some Looks write a theme file and then
  point a setting at it; the reverse order flashes a broken desktop.
* **Nothing is executed.** There is no hook machinery here and there never will
  be. This is what makes the sentence "Looks only change settings. They can't
  run programs on your computer." true rather than aspirational.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from . import ledger as ledger_store
from . import placeholders
from . import policy as look_policy
from .atomic import atomic_write_bytes
from .backends import can_write_settings, get_backend, is_missing
from .baseline import Baseline, BaselineError
from .confine import ConfinementError, confine_dest
from .gvariant import format_string_list, merge_string_lists, parse_string_list, values_equal
from .lock import LockBusy, process_lock
from .paths import dest_root, xdg_data_home
from .settings_backend import BackendError, BackendErrorKind, SettingsBackend

__all__ = [
    "Diff",
    "DiffEntry",
    "ExtensionEnable",
    "ExtensionInstall",
    "FileLink",
    "FileRemove",
    "FileWrite",
    "MergeMode",
    "Op",
    "Progress",
    "SettingReset",
    "SettingWrite",
    "Transaction",
    "TransactionError",
    "TransactionResult",
]

#: How a write combines with the value already there.
#:
#: ``"none"``       replace outright.
#: ``"list-union"`` append missing members to an existing list, preserving
#:                  order and duplicates-free-ness. This exists for exactly one
#:                  reason: ``enabled-extensions``. Replacing that key would
#:                  turn off every add-on the user enabled themselves, so a
#:                  Look unions into it — and restore puts back the exact
#:                  pre-merge value, not a computed difference.
MergeMode = Literal["none", "list-union"]


@dataclass(frozen=True)
class FileWrite:
    """Write one file the Look owns.

    Args:
        src: absolute path to the source file. The compiler resolves a Look's
            relative ``src`` against the Look's folder before it gets here, so
            by the time an op exists the path no longer depends on where the
            Look happened to live.
        dest: destination path. Must resolve inside the destination root; the
            preflight refuses anything else, including via symlinks.
        mode: octal permission string (``"0644"``), or None to leave default.
        template: render ``src`` through the template engine before writing,
            substituting palette values and ``{{ }}`` placeholders.
        merge: reserved; file writes are always ``"none"`` today.
    """

    src: str
    dest: str
    mode: str | None = None
    template: bool = False
    merge: MergeMode = "none"


@dataclass(frozen=True)
class SettingWrite:
    """Write one desktop setting.

    Args:
        key: a key string in the grammar frozen in ``core.settings_backend``.
        value: GVariant text, exactly as ``Variant.print_(True)`` renders it.
        merge: see :data:`MergeMode`.
        component: which part of the desktop this belongs to, from the closed
            registry in ``preset.model``. Drives how the change is described
            to the user ("Wallpaper", "Highlight colour") — it is presentation
            metadata and never affects what is written.
    """

    key: str
    value: str
    merge: MergeMode = "none"
    component: str | None = None


@dataclass(frozen=True)
class SettingReset:
    """Put one desktop setting back to having no value of its own.

    Not the same as writing the default: the desktop is then free to change
    what the default *is*, and the setting follows. Writing today's default
    freezes it forever, invisibly.

    This exists because two thirds of a pristine restore point is absence. The
    "Before gtheme" point imported from v1 on this machine records 46 settings,
    and 33 of them had no value at all — keys belonging to add-ons the user had
    never opened before a Look configured them. Without this op, undoing that
    moment could only be done outside the transaction, which meant those 33
    changes had no confinement preflight, no rollback and no restore point of
    their own.

    Args:
        key: a key string in the grammar frozen in ``core.settings_backend``.
        component: as :class:`SettingWrite`. Presentation only.
    """

    key: str
    component: str | None = None


@dataclass(frozen=True)
class FileRemove:
    """Delete one file that gtheme, or a Look, put there.

    The counterpart of :class:`SettingReset`, for the other half of absence: a
    restore point knows which files did not exist at the moment it was taken,
    and putting that moment back means the files are not there again.

    The same rules as :class:`FileWrite` apply and for the same reasons. The
    destination is confined before anything is touched — deleting outside the
    destination root is a worse accident than writing outside it — and what is
    at the destination is recorded first, so the removal can be rolled back
    like any other change. Anything that is not an ordinary file or a symlink
    is left alone (the F1 case): it cannot be copied, so it cannot be put back,
    so it does not get deleted.

    Args:
        dest: the file to delete. Must resolve inside the destination root.
        component: as :class:`SettingWrite`. Presentation only.
    """

    dest: str
    component: str | None = None


@dataclass(frozen=True)
class FileLink:
    """Put a symlink back where one was.

    The third face of the same story as :class:`FileRemove` and
    :class:`SettingReset`: what was at a destination before a Look wrote over
    it is sometimes neither a file nor nothing, but a link. This machine's own
    ``~/.config/ghostty`` is a symlink into a separate rice repository, and
    plenty of people keep their dotfiles that way.

    Without this op a saved moment could only record such a destination as
    "there was nothing here", and putting the moment back *deleted the user's
    own link* and left a hole. The pristine baseline always recorded links
    properly (``baseline.record_file``); this is what lets a restore point say
    the same thing, through the same transaction, with the same preflight and
    rollback.

    The link is recreated, never followed: writing through it would edit
    whatever it points at, which is exactly the dotfiles repository the user
    did not ask to have changed.

    Args:
        dest: where the link goes. Confined like any other destination.
        target: what it pointed at, exactly as ``readlink`` reported it —
            relative links stay relative.
        component: as :class:`SettingWrite`. Presentation only.
    """

    dest: str
    target: str
    component: str | None = None


@dataclass(frozen=True)
class ExtensionEnable:
    """Turn on an add-on that is already installed.

    Args:
        uuid: the extension's identifier. Never rendered to the user.
        alternates: other identifiers that satisfy the same need — the
            ding/gtk4-ding pair is why. The first one present wins.
    """

    uuid: str
    alternates: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExtensionInstall:
    """Fetch and install an add-on that is not present.

    Args:
        uuid: the extension's identifier.
        ego_pk: its numeric id on extensions.gnome.org, when known.
        source: ``"ego"`` means it can be offered for download;
            ``"local-only"`` means it is a private add-on that must already be
            on the machine, and its absence is a named skip, not an error.
    """

    uuid: str
    ego_pk: int | None = None
    source: Literal["ego", "local-only"] = "ego"


#: Everything a transaction can be asked to do. The set is closed, deliberately.
Op = (
    FileWrite
    | FileRemove
    | FileLink
    | SettingWrite
    | SettingReset
    | ExtensionEnable
    | ExtensionInstall
)


#: The one key that is shared global state. Every add-on the user turned on
#: themselves lives in this list, which is why a Look unions into it rather
#: than writing over it. See ``core.gvariant.merge_string_lists`` (the X1
#: defect).
ENABLED_EXTENSIONS_KEY = "gsettings:org.gnome.shell enabled-extensions"

#: Ledger owner name for changes that came from a page rather than a Look, and
#: for a saved moment being put back. Switching Looks tidies up after other
#: Looks; it never tidies up after the user's own deliberate edits. Defined in
#: ``core.ledger`` — where the cleanup that skips it lives — and re-exported
#: here because this is where callers look for it.
MANUAL_OWNER = ledger_store.MANUAL_OWNER

#: Component to the phrase shown to a first-time user, in reading order.
#: Mirrors ``preset.model.Component``; a test asserts every member is covered,
#: because a component with no phrase would silently vanish from a preview.
_COMPONENT_PHRASES: dict[str, tuple[str, str]] = {
    "wallpaper": ("Background picture", "Background picture"),
    "colors": ("Colours", "Colours"),
    "icons": ("Icons", "Icons"),
    "cursor": ("Mouse pointer", "Mouse pointer"),
    "fonts": ("Text style", "Text style"),
    "shell-theme": ("Top bar style", "Top bar style"),
    "topbar": ("Top bar", "Top bar"),
    "windows": ("Windows", "Windows"),
    "workspaces": ("Desktops", "Desktops"),
    "animations": ("Animations", "Animations"),
    "night-light": ("Warmer colours in the evening", "Warmer colours in the evening"),
    "sound": ("Sound", "Sound"),
    "power": ("Power and screen", "Power and screen"),
    "terminal": ("Terminal", "Terminal"),
    "addons": ("1 add-on", "{count} add-ons"),
    "addon-settings": ("1 add-on setting", "{count} add-on settings"),
    "privacy": ("Privacy", "Privacy"),
    "accessibility": ("Ease of use", "Ease of use"),
    "files": ("1 file", "{count} files"),
    # Files a Look may write and that must never be counted. See
    # ``core.policy``: these are a program's own settings file, in a format
    # that can also name a command for that program to run. "23 files" over
    # the sentence "they can't run programs on your computer" is exactly the
    # collapse review-report C1 was about, so each of these is named.
    "consequential-files": (
        "1 file that can start programs",
        "{count} files that can start programs",
    ),
    "other": ("Other settings", "Other settings"),
    # Undo's two phrases. They are not components of a Look — nothing writes
    # them into a theme.toml — but they are what the preview has to say when
    # the change is an absence rather than a value.
    "reset": (
        "Put back to how the system had it",
        "Put back to how the system had it",
    ),
    "removed-files": ("Remove 1 file", "Remove {count} files"),
}

#: Components whose single-entry line names the thing instead of counting it.
#: "Remove 1 file" tells a person nothing they can act on; "Remove
#: nightbloom.conf" tells them exactly what is about to disappear.
_NAMED_WHEN_SINGLE: frozenset[str] = frozenset({"removed-files"})

#: Components whose entries are listed one by one however many there are. A
#: count is the right summary for twenty wallpaper files and the wrong one for
#: two files that can start a program: the whole point of allowing those is
#: that the person is told, by name, which ones they are (review-report C1).
_ALWAYS_NAMED: frozenset[str] = frozenset({"consequential-files"})

_COMPONENT_ORDER: tuple[str, ...] = tuple(_COMPONENT_PHRASES)


def _settings_component(declared: str | None, *, default: str = "other") -> str:
    """The component a *setting* is counted under.

    One line, and it stops the preview telling a lie people noticed
    immediately: HYPERCLASS previewed as "31 add-ons" on a Look that turns on
    six. The other twenty-five entries were settings *belonging* to those six —
    the dock's icon size, the blur radius, where the panel sits — each one a
    ``SettingWrite`` the Look tagged ``component = "addons"``, and each one
    counted as if it were another add-on being switched on.

    An add-on is a thing you install and turn on. Changing how one is
    configured is not installing another one, and a person reading "31 add-ons"
    reasonably expects thirty-one new things on their desktop. So a setting
    that says it belongs to the add-ons part of the desktop is counted, and
    named, as a setting: only ``ExtensionEnable`` and ``ExtensionInstall`` are
    add-ons on that line.

    Done here rather than in ``preset.compile`` because both routes to the same
    mistake pass through here. A Look can arrive tagged this way from an
    ``[[extensions.settings]]`` table, which compile writes, or from an
    ordinary ``[[settings]]`` entry that simply declares the component itself —
    which is what the v1 conversion produced, and what HYPERCLASS is.
    """
    component = declared or default
    return "addon-settings" if component == "addons" else component


def _novice_phrase(component: str, count: int) -> str:
    singular, plural = _COMPONENT_PHRASES.get(component, ("Other settings", "Other settings"))
    template = singular if count == 1 else plural
    return template.format(count=count)


def _digest(data: bytes) -> str:
    """A short, stable fingerprint of a file's contents, for the diff."""
    return "file:" + hashlib.sha256(data).hexdigest()[:16]


def installed_extension_uuids() -> set[str]:
    """Which add-ons are present on this machine.

    Reads the two directories add-ons are unpacked into, and nothing else — no
    D-Bus call, because this has to work with no session running (the rescue
    path) and because a directory listing cannot fail in an interesting way.
    ``XDG_DATA_HOME`` reroots the user half, which is the seam the tests use.
    """
    found: set[str] = set()
    roots = (
        xdg_data_home() / "gnome-shell" / "extensions",
        Path("/usr/share/gnome-shell/extensions"),
    )
    for root in roots:
        try:
            found.update(child.name for child in root.iterdir() if child.is_dir())
        except OSError:
            continue
    return found


def _resolve_extension(op: ExtensionEnable, present: set[str]) -> str | None:
    """Which of an add-on's acceptable identifiers is actually installed.

    ``ding`` and ``gtk4-ding`` do the same job under different names; a Look
    that wants desktop icons should get whichever one the machine has.
    """
    for uuid in (op.uuid, *op.alternates):
        if uuid in present:
            return uuid
    return None


class Progress(Enum):
    """Stages a transaction reports through its progress callback."""

    PLANNING = "planning"
    SNAPSHOTTING = "snapshotting"
    WRITING_FILES = "writing-files"
    WRITING_SETTINGS = "writing-settings"
    EXTENSIONS = "extensions"
    DONE = "done"
    ROLLED_BACK = "rolled-back"


class TransactionError(Exception):
    """A transaction could not be completed.

    Attributes:
        op: the operation that failed, when one operation was to blame.
        rolled_back: whether the desktop was returned to its prior state. False
            here is the serious case and the UI must say so plainly.
    """

    def __init__(self, message: str, *, op: Op | None = None, rolled_back: bool = True) -> None:
        super().__init__(message)
        self.op = op
        self.rolled_back = rolled_back


@dataclass(frozen=True)
class DiffEntry:
    """One line of a planned change, in both machine and human form.

    **The contract, amended.** ``summary`` is still never a key name: it is the
    novice line, and "Wallpaper" is what the person who has never heard of a
    settings key needs to read. What the original wording was taken to mean —
    that the app never shows the real key or the real destination *anywhere* —
    was never the promise, and holding to it cost the app its own first rule:
    "nothing is applied that you have not seen first" was satisfied by the
    words "Terminal" and "20 files", and ``before``/``after`` were carried
    through every plan and rendered by nothing (persona-report §2.4). So there
    are deliberately two layers. ``summary`` is the headline and stays in the
    user's words; ``before`` and ``after`` are the machine's own values, and a
    caller may show them. The Looks page does, in a collapsed expander headed
    "Show exactly what changes" that nobody has to open. A second, honest
    layer behind one click is not a novice-first failure; a count with nothing
    behind it is.

    Args:
        op: the operation this describes.
        component: closed-registry component name, for grouping.
        summary: one short phrase in the user's words — "Wallpaper", "Highlight
            colour". Never a key name.
        before: current value as GVariant text or a file digest, None if absent.
        after: value after the change.
        no_op: True when before and after are equal. Kept in the diff rather
            than dropped, so "nothing to do" can be shown as such.
    """

    op: Op
    component: str
    summary: str
    before: str | None = None
    after: str | None = None
    no_op: bool = False


@dataclass
class Diff:
    """What a transaction would change. Rendered before applying, and after."""

    entries: list[DiffEntry] = field(default_factory=list)

    @property
    def changes(self) -> list[DiffEntry]:
        """Entries that would actually change something."""
        return [e for e in self.entries if not e.no_op]

    def to_novice_lines(self) -> list[str]:
        """Describe the change in the words a first-time user would use.

        Groups by component and collapses counts, so a Look that touches
        forty keys reads as ``["Wallpaper", "Highlight colour", "Icons",
        "3 add-ons"]`` rather than as forty key names. This is the string the
        preview dialog and the confirmation toast both show.

        Components appear in a fixed order — the order the desktop reads in,
        roughly top to bottom — so the same Look always describes itself the
        same way rather than in whatever order its author happened to write.

        Two kinds of entry are named instead of counted: the ones that name a
        file being deleted, and the ones a Look may write but that can start a
        program (``core.policy``'s consequential tier). "23 files" printed over
        "they can't run programs on your computer" is the collapse that made
        review-report C1 possible; a count is never used where the identity of
        the file is the whole point.
        """
        counted: dict[str, int] = {}
        only: dict[str, DiffEntry] = {}
        listed: dict[str, list[DiffEntry]] = {}
        for entry in self.changes:
            counted[entry.component] = counted.get(entry.component, 0) + 1
            only[entry.component] = entry
            if entry.component in _ALWAYS_NAMED:
                listed.setdefault(entry.component, []).append(entry)

        def phrases(component: str, count: int) -> list[str]:
            if component in _ALWAYS_NAMED:
                return [entry.summary for entry in listed.get(component, [])]
            if count == 1 and component in _NAMED_WHEN_SINGLE:
                return [only[component].summary]
            return [_novice_phrase(component, count)]

        lines: list[str] = []
        for component in _COMPONENT_ORDER:
            count = counted.pop(component, 0)
            if count:
                lines.extend(phrases(component, count))
        for component in sorted(counted):
            lines.extend(phrases(component, counted[component]))
        return lines


@dataclass
class TransactionResult:
    """The outcome of an applied transaction.

    The last three describe the tidy-up that runs before a Look switch, which
    is a real change to the desktop that this transaction's own diff says
    nothing about. They were computed and thrown away (review-report M1), so an
    apply that could not put part of the previous Look back reported plain
    success and told the user nothing.
    """

    diff: Diff
    applied: list[Op] = field(default_factory=list)
    skipped: list[tuple[Op, str]] = field(default_factory=list)
    restore_point: str | None = None
    #: What the restore point could not cover. A moment can be saved in part —
    #: one file unreadable, one setting the desktop would not report — and the
    #: point records that in its own warnings. They were read and dropped on
    #: the floor here (persona-report §2.5), so "you can put it back with one
    #: click" was said with the same confidence over a snapshot with holes in
    #: it. The UI shows these after the change lands.
    restore_warnings: list[str] = field(default_factory=list)
    #: Sentences about the previous Look that could not be changed back.
    cleanup_warnings: list[str] = field(default_factory=list)
    #: How many of the previous Look's things are still on the desktop and
    #: still recoverable from the Undo page.
    cleanup_kept: int = 0
    #: How many can never be changed back — the saved copy is gone. Counted
    #: apart from :attr:`cleanup_kept` because telling somebody "Undo can still
    #: recover them" about these would be untrue.
    cleanup_dead: int = 0


class Transaction:
    """An all-or-nothing batch of changes to the desktop.

    Args:
        ops: the operations, in author order. Execution order is imposed by
            the engine (files, then settings, then extensions), not by this
            sequence.
        dest_root: the root every file write must stay inside. Defaults to the
            user's home; ``GTHEME_DEST_ROOT`` overrides it, and that override
            is the seam the test suite uses to keep off the real desktop.
        label: what to call this in the saved-moment list ("NIGHTBLOOM"). A
            name for a moment, and nothing more: every saved moment has one,
            including the automatic one taken before a single tick on a page.
        look: the Look's own folder name, when this transaction is a Look being
            applied. This — not ``label`` — is the flag that says "a whole Look
            is being applied", and it is what turns the switch cleanup and the
            current-Look record on. The two were confused once and it cost the
            app its headline promise: because *every* saved moment carries a
            label, putting one back ran the Look-switch cleanup and stripped
            the Look that was on the desktop off it, so undoing one small tweak
            reverted the whole Look. A saved moment being put back carries a
            label ("My desktop, 25 August") and is emphatically not a Look, so
            it passes ``look=None`` and tidies up after nobody.
    """

    def __init__(
        self,
        ops: Iterable[Op] = (),
        *,
        dest_root: str | None = None,
        label: str | None = None,
        look: str | None = None,
    ) -> None:
        self.ops: Sequence[Op] = tuple(ops)
        self.dest_root = dest_root
        self.label = label
        self.look = look

    # -- shared machinery --------------------------------------------------

    @property
    def _backend(self) -> SettingsBackend:
        """The settings backend. Overridable per instance, mostly for tests.

        There is a second per-instance seam beside this one, set the same way
        and deliberately absent from the frozen constructor: ``installer``, a
        callable taking an :class:`ExtensionInstall` and returning whether the
        add-on is now on the machine. Set it and :meth:`_install_extensions`
        fetches missing add-ons before the settings phase; leave it alone — the
        default — and a missing add-on is a named skip, as it always was.
        Downloading needs the network and a person's consent, so the decision
        belongs to the caller, but the *ordering* belongs here (X1).
        """
        override = getattr(self, "backend", None)
        return override if override is not None else get_backend()

    @property
    def _root(self) -> Path:
        return Path(self.dest_root) if self.dest_root else dest_root()

    def _file_ops(self) -> list[FileWrite]:
        return [op for op in self.ops if isinstance(op, FileWrite)]

    def _remove_ops(self) -> list[FileRemove]:
        return [op for op in self.ops if isinstance(op, FileRemove)]

    def _link_ops(self) -> list[FileLink]:
        return [op for op in self.ops if isinstance(op, FileLink)]

    def _setting_ops(self) -> list[SettingWrite]:
        return [op for op in self.ops if isinstance(op, SettingWrite)]

    def _reset_ops(self) -> list[SettingReset]:
        return [op for op in self.ops if isinstance(op, SettingReset)]

    def _enable_ops(self) -> list[ExtensionEnable]:
        return [op for op in self.ops if isinstance(op, ExtensionEnable)]

    def _install_ops(self) -> list[ExtensionInstall]:
        return [op for op in self.ops if isinstance(op, ExtensionInstall)]

    def _preflight(self) -> dict[str, Path]:
        """Confine every destination before anything is written.

        Runs over *all* file operations, and runs before the first byte. A
        transaction that writes three files and then finds the fourth escapes
        has already done the damage; this is the whole reason the check is a
        separate pass.

        Raises:
            TransactionError: a destination escapes, or the destination root
                itself is unusable.
        """
        resolved: dict[str, Path] = {}
        for op in (*self._file_ops(), *self._remove_ops(), *self._link_ops()):
            try:
                resolved[op.dest] = confine_dest(op.dest, root=self._root)
            except ConfinementError as exc:
                raise TransactionError(str(exc), op=op) from exc
        return resolved

    def _policy_preflight(self, context: dict[str, str] | None = None) -> None:
        """Refuse a Look that asks for something no Look may have (C1, H4).

        Runs with the confinement preflight, before the first byte, and for the
        same reason: a Look whose fourth entry is a login script must not have
        had its first three applied. The refusal is whole-Look on purpose — a
        Look that needs to write a program entry is not a decorative Look, and
        applying "the rest of it" would be applying something its author never
        designed.

        Only for a Look. A saved moment being put back describes *this*
        machine as it already was — refusing to restore a file that was there
        before gtheme ever ran would break the promise the app is built on — so
        the question is asked only when ``look`` says a Look is being applied.
        See ``core.policy`` for the tiers and why each entry is in one.

        Raises:
            TransactionError: an operation falls in the refused tier.
        """
        if not self.look:
            return
        for op in (*self._file_ops(), *self._remove_ops(), *self._link_ops()):
            verdict = look_policy.file_verdict(op.dest, root=self._root)
            if verdict.refused:
                raise TransactionError(
                    f"this look asked to write {op.dest}, which gtheme will not do: "
                    f"{verdict.reason}",
                    op=op,
                )
        for op in (*self._setting_ops(), *self._reset_ops()):
            # Both the key as written and the key with its ``{{ }}`` tokens
            # filled in: the written form is what the Look is judged on, and
            # the filled-in form is what would actually be written.
            forms = {op.key}
            if context is not None:
                forms.add(placeholders.resolve(op.key, context))
            for key in forms:
                verdict = look_policy.setting_verdict(key)
                if verdict.refused:
                    raise TransactionError(
                        "this look asked to change something gtheme will not let a look "
                        f"change: {verdict.reason}",
                        op=op,
                    )

    def _file_line(self, op: FileWrite) -> tuple[str, str]:
        """``(component, summary)`` for one file being written.

        Ordinary files are counted ("23 files"). A file in the consequential
        tier — a program's own settings file, in a format that can also name a
        command for that program to run — is named instead, every time, because
        the identity of the file *is* what the person needs to see (C1).
        """
        verdict = look_policy.file_verdict(op.dest, root=self._root)
        if verdict.named:
            return "consequential-files", f"{verdict.what} — {verdict.reason}"
        return "files", _novice_phrase("files", 1)

    def _rendered(self, op: FileWrite, context: dict[str, str]) -> bytes:
        """The exact bytes ``op`` would write.

        Raises:
            TransactionError: the source is missing, unreadable, is a shortcut
                to somewhere else, or is being templated while not being text.
                That last one is not fussiness: templating a binary file used
                to truncate the destination to nothing.
        """
        source = Path(op.src)
        if not source.is_absolute():
            raise TransactionError(
                f"this look's file {op.src!r} was not resolved to a full location before "
                "the change was prepared",
                op=op,
            )
        if source.is_symlink():
            # H5, the second half. ``preset.compile`` resolves every source
            # through ``confine_src`` and stores the resolved location, so by
            # the time an op exists its source is a real file inside the Look's
            # own folder. A source that is a shortcut at *this* moment is
            # therefore either something that swapped underneath the plan or an
            # op built by hand, and following it would read whatever it points
            # at — which is exactly the private key the confinement rule exists
            # to keep out of a Look.
            raise TransactionError(
                f"this look's file {op.src} is a shortcut to somewhere else, so it was "
                "not copied",
                op=op,
            )
        if not source.is_file():
            raise TransactionError(f"this look is missing one of its files: {op.src}", op=op)
        if not op.template:
            try:
                return source.read_bytes()
            except OSError as exc:
                raise TransactionError(f"cannot read {op.src}: {exc}", op=op) from exc
        try:
            text = source.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise TransactionError(
                f"{op.src} is not text, so the personalised values in it cannot be filled in",
                op=op,
            ) from exc
        return placeholders.resolve(text, context).encode("utf-8")

    def _file_mode(self, op: FileWrite) -> int | None:
        if op.mode:
            # Mask off setuid/setgid/sticky. A Look may choose permissions; it
            # may not hand itself privileges.
            return int(op.mode, 8) & 0o777
        try:
            return Path(op.src).stat().st_mode & 0o777
        except OSError:
            return None

    @staticmethod
    def _schema_default(backend: SettingsBackend, key: str) -> str | None:
        """The value this key would have if nobody had ever set it.

        Used only to decide whether a :class:`SettingReset` would change
        anything visible. A key explicitly set to its own default reads as "no
        change here", which is the truth as far as the desktop is concerned —
        the observable state before and after is identical — even though the
        reset does still clear the stored value.

        Never raises: an answer of None means "could not tell", and the caller
        then treats the reset as a real change. Over-reporting a change in a
        preview is a much smaller sin than hiding one.
        """
        try:
            from gi.repository import Gio

            from .settings_backend import KeyKind, parse_key

            parsed = parse_key(key)
            if parsed.kind is KeyKind.DCONF or not parsed.schema or not parsed.key:
                return None
            source = backend.schema_source or Gio.SettingsSchemaSource.get_default()
            schema = source.lookup(parsed.schema, True) if source is not None else None
            if schema is None or not schema.has_key(parsed.key):
                return None
            return schema.get_key(parsed.key).get_default_value().print_(True)
        except Exception:  # pragma: no cover - defensive; never fatal
            return None

    def _current_setting(self, key: str) -> tuple[str | None, BackendError | None]:
        """``(value, failure)``. A missing schema is a value of None, not a raise.

        A location that is *unset* is not a failure at all and comes back as
        ``(None, None)``: a settings location nothing has ever written to is
        somewhere a value can be put, with no current value — which is a real
        change, not an absent add-on. Reading the two as the same thing is what
        made a never-written location impossible to set for good, because the
        skip preserved the very emptiness it keyed on (review-report H7).
        """
        try:
            return self._backend.get(key), None
        except BackendError as exc:
            if exc.kind is BackendErrorKind.UNSET:
                return None, None
            return None, exc

    def _planned_setting(
        self, op: SettingWrite, context: dict[str, str]
    ) -> tuple[str, str, str | None]:
        """``(key, value, skip_reason)`` for one setting, tokens resolved.

        A token that did not resolve skips the op wherever it stood. The value
        half was missed: ``key_ok`` only ever looked at the key, so a typo in a
        Look's ``{{ home }}`` inside a *value* was written through literally
        and the desktop was pointed at a file called ``{{ hoem }}``
        (review-report M12). ``docs/preset-format.md`` promises the opposite —
        "never written half-resolved" — for both halves.
        """
        key = placeholders.resolve(op.key, context)
        value = placeholders.resolve(op.value, context)
        missing = placeholders.unresolved_tokens(key)
        missing += [name for name in placeholders.unresolved_tokens(value) if name not in missing]
        if missing:
            return key, value, (
                "this needs something that is not set up on this computer yet "
                f"({', '.join(missing)})"
            )
        if not placeholders.key_ok(key):
            return key, value, "this setting's location came out incomplete on this computer"
        return key, value, None

    # -- planning ----------------------------------------------------------

    def plan(self) -> Diff:
        """Compute what would change, touching nothing.

        Reads current values through the settings backend and hashes the files
        that would be overwritten. Runs the full confinement preflight, so a
        transaction that would escape its destination root fails here — before
        the user is even shown a confirmation.

        The entries come back in the order they will be carried out — files,
        then settings, then add-ons — so the preview and the apply describe the
        same thing in the same order.

        Raises:
            TransactionError: the transaction cannot be applied at all.
        """
        backend = self._backend
        context = placeholders.runtime_context(backend)
        dests = self._preflight()
        self._policy_preflight(context)
        diff = Diff()

        for op in self._file_ops():
            dest = dests[op.dest]
            after = _digest(self._rendered(op, context))
            before: str | None = None
            if dest.is_symlink():
                before = f"link:{dest.readlink()}"
            elif dest.is_file():
                try:
                    before = _digest(dest.read_bytes())
                except OSError:
                    before = None
            component, summary = self._file_line(op)
            diff.entries.append(
                DiffEntry(
                    op=op,
                    component=component,
                    summary=summary,
                    before=before,
                    after=after,
                    no_op=before == after,
                )
            )

        for op in self._remove_ops():
            dest = dests[op.dest]
            before: str | None = None
            if dest.is_symlink():
                before = f"link:{dest.readlink()}"
            elif dest.is_file():
                try:
                    before = _digest(dest.read_bytes())
                except OSError:
                    before = "file:unreadable"
            component = op.component or "removed-files"
            diff.entries.append(
                DiffEntry(
                    op=op,
                    component=component,
                    summary=f"Remove {Path(op.dest).name}",
                    before=before,
                    after=None,
                    # Already gone is already right.
                    no_op=before is None,
                )
            )

        for op in self._link_ops():
            dest = dests[op.dest]
            before: str | None = None
            if dest.is_symlink():
                before = f"link:{dest.readlink()}"
            elif dest.is_file():
                try:
                    before = _digest(dest.read_bytes())
                except OSError:
                    before = "file:unreadable"
            after = f"link:{op.target}"
            diff.entries.append(
                DiffEntry(
                    op=op,
                    component=op.component or "files",
                    summary=f"Put back the shortcut {Path(op.dest).name}",
                    before=before,
                    after=after,
                    no_op=before == after,
                )
            )

        for op in self._setting_ops():
            key, value, skip = self._planned_setting(op, context)
            component = _settings_component(op.component)
            current, failure = self._current_setting(key)
            wanted = value
            if op.merge == "list-union":
                merged = merge_string_lists(current, value)
                if merged is not None:
                    wanted = merged
            unavailable = skip is not None or (failure is not None and is_missing(failure))
            diff.entries.append(
                DiffEntry(
                    op=op,
                    component=component,
                    summary=_novice_phrase(component, 1),
                    before=current,
                    after=wanted,
                    no_op=unavailable or values_equal(current, wanted),
                )
            )

        for op in self._reset_ops():
            key = placeholders.resolve(op.key, context)
            component = _settings_component(op.component, default="reset")
            current, failure = self._current_setting(key)
            unavailable = failure is not None and is_missing(failure)
            default = self._schema_default(backend, key)
            already = current is None or (default is not None and values_equal(current, default))
            diff.entries.append(
                DiffEntry(
                    op=op,
                    component=component,
                    summary=_novice_phrase(component, 1),
                    before=current,
                    after=default,
                    no_op=unavailable or already,
                )
            )

        enables = self._enable_ops()
        if enables:
            present = installed_extension_uuids()
            current, _failure = self._current_setting(ENABLED_EXTENSIONS_KEY)
            wanted_uuids = [
                uuid
                for uuid in (_resolve_extension(op, present) for op in enables)
                if uuid is not None
            ]
            merged = merge_string_lists(current, format_string_list(wanted_uuids))
            for op in enables:
                resolved = _resolve_extension(op, present)
                diff.entries.append(
                    DiffEntry(
                        op=op,
                        component="addons",
                        summary=_novice_phrase("addons", 1),
                        before=current,
                        after=merged,
                        no_op=resolved is None or (current is not None and resolved in (
                            parse_string_list(current) or []
                        )),
                    )
                )

        if self._install_ops():
            present = installed_extension_uuids()
            for op in self._install_ops():
                diff.entries.append(
                    DiffEntry(
                        op=op,
                        component="addons",
                        summary=_novice_phrase("addons", 1),
                        before="present" if op.uuid in present else None,
                        after="present",
                        # Downloading an add-on needs the network and a consent
                        # dialog, neither of which a plan may assume. A caller
                        # that has both can hand the transaction an
                        # ``installer`` and the apply will fetch it; a plan
                        # never promises that, because a preview that says "and
                        # then it will be downloaded" is a promise the person
                        # reading it has not agreed to yet.
                        no_op=True,
                    )
                )

        return diff

    def apply(
        self,
        progress_cb: Callable[[Progress, str], None] | None = None,
        *,
        restore_point: bool = True,
    ) -> TransactionResult:
        """Apply the transaction, all of it or none of it.

        Args:
            progress_cb: called as ``cb(stage, human_text)`` as work proceeds.
                Runs on the calling thread; the UI marshals to the main loop.
            restore_point: capture a restore point first. Defaults to True and
                there is no good reason to pass False outside tests.

        Returns:
            What was applied, what was skipped and why, and the id of the
            restore point that was taken.

        Raises:
            TransactionError: something failed. ``rolled_back`` says whether
                the desktop was returned to its prior state.
        """
        report = progress_cb or (lambda _stage, _text: None)
        report(Progress.PLANNING, "Working out what will change")
        diff = self.plan()

        try:
            with process_lock():
                return self._apply_locked(diff, report, restore_point)
        except LockBusy as exc:
            raise TransactionError(str(exc), rolled_back=True) from exc

    # -- applying ----------------------------------------------------------

    def _apply_locked(
        self,
        diff: Diff,
        report: Callable[[Progress, str], None],
        restore_point: bool,
    ) -> TransactionResult:
        backend = self._backend
        context = placeholders.runtime_context(backend)
        dests = self._preflight()
        self._policy_preflight(context)
        result = TransactionResult(diff=diff)

        baseline = Baseline(backend=backend).load()
        # Only a Look owns things under its own name. A page edit and a saved
        # moment being put back are the user's own doing, and both belong to
        # MANUAL_OWNER — which the switch cleanup walks past, so a later Look
        # cannot quietly revert them.
        owner = (self.label or self.look) if self.look else MANUAL_OWNER

        # The rollback journal. It is a Baseline pointed at a throwaway
        # directory, which is not a trick: "what was here immediately before
        # this transaction" and "what was here before gtheme ever ran" are the
        # same kind of recording, and reusing the class means symlinks, missing
        # parent directories and unset settings are handled once.
        journal_dir = Path(tempfile.mkdtemp(prefix="gtheme-rollback-"))
        journal = Baseline(journal_dir, backend=backend)
        fresh_files: list[str] = []
        fresh_settings: list[str] = []

        setting_ops = self._setting_ops()
        reset_ops = self._reset_ops()
        remove_ops = self._remove_ops()
        enables = self._enable_ops()

        # AS5. With nowhere to write settings into, every write fails the same
        # way. Reporting that forty times is noise; skipping the phase with one
        # sentence is the useful answer.
        #
        # The question is put to the *backend*, not to the environment. Reading
        # DBUS_SESSION_BUS_ADDRESS directly meant an environment variable could
        # switch off a backend that never needed a bus — the in-memory test
        # seam, whose whole point is to write nowhere real — so the suite's
        # verdict depended on the shell it was launched from (review-report
        # M16). A backend that needs a session says so; one that does not is
        # writable wherever it runs.
        no_session = bool(setting_ops or reset_ops or enables) and not can_write_settings(backend)
        if no_session:
            result.skipped.extend(
                (op, "your desktop session wasn't running, so this was left alone")
                for op in [*setting_ops, *reset_ops, *enables]
            )

        planned_files = [
            str(dests[op.dest])
            for op in (*self._file_ops(), *remove_ops, *self._link_ops())
        ]
        # A Look addresses the terminal profile as
        # ``dconf:/org/gnome/Ptyxis/Profiles/{{ ptyxis_default_profile }}/palette``
        # and the transaction writes the *resolved* path. The restore point has
        # to save the value of the key that is really about to change, so the
        # resolution is done once, here, and handed to the capture — exactly
        # the way ``resolved_dests`` already works for files. Reading the
        # literal token path instead saved nothing and made undo *reset* the
        # user's real value.
        resolved_keys = {
            op.key: placeholders.resolve(op.key, context) for op in (*setting_ops, *reset_ops)
        }
        planned_settings = [
            key for key in resolved_keys.values() if placeholders.key_ok(key)
        ]
        if enables:
            planned_settings.append(ENABLED_EXTENSIONS_KEY)

        ledger = ledger_store.read_ledger()
        prior = ledger.get(owner)
        prior_files = set(prior.get("files", [])) if isinstance(prior, dict) else set()
        prior_settings = set(prior.get("settings", [])) if isinstance(prior, dict) else set()

        # Switching Looks reverts what the outgoing one owned and the incoming
        # one does not manage. That is a real change to the desktop that the
        # diff says nothing about, so the restore point has to cover it too —
        # otherwise "Undo" after a switch returns to the pristine state rather
        # than to the Look that was on a moment ago, which is not what anybody
        # pressing it means.
        orphan_files, orphan_settings = self._orphans_of_other_looks(
            ledger, owner, set(planned_files), set(planned_settings)
        )

        report(Progress.SNAPSHOTTING, "Saving how things look right now")
        if restore_point:
            point = self._capture_restore_point(
                diff,
                backend,
                dests,
                extra_keys=orphan_settings if self.look else [],
                extra_dests=orphan_files if self.look else [],
                resolved_keys=resolved_keys,
            )
            if point is not None:
                result.restore_point = point.id
                result.restore_warnings = list(point.warnings)
                for warning in point.warnings:
                    report(Progress.SNAPSHOTTING, warning)

        # A single change made from a page, and a saved moment being put back,
        # are not switches and must never strip the rest of the desktop — so
        # this runs only for a Look, which is what ``look`` means and ``label``
        # never did.
        cleanup_changed = False
        if self.look:
            cleanup = ledger_store.switch_cleanup(
                owner, set(planned_files), set(planned_settings), baseline
            )
            # Whether the tidy-up really moved anything. AS4 below has to know:
            # a cleanup that reverted the outgoing Look is a real change to the
            # desktop, and "Nothing was changed" would be a lie about it.
            cleanup_changed = bool(cleanup.notes)
            for note in cleanup.notes:
                report(Progress.SNAPSHOTTING, note)
            # What the tidy-up could *not* do. ``ledger`` builds these
            # sentences and nothing read them, so an apply that left part of
            # the previous Look on the desktop reported plain success and the
            # user was told nothing (review-report M1). They travel on the
            # result as well as through the progress callback, because the
            # callback is fire-and-forget and the summary is read afterwards.
            result.cleanup_warnings = list(cleanup.warnings)
            result.cleanup_kept = cleanup.kept
            result.cleanup_dead = cleanup.dead
            for warning in cleanup.warnings:
                report(Progress.SNAPSHOTTING, warning)

        # R4. The claim goes down before the change it describes. A crash
        # between the two leaves a ledger that claims too much, which costs one
        # redundant restore; the other order orphans a change forever.
        ledger_store.write_entry(
            owner, prior_files | set(planned_files), prior_settings | set(planned_settings)
        )
        # The same rule for the same reason: written before the change it
        # describes, so an interrupt leaves a record that claims slightly too
        # much rather than a desktop nothing admits to having changed.
        previous_current = ledger_store.current_record()
        if self.look:
            ledger_store.set_current_look(self.look, label=self.label)

        try:
            self._write_files(dests, context, baseline, journal, fresh_files, result, report)
            # Removals ride with the files, for the same reason writes do: a
            # setting that points at a file must never outlive the file.
            self._remove_files(remove_ops, dests, baseline, journal, fresh_files, result, report)
            self._write_links(
                self._link_ops(), dests, baseline, journal, fresh_files, result, report
            )
            # Add-ons that have to arrive before the settings phase, not after
            # it. An add-on's settings only exist once the add-on does, so a
            # Look that configures one it also installs had every one of those
            # settings skipped as "not installed here" — and the skip was
            # invisible, so the tuning simply never happened and would have
            # worked on a second apply nothing suggested (X1). Installing needs
            # no session either, which is why it also runs when the settings
            # phase is being skipped: a missing add-on is reported rather than
            # silently swallowed with the rest (review-report L4).
            self._install_extensions(result, report)
            if not no_session:
                self._write_settings(
                    setting_ops, context, backend, baseline, journal, fresh_settings, result, report
                )
                self._reset_settings(
                    reset_ops, context, backend, baseline, journal, fresh_settings, result, report
                )
                self._write_extensions(
                    enables, backend, baseline, journal, fresh_settings, result, report
                )
        except TransactionError as exc:
            raise self._failed(
                exc,
                baseline=baseline,
                journal=journal,
                journal_dir=journal_dir,
                fresh_files=fresh_files,
                fresh_settings=fresh_settings,
                cleanup_changed=cleanup_changed,
                owner=owner,
                prior_files=prior_files,
                prior_settings=prior_settings,
                previous_current=previous_current,
                report=report,
            ) from exc
        except Exception as exc:
            # Everything else that can come out of the ops: an unreadable
            # snapshot, a settings failure that is not "not installed here", a
            # malformed key. Only ``TransactionError`` used to reach the
            # rollback, so all of these skipped it, deleted the journal, and
            # left the ledger claiming a Look that was half on the desktop —
            # which the app then reported as "Nothing was changed. Your desktop
            # is exactly as it was." (review-report H1). An unexpected failure
            # is still a failure of *this* transaction and unwinds like one.
            raise self._failed(
                TransactionError(str(exc) or exc.__class__.__name__),
                baseline=baseline,
                journal=journal,
                journal_dir=journal_dir,
                fresh_files=fresh_files,
                fresh_settings=fresh_settings,
                cleanup_changed=cleanup_changed,
                owner=owner,
                prior_files=prior_files,
                prior_settings=prior_settings,
                previous_current=previous_current,
                report=report,
            ) from exc
        except BaseException:
            # An interrupt, or the process being taken down. This arm re-raises
            # after the attempt and does nothing else, which is deliberate and
            # is *not* the H1 hole: the hole was that ordinary failures landed
            # here. A stop is a different thing from a failure. It stands in
            # for the case where no Python runs at all — a SIGKILL, a power cut
            # — and the guarantee for that case is the recording, not a
            # rollback: at every instant it describes exactly what has been
            # changed by then, and the claim written before the change is
            # deliberately too large rather than too small, so ``gtheme
            # rescue`` in a later process can still put everything back. Doing
            # a rollback here would forget the records that make that true.
            # ``tests/regression/test_crash_mid_apply.py`` is the argument.
            baseline.save()
            shutil.rmtree(journal_dir, ignore_errors=True)
            raise

        baseline.save()
        shutil.rmtree(journal_dir, ignore_errors=True)

        # AS4. A transaction where every setting was skipped and nothing else
        # happened did not apply anything, and recording it as the current Look
        # would be a lie the Undo page then has to live with.
        if not result.applied and result.skipped:
            # Withdraw this transaction's claim — and, when the tidy-up already
            # stripped the outgoing Look, do not put the desktop's name back to
            # that Look. It is not on the desktop any more; saying it is would
            # send the Undo page looking for files the cleanup deleted (H9).
            self._restore_ledger(
                owner,
                prior_files,
                prior_settings,
                None if cleanup_changed else previous_current,
            )
            if cleanup_changed:
                # The switch cleanup ran before the ops and really did revert
                # the outgoing Look. Saying "nothing was changed" about a
                # desktop that just lost its previous Look is the one kind of
                # lie this whole file exists to prevent — so say what happened,
                # and do not claim a rollback that did not occur. The restore
                # point taken above covers the tidy-up, so the Undo page can
                # still put it back.
                report(
                    Progress.ROLLED_BACK,
                    "Nothing from this look could be applied, and the previous look was "
                    "tidied up first — use Undo to put it back",
                )
                raise TransactionError(
                    "nothing could be changed — " + result.skipped[0][1],
                    op=result.skipped[0][0],
                    rolled_back=False,
                )
            report(Progress.ROLLED_BACK, "Nothing was changed")
            raise TransactionError(
                "nothing could be changed — " + result.skipped[0][1],
                op=result.skipped[0][0],
                rolled_back=True,
            )

        # Replace the claim made before the work with what the work actually
        # did. Anything skipped is no longer claimed, so nothing tries to undo
        # a change that never happened.
        applied_files = [
            str(dests[op.dest])
            for op in result.applied
            if isinstance(op, FileWrite | FileRemove | FileLink)
        ]
        ledger_store.write_entry(
            owner,
            prior_files | set(applied_files),
            prior_settings | set(self._applied_setting_keys(result, context)),
        )

        report(Progress.DONE, "Done")
        return result

    def _failed(
        self,
        exc: TransactionError,
        *,
        baseline: Baseline,
        journal: Baseline,
        journal_dir: Path,
        fresh_files: list[str],
        fresh_settings: list[str],
        cleanup_changed: bool,
        owner: str,
        prior_files: set[str],
        prior_settings: set[str],
        previous_current: dict | None,
        report: Callable[[Progress, str], None],
    ) -> TransactionError:
        """Unwind a failed apply and build the error the caller will see.

        One path for every kind of failure, which is the point: the rollback
        used to be reachable only from ``TransactionError`` while three other
        exception types could come out of the same block (review-report H1).

        ``rolled_back`` is the honest answer to "is the desktop as it was?",
        and it is two questions, not one. The journal says whether this
        transaction's own operations came back. The switch cleanup ran *before*
        them, outside the journal, and a cleanup that really reverted the
        outgoing Look is a change nothing here can undo — so a clean unwind of
        this transaction is still not "nothing was changed" (H9).
        """
        baseline.save()
        unwound = self._roll_back(journal, baseline, fresh_files, fresh_settings, report)
        # R4 from the failure side. Withdrawing the claim is right only when
        # the change it describes really did come back off the desktop. After a
        # rollback that could not finish, the leftover change is still there —
        # and a ledger that no longer claims it is a change nothing will ever
        # tidy up. Over-claiming costs one redundant restore; this costs the
        # item forever.
        if unwound:
            self._restore_ledger(
                owner,
                prior_files,
                prior_settings,
                # Never point the desktop back at a Look the tidy-up already
                # stripped off it: its files are gone, and naming it would send
                # the Undo page after something that is not there (H9).
                None if cleanup_changed else previous_current,
            )
        if cleanup_changed:
            report(
                Progress.ROLLED_BACK,
                "Everything this look had changed was put back, but the previous look was "
                "tidied up first — use Undo to put that back",
            )
        shutil.rmtree(journal_dir, ignore_errors=True)
        return TransactionError(
            str(exc), op=exc.op, rolled_back=unwound and not cleanup_changed
        )

    def _applied_setting_keys(
        self,
        result: TransactionResult,
        context: dict[str, str],
    ) -> list[str]:
        """The setting keys this transaction actually owns now."""
        keys = [
            placeholders.resolve(op.key, context)
            for op in result.applied
            if isinstance(op, SettingWrite | SettingReset)
        ]
        if any(isinstance(op, ExtensionEnable) for op in result.applied):
            keys.append(ENABLED_EXTENSIONS_KEY)
        return keys

    @staticmethod
    def _orphans_of_other_looks(
        ledger: dict[str, dict],
        owner: str,
        incoming_files: set[str],
        incoming_settings: set[str],
    ) -> tuple[list[str], list[str]]:
        """What a switch is about to revert: ``(files, settings)``.

        Every entry is walked, not just the most recent one, because a
        component overlaid from a third Look is still owned by that third Look.
        """
        files: list[str] = []
        settings: list[str] = []
        for name, owned in ledger.items():
            # Same exclusion as the cleanup itself: the user's own edits are
            # not a previous Look, are not reverted, and so are not part of
            # what the restore point has to cover.
            if name in (owner, MANUAL_OWNER) or not isinstance(owned, dict):
                continue
            files.extend(f for f in owned.get("files", []) if f not in incoming_files)
            settings.extend(s for s in owned.get("settings", []) if s not in incoming_settings)
        return files, settings

    def _capture_restore_point(
        self,
        diff: Diff,
        backend: SettingsBackend,
        dests: dict[str, Path],
        *,
        extra_keys: list[str] | None = None,
        extra_dests: list[str] | None = None,
        resolved_keys: dict[str, str] | None = None,
    ) -> Any:
        """Take a restore point before touching anything, or refuse to go on.

        A restore point that cannot be *written* used to be worth going
        without: the pristine baseline is a real guarantee and is recorded
        regardless. That reasoning was right about the engine and wrong about
        the person, because by the time this runs the dialog has already said
        "gtheme saves how your desktop looks right now. You can put it back
        with one click" (persona-report §2.5). Going on after that turns a
        promise the user agreed to into one they were never told was withdrawn
        — and the only sign of it was a missing button on an eight-second
        toast. So the failure stops the apply instead.

        Stopping here is cheap and honest: nothing has been written yet — not a
        file, not a setting, not the ledger — so this is genuinely the
        "nothing was changed" case and says so.

        Returns:
            The restore point, or None when the transaction would change
            nothing at all and there was nothing to save. Its ``warnings`` are
            what could only be saved in part, and the caller carries them out
            to the person rather than dropping them.

        Raises:
            TransactionError: the moment could not be saved. ``rolled_back`` is
                True because there is nothing yet to roll back.
        """
        # Imported here rather than at module scope because a restore point is
        # itself applied as a transaction.
        from . import restorepoints

        try:
            return restorepoints.capture_from_diff(
                diff,
                label=self.label or "Before your last change",
                backend=backend,
                resolved_dests={raw: str(path) for raw, path in dests.items()},
                resolved_keys=resolved_keys,
                extra_keys=extra_keys,
                extra_dests=extra_dests,
            )
        except OSError as exc:
            raise TransactionError(
                f"could not save how your desktop looks right now, so nothing was "
                f"changed: {exc}",
                rolled_back=True,
            ) from exc

    def _snapshot_file(
        self,
        op: Op,
        dest: Path,
        component: str,
        baseline: Baseline,
        journal: Baseline,
    ) -> bool:
        """Record what is at ``dest`` before changing it. Returns False for F1.

        The R4 rule says this happens before the change, and P5 says it happens
        *inside the same guard* as the change. It did not: every write was
        wrapped in a ``try`` and the recording that must precede it was not, so
        a full disk or an unreadable file at a destination raised an ``OSError``
        straight past the rollback (review-report H1/P5). A recording that
        cannot be made is a reason not to make the change, and it is this
        transaction's failure like any other.

        Returns:
            False when something that is not an ordinary file is already at the
            destination (F1) — it cannot be copied, so it cannot be put back,
            so it is not touched.

        Raises:
            TransactionError: the old state could not be saved.
        """
        try:
            if not baseline.record_file(dest, component, self.label or ""):
                return False
            journal.record_file(dest, component, self.label or "")
        except (BaselineError, OSError) as exc:
            raise TransactionError(
                f"could not save the old value of {dest} before changing it: {exc}", op=op
            ) from exc
        return True

    def _snapshot_setting(
        self,
        op: Op,
        key: str,
        component: str,
        baseline: Baseline,
        journal: Baseline,
    ) -> None:
        """Record a setting's old value before changing it. See P5 above.

        Raises:
            TransactionError: the old value could not be read or saved — a
                malformed key, a settings service that is not answering, a
                recording directory that cannot be written.
        """
        try:
            baseline.record_setting(key, component, self.label or "")
            if key not in journal.settings:
                journal.record_setting(key, component, self.label or "")
        except (BackendError, BaselineError, OSError) as exc:
            raise TransactionError(
                f"could not save the old value of {key} before changing it: {exc}", op=op
            ) from exc

    def _write_files(
        self,
        dests: dict[str, Path],
        context: dict[str, str],
        baseline: Baseline,
        journal: Baseline,
        fresh_files: list[str],
        result: TransactionResult,
        report: Callable[[Progress, str], None],
    ) -> None:
        """Files first: a Look that points a setting at a file it also ships
        must have shipped the file by the time the setting takes effect."""
        ops = self._file_ops()
        if not ops:
            return
        report(Progress.WRITING_FILES, f"Copying {len(ops)} file(s) into place")
        for op in ops:
            dest = dests[op.dest]
            data = self._rendered(op, context)
            key = str(dest)
            newly = key not in baseline.files
            if not self._snapshot_file(op, dest, "files", baseline, journal):
                # F1. There is a pipe, socket or device node where this file
                # should go. It cannot be copied, so it cannot be put back, so
                # it is not overwritten.
                result.skipped.append(
                    (op, f"something that is not an ordinary file is already at {dest}")
                )
                continue
            if newly:
                fresh_files.append(key)
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.is_dir() and not dest.is_symlink():
                    raise IsADirectoryError(f"{dest} is a folder, not a file")
                atomic_write_bytes(dest, data, self._file_mode(op))
            except OSError as exc:
                raise TransactionError(f"could not write {dest}: {exc}", op=op) from exc
            result.applied.append(op)

    def _remove_files(
        self,
        ops: list[FileRemove],
        dests: dict[str, Path],
        baseline: Baseline,
        journal: Baseline,
        fresh_files: list[str],
        result: TransactionResult,
        report: Callable[[Progress, str], None],
    ) -> None:
        """Delete files that should not be there. Recorded first, so undoable.

        The order relative to :meth:`_write_files` does not matter — a
        transaction may not both write and remove the same destination, and
        nothing checks that because nothing can produce it: a restore point
        records each destination once, as either "this was here" or "this was
        not".
        """
        if not ops:
            return
        report(Progress.WRITING_FILES, f"Removing {len(ops)} file(s)")
        for op in ops:
            dest = dests[op.dest]
            if not dest.exists() and not dest.is_symlink():
                # Already gone. Not a skip: the desired state is the state.
                result.applied.append(op)
                continue
            key = str(dest)
            newly = key not in baseline.files
            if not self._snapshot_file(op, dest, op.component or "files", baseline, journal):
                # F1 again, from the other side: something that is not an
                # ordinary file cannot be copied, so it cannot be put back, so
                # it does not get deleted.
                result.skipped.append(
                    (op, f"something that is not an ordinary file is at {dest}, so it was left alone")
                )
                continue
            if newly:
                fresh_files.append(key)
            try:
                dest.unlink()
            except OSError as exc:
                raise TransactionError(f"could not remove {dest}: {exc}", op=op) from exc
            result.applied.append(op)

    def _write_links(
        self,
        ops: list[FileLink],
        dests: dict[str, Path],
        baseline: Baseline,
        journal: Baseline,
        fresh_files: list[str],
        result: TransactionResult,
        report: Callable[[Progress, str], None],
    ) -> None:
        """Put back a shortcut that was at a destination before a Look wrote there.

        Recorded first like every other change, so it rolls back, and the link
        is *replaced* rather than written through: following it would edit
        whatever it points at, which is somebody's dotfiles repository.
        """
        if not ops:
            return
        report(Progress.WRITING_FILES, f"Putting back {len(ops)} shortcut(s)")
        for op in ops:
            dest = dests[op.dest]
            if dest.is_symlink() and str(dest.readlink()) == op.target:
                # Already the link it should be. The desired state is the state.
                result.applied.append(op)
                continue
            key = str(dest)
            newly = key not in baseline.files
            if not self._snapshot_file(op, dest, op.component or "files", baseline, journal):
                result.skipped.append(
                    (op, f"something that is not an ordinary file is at {dest}, so it was left alone")
                )
                continue
            if newly:
                fresh_files.append(key)
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.is_symlink() or dest.exists():
                    dest.unlink()
                dest.symlink_to(op.target)
            except OSError as exc:
                raise TransactionError(
                    f"could not put back the shortcut at {dest}: {exc}", op=op
                ) from exc
            result.applied.append(op)

    def _reset_settings(
        self,
        ops: list[SettingReset],
        context: dict[str, str],
        backend: SettingsBackend,
        baseline: Baseline,
        journal: Baseline,
        fresh_settings: list[str],
        result: TransactionResult,
        report: Callable[[Progress, str], None],
    ) -> None:
        """Put settings back to having no value of their own.

        Same shape as :meth:`_write_settings`, and deliberately so: recorded
        before it happens, an unreadable key is a named skip rather than a
        failure (AS8), and the rollback journal has what it needs to put the
        old value back if anything later in the transaction fails.
        """
        if not ops:
            return
        report(Progress.WRITING_SETTINGS, f"Putting {len(ops)} setting(s) back")
        for op in ops:
            key = placeholders.resolve(op.key, context)
            if not placeholders.key_ok(key):
                result.skipped.append(
                    (op, "this setting's location came out incomplete on this computer")
                )
                continue
            _current, failure = self._current_setting(key)
            if failure is not None and is_missing(failure):
                result.skipped.append((op, "that part of your desktop isn't installed here"))
                continue
            newly = key not in baseline.settings
            self._snapshot_setting(op, key, op.component or "other", baseline, journal)
            try:
                backend.reset(key)
            except BackendError as exc:
                if newly:
                    baseline.forget_settings([key])
                if is_missing(exc):
                    result.skipped.append((op, "that part of your desktop isn't installed here"))
                    continue
                raise TransactionError(f"could not put {key} back: {exc}", op=op) from exc
            if newly:
                fresh_settings.append(key)
            result.applied.append(op)

    def _write_settings(
        self,
        ops: list[SettingWrite],
        context: dict[str, str],
        backend: SettingsBackend,
        baseline: Baseline,
        journal: Baseline,
        fresh_settings: list[str],
        result: TransactionResult,
        report: Callable[[Progress, str], None],
    ) -> None:
        if not ops:
            return
        report(Progress.WRITING_SETTINGS, f"Changing {len(ops)} setting(s)")
        for op in ops:
            key, value, skip = self._planned_setting(op, context)
            if skip is not None:
                result.skipped.append((op, skip))
                continue
            current, failure = self._current_setting(key)
            if failure is not None and is_missing(failure):
                # AS8. The add-on or the app this belongs to is not on this
                # machine. One skip with a sentence, never a failed apply.
                result.skipped.append((op, "that part of your desktop isn't installed here"))
                continue
            wanted = value
            if op.merge == "list-union":
                merged = merge_string_lists(current, value)
                if merged is not None:
                    wanted = merged
            if values_equal(current, wanted):
                result.applied.append(op)
                continue
            newly = key not in baseline.settings
            self._snapshot_setting(op, key, op.component or "other", baseline, journal)
            try:
                backend.set(key, wanted)
            except BackendError as exc:
                if newly:
                    # Never keep a record for a key that was never changed:
                    # restoring it later would write a value nothing set.
                    baseline.forget_settings([key])
                if is_missing(exc):
                    result.skipped.append((op, "that part of your desktop isn't installed here"))
                    continue
                raise TransactionError(f"could not change {key}: {exc}", op=op) from exc
            if newly:
                fresh_settings.append(key)
            result.applied.append(op)

    def _install_extensions(
        self,
        result: TransactionResult,
        report: Callable[[Progress, str], None],
    ) -> None:
        """Get the add-ons this transaction needs, *before* the settings phase.

        Order is the whole fix. An add-on's settings do not exist until the
        add-on does, so a Look that installs an add-on and then configures it
        had every one of those settings answered with "that part of your
        desktop isn't installed here" — a skip nobody rendered, on a phase that
        ran before the add-on arrived. The tuning silently never happened, and
        would have worked on a second apply nothing suggested (X1).

        Downloading is still not something this layer does by itself: it needs
        the network and a person's consent, both of which belong to the caller.
        A caller that has them hands the transaction an ``installer`` — the
        same per-instance seam ``backend`` uses — and it runs here. With no
        installer, a missing add-on is a named skip, exactly as before, and the
        skip is now reported whether or not there is a desktop session to write
        settings into, because listing what is installed is a directory listing
        and needs neither (review-report L4).

        Nothing here is rolled back: gtheme cannot un-install an add-on, and an
        installed add-on that is never turned on changes nothing about the
        desktop. What *does* change the desktop — the enabled list — is written
        in the settings phase and rolls back with it.
        """
        ops = self._install_ops()
        if not ops:
            return
        present = installed_extension_uuids()
        pending = [op for op in ops if op.uuid not in present]
        if not pending:
            return
        installer: Callable[[ExtensionInstall], bool] | None = getattr(self, "installer", None)
        if installer is not None:
            report(Progress.EXTENSIONS, f"Getting {len(pending)} add-on(s)")
        for op in pending:
            if installer is not None and op.source != "local-only":
                try:
                    landed = bool(installer(op))
                except Exception as exc:  # noqa: BLE001 - a download is allowed to fail
                    landed = False
                    report(Progress.EXTENSIONS, f"could not get an add-on: {exc}")
                if landed and op.uuid in installed_extension_uuids():
                    result.applied.append(op)
                    continue
                result.skipped.append((op, "this add-on could not be downloaded"))
                continue
            if op.source == "local-only":
                result.skipped.append(
                    (op, "this look uses a private add-on that isn't on this computer")
                )
            else:
                result.skipped.append(
                    (op, "this add-on isn't installed yet — install it from the Add-ons page first")
                )

    def _write_extensions(
        self,
        ops: list[ExtensionEnable],
        backend: SettingsBackend,
        baseline: Baseline,
        journal: Baseline,
        fresh_settings: list[str],
        result: TransactionResult,
        report: Callable[[Progress, str], None],
    ) -> None:
        """Turn add-ons on by unioning into the one shared list (X1).

        Every add-on the user turned on themselves is in that list. Writing a
        Look's list over the top is experienced as the app deleting their dock,
        so the Look's members are added to theirs and the recording keeps the
        exact value from before, so undo restores their list rather than a
        computed difference.

        Getting add-ons that are not here yet happens earlier, in
        :meth:`_install_extensions`, so their settings exist by the time the
        settings phase runs.
        """
        if not ops:
            return
        present = installed_extension_uuids()
        wanted: list[str] = []
        # An op is applied or it is skipped, never both. The unresolvable ones
        # are already in ``result.skipped``, so everything below counts only
        # the ops that really are being turned on — otherwise an add-on that is
        # not installed is reported as enabled, the AS4 gate below sees a
        # transaction that "applied" something it did not, and every caller
        # that counts applied ops over-reports what happened.
        resolved_ops: list[ExtensionEnable] = []
        for op in ops:
            resolved = _resolve_extension(op, present)
            if resolved is None:
                result.skipped.append((op, "that add-on isn't installed on this computer"))
                continue
            wanted.append(resolved)
            resolved_ops.append(op)
        if not wanted:
            return

        report(Progress.EXTENSIONS, f"Turning on {len(wanted)} add-on(s)")
        key = ENABLED_EXTENSIONS_KEY
        current, failure = self._current_setting(key)
        if failure is not None and is_missing(failure):
            for op in resolved_ops:
                result.skipped.append((op, "add-ons cannot be turned on on this computer"))
            return
        merged = merge_string_lists(current, format_string_list(wanted))
        if merged is None or values_equal(current, merged):
            result.applied.extend(resolved_ops)
            return
        newly = key not in baseline.settings
        self._snapshot_setting(resolved_ops[0], key, "addons", baseline, journal)
        try:
            backend.set(key, merged)
        except BackendError as exc:
            if newly:
                baseline.forget_settings([key])
            raise TransactionError(
                f"could not turn the add-ons on: {exc}", op=resolved_ops[0]
            ) from exc
        if newly:
            fresh_settings.append(key)
        result.applied.extend(resolved_ops)

    def _roll_back(
        self,
        journal: Baseline,
        baseline: Baseline,
        fresh_files: list[str],
        fresh_settings: list[str],
        report: Callable[[Progress, str], None],
    ) -> bool:
        """Put back everything this transaction changed. All of it or none.

        Returns:
            Whether the desktop really did come back. False is the serious
            case and the caller must say so in plain words rather than
            reporting a tidy failure.
        """
        report(Progress.ROLLED_BACK, "Putting everything back the way it was")
        files = journal.restore_files()
        settings = journal.restore_settings()
        # Records this transaction created are the ones that describe changes
        # that have now been undone. Dropping them means the next apply takes a
        # fresh snapshot rather than restoring to a moment that never happened.
        baseline.forget_files([key for key in fresh_files if key in files.done])
        baseline.forget_settings([key for key in fresh_settings if key in settings.done])
        return not files.warnings and not settings.warnings

    def _restore_ledger(
        self,
        owner: str,
        files: set[str],
        settings: set[str],
        previous_current: dict | None = None,
    ) -> None:
        """Undo the R4 early write, keeping ownership from earlier applies.

        An owner that already owned things before this transaction still owns
        them — they are still on disk. Only the claim this transaction added is
        withdrawn, and that includes the claim to be the Look in use: AS4's
        whole point is that a transaction which applied nothing did not apply
        anything, and recording it as the current Look would be a lie the Undo
        page then has to live with.
        """
        if files or settings:
            ledger_store.write_entry(owner, files, settings)
        else:
            ledger_store.drop_entry(owner)
        if self.look:
            name = (previous_current or {}).get("name")
            if name:
                ledger_store.set_current_look(
                    str(name), label=(previous_current or {}).get("label")
                )
            else:
                ledger_store.clear_current_look()
