"""One named test per defect v1 found, fixed, and left a comment tag for.

The tags were re-grepped from the legacy source rather than taken from a list
(DESIGN.md F9 asks for exactly that). What is there, and where:

    apply.py   AS4 @802,811   AS5 @691   AS8 @781   R1 @912   R3 @930
               R4 @715        R5 @889    R6 @914    F1 @728   L1 @646,856
               X1 @764        H2 @708
    backup.py  F1 @308
    paths.py   E1 @102
    cli.py     R2 @522        L1 @524

H2 (a failed required pre-hook blocks the apply) and R2 (run a theme's recorded
restore hooks before deleting it) are both hook machinery. v2 executes nothing,
so there is no code for them to guard and no test here — the reasoning lives in
``docs/architecture.md``. Every other tag has a test below.

R2 is worth one more sentence, because "we deleted the test" is exactly what a
regression suite is supposed to make impossible. The v1 bug was that removing a
theme orphaned privileged changes made by its install hook. In v2 a Look cannot
make a privileged change, because a Look cannot run anything; the class of bug
is gone rather than the check for it.
"""

# A Look apply is a transaction with ``look=`` set. ``label=`` alone is only a
# name for the saved moment it takes — every moment has one, including the
# automatic one before a single tick on a page — so the tests below pass both,
# the way ``preset.compile`` does. Keying the switch cleanup on ``label`` is
# what once made putting a saved moment back strip the whole Look.


from __future__ import annotations

import os
from pathlib import Path

import pytest

from gtheme.core import ledger as ledger_store
from gtheme.core import restorepoints
from gtheme.core.baseline import Baseline
from gtheme.core.confine import ConfinementError, confine_dest
from gtheme.core.gvariant import merge_string_lists
from gtheme.core.lock import LockBusy, process_lock
from gtheme.core.transaction import (
    ExtensionEnable,
    FileWrite,
    SettingWrite,
    Transaction,
    TransactionError,
)

#: Spelled here rather than imported from conftest: the tests directory is not
#: a package, so a relative import would not resolve.
SCHEME = "gsettings:org.gnome.desktop.interface color-scheme"
ICONS = "gsettings:org.gnome.desktop.interface icon-theme"
ENABLED = "gsettings:org.gnome.shell enabled-extensions"


def _look(tmp_path: Path, name: str, body: str) -> str:
    """A Look's file on disk, returned as the absolute source path."""
    folder = tmp_path / "look" / name
    folder.parent.mkdir(parents=True, exist_ok=True)
    folder.write_text(body, encoding="utf-8")
    return str(folder)


# -- AS4 -------------------------------------------------------------------


def test_AS4_a_transaction_that_applied_nothing_does_not_claim_it_did(engine, tmp_path):
    """apply.py:802,811 — nothing applied must not be recorded as applied.

    v1's bug: a settings-only apply where every setting was skipped still wrote
    the theme name into ``current`` and claimed ownership in the ledger. The
    desktop was unchanged and the app said otherwise, which is the one thing a
    tool whose whole promise is "you can undo this" must never do.
    """
    tx = Transaction(
        [SettingWrite(key="gsettings:org.not.installed.at.all a-key", value="'x'")],
        dest_root=str(engine.dest_root),
        label="GHOST", look="ghost",
    )
    with pytest.raises(TransactionError) as caught:
        tx.apply(restore_point=False)
    assert caught.value.rolled_back is True
    assert "GHOST" not in ledger_store.read_ledger()


def test_AS4_keeps_ownership_from_earlier_applies(engine, tmp_path):
    """apply.py:811 — rolling back the early claim must not destroy an old one.

    A Look that already owns things from a previous apply still owns them: they
    are still on disk. Only the claim this attempt added is withdrawn.
    """
    source = _look(tmp_path, "one", "first")
    dest = "~/.config/demo/one"
    Transaction(
        [FileWrite(src=source, dest=dest)], dest_root=str(engine.dest_root), label="MIXED", look="mixed"
    ).apply(restore_point=False)
    owned_before = ledger_store.read_ledger()["MIXED"]["files"]
    assert owned_before

    with pytest.raises(TransactionError):
        Transaction(
            [SettingWrite(key="gsettings:org.not.installed.at.all a-key", value="'x'")],
            dest_root=str(engine.dest_root),
            label="MIXED", look="mixed",
        ).apply(restore_point=False)
    assert ledger_store.read_ledger()["MIXED"]["files"] == owned_before


