"""Unit tests for the interactive TUI primitives and the menu's arg-building.

These exercise the pure parts — navigation state machine, the injectable
select/multiselect/confirm loops, raw escape-sequence decoding (through a
pipe, no real terminal), ANSI-aware width helpers, and the Namespace the
menu hands to the cmd_* handlers.
"""

from __future__ import annotations

import os

import gtheme.ansi as ansi
import gtheme.menu as menu
import gtheme.tui as tui


# --------------------------------------------------------------- navigation ---
def test_handle_nav_moves_and_wraps():
    assert tui._handle_nav("down", 0, 3) == 1
    assert tui._handle_nav("up", 0, 3) == 2  # wrap to last
    assert tui._handle_nav("down", 2, 3) == 0  # wrap to first
    assert tui._handle_nav("j", 0, 3) == 1
    assert tui._handle_nav("k", 1, 3) == 0


def test_handle_nav_jumps():
    assert tui._handle_nav("home", 2, 5) == 0
    assert tui._handle_nav("end", 0, 5) == 4
    assert tui._handle_nav("pgdn", 0, 20) == 5
    assert tui._handle_nav("pgup", 10, 20) == 5
    assert tui._handle_nav("3", 0, 5) == 2  # number jump (1-indexed)
    assert tui._handle_nav("9", 0, 5) == 0  # out of range: no move


def test_handle_nav_select_and_cancel():
    assert tui._handle_nav("enter", 1, 3) is tui._SELECT
    assert tui._handle_nav("right", 1, 3) is tui._SELECT
    assert tui._handle_nav("q", 1, 3) is tui._CANCEL
    assert tui._handle_nav("esc", 1, 3) is tui._CANCEL
    # Left arrow / h are "go back" — the arrow variant regressed once
    # (mis-mapped to "down" in _ARROWS), hence both are pinned here.
    assert tui._handle_nav("left", 1, 3) is tui._CANCEL
    assert tui._handle_nav("h", 1, 3) is tui._CANCEL
    # Swallowed unknown sequences must be a no-op, not a cancel.
    assert tui._handle_nav("ignore", 1, 3) == 1


# ------------------------------------------------------------ escape decoding ---
def _keys_from_bytes(data: bytes) -> list[str]:
    """Feed raw bytes through read_key via a pipe and collect logical keys."""
    r, w = os.pipe()
    try:
        os.write(w, data)
        os.close(w)
        keys = []
        while True:
            key = tui.read_key(r)
            if key == "":
                break
            keys.append(key)
        return keys
    finally:
        os.close(r)


def test_read_key_decodes_all_four_arrows():
    assert _keys_from_bytes(b"\x1b[A\x1b[B\x1b[C\x1b[D") == ["up", "down", "right", "left"]
    # SS3 variants (application cursor mode) decode identically.
    assert _keys_from_bytes(b"\x1bOD") == ["left"]


def test_read_key_swallows_unknown_sequences():
    # Shift+Down, Delete, Ctrl+Right, F5: each must come back as ONE
    # ignorable key with no residue bytes leaking in as phantom presses.
    for seq in (b"\x1b[1;2B", b"\x1b[3~", b"\x1b[1;5C", b"\x1b[15~"):
        assert _keys_from_bytes(seq) == ["ignore"], seq


def test_read_key_plain_and_special():
    assert _keys_from_bytes(b"\rq \x7f") == ["enter", "q", "space", "backspace"]


# ------------------------------------------------------------------- select ---
def _scripted(keys):
    """A read() callable that pops one key per call from a list."""
    it = iter(keys)
    return lambda: next(it, "")


def test_select_returns_highlighted_option():
    chosen = tui.select(
        "pick", ["a", "b", "c"],
        read=_scripted(["down", "down", "enter"]),
        render=lambda *a, **k: 0,
    )
    assert chosen == "c"


def test_select_cancel_returns_none():
    chosen = tui.select(
        "pick", ["a", "b"],
        read=_scripted(["q"]),
        render=lambda *a, **k: 0,
    )
    assert chosen is None


def test_select_digit_jumps_and_selects():
    # A 1-9 digit press picks that row immediately (no enter needed).
    chosen = tui.select(
        "pick", ["a", "b", "c", "d"],
        read=_scripted(["3"]),
        render=lambda *a, **k: 0,
    )
    assert chosen == "c"


def test_select_ignores_swallowed_sequences():
    chosen = tui.select(
        "pick", ["a", "b"],
        read=_scripted(["ignore", "down", "enter"]),
        render=lambda *a, **k: 0,
    )
    assert chosen == "b"


