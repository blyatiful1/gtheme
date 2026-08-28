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
import zipfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from ...core import restorepoints  # noqa: E402
from ...core.backends import get_backend  # noqa: E402
from ...core.gvariant import parse_string_list, unquote  # noqa: E402
from ...core.stop import Stopped  # noqa: E402
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
    AddonBrief,
    ExtensionInstaller,
    InstallOutcome,
    InstallReport,
    describe_addons,
    readable_name,
)
from ...panels import conflicts as addon_conflicts  # noqa: E402
from ...panels import keyset  # noqa: E402
from ...prefs import Prefs  # noqa: E402
from ...preset import capture as capture_module  # noqa: E402
from ...preset import registry as look_registry  # noqa: E402
from ...preset.capture import CaptureResult, Omission, capture_share  # noqa: E402
from ...preset.compile import Available, compile_preset  # noqa: E402
from ...preset.loader import LoadResult, load, load_all, user_themes_dir  # noqa: E402
from ...preset.model import Component  # noqa: E402
from ..applyrunner import ApplyRunner  # noqa: E402
from ..preview import ASPECT_RATIO, build_preview  # noqa: E402
from ..search import escape_markup  # noqa: E402
from ..widgets.explainer import first_visit_banner  # noqa: E402

__all__ = [
    "BADGES",
    "COPY",
    "GRID_COLUMN",
    "TILE_WIDTH",
    "AddonBatch",
    "ApplyPlan",
    "LookAddons",
    "LookTile",
    "LooksPage",
    "MainLoopClient",
    "TileFrame",
    "accessibility_lines",
    "addon_names",
    "build",
    "capture_keys",
    "component_for_key",
    "conflict_lines",
    "detail_lines",
    "export_archive",
    "look_from_archive",
    "omission_sections",
    "plan_apply",
    "slugify",
    "tiles_from_results",
    "what_is_installed",
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
    # The add-ons themselves, by name, before anything is fetched. A count is
    # not something anybody can agree to: they are somebody else's code, and
    # which ones they are is the entire question (review-report H6).
    "addons-named": "The ones it would get:",
    "addons-source-note": (
        "gtheme downloads these itself and hands each one to your desktop to add. "
        "Your desktop does not show its own confirmation box when a Look brings "
        "add-ons — this list is it."
    ),
    "get-addons": "Get them and use this look",
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
    # The folder is in the sentence because "Saved as My Desktop." left the one
    # workaround for having no export — copying the folder yourself — with
    # nothing anywhere in the app naming the folder to copy (persona-report
    # §2.7).
    "saved": "Saved as {title}, in {folder}.",
    "save-failed": "gtheme could not save this desktop as a Look.",
    "save-notes-heading": "What gtheme changed before saving",
    "save-notes-omitted": "What this Look does not carry",
    "omitted-file": "Files:",
    "omitted-setting": "Settings:",
    "omitted-palette": "Colours:",
    "omitted-picture": "A picture of this desktop:",
    # -- moving a Look on or off this computer
    "export": "Save this Look to a file…",
    "export-title": "Save this Look to a file",
    "export-working": "Writing the file…",
    "exported": "Saved to {file}.",
    "export-failed": "gtheme could not write that file.",
    "import": "Add a Look from a file…",
    "import-title": "Add a Look from a file",
    "import-working": "Reading the file…",
    "imported": "{name} is on your computer now. Open it to try it out.",
    "import-failed": "That file could not be used as a Look",
    "import-not-a-look": (
        "gtheme could not find a Look in that file. A Look is the folder gtheme "
        "saves, or a file made by “Save this Look to a file”."
    ),
    "import-too-big": "That file is far larger than a Look should be.",
    # -- what this Look would do to settings you rely on
    "a11y-heading": (
        "This Look changes settings you use to see the screen. Undo puts them back:"
    ),
    "a11y-contrast": "Stronger contrast is switched on right now, and this Look changes it.",
    "a11y-text": "Your text is set larger than usual right now, and this Look changes it.",
    "a11y-motion": (
        "Movement and animation are switched off right now, and this Look switches "
        "them back on."
    ),
    "conflicts-heading": "Two add-ons would end up doing the same job:",
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
        addon_lines: those same add-ons *named* — one line each, from
            ``ego.install.describe_addons``. The count was all the dialog ever
            said, and a count is not something anybody can agree to: the button
            underneath downloads third-party code (review-report H6). Filled in
            from the Look's own file, without asking the network anything, so
            the preview says the same thing with the network unplugged and
            opening one is not a request to extensions.gnome.org.
        conflicts: pairs of add-ons that would end up doing the same job once
            this Look is on, in the words ``panels.conflicts`` already uses for
            the Add-ons page (persona-report §2.6).
        accessibility: the settings this Look would write over that the person
            is using to see the screen. Never collapsed into a count and never
            silent.
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
    addon_lines: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    accessibility: list[str] = field(default_factory=list)
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
        if self.accessibility:
            parts.append(
                COPY["a11y-heading"] + "\n" + "\n".join(f"• {line}" for line in self.accessibility)
            )
        if self.missing_addons:
            template = (
                COPY["missing-addons-one"]
                if self.missing_addons == 1
                else COPY["missing-addons-many"]
            )
            said = [template.format(count=self.missing_addons)]
            if self.addon_lines:
                # Named, and named *here* — above the button that fetches them,
                # in the same block of text as the count they replace.
                said.append(
                    COPY["addons-named"]
                    + "\n"
                    + "\n".join(f"• {line}" for line in self.addon_lines)
                )
                said.append(COPY["addons-source-note"])
            said.append(COPY["missing-addons-note"])
            parts.append("\n".join(said))
        if self.conflicts:
            parts.append(
                COPY["conflicts-heading"] + "\n" + "\n".join(f"• {line}" for line in self.conflicts)
            )
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


#: The settings somebody uses to see the screen, and what "switched on" means
#: for each. A Look that writes over one of these is not doing anything it is
#: forbidden to do — it is doing something the person has to be *told* about,
#: because the desktop they set up to be readable is about to stop being it
#: (persona-report §2.10). Each entry is ``(key, is-on test, sentence)``.
_ACCESSIBILITY: tuple[tuple[str, Callable[[str], bool], str], ...] = (
    (
        "gsettings:org.gnome.desktop.a11y.interface high-contrast",
        lambda value: unquote(value).strip().lower() == "true",
        COPY["a11y-contrast"],
    ),
    (
        "gsettings:org.gnome.desktop.interface text-scaling-factor",
        lambda value: _as_number(value) > 1.0,
        COPY["a11y-text"],
    ),
    (
        "gsettings:org.gnome.desktop.interface enable-animations",
        lambda value: unquote(value).strip().lower() == "false",
        COPY["a11y-motion"],
    ),
)


def _as_number(value: str) -> float:
    """A GVariant number as a number, or 0 when it is not one."""
    try:
        return float(unquote(value).strip())
    except (TypeError, ValueError):
        return 0.0


def accessibility_lines(diff: Diff) -> list[str]:
    """What this change would do to the settings somebody sees the screen with.

    Read off the plan rather than from a second look at the desktop: the diff
    already carries the current value of every key the Look writes, so the
    question "is high contrast on *now*" is already answered in the thing being
    previewed. A key the Look sets to the value it already has is not in
    ``changes`` and is not mentioned, because nothing would happen to it.
    """
    lines: list[str] = []
    for entry in diff.changes:
        key = getattr(entry.op, "key", None)
        if not key:
            continue
        for watched, is_on, sentence in _ACCESSIBILITY:
            if key == watched and entry.before is not None and is_on(entry.before):
                if sentence not in lines:
                    lines.append(sentence)
    return lines


def conflict_lines(
    enabled: Iterable[str],
    wanted: Iterable[str],
    *,
    names: Mapping[str, str] | None = None,
    extra: Iterable[Any] = (),
) -> list[str]:
    """Add-ons that would end up doing the same job once this Look is on.

    The Add-ons page runs this check on every switch and offers to turn the
    other one off; applying a whole Look ran it nowhere, so a Look that brings
    a dock left an Ubuntu desktop with two of them and no explanation
    (persona-report §2.6). Same table, same question, same sentence — asked of
    the union of what is on now and what the Look would switch on.

    Args:
        enabled: the add-ons on right now.
        wanted: the add-ons this Look would switch on.
        names: identifier to the name it calls itself, from
            :func:`addon_names`. Anything missing falls back to a readable form
            of its own file name, so a pair is never described by identifier.
        extra: further pairs, from ``panels.conflicts.from_panels``.
    """
    known = dict(names or {})

    def title(uuid: str) -> str:
        return known.get(uuid) or readable_name(uuid)

    lines: list[str] = []
    for conflict in addon_conflicts.active_conflicts({*enabled, *wanted}, extra):
        lines.append(
            f"{addon_conflicts.replacement_question(title(conflict.a), title(conflict.b))} "
            f"{conflict.explain}"
        )
    return lines


def what_is_installed() -> Available:
    """The icon sets, pointers, app styles and fonts on this computer.

    Read here rather than in the compiler, which judges values and never goes
    looking for them. Every one of these scanners already existed and
    ``scan_font_families`` had no caller in the whole application — the Looks
    that promise ``Papirus-Dark`` were never checked against the machine they
    were about to be applied to (persona-report §2.6).

    Never raises: a directory that will not be read costs a warning, never the
    preview it was going to appear in.
    """
    from ...system.fontscan import scan_font_families
    from ...system.iconscan import cursor_themes, default_icon_roots, scan_icon_themes
    from ...system.themescan import default_theme_roots, gtk_themes, scan_themes

    icons: frozenset[str] = frozenset()
    pointers: frozenset[str] = frozenset()
    styles: frozenset[str] = frozenset()
    fonts: frozenset[str] = frozenset()
    try:
        entries = scan_icon_themes(default_icon_roots())
        icons = frozenset(entry.directory_name for entry in entries)
        pointers = frozenset(entry.directory_name for entry in cursor_themes(entries))
    except OSError:  # pragma: no cover - a directory that will not be read
        pass
    try:
        styles = frozenset(entry.name for entry in gtk_themes(scan_themes(default_theme_roots())))
    except OSError:  # pragma: no cover - same
        pass
    try:
        fonts = frozenset(entry.name for entry in scan_font_families())
    except Exception:  # noqa: BLE001 - no font map, no font check
        pass
    return Available(
        icon_themes=icons, cursor_themes=pointers, app_styles=styles, fonts=fonts
    )


def plan_apply(
    tile: LookTile,
    *,
    installed: Sequence[str] | None = None,
    enabled: Sequence[str] | None = None,
    dest_root: str | None = None,
    shell_version: str | None = None,
    available: Available | None = None,
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
        enabled: the add-ons switched on right now, for the either/or check.
            None reads them; an empty list means "nothing is on", which is a
            different answer and produces no pairs either way.
        shell_version: what this desktop calls itself. The compiler's
            ``min_shell`` warning is computed from it, and a caller that does
            not pass it gets no warning — which is why the page reads it from
            the window instead of leaving it out (review-report L8: the engine
            half landed in Wave A and nothing ever handed it a version, so a
            Look made for a newer GNOME still applied in silence).
        available: what this computer has, for the value check. None means the
            values are not checked and nothing is claimed about them.
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
            available=available,
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
            addon_lines=describe_addons(
                AddonBrief(uuid=uuid, source=source) for uuid, source, _alt in missing
            ),
            problem=f"{COPY['cannot-preview']}\n\n{exc}",
        )

    uuids = [
        op.uuid
        for op in compiled.transaction.ops
        if isinstance(op, ExtensionEnable | ExtensionInstall)
    ]
    names = addon_names(uuids)
    switched_on = list(enabled) if enabled is not None else enabled_extension_uuids()
    return ApplyPlan(
        title=tile.title,
        lines=diff.to_novice_lines(),
        warnings=list(compiled.warnings),
        missing_addons=len(missing),
        missing=missing,
        # Named from this computer alone, so the dialog is the same dialog with
        # the network unplugged. The real titles and authors arrive after, and
        # only if the library answers.
        addon_lines=describe_addons(
            AddonBrief(uuid=uuid, source=source) for uuid, source, _alt in missing
        ),
        conflicts=conflict_lines(switched_on, uuids, names=names),
        accessibility=accessibility_lines(diff),
        details=detail_lines(diff, names=names),
        transaction=compiled.transaction,
    )


class MainLoopClient:
    """The add-on library, asked from the main loop and answered on this thread.

    Two rules pull in opposite directions and this is what reconciles them.
    libsoup's session may only be used from the thread running the main loop —
    that is why the whole download path is asynchronous in the first place. And
    unpacking an add-on may not run *on* that thread: ``gnome-extensions
    install`` compiles the add-on's settings descriptions, which is a subprocess
    with no timeout, once per add-on, and it ran inside the download callback —
    on the main loop, behind the app's own progress dialog, with the window
    frozen for the whole batch (review-report M9).

    So the request hops to the main loop and the answer comes back here: this
    wrapper is handed to :class:`~gtheme.ego.install.ExtensionInstaller` in
    place of the real library, and every method of it blocks the *worker*
    thread until the main loop has been round. The installer's own code is
    unchanged and runs entirely on the thread that called it, which is the
    worker thread the runner already provides — so the unpack happens there and
    only the network legs are on the main loop.

    Called from the main thread itself, it calls straight through: a test with a
    fake library that answers immediately needs no loop to be running.

    Args:
        client: the real library.
        timeout: how long one request may take before the answer is "no".
    """

    #: One request's own ceiling. Shorter than the batch's, because a batch is
    #: several of these and the batch timeout is the one a person waits out.
    TIMEOUT_SECONDS = 60.0

    def __init__(self, client: Any, *, timeout: float | None = None) -> None:
        self.client = client
        self.timeout = self.TIMEOUT_SECONDS if timeout is None else timeout

    def info(self, uuid: str, callback: Callable[[Any, Any], None]) -> None:
        """Ask the library about one add-on."""
        self._ask(lambda answer: self.client.info(uuid, answer), callback)

    def download(
        self, uuid: str, version_tag: int, callback: Callable[[Any, Any], None]
    ) -> None:
        """Fetch one add-on's package."""
        self._ask(lambda answer: self.client.download(uuid, version_tag, answer), callback)

    def _ask(
        self,
        start: Callable[[Callable[[Any, Any], None]], None],
        callback: Callable[[Any, Any], None],
    ) -> None:
        if threading.current_thread() is threading.main_thread():
            start(callback)
            return
        landed: dict[str, Any] = {}
        finished = threading.Event()

        def answered(payload: Any, error: Any) -> None:
            landed["payload"], landed["error"] = payload, error
            finished.set()

        def kick() -> bool:
            try:
                start(answered)
            except Exception as exc:  # noqa: BLE001 - reported as this request's error
                answered(None, exc)
            return GLib.SOURCE_REMOVE

        GLib.idle_add(kick)
        if not finished.wait(self.timeout):
            callback(None, TimeoutError(COPY["addons-timeout"]))
            return
        callback(landed.get("payload"), landed.get("error"))


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
        bridged: the client is a :class:`MainLoopClient`, so the batch may run
            on the thread that started it and the unpacking stays off the main
            loop (review-report M9). With the real library this must be false,
            because the real library may only be spoken to from the main loop.
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
        bridged: bool = False,
    ) -> None:
        self.installer = installer
        self.client = client
        self.shell_version = shell_version
        self.label = label
        self.bridged = bridged

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

        if self.bridged:
            # Every leg that has to be on the main loop already knows how to get
            # there by itself (:class:`MainLoopClient`), so the rest of the
            # batch — the unpacking, which is a subprocess per add-on — runs
            # right here, on whichever thread asked (review-report M9).
            start()
        elif threading.current_thread() is threading.main_thread():
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


