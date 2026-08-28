"""Fonts & Text — which lettering the desktop uses, how big, and how sharp.

Everything on this page is shown in the lettering it is about. A font name in a
dropdown is the purest form of the failure this app exists to fix: it asks a
person to imagine the result of a choice they could simply be shown.

Two settings here are inert until a *second* setting is changed first, and both
are handled out loud rather than quietly:

* **Text sharpness and smoothing** do nothing while the desktop is choosing text
  rendering for itself. The row library writes that second key before the one
  the person touched — and this page puts the descriptor's own sentence about it
  on screen, word for word, so the change is never a surprise.
* **The lettering for window headings** does nothing while headings follow the
  main text style. That one is two writes in one transaction, together or not at
  all, because a heading font set while headings still follow the main style is
  a control that visibly moves and changes nothing.

The variable-weight suffix (the ``@wght=460`` in this desktop's own text style)
survives every write. A picker that dropped it would silently reset the weight
of every letter on screen, and nothing in any settings app would explain why.
"""

from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk, Pango  # noqa: E402

from ...core.settings_backend import SettingsBackend  # noqa: E402
from ...core.transaction import Op, SettingWrite  # noqa: E402
from ...panels.descriptor import Row  # noqa: E402
from ...system.fontscan import parse_font_description  # noqa: E402
from ..widgets.rows import attach_reset, key_for, write_value  # noqa: E402
from ._style_common import (  # noqa: E402
    PageShell,
    apply_ops,
    quote,
    unquote,
    value_or_none,
)

__all__ = [
    "COPY",
    "FONT_RENDERING_KEY",
    "PREVIEW_TEXT",
    "TITLEBAR_FONT_KEY",
    "TITLEBAR_USES_SYSTEM_FONT_KEY",
    "build",
    "font_choice",
    "needs_manual_rendering",
    "window_heading_font_ops",
]


#: Every sentence this page says, in one place, so it can be read and linted as
#: a whole. The sentences about *changing a second setting first* are NOT here:
#: those come from the descriptor corpus, word for word, so that the page and
#: the data can never drift into saying two different things.
COPY: dict[str, str] = {
    "banner": (
        "Every line below is shown in the lettering it changes. Undo & Restore "
        "Points puts any of this back."
    ),
    "lettering-group": "Lettering",
    "lettering-description": (
        "Which letters the desktop draws with. Each line shows you the one it "
        "is about."
    ),
    "choose": "Change",
    "size-group": "Text size",
    "size-description": (
        "Makes every piece of writing on the desktop bigger or smaller at once. "
        "The line below grows and shrinks with it."
    ),
    "sharpness-group": "Sharpness and smoothing",
    "sharpness-description": (
        "How firmly letters are pressed onto the dots of your screen. Most "
        "people never touch these, and the desktop usually gets it right."
    ),
    "heading-done": "Changed the lettering used for window headings.",
    "not-readable": "gtheme cannot read this setting on this computer.",
}

#: What the previews spell out. A pangram, so every letter is on screen, and a
#: short one, so it fits a narrow window.
PREVIEW_TEXT = "The quick brown fox jumps over the lazy dog"

FONT_RENDERING_KEY = "gsettings:org.gnome.desktop.interface font-rendering"
TITLEBAR_FONT_KEY = "gsettings:org.gnome.desktop.wm.preferences titlebar-font"
TITLEBAR_USES_SYSTEM_FONT_KEY = (
    "gsettings:org.gnome.desktop.wm.preferences titlebar-uses-system-font"
)

#: The three lettering choices, in the order they matter to a person.
FONT_ROW_IDS: tuple[str, ...] = (
    "org.gnome.desktop.interface:font-name",
    "org.gnome.desktop.interface:document-font-name",
    "org.gnome.desktop.interface:monospace-font-name",
)


# --------------------------------------------------------------------------
# keeping the variable-weight suffix
# --------------------------------------------------------------------------


def font_choice(current: str | None, chosen: str) -> str:
    """The value to store when a person picks ``chosen`` over ``current``.

    This desktop's own text style is ``Adwaita Sans 11 @wght=460``: a family, a
    size, and a *variable axis* pinning the weight between the named weights a
    font offers. Font choosers do not always hand that suffix back — and a value
    written without it is not the same lettering, it is the font's default
    weight, everywhere, with nothing on screen saying why it changed.

    So the suffix survives: when the family is unchanged and the new value
    carries no axes of its own, the old ones are carried across. When the person
    picks a different family, the old axes are dropped — a weight pinned for one
    family means nothing in another.

    Returns:
        A Pango font description string. Picking the same font back out of a
        chooser round-trips to the identical string, suffix included.
    """
    if current is None:
        return chosen
    before = parse_font_description(current)
    after = parse_font_description(chosen)
    if after.axes or not before.axes:
        return chosen
    if after.family_and_style != before.family_and_style:
        return chosen
    spec = after
    for axis, value in before.axes:
        spec = spec.with_axis(axis, value)
    return spec.to_pango_string()


