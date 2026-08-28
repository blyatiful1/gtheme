"""Terminal — giving the command window, the prompt and the little tools a look.

One card per program that is *actually on this computer*. A list of ten
terminals with nine greyed out is a list of things the user cannot do, so
:func:`gtheme.terminal.installed` decides what appears and nothing else does.

Three things this page refuses to fudge.

**When you will see it.** Every adapter carries its own answer — ghostty does
not reload its own settings, alacritty does within a second, ptyxis changes
while you watch, fastfetch is not running at all. Those sentences are written
by the adapters and rendered here **verbatim**, under the card they belong to.
Telling somebody their terminal changed when the window in front of them has
not is the small lie that makes a person stop believing the whole app.

**Whose settings these are.** On the machine this was built on,
``~/.config/ghostty`` is a link into a separate project the user maintains by
hand. The adapter reports that and refuses to write; this page shows the
adapter's own notice and offers to take the folder over — a deliberate,
recorded, undoable act. It never finds out by trying: calling ``apply`` to see
whether it fails would be exactly the write the refusal exists to prevent.

**Where the colours come from.** A look's colours come from a Look. With no
Look applied there is no palette, and the button says so and stays off rather
than inventing one. A Look whose palette holds something that is not a colour
is not a page that cannot be opened: the page falls back to the same "no
colours from this Look" branch it already has (review-report M11).

**Nothing is written from here.** The button collects what each program wants
changed and hands all of it to one transaction, so the terminal look is
recorded, claimed, undoable and rolled back as one thing like every other
change in this app (review-report H8). It runs on the shared runner, because
copying files and writing settings on the main loop is how a window stops
repainting mid-change.
"""

from __future__ import annotations

import shutil
from typing import Any

from ...core import applog
from ...core.backends import get_backend
from ...core.gvariant import quote, unquote
from ...core.settings_backend import BackendError
from ...panels.descriptor import Choice, Row, WidgetKind
from ...panels.schema_probe import SchemaProbe
from ...terminal import ApplyReport, apply_all, installed
from ...terminal.ghostty import FOREIGN_NOTICE, GhosttyAdapter
from ...terminal.model import Palette, is_colour, read_palette
from ..search import build_indexed_rows, escape_markup, page_rows, probe_built_rows

__all__ = [
    "COPY",
    "KNOWN_TERMINAL_APPS",
    "applied_look",
    "build",
    "installed_terminal_apps",
    "palette_from_look",
]

PAGE_ID = "terminal"

#: The one-shot explainer key in ``prefs.json``.
BANNER_ID = "first-visit-terminal"

#: The setting that says which app opens when something needs a command window.
TERMINAL_APP_ROW = "org.gnome.desktop.default-applications.terminal:exec"

COPY: dict[str, str] = {
    "banner": (
        "A command window is the black window you type instructions into. gtheme "
        "can give the ones you have the same colours as the look you are using. "
        "It never changes what they do — only how they look."
    ),
    "colours-title": "Colours to use",
    "colours-none": (
        "No look is applied yet, so gtheme has no set of colours to hand out. "
        "Pick a look first and this page will offer its colours here."
    ),
    "colours-from": "The colours of the look you are using: {name}.",
    "colours-swatch": "Background, text and highlight, as they will appear.",
    "apply": "Give these programs those colours",
    "apply-none": "Nothing on this computer to give colours to.",
    "include": "Include this one",
    "include-subtitle": "Uncheck to leave this program exactly as it is.",
    "using-now": "Using now",
    "using-unknown": "gtheme cannot tell which colours this is using.",
    "done": "Done. {when}",
    "failed": "Not changed. {why}",
    "working-heading": "Giving these programs those colours",
    "working": "gtheme is saving how things are now, then changing them.",
    "some-changed": "{done} of {total} changed.",
    "crashed": (
        "gtheme could not make that change. Nothing on this page was changed. "
        "The details are in gtheme's own log."
    ),
    "take-over": "Take them over",
    "undo-take-over": "Put the folder link back",
    "taken-over": (
        "gtheme is now looking after these settings. The original folder link was "
        "saved and can be put back at any time."
    ),
    "link-restored": "The original folder link is back. gtheme will not write here again.",
    "app-title": "Which command window opens",
    "app-description": (
        "The app your desktop opens when something needs a command window. Only "
        "apps that are on this computer are offered."
    ),
    "elsewhere-title": "Not part of this app",
    "spicetify": "Changing how Spotify itself looks is not managed by this app.",
    "nothing-title": "No command window found",
    "nothing-body": (
        "gtheme could not find a command window, a prompt or a small tool it knows "
        "how to restyle on this computer. Install one and it will appear here."
    ),
}

