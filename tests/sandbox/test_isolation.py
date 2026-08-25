"""The isolation proof: a write inside the sandbox must not reach the desktop.

Everything else in this tier rests on this file. If the sandbox leaked, every
other sandbox test would be quietly editing the machine it runs on, and the
first symptom would be somebody's wallpaper changing during a test run.

The canary in ``conftest.py`` already runs around every test here. These tests
attack the question directly instead: write a value that could not possibly
occur naturally, then look for it in the live session from the outside.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import canary
import pytest
from sandboxlib import DataMode, SandboxSession

pytestmark = pytest.mark.sandbox

CANARY_VALUE = "SANDBOX-CANARY-DO-NOT-LEAK"


def _live(*argv: str) -> str:
    """Read something from the LIVE session. Reads only, never writes."""
    return subprocess.run(
        list(argv), capture_output=True, text=True, check=False, timeout=30
    ).stdout.strip()


def test_the_private_bus_is_not_the_live_bus(sandbox_shared_data: SandboxSession):
    assert sandbox_shared_data.bus
    assert sandbox_shared_data.bus != os.environ.get("DBUS_SESSION_BUS_ADDRESS")
    assert sandbox_shared_data.bus.startswith("unix:")


@pytest.mark.mutating
def test_a_canary_write_lands_in_the_sandbox_and_nowhere_else(
    sandbox_shared_data: SandboxSession,
):
    """The decisive test. Same shape as the proof script that established it."""
    session = sandbox_shared_data
    live_before = _live("gsettings", "get", "org.gnome.desktop.interface", "gtk-theme")

    session.gsettings("set", "org.gnome.desktop.interface", "gtk-theme", CANARY_VALUE)

    inside = session.gsettings("get", "org.gnome.desktop.interface", "gtk-theme").stdout
    assert CANARY_VALUE in inside, (
        "the canary did not stick inside the sandbox, so this run proves nothing "
        f"about isolation: {inside!r}"
    )

    live_after = _live("gsettings", "get", "org.gnome.desktop.interface", "gtk-theme")
    assert CANARY_VALUE not in live_after, "THE CANARY LEAKED INTO THE LIVE SESSION"
    assert live_after == live_before

    dump = _live("dconf", "dump", "/")
    assert CANARY_VALUE not in dump, "the canary reached the live dconf store"

    # And it is genuinely in the private store on disk, not merely in a
    # process's memory: a value that never hit a store would also fail to leak.
    store = session.dconf_store
    assert store.is_file(), f"no private dconf store at {store}"
    assert CANARY_VALUE.encode() in store.read_bytes()

    # Leave the session as it was found: the fixture is session-scoped, and a
    # nonexistent gtk-theme would follow the next test into its screenshots.
    session.gsettings("reset", "org.gnome.desktop.interface", "gtk-theme")


def test_the_private_store_is_under_the_temporary_root(
    sandbox_shared_data: SandboxSession,
):
    store = sandbox_shared_data.dconf_store
    assert sandbox_shared_data.root in store.parents
    assert Path.home() / ".config" / "dconf" not in store.parents


def test_shared_mode_can_see_the_users_extensions_read_only(
    sandbox_shared_data: SandboxSession,
):
    """SHARED mode exists so the page-walk sees the real machine."""
    assert sandbox_shared_data.mode is DataMode.SHARED
    assert sandbox_shared_data.data_home == Path.home() / ".local/share"
    known = sandbox_shared_data.known_uuids()
    assert "gtheme-sandbox@gtheme.local" in known


def test_private_mode_cannot_see_the_users_extensions(
    sandbox_private_data: SandboxSession,
):
    """PRIVATE mode is what every install/enable test must use."""
    session = sandbox_private_data
    assert session.mode is DataMode.PRIVATE
    assert session.root in session.data_home.parents
    assert session.extensions_dir.is_dir()

    seeded = {path.name for path in session.extensions_dir.iterdir()}
    assert "window-calls@domandoman.xyz" in seeded, "window-calls was not copied in"
    assert len(seeded) > 5, f"the fixture corpus was not seeded: {sorted(seeded)}"

    # The user's private extension is the sharpest test: it exists on this
    # machine and must not be visible from a private-data session.
    assert "intellibar@nightbloom.local" not in seeded


@pytest.mark.mutating
def test_the_user_extensions_directory_was_not_written_to(
    sandbox_private_data: SandboxSession,
):
    """Explicit, on top of the autouse canary, because this is the scary one."""
    session = sandbox_private_data
    user_dir = Path.home() / ".local/share/gnome-shell/extensions"
    before = canary.tree_hash(user_dir)
    was = session.gsettings("get", "org.gnome.shell", "enabled-extensions").stdout.strip()
    try:
        session.gsettings(
            "set", "org.gnome.shell", "enabled-extensions", "['probe@nowhere.local']"
        )
        assert canary.tree_hash(user_dir) == before
    finally:
        # Session-scoped fixture: put the shell's own extensions back, or every
        # later test in this session runs without window-calls and Eval.
        session.gsettings("set", "org.gnome.shell", "enabled-extensions", was)


def test_the_canary_would_actually_notice(tmp_path: Path):
    """A canary that cannot fail is decoration. Prove this one can.

    Every failure mode the real canary watches for is exercised here against a
    throwaway tree: a changed file, a new file, a deleted file, a replaced
    symlink, and a directory that disappears entirely.
    """
    tree = tmp_path / "tree"
    (tree / "sub").mkdir(parents=True)
    (tree / "sub" / "a.txt").write_text("one", encoding="utf-8")
    (tree / "link").symlink_to("a.txt")
    base = canary.tree_hash(tree)

    (tree / "sub" / "a.txt").write_text("two", encoding="utf-8")
    assert canary.tree_hash(tree) != base, "an edited file went unnoticed"

    (tree / "sub" / "a.txt").write_text("one", encoding="utf-8")
    assert canary.tree_hash(tree) == base, "the hash is not stable for equal trees"

    (tree / "sub" / "b.txt").write_text("new", encoding="utf-8")
    assert canary.tree_hash(tree) != base, "a new file went unnoticed"
    (tree / "sub" / "b.txt").unlink()

    (tree / "link").unlink()
    (tree / "link").symlink_to("elsewhere.txt")
    assert canary.tree_hash(tree) != base, "a re-pointed symlink went unnoticed"

    assert canary.tree_hash(tmp_path / "missing") == canary.ABSENT


def test_the_canary_reports_what_moved(tmp_path: Path):
    """The failure message has to name the leak, not just say something moved."""
    before = canary.Snapshot(
        dconf_mtime_ns=1, dconf_size=10, enabled_extensions="['a']", trees={"x": "aaa"}
    )
    after = canary.Snapshot(
        dconf_mtime_ns=2, dconf_size=11, enabled_extensions="['a', 'b']", trees={"x": "bbb"}
    )
    with pytest.raises(AssertionError) as excinfo:
        canary.assert_unchanged(before, after, context="a test")
    message = str(excinfo.value)
    assert "THE LIVE DESKTOP WAS MODIFIED during a test" in message
    assert "dconf store was written" in message
    assert "enabled-extensions changed" in message
    assert "~/x changed on disk" in message