def needs_manual_rendering(font_rendering: str | None) -> bool:
    """Is the desktop still choosing text rendering for itself?

    While it is, sharpness and smoothing do nothing at all. The row library
    writes the second key first when somebody changes one of them; this is what
    decides whether the page says so beforehand.
    """
    if font_rendering is None:
        return False
    return unquote(font_rendering) != "manual"


def window_heading_font_ops(chosen: str) -> list[Op]:
    """Both writes the window-heading lettering needs, in order.

    Headings follow the main text style until told not to. Writing the heading
    font alone leaves a control that moves and does nothing; writing them in two
    separate transactions leaves a moment where headings have stopped following
    the main style and have no style of their own yet.
    """
    return [
        SettingWrite(TITLEBAR_USES_SYSTEM_FONT_KEY, "false", component="fonts"),
        SettingWrite(TITLEBAR_FONT_KEY, quote(chosen), component="fonts"),
    ]


# --------------------------------------------------------------------------
# previews
# --------------------------------------------------------------------------


def preview_label(font: str | None, text: str = PREVIEW_TEXT) -> Gtk.Label:
    """A line of real text, drawn in the lettering it describes."""
    label = Gtk.Label(
        label=text,
        xalign=0.0,
        ellipsize=Pango.EllipsizeMode.END,
        max_width_chars=40,
    )
    set_preview_font(label, font)
    return label


def set_preview_font(label: Gtk.Label, font: str | None) -> None:
    """Draw ``label`` in ``font``, or in whatever the app uses when there is none."""
    if not font:
        label.set_attributes(None)
        return
    attributes = Pango.AttrList()
    attributes.insert(Pango.attr_font_desc_new(Pango.FontDescription.from_string(font)))
    label.set_attributes(attributes)


# --------------------------------------------------------------------------
# the lettering rows
# --------------------------------------------------------------------------


def _font_row(
    shell: PageShell,
    row: Row,
    *,
    write: Any = None,
) -> tuple[Adw.ActionRow, Any]:
    """One lettering choice: the name, a live preview, and a Change button.

    Args:
        shell: the page being built.
        row: the descriptor.
        write: how to store a chosen value, given the new description string.
            Defaults to an ordinary single write; the window-heading row passes
            its two-key transaction instead.
    """
    backend: SettingsBackend = shell.backend
    key = key_for(row)
    widget = Adw.ActionRow(title=row.title, subtitle=row.subtitle)
    preview = preview_label(None)
    button = Gtk.Button(label=COPY["choose"], valign=Gtk.Align.CENTER)
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, valign=Gtk.Align.CENTER)
    box.append(preview)
    box.append(button)
    widget.add_suffix(box)
    widget.set_activatable_widget(button)

    def current() -> str | None:
        raw = value_or_none(backend, key)
        return unquote(raw) if raw is not None else None

    state: list[Any] = [lambda: None]

    def refresh() -> None:
        font = current()
        set_preview_font(preview, font)
        preview.set_text(font or PREVIEW_TEXT)
        if font is None:
            widget.set_sensitive(False)
            widget.set_subtitle(COPY["not-readable"])

    def store(chosen: str) -> None:
        value = font_choice(current(), chosen)
        if write is not None:
            write(value)
        elif not write_value(
            backend, key, quote(value), widget=widget, refresh=refresh, component=row.id
        ):
            return
        state[0]()

    button.connect("clicked", lambda *_a: _ask_for_a_font(button, row, current(), store))
    refresh()
    state[0] = refresh
    if row.reset and row.key is not None:
        state[0] = attach_reset(backend, row, widget, refresh)
    return widget, state[0]


def _ask_for_a_font(
    origin: Gtk.Widget,
    row: Row,
    current: str | None,
    on_chosen: Any,
) -> None:
    """Open the system's font chooser and hand back what was picked.

    The chooser is the platform's own, deliberately: it lists what is really
    installed, previews as you scroll, and is the same window every other app
    on this desktop opens for the same job.
    """
    dialog = Gtk.FontDialog(title=row.title)
    initial = Pango.FontDescription.from_string(current) if current else None

    def done(source: Gtk.FontDialog, result: Any) -> None:
        try:
            description = source.choose_font_finish(result)
        except Exception:  # noqa: BLE001 - cancelled, or no chooser available
            return
        if description is not None:
            on_chosen(description.to_string())

    root = origin.get_root()
    parent = root if isinstance(root, Gtk.Window) else None
    dialog.choose_font(parent, initial, None, done)


