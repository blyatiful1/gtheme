"""Colours & Style — light or dark, the highlight colour, and the two styles.

Four ideas, in the order a person meets them:

1. **Light or dark**, as two tiles you look at rather than a switch you read.
   This is the one control on the page that writes *two* settings: the desktop's
   own light/dark choice, and the style older apps use, which is a separate
   thing with a separate name for its dark version. Writing only the first is
   the classic split-brain bug — a dark desktop full of white windows — so the
   two go through one transaction, together or not at all.
2. **The highlight colour**, as nine coloured dots. The control is the preview.
   GNOME offers exactly these nine and no way to add a tenth; the page says so
   out loud rather than leaving a person hunting for a colour wheel that is not
   there.
3. **The two styles** — one for the insides of app windows, one for the bar at
   the top. The second needs a GNOME add-on that may be switched off, and when
   it is, the page offers the button that switches it on instead of naming the
   component that is missing.
4. **Ease of use** — stronger colours, less movement, shapes on switches. These
   are style choices as much as accessibility ones, and they belong where a
   person changing how their desktop looks will find them.
"""

from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gtk  # noqa: E402

from ...core.settings_backend import BackendError, SettingsBackend  # noqa: E402
from ...core.transaction import Op, SettingWrite  # noqa: E402
from ...panels.descriptor import Row  # noqa: E402
from ...system.themescan import (  # noqa: E402
    ThemeEntry,
    dark_variant_name,
    default_theme_roots,
    gtk_themes,
    scan_themes,
    shell_themes,
)
from ._style_common import (  # noqa: E402
    PageShell,
    apply_ops,
    picker_row,
    quote,
    toast,
    unquote,
    value_or_none,
)

__all__ = [
    "ACCENTS",
    "COLOR_SCHEME_KEY",
    "COPY",
    "GTK_THEME_KEY",
    "USER_THEME_UUID",
    "build",
    "dark_mode_ops",
    "is_dark",
]

#: Every sentence this page says, in one place, so the wording can be read as a
#: whole and linted as a whole. The reader has never used Linux.
COPY: dict[str, str] = {
    "banner": (
        "Everything here changes how your desktop looks straight away. "
        "Nothing is permanent — Undo & Restore Points puts any of it back."
    ),
    "mode-group": "Light or dark",
    "mode-description": (
        "Dark makes windows and menus dark. gtheme switches older apps over at "
        "the same time, so everything on screen matches."
    ),
    "light": "Light",
    "dark": "Dark",
    "mode-done": "Changed how your desktop is lit.",
    "accent-group": "Highlight colour",
    "accent-description": (
        "The colour used for selected items, switches and the main button in a "
        "window. GNOME offers these nine and no others — a colour of your own "
        "is not something this desktop can do yet."
    ),
    "styles-group": "Styles",
    "no-styles": "Only the style your computer came with is installed.",
    "topbar-group": "The bar at the top",
    "topbar-missing-addon": (
        "To use this, gtheme needs to turn on one GNOME add-on. It only lets "
        "you choose a style for the bar at the top."
    ),
    "topbar-turn-on": "Turn it on",
    "topbar-no-desktop": (
        "gtheme cannot reach your desktop to turn that on right now. Try again "
        "after you log out and back in."
    ),
    "topbar-none-installed": (
        "No styles for the top bar are installed yet. A Look can bring one with it."
    ),
    "a11y-group": "Ease of use",
    "a11y-description": (
        "Changes that make the desktop easier to read and calmer to look at."
    ),
}

COLOR_SCHEME_KEY = "gsettings:org.gnome.desktop.interface color-scheme"
GTK_THEME_KEY = "gsettings:org.gnome.desktop.interface gtk-theme"

#: The add-on the desktop insists on before it will use a downloaded style for
#: the bar at the top. Never rendered — it is only ever handed to the desktop.
USER_THEME_UUID = "user-theme@gnome-shell-extensions.gcampax.github.com"

#: The nine highlight colours, in GNOME's own order, with the exact colour
#: libadwaita paints for each (research/gnome-domains.md §1.1). The label is
#: what a person calls the colour; "slate" is not a colour anybody names.
ACCENTS: tuple[tuple[str, str, str], ...] = (
    ("blue", "Blue", "#3584e4"),
    ("teal", "Teal", "#2190a4"),
    ("green", "Green", "#3a944a"),
    ("yellow", "Yellow", "#c88800"),
    ("orange", "Orange", "#ed5b00"),
    ("red", "Red", "#e62d42"),
    ("pink", "Pink", "#d56199"),
    ("purple", "Purple", "#9141ac"),
    ("slate", "Grey", "#6f8396"),
)