#: Programs that can be the desktop's command window, and what to call them.
#: Only the ones actually present are offered — the setting takes any text at
#: all, and a name that is not there is a setting that silently does nothing.
KNOWN_TERMINAL_APPS: tuple[tuple[str, str], ...] = (
    ("ghostty", "Ghostty"),
    ("ptyxis", "Ptyxis"),
    ("kgx", "Console"),
    ("gnome-terminal", "Terminal"),
    ("alacritty", "Alacritty"),
    ("kitty", "Kitty"),
    ("foot", "Foot"),
    ("wezterm", "WezTerm"),
    ("xterm", "XTerm"),
)

#: The eight ANSI colours, in the order every palette lists them.
_ANSI_NAMES: tuple[str, ...] = (
    "black",
    "red",
    "green",
    "yellow",
    "blue",
    "magenta",
    "cyan",
    "white",
)


# ---------------------------------------------------------------------------
# where the colours come from
# ---------------------------------------------------------------------------


def applied_look(looks: list[Any] | None = None) -> Any | None:
    """The Look currently in use, or None when gtheme did not apply one.

    Which Look is in use is recorded when it is applied, and read back here.

    It used to be *guessed*, by intersecting the ownership ledger's keys with
    the list of installed Looks and accepting the answer only when exactly one
    matched. That guess was wrong in three ways at once. The ledger is keyed by
    a Look's title and the match was against its folder name, so any Look whose
    title differs from its name — which is most of them — never matched at all.
    Saved moments are ledger owners too, so a moment labelled the same as a
    Look would have counted as one. And a Look that still owns one leftover
    file is not the Look you are using; it is a Look you used once.

    None is still a real answer and a common one: a desktop nobody has applied
    a Look to, or one that has been put back to a saved moment since.
    """
    from ...core.ledger import current_look
    from ...preset import loader as preset_loader

    name = current_look()
    if not name:
        return None
    available = looks if looks is not None else preset_loader.load_all()
    for result in available:
        if getattr(result, "preset", None) is not None and result.name == name:
            return result
    return None


def _pick(palette: dict[str, str], *names: str) -> str | None:
    for name in names:
        value = palette.get(name)
        if value:
            return value
    return None


def _ansi(palette: dict[str, str]) -> tuple[str, ...]:
    """The sixteen colours, or nothing at all.

    Looks spell these two ways — ``red``/``bright_red`` and
    ``ansi_red``/``ansi_bright_red`` — and both are read. A palette missing
    even one of the sixteen yields none of them: a partial ANSI set written
    into a terminal is a terminal with eight of its colours from one look and
    eight from another.

    One of the sixteen not being a colour gtheme can write counts as missing,
    for the same reason and for one more: a Look's palette is unvalidated text,
    and this rule is what keeps one unusable entry from costing the page the
    fifteen good ones and the background with them.
    """
    found: list[str] = []
    for name in _ANSI_NAMES:
        colour = _pick(palette, f"ansi_{name}", name)
        if colour is None or not is_colour(colour):
            return ()
        found.append(colour)
    for name in _ANSI_NAMES:
        colour = _pick(palette, f"ansi_bright_{name}", f"bright_{name}")
        if colour is None or not is_colour(colour):
            return ()
        found.append(colour)
    return tuple(found)


def _opacity(palette: dict[str, str]) -> float:
    raw = _pick(palette, "opacity", "terminal_opacity", "background_opacity")
    try:
        value = float(raw) if raw is not None else 1.0
    except ValueError:
        return 1.0
    return min(max(value, 0.0), 1.0)


def palette_from_look(preset: Any) -> Palette | None:
    """The terminal palette a Look describes, or None when it describes none.

    Looks name their colours for themselves — one calls its darkest colour
    ``bg`` and another does not have a ``bg`` at all. So the background and the
    text colour are looked for under the ordinary names first and fall back to
    the palette's own black and white, which every Look that describes a
    terminal has.

    Built through :func:`~gtheme.terminal.model.read_palette`, which answers
    None for anything that is not a palette instead of raising. A Look's
    ``[palette]`` is unvalidated text — a v1 import folds every colour string
    through untouched, and the Look preview parses colours with a reader that
    accepts ``black`` — so a single colour spelled in a way gtheme cannot write
    used to raise out of here, and the window *cached* the resulting error
    placeholder: the whole Terminal page was unreachable for the rest of the
    session (review-report M11). "gtheme has no set of colours to hand out" is
    already what this page says when a Look describes none, and it is the right
    answer for a Look whose colours it cannot use either.
    """
    colours = dict(getattr(preset, "palette", {}) or {})
    if not colours:
        return None
    ansi = _ansi(colours)
    background = _pick(colours, "bg", "bg0", "background", "base", "void", "surface")
    foreground = _pick(colours, "fg", "fg0", "foreground", "text")
    if background is None and ansi:
        background = ansi[0]
    if foreground is None and ansi:
        foreground = ansi[7]
    if not background or not foreground:
        return None
    return read_palette(
        name=getattr(getattr(preset, "meta", None), "name", None) or "gtheme",
        background=background,
        foreground=foreground,
        cursor=_pick(colours, "cursor", "accent"),
        ansi=ansi,
        opacity=_opacity(colours),
    )


