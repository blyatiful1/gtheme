"""The Looks page — pick a whole desktop, see it first, put it back if you hate it.

This is tier one of the three-tier disclosure (competitor-ux P8): for most
people it is the entire app. Everything on it obeys four rules that come
straight out of the research, and every one of them is visible in the code
below rather than asserted in a comment:

* **Nothing is applied that was not previewed.** A tile opens a dialog that
  lists, in the user's own words, what is about to change —
  :meth:`Diff.to_novice_lines` renders it, and nothing else writes that text.
* **Nothing is applied without a way back.** The transaction takes its own
  restore point before the first byte moves; the toast that follows carries an
  Undo button wired to it.
* **A Look that is broken is listed as broken.** Hiding it would look like
  gtheme lost it, and a Look that vanishes is a scarier bug than a Look that
  says what is wrong with it.
* **Nothing here promises what it cannot do.** A Look that wants add-ons this
  computer does not have says so before it is applied, says what will happen
  anyway, and offers the page that can add them — it does not silently apply
  two thirds of itself and call that success.

The page talks only to services: ``preset.loader`` for what is on disk,
``preset.compile`` for turning a Look into a transaction, ``core.transaction``
for applying it, ``core.restorepoints`` for undoing it, ``preset.registry`` for
the community list, ``preset.capture`` for saving the current desktop. It never
constructs a settings backend and never writes a key itself.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk, Pango  # noqa: E402

from ...core import restorepoints  # noqa: E402
from ...core.backends import get_backend  # noqa: E402
from ...core.gvariant import parse_string_list  # noqa: E402
from ...core.transaction import (  # noqa: E402
    ENABLED_EXTENSIONS_KEY,
    Diff,
    ExtensionEnable,
    ExtensionInstall,
    FileLink,
    FileRemove,
    FileWrite,
    Progress,
    Transaction,
    TransactionError,
    installed_extension_uuids,
)
from ...ego.install import COPY as EGO_COPY  # noqa: E402
from ...ego.install import (  # noqa: E402
    ExtensionInstaller,
    InstallOutcome,
    InstallReport,
)
from ...panels.loader import load_corpus  # noqa: E402
from ...prefs import Prefs  # noqa: E402
from ...preset import registry as look_registry  # noqa: E402
from ...preset.capture import capture_share  # noqa: E402
from ...preset.compile import compile_preset  # noqa: E402
from ...preset.loader import LoadResult, load_all, user_themes_dir  # noqa: E402
from ...preset.model import Component  # noqa: E402
from ..applyrunner import ApplyRunner  # noqa: E402
from ..preview import ASPECT_RATIO, build_preview  # noqa: E402
from ..search import escape_markup  # noqa: E402
from ..widgets.explainer import first_visit_banner  # noqa: E402
from ..widgets.rows import key_for  # noqa: E402

__all__ = [
    "BADGES",
    "COPY",
    "GRID_COLUMN",
    "TILE_WIDTH",
    "AddonBatch",
    "ApplyPlan",
    "LookTile",
    "LooksPage",
    "TileFrame",
    "addon_names",
    "build",
    "capture_keys",
    "component_for_key",
    "detail_lines",
    "plan_apply",
    "slugify",
    "tiles_from_results",
]


#: Every sentence this page says, in one place, so the wording can be reviewed
#: as a whole and linted as a whole. Nothing below builds user-visible text by
#: concatenation except through these.
COPY: dict[str, str] = {
    # -- the page itself
    "first-visit": (
        "A Look changes your background picture, colours, text and add-ons all at once. "
        "Before anything changes, gtheme saves how your desktop looks right now, so one "
        "click puts it back."
    ),
    "installed-title": "Your Looks",
    "browse-title": "Get more",
    "safety": "Looks only change settings. They can't run programs on your computer.",
    "empty-installed": "No Looks yet",
    "empty-installed-body": (
        "Looks change your background picture, colours and icons all at once. "
        "Save how your desktop looks now to make your first one."
    ),
    # -- tiles
    "broken": "This Look has a problem",
    "broken-heading": "This Look can't be used",
    "broken-body": "gtheme could not read this Look, so it cannot be applied:",
    "notes-heading": "Some of this Look won't apply",
    # -- the preview dialog
    "apply-intro": "This will change:",
    "apply-safety": (
        "Before anything changes, gtheme saves how your desktop looks right now. "
        "You can put it back with one click."
    ),
    "apply-button": "Use this look",
    "apply-anyway": "Use it anyway",
    "cancel": "Cancel",
    "nothing-to-do": "Your desktop already looks like this. Nothing would change.",
    "close": "Close",
    "missing-addons-one": "This Look uses 1 add-on you don't have.",
    "missing-addons-many": "This Look uses {count} add-ons you don't have.",
    "missing-addons-note": (
        "Everything else in the Look still applies. You can add the missing ones on "
        "the Add-ons page."
    ),
    "get-addons": "Get the missing ones",
    "open-addons": "Open Add-ons",
    "addons-working": "Getting the add-ons this Look needs…",
    "addons-heading": "Adding what this Look needs",
    "addons-none": "gtheme cannot add add-ons right now. Open the Add-ons page to try there.",
    "addons-done-heading": "What happened",
    "addons-failed": "Those add-ons could not be added.",
    "addons-timeout": (
        "The add-ons this Look needs took too long to arrive, so gtheme stopped "
        "waiting. Nothing was added."
    ),
    # -- somebody else's Look wants a name that is already taken
    "replace-heading": "You already have a Look called {name}",
    "replace-yours": (
        "Getting this one would replace the Look of that name that is already on this "
        "computer, and what is in that one now would be gone."
    ),
    "replace-built-in": (
        "gtheme comes with a Look of that name. Getting this one would take its place in "
        "the list — the built-in one stays on your computer, but you would stop seeing it."
    ),
    "replace-confirm": "Replace it",
    "replace-keep": "Keep what I have",
    "cannot-preview": (
        "gtheme could not work out what this Look would change on this computer."
    ),
    # -- what the change really is, under the everyday summary
    "details-title": "Show exactly what changes",
    "details-note": (
        "The list above is this change in everyday words. This is the same change "
        "written the way your computer stores it."
    ),
    "details-file-add": "added",
    "details-file-replace": "replaces what is there now",
    "details-file-remove": "deleted",
    "details-file-link": "becomes a shortcut to {target}",
    "details-nothing": "nothing yet",
    "details-addon-on": "turned on",
    "details-addon-get": "not on this computer yet",
    # -- applying
    "working": "Getting your desktop ready…",
    "applied": "{title} is on now.",
    "undo": "Undo",
    "undone": "Put back how it was.",
    "undo-failed": "gtheme could not put everything back. Open Undo & Restore Points.",
    "failed-heading": "Nothing was changed",
    "failed-body": "Your desktop is exactly as it was.",
    "half-heading": "Something went wrong part way through",
    "half-body": (
        "gtheme could not put everything back on its own. Go back to the moment "
        "gtheme saved just before this, or open Undo & Restore Points."
    ),
    "failure-undo": "Put my desktop back",
    # -- what gtheme could not do, said after the Look is on
    "after-heading": "What gtheme could not do",
    "snapshot-partial": (
        "gtheme saved how your desktop looked before this, but not all of it. "
        "Undo puts back everything it did save. These were left out:"
    ),
    "cleanup-partial": (
        "Parts of the Look you had on before could not be changed back:"
    ),
    "cleanup-kept": "Those things are still on your desktop. Undo & Restore Points can put them back.",
    "cleanup-dead": (
        "gtheme no longer has a saved copy of those, so it cannot put them back."
    ),
    # -- saving your own
    "save": "Save how my desktop looks now",
    "save-heading": "Save this desktop as a Look",
    "save-body": (
        "gtheme writes down how your desktop looks right now so you can come back to "
        "it, or give it to someone else. Anything that looks private is left out."
    ),
    "save-name": "Name",
    "save-confirm": "Save",
    "save-empty-name": "Give the Look a name first.",
    "save-replace-yours": (
        "Saving under that name would replace the Look of that name that is already on "
        "this computer, and what is in that one now would be gone."
    ),
    "save-replace-built-in": (
        "gtheme comes with a Look of that name. Saving under it would take its place in "
        "the list — the built-in one stays on your computer, but you would stop seeing it."
    ),
    "saved": "Saved as {title}.",
    "save-failed": "gtheme could not save this desktop as a Look.",
    "save-notes-heading": "What gtheme changed before saving",
    # -- the community list
    "browse-loading": "Looking for Looks other people have published…",
    "browse-empty": "Nothing published yet",
    "browse-empty-body": "Nobody has published a Look yet. Yours could be the first.",
    "browse-failed": "That list isn't available right now",
    "browse-retry": "Try again",
    "browse-here": "Already on this computer",
    "browse-open": "Open it",
    "browse-get": "Get this look",
    "browse-getting": "Getting it now…",
    "browse-get-failed": "That look could not be downloaded",
    "browse-got": "{name} is on your computer now. Open it to try it out.",
}

#: Provenance to the badge shown on a tile. The wording is the one from
#: competitor-ux's steal-list item 10, which is the UX KDE said it wished it had.
BADGES: dict[str, str] = {
    "bundled": "Built-in",
    "user": "Yours",
    "community": "From the community",
}

#: The banner state key. Defined in ``prefs.KNOWN_BANNERS``.
BANNER_ID = "first-visit-looks"

#: How wide one tile asks to be, and the reason the grid is a grid.
#:
#: A ``Gtk.FlowBox`` decides how many children fit on a line from what they say
#: they *naturally* want, and a Look's preview is a real screenshot: the
#: ``Gtk.Picture`` inside it reports the picture's own width, 2561px for a 1440p
#: shot, and ``Gtk.AspectFrame`` passes that straight through. So the FlowBox
#: was answering correctly — one child per line — and the wide empty margins
#: either side were the aspect frame centring a 320px preview inside a line it
#: had been told was needed. :class:`TileFrame` is what turns "this tile wants
#: the width of a cinema screen" into "this tile wants a tile".
TILE_WIDTH = 360

#: How wide the column holding a grid is allowed to get.
#:
#: The ``tightening_threshold`` matters as much as the maximum. An
#: ``Adw.Clamp`` left at its default threshold of 400 hands its child *less*
#: than the room available all the way up to the maximum — 754px out of 864 on
#: the window this app opens at — which is exactly the kind of missing hundred
#: pixels that costs a grid its second column. A column of tiles is not a
#: column of prose: it wants the width it is given, up to a limit, so the
#: threshold and the maximum are the same number here.
GRID_COLUMN = 1000


# --------------------------------------------------------------------------
# the parts with no widgets in them
# --------------------------------------------------------------------------


def slugify(text: str) -> str:
    """Turn what a person typed into a name a Look folder can have.

    ``preset.model.Meta`` demands ``^[a-z0-9][a-z0-9._-]*$``. Rather than
    refusing "My Desktop" with a rule nobody should have to read, the name a
    person types becomes the *title* and this becomes the folder name.
    """
    kept: list[str] = []
    for char in text.strip().lower():
        if char.isalnum() and char.isascii():
            kept.append(char)
        elif char in " -_." and kept and kept[-1] != "-":
            kept.append("-")
    slug = "".join(kept).strip("-.")
    return slug or ""


@dataclass(frozen=True)
class LookTile:
    """One Look, as the grid needs it. Broken ones included, deliberately."""

    name: str
    title: str
    description: str
    badge: str
    directory: Path
    palette: Mapping[str, str] = field(default_factory=dict)
    pictures: tuple[Path, ...] = ()
    problems: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    result: LoadResult | None = None

    @property
    def broken(self) -> bool:
        return bool(self.problems) or self.result is None or self.result.preset is None


def tiles_from_results(results: Iterable[LoadResult]) -> list[LookTile]:
    """Describe every loaded Look for the grid, in the order they came in."""
    tiles: list[LookTile] = []
    for result in results:
        preset = result.preset
        badge = BADGES.get(result.provenance, BADGES["user"])
        if preset is None:
            tiles.append(
                LookTile(
                    name=result.path.name,
                    title=result.path.name,
                    description=COPY["broken"],
                    badge=badge,
                    directory=result.path,
                    problems=tuple(result.errors),
                    result=result,
                )
            )
            continue
        tiles.append(
            LookTile(
                name=preset.meta.name,
                title=preset.meta.title or preset.meta.name,
                description=preset.meta.description,
                badge=badge,
                directory=result.path,
                palette=dict(preset.palette),
                pictures=tuple(result.path / shot for shot in preset.meta.screenshots),
                notes=tuple(result.warnings),
                result=result,
            )
        )
    return tiles


@dataclass
class ApplyPlan:
    """What using a Look would do, ready to be shown and then done.

    Attributes:
        title: the Look's name, as the dialog heading uses it.
        lines: the change, in the user's words. Straight from
            :meth:`Diff.to_novice_lines`; this page never rewords it.
        warnings: what the Look asked for that will not happen. Straight from
            the compiler, which already phrases them for a first-time reader.
        missing_addons: how many add-ons the Look wants that are not here.
        missing: those add-ons as ``(uuid, source, alternates)`` — exactly the
            shape ``ego.install.ExtensionInstaller.plan_for_look`` takes, so
            the "get the missing ones" button hands this straight over instead
            of rebuilding it from something that has already been worked out.
        details: the same change, one line per thing that moves, with the real
            destination or the real value on it. The second layer of the
            preview (persona-report §2.4): :attr:`lines` stays the headline in
            everyday words, and this is what the "Show exactly what changes"
            expander holds for anyone who wants to check.
        transaction: what to apply. None when the Look could not be compiled.
        problem: why there is nothing to apply, when there is nothing.
    """

    title: str
    lines: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing_addons: int = 0
    missing: list[tuple[str, str, tuple[str, ...]]] = field(default_factory=list)
    details: list[str] = field(default_factory=list)
    transaction: Transaction | None = None
    problem: str | None = None

    @property
    def nothing_to_do(self) -> bool:
        return self.transaction is not None and not self.lines

    def body(self) -> str:
        """The dialog's whole body text, in reading order."""
        if self.problem:
            return self.problem
        parts: list[str] = []
        if self.lines:
            parts.append(COPY["apply-intro"])
            parts.append("\n".join(f"• {line}" for line in self.lines))
        else:
            parts.append(COPY["nothing-to-do"])
        if self.missing_addons:
            template = (
                COPY["missing-addons-one"]
                if self.missing_addons == 1
                else COPY["missing-addons-many"]
            )
            parts.append(template.format(count=self.missing_addons) + "\n" + COPY["missing-addons-note"])
        if self.warnings:
            parts.append(COPY["notes-heading"] + "\n" + "\n".join(f"• {w}" for w in self.warnings))
        if self.lines:
            parts.append(COPY["apply-safety"])
        parts.append(COPY["safety"])
        return "\n\n".join(parts)


