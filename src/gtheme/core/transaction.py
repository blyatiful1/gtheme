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
from typing import Literal

from . import ledger as ledger_store
from . import placeholders
from .atomic import atomic_write_bytes
from .backends import get_backend, has_session_bus, is_missing
from .baseline import Baseline
from .confine import ConfinementError, confine_dest
from .gvariant import format_string_list, merge_string_lists, parse_string_list, values_equal
from .lock import LockBusy, process_lock
from .paths import dest_root, xdg_data_home
from .settings_backend import BackendError, SettingsBackend

__all__ = [
    "Diff",
    "DiffEntry",
    "ExtensionEnable",
    "ExtensionInstall",
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
Op = FileWrite | FileRemove | SettingWrite | SettingReset | ExtensionEnable | ExtensionInstall


#: The one key that is shared global state. Every add-on the user turned on
#: themselves lives in this list, which is why a Look unions into it rather
#: than writing over it. See ``core.gvariant.merge_string_lists`` (the X1
#: defect).
ENABLED_EXTENSIONS_KEY = "gsettings:org.gnome.shell enabled-extensions"

#: Ledger owner name for changes that came from a page rather than a Look.
#: Switching Looks tidies up after other Looks; it never tidies up after the
#: user's own deliberate edits.
MANUAL_OWNER = "__manual__"

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
        """
        counted: dict[str, int] = {}
        only: dict[str, DiffEntry] = {}
        for entry in self.changes:
            counted[entry.component] = counted.get(entry.component, 0) + 1
            only[entry.component] = entry

        def phrase(component: str, count: int) -> str:
            if count == 1 and component in _NAMED_WHEN_SINGLE:
                return only[component].summary
            return _novice_phrase(component, count)

        lines: list[str] = []
        for component in _COMPONENT_ORDER:
            count = counted.pop(component, 0)
            if count:
                lines.append(phrase(component, count))
        for component in sorted(counted):
            lines.append(phrase(component, counted[component]))
        return lines


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
        label: what to call this in the saved-moment list ("NIGHTBLOOM"). Also
            the ledger owner name, and the flag that says this is a whole Look
            rather than one change made from a page — which is what turns the
            switch cleanup on.
        look: the Look's own folder name, when this transaction is a Look being
            applied. Separate from ``label`` on purpose: a Look's label is its
            title, which is what a person was shown, and its name is what a
            lookup matches on. Recording only the title is how the guess this
            replaced went wrong — and a saved moment being put back carries a
            label too ("My desktop, 25 August") and is emphatically not a Look.
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
        """The settings backend. Overridable per instance, mostly for tests."""
        override = getattr(self, "backend", None)
        return override if override is not None else get_backend()

    @property
    def _root(self) -> Path:
        return Path(self.dest_root) if self.dest_root else dest_root()

    def _file_ops(self) -> list[FileWrite]:
        return [op for op in self.ops if isinstance(op, FileWrite)]

    def _remove_ops(self) -> list[FileRemove]:
        return [op for op in self.ops if isinstance(op, FileRemove)]

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
        for op in (*self._file_ops(), *self._remove_ops()):
            try:
                resolved[op.dest] = confine_dest(op.dest, root=self._root)
            except ConfinementError as exc:
                raise TransactionError(str(exc), op=op) from exc
        return resolved

    def _rendered(self, op: FileWrite, context: dict[str, str]) -> bytes:
        """The exact bytes ``op`` would write.

        Raises:
            TransactionError: the source is missing, unreadable, or is being
                templated while not being text. That last one is not fussiness:
                templating a binary file used to truncate the destination to
                nothing.
        """
        source = Path(op.src)
        if not source.is_absolute():
            raise TransactionError(
                f"this look's file {op.src!r} was not resolved to a full location before "
                "the change was prepared",
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
        """``(value, failure)``. A missing schema is a value of None, not a raise."""
        try:
            return self._backend.get(key), None
        except BackendError as exc:
            return None, exc

    def _planned_setting(
        self, op: SettingWrite, context: dict[str, str]
    ) -> tuple[str, str, str | None]:
        """``(key, value, skip_reason)`` for one setting, tokens resolved."""
        key = placeholders.resolve(op.key, context)
        value = placeholders.resolve(op.value, context)
        if not placeholders.key_ok(key):
            missing = placeholders.unresolved_tokens(op.key) + placeholders.unresolved_tokens(op.value)
            if missing:
                return key, value, (
                    "this needs something that is not set up on this computer yet "
                    f"({', '.join(missing)})"
                )
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
        dests = self._preflight()
        backend = self._backend
        context = placeholders.runtime_context(backend)
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
            diff.entries.append(
                DiffEntry(
                    op=op,
                    component="files",
                    summary=_novice_phrase("files", 1),
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
                        # Downloading an add-on is not something this layer can
                        # do — it needs the network and a consent dialog. The
                        # Add-ons page installs first and then applies, so by
                        # the time a transaction runs, an add-on is either here
                        # or it is a named skip. Never a promise it cannot keep.
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
        result = TransactionResult(diff=diff)

        baseline = Baseline(backend=backend).load()
        owner = self.label or MANUAL_OWNER

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

        # AS5. With no session to write into, every settings write fails the
        # same way. Reporting that forty times is noise; skipping the phase
        # with one sentence is the useful answer.
        no_session = bool(setting_ops or reset_ops or enables) and not has_session_bus()
        if no_session:
            result.skipped.extend(
                (op, "your desktop session wasn't running, so this was left alone")
                for op in [*setting_ops, *reset_ops, *enables]
            )

        planned_files = [
            str(dests[op.dest]) for op in (*self._file_ops(), *remove_ops)
        ]
        planned_settings = [
            placeholders.resolve(op.key, context)
            for op in (*setting_ops, *reset_ops)
            if placeholders.key_ok(placeholders.resolve(op.key, context))
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
            result.restore_point = self._capture_restore_point(
                diff,
                backend,
                dests,
                extra_keys=orphan_settings if self.label else [],
                extra_dests=orphan_files if self.label else [],
            )

        # A single change made from a page is not a switch and must never strip
        # the rest of the desktop, so this runs only for a Look.
        if self.label:
            cleanup = ledger_store.switch_cleanup(
                owner, set(planned_files), set(planned_settings), baseline
            )
            for note in cleanup.notes:
                report(Progress.SNAPSHOTTING, note)

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
            baseline.save()
            rolled_back = self._roll_back(journal, baseline, fresh_files, fresh_settings, report)
            self._restore_ledger(owner, prior_files, prior_settings, previous_current)
            shutil.rmtree(journal_dir, ignore_errors=True)
            raise TransactionError(str(exc), op=exc.op, rolled_back=rolled_back) from exc
        except BaseException:
            # A crash, an interrupt, anything. The recording persisted itself
            # record by record, so it already describes exactly what had been
            # touched; flushing the indexes keeps it readable.
            baseline.save()
            shutil.rmtree(journal_dir, ignore_errors=True)
            raise

        baseline.save()
        shutil.rmtree(journal_dir, ignore_errors=True)

        # AS4. A transaction where every setting was skipped and nothing else
        # happened did not apply anything, and recording it as the current Look
        # would be a lie the Undo page then has to live with.
        if not result.applied and result.skipped:
            self._restore_ledger(owner, prior_files, prior_settings, previous_current)
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
            if isinstance(op, FileWrite | FileRemove)
        ]
        ledger_store.write_entry(
            owner,
            prior_files | set(applied_files),
            prior_settings | set(self._applied_setting_keys(result, context)),
        )

        report(Progress.DONE, "Done")
        return result

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
            if name == owner or not isinstance(owned, dict):
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
    ) -> str | None:
        """Take a restore point before touching anything. Never fatal.

        A restore point that cannot be written is worth going without, not a
        refusal: the pristine baseline is the real guarantee and is recorded
        regardless. Imported here rather than at module scope because a restore
        point is itself applied as a transaction.
        """
        from . import restorepoints

        try:
            point = restorepoints.capture_from_diff(
                diff,
                label=self.label or "Before your last change",
                backend=backend,
                resolved_dests={raw: str(path) for raw, path in dests.items()},
                extra_keys=extra_keys,
                extra_dests=extra_dests,
            )
        except OSError:
            return None
        return point.id if point is not None else None

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
            if not baseline.record_file(dest, "files", self.label or ""):
                # F1. There is a pipe, socket or device node where this file
                # should go. It cannot be copied, so it cannot be put back, so
                # it is not overwritten.
                result.skipped.append(
                    (op, f"something that is not an ordinary file is already at {dest}")
                )
                continue
            if newly:
                fresh_files.append(key)
            journal.record_file(dest, "files", self.label or "")
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
            if not baseline.record_file(dest, op.component or "files", self.label or ""):
                # F1 again, from the other side: something that is not an
                # ordinary file cannot be copied, so it cannot be put back, so
                # it does not get deleted.
                result.skipped.append(
                    (op, f"something that is not an ordinary file is at {dest}, so it was left alone")
                )
                continue
            if newly:
                fresh_files.append(key)
            journal.record_file(dest, op.component or "files", self.label or "")
            try:
                dest.unlink()
            except OSError as exc:
                raise TransactionError(f"could not remove {dest}: {exc}", op=op) from exc
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
            baseline.record_setting(key, op.component or "other", self.label or "")
            if key not in journal.settings:
                journal.record_setting(key, op.component or "other", self.label or "")
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
            baseline.record_setting(key, op.component or "other", self.label or "")
            if key not in journal.settings:
                journal.record_setting(key, op.component or "other", self.label or "")
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
        """
        for op in self._install_ops():
            if op.uuid in installed_extension_uuids():
                continue
            if op.source == "local-only":
                result.skipped.append(
                    (op, "this look uses a private add-on that isn't on this computer")
                )
            else:
                result.skipped.append(
                    (op, "this add-on isn't installed yet — install it from the Add-ons page first")
                )

        if not ops:
            return
        present = installed_extension_uuids()
        wanted: list[str] = []
        for op in ops:
            resolved = _resolve_extension(op, present)
            if resolved is None:
                result.skipped.append((op, "that add-on isn't installed on this computer"))
                continue
            wanted.append(resolved)
        if not wanted:
            return

        report(Progress.EXTENSIONS, f"Turning on {len(wanted)} add-on(s)")
        key = ENABLED_EXTENSIONS_KEY
        current, failure = self._current_setting(key)
        if failure is not None and is_missing(failure):
            for op in ops:
                result.skipped.append((op, "add-ons cannot be turned on on this computer"))
            return
        merged = merge_string_lists(current, format_string_list(wanted))
        if merged is None or values_equal(current, merged):
            result.applied.extend(ops)
            return
        newly = key not in baseline.settings
        baseline.record_setting(key, "addons", self.label or "")
        if key not in journal.settings:
            journal.record_setting(key, "addons", self.label or "")
        try:
            backend.set(key, merged)
        except BackendError as exc:
            if newly:
                baseline.forget_settings([key])
            raise TransactionError(f"could not turn the add-ons on: {exc}", op=ops[0]) from exc
        if newly:
            fresh_settings.append(key)
        result.applied.extend(ops)

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