# ---------------------------------------------------------------------------
# which app opens a command window
# ---------------------------------------------------------------------------


def installed_terminal_apps() -> list[tuple[str, str]]:
    """``(command, name)`` for every command-window app on this computer."""
    return [(command, name) for command, name in KNOWN_TERMINAL_APPS if shutil.which(command)]


def _current_text(backend: Any, row: Row) -> str | None:
    from ..widgets.rows import key_for

    try:
        raw = backend.get(key_for(row))
    except BackendError:
        return None
    return unquote(raw) or None


def terminal_app_row(row: Row, backend: Any, *, found: list[tuple[str, str]] | None = None) -> Row:
    """Turn the command-window picker into a pick-one over what is installed."""
    apps = list(found) if found is not None else installed_terminal_apps()
    current = _current_text(backend, row)
    if current and current not in {command for command, _ in apps}:
        apps.append((current, current))
    choices = [Choice(value=quote(command), label=name) for command, name in apps]
    if not choices:
        return row
    return row.model_copy(update={"kind": WidgetKind.CHOICE, "choices": choices})


# ---------------------------------------------------------------------------
# the page
# ---------------------------------------------------------------------------


def build(window: Any, *, backend: Any = None, probe: SchemaProbe | None = None) -> Any:
    """The Terminal page.

    Args:
        window: the application window.
        backend: the settings backend. Defaults to the app's — ptyxis is
            settings-driven and is simply absent without one, which is the
            adapter's own rule and not something this page works around.
        probe: the window's schema probe.
    """
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk

    settings = backend if backend is not None else get_backend()
    scanner = probe if probe is not None else SchemaProbe()
    prefs = getattr(window, "prefs", None)

    # One detect() per adapter, and the answer travels with it: the card, the
    # foreign-settings notice and the "is it here at all" question are all
    # answered from this one scan (review-report L17).
    found = installed(settings)
    look = applied_look()
    palette = palette_from_look(look.preset) if look is not None else None

    page = Adw.PreferencesPage(vexpand=True)
    include: dict[str, Any] = {}
    status: dict[str, Any] = {}

    page.add(_colours_group(Adw, Gtk, look, palette))

    if not found:
        page.add(
            Adw.PreferencesGroup(
                title=escape_markup(COPY["nothing-title"]),
                description=escape_markup(COPY["nothing-body"]),
            )
        )
    for adapter, state in found:
        page.add(_adapter_group(Adw, Gtk, window, adapter, state, include, status))

    if found:
        adapters = [adapter for adapter, _state in found]
        page.add(_apply_group(Adw, window, adapters, palette, include, status, settings))

    built = _app_group(window, page, settings, scanner, Adw)
    page.add(_elsewhere_group(Adw))

    probe_built_rows(page, scanner, built, backend=settings)

    from ..widgets.explainer import with_first_visit_banner

    return with_first_visit_banner(page, prefs, BANNER_ID, COPY["banner"])


def _colours_group(Adw: Any, Gtk: Any, look: Any, palette: Palette | None) -> Any:
    """What colours are on offer, and where they came from."""
    if palette is None or look is None:
        return Adw.PreferencesGroup(
            title=escape_markup(COPY["colours-title"]),
            description=escape_markup(COPY["colours-none"]),
        )
    group = Adw.PreferencesGroup(
        title=escape_markup(COPY["colours-title"]),
        description=escape_markup(COPY["colours-from"].format(name=look.preset.meta.title)),
    )
    row = Adw.ActionRow(
        title=escape_markup(look.preset.meta.title),
        subtitle=escape_markup(COPY["colours-swatch"]),
    )
    swatches = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, valign=Gtk.Align.CENTER)
    for colour in (palette.background, palette.foreground, palette.cursor or palette.foreground):
        swatches.append(_swatch(Gtk, colour))
    row.add_suffix(swatches)
    group.add(row)
    return group