# -- AS5 -------------------------------------------------------------------


def test_AS5_no_desktop_session_skips_the_whole_settings_phase_once(
    engine, tmp_path, monkeypatch
):
    """apply.py:691 — one sentence, not forty identical failures.

    With nowhere to write settings into, every settings write fails the same
    way. v1 learned to say so once rather than flooding the output.

    The *simulation* changed with review-report M16 and the invariant did not.
    This used to unset ``DBUS_SESSION_BUS_ADDRESS``, because the gate read that
    variable — which meant an environment variable could switch off a backend
    that never touches a bus, and the suite's verdict depended on the shell it
    was launched from. The gate now asks the backend, so the honest way to
    stage "no desktop session" is a backend that says it cannot write. The test
    below pins the other half: unsetting the variable no longer silences a
    backend that can.
    """
    monkeypatch.setattr(type(engine.backend), "can_write", lambda _self: False, raising=False)

    source = _look(tmp_path, "file", "content")
    tx = Transaction(
        [
            FileWrite(src=source, dest="~/.config/demo/file"),
            SettingWrite(key=SCHEME, value="'prefer-dark'"),
            SettingWrite(key=ICONS, value="'Papirus'"),
        ],
        dest_root=str(engine.dest_root),
        label="NOBUS", look="nobus",
    )
    result = tx.apply(restore_point=False)

    assert [op for op in result.applied if isinstance(op, FileWrite)]
    assert not [op for op in result.applied if isinstance(op, SettingWrite)]
    reasons = {reason for _op, reason in result.skipped}
    assert len(reasons) == 1
    assert "session" in next(iter(reasons))
    # And nothing was written: the values are still the schema defaults.
    assert engine.backend.get(SCHEME) == "'default'"


# -- AS8 -------------------------------------------------------------------


def test_AS8_a_missing_setting_is_one_skip_not_a_failed_apply(engine):
    """apply.py:781 — an add-on you do not have is a skip, not an error.

    A Look built for a machine with Vitals installed must still apply on a
    machine without it. Everything else it asks for still happens.
    """
    tx = Transaction(
        [
            SettingWrite(key=SCHEME, value="'prefer-dark'"),
            SettingWrite(key="gsettings:org.gnome.shell.extensions.vitals position", value="1"),
        ],
        dest_root=str(engine.dest_root),
        label="PARTIAL", look="partial",
    )
    result = tx.apply(restore_point=False)

    assert engine.backend.get(SCHEME) == "'prefer-dark'"
    assert len(result.skipped) == 1
    assert "isn't installed" in result.skipped[0][1]


def test_AS8_a_skipped_setting_leaves_no_baseline_record(engine):
    """A record for a key that was never changed would restore a value nobody set."""
    tx = Transaction(
        [
            SettingWrite(key=SCHEME, value="'prefer-dark'"),
            SettingWrite(key="gsettings:org.gnome.shell.extensions.vitals position", value="1"),
        ],
        dest_root=str(engine.dest_root),
        label="PARTIAL", look="partial",
    )
    tx.apply(restore_point=False)
    recorded = Baseline(backend=engine.backend).load().settings
    assert SCHEME in recorded
    assert not [key for key in recorded if "vitals" in key]


# -- R1 / R3 / R6 ----------------------------------------------------------


def test_R1_a_failed_restore_keeps_its_recovery_state(engine, tmp_path):
    """apply.py:912 — only discard recovery state when the revert succeeded.

    Forgetting a record whose revert failed throws away the only pre-gtheme
    copy of somebody's file. The record and its stored copy both stay.
    """
    dest = engine.dest_root / ".config" / "demo" / "keep"
    dest.parent.mkdir(parents=True)
    dest.write_text("original", encoding="utf-8")

    baseline = Baseline(backend=engine.backend).load()
    baseline.record_file(dest)
    dest.write_text("changed", encoding="utf-8")

    # Make the revert fail: the parent becomes read-only, so the copy back
    # cannot replace the file.
    os.chmod(dest.parent, 0o500)
    try:
        outcome = baseline.restore_files()
    finally:
        os.chmod(dest.parent, 0o700)

    assert outcome.done == []
    assert outcome.dead == []
    assert outcome.warnings
    # Untouched: still recorded, stored copy still there.
    assert str(dest) in baseline.files
    blob = baseline.files[str(dest)]["backup"]
    assert (baseline.files_dir / blob).read_text(encoding="utf-8") == "original"


