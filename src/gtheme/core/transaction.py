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

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

__all__ = [
    "Diff",
    "DiffEntry",
    "ExtensionEnable",
    "ExtensionInstall",
    "FileWrite",
    "MergeMode",
    "Op",
    "Progress",
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
        src: source path inside the Look's folder.
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
Op = FileWrite | SettingWrite | ExtensionEnable | ExtensionInstall


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
        """
        raise NotImplementedError("Diff.to_novice_lines")


@dataclass
class TransactionResult:
    """The outcome of an applied transaction."""

    diff: Diff
    applied: list[Op] = field(default_factory=list)
    skipped: list[tuple[Op, str]] = field(default_factory=list)
    restore_point: str | None = None


class Transaction:
    """An all-or-nothing batch of changes to the desktop.

    Args:
        ops: the operations, in author order. Execution order is imposed by
            the engine (files, then settings, then extensions), not by this
            sequence.
        dest_root: the root every file write must stay inside. Defaults to the
            user's home; ``GTHEME_DEST_ROOT`` overrides it, and that override
            is the seam the test suite uses to keep off the real desktop.
        label: what to call this in the restore-point list ("NIGHTBLOOM").
    """

    def __init__(
        self,
        ops: Iterable[Op] = (),
        *,
        dest_root: str | None = None,
        label: str | None = None,
    ) -> None:
        self.ops: Sequence[Op] = tuple(ops)
        self.dest_root = dest_root
        self.label = label

    def plan(self) -> Diff:
        """Compute what would change, touching nothing.

        Reads current values through the settings backend and hashes the files
        that would be overwritten. Runs the full confinement preflight, so a
        transaction that would escape its destination root fails here — before
        the user is even shown a confirmation.

        Raises:
            TransactionError: the transaction cannot be applied at all.
        """
        raise NotImplementedError("Transaction.plan")

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
        raise NotImplementedError("Transaction.apply")