def _swatch(Gtk: Any, colour: str) -> Any:
    """A small square of one colour. The control is the preview (P1)."""
    area = Gtk.DrawingArea(width_request=22, height_request=22, valign=Gtk.Align.CENTER)
    parsed = _rgba(colour)

    def draw(_area: Any, context: Any, width: int, height: int) -> None:
        context.set_source_rgba(parsed[0], parsed[1], parsed[2], 1.0)
        context.rectangle(0, 0, width, height)
        context.fill()

    area.set_draw_func(draw)
    area.set_tooltip_text(colour)
    return area


def _rgba(colour: str) -> tuple[float, float, float]:
    text = colour.lstrip("#")
    if len(text) != 6:
        return (0.5, 0.5, 0.5)
    try:
        return tuple(int(text[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return (0.5, 0.5, 0.5)


def _adapter_group(
    Adw: Any,
    Gtk: Any,
    window: Any,
    adapter: Any,
    state: Any,
    include: dict[str, Any],
    status: dict[str, Any],
) -> Any:
    """One card: what it is, what it is using, and when a change shows up.

    The notes come from the adapter and are shown word for word. They are the
    honest answer to "when will I see this?", and rewording them here is how
    the honesty would get lost.

    Takes the state it was found with rather than asking again: ``detect()``
    walks ``PATH`` and re-parses that program's settings file, and doing it a
    second time here made opening the page do the same work twice per card.
    """
    group = Adw.PreferencesGroup(
        title=escape_markup(adapter.name),
        description=escape_markup("\n".join(state.notes)) or None,
    )

    switch = Adw.SwitchRow(
        title=escape_markup(COPY["include"]),
        subtitle=escape_markup(COPY["include-subtitle"]),
        active=True,
    )
    include[adapter.id] = switch
    group.add(switch)

    current = state.current
    group.add(
        Adw.ActionRow(
            title=escape_markup(COPY["using-now"]),
            subtitle=escape_markup(
                current.name if current is not None else COPY["using-unknown"]
            ),
        )
    )

    outcome = Adw.ActionRow(title="", visible=False)
    status[adapter.id] = outcome
    group.add(outcome)

    if isinstance(adapter, GhosttyAdapter) and state.foreign_root is not None:
        group.set_header_suffix(_takeover_button(Adw, Gtk, window, adapter, state, switch))
    return group


def _takeover_button(Adw: Any, Gtk: Any, window: Any, adapter: Any, state: Any, switch: Any) -> Any:
    """The one button that answers the F7 refusal, and its undo.

    Nothing here probes by writing. ``foreign_root()`` and ``taken_over()``
    both only look, and the button label is chosen from what they say.
    """
    button = Gtk.Button(valign=Gtk.Align.CENTER, css_classes=["flat"])
    notice = _foreign_notice(state)

    def refresh() -> None:
        taken = adapter.taken_over()
        button.set_label(COPY["undo-take-over"] if taken else COPY["take-over"])
        button.set_tooltip_text(COPY["taken-over"] if taken else notice)
        switch.set_sensitive(taken)
        if not taken:
            switch.set_active(False)

    def clicked(*_args: Any) -> None:
        try:
            if adapter.taken_over():
                changed, message = adapter.undo_takeover(), COPY["link-restored"]
            else:
                changed, message = adapter.take_over(), COPY["taken-over"]
        except OSError as exc:
            changed, message = False, COPY["failed"].format(why=exc)
        if changed:
            _toast(window, message)
        refresh()

    button.connect("clicked", _guarded(window, clicked))
    refresh()
    return button


def _foreign_notice(state: Any) -> str:
    """The adapter's own refusal sentence, taken from its own notes.

    Matched by the fixed half of the constant rather than by position, so the
    page keeps saying what the adapter says even if the adapter grows a note.
    Read out of the state the card was built from — asking the adapter again
    would re-run a full scan to re-read a sentence already on screen.
    """
    prefix = FOREIGN_NOTICE.split("{owner}")[0]
    for note in state.notes:
        if note.startswith(prefix):
            return note
    return prefix.strip()


def _apply_group(
    Adw: Any,
    window: Any,
    adapters: list[Any],
    palette: Palette | None,
    include: dict[str, Any],
    status: dict[str, Any],
    backend: Any,
) -> Any:
    group = Adw.PreferencesGroup()
    button = Adw.ButtonRow(title=COPY["apply"])
    button.add_css_class("suggested-action")
    if palette is None:
        button.set_sensitive(False)
        button.set_title(COPY["apply-none"] if not adapters else COPY["apply"])
        group.set_description(COPY["colours-none"])
    else:
        button.connect(
            "activated",
            _guarded(
                window, lambda *_a: _apply(window, adapters, palette, include, status, backend)
            ),
        )
    group.add(button)
    return group


def _guarded(window: Any, handler: Any) -> Any:
    """A signal handler that cannot end in a traceback nobody sees.

    PyGObject prints what escapes a signal handler and carries on, so a
    handler that raised produced **nothing**: no message, no error row, and a
    click that looked like it did not register (review-report H12). Everything
    below this line reports its own failures; this is the layer for the ones
    nobody predicted, and it says so and writes the details to the log.
    """

    def wrapped(*args: Any) -> None:
        try:
            handler(*args)
        except Exception:  # noqa: BLE001 - a GTK signal is the end of the line
            applog.logger(__name__).exception("terminal page: a handler failed")
            _toast(window, COPY["crashed"])

    return wrapped


def _apply(
    window: Any,
    adapters: list[Any],
    palette: Palette,
    include: dict[str, Any],
    status: dict[str, Any],
    backend: Any,
) -> None:
    """Hand the palette to the chosen programs and report each one separately.

    The work — saving how everything is now, copying files, writing settings —
    goes on the window's shared runner, which is where every other slow change
    in the app happens. With no runner (a page built by a test) it runs inline
    and the result is there when this returns.

    One program refusing does not stop the others and is never reported as
    success: :func:`gtheme.terminal.apply_all` answers per adapter, and every
    answer is shown on that adapter's own card.
    """
    chosen = [a for a in adapters if include[a.id].get_active()]
    if not chosen:
        return

    def work(narrate: Any = None) -> ApplyReport:
        return apply_all(palette, chosen, backend=backend, narrate=narrate)

    runner = _runner(window)
    if runner is None:
        _report(window, chosen, status, work())
        return
    runner.run(
        work,
        heading=COPY["working-heading"],
        starting=COPY["working"],
        on_done=lambda report: _report(window, chosen, status, report),
        on_failed=lambda _error: _toast(window, COPY["crashed"]),
    )


def _runner(window: Any) -> Any | None:
    """The window's runner, or None when this page is not in a window."""
    from ..applyrunner import ApplyRunner

    runner = getattr(window, "runner", None)
    return runner if isinstance(runner, ApplyRunner) else None


def _report(window: Any, chosen: list[Any], status: dict[str, Any], report: ApplyReport) -> None:
    """Put each program's own answer on its own card, then say it once out loud."""
    failures = 0
    for adapter in chosen:
        problem = report.problems.get(adapter.id)
        row = status.get(adapter.id)
        if row is None:
            continue
        if problem is None:
            row.set_title(
                escape_markup(COPY["done"].format(when=adapter.reload_semantics.sentence()))
            )
            row.remove_css_class("error")
        else:
            failures += 1
            row.set_title(escape_markup(COPY["failed"].format(why=problem)))
            row.add_css_class("error")
        row.set_visible(True)
    if failures:
        _toast(
            window,
            COPY["some-changed"].format(done=len(chosen) - failures, total=len(chosen)),
        )
    else:
        _toast(window, COPY["done"].format(when=""))
    for warning in report.warnings:
        # What the saved moment could only save in part. Said after the change,
        # never instead of it.
        _toast(window, warning)


def _toast(window: Any, text: str) -> None:
    toast = getattr(window, "toast", None)
    if toast is not None:
        toast(text.strip())


def _app_group(
    window: Any, page: Any, backend: Any, probe: Any, Adw: Any
) -> list[tuple[Row, Any]]:
    """The one desktop setting this page owns: which app opens."""
    rows = [terminal_app_row(row, backend) for row in page_rows(PAGE_ID)]
    if not rows:
        return []
    group = Adw.PreferencesGroup(
        title=escape_markup(COPY["app-title"]),
        description=escape_markup(COPY["app-description"]),
    )
    built = build_indexed_rows(
        window, PAGE_ID, rows, backend=backend, probe=probe, into=group
    )
    page.add(group)
    return built


def _elsewhere_group(Adw: Any) -> Any:
    """What this page deliberately does not do, said out loud once."""
    group = Adw.PreferencesGroup(title=escape_markup(COPY["elsewhere-title"]))
    group.add(Adw.ActionRow(title=escape_markup(COPY["spicetify"]), sensitive=False))
    return group
