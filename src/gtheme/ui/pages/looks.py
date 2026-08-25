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
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ...core import restorepoints  # noqa: E402
from ...core.backends import get_backend  # noqa: E402
from ...core.gvariant import parse_string_list  # noqa: E402
from ...core.transaction import (  # noqa: E402
    ENABLED_EXTENSIONS_KEY,
    ExtensionInstall,
    Progress,
    Transaction,
    TransactionError,
    installed_extension_uuids,
)
from ...panels.loader import load_corpus  # noqa: E402
from ...prefs import Prefs  # noqa: E402
from ...preset import registry as look_registry  # noqa: E402
from ...preset.capture import capture_share  # noqa: E402
from ...preset.compile import compile_preset  # noqa: E402
from ...preset.loader import LoadResult, load_all, user_themes_dir  # noqa: E402
from ...preset.model import Component  # noqa: E402
from ..preview import build_preview  # noqa: E402
from ..widgets.rows import key_for  # noqa: E402

__all__ = [
    "BADGES",
    "COPY",
    "ApplyPlan",
    "LookTile",
    "LooksPage",
    "build",
    "capture_keys",
    "component_for_key",
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
    "first-visit-dismiss": "Got it",
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
    "get-addons": "Open Add-ons",
    "cannot-preview": (
        "gtheme could not work out what this Look would change on this computer."
    ),
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
        "gtheme could not put everything back on its own. Open Undo & Restore Points "
        "and go back to a saved moment."
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
    "browse-not-yet": (
        "Downloading a Look from other people isn't built yet. This list shows what "
        "has been published so far."
    ),
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
        transaction: what to apply. None when the Look could not be compiled.
        problem: why there is nothing to apply, when there is nothing.
    """

    title: str
    lines: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing_addons: int = 0
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


def plan_apply(
    tile: LookTile,
    *,
    installed: Sequence[str] | None = None,
    dest_root: str | None = None,
) -> ApplyPlan:
    """Compile a Look and work out what applying it would change.

    Never raises. Everything that can go wrong here — a Look that does not
    validate, a settings store that cannot be read — is something the dialog has
    to be able to say out loud, so it comes back as ``problem`` rather than as
    an exception thrown at a click handler.
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
        )
    except Exception as exc:  # noqa: BLE001 - a bad Look must not kill the page
        return ApplyPlan(title=tile.title, problem=f"{COPY['cannot-preview']}\n\n{exc}")

    missing = sum(1 for op in compiled.transaction.ops if isinstance(op, ExtensionInstall))
    try:
        diff = compiled.transaction.plan()
    except Exception as exc:  # noqa: BLE001 - same reason
        return ApplyPlan(
            title=tile.title,
            warnings=list(compiled.warnings),
            missing_addons=missing,
            problem=f"{COPY['cannot-preview']}\n\n{exc}",
        )

    return ApplyPlan(
        title=tile.title,
        lines=diff.to_novice_lines(),
        warnings=list(compiled.warnings),
        missing_addons=missing,
        transaction=compiled.transaction,
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
        self.connect("destroy", self._on_destroy)

        self._banner = Adw.Banner(
            title=COPY["first-visit"],
            button_label=COPY["first-visit-dismiss"],
            revealed=self._prefs.should_show_banner(BANNER_ID),
        )
        self._banner.connect("button-clicked", self._on_banner_dismissed)
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

        clamp = Adw.Clamp(maximum_size=1000, margin_start=18, margin_end=18, margin_bottom=24)
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
        clamp = Adw.Clamp(maximum_size=1000, margin_start=18, margin_end=18, margin_bottom=24)
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
        button.set_child(self._tile_content(tile))
        button.set_tooltip_text(tile.description or tile.title)
        button.connect("clicked", lambda _button, t=tile: self._on_tile_activated(t))
        return button

    def _tile_content(self, tile: LookTile) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.append(build_preview(palette=tile.palette, pictures=list(tile.pictures)))

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
            description = Gtk.Inscription(
                text=tile.description, nat_lines=2, xalign=0, hexpand=True
            )
            description.add_css_class("dimmed")
            description.add_css_class("caption")
            box.append(description)
        return box

    # -- the apply flow ----------------------------------------------------

    def _on_tile_activated(self, tile: LookTile) -> None:
        if tile.broken:
            self._show_problem(tile)
            return
        plan = plan_apply(tile)
        self._show_preview(tile, plan)

    def _show_problem(self, tile: LookTile) -> None:
        body = COPY["broken-body"] + "\n\n" + "\n".join(f"• {line}" for line in tile.problems)
        dialog = Adw.AlertDialog(heading=COPY["broken-heading"], body=body)
        dialog.add_response("close", COPY["close"])
        dialog.present(self)

    def _show_preview(self, tile: LookTile, plan: ApplyPlan) -> None:
        dialog = Adw.AlertDialog(heading=tile.title, body=plan.body(), prefer_wide_layout=True)
        dialog.add_response("cancel", COPY["cancel"])
        if plan.missing_addons:
            dialog.add_response("addons", COPY["get-addons"])
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
            self._go_to_page("addons")

    def _apply(self, tile: LookTile, transaction: Transaction) -> None:
        """Apply a Look on a worker thread, narrating on the main one."""
        progress = Adw.AlertDialog(heading=tile.title, body=COPY["working"])
        progress.present(self)

        def report(_stage: Progress, text: str) -> None:
            GLib.idle_add(self._set_progress, progress, text)

        def work() -> None:
            try:
                outcome = transaction.apply(report)
            except TransactionError as error:
                GLib.idle_add(self._apply_failed, progress, error)
            except Exception as error:  # noqa: BLE001 - never leave the dialog spinning
                GLib.idle_add(
                    self._apply_failed, progress, TransactionError(str(error), rolled_back=True)
                )
            else:
                GLib.idle_add(self._apply_finished, progress, tile, outcome)

        threading.Thread(target=work, daemon=True, name="gtheme-apply-look").start()

    def _set_progress(self, dialog: Adw.AlertDialog, text: str) -> bool:
        if self._alive:
            dialog.set_body(text)
        return GLib.SOURCE_REMOVE

    def _apply_finished(self, dialog: Adw.AlertDialog, tile: LookTile, outcome: Any) -> bool:
        dialog.close()
        if not self._alive:
            return GLib.SOURCE_REMOVE
        point = getattr(outcome, "restore_point", None)
        self._toast(COPY["applied"].format(title=tile.title), undo_point=point)
        self.reload()
        return GLib.SOURCE_REMOVE

    def _apply_failed(self, dialog: Adw.AlertDialog, error: TransactionError) -> bool:
        dialog.close()
        if not self._alive:
            return GLib.SOURCE_REMOVE
        heading, body = failure_text(error)
        failed = Adw.AlertDialog(heading=heading, body=body)
        failed.add_response("close", COPY["close"])
        failed.present(self)
        return GLib.SOURCE_REMOVE

    # -- undo --------------------------------------------------------------

    def _undo(self, point_id: str) -> None:
        def work() -> None:
            result = restorepoints.apply_point(point_id)
            GLib.idle_add(self._undo_finished, result)

        threading.Thread(target=work, daemon=True, name="gtheme-undo-look").start()

    def _undo_finished(self, result: Any) -> bool:
        if not self._alive:
            return GLib.SOURCE_REMOVE
        warnings = list(getattr(result, "warnings", []))
        self._toast(COPY["undo-failed"] if warnings else COPY["undone"])
        self.reload()
        return GLib.SOURCE_REMOVE

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
        self._save_look(slug, typed)

    def _save_look(self, slug: str, title: str) -> None:
        def work() -> None:
            try:
                result = self.save_current_desktop(slug, title)
            except Exception as error:  # noqa: BLE001 - reported, never raised at a click
                GLib.idle_add(self._save_finished, title, None, error)
            else:
                GLib.idle_add(self._save_finished, title, result, None)

        threading.Thread(target=work, daemon=True, name="gtheme-save-look").start()

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

    def _save_finished(self, title: str, result: Any, error: Exception | None) -> bool:
        if not self._alive:
            return GLib.SOURCE_REMOVE
        if error is not None or result is None:
            failed = Adw.AlertDialog(
                heading=COPY["save-failed"], body=str(error) if error else COPY["save-failed"]
            )
            failed.add_response("close", COPY["close"])
            failed.present(self)
            return GLib.SOURCE_REMOVE
        self.reload()
        self._toast(COPY["saved"].format(title=title))
        notes = list(result.warnings)
        if notes:
            dialog = Adw.AlertDialog(
                heading=COPY["save-notes-heading"],
                body="\n".join(f"• {note}" for note in notes),
            )
            dialog.add_response("close", COPY["close"])
            dialog.present(self)
        return GLib.SOURCE_REMOVE

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
        box.append(build_preview(palette=None))

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
            description = Gtk.Inscription(
                text=entry.description, nat_lines=2, xalign=0, hexpand=True
            )
            description.add_css_class("dimmed")
            description.add_css_class("caption")
            box.append(description)

        button = Gtk.Button(has_frame=False, child=box)
        button.add_css_class("flat")
        button.connect("clicked", lambda _button, e=entry, h=here: self._on_community(e, h))
        return button

    def _on_community(self, entry: Any, here: bool) -> None:
        if here:
            self._stack.set_visible_child_name("installed")
            return
        dialog = Adw.AlertDialog(
            heading=entry.title or entry.name,
            body=f"{entry.description}\n\n{COPY['browse-not-yet']}".strip(),
        )
        dialog.add_response("close", COPY["close"])
        dialog.present(self)

    # -- small helpers -----------------------------------------------------

    def _on_banner_dismissed(self, banner: Adw.Banner) -> None:
        banner.set_revealed(False)
        self._prefs.mark_banner_seen(BANNER_ID)

    def _toast(self, text: str, *, undo_point: str | None = None) -> None:
        toast = Adw.Toast(title=text, timeout=8)
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


def build(window: Any) -> Gtk.Widget:
    """The factory named by ``ui.registry``'s manifest."""
    return LooksPage(window)