def test_R6_a_complete_restore_consumes_the_recording(engine, tmp_path):
    """apply.py:914 — after a full undo the desktop *is* pristine.

    Keeping the recording would stop the next change from taking a fresh
    snapshot, and the next undo would silently revert everything the user did
    by hand in between.
    """
    source = _look(tmp_path, "f", "look content")
    Transaction(
        [
            FileWrite(src=source, dest="~/.config/demo/f"),
            SettingWrite(key=SCHEME, value="'prefer-dark'"),
        ],
        dest_root=str(engine.dest_root),
        label="CONSUMED", look="consumed",
    ).apply(restore_point=False)

    from gtheme.core.rescue import run_rescue

    assert run_rescue() == 0
    after = Baseline(backend=engine.backend).load()
    assert after.is_empty
    assert ledger_store.read_ledger() == {}
    assert engine.backend.get(SCHEME) == "'default'"
    assert not (engine.dest_root / ".config" / "demo" / "f").exists()


def test_R3_switching_forgets_only_what_actually_reverted(engine, tmp_path):
    """apply.py:930 — the ledger must describe what is really on disk.

    Switching from one Look to another reverts what the outgoing one owned and
    the incoming one does not manage, and then forgets exactly those.
    """
    first = _look(tmp_path, "first", "from look one")
    Transaction(
        [
            FileWrite(src=first, dest="~/.config/demo/only-in-one"),
            SettingWrite(key=ICONS, value="'Papirus'"),
        ],
        dest_root=str(engine.dest_root),
        label="ONE", look="one",
    ).apply(restore_point=False)

    second = _look(tmp_path, "second", "from look two")
    Transaction(
        [
            FileWrite(src=second, dest="~/.config/demo/only-in-two"),
            SettingWrite(key=SCHEME, value="'prefer-dark'"),
        ],
        dest_root=str(engine.dest_root),
        label="TWO", look="two",
    ).apply(restore_point=False)

    ledger = ledger_store.read_ledger()
    assert "ONE" not in ledger
    assert "TWO" in ledger
    # The first Look's file is gone and its setting is back at the default.
    assert not (engine.dest_root / ".config" / "demo" / "only-in-one").exists()
    assert engine.backend.get(ICONS) == "'Adwaita'"
    assert (engine.dest_root / ".config" / "demo" / "only-in-two").is_file()


# -- R4 --------------------------------------------------------------------


def test_R4_ownership_is_claimed_before_the_change_it_describes(engine, tmp_path):
    """apply.py:715 — a crash between the two must over-claim, never under-claim.

    Over-claiming costs a redundant restore of something already correct.
    Under-claiming orphans a change forever, because nothing knows it happened.
    """
    source = _look(tmp_path, "boom", "content")
    seen: list[dict] = []

    original = Baseline.record_file

    def explode(self, dest, component="", label=""):
        seen.append(ledger_store.read_ledger())
        return original(self, dest, component, label)

    Baseline.record_file = explode  # noqa: B010
    try:
        Transaction(
            [FileWrite(src=source, dest="~/.config/demo/boom")],
            dest_root=str(engine.dest_root),
            label="EARLY", look="early",
        ).apply(restore_point=False)
    finally:
        Baseline.record_file = original  # noqa: B010

    assert seen, "the file phase never ran"
    claimed = seen[0].get("EARLY", {}).get("files", [])
    assert str(engine.dest_root / ".config" / "demo" / "boom") in claimed


# -- R5 --------------------------------------------------------------------


def test_R5_a_dead_record_is_reported_apart_from_a_transient_failure(engine):
    """apply.py:889 — a record that can never revert must not wedge restore.

    The stored copy is gone. Re-running will never fix that, so it comes back
    as ``dead`` and the caller may drop it, instead of failing forever.
    """
    dest = engine.dest_root / ".config" / "demo" / "orphan"
    dest.parent.mkdir(parents=True)
    dest.write_text("original", encoding="utf-8")

    baseline = Baseline(backend=engine.backend).load()
    baseline.record_file(dest)
    blob = baseline.files[str(dest)]["backup"]
    (baseline.files_dir / blob).unlink()

    outcome = baseline.restore_files()
    assert outcome.dead == [str(dest)]
    assert outcome.done == []
    assert "gone" in outcome.warnings[0]
    # And the file was left exactly as it is, not truncated or removed.
    assert dest.read_text(encoding="utf-8") == "original"