def addon_names(uuids: Iterable[str]) -> dict[str, str]:
    """What each add-on calls itself, read from this computer and nothing else.

    The preview has to name add-ons (persona-report §2.4) and must do it with
    no network: a dialog that cannot be shown offline is a dialog that is not
    shown when somebody's connection is down. Every add-on that is already
    here has its own name on disk, so that is where the name comes from; one
    that is not here yet has only its identifier, and the expander shows that
    rather than inventing a title for it.
    """
    from ...system.extscan import default_extension_roots, scan_extensions

    wanted = set(uuids)
    if not wanted:
        return {}
    try:
        entries = scan_extensions(default_extension_roots())
    except OSError:  # pragma: no cover - a directory that will not be read
        return {}
    return {entry.uuid: entry.name for entry in entries if entry.uuid in wanted}


def detail_lines(diff: Diff, *, names: Mapping[str, str] | None = None) -> list[str]:
    """Every change in the plan, one line each, with the real thing named.

    The honest second layer of the preview. ``Diff.to_novice_lines`` collapses
    twenty files into "20 files" on purpose — that is the right headline for
    somebody who has never heard of a config file — but it was also the *only*
    thing the app ever showed, so "Terminal" could stand for rewriting five
    files under the user's own home and nothing said which (persona-report
    §2.4). ``DiffEntry`` has carried ``before`` and ``after`` since the first
    contract; this renders them.

    Args:
        diff: what the transaction plans to do.
        names: add-on identifier to the name it calls itself, from
            :func:`addon_names`. Missing ones are shown by identifier.

    Returns:
        One line per real change, in the order the engine will carry them out.
    """
    known = dict(names or {})
    lines: list[str] = []
    for entry in diff.changes:
        op = entry.op
        if isinstance(op, FileWrite):
            state = COPY["details-file-replace"] if entry.before else COPY["details-file-add"]
            lines.append(f"{op.dest} — {state}")
        elif isinstance(op, FileRemove):
            lines.append(f"{op.dest} — {COPY['details-file-remove']}")
        elif isinstance(op, FileLink):
            lines.append(f"{op.dest} — {COPY['details-file-link'].format(target=op.target)}")
        elif isinstance(op, ExtensionEnable | ExtensionInstall):
            state = (
                COPY["details-addon-get"]
                if isinstance(op, ExtensionInstall)
                else COPY["details-addon-on"]
            )
            name = known.get(op.uuid)
            lines.append(f"{name} ({op.uuid}) — {state}" if name else f"{op.uuid} — {state}")
        else:
            before = entry.before if entry.before is not None else COPY["details-nothing"]
            after = entry.after if entry.after is not None else COPY["details-nothing"]
            lines.append(f"{_plain_key(op.key)}: {before} → {after}")
    return lines


