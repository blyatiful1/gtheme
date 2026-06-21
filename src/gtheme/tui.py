"""Stdlib interactive-TUI primitives for gtheme (no curses/rich dependency).

Everything here is built from ``termios``/``tty`` raw input and ANSI escapes,
degrading to a plain numbered prompt when there is no usable TTY (pipes, CI,
or platforms without ``termios``). The interactive loops (:func:`select`,
:func:`confirm`, :func:`multiselect`) accept injectable ``read``/``render``
callables so their navigation logic can be unit-tested without a real
terminal.
"""

from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager
from typing import Callable, Iterable, Sequence

from . import ansi

try:  # POSIX only; Windows/odd platforms fall back to the dumb prompt.
    import termios
    import tty
    import select as _select

    _HAVE_TERMIOS = True
except ImportError:  # pragma: no cover - platform dependent
    _HAVE_TERMIOS = False


# Brand gradient endpoints for banners/headers (cyan -> magenta).
BRAND_A = "#22d3ee"
BRAND_B = "#a855f7"

_ANIM = (
    ansi.enabled()
    and os.environ.get("GTHEME_NO_ANIM") is None
    and os.environ.get("NO_COLOR") is None
)


def is_interactive() -> bool:
    """True when we can drive a full-screen arrow-key menu."""
    return _HAVE_TERMIOS and sys.stdin.isatty() and sys.stdout.isatty()


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


@contextmanager
def _raw():
    """Put stdin into cbreak/raw mode for the duration of the block."""
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
# Logical key names returned by read_key.
_ARROWS = {"A": "up", "B": "down", "C": "right", "D": "down", "H": "home", "F": "end"}


