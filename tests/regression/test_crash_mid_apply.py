"""What survives a crash halfway through a change.

The guarantee is narrow and absolute: at every instant during an apply, the
recording on disk describes exactly what has been changed by then. Not an empty
recording that has not been written yet, and not a stale one from the last run.
So a power cut, an OOM kill or a Ctrl-C leaves a desktop that ``gtheme rescue``
can still put back.

That falls out of two decisions. Every record persists its own index the moment
it is made, rather than a single save at the end that a SIGKILL would skip. And
the ownership claim goes down *before* the change it describes (the R4 rule), so
an interruption between the two leaves a claim that is slightly too large rather
than a change nothing knows about.

These tests interrupt an apply for real — an exception raised from inside the
write loop — and then check what a fresh process would find.
"""

# A Look apply is a transaction with ``look=`` set. ``label=`` alone is only a
# name for the saved moment it takes — every moment has one, including the
# automatic one before a single tick on a page — so the tests below pass both,
# the way ``preset.compile`` does. Keying the switch cleanup on ``label`` is
# what once made putting a saved moment back strip the whole Look.


from __future__ import annotations

from pathlib import Path

import pytest

from gtheme.core import ledger as ledger_store
from gtheme.core.atomic import atomic_write_bytes
from gtheme.core.baseline import Baseline
from gtheme.core.transaction import FileWrite, SettingWrite, Transaction

SCHEME = "gsettings:org.gnome.desktop.interface color-scheme"
ICONS = "gsettings:org.gnome.desktop.interface icon-theme"


class Interrupted(BaseException):
    """Stands in for a SIGKILL: not an ``Exception``, so nothing catches it."""


def _look(tmp_path: Path, name: str, body: str) -> str:
    folder = tmp_path / "look"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    target.write_text(body, encoding="utf-8")
    return str(target)


def test_an_interrupted_apply_leaves_a_recording_that_covers_what_it_did(
    engine, tmp_path, monkeypatch
):
    """The half that happened is recoverable; the half that did not is untouched."""
    first = _look(tmp_path, "first", "look content one")
    second = _look(tmp_path, "second", "look content two")

    existing = engine.dest_root / ".config" / "demo" / "first"
    existing.parent.mkdir(parents=True)
    existing.write_text("the user's own file", encoding="utf-8")

    calls = {"n": 0}
    real = atomic_write_bytes

    def blow_up_on_the_second_file(dest, data, mode=None):
        calls["n"] += 1
        if calls["n"] == 2:
            raise Interrupted("power cut")
        real(dest, data, mode)

    monkeypatch.setattr(
        "gtheme.core.transaction.atomic_write_bytes", blow_up_on_the_second_file
    )

    tx = Transaction(
        [
            FileWrite(src=first, dest="~/.config/demo/first"),
            FileWrite(src=second, dest="~/.config/demo/second"),
        ],
        dest_root=str(engine.dest_root),
        label="CRASH", look="crash",
    )
    with pytest.raises(Interrupted):
        tx.apply(restore_point=False)

    # A fresh reader — as a new process would be — finds both files recorded:
    # the one that landed, and the one that was about to.
    fresh = Baseline(backend=engine.backend).load()
    assert str(existing) in fresh.files
    assert str(engine.dest_root / ".config" / "demo" / "second") in fresh.files

    # And the recorded copy is the user's file, not the Look's.
    blob = fresh.files[str(existing)]["backup"]
    assert (fresh.files_dir / blob).read_text(encoding="utf-8") == "the user's own file"


def test_rescue_after_an_interrupted_apply_puts_everything_back(
    engine, tmp_path, monkeypatch
):
    """The point of the recording: a rescue in a later process still works."""
    first = _look(tmp_path, "first", "look content one")
    second = _look(tmp_path, "second", "look content two")

    existing = engine.dest_root / ".config" / "demo" / "first"
    existing.parent.mkdir(parents=True)
    existing.write_text("the user's own file", encoding="utf-8")
    engine.backend.set(SCHEME, "'default'")

    calls = {"n": 0}
    real = atomic_write_bytes

    def blow_up_on_the_second_file(dest, data, mode=None):
        calls["n"] += 1
        if calls["n"] == 2:
            raise Interrupted("power cut")
        real(dest, data, mode)

    monkeypatch.setattr(
        "gtheme.core.transaction.atomic_write_bytes", blow_up_on_the_second_file
    )

    with pytest.raises(Interrupted):
        Transaction(
            [
                FileWrite(src=first, dest="~/.config/demo/first"),
                FileWrite(src=second, dest="~/.config/demo/second"),
            ],
            dest_root=str(engine.dest_root),
            label="CRASH", look="crash",
        ).apply(restore_point=False)

    assert existing.read_text(encoding="utf-8") == "look content one"

    from gtheme.core.rescue import run_rescue

    assert run_rescue() == 0
    assert existing.read_text(encoding="utf-8") == "the user's own file"
    assert not (engine.dest_root / ".config" / "demo" / "second").exists()