def _plain_key(key: str) -> str:
    """A setting's name without the part that says how it is stored.

    ``gsettings:org.gnome.desktop.interface icon-theme`` is two facts, and only
    the second one is about the user's desktop. The first names the machinery,
    which is a word this app does not say (``ui.jargon``), so it is dropped
    here rather than shown and then explained.
    """
    scheme, sep, rest = key.partition(":")
    return rest if sep and not scheme.startswith("/") else key


def plan_apply(
    tile: LookTile,
    *,
    installed: Sequence[str] | None = None,
    dest_root: str | None = None,
    shell_version: str | None = None,
) -> ApplyPlan:
    """Compile a Look and work out what applying it would change.

    Never raises. Everything that can go wrong here — a Look that does not
    validate, a settings store that cannot be read — is something the dialog has
    to be able to say out loud, so it comes back as ``problem`` rather than as
    an exception thrown at a click handler.

    Args:
        tile: the Look, as the grid holds it.
        installed: the add-ons on this machine. None reads them.
        dest_root: passed to the compiler; the tests' seam.
        shell_version: what this desktop calls itself. The compiler's
            ``min_shell`` warning is computed from it, and a caller that does
            not pass it gets no warning — which is why the page reads it from
            the window instead of leaving it out (review-report L8: the engine
            half landed in Wave A and nothing ever handed it a version, so a
            Look made for a newer GNOME still applied in silence).
    """
    result = tile.result
    if result is None or result.preset is None:
        return ApplyPlan(title=tile.title, problem=COPY["broken-body"])

    present = set(installed) if installed is not None else installed_extension_uuids()
    try:
        compiled = compile_preset(
            result.preset,
            tile.directory,
            dest_root=dest_root,
            installed_extensions=present,
            shell_version=shell_version,
        )
    except Exception as exc:  # noqa: BLE001 - a bad Look must not kill the page
        return ApplyPlan(title=tile.title, problem=f"{COPY['cannot-preview']}\n\n{exc}")

    missing = [
        (op.uuid, op.source, ())
        for op in compiled.transaction.ops
        if isinstance(op, ExtensionInstall)
    ]
    try:
        diff = compiled.transaction.plan()
    except Exception as exc:  # noqa: BLE001 - same reason
        return ApplyPlan(
            title=tile.title,
            warnings=list(compiled.warnings),
            missing_addons=len(missing),
            missing=missing,
            problem=f"{COPY['cannot-preview']}\n\n{exc}",
        )

    uuids = [
        op.uuid
        for op in compiled.transaction.ops
        if isinstance(op, ExtensionEnable | ExtensionInstall)
    ]
    return ApplyPlan(
        title=tile.title,
        lines=diff.to_novice_lines(),
        warnings=list(compiled.warnings),
        missing_addons=len(missing),
        missing=missing,
        details=detail_lines(diff, names=addon_names(uuids)),
        transaction=compiled.transaction,
    )


class AddonBatch:
    """Add every add-on a Look wants, as ONE change to the desktop.

    A Look that adds three add-ons must not be three separate changes. Three
    changes means three restore points, three chances to end up half applied,
    and — on the live install path — three confirmation boxes, which the
    installer's own docstring calls an interrogation. So the download path is
    used for all of them, each one's enable step comes back as a planned
    transaction, and this puts those together with the enable steps for the
    add-ons that were already here into one transaction the caller applies.

    Nothing here is a widget and nothing here applies anything: the caller
    applies, because the caller is the one that can put a restore point and a
    progress dialog around it. That is also what makes this testable with a
    fake installer and a fake library and no desktop at all.

    Args:
        installer: ``ego.install.ExtensionInstaller``.
        client: the add-on library, for looking up which exact build to fetch.
        shell_version: what this desktop calls itself, for the compatibility
            check. The library's own answer never reports incompatibility.
        label: what to call the resulting change.
    """

    #: How long :meth:`run_and_wait` will wait for the whole batch. Three
    #: minutes covers a slow connection fetching several add-ons; past that,
    #: saying so beats a progress dialog that never closes.
    TIMEOUT_SECONDS = 180.0

    def __init__(
        self,
        installer: Any,
        client: Any = None,
        *,
        shell_version: str = "",
        label: str | None = None,
    ) -> None:
        self.installer = installer
        self.client = client
        self.shell_version = shell_version
        self.label = label

    def run(
        self,
        wanted: Sequence[tuple[str, str, tuple[str, ...]]],
        on_done: Callable[[Transaction | None, list[Any]], None],
        *,
        on_progress: Callable[[str], None] | None = None,
    ) -> None:
        """Work through the list, then call ``on_done(transaction, reports)``.

        ``transaction`` is None only when there is genuinely nothing to do.
        ``reports`` is one per add-on that could not be added, carrying the
        installer's own sentence for why — never a reworded one.
        """
        enable, missing = self.installer.plan_for_look(list(wanted), label=self.label)
        ops: list[Any] = list(enable.ops)
        problems: list[Any] = []
        queue = [report for report in missing if report.outcome is InstallOutcome.NEEDS_RELOGIN]
        problems.extend(
            report for report in missing if report.outcome is not InstallOutcome.NEEDS_RELOGIN
        )

        def finish() -> None:
            on_done(Transaction(ops, label=self.label) if ops else None, problems)

        def landed(report: Any) -> None:
            if report.transaction is not None:
                ops.extend(report.transaction.ops)
            if not report.ok:
                problems.append(report)
            step()

        def step() -> None:
            if not queue:
                finish()
                return
            report = queue.pop(0)
            uuid = report.uuid
            if on_progress is not None:
                on_progress(COPY["addons-working"])
            if self.client is None:
                problems.append(_not_added(uuid))
                step()
                return

            def described(record: Any, error: Any) -> None:
                if record is None or error is not None:
                    # The library could not be asked. Nothing was downloaded,
                    # so the queued "Added." report must not be what is shown.
                    problems.append(_not_added(uuid, error))
                    step()
                    return
                if not record.supports(self.shell_version):
                    problems.append(
                        InstallReport(
                            uuid,
                            InstallOutcome.NOT_COMPATIBLE,
                            EGO_COPY[InstallOutcome.NOT_COMPATIBLE],
                        )
                    )
                    step()
                    return
                tag = record.version_tag_for(self.shell_version)
                if tag is None:
                    problems.append(
                        InstallReport(
                            uuid,
                            InstallOutcome.NOT_COMPATIBLE,
                            EGO_COPY[InstallOutcome.NOT_COMPATIBLE],
                        )
                    )
                    step()
                    return
                self.installer.install_package(uuid, tag, landed, label=self.label)

            self.client.info(uuid, described)

        step()

    def run_and_wait(
        self,
        wanted: Sequence[tuple[str, str, tuple[str, ...]]],
        *,
        on_progress: Callable[[str], None] | None = None,
        timeout: float | None = None,
    ) -> tuple[Transaction | None, list[Any]]:
        """:meth:`run`, but it does not return until the answer is really in.

        :meth:`run` is asynchronous end to end: looking an add-on up and
        downloading it both go through the library's ``send_and_read_async``,
        whose callbacks land on the main loop some time later. A caller that
        calls :meth:`run` and reads the result on the next line gets ``(None,
        [])`` every time there is anything to download — no add-ons added, no
        failure reported, and the download finishing into a dictionary nobody
        is looking at any more. That was the bug; this is the fix.

        The batch is *started* on the main loop, because the library's session
        may only be used from there, and this waits on a plain event for the
        callbacks to come back. Called from the main thread itself — which a
        test does — the main context is pumped instead of waited on, so a fake
        that answers straight away still returns immediately.

        Raises:
            TimeoutError: nothing came back within ``timeout`` seconds. Better
                than a worker thread parked forever behind a dialog that never
                closes.
        """
        deadline = time.monotonic() + (self.TIMEOUT_SECONDS if timeout is None else timeout)
        landed: dict[str, Any] = {}
        finished = threading.Event()

        def collected(transaction: Transaction | None, problems: list[Any]) -> None:
            landed["transaction"] = transaction
            landed["problems"] = list(problems)
            finished.set()

        def start() -> bool:
            try:
                self.run(wanted, collected, on_progress=on_progress)
            except Exception as error:  # noqa: BLE001 - reported to the caller
                landed["error"] = error
                finished.set()
            return GLib.SOURCE_REMOVE

        if threading.current_thread() is threading.main_thread():
            start()
            context = GLib.MainContext.default()
            while not finished.is_set() and time.monotonic() < deadline:
                if not context.iteration(False):
                    time.sleep(_PUMP_SECONDS)
        else:
            GLib.idle_add(start)
            finished.wait(max(0.0, deadline - time.monotonic()))

        error = landed.get("error")
        if error is not None:
            raise error
        if not finished.is_set():
            raise TimeoutError(COPY["addons-timeout"])
        return landed.get("transaction"), landed.get("problems", [])