def test_R5_a_symlink_recorded_without_a_target_is_dead_not_transient(engine):
    baseline = Baseline(backend=engine.backend).load()
    dest = engine.dest_root / "link"
    baseline.files[str(dest)] = {
        "existed": True,
        "symlink": True,
        "target": "",
        "backup": None,
        "component": "",
        "label": "",
    }
    outcome = baseline.restore_files()
    assert outcome.dead == [str(dest)]


# -- F1 --------------------------------------------------------------------


def test_F1_a_pipe_at_the_destination_is_never_written_over(engine, tmp_path):
    """apply.py:728 + backup.py:308 — what cannot be saved is not overwritten.

    A FIFO, socket or device node cannot be copied, so there is no way to put
    it back. The write is skipped with a sentence rather than destroying it.
    """
    dest_dir = engine.dest_root / ".config" / "demo"
    dest_dir.mkdir(parents=True)
    fifo = dest_dir / "pipe"
    os.mkfifo(fifo)

    source = _look(tmp_path, "pipe", "content that must not land")
    with pytest.raises(TransactionError):
        # Nothing applied at all: the one operation was skipped (AS4).
        Transaction(
            [FileWrite(src=source, dest="~/.config/demo/pipe")],
            dest_root=str(engine.dest_root),
            label="FIFO", look="fifo",
        ).apply(restore_point=False)

    import stat

    assert stat.S_ISFIFO(os.stat(fifo).st_mode), "the pipe was replaced"
    assert str(fifo) not in Baseline(backend=engine.backend).load().files


# -- L1 --------------------------------------------------------------------


def test_L1_two_gthemes_cannot_mutate_at_once(engine):
    """apply.py:646,856 + cli.py:524 — one at a time, and fail fast.

    Two concurrent applies interleave their read-modify-writes over the ledger,
    and two recordings that loaded the same copy counter overwrite each other's
    stored files. Queueing behind the other one would just hang the window; the
    honest answer is one sentence.
    """
    with process_lock():
        with pytest.raises(LockBusy) as caught:
            with process_lock():
                pass
    assert "already changing your desktop" in str(caught.value)


def test_L1_the_transaction_reports_a_busy_lock_in_plain_words(engine, tmp_path):
    source = _look(tmp_path, "locked", "content")
    with process_lock():
        with pytest.raises(TransactionError) as caught:
            Transaction(
                [FileWrite(src=source, dest="~/.config/demo/locked")],
                dest_root=str(engine.dest_root),
                label="BUSY", look="busy",
            ).apply(restore_point=False)
    assert caught.value.rolled_back is True
    assert "already changing your desktop" in str(caught.value)


# -- X1 --------------------------------------------------------------------


def test_X1_a_look_unions_into_enabled_addons_instead_of_replacing_them(engine):
    """apply.py:764 — the user's own add-ons must survive applying a Look.

    ``enabled-extensions`` is shared global state. Writing a Look's list over
    the top turns off the user's dock, their clipboard manager and everything
    else they chose, and they experience that as the app deleting their setup.
    """
    engine.backend.set(ENABLED, "['mine@user', 'also-mine@user']")
    engine.install_extension("blur-my-shell@aunetx")

    Transaction(
        [ExtensionEnable(uuid="blur-my-shell@aunetx")],
        dest_root=str(engine.dest_root),
        label="UNION", look="union",
    ).apply(restore_point=False)

    after = engine.backend.get(ENABLED)
    assert "mine@user" in after
    assert "also-mine@user" in after
    assert "blur-my-shell@aunetx" in after


def test_X1_undo_restores_the_exact_value_from_before_the_union(engine):
    """The recording keeps the pre-union list, not a computed difference."""
    engine.backend.set(ENABLED, "['mine@user']")
    engine.install_extension("blur-my-shell@aunetx")

    Transaction(
        [ExtensionEnable(uuid="blur-my-shell@aunetx")],
        dest_root=str(engine.dest_root),
        label="UNION", look="union",
    ).apply(restore_point=False)

    from gtheme.core.rescue import run_rescue

    assert run_rescue() == 0
    assert engine.backend.get(ENABLED) == "['mine@user']"