def read_key(fd: int | None = None) -> str:
    """Block for one keypress and return a logical key name.

    Names: up/down/left/right/enter/esc/space/backspace/home/end/pgup/pgdn,
    a single printable character, or "" on EOF.
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
        # Escape: could be a bare ESC or the start of a CSI sequence. Peek with
        # a short timeout to tell them apart.
        if not _waiting(fd, 0.02):
            return "esc"
        nxt = os.read(fd, 1)
        if nxt == b"[" or nxt == b"O":
            code = os.read(fd, 1)
            if code in (b"5", b"6"):  # PgUp/PgDn end with '~'
                os.read(fd, 1)
                return "pgup" if code == b"5" else "pgdn"
            return _ARROWS.get(code.decode("latin-1"), "esc")
        return "esc"
    try:
        return ch.decode("utf-8")
    except UnicodeDecodeError:
        return ""


def _waiting(fd: int, timeout: float) -> bool:
    r, _, _ = _select.select([fd], [], [], timeout)
    return bool(r)


# ------------------------------------------------------------------- widgets ---
def banner(title: str, subtitle: str = "") -> list[str]:
    """Return the lines of the gradient title banner (already styled)."""
    bar = "─" * (len(title) + 4)
    lines = [
        ansi.gradient("╭" + bar + "╮", BRAND_A, BRAND_B),
        ansi.gradient("│  " + title + "  │", BRAND_A, BRAND_B),
        ansi.gradient("╰" + bar + "╯", BRAND_A, BRAND_B),
    ]
    if subtitle:
        lines.append(ansi.style(subtitle, "grey"))
    return lines


def reveal(lines: Iterable[str], delay: float = 0.012) -> None:
    """Print lines top-to-bottom with a quick staggered reveal (flair)."""
    for line in lines:
        _emit(line + "\n")
        if _ANIM and delay:
            time.sleep(delay)


@contextmanager
def spinner(message: str):
    """A lightweight braille spinner shown while a block runs.

    Falls back to a one-line static message when animation is off.
    """
    if not _ANIM:
        _emit(ansi.style(f"  {message}…\n", "grey"))
        yield
        return

    frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    stop = {"v": False}

    import threading

    def run() -> None:
        i = 0
        hide_cursor()
        while not stop["v"]:
            f = ansi.fg(frames[i % len(frames)], BRAND_A)
            _emit(f"\r  {f} {ansi.style(message, 'grey')}")
            i += 1
            time.sleep(0.08)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    try:
        yield
    finally:
        stop["v"] = True
        t.join(timeout=0.2)
        _emit("\r\033[K")  # clear the spinner line
        show_cursor()


# ------------------------------------------------------------------- select ---
def _default_render(
    title: str,
    rows: Sequence[str],
    index: int,
    footer: str,
    height: int,
    subtitle: str = "",
) -> int:
    """Render the menu in place and return the number of lines drawn."""
    lines: list[str] = []
    lines += banner(title, subtitle)
    lines.append("")
    n = len(rows)
    # Scroll window so the cursor stays visible for long lists.
    if height and n > height:
        top = max(0, min(index - height // 2, n - height))
        visible = range(top, top + height)
    else:
        visible = range(n)
    for i in visible:
        row = rows[i]
        if i == index:
            pointer = ansi.fg("❯", BRAND_B)
            lines.append(f" {pointer} {ansi.style(row, 'bold')}")
        else:
            lines.append(f"   {row}")
    lines.append("")
    lines.append(ansi.style(footer, "grey"))
    for ln in lines:
        _emit("\033[K" + ln + "\n")
    return len(lines)


def select(
    title: str,
    options: Sequence,
    *,
    to_label: Callable[[object], str] = str,
    footer: str = "↑/↓ move · enter select · q back",
    subtitle: str = "",
    initial: int = 0,
    height: int = 0,
    read: Callable[[], str] | None = None,
    render: Callable[..., int] | None = None,
) -> object | None:
    """Arrow-key single-select. Returns the chosen option or None if cancelled.

    ``read``/``render`` are injectable for testing; by default they drive the
    real terminal. When there is no usable TTY, a numbered prompt is used.
    """
    options = list(options)
    if not options:
        return None
    if read is None and render is None and not is_interactive():
        return _dumb_select(title, options, to_label)

    rows = [to_label(o) for o in options]
    index = max(0, min(initial, len(options) - 1))
    _read = read or read_key
    _render = render or _default_render
    drawn = 0

    def repaint() -> None:
        nonlocal drawn
        if drawn:
            _up(drawn)
        drawn = _render(title, rows, index, footer, height, subtitle)

    interactive = read is None and render is None
    if interactive:
        with _raw():
            repaint()
            while True:
                key = _read()
                done = _handle_nav(key, index, len(options))
                if done is _CANCEL:
                    _clear_below()
                    return None
                if done is _SELECT:
                    _clear_below()
                    return options[index]
                index = done
                repaint()
    else:
        # Test / non-terminal path: no raw mode, render is a no-op or capture.
        repaint()
        while True:
            key = _read()
            if key == "":
                return None
            done = _handle_nav(key, index, len(options))
            if done is _CANCEL:
                return None
            if done is _SELECT:
                return options[index]
            index = done
            repaint()


# Sentinels distinguishing "moved to index N" from select/cancel.
_SELECT = object()
_CANCEL = object()


def _handle_nav(key: str, index: int, n: int):
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
        return max(0, index - 5)
    if key == "pgdn":
        return min(n - 1, index + 5)
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
    footer: str = "↑/↓ move · space toggle · enter confirm · q back",
    read: Callable[[], str] | None = None,
    render: Callable[..., int] | None = None,
) -> list | None:
    """Space-to-toggle multi-select. Returns chosen options, or None if cancelled."""
    options = list(options)
    if not options:
        return []
    index = 0
    chosen: set[int] = set()
    _read = read or read_key
    interactive = read is None and render is None
    drawn = 0

    def rows() -> list[str]:
        out = []
        for i, o in enumerate(options):
            box = ansi.fg("◉", BRAND_A) if i in chosen else ansi.style("○", "grey")
            out.append(f"{box} {to_label(o)}")
        return out

    def _render_default(*_a) -> int:
        lines = banner(title)
        for i, row in enumerate(rows()):
            if i == index:
                lines.append(f" {ansi.fg('❯', BRAND_B)} {ansi.style(row, 'bold')}")
            else:
                lines.append(f"   {row}")
        lines.append("")
        lines.append(ansi.style(footer, "grey"))
        for ln in lines:
            _emit("\033[K" + ln + "\n")
        return len(lines)

    _render = render or _render_default

    def repaint() -> None:
        nonlocal drawn
        if drawn:
            _up(drawn)
        drawn = _render()

    def step(key: str):
        nonlocal index
        if key in ("up", "k"):
            index = (index - 1) % len(options)
        elif key in ("down", "j"):
            index = (index + 1) % len(options)
        elif key == "space":
            chosen.symmetric_difference_update({index})
        elif key == "enter":
            return "done"
        elif key in ("esc", "q"):
            return "cancel"
        return None

    if interactive:
        with _raw():
            repaint()
            while True:
                r = step(_read())
                if r == "cancel":
                    _clear_below()
                    return None
                if r == "done":
                    _clear_below()
                    return [options[i] for i in sorted(chosen)]
                repaint()
    else:
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


# ------------------------------------------------------------------ confirm ---
def confirm(prompt: str, *, default: bool = False, read: Callable[[], str] | None = None) -> bool:
    """A yes/no confirmation. Enter accepts the default."""
    suffix = "[Y/n]" if default else "[y/N]"
    if read is None and not is_interactive():
        try:
            ans = input(f"{prompt} {suffix} ").strip().lower()
        except EOFError:
            return default
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
        val = input(f"  {ansi.fg('›', BRAND_A)} {label}{hint}: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    return val or default


# ------------------------------------------------------- non-TTY fallback ---
def _dumb_select(title: str, options: Sequence, to_label: Callable) -> object | None:
    """Numbered prompt for environments without a controllable TTY."""
    print(title)
    for i, o in enumerate(options, 1):
        print(f"  {i}. {to_label(o)}")
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