# -------------------------------------------------------------- multiselect ---
def test_multiselect_toggles_and_confirms():
    picked = tui.multiselect(
        "pick", ["x", "y", "z"],
        read=_scripted(["space", "down", "down", "space", "enter"]),
        render=lambda *a, **k: 0,
    )
    assert picked == ["x", "z"]


def test_multiselect_cancel():
    picked = tui.multiselect(
        "pick", ["x", "y"],
        read=_scripted(["space", "q"]),
        render=lambda *a, **k: 0,
    )
    assert picked is None


def test_multiselect_require_one_refuses_empty_enter():
    # First enter is refused (nothing toggled); space + enter then succeeds.
    picked = tui.multiselect(
        "pick", ["x", "y"], require_one=True,
        read=_scripted(["enter", "space", "enter"]),
        render=lambda *a, **k: 0,
    )
    assert picked == ["x"]


def test_multiselect_dumb_fallback(monkeypatch):
    monkeypatch.setattr(tui, "is_interactive", lambda: False)
    monkeypatch.setattr("builtins.input", lambda *a: "1, 3")
    picked = tui.multiselect("pick", ["x", "y", "z"])
    assert picked == ["x", "z"]


def test_multiselect_dumb_fallback_blank_cancels(monkeypatch):
    monkeypatch.setattr(tui, "is_interactive", lambda: False)
    monkeypatch.setattr("builtins.input", lambda *a: "")
    assert tui.multiselect("pick", ["x", "y"]) is None


# ------------------------------------------------------------------ confirm ---
def test_confirm_yes_no_and_default():
    assert tui.confirm("ok?", read=_scripted(["y"])) is True
    assert tui.confirm("ok?", read=_scripted(["n"])) is False
    assert tui.confirm("ok?", default=True, read=_scripted(["enter"])) is True
    assert tui.confirm("ok?", default=False, read=_scripted(["enter"])) is False


# ------------------------------------------------------------- accessibility ---
def test_gtheme_plain_forces_non_interactive(monkeypatch):
    monkeypatch.setenv("GTHEME_PLAIN", "1")
    assert tui.is_interactive() is False


# ----------------------------------------------------- menu arg construction ---
def test_ns_defaults_are_complete():
    ns = menu._ns(name="nsx")
    # Every attribute the cmd_* handlers read must be present with a default.
    for attr in ("name", "only", "dry_run", "no_sudo", "no_hooks", "yes",
                 "wipe", "summary", "force", "insecure", "allow_unsafe",
                 "source", "query", "title", "output", "verbose"):
        assert hasattr(ns, attr), attr
    assert ns.name == "nsx"
    assert getattr(ns, "from") is None


def test_ns_from_base_maps_to_reserved_attr():
    ns = menu._ns(name="ocean", from_base="nsx")
    assert getattr(ns, "from") == "nsx"


# ------------------------------------------------------------- ansi helpers ---
def test_gradient_is_plain_when_color_disabled(monkeypatch):
    # With colour depth 0, gradient must return the text untouched.
    monkeypatch.setattr(ansi, "_DEPTH", 0)
    assert ansi.gradient("hello", "#000000", "#ffffff") == "hello"


def test_strip_and_visible_len():
    styled = "\033[1mbold\033[0m and \033[38;2;1;2;3mrgb\033[0m"
    assert ansi.strip(styled) == "bold and rgb"
    assert ansi.visible_len(styled) == len("bold and rgb")


def test_truncate_is_ansi_aware():
    styled = "\033[1m" + "x" * 20 + "\033[0m"
    cut = ansi.truncate(styled, 10)
    assert ansi.visible_len(cut) <= 10
    assert ansi.strip(cut).startswith("xxxxxxxxx")
    # Plain strings truncate too, and short ones pass through untouched.
    assert ansi.strip(ansi.truncate("hello world", 6)).startswith("hello")
    assert ansi.truncate("hi", 10) == "hi"


def test_pad_counts_visible_cells():
    styled = "\033[1mab\033[0m"
    assert ansi.visible_len(ansi.pad(styled, 6)) == 6
    assert ansi.pad("ab", 4) == "ab  "


def test_ansi256_quantization_bounds():
    assert 16 <= ansi._ansi256(255, 0, 0) <= 231
    assert 232 <= ansi._ansi256(128, 128, 128) <= 255  # grey ramp
    assert ansi._ansi256(0, 0, 0) == 16
    assert ansi._ansi256(255, 255, 255) == 231