# --------------------------------------------------------------------------
# the page
# --------------------------------------------------------------------------


def _sharpness_group(shell: PageShell) -> None:
    group = shell.group(COPY["sharpness-group"], COPY["sharpness-description"])
    hinting = shell.descriptor("org.gnome.desktop.interface:font-hinting")

    # The consent notice, word for word from the descriptor. The row library
    # writes that second setting when somebody changes one of these; saying so
    # first is what turns a silent extra write into a change the person agreed
    # to. It disappears once the desktop has stopped choosing for itself.
    if hinting is not None and hinting.requires_first:
        explain = hinting.requires_first[0].explain
        banner = Adw.Banner(title=explain, revealed=False)
        shell.container.insert_child_after(banner, shell.banner)

        def follow() -> None:
            banner.set_revealed(
                needs_manual_rendering(value_or_none(shell.backend, FONT_RENDERING_KEY))
            )

        follow()
        shell.notices.append(follow)

    for descriptor_id in (
        "org.gnome.desktop.interface:font-hinting",
        "org.gnome.desktop.interface:font-antialiasing",
    ):
        shell.add_descriptor_row(group, descriptor_id)

    advanced = shell.advanced(group)
    shell.add_descriptor_row(advanced, "org.gnome.desktop.interface:font-rgba-order")

    heading = shell.descriptor("org.gnome.desktop.wm.preferences:titlebar-font")
    if heading is not None:
        if heading.requires_first:
            note = Adw.ActionRow(
                title=heading.requires_first[0].explain,
                sensitive=False,
                css_classes=["dimmed"],
            )
            note.set_title_lines(3)
            advanced.add_row(note)
        widget, refresh = _font_row(
            shell,
            heading,
            write=lambda value: apply_ops(
                shell.window, window_heading_font_ops(value), done=COPY["heading-done"]
            ),
        )
        advanced.add_row(widget)
        shell.register(heading, widget, refresh)


def build(window: Any) -> Gtk.Widget:
    """Build the Fonts & Text page."""
    shell = PageShell(
        window,
        "fonts",
        banner_id="first-visit-fonts",
        banner_text=COPY["banner"],
    )

    lettering = shell.group(COPY["lettering-group"], COPY["lettering-description"])
    for descriptor_id in FONT_ROW_IDS:
        row = shell.descriptor(descriptor_id)
        if row is None:  # pragma: no cover - the corpus always has these
            continue
        widget, refresh = _font_row(shell, row)
        lettering.add(widget)
        shell.register(row, widget, refresh)

    size = shell.group(COPY["size-group"], COPY["size-description"])
    shell.add_descriptor_row(size, "org.gnome.desktop.interface:text-scaling-factor")
    size.add(
        Adw.PreferencesRow(
            activatable=False,
            focusable=False,
            child=_scaled_preview(shell),
        )
    )

    _sharpness_group(shell)
    return shell.finish()


def _scaled_preview(shell: PageShell) -> Gtk.Widget:
    """A line of text that grows and shrinks with the text-size slider.

    Reading the scaling factor and applying it here rather than trusting the
    app's own text to change: the desktop applies text scaling on the next
    start for some apps, and a preview that only updated after a restart would
    be worse than none.
    """
    label = preview_label(None)
    label.set_margin_start(12)
    label.set_margin_end(12)
    label.set_margin_top(6)
    label.set_margin_bottom(6)

    def follow() -> None:
        raw = value_or_none(shell.backend, "gsettings:org.gnome.desktop.interface font-name")
        font = unquote(raw) if raw is not None else None
        scale_text = value_or_none(
            shell.backend, "gsettings:org.gnome.desktop.interface text-scaling-factor"
        )
        try:
            scale = float(scale_text) if scale_text is not None else 1.0
        except ValueError:
            scale = 1.0
        spec = parse_font_description(font) if font else None
        if spec is not None and spec.size is not None:
            try:
                spec = spec.with_size(f"{float(spec.size) * scale:.1f}")
            except ValueError:  # pragma: no cover - a size that is not a number
                pass
        set_preview_font(label, spec.to_pango_string() if spec is not None else None)
        label.set_text(PREVIEW_TEXT)

    follow()
    shell.notices.append(follow)
    return label