#: How long :meth:`AddonBatch.run_and_wait` sleeps between pumps of the main
#: context when it is doing the pumping itself. Long enough not to spin a core,
#: short enough that a fake answering on the next iteration is not felt.
_PUMP_SECONDS = 0.01


def _not_added(uuid: str, error: Any = None) -> InstallReport:
    """"It was not added", for an add-on whose download never started.

    ``plan_for_look`` marks an add-on that is missing *but downloadable* as
    :attr:`~gtheme.ego.install.InstallOutcome.NEEDS_RELOGIN`, whose sentence is
    "Added. It starts working after you log out and back in." That sentence is
    true only once the download has happened. Showing the queued report on a
    path where nothing was fetched tells the person an add-on was added that
    never was — the exact honesty failure that wording exists to prevent.
    """
    return InstallReport(
        uuid,
        InstallOutcome.FAILED,
        EGO_COPY["download-failed"],
        error=error if isinstance(error, Exception) else None,
    )


def failure_text(error: TransactionError) -> tuple[str, str]:
    """``(heading, body)`` for a transaction that did not finish.

    Two outcomes, two different things to say. Rolled back is the ordinary
    case and the reassuring one. Not rolled back is the serious one and must
    never be dressed up as the other.
    """
    if error.rolled_back:
        return COPY["failed-heading"], f"{COPY['failed-body']}\n\n{error}"
    return COPY["half-heading"], f"{COPY['half-body']}\n\n{error}"


#: Which part of the desktop a setting belongs to, by the group it lives in.
#: Used only when saving a desktop as a Look: the component decides how the
#: Look later *describes* itself in a preview, never what it writes. Longest
#: prefix wins.
_COMPONENT_BY_SCHEMA: tuple[tuple[str, Component], ...] = (
    ("org.gnome.desktop.background", Component.WALLPAPER),
    ("org.gnome.desktop.screensaver", Component.WALLPAPER),
    ("org.gnome.desktop.interface.icon-theme", Component.ICONS),
    ("org.gnome.desktop.interface.cursor", Component.CURSOR),
    ("org.gnome.desktop.wm.preferences", Component.WINDOWS),
    ("org.gnome.desktop.a11y", Component.ACCESSIBILITY),
    ("org.gnome.desktop.privacy", Component.PRIVACY),
    ("org.gnome.desktop.sound", Component.SOUND),
    ("org.gnome.settings-daemon.plugins.color", Component.NIGHT_LIGHT),
    ("org.gnome.settings-daemon.plugins.power", Component.POWER),
    ("org.gnome.shell.extensions.user-theme", Component.SHELL_THEME),
    ("org.gnome.shell.extensions", Component.ADDONS),
    ("org.gnome.shell", Component.TOPBAR),
    ("org.gnome.mutter", Component.WORKSPACES),
    ("org.gnome.Ptyxis", Component.TERMINAL),
)

#: Keys inside ``org.gnome.desktop.interface``, which is one group holding four
#: different parts of the desktop.
_INTERFACE_KEYS: dict[str, Component] = {
    "color-scheme": Component.COLORS,
    "accent-color": Component.COLORS,
    "gtk-theme": Component.COLORS,
    "icon-theme": Component.ICONS,
    "cursor-theme": Component.CURSOR,
    "cursor-size": Component.CURSOR,
    "font-name": Component.FONTS,
    "document-font-name": Component.FONTS,
    "monospace-font-name": Component.FONTS,
    "font-antialiasing": Component.FONTS,
    "font-hinting": Component.FONTS,
    "font-rendering": Component.FONTS,
    "text-scaling-factor": Component.FONTS,
    "enable-animations": Component.ANIMATIONS,
}


def component_for_key(key: str) -> Component:
    """Which part of the desktop one setting belongs to.

    A saved Look with everything filed under "Other settings" previews as
    "Other settings" and tells the next person nothing, which is why this table
    exists at all.
    """
    body = key.split(":", 1)[-1]
    group, _, name = body.partition(" ")
    group = group.split(":", 1)[0]
    if group == "org.gnome.desktop.interface":
        return _INTERFACE_KEYS.get(name, Component.COLORS)
    for prefix, component in _COMPONENT_BY_SCHEMA:
        if group == prefix or group.startswith(prefix + "."):
            return component
    return Component.OTHER


def capture_keys(corpus: Any | None = None) -> list[str]:
    """Every setting gtheme knows how to describe, as backend keys.

    "Save my desktop as a Look" saves what this app understands — which is
    exactly the descriptor corpus, and nothing beyond it. Saving keys the app
    cannot show would produce a Look nobody could inspect before applying.
    """
    loaded = corpus if corpus is not None else load_corpus()
    keys: list[str] = []
    for row in loaded.rows:
        if row.schema_id is None or row.key is None:
            continue  # a link row goes somewhere; it holds no value
        key = key_for(row)
        if key not in keys:
            keys.append(key)
    return keys


def enabled_extension_uuids(backend: Any | None = None) -> list[str]:
    """The add-ons switched on right now, for a captured Look to name."""
    reader = backend if backend is not None else get_backend()
    try:
        current = reader.get(ENABLED_EXTENSIONS_KEY)
    except Exception:  # noqa: BLE001 - no session, no add-ons to name
        return []
    return list(parse_string_list(current) or [])


# --------------------------------------------------------------------------
# the grid's two shared pieces
# --------------------------------------------------------------------------