_ACCENT_CSS = "\n".join(
    f".gtheme-accent-{name} {{ background: {hex_value}; }}" for name, _label, hex_value in ACCENTS
) + """
.gtheme-accent-dot {
    min-width: 26px;
    min-height: 26px;
    border-radius: 999px;
    padding: 0;
    border: 1px solid alpha(currentColor, 0.25);
}
.gtheme-mode-tile { padding: 6px; }
.gtheme-mode-sample {
    min-width: 132px;
    min-height: 74px;
    border-radius: 9px;
    border: 1px solid alpha(currentColor, 0.2);
}
.gtheme-mode-sample-light { background: #fafafa; }
.gtheme-mode-sample-dark { background: #222226; }
.gtheme-mode-bar {
    min-height: 12px;
    border-radius: 9px 9px 0 0;
}
.gtheme-mode-bar-light { background: #e6e6e6; }
.gtheme-mode-bar-dark { background: #131316; }
.gtheme-mode-window {
    min-width: 84px;
    min-height: 34px;
    border-radius: 6px;
    margin: 8px;
    border: 1px solid alpha(currentColor, 0.2);
}
.gtheme-mode-window-light { background: #ffffff; }
.gtheme-mode-window-dark { background: #303034; }
"""

_CSS_INSTALLED = False


def _install_css() -> None:
    """Add this page's colours to the display once, and only once."""
    global _CSS_INSTALLED
    if _CSS_INSTALLED:
        return
    display = Gdk.Display.get_default()
    if display is None:  # pragma: no cover - no display, no styling to do
        return
    provider = Gtk.CssProvider()
    provider.load_from_string(_ACCENT_CSS)
    Gtk.StyleContext.add_provider_for_display(
        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    _CSS_INSTALLED = True


# --------------------------------------------------------------------------
# light and dark: the two-key change
# --------------------------------------------------------------------------


def is_dark(color_scheme: str | None) -> bool:
    """Whether a stored colour-scheme value means dark."""
    return color_scheme is not None and unquote(color_scheme) == "prefer-dark"


def dark_mode_ops(
    backend: SettingsBackend,
    dark: bool,
    installed: set[str] | None = None,
) -> list[Op]:
    """The whole light/dark change, as operations for one transaction.

    Two keys, because the desktop keeps its light/dark choice and the style
    older apps use in two different places, and the dark version of a style is
    a *different style* rather than a flag on the same one. Change only the
    first and a person gets a dark desktop full of glaring white windows, with
    nothing in any settings app explaining why.

    The second write only happens when the counterpart style is really
    installed — writing the name of something that is not there would leave
    every older app falling back to a default, which looks like gtheme broke
    them.

    Args:
        backend: read the current style through this.
        dark: what the person just chose.
        installed: style names present on this computer. Scanned when omitted.

    Returns:
        One or two operations, in the order they will be carried out.
    """
    ops: list[Op] = [
        SettingWrite(
            COLOR_SCHEME_KEY,
            quote("prefer-dark" if dark else "default"),
            component="colors",
        )
    ]
    raw = value_or_none(backend, GTK_THEME_KEY)
    if raw is None:
        return ops
    current = unquote(raw)
    if installed is None:
        installed = {entry.name for entry in scan_themes(default_theme_roots())}
    already = current.endswith("-dark")
    if already == dark:
        return ops
    counterpart = dark_variant_name(current, installed)
    if counterpart is not None:
        ops.append(SettingWrite(GTK_THEME_KEY, quote(counterpart), component="colors"))
    return ops


def _mode_sample(dark: bool) -> Gtk.Widget:
    """A small, honest drawing of what the choice looks like.

    Not a screenshot and not a rendered theme: a bar, a window and a shadow, in
    the two shades the choice actually produces. Enough for the eye to pick the
    one it wants without reading either label.
    """
    suffix = "dark" if dark else "light"
    outer = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        css_classes=["gtheme-mode-sample", f"gtheme-mode-sample-{suffix}"],
    )
    outer.append(Gtk.Box(css_classes=["gtheme-mode-bar", f"gtheme-mode-bar-{suffix}"]))
    window = Gtk.Box(css_classes=["gtheme-mode-window", f"gtheme-mode-window-{suffix}"])
    window.set_hexpand(False)
    outer.append(window)
    return outer


