"""Unit tests for the interactive TUI primitives and the menu's arg-building.

These exercise the pure parts — navigation state machine, the injectable
select/multiselect/confirm loops, and the Namespace the menu hands to the
cmd_* handlers — without needing a real terminal.
"""

from __future__ import annotations

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


def _scripted(keys):
    """A read() callable that pops one key per call from a list."""
    it = iter(keys)
    return lambda: next(it, "")


# ------------------------------------------------------------------- select ---
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


def test_select_number_jump():
    chosen = tui.select(
        "pick", ["a", "b", "c", "d"],
        read=_scripted(["3", "enter"]),
        render=lambda *a, **k: 0,
    )
    assert chosen == "c"


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


# ------------------------------------------------------------------ confirm ---
def test_confirm_yes_no_and_default():
    assert tui.confirm("ok?", read=_scripted(["y"])) is True
    assert tui.confirm("ok?", read=_scripted(["n"])) is False
    assert tui.confirm("ok?", default=True, read=_scripted(["enter"])) is True
    assert tui.confirm("ok?", default=False, read=_scripted(["enter"])) is False


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


# --------------------------------------------------------------- gradient ---
def test_gradient_is_plain_when_color_disabled(monkeypatch):
    # With truecolor off, gradient must return the text untouched.
    monkeypatch.setattr(tui.ansi, "_TRUECOLOR", False)
    assert tui.ansi.gradient("hello", "#000000", "#ffffff") == "hello"