def test_the_ownership_claim_is_never_smaller_than_what_happened(
    engine, tmp_path, monkeypatch
):
    """R4 again, from the crash side: over-claiming is the safe direction.

    A claim that covers something already correct costs a redundant restore. A
    claim that misses something means nothing will ever undo it.
    """
    first = _look(tmp_path, "first", "one")
    second = _look(tmp_path, "second", "two")

    calls = {"n": 0}
    real = atomic_write_bytes

    def blow_up_on_the_second_file(dest, data, mode=None):
        calls["n"] += 1
        if calls["n"] == 2:
            raise Interrupted("power cut")
        real(dest, data, mode)

    monkeypatch.setattr(
        "gtheme.core.transaction.atomic_write_bytes", blow_up_on_the_second_file
    )

    with pytest.raises(Interrupted):
        Transaction(
            [
                FileWrite(src=first, dest="~/.config/demo/first"),
                FileWrite(src=second, dest="~/.config/demo/second"),
            ],
            dest_root=str(engine.dest_root),
            label="CLAIMS", look="claims",
        ).apply(restore_point=False)

    claimed = set(ledger_store.read_ledger()["CLAIMS"]["files"])
    written = {str(engine.dest_root / ".config" / "demo" / "first")}
    assert written <= claimed


def test_a_failure_rolls_the_whole_transaction_back(engine, tmp_path):
    """All of it or none of it — the property the preview dialog promises.

    A settings write that genuinely fails (not a missing add-on, which is a
    skip) must leave the desktop exactly as it was, including the parts that
    had already succeeded.
    """
    source = _look(tmp_path, "styled", "look content")
    engine.backend.set(ICONS, "'Adwaita'")

    class Refusing:
        """A backend that reads fine and refuses one particular write."""

        def __init__(self, real):
            self.real = real

        def get(self, key):
            return self.real.get(key)

        def reset(self, key):
            self.real.reset(key)

        def set(self, key, value):
            if key == SCHEME:
                from gtheme.core.settings_backend import BackendError, BackendErrorKind

                raise BackendError(BackendErrorKind.COMMIT_FAILED, "the store said no", key=key)
            self.real.set(key, value)

    from gtheme.core import backends

    tx = Transaction(
        [
            FileWrite(src=source, dest="~/.config/demo/styled"),
            SettingWrite(key=ICONS, value="'Papirus'"),
            SettingWrite(key=SCHEME, value="'prefer-dark'"),
        ],
        dest_root=str(engine.dest_root),
        label="ALLORNOTHING", look="allornothing",
    )
    with backends.use_backend(Refusing(engine.backend)):
        from gtheme.core.transaction import TransactionError

        with pytest.raises(TransactionError) as caught:
            tx.apply(restore_point=False)

    assert caught.value.rolled_back is True
    assert engine.backend.get(ICONS) == "'Adwaita'"
    assert not (engine.dest_root / ".config" / "demo" / "styled").exists()


def test_a_rolled_back_transaction_leaves_no_recording_behind(engine, tmp_path):
    """Records for changes that were undone would restore a moment that never was."""
    source = _look(tmp_path, "styled", "look content")

    class Refusing:
        def __init__(self, real):
            self.real = real

        def get(self, key):
            return self.real.get(key)

        def reset(self, key):
            self.real.reset(key)

        def set(self, key, value):
            from gtheme.core.settings_backend import BackendError, BackendErrorKind

            raise BackendError(BackendErrorKind.COMMIT_FAILED, "no", key=key)

    from gtheme.core import backends
    from gtheme.core.transaction import TransactionError

    with backends.use_backend(Refusing(engine.backend)):
        with pytest.raises(TransactionError):
            Transaction(
                [
                    FileWrite(src=source, dest="~/.config/demo/styled"),
                    SettingWrite(key=ICONS, value="'Papirus'"),
                ],
                dest_root=str(engine.dest_root),
                label="UNDONE", look="undone",
            ).apply(restore_point=False)

    fresh = Baseline(backend=engine.backend).load()
    assert fresh.is_empty
    assert "UNDONE" not in ledger_store.read_ledger()