class _ModeChooser:
    """The two tiles, kept in step with what the desktop actually holds."""

    def __init__(self, window: Any, backend: SettingsBackend, shell: PageShell) -> None:
        self.window = window
        self.backend = backend
        self.shell = shell
        self.busy = False

        self.box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
            halign=Gtk.Align.CENTER,
            margin_top=6,
            margin_bottom=6,
        )
        self.light = self._tile(COPY["light"], dark=False)
        self.dark = self._tile(COPY["dark"], dark=True)
        self.dark.set_group(self.light)
        self.box.append(self.light)
        self.box.append(self.dark)
        self.refresh()
        self.light.connect("toggled", self._on_toggled)
        self.dark.connect("toggled", self._on_toggled)
        # These two tiles are the one control on this page that is not a
        # descriptor row, so nothing in the row index knows they exist. Without
        # this line the only thing that ever re-read them was toggling them:
        # a dark Look applied from the Looks page, or dark mode flipped in the
        # desktop's own Settings, left the Light tile looking selected on a
        # dark desktop. Both of those paths end in ``run_notices``.
        shell.notices.append(self.refresh)

    def _tile(self, label: str, *, dark: bool) -> Gtk.ToggleButton:
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        content.append(_mode_sample(dark))
        content.append(Gtk.Label(label=label))
        button = Gtk.ToggleButton(child=content, css_classes=["flat", "gtheme-mode-tile"])
        button.set_tooltip_text(label)
        button.dark = dark  # type: ignore[attr-defined]
        return button

    def refresh(self) -> None:
        """Show what the desktop holds, without writing anything."""
        self.busy = True
        try:
            dark = is_dark(value_or_none(self.backend, COLOR_SCHEME_KEY))
            self.dark.set_active(dark)
            self.light.set_active(not dark)
        finally:
            self.busy = False

    def _on_toggled(self, button: Gtk.ToggleButton) -> None:
        if self.busy or not button.get_active():
            return
        wanted = bool(getattr(button, "dark", False))
        ops = dark_mode_ops(self.backend, wanted)
        if apply_ops(self.window, ops, done=COPY["mode-done"]):
            # The same style key has a picker of its own further down the page.
            # Two controls over one setting have to agree at all times.
            self.shell.refresh("org.gnome.desktop.interface:gtk-theme")
        self.refresh()


# --------------------------------------------------------------------------
# the highlight colour
# --------------------------------------------------------------------------


def _accent_row(backend: SettingsBackend, row: Row) -> tuple[Adw.PreferencesRow, Any]:
    """Nine dots. Picking a colour is done by looking at it, not reading it."""
    _install_css()
    widget = Adw.ActionRow(title=row.title, subtitle=row.subtitle)
    dots = Gtk.Box(
        orientation=Gtk.Orientation.HORIZONTAL, spacing=6, valign=Gtk.Align.CENTER
    )
    widget.add_suffix(dots)

    key = "gsettings:org.gnome.desktop.interface accent-color"
    guard = {"busy": False}
    buttons: dict[str, Gtk.ToggleButton] = {}
    first: Gtk.ToggleButton | None = None

    def choose(name: str) -> None:
        if guard["busy"]:
            return
        try:
            backend.set(key, quote(name))
        except BackendError:
            return
        refresh()

    for name, label, _hex_value in ACCENTS:
        button = Gtk.ToggleButton(
            css_classes=["gtheme-accent-dot", f"gtheme-accent-{name}"],
            tooltip_text=label,
            valign=Gtk.Align.CENTER,
        )
        button.update_property([Gtk.AccessibleProperty.LABEL], [label])
        if first is None:
            first = button
        else:
            button.set_group(first)
        button.connect(
            "toggled",
            lambda b, n=name: choose(n) if b.get_active() else None,
        )
        buttons[name] = button
        dots.append(button)

    def refresh() -> None:
        guard["busy"] = True
        try:
            raw = value_or_none(backend, key)
            current = unquote(raw) if raw is not None else ""
            for name, button in buttons.items():
                button.set_active(name == current)
        finally:
            guard["busy"] = False

    refresh()
    return widget, refresh


# --------------------------------------------------------------------------
# the style pickers
# --------------------------------------------------------------------------


def _app_style_picker(
    shell: PageShell, group: Adw.PreferencesGroup, themes: list[ThemeEntry]
) -> None:
    row = shell.descriptor("org.gnome.desktop.interface:gtk-theme")
    if row is None:  # pragma: no cover - the corpus always has this
        return
    options = [(entry.name, entry.name) for entry in gtk_themes(themes)]
    widget, refresh = picker_row(shell.backend, row, options)
    group.add(widget)
    shell.register(row, widget, refresh)
    if len(options) <= 1:
        group.set_description(COPY["no-styles"])


