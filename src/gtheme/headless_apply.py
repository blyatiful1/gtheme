"""Using a Look from a terminal, with no window open.

The engine has always been able to do this — :meth:`Transaction.apply` takes no
widgets — but the only route from a finished Look to a changed desktop was
logging in and clicking (persona-report, Marek). Anyone who keeps their setup in
a git repository, or who wants a machine to look the same after a reinstall,
had nothing to run.

What this module is *not* is a second apply path. It compiles the Look with the
same :func:`~gtheme.preset.compile.compile_preset` the app's Looks page uses,
and hands the result to the same :class:`~gtheme.core.transaction.Transaction`:
same restore point, same first-touch recording, same rollback, same refusals.
The only thing that is different is where the sentences come out.

Three rules shape what gets printed.

**Say the same things the dialog says.** The preview lines are
:meth:`Diff.to_novice_lines` verbatim, so the terminal and the window describe
one Look the same way. That includes the files a Look may write but that can
start a program: those are named one by one and never collapsed into a count,
which is the whole reason the app is allowed to write them at all.

**A refusal is not a crash.** A Look that asks for something no Look may have
prints why, in the same words the dialog would use, and exits 1 without
touching the desktop.

**Being made for a newer desktop is a warning.** ``min_shell`` has always been
documented as something that warns and never blocks, so it is printed and the
Look is applied anyway.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .core.transaction import (
    ExtensionInstall,
    Progress,
    Transaction,
    TransactionError,
    installed_extension_uuids,
)
from .preset.compile import compile_preset
from .preset.loader import discover, load
from .preset.model import PRESET_FILENAME

__all__ = [
    "HeadlessPlan",
    "LookNotFound",
    "detect_shell_version",
    "make_plan",
    "plan_report",
    "resolve_look",
    "run_apply",
]


class LookNotFound(Exception):
    """No Look by that name, and nothing at that place.

    The message is the sentence to print. It names what was looked for and,
    when a name was asked for, what names there are — a list is the only useful
    thing to say to somebody who has just mistyped one.
    """


def _looks_like_a_place(target: str) -> bool:
    """Is this a folder someone is pointing at, rather than a Look's name?

    A Look's name cannot contain a slash (``registry.safe_name`` refuses one),
    so a slash is unambiguous. ``~`` and a leading dot are the other two ways
    people write a place.
    """
    return "/" in target or target.startswith(("~", "."))


def resolve_look(target: str) -> Path:
    """The folder a Look lives in, from a name or from a place.

    Args:
        target: a Look's name as the app lists it, or the path to the folder a
            Look lives in, or the path to its ``theme.toml`` itself — people
            tab-complete onto the file, and refusing that would be pedantry.

    Raises:
        LookNotFound: nothing was there.
    """
    if _looks_like_a_place(target):
        place = Path(target).expanduser()
        if place.is_file() and place.name == PRESET_FILENAME:
            place = place.parent
        if not (place / PRESET_FILENAME).is_file():
            raise LookNotFound(
                f"there is no Look in {place} — a Look is a folder with a "
                f"{PRESET_FILENAME} file in it"
            )
        return place

    installed = discover()
    if target in installed:
        return installed[target]
    # A bare folder name in the folder you are standing in. Cheap to check, and
    # it is what someone who has just unpacked a Look next to them will type.
    here = Path(target)
    if (here / PRESET_FILENAME).is_file():
        return here

    names = sorted(installed)
    if names:
        raise LookNotFound(
            f"there is no Look called {target!r} on this computer. "
            f"The Looks that are here: {', '.join(names)}"
        )
    raise LookNotFound(
        f"there is no Look called {target!r} on this computer, and no Looks are "
        "installed yet"
    )


def detect_shell_version() -> str | None:
    """What this desktop calls itself, or None when it cannot be asked.

    Read-only, and never fatal. A version that cannot be read means the
    ``min_shell`` sentence is not said at all, which is the honest outcome:
    nothing was measured, so nothing is claimed.
    """
    try:
        from .ego.shelldbus import GDBusShellProxy

        return GDBusShellProxy().shell_version() or None
    except Exception:  # noqa: BLE001 - any failure means "could not ask"
        return None


@dataclass
class HeadlessPlan:
    """What using a Look would do, ready to print and then to do.

    Attributes:
        title: what the Look calls itself.
        directory: the folder it was read from.
        lines: the change in a first-time reader's words, straight from
            :meth:`Diff.to_novice_lines`.
        notes: things the Look asked for that will not happen.
        refusals: things gtheme will not let any Look do. One of these means
            the Look is not applied at all.
        problems: why the Look could not be read or compiled at all.
        missing_addons: add-ons the Look wants that are not on this computer.
        transaction: what to apply, or None when there is nothing to apply.
    """

    title: str
    directory: Path
    lines: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    missing_addons: list[str] = field(default_factory=list)
    transaction: Transaction | None = None

    @property
    def usable(self) -> bool:
        """Can this Look be applied at all?"""
        return self.transaction is not None and not self.refusals and not self.problems


def make_plan(
    directory: str | Path,
    *,
    installed: set[str] | None = None,
    shell_version: str | None = None,
    dest_root: str | None = None,
) -> HeadlessPlan:
    """Read and compile a Look, and work out what applying it would change.

    Never raises for a bad Look: everything that can go wrong is something the
    person has to be told in a sentence, so it comes back in ``problems``.
    """
    path = Path(directory)
    result = load(path)
    if result.preset is None:
        return HeadlessPlan(title=path.name, directory=path, problems=list(result.errors))

    preset = result.preset
    title = preset.meta.title or preset.meta.name
    present = installed_extension_uuids() if installed is None else installed

    try:
        compiled = compile_preset(
            preset,
            path,
            dest_root=dest_root,
            installed_extensions=present,
            shell_version=shell_version,
        )
    except Exception as exc:  # noqa: BLE001 - a bad Look must not be a traceback
        return HeadlessPlan(
            title=title,
            directory=path,
            problems=[f"this Look could not be prepared: {exc}"],
        )

    refusals = list(compiled.refusals)
    notes = [line for line in compiled.warnings if line not in refusals]
    missing = [op.uuid for op in compiled.transaction.ops if isinstance(op, ExtensionInstall)]

    plan = HeadlessPlan(
        title=title,
        directory=path,
        notes=notes,
        refusals=refusals,
        missing_addons=missing,
        transaction=compiled.transaction,
    )
    try:
        plan.lines = compiled.transaction.plan().to_novice_lines()
    except Exception as exc:  # noqa: BLE001 - same reason
        # A refused Look cannot be previewed either: the engine's own preflight
        # refuses it before the first line of a diff exists, which is the point
        # of the preflight. That is not a second thing to report — the
        # compiler's refusal sentences already say it, in words, so they stay
        # the whole story and this exception is not turned into a second one.
        if not refusals:
            plan.problems.append(f"what this Look would change could not be worked out: {exc}")
        plan.transaction = None
    return plan


def plan_report(plan: HeadlessPlan) -> list[str]:
    """The dry-run text, in reading order.

    Everything the confirmation dialog shows, minus the buttons: what changes,
    what will not happen, and — named, never counted — anything gtheme refuses.
    """
    out: list[str] = []
    if plan.problems:
        out.append(f"{plan.title} cannot be used:")
        out.extend(f"  - {line}" for line in plan.problems)
        return out

    if plan.lines:
        out.append(f"{plan.title} would change:")
        out.extend(f"  - {line}" for line in plan.lines)
    elif not plan.refusals:
        out.append(f"{plan.title}: your desktop already looks like this.")

    if plan.missing_addons:
        count = len(plan.missing_addons)
        out.append(
            "1 add-on this Look wants is not on this computer, so that part will be "
            "left out. Open gtheme to get it:"
            if count == 1
            else f"{count} add-ons this Look wants are not on this computer, so those "
            "parts will be left out. Open gtheme to get them:"
        )
        out.extend(f"  - {uuid}" for uuid in plan.missing_addons)

    if plan.notes:
        out.append("Worth knowing:")
        out.extend(f"  - {line}" for line in plan.notes)

    if plan.refusals:
        out.append("gtheme will not use this Look:")
        out.extend(f"  - {line}" for line in plan.refusals)
    return out


def run_apply(
    target: str,
    *,
    dry_run: bool = False,
    out=None,
    err=None,
    shell_version: str | None = None,
) -> int:
    """``gtheme apply``. Returns the exit code.

    Args:
        target: a Look's name, or the folder one lives in.
        dry_run: print what would change and change nothing.
        out: where the ordinary text goes. Defaults to standard output.
        err: where the reasons a Look was not used go. Defaults to standard
            error, so a script can separate the two.
        shell_version: what this desktop calls itself. Measured when not given.

    Returns:
        0 when the Look was applied, or when a dry run had nothing to object
        to. 1 when the Look was refused, could not be read, or failed to apply
        — with the reason on standard error in plain words.
    """
    import sys

    stdout = sys.stdout if out is None else out
    stderr = sys.stderr if err is None else err

    def say(text: str) -> None:
        print(text, file=stdout)

    def complain(text: str) -> None:
        print(f"gtheme: {text}", file=stderr)

    try:
        directory = resolve_look(target)
    except LookNotFound as exc:
        complain(str(exc))
        return 1

    if shell_version is None:
        shell_version = detect_shell_version()
    plan = make_plan(directory, shell_version=shell_version)

    if dry_run:
        for line in plan_report(plan):
            say(line)
        if plan.problems or plan.refusals:
            complain(f"{plan.title} would not be used. Nothing was changed.")
            return 1
        say("Nothing has been changed. Leave off --dry-run to use this Look.")
        return 0

    # Refusals first. A refused Look also fails to *preview* — the engine's
    # preflight stops it before a diff exists — and "it could not be worked
    # out" is a much worse sentence than the one saying which file it asked for.
    if plan.refusals:
        complain(f"{plan.title} asks for something gtheme will not let a Look do.")
        for line in plan.refusals:
            print(f"  - {line}", file=stderr)
        complain("Nothing was changed.")
        return 1

    if plan.problems:
        complain(f"{plan.title} cannot be used.")
        for line in plan.problems:
            print(f"  - {line}", file=stderr)
        return 1

    if plan.transaction is None:  # pragma: no cover - guarded by the two above
        complain(f"{plan.title} cannot be used.")
        return 1

    if not plan.lines:
        for line in plan.notes:
            say(f"Worth knowing: {line}")
        say(f"{plan.title}: your desktop already looks like this. Nothing was changed.")
        return 0

    say(f"Using {plan.title}:")
    for line in plan.lines:
        say(f"  - {line}")
    if plan.missing_addons:
        for uuid in plan.missing_addons:
            say(f"  - not on this computer, so it is left out: {uuid}")
    for line in plan.notes:
        say(f"Worth knowing: {line}")

    def report(_stage: Progress, text: str) -> None:
        say(text)

    try:
        outcome = plan.transaction.apply(report)
    except TransactionError as exc:
        complain(str(exc))
        if exc.rolled_back:
            complain("Nothing was changed. Your desktop is exactly as it was.")
        else:
            complain(
                "Part of the change stayed. Run 'gtheme rescue' to put your desktop back."
            )
        return 1

    for line in outcome.cleanup_warnings:
        say(f"Worth knowing: {line}")
    if outcome.restore_point:
        say(f"Done. Open gtheme's Undo page to go back to how it was before {plan.title}.")
    else:
        say("Done.")
    return 0
