"""Stdlib interactive-TUI primitives for gtheme (no curses/rich dependency).

Everything here is built from ``termios``/``tty`` raw input and ANSI escapes,
degrading to a plain numbered prompt when there is no usable TTY (pipes, CI,
platforms without ``termios``) or when ``GTHEME_PLAIN=1`` is set — the
screen-reader-friendly mode: no raw input, no in-place repaints. The
interactive loops (:func:`select`, :func:`confirm`, :func:`multiselect`)
accept injectable ``read``/``render`` callables so their navigation logic can
be unit-tested without a real terminal.

Layout contract — every screen draws as::

    breadcrumb title                                    right status chip
    ────────────────────────────────────────────────────────────────────
      ❯ the rows (scroll window with "N more" overflow hints)
    optional info panel for the highlighted row
    ────────────────────────────────────────────────────────────────────
    key hints                                                       3/12

Every emitted line is pre-truncated to the terminal width, and the width is
re-measured on each repaint, so the in-place repaint's line accounting is
exact by construction: no wrapped lines, no corrupted frames in narrow or
resized terminals.
"""

from __future__ import annotations

import os
import shutil
import sys
from contextlib import contextmanager
from typing import Callable, Sequence

from . import ansi

try:  # POSIX only; Windows/odd platforms fall back to the dumb prompt.
    import termios
    import tty
    import select as _select

    _HAVE_TERMIOS = True
except ImportError:  # pragma: no cover - platform dependent
    _HAVE_TERMIOS = False


# Brand gradient endpoints for the header wordmark (cyan -> magenta). The
# menu retints these to the applied theme's accent at startup, so the tool
# wears whatever theme the desktop wears.
BRAND_A = "#22d3ee"
BRAND_B = "#a855f7"
_DEFAULT_BRAND = (BRAND_A, BRAND_B)


def set_brand(a: str | None, b: str | None = None) -> None:
    """Retint the header gradient; ``set_brand(None)`` restores the default.

    Bad/unparseable colours are ignored rather than raised — the brand tint
    is decoration, never worth an error.
    """
    global BRAND_A, BRAND_B
    if a is None:
        BRAND_A, BRAND_B = _DEFAULT_BRAND
        return
    b = b or a
    try:
        ansi._rgb(a), ansi._rgb(b)
    except (ValueError, TypeError):
        return
    BRAND_A, BRAND_B = a, b


def is_interactive() -> bool:
    """True when we can drive a full-screen arrow-key menu."""
    if os.environ.get("GTHEME_PLAIN"):  # accessibility: force numbered prompts
        return False
    return _HAVE_TERMIOS and sys.stdin.isatty() and sys.stdout.isatty()


def term_size() -> tuple[int, int]:
    """(columns, rows); re-read every repaint so resizes self-heal."""
    size = shutil.get_terminal_size((80, 24))
    return size.columns, size.lines


# ----------------------------------------------------------- screen control ---
def _emit(s: str) -> None:
    sys.stdout.write(s)
    sys.stdout.flush()


def hide_cursor() -> None:
    if ansi.enabled():
        _emit("\033[?25l")


def show_cursor() -> None:
    if ansi.enabled():
        _emit("\033[?25h")


def clear() -> None:
    if ansi.enabled():
        _emit("\033[2J\033[H")


def _up(n: int) -> None:
    if n > 0:
        _emit(f"\033[{n}A")


def _clear_below() -> None:
    _emit("\033[J")


_ALT = False


def enter_alt() -> None:
    """Switch to the terminal's alternate screen (like lazygit/htop do)."""
    global _ALT
    if not _ALT and ansi.enabled() and is_interactive():
        _emit("\033[?1049h\033[H")
        _ALT = True


def leave_alt() -> None:
    """Return to the normal screen; the user's scrollback is untouched."""
    global _ALT
    if _ALT:
        _emit("\033[?1049l")
        show_cursor()
        _ALT = False