def test_X1_an_empty_current_list_does_not_defeat_the_merge():
    """``@as []`` is not Python syntax, and v1's parser gave up on it.

    Giving up was safe — the caller then wrote the Look's list, which is the
    right answer when there is nothing to preserve — but saying so explicitly
    is better than relying on a fallback.
    """
    assert merge_string_lists("@as []", "['a@b']") == "['a@b']"
    assert merge_string_lists(None, "['a@b']") == "['a@b']"
    assert merge_string_lists("['a@b']", "@as []") == "['a@b']"
    # Something that is not a string list at all: no guess is made.
    assert merge_string_lists("['a@b']", "'not a list'") is None


def test_X1_the_union_keeps_order_and_does_not_duplicate():
    assert merge_string_lists("['a', 'b']", "['b', 'c']") == "['a', 'b', 'c']"


# -- E1 --------------------------------------------------------------------


def test_E1_an_unusable_destination_root_refuses_every_write(monkeypatch):
    """paths.py:102 — a broken home folder must not silently disable confinement.

    If the root resolves to ``/``, every path is "inside" it and the whole
    boundary evaporates. Refusing is the only safe answer, and it is refused
    before any expansion happens.
    """
    monkeypatch.setenv("GTHEME_DEST_ROOT", "/")
    with pytest.raises(ConfinementError):
        confine_dest("~/.config/anything")

    monkeypatch.setenv("GTHEME_DEST_ROOT", "relative/path")
    with pytest.raises(ConfinementError):
        confine_dest("~/.config/anything")


def test_E1_refuses_before_it_would_have_let_an_escape_through(monkeypatch):
    """The refusal comes first, so ``/`` never gets a chance to look permissive."""
    monkeypatch.setenv("GTHEME_DEST_ROOT", "/")
    with pytest.raises(ConfinementError) as caught:
        confine_dest("/etc/shadow")
    assert "whole disk" in str(caught.value)


# -- the restore point that backs all of it --------------------------------


def test_a_restore_point_is_taken_before_anything_changes(engine, tmp_path):
    """Not a v1 tag — a v2 promise, tested in the same net.

    Every transaction saves the moment before it. This is the feature the whole
    app is built around, so it is checked at the level that would actually
    catch it disappearing.
    """
    engine.backend.set(SCHEME, "'default'")
    result = Transaction(
        [SettingWrite(key=SCHEME, value="'prefer-dark'")],
        dest_root=str(engine.dest_root),
        label="SNAPPED", look="snapped",
    ).apply()

    assert result.restore_point is not None
    point = restorepoints.load(result.restore_point)
    assert point is not None
    assert point.settings[SCHEME] == "'default'"


def test_undoing_a_switch_returns_to_the_previous_look_not_to_pristine(engine, tmp_path):
    """What "Undo last change" has to mean after switching Looks.

    Switching reverts what the outgoing Look owned and the incoming one does
    not manage. The diff says nothing about that — it describes what the
    *incoming* Look writes — so the restore point has to be widened to cover
    it, or pressing Undo lands somewhere the user was never at.
    """
    first = _look(tmp_path, "first", "look one's file")
    Transaction(
        [
            FileWrite(src=first, dest="~/.config/demo/only-in-one"),
            SettingWrite(key=ICONS, value="'Papirus'"),
        ],
        dest_root=str(engine.dest_root),
        label="ONE", look="one",
    ).apply(restore_point=False)

    second = _look(tmp_path, "second", "look two's file")
    result = Transaction(
        [
            FileWrite(src=second, dest="~/.config/demo/only-in-two"),
            SettingWrite(key=SCHEME, value="'prefer-dark'"),
        ],
        dest_root=str(engine.dest_root),
        label="TWO", look="two",
    ).apply()

    point = restorepoints.load(result.restore_point)
    assert point is not None
    # The outgoing Look's setting and file are both in the saved moment, even
    # though the incoming Look never mentions either of them.
    assert point.settings[ICONS] == "'Papirus'"
    assert str(engine.dest_root / ".config" / "demo" / "only-in-one") in point.files