def _user_theme_is_on(backend: SettingsBackend) -> bool:
    """Is the add-on that allows a top-bar style switched on?

    Read from the list of add-ons the desktop is told to run, not asked over
    D-Bus: this has to answer instantly while a page is being built, and it has
    to answer at all when there is no desktop to ask.
    """
    from ...core.gvariant import parse_string_list

    raw = value_or_none(backend, "gsettings:org.gnome.shell enabled-extensions")
    if raw is None:
        return False
    return USER_THEME_UUID in (parse_string_list(raw) or [])


def _turn_on_user_theme(window: Any) -> None:
    """Ask the desktop to switch the add-on on, and say what happened.

    The desktop answers False for an add-on it has not scanned, which is not a
    failure — it means "after you log back in". The words for both come from
    the add-on library, so this page and the Add-ons page cannot drift apart.
    """
    from ...ego.install import COPY as EGO_COPY
    from ...ego.shelldbus import EnableResult, GDBusShellProxy, ShellError, ShellExtensions

    shell = ShellExtensions(GDBusShellProxy())
    try:
        shell.load()
        outcome = shell.enable(USER_THEME_UUID)
    except ShellError:
        toast(window, COPY["topbar-no-desktop"])
        return
    finally:
        try:
            shell.close()
        except ShellError:  # pragma: no cover - closing a proxy that never opened
            pass
    if outcome is EnableResult.ENABLED_NOW:
        toast(window, EGO_COPY["turned-on"])
    elif outcome is EnableResult.NEEDS_RELOGIN:
        toast(window, EGO_COPY["turn-on-after-login"])
    else:
        toast(window, EGO_COPY["would-not-start"])


def _top_bar_group(shell: PageShell, themes: list[ThemeEntry]) -> None:
    row = shell.descriptor("org.gnome.shell.extensions.user-theme:name")
    if row is None:  # pragma: no cover - the corpus always has this
        return
    # The honest caveat, straight from the descriptor: a top bar style is one
    # design and will not follow light and dark the way the rest does.
    group = shell.group(COPY["topbar-group"], row.warn)

    if not _user_theme_is_on(shell.backend):
        banner = Adw.Banner(
            title=COPY["topbar-missing-addon"],
            button_label=COPY["topbar-turn-on"],
            revealed=True,
        )
        banner.set_button_style(Adw.BannerButtonStyle.SUGGESTED)

        def turn_on(*_args: Any) -> None:
            _turn_on_user_theme(shell.window)
            banner.set_revealed(False)

        banner.connect("button-clicked", turn_on)
        shell.container.insert_child_after(banner, shell.banner)

    options = [(entry.name, entry.name) for entry in shell_themes(themes)]
    widget, refresh = picker_row(
        shell.backend, row, options, empty_label="The one the desktop came with"
    )
    group.add(widget)
    shell.register(row, widget, refresh)
    if not options:
        widget.set_subtitle(COPY["topbar-none-installed"])


# --------------------------------------------------------------------------
# the page
# --------------------------------------------------------------------------


def build(window: Any) -> Gtk.Widget:
    """Build the Colours & Style page."""
    _install_css()
    shell = PageShell(
        window,
        "colors",
        banner_id="first-visit-colors",
        banner_text=COPY["banner"],
    )
    themes = scan_themes(default_theme_roots())

    mode_group = Adw.PreferencesGroup(
        title=COPY["mode-group"], description=COPY["mode-description"]
    )
    shell.page.add(mode_group)
    mode_group.add(_ModeChooser(window, shell.backend, shell).box)

    accent = shell.descriptor("org.gnome.desktop.interface:accent-color")
    if accent is not None:
        accent_group = shell.group(COPY["accent-group"], COPY["accent-description"])
        widget, refresh = _accent_row(shell.backend, accent)
        accent_group.add(widget)
        shell.register(accent, widget, refresh)

    styles = shell.group(COPY["styles-group"])
    _app_style_picker(shell, styles, themes)
    _top_bar_group(shell, themes)

    ease = shell.group(COPY["a11y-group"], COPY["a11y-description"])
    for descriptor_id in (
        "org.gnome.desktop.a11y.interface:high-contrast",
        "org.gnome.desktop.a11y.interface:reduced-motion",
        "org.gnome.desktop.a11y.interface:show-status-shapes",
    ):
        shell.add_descriptor_row(ease, descriptor_id)

    advanced = shell.advanced(ease)
    shell.add_descriptor_row(advanced, "org.gnome.desktop.interface:overlay-scrolling")

    return shell.finish()