@contextmanager
def alt_screen():
    """Run a whole menu session on the alternate screen; always restores."""
    enter_alt()
    try:
        yield
    finally:
        leave_alt()


@contextmanager
def _raw():
    """Put stdin into cbreak mode for the duration of the block."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        hide_cursor()
        yield fd
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        show_cursor()


# --------------------------------------------------------------- key reader ---
_ARROWS = {"A": "up", "B": "down", "C": "right", "D": "left", "H": "home", "F": "end"}


def read_key(fd: int | None = None) -> str:
    """Block for one keypress and return a logical key name.

    Names: up/down/left/right/enter/esc/space/backspace/home/end/pgup/pgdn,
    a single printable character, "ignore" for swallowed-but-unmapped input
    (modified arrows, F-keys, Delete, undecodable bytes), or "" on EOF.
    """
    if fd is None:
        fd = sys.stdin.fileno()
    ch = os.read(fd, 1)
    if not ch:
        return ""
    if ch in (b"\r", b"\n"):
        return "enter"
    if ch == b" ":
        return "space"
    if ch in (b"\x7f", b"\x08"):
        return "backspace"
    if ch == b"\x03":  # Ctrl-C
        raise KeyboardInterrupt
    if ch == b"\x1b":
        # Escape: could be a bare ESC or the start of a CSI/SS3 sequence.
        # Peek with a short timeout to tell them apart.
        if not _waiting(fd, 0.02):
            return "esc"
        nxt = os.read(fd, 1)
        if nxt in (b"[", b"O"):
            code = os.read(fd, 1)
            if code in (b"5", b"6"):
                # PgUp/PgDn end with '~', but modified variants (ESC[5;5~)
                # carry a parameter tail — drain to the final byte so nothing
                # leaks in as phantom digit presses (digits select rows!).
                key = "pgup" if code == b"5" else "pgdn"
                while code and not 0x40 <= code[0] <= 0x7E:
                    if not _waiting(fd, 0.02):
                        break
                    code = os.read(fd, 1)
                return key
            name = _ARROWS.get(code.decode("latin-1"))
            if name:
                return name
            # Unknown sequence (Shift/Ctrl+arrow, Delete, F-keys): swallow it
            # to the final byte (0x40-0x7E) so its tail can't leak in as
            # phantom keypresses, then report it as ignorable — a stray
            # Delete must not cancel the whole menu.
            while code and not 0x40 <= code[0] <= 0x7E:
                if not _waiting(fd, 0.02):
                    break
                code = os.read(fd, 1)
            return "ignore"
        return "esc"
    try:
        return ch.decode("utf-8")
    except UnicodeDecodeError:
        return "ignore"


def _waiting(fd: int, timeout: float) -> bool:
    r, _, _ = _select.select([fd], [], [], timeout)
    return bool(r)


# ------------------------------------------------------------------- header ---
def _bold_gradient(text: str) -> str:
    g = ansi.gradient(text, BRAND_A, BRAND_B)
    # gradient() only resets at its end, so a leading bold survives throughout.
    # The trailing reset matters when colour depth is 0 (TERM=linux/vt100):
    # gradient() returns plain text there and the bold would otherwise leak.
    return f"\033[1m{g}\033[0m" if ansi.enabled() else text


def _crumbs(title: str) -> str:
    """Style 'gtheme › apply › jojo': gradient wordmark, dim separators."""
    sep = ansi.GLYPH["crumb"]
    parts = [p.strip() for p in title.split("›")]
    out = [_bold_gradient(parts[0])]
    for p in parts[1:]:
        out.append(ansi.style(sep, "grey"))
        out.append(ansi.style(p, "bold"))
    return " ".join(out)


def _header_lines(title: str, right: str, subtitle: str, width: int) -> list[str]:
    left = "  " + _crumbs(title)
    line = left
    if right:
        gap = (width - 2) - ansi.visible_len(left) - ansi.visible_len(right)
        if gap >= 2:  # drop the chip rather than crowd the title
            line = left + " " * gap + right
    lines = [line]
    if subtitle:
        lines.append("  " + ansi.style(subtitle, "grey"))
    # A faint brand-gradient hairline under the header; dim keeps it subtle.
    # Explicit trailing reset: at colour depth 0 gradient() is a no-op and
    # the dim attribute would otherwise bleed into the rows below.
    hair = ansi.GLYPH["rule"] * (width - 4)
    if ansi.enabled():
        lines.append("  \033[2m" + ansi.gradient(hair, BRAND_A, BRAND_B) + "\033[0m")
    else:
        lines.append("  " + hair)
    return lines


def _footer_line(footer: str, counter: str, width: int) -> str:
    line = "  " + ansi.style(footer, "grey")
    if counter:
        gap = (width - 2) - ansi.visible_len(line) - len(counter)
        if gap >= 2:
            line = line + " " * gap + ansi.style(counter, "grey")
    return line


# ------------------------------------------------------------------- select ---
def _default_render(
    title: str,
    rows: Sequence[str],
    index: int,
    footer: str,
    height: int,
    subtitle: str = "",
    *,
    rows_sel: Sequence[str] | None = None,
    right: str = "",
    panel_lines: Sequence[str] | None = None,
) -> int:
    """Render one frame in place and return the number of lines drawn."""
    cols, term_rows = term_size()
    width = max(30, cols - 1)
    lines: list[str] = []
    lines += _header_lines(title, right, subtitle, width)
    lines.append("")

    n = len(rows)
    panel_lines = list(panel_lines or [])
    # Vertical budget: header + footer + panel + overflow hints always fit,
    # so the highlighted row can never scroll off-screen.
    overhead = len(lines) + len(panel_lines) + (1 if panel_lines else 0) + 5
    fit = max(3, term_rows - overhead)
    win = min(height, fit) if height else fit
    if n > win:
        top = max(0, min(index - win // 2, n - win))
    else:
        top, win = 0, n

    if top > 0:
        lines.append(ansi.style(f"    {ansi.GLYPH['up']} {top} more", "grey"))
    for i in range(top, top + win):
        if i == index:
            pointer = ansi.fg(ansi.GLYPH["pointer"], BRAND_B)
            body = rows_sel[i] if rows_sel else ansi.reverse(ansi.strip(rows[i]))
            lines.append(f"  {pointer} {body}")
        else:
            lines.append(f"    {rows[i]}")
    below = n - (top + win)
    if below > 0:
        lines.append(ansi.style(f"    {ansi.GLYPH['down']} {below} more", "grey"))

    if panel_lines:
        lines.append("")
        lines += ["    " + p for p in panel_lines]

    lines.append("")
    lines.append("  " + ansi.rule(width - 4))
    counter = f"{index + 1}/{n}" if n > win else ""
    lines.append(_footer_line(footer, counter, width))

    for ln in lines:
        _emit("\033[K" + ansi.truncate(ln, width) + "\n")
    _clear_below()  # a shorter frame must erase the taller one before it
    return len(lines)


def _default_footer(back: str = "back") -> str:
    d = ansi.GLYPH["dot"]
    return (
        f"{ansi.GLYPH['up']}{ansi.GLYPH['down']} move {d} enter select {d} q {back}"
    )


def select(
    title: str,
    options: Sequence,
    *,
    to_label: Callable[[object], str] = str,
    to_label_sel: Callable[[object], str] | None = None,
    footer: str | None = None,
    subtitle: str = "",
    right: str = "",
    panel: Callable[[object], Sequence[str]] | None = None,
    initial: int = 0,
    height: int = 0,
    read: Callable[[], str] | None = None,
    render: Callable[..., int] | None = None,
) -> object | None:
    """Arrow-key single-select. Returns the chosen option or None if cancelled.

    ``read``/``render`` are injectable for testing; by default they drive the
    real terminal. When there is no usable TTY, a numbered prompt is used.
    A 1-9 digit press jumps to that row and selects it immediately.
    """
    options = list(options)
    if not options:
        return None
    if read is None and render is None and not is_interactive():
        return _dumb_select(title, options, to_label)

    rows = [to_label(o) for o in options]
    rows_sel = [to_label_sel(o) for o in options] if to_label_sel else None
    if footer is None:
        footer = _default_footer()
    index = max(0, min(initial, len(options) - 1))
    _read = read or read_key
    _render = render or _default_render
    drawn = 0

    def repaint() -> None:
        nonlocal drawn
        if drawn:
            _up(drawn)
        panel_lines = list(panel(options[index])) if panel else None
        drawn = _render(
            title, rows, index, footer, height, subtitle,
            rows_sel=rows_sel, right=right, panel_lines=panel_lines,
        )

    def loop() -> object | None:
        nonlocal index
        repaint()
        while True:
            key = _read()
            if key == "":  # EOF (or an exhausted scripted read): cancel
                return None
            done = _handle_nav(key, index, len(options))
            if done is _CANCEL:
                return None
            if done is _SELECT:
                return options[index]
            index = done
            # A 1-9 digit jump also selects (the idiom newcomers expect:
            # "press 2 to pick the second one").
            if key.isdigit() and key != "0" and int(key) - 1 == index:
                return options[index]
            repaint()

    if read is None and render is None:
        with _raw():
            return loop()
    return loop()


# Sentinels distinguishing "moved to index N" from select/cancel.
_SELECT = object()
_CANCEL = object()


def _handle_nav(key: str, index: int, n: int, page: int = 5):
    """Pure navigation step: return new index, or _SELECT/_CANCEL."""
    if key in ("up", "k"):
        return (index - 1) % n
    if key in ("down", "j"):
        return (index + 1) % n
    if key == "home":
        return 0
    if key == "end":
        return n - 1
    if key == "pgup":
        return max(0, index - page)
    if key == "pgdn":
        return min(n - 1, index + page)
    if key in ("enter", "right", "l"):
        return _SELECT
    if key in ("esc", "q", "left", "h"):
        return _CANCEL
    if key.isdigit() and key != "0":
        target = int(key) - 1
        if target < n:
            return target
    return index


# -------------------------------------------------------------- multiselect ---
def multiselect(
    title: str,
    options: Sequence,
    *,
    to_label: Callable[[object], str] = str,
    footer: str | None = None,
    subtitle: str = "",
    right: str = "",
    require_one: bool = False,
    read: Callable[[], str] | None = None,
    render: Callable[..., int] | None = None,
) -> list | None:
    """Space-to-toggle multi-select. Returns chosen options, or None if cancelled.

    With ``require_one`` enter is refused (with a hint) until something is
    toggled — an empty pick silently meaning "everything" is a trap.
    """
    options = list(options)
    if not options:
        return []
    if read is None and render is None and not is_interactive():
        return _dumb_multiselect(title, options, to_label)

    index = 0
    chosen: set[int] = set()
    notice = ""
    d = ansi.GLYPH["dot"]
    if footer is None:
        footer = f"{ansi.GLYPH['up']}{ansi.GLYPH['down']} move {d} space toggle {d} enter confirm {d} q back"
    _read = read or read_key
    drawn = 0

    def rows(selected: bool) -> list[str]:
        out = []
        for i, o in enumerate(options):
            box = (
                ansi.fg(ansi.GLYPH["on"], BRAND_A)
                if i in chosen
                else ansi.style(ansi.GLYPH["off"], "grey")
            )
            label = to_label(o)
            if selected and i == index:
                label = ansi.reverse(ansi.strip(label))
            out.append(f"{box} {label}")
        return out

    _render = render or _default_render

    def repaint() -> None:
        nonlocal drawn
        if drawn:
            _up(drawn)
        foot = footer if not notice else f"{footer}   {notice}"
        drawn = _render(
            title, rows(False), index, foot, 0, subtitle,
            rows_sel=rows(True), right=right,
        )

    def step(key: str):
        nonlocal index, notice
        notice = ""
        if key in ("space", "right", "l"):
            chosen.symmetric_difference_update({index})
            return None
        if key == "enter":
            if chosen or not require_one:
                return "done"
            notice = ansi.style("toggle at least one (space)", "yellow")
            return None
        done = _handle_nav(key, index, len(options))
        if done is _CANCEL:
            return "cancel"
        if done is _SELECT:  # unreachable (enter/right/l handled above)
            return "done"
        index = done
        return None

    def loop() -> list | None:
        repaint()
        while True:
            key = _read()
            if key == "":
                return None
            r = step(key)
            if r == "cancel":
                return None
            if r == "done":
                return [options[i] for i in sorted(chosen)]
            repaint()

    if read is None and render is None:
        with _raw():
            return loop()
    return loop()


# ------------------------------------------------------------------ confirm ---
def confirm(prompt: str, *, default: bool = False, read: Callable[[], str] | None = None) -> bool:
    """A yes/no confirmation. Enter accepts the default."""
    suffix = "[Y/n]" if default else "[y/N]"
    if read is None and not is_interactive():
        try:
            ans = input(f"{prompt} {suffix} ").strip().lower()
        except EOFError:
            # No input stream at all (closed pipe): never let a default=True
            # silently consent to a destructive action. A blank LINE is an
            # explicit enter and still takes the default.
            return False
        if not ans:
            return default
        return ans in ("y", "yes")
    _read = read or read_key
    line = f"  {ansi.fg('?', BRAND_B)} {prompt} {ansi.style(suffix, 'grey')} "
    if read is None:
        with _raw():
            _emit(line)
            while True:
                key = _read()
                if key in ("enter",):
                    _emit("\n")
                    return default
                if key in ("y", "Y"):
                    _emit("y\n")
                    return True
                if key in ("n", "N", "esc", "q"):
                    _emit("n\n")
                    return False
    else:
        while True:
            key = _read()
            if key == "":
                return default
            if key == "enter":
                return default
            if key in ("y", "Y"):
                return True
            if key in ("n", "N", "esc", "q"):
                return False


# --------------------------------------------------------------- text input ---
def prompt_text(label: str, *, default: str = "") -> str | None:
    """Read a line of text with the cursor shown. Returns None if cancelled."""
    show_cursor()
    hint = f" ({default})" if default else ""
    try:
        val = input(f"  {ansi.fg(ansi.GLYPH['prompt'], BRAND_A)} {label}{hint}: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    return val or default


# ------------------------------------------------------- non-TTY fallback ---
def _dumb_select(title: str, options: Sequence, to_label: Callable) -> object | None:
    """Numbered prompt for environments without a controllable TTY."""
    print()
    print(ansi.strip(title))
    for i, o in enumerate(options, 1):
        print(f"  {i}. {ansi.strip(to_label(o)).rstrip()}")
    try:
        raw = input("select a number (blank to cancel): ").strip()
    except EOFError:
        return None
    if not raw:
        return None
    try:
        idx = int(raw) - 1
    except ValueError:
        return None
    if 0 <= idx < len(options):
        return options[idx]
    return None


def _dumb_multiselect(title: str, options: Sequence, to_label: Callable) -> list | None:
    """Numbered multi-pick for environments without a controllable TTY."""
    print()
    print(ansi.strip(title))
    for i, o in enumerate(options, 1):
        print(f"  {i}. {ansi.strip(to_label(o)).rstrip()}")
    try:
        raw = input("numbers to include, e.g. 1,3 (blank to cancel): ").strip()
    except EOFError:
        return None
    if not raw:
        return None
    picked = []
    for tok in raw.replace(",", " ").split():
        if tok.isdigit() and 1 <= int(tok) <= len(options):
            o = options[int(tok) - 1]
            if o not in picked:
                picked.append(o)
    return picked or None