class LookAddons:
    """Fetch the add-ons a Look needs, from inside the Look's own transaction.

    Wave A gave :class:`~gtheme.core.transaction.Transaction` an ``installer``
    seam and deliberately left it unwired: downloading needs the network and a
    person's consent, and neither belongs to the engine. This is the thing that
    fills it, and the consent is the button — "Get them and use this look" is
    the one press that says yes to third-party code, and it is pressed under a
    list that names every add-on it would fetch (review-report H6, X1).

    Why it matters that this runs *inside* the transaction rather than beside
    it: an add-on's settings do not exist until the add-on does, so a Look that
    brought an add-on and then tuned it used to need **two** applies — the
    first installed it and silently skipped every one of its settings, and
    nothing said so. Now the install phase runs first, in the same
    all-or-nothing change, with one restore point around the lot.

    Applying a Look *without* that press hands the transaction no installer at
    all, which is the old behaviour and the honest one: a missing add-on is a
    named skip.

    Args:
        batch: the :class:`AddonBatch` that knows how to fetch one.
        on_progress: called with each sentence, for the progress dialog.
    """

    def __init__(self, batch: AddonBatch, on_progress: Callable[[str], None] | None = None) -> None:
        self.batch = batch
        self.on_progress = on_progress
        #: Every add-on that did not arrive, carrying the installer's own
        #: sentence for why. Read after the apply and shown as-is.
        self.problems: list[Any] = []

    def __call__(self, op: ExtensionInstall) -> bool:
        """Get one add-on. Returns whether it is now on this computer."""
        try:
            _transaction, problems = self.batch.run_and_wait(
                [(op.uuid, op.source, ())], on_progress=self.on_progress
            )
        except TimeoutError:
            self.problems.append(
                InstallReport(op.uuid, InstallOutcome.FAILED, COPY["addons-timeout"])
            )
            return False
        except Stopped:
            # The progress callback is the runner's narrator, and the narrator
            # is where Stop is raised — so a stop pressed during a download
            # arrives here, looking exactly like a download that failed. It is
            # not one. Recording it as one told the reader their internet
            # connection was at fault for their own decision, and the arm below
            # then let the apply run to the end (review-report E5).
            raise
        except Exception as error:  # noqa: BLE001 - one add-on may fail; the Look may not
            self.problems.append(_not_added(op.uuid, error))
            return False
        self.problems.extend(problems)
        return not problems


