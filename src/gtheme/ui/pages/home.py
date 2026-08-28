"""Home — what your desktop looks like right now, and the way back.

GNOME's own Appearance panel cannot show a person their current setup: on the
machine this was written on it is silent about ``adw-gtk3-dark``,
``Papirus-Dark`` and a custom text style, all of which are in force
(research/competitor-ux.md §1.6). Being able to *see* what you have is step
zero of changing it, so that is what this page is: one card that reads the
desktop back to you in words you already know, the two safety actions next to
it, and a way through to the pages that change each thing.

Nothing here is a control. Every value shown is read-only and lives on a page
of its own — a home screen that also edits is a home screen people are afraid
to open. The one thing this page *does* is safety: save a moment, or undo the
last change.

**No descriptor rows.** The card's rows are summaries of several settings at
once ("Light or dark" reads one key and shows a phrase), so they are not
registered with the row index: a search hit for "highlight colour" must land on
Colours & Style, where the control actually is, not on a read-only echo of it
here.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gtk  # noqa: E402

from ...core.backends import get_backend, has_session_bus  # noqa: E402
from ...core.gvariant import unquote as unquote_variant  # noqa: E402
from ...core.settings_backend import BackendError, SettingsBackend  # noqa: E402
from ..applyrunner import ApplyRunner  # noqa: E402
from ..widgets import a11y  # noqa: E402
from ..widgets.actions import action_row  # noqa: E402
from ..widgets.explainer import first_visit_banner  # noqa: E402
from . import colors as colors_page  # noqa: E402
from . import restore as restore_page  # noqa: E402
from .wallpaper import readable_name  # noqa: E402

__all__ = [
    "ACCENT_COLOURS",
    "ACCENT_NAMES",
    "BANNER_ID",
    "COPY",
    "HomePage",
    "addon_summary",
    "build",
    "current_wallpaper",
    "describe_accent",
    "describe_light_or_dark",
    "read",
    "summarise_setting",
]

#: The one-shot explainer shown the first time the app opens.
BANNER_ID = "first-visit-home"

#: Where each summary reads from. Two-part backend grammar: ``schema key``.
KEYS: dict[str, str] = {
    "wallpaper": "gsettings:org.gnome.desktop.background picture-uri",
    "wallpaper-dark": "gsettings:org.gnome.desktop.background picture-uri-dark",
    "light-or-dark": "gsettings:org.gnome.desktop.interface color-scheme",
    "highlight": "gsettings:org.gnome.desktop.interface accent-color",
    "app-style": "gsettings:org.gnome.desktop.interface gtk-theme",
    "icons": "gsettings:org.gnome.desktop.interface icon-theme",
    "pointer": "gsettings:org.gnome.desktop.interface cursor-theme",
    "text": "gsettings:org.gnome.desktop.interface font-name",
}

#: The highlight colours GNOME offers, named and painted. Both are *views* of
#: the one table on the Colours & Style page — the page that actually offers
#: them — because this card is a mirror and a mirror that has its own idea of
#: what the desktop supports is not a mirror (review-report L15). A colour this
#: version has never heard of still gets a readable name and an honest grey dot
#: rather than falling off the end of a dictionary.
ACCENT_NAMES: dict[str, str] = colors_page.ACCENT_LABELS
ACCENT_COLOURS: dict[str, str] = colors_page.ACCENT_HEXES

_LIGHT_OR_DARK: dict[str, str] = {
    "prefer-dark": "Dark",
    "prefer-light": "Light",
    "default": "Light",
}

#: Every sentence this page can say. Read by the jargon lint.
COPY: dict[str, str] = {
    "banner": (
        "This is how your desktop looks right now. Change one thing at a time "
        "from the list on the left, or pick a whole new look — and whatever you "
        "do, you can always come back to how it was."
    ),
    "card-title": "How your desktop looks right now",
    "card-description": "Everything here can be changed, one thing at a time.",
    "safety-title": "Your way back",
    "safety-description": (
        "gtheme saves how your desktop looks before it changes anything."
    ),
    "explore-title": "Change something",
    "row-background": "Background picture",
    "row-look": "Look",
    "no-look": "None — you have changed things one at a time",
    "row-light-or-dark": "Light or dark",
    "row-highlight": "Highlight colour",
    "row-app-style": "App style",
    "row-icons": "Icon set",
    "row-pointer": "Mouse pointer",
    "row-text": "Text style",
    "row-addons": "Add-ons",
    "unknown": "Not set",
    "unreadable": "Could not read this one",
    "addons-unavailable": "Can't check right now",
    "link-looks": "Pick a whole look",
    "link-looks-subtitle": "Background picture, colours, icons and add-ons, all at once.",
    "link-wallpaper": "Change the background picture",
    "link-wallpaper-subtitle": "Pick a different picture, or one for light and one for dark.",
    "link-colors": "Change the colours",
    "link-colors-subtitle": "Light or dark, and the highlight colour.",
    "link-addons": "Add extra features",
    "link-addons-subtitle": "Small extras you can switch on and off again.",
    "link-restore": "Go back to how it was",
    "link-restore-subtitle": "Every moment gtheme has saved for you.",
    "undo-button": "Undo last change",
    # What the card's picture is called for somebody who cannot see it. The
    # card is the app's opening statement — "this is how your desktop looks
    # right now" — and the picture in it carried no text of any kind.
    "picture-alt": "Your background picture: {name}",
    "picture-none": "No background picture is set",
}


# --------------------------------------------------------------------------
# reading the desktop
# --------------------------------------------------------------------------


def read(backend: SettingsBackend, name: str) -> str | None:
    """One summarised value, or None when it cannot be read.

    None is a real answer here and is shown as one. A missing setting means the
    desktop is not what this app expects, and inventing a plausible default
    would make the card lie about the machine it is describing.
    """
    key = KEYS.get(name)
    if key is None:
        return None
    try:
        return unquote_variant(backend.get(key))
    except BackendError:
        return None


def describe_light_or_dark(value: str | None) -> str:
    if value is None:
        return COPY["unreadable"]
    return _LIGHT_OR_DARK.get(value, value)


def describe_accent(value: str | None) -> str:
    if value is None:
        return COPY["unreadable"]
    return colors_page.accent_label(value) or COPY["unknown"]


def summarise_setting(value: str | None) -> str:
    """A theme or text-style name, shown as it is. Blank means nothing is set."""
    if value is None:
        return COPY["unreadable"]
    return value or COPY["unknown"]


def current_look_label() -> str:
    """The Look in use, named the way the person picking it saw it named.

    "None" here is a real state and a common one — a desktop somebody has
    changed one thing at a time on has no Look, and the row says which of the
    two it is rather than going blank.
    """
    from ...core.ledger import current_record

    record = current_record()
    label = record.get("label") or record.get("name")
    return str(label) if label else COPY["no-look"]


def current_wallpaper(backend: SettingsBackend, *, dark: bool | None = None) -> Path | None:
    """The picture file behind everything, or None when there is not one.

    ``picture-uri`` accepts anything — the settings store does not check that a
    file exists — so the answer is only returned when the file is really there.
    A slideshow is an XML file rather than a picture; it is returned all the
    same, and the caller falls back to an icon when no thumbnail can be made,
    which is the honest outcome for "the picture changes during the day".
    """
    names = ("wallpaper-dark", "wallpaper") if dark else ("wallpaper", "wallpaper-dark")
    for name in names:
        value = read(backend, name)
        if not value:
            continue
        parsed = urlparse(value)
        path = Path(unquote(parsed.path)) if parsed.scheme == "file" else Path(value)
        if path.is_file():
            return path
    return None


def addon_summary(shell: Any | None = None) -> str:
    """"4 of 15 switched on" — how many add-ons this desktop has.

    The desktop is asked directly, and read-only. When there is nothing to ask —
    no desktop running, a version that does not answer — the row says it cannot
    check rather than showing a confident zero.
    """
    extensions = _load_extensions(shell)
    if extensions is None:
        return COPY["addons-unavailable"]
    total = len(extensions)
    if not total:
        return "None yet"
    running = sum(1 for ext in extensions.values() if getattr(ext, "is_running", False))
    return f"{running} of {total} switched on"


def _load_extensions(shell: Any | None) -> dict[str, Any] | None:
    """The installed add-ons, or None when the desktop cannot be asked."""
    if shell is not None:
        try:
            return shell.load()
        except Exception:  # noqa: BLE001 - an unavailable desktop is not an error
            return None
    if not has_session_bus():
        return None
    try:
        from ...ego.shelldbus import GDBusShellProxy, ShellExtensions

        return ShellExtensions(GDBusShellProxy()).load()
    except Exception:  # noqa: BLE001 - the same, for the real desktop
        return None


# --------------------------------------------------------------------------
# the accent dot
# --------------------------------------------------------------------------

#: How big the dot is, in pixels, before scaling.
DOT_SIZE = 16


def dot_pixels(colour: str, size: int = DOT_SIZE) -> bytes:
    """An anti-aliased filled circle as raw RGBA bytes.

    Drawn by hand rather than with a drawing context on purpose: this is nine
    fixed colours in a sixteen-pixel square, and painting it into a texture has
    no toolkit dependency beyond the one that shows it. Coverage is sampled on a
    2x2 grid per pixel, which is enough for a dot this small to have a clean
    edge in both light and dark.
    """
    red, green, blue = (int(colour[i : i + 2], 16) for i in (1, 3, 5))
    centre = size / 2
    radius = centre - 0.5
    out = bytearray(size * size * 4)
    offsets = (0.25, 0.75)
    for y in range(size):
        for x in range(size):
            hits = sum(
                1
                for dy in offsets
                for dx in offsets
                if (x + dx - centre) ** 2 + (y + dy - centre) ** 2 <= radius * radius
            )
            if not hits:
                continue
            alpha = round(255 * hits / 4)
            index = (y * size + x) * 4
            # Premultiplied is not asked for; the straight format is used below.
            out[index : index + 4] = bytes((red, green, blue, alpha))
    return bytes(out)


def _accent_dot(accent: str | None) -> Gtk.Widget:
    """A filled circle in the highlight colour.

    The colour is the label — for anybody who can see it. The row it sits in
    already reads "Highlight colour: Blue", so for anybody who cannot, the dot
    is a picture of a word that has already been said, and it stays out of the
    way rather than being announced as an unnamed image (persona-report §2.10).
    """
    colour = colors_page.accent_hex(accent)
    image = Gtk.Image(valign=Gtk.Align.CENTER, pixel_size=DOT_SIZE)
    a11y.hide_from_screen_readers(image)
    try:
        from gi.repository import GLib

        data = GLib.Bytes.new(dot_pixels(colour))
        texture = Gdk.MemoryTexture.new(
            DOT_SIZE, DOT_SIZE, Gdk.MemoryFormat.R8G8B8A8, data, DOT_SIZE * 4
        )
        image.set_from_paintable(texture)
    except Exception:  # noqa: BLE001 - a missing dot must never cost the page
        image.set_from_icon_name("preferences-color-symbolic")
    return image


# --------------------------------------------------------------------------
# the page
# --------------------------------------------------------------------------


class HomePage(Adw.Bin):
    """The Home page: one card, two safety actions, four ways onward."""

    __gtype_name__ = "GthemeHomePage"

    def __init__(
        self,
        window: Any | None = None,
        *,
        backend: SettingsBackend | None = None,
        shell: Any | None = None,
        root: str | Path | None = None,
        thumbnails: bool = True,
    ) -> None:
        super().__init__()
        self.window = window
        self.backend = backend if backend is not None else get_backend()
        self.shell = shell
        self.root = root
        self._want_thumbnails = thumbnails

        self._page = Adw.PreferencesPage()
        self.set_child(self._page)
        # The card's picture is the first thing the app shows anybody, and it
        # was the largest unnamed image in the tree: a bare Gtk.Picture with no
        # alternative text at all (persona-report §2.10). The text is set again
        # in :meth:`_load_picture` once the picture's name is known; this is
        # what it says while there is nothing to show, and if the desktop has no
        # background picture at all it is the whole truth.
        self._picture = Gtk.Picture(
            height_request=180,
            content_fit=Gtk.ContentFit.COVER,
            css_classes=["card"],
            alternative_text=COPY["picture-none"],
        )
        self._rows: dict[str, Adw.ActionRow] = {}
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

        card = Adw.PreferencesGroup(
            title=COPY["card-title"], description=COPY["card-description"]
        )
        card.add(self._picture)
        for name, title in (
            ("look", COPY["row-look"]),
            ("light-or-dark", COPY["row-light-or-dark"]),
            ("highlight", COPY["row-highlight"]),
            ("app-style", COPY["row-app-style"]),
            ("icons", COPY["row-icons"]),
            ("pointer", COPY["row-pointer"]),
            ("text", COPY["row-text"]),
            ("addons", COPY["row-addons"]),
        ):
            row = Adw.ActionRow(title=title)
            self._rows[name] = row
            card.add(row)
        self._page.add(card)

        safety = Adw.PreferencesGroup(
            title=COPY["safety-title"], description=COPY["safety-description"]
        )
        safety.add(
            action_row(
                restore_page.COPY["save-title"],
                restore_page.COPY["save-subtitle"],
                restore_page.COPY["save-button"],
                self.save_restore_point,
                suggested=True,
            )
        )
        safety.add(
            action_row(
                restore_page.COPY["undo-title"],
                restore_page.COPY["undo-subtitle"],
                restore_page.COPY["undo-button"],
                self.undo_last_change,
            )
        )
        safety.add(self._link_row("restore", COPY["link-restore"], COPY["link-restore-subtitle"]))
        self._page.add(safety)

        explore = Adw.PreferencesGroup(title=COPY["explore-title"])
        for page_id, title, subtitle in (
            ("looks", COPY["link-looks"], COPY["link-looks-subtitle"]),
            ("wallpaper", COPY["link-wallpaper"], COPY["link-wallpaper-subtitle"]),
            ("colors", COPY["link-colors"], COPY["link-colors-subtitle"]),
            ("addons", COPY["link-addons"], COPY["link-addons-subtitle"]),
        ):
            explore.add(self._link_row(page_id, title, subtitle))
        self._page.add(explore)

        self.refresh()

    def _link_row(self, page_id: str, title: str, subtitle: str) -> Adw.ActionRow:
        row = Adw.ActionRow(title=title, subtitle=subtitle, activatable=True)
        row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        row.connect("activated", lambda *_a: self.open_page(page_id))
        return row

    # -- values ------------------------------------------------------------

    def refresh(self) -> None:
        """Re-read everything the card shows."""
        accent = read(self.backend, "highlight")
        self._set("look", current_look_label())
        self._set("light-or-dark", describe_light_or_dark(read(self.backend, "light-or-dark")))
        self._set("highlight", describe_accent(accent))
        self._set("app-style", summarise_setting(read(self.backend, "app-style")))
        self._set("icons", summarise_setting(read(self.backend, "icons")))
        self._set("pointer", summarise_setting(read(self.backend, "pointer")))
        self._set("text", summarise_setting(read(self.backend, "text")))
        self._set("addons", addon_summary(self.shell))

        highlight = self._rows.get("highlight")
        if highlight is not None:
            existing = getattr(self, "_dot", None)
            if existing is not None:
                highlight.remove(existing)
            dot = _accent_dot(accent)
            highlight.add_prefix(dot)
            self._dot = dot

        self._load_picture()

    def _set(self, name: str, text: str) -> None:
        row = self._rows.get(name)
        if row is not None:
            row.set_subtitle(text)

    def _load_picture(self) -> None:
        """Show the current background picture, thumbnail first.

        The stock GNOME 50 pictures are 4096-pixel JPEG-XL files; handing one
        straight to a picture widget is a visible stall on the app's first
        screen. The desktop's own thumbnail is looked up first and generated on
        a worker thread only if it is missing, so this returns immediately
        either way.
        """
        path = current_wallpaper(self.backend)
        if path is None:
            self._picture.set_paintable(None)
            self._picture.set_alternative_text(COPY["picture-none"])
            return
        self._picture.set_alternative_text(
            COPY["picture-alt"].format(name=readable_name(path))
        )
        if not self._want_thumbnails:
            self._picture.set_filename(str(path))
            return
        try:
            from ...system import thumbnails

            def ready(thumb: Path | None, _error: Exception | None) -> None:
                self._picture.set_filename(str(thumb if thumb is not None else path))

            thumbnails.request_thumbnail_async(path, ready)
        except Exception:  # noqa: BLE001 - a missing thumbnail is not a failure
            self._picture.set_filename(str(path))

    # -- actions -----------------------------------------------------------

    def open_page(self, page_id: str) -> None:
        """Go to another page of the app, if the window can be asked to."""
        show = getattr(self.window, "show_page", None)
        if callable(show):
            show(page_id)

    def _toast(self, text: str) -> None:
        toast = getattr(self.window, "toast", None)
        if callable(toast):
            toast(text)

    def _runner(self) -> ApplyRunner | None:
        """The window's runner, or None when this page is not in a window.

        The header-bar Undo button and the two rows below the card are the most
        prominent way into the engine the app has, and they used to call it
        straight from the click handler — the very pattern
        :mod:`gtheme.ui.applyrunner` was written to remove. They go through the
        window's one runner now, so they narrate, and so the window keeps
        repainting while several dozen settings are written.
        """
        runner = getattr(self.window, "runner", None)
        return runner if isinstance(runner, ApplyRunner) else None

    def save_restore_point(self) -> Any:
        """Save how the desktop looks right now, on the shared runner."""
        runner = self._runner()
        if runner is None:
            try:
                point = self._capture()
            except OSError as exc:
                self._save_failed(exc)
                return None
            return self._save_finished(point)
        runner.run(
            lambda _narrate: self._capture(),
            heading=restore_page.COPY["save-title"],
            starting=restore_page.COPY["save-subtitle"],
            on_done=self._save_finished,
            on_failed=self._save_failed,
        )
        return None

    def _capture(self) -> Any:
        """The engine half of saving a moment. No widgets, no thread."""
        return restore_page.create_restore_point(backend=self.backend, root=self.root)

    def _save_finished(self, point: Any) -> Any:
        self._toast(restore_page.COPY["saved"])
        self._changed()
        return point

    def _save_failed(self, error: Exception) -> None:
        self._toast(restore_page.save_failed_sentence(error))

    def undo_last_change(self) -> Any:
        """Go back to the most recent saved moment. Backs the header button."""
        runner = self._runner()
        if runner is None:
            return self._undo_finished(self._undo(None))
        runner.run(
            self._undo,
            heading=restore_page.COPY["working-heading"],
            starting=restore_page.COPY["working"],
            on_done=self._undo_finished,
            on_failed=self._undo_failed,
        )
        return None

    def _undo_failed(self, error: BaseException) -> None:
        """Say which of the two very different failures just happened.

        This handler used to throw the error away and toast "Nothing was
        changed. Your desktop is exactly as it was." — the one sentence that
        must never be said over a desktop nobody can vouch for. An unknown
        failure is an unknown desktop unless the error itself says otherwise
        (review-report H2), which is what ``rolled_back`` is for.
        """
        self._toast(
            restore_page.failure_sentence(
                str(error), rolled_back=bool(getattr(error, "rolled_back", False))
            )
        )

    def _undo(self, narrate: Any = None) -> Any:
        """The engine half of going back. Runs off the main loop, or inline."""

        def progress(*args: Any) -> None:
            text = next((value for value in args if isinstance(value, str) and value), "")
            if text and narrate is not None:
                narrate(text)

        return restore_page.undo_last_change(
            root=self.root, backend=self.backend, progress_cb=progress
        )

    def _undo_finished(self, landed: Any) -> Any:
        point, result = landed
        if point is None:
            self._toast(restore_page.COPY["undo-nothing"])
            return None
        if result is not None and result.warnings and result.transaction is None:
            # Whether the desktop came back with the failed undo is the
            # engine's answer to give, and the result carries it now
            # (review-report L1). The Undo page says the same two sentences
            # through the same function.
            self._toast(
                restore_page.failure_sentence(
                    result.warnings[0], rolled_back=result.rolled_back
                )
            )
            return result
        # Named, through the Undo page's own sentence. This card has no list of
        # moments under it, so "back the way it was" answered a question the
        # person had not asked and left the one they had — back to *when*? —
        # unanswered (U8).
        self._toast(restore_page.done_sentence(point))
        self._changed()
        return result

    def _changed(self) -> None:
        """The desktop moved. Everything on screen re-reads itself.

        The Undo page's list has a new entry in it, the card above has new
        values, and search has a new saved moment to find. This page knows
        about none of that; the window does.
        """
        after = getattr(self.window, "after_change", None)
        if callable(after):
            after()
        else:
            self.refresh()


def header_button(page: HomePage) -> Gtk.Button:
    """The "Undo last change" button this page wants in the window's header.

    The header bar belongs to the window, which this page does not own, so the
    button is built here and handed over. Wave 3 packs it; until then the same
    action is on the page itself, where nobody can fail to find it.
    """
    button = Gtk.Button(
        label=COPY["undo-button"],
        tooltip_text=restore_page.COPY["undo-subtitle"],
        icon_name="edit-undo-symbolic",
    )
    button.connect("clicked", lambda *_a: page.undo_last_change())
    return button


def build(window: Any | None = None, *, shell: Any = None, **kwargs: Any) -> Gtk.Widget:
    """Factory named by ``ui.registry``: the Home page.

    ``shell`` is named rather than left to ``**kwargs`` because that is how the
    window knows it can hand one over: it offers what it owns one of, and a
    factory takes what it names. Left out, the add-on line asks the desktop
    itself, which is what every test that builds this page relies on.
    """
    return HomePage(window, shell=shell, **kwargs)


def copy_strings() -> Iterable[tuple[str, str]]:
    """``(where, text)`` pairs for the jargon lint."""
    return [(f"home.{name}", text) for name, text in COPY.items()]