class TileFrame(Gtk.Widget):
    """One tile: asks for a tile's worth of width, then fills what it is given.

    ``Adw.Clamp`` is the obvious tool for this and the wrong one, because it
    caps the *allocation* as well as the request: a FlowBox stretches the
    columns of a line to fill it, and a clamped tile inside a stretched column
    is a picture floating in the middle of empty space — which is the defect
    this whole exercise is about, moved rather than fixed. Capping only what
    the tile asks for is what a grid needs: it decides the number of columns,
    and then every tile takes its column whole.

    See :data:`TILE_WIDTH` for why the request has to be capped at all.
    """

    __gtype_name__ = "GthemeLookTileFrame"

    def __init__(self, child: Gtk.Widget) -> None:
        super().__init__()
        self._child: Gtk.Widget | None = child
        child.set_parent(self)

    def do_measure(  # noqa: D102 - GTK vfunc
        self, orientation: Gtk.Orientation, for_size: int
    ) -> tuple[int, int, int, int]:
        if self._child is None:
            return 0, 0, -1, -1
        minimum, natural, min_baseline, nat_baseline = self._child.measure(
            orientation, for_size
        )
        if orientation == Gtk.Orientation.HORIZONTAL:
            natural = max(minimum, min(natural, TILE_WIDTH))
        return minimum, natural, min_baseline, nat_baseline

    def do_size_allocate(self, width: int, height: int, baseline: int) -> None:  # noqa: D102
        if self._child is not None:
            self._child.allocate(width, height, baseline, None)

    def do_dispose(self) -> None:  # noqa: D102 - GTK vfunc
        if self._child is not None:
            self._child.unparent()
            self._child = None
        Gtk.Widget.do_dispose(self)


def _tile_preview(preview: Gtk.Widget) -> Gtk.Widget:
    """Let a tile's picture be as tall as a tile is wide, in 16:9.

    ``ui.preview.build_preview`` asks for 320x180 and nothing taller, because it
    does not know how wide the thing showing it will be. Its aspect frame then
    keeps the ratio by *narrowing* the picture back to 320 inside whatever width
    it was given — which is where the empty margins either side of a tile's
    picture came from, and why they did not go away when the tiles themselves
    stopped being a page wide. Asking for the height a :data:`TILE_WIDTH` tile
    needs is what lets the picture fill one. The existing width request is read
    back rather than restated, so this stays true if that default moves.
    """
    width, _height = preview.get_size_request()
    preview.set_size_request(width, round(TILE_WIDTH / ASPECT_RATIO))
    return preview


def _tile_description(text: str) -> Gtk.Widget:
    """A Look's own sentence about itself, cut with an ellipsis and not a knife.

    ``Gtk.Inscription`` clips by default, and clipping happens wherever the
    pixels run out — which is how "a brass hairline" became "a brass hai" at
    the edge of a tile. Ellipsizing ends the line at a word boundary instead,
    with the one mark that says there is more of it; the whole sentence is on
    the tile's tooltip either way.
    """
    description = Gtk.Inscription(
        text=text,
        nat_lines=2,
        xalign=0,
        hexpand=True,
        text_overflow=Gtk.InscriptionOverflow.ELLIPSIZE_END,
    )
    description.add_css_class("dimmed")
    description.add_css_class("caption")
    return description


def _details_widget(lines: Sequence[str]) -> Gtk.Widget:
    """The "Show exactly what changes" expander, closed until it is asked for.

    Closed, because the headline is what a first-time user needs and a wall of
    destinations under it would bury the one sentence that matters. Present,
    because "nothing is applied that you have not seen" is the page's first
    rule and a count is not a sight of it.

    A plain ``Gtk.Label`` rather than a row list: this is a body of text a
    person may want to read, select and paste into a question, and it must not
    render markup — a Look's own file names are not this app's words.
    """
    body = Gtk.Label(
        label="\n".join(lines),
        xalign=0,
        wrap=True,
        wrap_mode=Pango.WrapMode.WORD_CHAR,
        selectable=True,
        margin_top=6,
        margin_start=6,
        margin_end=6,
    )
    body.add_css_class("caption")
    body.add_css_class("monospace")

    note = Gtk.Label(label=COPY["details-note"], xalign=0, wrap=True, margin_top=6)
    note.add_css_class("dimmed")
    note.add_css_class("caption")

    inside = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    inside.append(note)
    inside.append(
        Gtk.ScrolledWindow(
            child=body,
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            max_content_height=260,
            propagate_natural_height=True,
        )
    )

    expander = Gtk.Expander(label=COPY["details-title"], expanded=False, margin_top=6)
    expander.set_child(inside)
    return expander


# --------------------------------------------------------------------------
# the page
# --------------------------------------------------------------------------