#: How many files one Look may be made of, coming in. A Look is a description,
#: a picture and a handful of small text files; the bundled ones ship twenty.
#: A cap is here because the file on the other side of this was chosen by
#: somebody else, and unpacking is the moment to stop being trusting.
MAX_LOOK_FILES = 400

#: The name given to a Look saved out of gtheme.
ARCHIVE_SUFFIX = ".gtheme.zip"


def export_archive(folder: Path | str, destination: Path | str) -> Path:
    """Write one Look folder into a single file somebody can send.

    The format genuinely travels — ``{{ home }}`` in place of the login name, a
    wallpaper copied in, a scan for anything private — and there was no way to
    move one: no export, no import, no "reveal in Files", and the save toast
    did not even name the folder to copy by hand (persona-report §2.7).

    Written with the Look's own files at the root of the archive, so what comes
    out of :func:`look_from_archive` needs no unwrapping, and a person who opens
    it in their file manager sees ``theme.toml`` rather than one folder holding
    one folder.
    """
    source = Path(folder)
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f".{target.name}.part")
    try:
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(source.rglob("*")):
                if item.is_file() and not item.is_symlink():
                    archive.write(item, arcname=str(item.relative_to(source).as_posix()))
        partial.replace(target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return target


def _archive_members(path: Path) -> dict[str, bytes]:
    """Every file in a Look archive or Look folder, by its path inside it.

    Refuses before it reads: a member that names an absolute path or climbs out
    with ``..`` is not a Look gtheme is going to unpack, and a file larger than
    a Look's own limit is not one either. ``registry.install_look`` checks the
    same boundary again on the way in — this one is here so the refusal has a
    sentence attached rather than being an exception from three layers down.
    """
    if path.is_dir():
        found: dict[str, bytes] = {}
        for item in sorted(path.rglob("*")):
            if not item.is_file() or item.is_symlink():
                continue
            if item.stat().st_size > look_registry.MAX_LOOK_FILE_BYTES:
                raise look_registry.LookFetchError(COPY["import-too-big"])
            found[str(item.relative_to(path).as_posix())] = item.read_bytes()
            if len(found) > MAX_LOOK_FILES:
                raise look_registry.LookFetchError(COPY["import-too-big"])
        return found
    with zipfile.ZipFile(path) as archive:
        names = [item for item in archive.infolist() if not item.is_dir()]
        if len(names) > MAX_LOOK_FILES:
            raise look_registry.LookFetchError(COPY["import-too-big"])
        found = {}
        for item in names:
            relative = PurePosixPath(item.filename)
            if relative.is_absolute() or ".." in relative.parts:
                raise look_registry.LookFetchError(
                    "that file tried to put something outside the Look's own folder"
                )
            if item.file_size > look_registry.MAX_LOOK_FILE_BYTES:
                raise look_registry.LookFetchError(COPY["import-too-big"])
            found[str(relative)] = archive.read(item)
        return found


def _unwrapped(files: Mapping[str, bytes]) -> dict[str, bytes]:
    """The Look's own files, with one wrapping folder taken off if there is one.

    Somebody zipping the folder themselves gets ``magma/theme.toml``; gtheme's
    own export writes ``theme.toml``. Both are the same Look and both open.
    """
    if look_registry.PRESET_FILENAME in files:
        return dict(files)
    tops = {PurePosixPath(name).parts[0] for name in files if PurePosixPath(name).parts}
    if len(tops) != 1:
        return dict(files)
    prefix = tops.pop() + "/"
    if not all(name.startswith(prefix) for name in files):
        return dict(files)
    return {name[len(prefix) :]: payload for name, payload in files.items()}


def look_from_archive(path: Path | str) -> tuple[Any, dict[str, bytes]]:
    """Read a Look out of a file (or a folder) somebody handed you.

    Returns ``(entry, files)`` in exactly the shape
    :func:`gtheme.preset.registry.install_look` takes, so a Look that arrives
    from a file goes onto the computer through the same door a downloaded one
    does: the same confinement, the same staging folder, the same validation by
    the same loader, and the same question when the name is already taken.

    Raises:
        LookFetchError: the file holds no Look, or holds something that is not
            allowed to be in one. Nothing is written in either case.
    """
    source = Path(path)
    try:
        files = _unwrapped(_archive_members(source))
    except look_registry.LookFetchError:
        raise
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise look_registry.LookFetchError(COPY["import-not-a-look"]) from exc
    if look_registry.PRESET_FILENAME not in files:
        raise look_registry.LookFetchError(COPY["import-not-a-look"])

    import tempfile

    with tempfile.TemporaryDirectory(prefix="gtheme-import-") as tmp:
        staged = Path(tmp) / "look"
        for relative, payload in files.items():
            landing = staged / relative
            if not landing.resolve().is_relative_to(staged.resolve()):
                raise look_registry.LookFetchError(
                    "that file tried to put something outside the Look's own folder"
                )
            landing.parent.mkdir(parents=True, exist_ok=True)
            landing.write_bytes(payload)
        result = load(staged)
    if result.preset is None or result.errors:
        problems = "; ".join(result.errors) or COPY["import-not-a-look"]
        raise look_registry.LookFetchError(problems)
    return look_registry.entry_for(result.preset, provenance="community"), files


def _already_said(result: CaptureResult) -> set[str]:
    """The warning lines that are only a prose form of the omissions.

    A capture records every omission twice on purpose: once in the structured
    list, and once as a sentence in ``warnings`` — because until now the only
    renderer read ``warnings`` and a saved Look that quietly left something
    behind was the failure that list was added to stop. Now that the dialog
    lays the list out properly, the prose copies have to come out or it says
    everything twice (persona-report §2.7, P1's note).

    The function that *built* those sentences is the only honest answer to
    "which ones are they": a copy of the wording here would go stale in silence
    the first time a sentence is reworded. Read defensively, because a nicer
    dialog is never worth losing the save.
    """
    notes = getattr(capture_module, "_omission_notes", None)
    if notes is None:  # pragma: no cover - only if capture is restructured
        return set()
    try:
        return set(notes(result.omissions))
    except Exception:  # noqa: BLE001 - same reason
        return set()


def omission_sections(omissions: Sequence[Omission]) -> list[str]:
    """What a saved Look does not carry, grouped by what kind of thing it is.

    :class:`~gtheme.preset.capture.Omission` is structured on purpose — one
    entry per thing, with the thing named — and the only renderer it had read
    the *sentences* out of ``warnings`` instead, where settings are counted by
    reason because there is no room to list them. So the dialog said "one
    setting was left out because it may contain something private" and never
    which one, while the list that knew sat unused beside it (persona-report
    §2.7, P1's double-say note).
    """
    headings = {
        "file": COPY["omitted-file"],
        "setting": COPY["omitted-setting"],
        "palette": COPY["omitted-palette"],
        "picture": COPY["omitted-picture"],
    }
    sections: list[str] = []
    for kind, heading in headings.items():
        group = [item for item in omissions if item.kind == kind]
        if not group:
            continue
        sections.append(
            heading + "\n" + "\n".join(f"• {item.sentence()}" for item in group)
        )
    return sections


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


def capture_keys(corpus: Any | None = None, *, directory: Path | str | None = None) -> list[str]:
    """Every setting a Look saved from this desktop carries.

    One derivation, shared with the saved moments the Undo page writes, because
    two loops over the same data disagreed by 174 keys and the light-or-dark
    switch was one of them: a desktop saved as a Look on a dark machine carried
    the dark *app style* and not the switch that makes the rest of the desktop
    dark, so applying it on a light machine produced half a Look
    (review-report H13). :mod:`gtheme.panels.keyset` holds the derivation and
    the reasoning, including why a shareable Look deliberately leaves the
    ``floor`` tier — somebody's accessibility and screensaver settings — out.
    """
    return keyset.look_keys(corpus, directory=directory)


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


#: Every Look picture this session has decoded, by the file it came from and
#: when that file was last written.
#:
#: A Look's screenshot is a real screenshot: the four shipped ones are 2560×1440
#: PNGs, ~11-15 MB of texture each once materialised and 55-75 ms to decode, and
#: ``reload()`` rebuilt every tile from scratch — on first open, and again after
#: every applied Look, undo, restore point and download (review-report M8). The
#: Home page and the wallpaper grid have gone through the desktop's own
#: thumbnail store since they were written, with the comment "handing one
#: straight to a picture widget is a visible stall"; this is that route, plus a
#: texture kept so a rebuild is a dictionary lookup rather than a second decode.
_TEXTURES: dict[tuple[str, int], Gdk.Texture] = {}


def _texture_for(path: Path) -> Gdk.Texture | None:
    """A decoded picture for one file, from this session's cache or from disk.

    Never raises: a picture that cannot be read leaves the tile with the
    painted card it already has, which is a worse preview and a working tile.
    """
    try:
        stamp = int(path.stat().st_mtime)
    except OSError:
        return None
    seen = _TEXTURES.get((str(path), stamp))
    if seen is not None:
        return seen
    try:
        texture = Gdk.Texture.new_from_filename(str(path))
    except GLib.Error:
        return None
    _TEXTURES[(str(path), stamp)] = texture
    return texture


def _show_picture(frame: Gtk.Widget, path: Path) -> bool:
    """Put a picture inside a preview frame in place of its painted card."""
    texture = _texture_for(path)
    if texture is None:
        return False
    setter = getattr(frame, "set_child", None)
    if setter is None:  # pragma: no cover - build_preview always returns a frame
        return False
    setter(Gtk.Picture(paintable=texture, content_fit=Gtk.ContentFit.COVER))
    return True


def _picture_tile(
    frame: Gtk.Widget, source: Path | None, *, alive: Callable[[], bool] | None = None
) -> Gtk.Widget:
    """Fill a preview frame from the thumbnail store, generating off-thread.

    The cached thumbnail is a stat-and-hash lookup, cheap enough for the main
    loop and the reason a grid of Looks opens without a hitch. A miss goes to a
    worker thread and lands back here later; until then the tile shows the
    Look's own colours, which is what it showed before this existed.
    """
    if source is None:
        return frame
    from ...system import thumbnails

    try:
        cached = thumbnails.lookup_cached_thumbnail(source)
    except Exception:  # noqa: BLE001 - no thumbnail store, no thumbnail
        cached = None
    if cached is not None and _show_picture(frame, cached):
        return frame

    def ready(thumb: Path | None, _error: Exception | None) -> None:
        if alive is not None and not alive():
            return
        _show_picture(frame, thumb if thumb is not None else source)

    try:
        thumbnails.request_thumbnail_async(source, ready)
    except Exception:  # noqa: BLE001 - same
        _show_picture(frame, source)
    return frame


def _first_picture(paths: Iterable[Path]) -> Path | None:
    """The first screenshot a Look actually ships, in its own preference order."""
    for path in paths:
        try:
            if path.is_file():
                return path
        except OSError:  # pragma: no cover - a path that will not be stat'd
            continue
    return None


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
        self._installed_things: Available | None = None
        self._addon_library: Any = None
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

        # Under the list in every one of its states, including the empty one.
        # Until now there was no way to get a Look onto this computer except
        # the published list, and the published list holds only Looks that
        # came with the app — so "get more" could not get you any
        # (persona-report §2.2, §2.7). A file somebody sent you is the other
        # way in, and it lands through the same door a download does.
        add = Adw.PreferencesGroup(margin_top=12, margin_start=18, margin_end=18)
        add_row = Adw.ButtonRow(title=COPY["import"], start_icon_name="document-open-symbolic")
        add_row.connect("activated", lambda _row: self._open_import_dialog())
        add.add(add_row)

        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._browse_stack.set_vexpand(True)
        column.append(self._browse_stack)
        column.append(add)
        return column

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
        # The palette card first, always: it is what this tile shows until a
        # picture is ready, and what it keeps if none ever is.
        box.append(
            _picture_tile(
                _tile_preview(build_preview(palette=tile.palette)),
                _first_picture(tile.pictures),
                alive=lambda: self._alive,
            )
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
        self._show_preview(tile, self.plan_for(tile))

    def plan_for(self, tile: LookTile) -> ApplyPlan:
        """What using this Look would do to *this* computer.

        Everything the compiler needs measuring is measured here and passed in,
        because the compiler judges and never goes looking: what version the
        desktop calls itself, which icon sets and fonts are installed, which
        add-ons are switched on. A helper rather than three arguments at the
        call site so the community grid and the installed grid ask the same
        question.
        """
        return plan_apply(
            tile,
            shell_version=self._shell_version(),
            available=self._available(),
        )

    def _available(self) -> Available:
        """What this computer has, read once per rebuild of the grid."""
        if self._installed_things is None:
            self._installed_things = what_is_installed()
        return self._installed_things

    def _show_problem(self, tile: LookTile) -> None:
        body = COPY["broken-body"] + "\n\n" + "\n".join(f"• {line}" for line in tile.problems)
        dialog = Adw.AlertDialog(heading=COPY["broken-heading"], body=body)
        dialog.add_response("close", COPY["close"])
        dialog.present(self)

    def _show_preview(self, tile: LookTile, plan: ApplyPlan) -> None:
        """The preview, built entirely from this computer.

        Nothing here asks the network anything, and that is a promise rather
        than an accident: README says gtheme "only goes online if you ask it to
        look for new add-ons or new Looks, and it says so when it does", and
        SECURITY.md lists the two requests it ever makes. Opening a preview is
        neither of them.

        A version of this did look the missing add-ons up on
        extensions.gnome.org — one request each, to replace their identifiers
        with the titles their authors gave them — behind a dialog that said
        nothing about going online. The names H6 asked for are already here
        without it: ``ApplyPlan.addon_lines`` is filled in from the Look's own
        file when the plan is built, so the reader still agrees to named
        add-ons rather than to a count, offline, with the network unplugged.
        A nicer title was not worth the third silent request.
        """
        dialog = Adw.AlertDialog(heading=tile.title, body=plan.body(), prefer_wide_layout=True)
        if plan.details:
            dialog.set_extra_child(_details_widget(plan.details))
        dialog.add_response("cancel", COPY["cancel"])
        dialog.add_response("export", COPY["export"])
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
        elif response == "export":
            self._open_export_dialog(tile)

    def _apply(
        self, tile: LookTile, transaction: Transaction, *, addons: LookAddons | None = None
    ) -> None:
        """Apply a Look on the shared runner, narrating while it happens.

        Args:
            addons: how to fetch the add-ons this Look wants, when the person
                has said to. Absent — the ordinary "use this look" press — the
                transaction gets no installer and a missing add-on stays a
                named skip, which is the promise the preview made (X1).
        """
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

            if addons is not None:
                # The seam, filled only here. ``work`` runs on the runner's
                # worker thread, which is exactly where an unpack belongs.
                addons.on_progress = narrate
                transaction.installer = addons  # type: ignore[attr-defined]
            return transaction.apply(report)

        def done(outcome: Any) -> None:
            if not self._alive:
                return
            point = getattr(outcome, "restore_point", None)
            self._toast(COPY["applied"].format(title=tile.title), undo_point=point)
            self._changed()
            if addons is not None:
                self._report_addons(addons.problems)
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
        """Fetch what this Look needs and use it, as one change.

        Not a redirect to another page: the person said "use this look", and
        "go and find three add-ons yourself" is not an answer to that. Not two
        changes either — the add-ons arrive inside the Look's own transaction,
        so one restore point covers the lot and an add-on's settings are
        written after the add-on exists rather than skipped before it does
        (review-report X1).

        The press is the consent, and it is pressed under a list that names
        every add-on by title, author and where it comes from.
        """
        batch = self._addon_batch(tile.title)
        if batch is None:
            self._toast(COPY["addons-none"])
            self._go_to_page("addons")
            return
        if plan.transaction is None:
            return
        self._apply(tile, plan.transaction, addons=LookAddons(batch))

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
        """The batch installer, or None when there is no desktop to add to.

        The library is wrapped in a :class:`MainLoopClient` before the
        installer ever sees it, so the network legs run on the main loop and
        everything else — unzipping, ``gnome-extensions install``, one
        subprocess per add-on — runs on whichever thread drove the batch
        (review-report M9). Nothing downstream knows the difference.
        """
        shell = getattr(self._window, "shell", None)
        if shell is None:
            return None
        version = self._shell_version() or ""
        client = self._addon_client(version)
        bridged = MainLoopClient(client) if client is not None else None
        installer = ExtensionInstaller(shell, bridged)
        return AddonBatch(
            installer, bridged, shell_version=version, label=label, bridged=bridged is not None
        )

    def _addon_client(self, version: str) -> Any:
        """The add-on library, built once per page.

        Once, because one batch asks it for a build per add-on and a new
        session with a new on-disk store per dialog would throw away the
        answers that make the next look-up free. Built lazily, on the first
        thing that really needs the network — opening a preview is not one of
        them, and must not become one.
        """
        from ...ego.client import DiskCache, EgoClient, SoupTransport

        if self._addon_library is None:
            try:
                self._addon_library = EgoClient(
                    SoupTransport("gtheme"), version or "50", DiskCache()
                )
            except Exception:  # noqa: BLE001 - no internet client, no download path
                return None
        return self._addon_library

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
        # The moment is read before the work, and named in the sentence at the
        # end. This is the fourth surface that could start an undo and the
        # fourth that said only "Put back how it was." — U8's acceptance line
        # is "toast names the moment", and one page still not naming it is the
        # same failure as four pages not naming it. Read first, because going
        # back takes a restore point of its own and the newest moment
        # afterwards is a different one.
        from . import restore as restore_page

        try:
            point = restorepoints.load(point_id)
        except OSError:  # pragma: no cover - defensive; a name is never worth a crash
            point = None

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
            self._toast(
                COPY["undo-failed"] if failed else restore_page.done_sentence(point)
            )
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
        folder = getattr(result, "path", None) or user_themes_dir()
        self._toast(COPY["saved"].format(title=title, folder=folder))
        body = self.save_notes(result)
        if body:
            dialog = Adw.AlertDialog(heading=COPY["save-notes-heading"], body=body)
            dialog.add_response("close", COPY["close"])
            dialog.present(self)

    def save_notes(self, result: CaptureResult) -> str:
        """What to tell somebody about the Look that was just written.

        Two different things, said once each. What the capture *changed* on the
        way out — a path made general so it works on somebody else's computer,
        a wallpaper copied in — is a warning. What the Look does not carry is
        an omission, and those are grouped and named here from
        :attr:`~gtheme.preset.capture.CaptureResult.omissions` rather than read
        back out of the warning list, where every setting is counted by reason
        because the sentences have no room to name them. Both lists held the
        same facts and the dialog showed both, so a saved desktop reported the
        same omission twice in two different phrasings (persona-report §2.7).
        """
        sections = omission_sections(getattr(result, "omissions", []) or [])
        changed = [note for note in result.warnings if note not in _already_said(result)]
        parts: list[str] = []
        if changed:
            parts.append("\n".join(f"• {note}" for note in changed))
        if sections:
            parts.append(COPY["save-notes-omitted"] + "\n" + "\n\n".join(sections))
        return "\n\n".join(parts)

    # -- moving a Look on and off this computer ---------------------------

    def _open_export_dialog(self, tile: LookTile) -> None:
        """Ask where to put this Look, then write it there."""
        dialog = Gtk.FileDialog(
            title=COPY["export-title"], initial_name=f"{tile.name}{ARCHIVE_SUFFIX}"
        )

        def chosen(source: Any, result: Any) -> None:
            try:
                target = source.save_finish(result)
            except GLib.Error:
                return  # the person closed the picker; that is not a failure
            if target is None or target.get_path() is None:
                return
            self.export_look(tile, Path(target.get_path()))

        dialog.save(self._parent_window(), None, chosen)

    def export_look(self, tile: LookTile, destination: Path) -> None:
        """Write a Look to a file on the shared runner, and say where it went."""

        def done(path: Any) -> None:
            if self._alive:
                self._toast(COPY["exported"].format(file=path))

        def failed(error: Exception) -> None:
            if not self._alive:
                return
            dialog = Adw.AlertDialog(heading=COPY["export-failed"], body=str(error))
            dialog.add_response("close", COPY["close"])
            dialog.present(self)

        self._runner().run(
            lambda _narrate: export_archive(tile.directory, destination),
            heading=COPY["export-title"],
            starting=COPY["export-working"],
            on_done=done,
            on_failed=failed,
        )

    def _open_import_dialog(self) -> None:
        """Ask for a file, then put the Look in it onto this computer."""
        dialog = Gtk.FileDialog(title=COPY["import-title"])
        looks_only = Gtk.FileFilter(name=COPY["import-title"])
        looks_only.add_pattern("*.zip")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(looks_only)
        dialog.set_filters(filters)
        dialog.set_default_filter(looks_only)

        def chosen(source: Any, result: Any) -> None:
            try:
                chosen_file = source.open_finish(result)
            except GLib.Error:
                return  # cancelled
            if chosen_file is None or chosen_file.get_path() is None:
                return
            self.import_look(Path(chosen_file.get_path()))

        dialog.open(self._parent_window(), None, chosen)

    def import_look(self, path: Path, *, replace: bool = False) -> None:
        """Read a Look out of a file and install it, asking before overwriting.

        The reading and the writing are one job on the runner: both touch the
        disk, and a Look with a wallpaper in it is not always small.
        """

        def work(_narrate: Any) -> Any:
            entry, files = look_from_archive(path)
            if not replace and look_registry.name_conflict(entry.name) is not None:
                return entry  # ask first; nothing has been written
            return (entry, look_registry.install_look(entry, files, replace=replace))

        def done(outcome: Any) -> None:
            if not self._alive:
                return
            if isinstance(outcome, tuple):
                entry, _folder = outcome
                self._changed()
                self._stack.set_visible_child_name("installed")
                self._toast(COPY["imported"].format(name=entry.title or entry.name))
                return
            held_by = look_registry.name_conflict(outcome.name) or "yours"
            self._confirm_import_over(path, outcome, held_by).present(self)

        def failed(error: Exception) -> None:
            if not self._alive:
                return
            dialog = Adw.AlertDialog(heading=COPY["import-failed"], body=str(error))
            dialog.add_response("close", COPY["close"])
            dialog.present(self)

        self._runner().run(
            work,
            heading=COPY["import-title"],
            starting=COPY["import-working"],
            on_done=done,
            on_failed=failed,
        )

    def _confirm_import_over(self, path: Path, entry: Any, held_by: str) -> Adw.AlertDialog:
        """The same question a download asks, for a Look arriving from a file.

        Returned rather than presented so a test can drive the answer with no
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
            lambda _d, answer: self.import_look(path, replace=True)
            if answer == "replace"
            else None,
        )
        return dialog

    def _parent_window(self) -> Any:
        """The window a file picker should sit on, or None outside one."""
        root = self.get_root()
        return root if isinstance(root, Gtk.Window) else None

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
        # The publish rule *and* the mirror rule, both in one function now
        # (``registry.browsable``): a Look nobody can see is a Look nobody
        # should be offered, and a Look that came with the app is not a
        # discovery. Every entry in the published list is bundled today, so
        # this grid used to show the user four Looks they already had, each
        # badged "Already on this computer", each bouncing them back to the
        # other tab when clicked — and the honest empty state written for this
        # page was unreachable (persona-report §2.2).
        listable = look_registry.browsable(entries)
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
        box.append(self._community_preview(entry))

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

    def _community_preview(self, entry: Any) -> Gtk.Widget:
        """A community tile's picture: the real screenshot, fetched.

        Every tile in this grid was drawn ``build_preview(palette=None)`` — the
        neutral grey card — immediately after a filter whose comment read "No
        picture, no listing" (persona-report §2.2). The picture exists, at an
        address ``registry.screenshot_url`` already knew how to build; nothing
        ever asked for it. A fetch that fails leaves the card, which is why the
        card is what gets built first.
        """
        frame = _tile_preview(build_preview(palette=None))
        cached = look_registry.cached_screenshot(entry)
        if cached is not None and _show_picture(frame, cached):
            return frame

        def landed(path: Any, _reason: str | None) -> None:
            if not self._alive or path is None:
                return
            _picture_tile(frame, Path(path), alive=lambda: self._alive)

        try:
            look_registry.fetch_screenshot_async(entry, landed)
        except Exception:  # noqa: BLE001 - a missing picture is not a lost tile
            pass
        return frame

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