class LooksPage(Gtk.Box):
    """Installed Looks, the community list, and the apply flow."""

    __gtype_name__ = "GthemeLooksPage"

    def __init__(self, window: Any) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._window = window
        self._prefs: Prefs = getattr(window, "prefs", None) or Prefs()
        self._alive = True
        self._browse_started = False
        self._tiles: list[LookTile] = []
        self._own_runner: ApplyRunner | None = None
        self.connect("destroy", self._on_destroy)

        # ``keep_hidden`` because this page keeps the banner as a member and
        # this class is built once per window: the widget exists whether or not
        # it is revealed. Everywhere else a dismissed explainer is not built at
        # all (review-report M28).
        self._banner = first_visit_banner(
            self._prefs, BANNER_ID, COPY["first-visit"], keep_hidden=True
        )
        self.append(self._banner)

        self._stack = Adw.ViewStack(vexpand=True)
        self._installed_box = self._build_installed()
        self._stack.add_titled(self._installed_box, "installed", COPY["installed-title"])
        self._browse_box = self._build_browse()
        self._stack.add_titled(self._browse_box, "browse", COPY["browse-title"])
        self._stack.connect("notify::visible-child-name", self._on_view_changed)

        switcher_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            halign=Gtk.Align.CENTER,
            margin_top=12,
            margin_bottom=6,
        )
        switcher_box.append(Adw.InlineViewSwitcher(stack=self._stack))
        self.append(switcher_box)
        self.append(self._stack)

        self.reload()

    # -- teardown ----------------------------------------------------------

    def _on_destroy(self, _widget: Gtk.Widget) -> None:
        """Stop every callback that could still be in flight.

        The community list is fetched asynchronously and a Look is applied on a
        worker thread; both come back through ``GLib.idle_add``. A callback that
        lands after the page is gone would touch a destroyed widget, so every
        one of them checks this flag first.
        """
        self._alive = False

    # -- construction ------------------------------------------------------

    def _build_installed(self) -> Gtk.Widget:
        # ``max_children_per_line`` is a ceiling, not a target: what actually
        # decides how many tiles share a line is how wide a tile says it is,
        # which is :data:`TILE_WIDTH`. ``min_children_per_line`` stays at one
        # because this grid lives in a scroller with no horizontal bar, so a
        # floor of two would make the whole page refuse to be narrower than two
        # tiles — and the window is allowed down to 360px.
        self._grid = Gtk.FlowBox(
            valign=Gtk.Align.START,
            homogeneous=True,
            max_children_per_line=3,
            min_children_per_line=1,
            column_spacing=18,
            row_spacing=18,
            selection_mode=Gtk.SelectionMode.NONE,
        )

        self._empty = Adw.StatusPage(
            icon_name="starred-symbolic",
            title=COPY["empty-installed"],
            description=COPY["empty-installed-body"],
        )
        self._empty.set_visible(False)

        save = Adw.PreferencesGroup(margin_top=24)
        save_row = Adw.ButtonRow(title=COPY["save"], start_icon_name="document-save-symbolic")
        save_row.add_css_class("suggested-action")
        save_row.connect("activated", lambda _row: self._open_save_dialog())
        save.add(save_row)

        safety = Gtk.Label(
            label=COPY["safety"],
            wrap=True,
            justify=Gtk.Justification.CENTER,
            margin_top=12,
        )
        safety.add_css_class("dimmed")
        safety.add_css_class("caption")

        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        column.append(self._grid)
        column.append(self._empty)
        column.append(save)
        column.append(safety)

        clamp = Adw.Clamp(
            maximum_size=GRID_COLUMN,
            tightening_threshold=GRID_COLUMN,
            margin_start=18,
            margin_end=18,
            margin_bottom=24,
        )
        clamp.set_child(column)
        return Gtk.ScrolledWindow(
            child=clamp, hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True
        )

    def _build_browse(self) -> Gtk.Widget:
        self._browse_stack = Gtk.Stack()

        loading = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            valign=Gtk.Align.CENTER,
            halign=Gtk.Align.CENTER,
        )
        loading.append(Adw.Spinner(width_request=32, height_request=32))
        loading.append(Gtk.Label(label=COPY["browse-loading"], wrap=True))
        self._browse_stack.add_named(loading, "loading")

        self._browse_grid = Gtk.FlowBox(
            valign=Gtk.Align.START,
            homogeneous=True,
            max_children_per_line=3,
            min_children_per_line=1,
            column_spacing=18,
            row_spacing=18,
            selection_mode=Gtk.SelectionMode.NONE,
        )
        clamp = Adw.Clamp(
            maximum_size=GRID_COLUMN,
            tightening_threshold=GRID_COLUMN,
            margin_start=18,
            margin_end=18,
            margin_bottom=24,
        )
        clamp.set_child(self._browse_grid)
        self._browse_stack.add_named(
            Gtk.ScrolledWindow(
                child=clamp, hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True
            ),
            "results",
        )

        self._browse_stack.add_named(
            Adw.StatusPage(
                icon_name="starred-symbolic",
                title=COPY["browse-empty"],
                description=COPY["browse-empty-body"],
            ),
            "empty",
        )

        self._browse_error = Adw.StatusPage(
            icon_name="network-offline-symbolic", title=COPY["browse-failed"]
        )
        retry = Gtk.Button(label=COPY["browse-retry"], halign=Gtk.Align.CENTER)
        retry.add_css_class("pill")
        retry.connect("clicked", lambda _button: self._start_browse(force=True))
        self._browse_error.set_child(retry)
        self._browse_stack.add_named(self._browse_error, "error")

        self._browse_stack.set_visible_child_name("loading")
        return self._browse_stack

    # -- the installed grid ------------------------------------------------

    def reload(self) -> None:
        """Read the Looks on disk again and rebuild the grid."""
        self._tiles = tiles_from_results(load_all())
        child = self._grid.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            self._grid.remove(child)
            child = following
        for tile in self._tiles:
            self._grid.append(self._tile_button(tile))
        self._grid.set_visible(bool(self._tiles))
        self._empty.set_visible(not self._tiles)

    def _tile_button(self, tile: LookTile) -> Gtk.Widget:
        button = Gtk.Button(has_frame=False)
        button.add_css_class("flat")
        button.set_child(TileFrame(self._tile_content(tile)))
        # The card is a card, not a column: on a wide window the FlowBox
        # stretches its columns, and a stretched card is empty space with a
        # picture in the middle of it. Centring puts that space between the
        # cards, where a grid wants it.
        button.set_halign(Gtk.Align.CENTER)
        button.set_tooltip_text(tile.description or tile.title)
        button.connect("clicked", lambda _button, t=tile: self._on_tile_activated(t))
        return button

    def _tile_content(self, tile: LookTile) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.append(
            _tile_preview(build_preview(palette=tile.palette, pictures=list(tile.pictures)))
        )

        title = Gtk.Label(label=tile.title, xalign=0, wrap=True)
        title.add_css_class("heading")
        box.append(title)

        badges = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        badge = Gtk.Label(label=tile.badge, xalign=0)
        badge.add_css_class("caption")
        badge.add_css_class("dimmed")
        badges.append(badge)
        if tile.broken:
            problem = Gtk.Label(label=COPY["broken"], xalign=0)
            problem.add_css_class("caption")
            problem.add_css_class("warning")
            badges.append(problem)
        box.append(badges)

        if tile.description and not tile.broken:
            box.append(_tile_description(tile.description))
        return box

    # -- the apply flow ----------------------------------------------------

    def _on_tile_activated(self, tile: LookTile) -> None:
        if tile.broken:
            self._show_problem(tile)
            return
        plan = plan_apply(tile, shell_version=self._shell_version())
        self._show_preview(tile, plan)

    def _show_problem(self, tile: LookTile) -> None:
        body = COPY["broken-body"] + "\n\n" + "\n".join(f"• {line}" for line in tile.problems)
        dialog = Adw.AlertDialog(heading=COPY["broken-heading"], body=body)
        dialog.add_response("close", COPY["close"])
        dialog.present(self)

    def _show_preview(self, tile: LookTile, plan: ApplyPlan) -> None:
        dialog = Adw.AlertDialog(heading=tile.title, body=plan.body(), prefer_wide_layout=True)
        if plan.details:
            dialog.set_extra_child(_details_widget(plan.details))
        dialog.add_response("cancel", COPY["cancel"])
        if plan.missing_addons:
            dialog.add_response("addons", COPY["get-addons"])
            dialog.add_response("open-addons", COPY["open-addons"])
        if plan.transaction is not None and plan.lines:
            label = COPY["apply-anyway"] if plan.missing_addons else COPY["apply-button"]
            dialog.add_response("apply", label)
            dialog.set_response_appearance("apply", Adw.ResponseAppearance.SUGGESTED)
            dialog.set_default_response("apply")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_preview_response, tile, plan)
        dialog.present(self)

    def _on_preview_response(
        self, _dialog: Adw.AlertDialog, response: str, tile: LookTile, plan: ApplyPlan
    ) -> None:
        if response == "apply" and plan.transaction is not None:
            self._apply(tile, plan.transaction)
        elif response == "addons":
            self._get_missing_addons(tile, plan)
        elif response == "open-addons":
            self._go_to_page("addons")

    def _apply(self, tile: LookTile, transaction: Transaction) -> None:
        """Apply a Look on the shared runner, narrating while it happens."""
        # Which saved moment was the newest before any of this started. The
        # engine reports the moment it took only on the success path, and the
        # failure dialog is exactly where a way back is worth offering — so
        # "did a new moment appear" is what tells them apart, and it is read
        # here rather than after the failure alone, when an older moment would
        # look like this apply's own.
        before = _newest_point_id()

        def work(narrate: Any) -> Any:
            def report(_stage: Progress, text: str) -> None:
                narrate(text)

            return transaction.apply(report)

        def done(outcome: Any) -> None:
            if not self._alive:
                return
            point = getattr(outcome, "restore_point", None)
            self._toast(COPY["applied"].format(title=tile.title), undo_point=point)
            self._changed()
            self._report_leftovers(outcome)

        def failed(error: Exception) -> None:
            if not self._alive:
                return
            if not isinstance(error, TransactionError):
                # An unknown failure is an unknown desktop state. This wrapper
                # used to claim ``rolled_back=True``, and the only failures
                # that reach it as something other than a TransactionError are
                # the ones that did *not* unwind — so the app said "Nothing was
                # changed. Your desktop is exactly as it was." about precisely
                # the half-applied case, and the honest wording written for it
                # could never be reached (review-report H2).
                error = TransactionError(str(error), rolled_back=False)
            heading, body = failure_text(error)
            dialog = Adw.AlertDialog(heading=heading, body=body)
            dialog.add_response("close", COPY["close"])
            # The moment before this apply is the thing that answers "what do I
            # do now", so it is offered here instead of being described as a
            # page the frightened person has to go and find.
            point = _newest_point_id()
            if point is not None and point != before:
                dialog.add_response("undo", COPY["failure-undo"])
                dialog.set_response_appearance("undo", Adw.ResponseAppearance.SUGGESTED)
                dialog.set_default_response("undo")
                dialog.connect(
                    "response",
                    lambda _d, answer, p=point: self._undo(p) if answer == "undo" else None,
                )
            dialog.set_close_response("close")
            dialog.present(self)

        self._runner().run(
            work, heading=tile.title, starting=COPY["working"], on_done=done, on_failed=failed
        )

    def _report_leftovers(self, outcome: Any) -> None:
        """Say what an otherwise successful apply could not do.

        Two things the engine now reports and nothing showed. A restore point
        that could only be taken in part means Undo will put back less than the
        person was promised, and the tidy-up after the Look that was on before
        can leave parts of it behind (review-report M1, persona-report §2.5).
        Both are quiet by nature — the Look went on, the toast says so — which
        is exactly why they are said out loud here.
        """
        sections: list[str] = []
        snapshot = [str(text) for text in getattr(outcome, "restore_warnings", []) or []]
        if snapshot:
            sections.append(
                COPY["snapshot-partial"] + "\n" + "\n".join(f"• {text}" for text in snapshot)
            )
        leftovers = [str(text) for text in getattr(outcome, "cleanup_warnings", []) or []]
        if leftovers:
            part = COPY["cleanup-partial"] + "\n" + "\n".join(f"• {text}" for text in leftovers)
            if getattr(outcome, "cleanup_kept", 0):
                part = f"{part}\n\n{COPY['cleanup-kept']}"
            if getattr(outcome, "cleanup_dead", 0):
                part = f"{part}\n\n{COPY['cleanup-dead']}"
            sections.append(part)
        if not sections:
            return
        dialog = Adw.AlertDialog(heading=COPY["after-heading"], body="\n\n".join(sections))
        dialog.add_response("close", COPY["close"])
        dialog.present(self)

    # -- the add-ons a Look wants and this computer does not have ----------

    def _get_missing_addons(self, tile: LookTile, plan: ApplyPlan) -> None:
        """Add every add-on this Look needs, as one change, then ask again.

        Not a redirect to another page: the person said "use this look", and
        "go and find three add-ons yourself" is not an answer to that. What
        they get instead is one change, one restore point, and then the same
        preview again — now with nothing missing from it.
        """
        batch = self._addon_batch(tile.title)
        if batch is None:
            self._toast(COPY["addons-none"])
            self._go_to_page("addons")
            return

        def work(narrate: Any) -> tuple[Any, list[Any]]:
            # run_and_wait, not run: the batch is asynchronous, and reading its
            # answer on the line after starting it is how "Get the missing
            # ones" became a button that quietly did nothing.
            transaction, problems = batch.run_and_wait(plan.missing, on_progress=narrate)
            outcome = transaction.apply(lambda _stage, text: narrate(text)) if transaction else None
            return outcome, problems

        def done(result: tuple[Any, list[Any]]) -> None:
            if not self._alive:
                return
            _outcome, problems = result
            self._changed()
            self._report_addons(problems)
            # Ask again, with the same Look. Whatever arrived is now present,
            # so the preview it opens is the truthful one.
            fresh = next((t for t in self._tiles if t.name == tile.name), None)
            if fresh is not None:
                self._show_preview(fresh, plan_apply(fresh))

        def failed(error: Exception) -> None:
            if not self._alive:
                return
            timed_out = isinstance(error, TimeoutError)
            self._toast(COPY["addons-timeout"] if timed_out else COPY["addons-failed"])

        self._runner().run(
            work,
            heading=COPY["addons-heading"],
            starting=COPY["addons-working"],
            on_done=done,
            on_failed=failed,
        )

    def _shell_version(self) -> str | None:
        """What this desktop calls itself, or None when it will not say.

        One reader, because two of them drift: the add-on batch needs it to
        pick a build, and the preview needs it for the ``min_shell`` warning
        (review-report L8). None means "not measured", and every caller treats
        that as a reason to claim nothing rather than to guess.
        """
        shell = getattr(self._window, "shell", None)
        if shell is None:
            return None
        try:
            return shell.proxy.shell_version() or None
        except Exception:  # noqa: BLE001 - the desktop answered nothing useful
            return None

    def _addon_batch(self, label: str) -> AddonBatch | None:
        """The batch installer, or None when there is no desktop to add to."""
        shell = getattr(self._window, "shell", None)
        if shell is None:
            return None
        version = self._shell_version() or ""
        installer = ExtensionInstaller(shell, self._addon_client(version))
        return AddonBatch(installer, installer.client, shell_version=version, label=label)

    def _addon_client(self, version: str) -> Any:
        from ...ego.client import DiskCache, EgoClient, SoupTransport

        try:
            return EgoClient(SoupTransport("gtheme"), version or "50", DiskCache())
        except Exception:  # noqa: BLE001 - no internet client, no download path
            return None

    def _report_addons(self, problems: Sequence[Any]) -> None:
        """Say what did not happen, in the installer's own words.

        The sentences come from ``ego.install.COPY`` verbatim. Re-wording them
        here is how "it starts working after you log out and back in" quietly
        becomes "added", which is the one thing that wording exists to prevent.
        """
        if not problems:
            return
        body = "\n".join(f"• {report.message}" for report in problems)
        dialog = Adw.AlertDialog(heading=COPY["addons-done-heading"], body=body)
        dialog.add_response("close", COPY["close"])
        dialog.present(self)

    # -- undo --------------------------------------------------------------

    def _undo(self, point_id: str) -> None:
        def work(narrate: Any) -> Any:
            return restorepoints.apply_point(point_id, lambda *a: narrate(_first_sentence(a)))

        def done(result: Any) -> None:
            if not self._alive:
                return
            # The same test the other two undo paths use (``window.py`` and the
            # Undo page). ``warnings`` is filled on the *success* path too —
            # from the settings a saved moment covers that this desktop no
            # longer has — so warnings alone said "gtheme could not put
            # everything back" about a restore that put everything back
            # (review-report M6). What did not finish is a restore with
            # nothing written: no transaction.
            warnings = list(getattr(result, "warnings", []) or [])
            failed = bool(warnings) and getattr(result, "transaction", None) is None
            self._toast(COPY["undo-failed"] if failed else COPY["undone"])
            self._changed()

        self._runner().run(
            work,
            heading=COPY["undo"],
            starting=COPY["undone"],
            on_done=done,
            on_failed=lambda _e: self._toast(COPY["undo-failed"]),
        )

    # -- saving the current desktop ---------------------------------------

    def _open_save_dialog(self) -> None:
        entry = Adw.EntryRow(title=COPY["save-name"])
        group = Adw.PreferencesGroup()
        group.add(entry)

        dialog = Adw.AlertDialog(heading=COPY["save-heading"], body=COPY["save-body"])
        dialog.set_extra_child(group)
        dialog.add_response("cancel", COPY["cancel"])
        dialog.add_response("save", COPY["save-confirm"])
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_save_response, entry)
        dialog.present(self)

    def _on_save_response(
        self, _dialog: Adw.AlertDialog, response: str, entry: Adw.EntryRow
    ) -> None:
        if response != "save":
            return
        typed = entry.get_text().strip()
        slug = slugify(typed)
        if not slug:
            self._toast(COPY["save-empty-name"])
            return
        held_by = look_registry.name_conflict(slug)
        if held_by is None:
            self._save_look(slug, typed)
            return
        self._confirm_save_over(slug, typed, held_by).present(self)

    def _confirm_save_over(self, slug: str, title: str, held_by: str) -> Adw.AlertDialog:
        """Ask before saving over a Look that is already here. Returns the dialog.

        A download that lands on a name already taken asks first
        (:meth:`_confirm_replace`); saving the current desktop under that same
        name used to write straight over the folder — same destruction, no
        question. The two paths now ask the same question, for the same reason
        and with the same two answers.

        Returned rather than merely presented so a test can drive the response
        with no window anywhere near it.
        """
        body = COPY["save-replace-yours"] if held_by == "yours" else COPY["save-replace-built-in"]
        dialog = Adw.AlertDialog(
            heading=COPY["replace-heading"].format(name=title or slug),
            body=body,
        )
        dialog.add_response("keep", COPY["replace-keep"])
        dialog.add_response("replace", COPY["replace-confirm"])
        dialog.set_response_appearance("replace", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("keep")
        dialog.set_close_response("keep")
        dialog.connect(
            "response",
            lambda _d, answer: self._save_look(slug, title) if answer == "replace" else None,
        )
        return dialog

    def _save_look(self, slug: str, title: str) -> None:
        self._runner().run(
            lambda _narrate: self.save_current_desktop(slug, title),
            heading=COPY["save-heading"],
            starting=COPY["working"],
            on_done=lambda result: self._save_finished(title, result, None),
            on_failed=lambda error: self._save_finished(title, None, error),
        )

    def save_current_desktop(self, slug: str, title: str) -> Any:
        """Write the desktop as it is now into a Look folder of its own.

        A method rather than a closure so that the whole save can be exercised
        by a test with a temporary Looks folder and a memory settings backend,
        without a dialog or a thread anywhere near it.
        """
        backend = get_backend()
        keys = capture_keys()
        return capture_share(
            keys,
            backend,
            out_dir=user_themes_dir() / slug,
            name=slug,
            title=title or slug,
            description="",
            components={key: component_for_key(key) for key in keys},
            enabled_extensions=enabled_extension_uuids(backend),
        )

    def _save_finished(self, title: str, result: Any, error: Exception | None) -> None:
        if not self._alive:
            return
        if error is not None or result is None:
            failed = Adw.AlertDialog(
                heading=COPY["save-failed"], body=str(error) if error else COPY["save-failed"]
            )
            failed.add_response("close", COPY["close"])
            failed.present(self)
            return
        self._changed()
        self._toast(COPY["saved"].format(title=title))
        notes = list(result.warnings)
        if notes:
            dialog = Adw.AlertDialog(
                heading=COPY["save-notes-heading"],
                body="\n".join(f"• {note}" for note in notes),
            )
            dialog.add_response("close", COPY["close"])
            dialog.present(self)

    # -- the community list ------------------------------------------------

    def _on_view_changed(self, *_args: Any) -> None:
        if self._stack.get_visible_child_name() == "browse":
            self._start_browse()

    def _start_browse(self, *, force: bool = False) -> None:
        if self._browse_started and not force:
            return
        self._browse_started = True
        self._browse_stack.set_visible_child_name("loading")
        look_registry.fetch_index_async(self._on_index)

    def _on_index(self, entries: Any, error: str | None) -> None:
        if not self._alive:
            return
        if error is not None or entries is None:
            self._browse_error.set_description(error or COPY["browse-failed"])
            self._browse_stack.set_visible_child_name("error")
            return
        # The publish rule: a Look nobody can see is a Look nobody should be
        # offered. No picture, no listing.
        listable = [entry for entry in entries if entry.screenshots]
        child = self._browse_grid.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            self._browse_grid.remove(child)
            child = following
        for entry in listable:
            self._browse_grid.append(self._community_tile(entry))
        self._browse_stack.set_visible_child_name("results" if listable else "empty")

    def _community_tile(self, entry: Any) -> Gtk.Widget:
        here = any(tile.name == entry.name for tile in self._tiles)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.append(_tile_preview(build_preview(palette=None)))

        title = Gtk.Label(label=entry.title or entry.name, xalign=0, wrap=True)
        title.add_css_class("heading")
        box.append(title)

        badge = Gtk.Label(
            label=COPY["browse-here"] if here else BADGES["community"], xalign=0
        )
        badge.add_css_class("caption")
        badge.add_css_class("dimmed")
        box.append(badge)

        if entry.description:
            box.append(_tile_description(entry.description))

        button = Gtk.Button(has_frame=False, child=TileFrame(box), halign=Gtk.Align.CENTER)
        button.add_css_class("flat")
        button.set_tooltip_text(entry.description or entry.title or entry.name)
        button.connect("clicked", lambda _button, e=entry, h=here: self._on_community(e, h))
        return button

    def _on_community(self, entry: Any, here: bool) -> None:
        if here:
            self._stack.set_visible_child_name("installed")
            return
        dialog = Adw.AlertDialog(
            heading=entry.title or entry.name,
            body=f"{entry.description}\n\n{COPY['safety']}".strip(),
        )
        dialog.add_response("close", COPY["close"])
        dialog.add_response("get", COPY["browse-get"])
        dialog.set_response_appearance("get", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("get")
        dialog.connect("response", self._on_community_response, entry)
        dialog.present(self)

    def _on_community_response(self, dialog: Adw.AlertDialog, response: str, entry: Any) -> None:
        if response != "get":
            return
        held_by = look_registry.name_conflict(entry.name)
        if held_by is None:
            self._download(entry)
            return
        self._confirm_replace(entry, held_by).present(self)

    def _confirm_replace(self, entry: Any, held_by: str) -> Adw.AlertDialog:
        """Ask before somebody else's Look takes the name of one already here.

        v1 never asked. A community Look called ``magma`` overwrote the user's
        own ``magma``, or shadowed the built-in one, and the only sign of it
        afterwards was that the Look they knew had different contents. The
        question has two answers because it has two consequences: replacing
        their own Look destroys it, and shadowing a built-in one only hides it.

        Returned rather than presented so a test can read the dialog without a
        window anywhere near it.
        """
        body = COPY["replace-yours"] if held_by == "yours" else COPY["replace-built-in"]
        dialog = Adw.AlertDialog(
            heading=COPY["replace-heading"].format(name=entry.title or entry.name),
            body=f"{body}\n\n{COPY['safety']}",
        )
        dialog.add_response("keep", COPY["replace-keep"])
        dialog.add_response("replace", COPY["replace-confirm"])
        dialog.set_response_appearance("replace", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("keep")
        dialog.set_close_response("keep")
        dialog.connect(
            "response",
            lambda _d, answer, e=entry: self._download(e, replace=True)
            if answer == "replace"
            else None,
        )
        return dialog

    def _download(self, entry: Any, *, replace: bool = False) -> None:
        """Fetch a Look and say what is happening while it happens.

        No thread. The fetch is asynchronous on the main loop already, so the
        progress dialog is updated straight from the callback -- HTTP on a
        worker thread is how a slow network becomes a frozen window, and it is
        the one thing the transport was built to avoid.
        """
        progress = Adw.AlertDialog(
            heading=entry.title or entry.name, body=COPY["browse-getting"]
        )
        progress.present(self)

        def done(path: Any, error: str | None) -> None:
            if not self._alive:
                return
            progress.close()
            if error is not None or path is None:
                failed = Adw.AlertDialog(
                    heading=COPY["browse-get-failed"], body=error or COPY["browse-failed"]
                )
                failed.add_response("close", COPY["close"])
                failed.present(self)
                return
            self._changed()
            # The community list badges what is already here, so it has to be
            # asked again or the tile the user just used still says "get".
            self._start_browse(force=True)
            self._stack.set_visible_child_name("installed")
            self._toast(COPY["browse-got"].format(name=entry.title or entry.name))

        look_registry.fetch_look_async(entry, done, replace=replace)

    # -- small helpers -----------------------------------------------------

    def _toast(self, text: str, *, undo_point: str | None = None) -> None:
        # ``Adw.Toast:title`` renders Pango markup. A Look is named by whoever
        # wrote it, so "Black & Gold" made the one confirmation that a Look was
        # applied render as nothing at all, and a title that is markup could
        # make it say something else entirely (review-report M15). The rest of
        # the app already escapes third-party names; the toasts were the miss.
        toast = Adw.Toast(title=escape_markup(text), timeout=8)
        if undo_point:
            toast.set_button_label(COPY["undo"])
            toast.connect("button-clicked", lambda _toast, p=undo_point: self._undo(p))
        overlay = getattr(self._window, "toasts", None)
        if overlay is not None:
            overlay.add_toast(toast)
        elif hasattr(self._window, "toast"):
            self._window.toast(text)

    def _go_to_page(self, page_id: str) -> None:
        show = getattr(self._window, "show_page", None)
        if callable(show):
            show(page_id)

    def _runner(self) -> ApplyRunner:
        """The window's runner, or a private one when there is no window.

        One runner per window means one progress dialog at a time, which is the
        property that stops two Looks being applied on top of each other.
        """
        runner = getattr(self._window, "runner", None)
        if isinstance(runner, ApplyRunner):
            return runner
        if self._own_runner is None:
            self._own_runner = ApplyRunner(self)
        return self._own_runner

    def _changed(self) -> None:
        """The desktop moved. Everything on screen re-reads itself."""
        after = getattr(self._window, "after_change", None)
        if callable(after):
            after()
        else:
            self.reload()


def _newest_point_id() -> str | None:
    """The most recent saved moment that is not "Before gtheme", if there is one.

    Never raises: this is only ever used to decide whether a *better* answer
    than "Close" can be offered on a failure dialog, and a state directory that
    cannot be read is a reason to offer less, not to lose the dialog.
    """
    try:
        points = [
            point for point in restorepoints.list_restore_points() if point.kind != "pristine"
        ]
    except Exception:  # noqa: BLE001 - no saved moments readable, no offer to make
        return None
    return points[0].id if points else None


def _first_sentence(args: Iterable[Any]) -> str:
    """Whatever the engine said, as one sentence to narrate."""
    for value in args:
        if isinstance(value, str) and value:
            return value
    return ""


def build(window: Any) -> Gtk.Widget:
    """The factory named by ``ui.registry``'s manifest."""
    return LooksPage(window)
