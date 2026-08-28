"""The apply contract under failure, and the order the phases run in.

Everything here pins one finding from the review, and every one of them is a
place where the engine's own documented promise was true of some code paths and
not others:

* **H1** — only ``TransactionError`` reached the rollback. An unreadable
  snapshot or a settings failure that was not "not installed here" skipped it,
  deleted the journal, and left the ledger claiming a Look that was half on the
  desktop.
* **H9** — a failed switch reported ``rolled_back=True`` although the tidy-up
  had already stripped the outgoing Look off the desktop, and pointed
  ``current`` back at that Look.
* **M1** — the tidy-up's warnings were computed and thrown away.
* **M2** — a setting a Look did not have to change was claimed with no
  recording behind it, and wedged the previous Look's entry forever.
* **M12** — an unfilled ``{{ }}`` token in a *value* was written through
  literally.
* **M16** — the settings phase asked an environment variable instead of the
  backend whether it could write.
* **L4** — a missing add-on went unreported when there was no session.
* **X1** — add-on settings were written before the add-on arrived.
* **H7** — a settings location that had never been written was read as a
  missing add-on and could therefore never be written.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from gtheme.core import ledger as ledger_store
from gtheme.core import transaction as transaction_module
from gtheme.core.baseline import Baseline, BaselineError
from gtheme.core.settings_backend import BackendError, BackendErrorKind, SettingsBackend
from gtheme.core.transaction import (
    ExtensionEnable,
    ExtensionInstall,
    FileWrite,
    Progress,
    SettingWrite,
    Transaction,
    TransactionError,
    TransactionResult,
)

SCHEME = "gsettings:org.gnome.desktop.interface color-scheme"
ICONS = "gsettings:org.gnome.desktop.interface icon-theme"
BLUR = "dconf:/org/gnome/shell/extensions/blur-my-shell/panel/blur"


def _apply(
    engine,
    ops,
    *,
    title: str = "DEMO",
    name: str = "demo",
    seen: list[tuple[Progress, str]] | None = None,
    backend: SettingsBackend | None = None,
    installer=None,
) -> TransactionResult:
    """Apply ``ops`` as a whole Look, the way ``preset.compile`` builds one."""
    tx = Transaction(ops, dest_root=str(engine.dest_root), label=title, look=name)
    if backend is not None:
        tx.backend = backend
    if installer is not None:
        tx.installer = installer
    report = (lambda stage, text: seen.append((stage, text))) if seen is not None else None
    return tx.apply(report, restore_point=False)


def _file(tmp_path: Path, name: str, body: str) -> str:
    target = tmp_path / "look" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return str(target)


# -- H1: everything that fails mid-apply unwinds ---------------------------


def test_a_snapshot_that_cannot_be_made_rolls_the_whole_apply_back(
    engine, tmp_path, monkeypatch
):
    """H1/P5. The write was guarded; the recording that must precede it was not.

    ``record_file`` copies the file it is about to let something overwrite. A
    full disk or an unreadable file there raised straight past the rollback,
    so the first file stayed on the desktop, the journal was deleted, and
    ``current`` still named the Look — which the app reported as "Nothing was
    changed. Your desktop is exactly as it was."
    """
    victim = engine.dest_root / ".config" / "demo" / "first.conf"
    victim.parent.mkdir(parents=True)
    victim.write_text("the user's own file", encoding="utf-8")

    real = Baseline.record_file

    def flaky(self, dest, component="", label=""):
        if Path(dest).name == "second.conf":
            raise BaselineError("could not write down what was at second.conf")
        return real(self, dest, component, label)

    monkeypatch.setattr(Baseline, "record_file", flaky)

    with pytest.raises(TransactionError) as caught:
        _apply(
            engine,
            [
                FileWrite(src=_file(tmp_path, "a", "the look's file"), dest="~/.config/demo/first.conf"),
                FileWrite(src=_file(tmp_path, "b", "the second"), dest="~/.config/demo/second.conf"),
            ],
            title="NEW",
            name="new",
        )

    assert caught.value.rolled_back is True
    assert "could not save the old value" in str(caught.value)
    assert victim.read_text(encoding="utf-8") == "the user's own file"
    assert ledger_store.current_look() is None, "a Look that did not land is not the current one"
    assert "NEW" not in ledger_store.read_ledger()


def test_a_settings_failure_that_is_not_a_missing_add_on_unwinds_too(engine, tmp_path):
    """H1's second trigger: any read failure that is not "not installed here".

    A dead settings service, a missing ``dconf`` binary, a refused read — all
    of them came out of the *unguarded* recording call as a ``BackendError``,
    which is not a ``TransactionError`` and so never reached the rollback.
    """

    class Sulking(SettingsBackend):
        """Answers normally, except for one key it refuses to talk about."""

        def __init__(self, inner: SettingsBackend, refuse: str) -> None:
            super().__init__(inner.schema_source)
            self.inner = inner
            self.refuse = refuse

        def _guard(self, key: str) -> None:
            if key == self.refuse:
                raise BackendError(BackendErrorKind.OTHER, "the settings service is not answering")

        def get(self, key: str) -> str:
            self._guard(key)
            return self.inner.get(key)

        def set(self, key: str, value: str) -> None:
            self._guard(key)
            self.inner.set(key, value)

        def reset(self, key: str) -> None:
            self._guard(key)
            self.inner.reset(key)

    with pytest.raises(TransactionError) as caught:
        _apply(
            engine,
            [
                SettingWrite(key=SCHEME, value="'prefer-dark'", component="colors"),
                SettingWrite(key=ICONS, value="'Papirus'", component="icons"),
            ],
            title="NEW",
            name="new",
            backend=Sulking(engine.backend, ICONS),
        )

    assert caught.value.rolled_back is True
    assert engine.backend.get(SCHEME) == "'default'", "the first write did not come back"
    assert ledger_store.current_look() is None


def test_a_change_that_lands_and_then_cannot_be_recorded_says_so(engine, monkeypatch):
    """H2/M3. The last two writes of an apply are after the ops, not before.

    ``baseline.save()`` and the closing ``write_entry`` run once every op has
    landed, outside every ``except`` — so a full or read-only
    ``~/.local/state`` sent a bare ``OSError`` out of ``apply()`` over a
    desktop that really had changed. Every caller reads ``TransactionError``
    for "did the desktop move?", so a bare ``OSError`` meant they could only
    guess, and one of them guessed the reassuring way: the style pages told the
    person "Your desktop is exactly as it was." with the setting sitting at its
    new value.

    Leaving by ``TransactionError`` with ``rolled_back=False`` is the whole
    fix: nothing was put back, and now the type says so.
    """
    real_save = Baseline.save

    def no_room(self):
        if "gtheme-rollback-" in str(self.dir):  # the journal must keep working
            return real_save(self)
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Baseline, "save", no_room)

    with pytest.raises(TransactionError) as caught:
        _apply(engine, [SettingWrite(key=SCHEME, value="'prefer-dark'", component="colors")])

    assert caught.value.rolled_back is False, (
        "the write landed and nothing put it back — claiming a rollback here is the H2 lie"
    )
    assert engine.backend.get(SCHEME) == "'prefer-dark'", "the premise: it really moved"
    assert isinstance(caught.value.__cause__, OSError)


def test_a_change_whose_closing_ledger_entry_fails_says_so_too(engine, monkeypatch):
    """The same hole, the other post-ops write: the ledger entry.

    Written separately because the two are separate statements with separate
    handlers, and a fix that guarded only the one the reviewer named would
    leave the other reachable by exactly the same full disk.
    """
    real_write = transaction_module.ledger_store.write_entry
    calls: list[int] = []

    def refuse_the_closing_entry(*args, **kwargs):
        calls.append(1)
        # R4 writes the claim first and replaces it afterwards; only the
        # second call is the one that runs after the ops.
        if len(calls) >= 2:
            raise OSError(28, "No space left on device")
        return real_write(*args, **kwargs)

    monkeypatch.setattr(
        transaction_module.ledger_store, "write_entry", refuse_the_closing_entry
    )

    with pytest.raises(TransactionError) as caught:
        _apply(engine, [SettingWrite(key=SCHEME, value="'prefer-dark'", component="colors")])

    assert caught.value.rolled_back is False
    assert engine.backend.get(SCHEME) == "'prefer-dark'"


# -- H9: a switch whose tidy-up already happened ---------------------------


def test_a_failed_switch_after_a_real_tidy_up_does_not_claim_nothing_changed(engine, tmp_path):
    """H9. Two questions, not one.

    The journal knows whether *this* transaction's operations came back. The
    switch cleanup ran before them and outside the journal, so a clean unwind
    is still not "your desktop is exactly as it was" — the previous Look is
    gone. And ``current`` must not be pointed back at that Look: its files were
    just deleted, so naming it would send Undo after something that is not
    there.
    """
    _apply(
        engine,
        [FileWrite(src=_file(tmp_path, "old.css", "the outgoing look"), dest="~/.config/demo/old.css")],
        title="OLD",
        name="old",
    )
    victim = engine.dest_root / ".config" / "demo" / "old.css"
    assert victim.is_file()

    seen: list[tuple[Progress, str]] = []
    with pytest.raises(TransactionError) as caught:
        _apply(
            engine,
            [
                FileWrite(src=_file(tmp_path, "new.css", "the incoming look"), dest="~/.config/demo/new.css"),
                # A number where the setting wants words: refused by the store,
                # so the ops fail after the file has already been written.
                SettingWrite(key=ICONS, value="42", component="icons"),
            ],
            title="NEW",
            name="new",
            seen=seen,
        )

    assert not victim.exists(), "the tidy-up really did revert the outgoing Look"
    assert not (engine.dest_root / ".config" / "demo" / "new.css").exists(), (
        "this transaction's own work did come back"
    )
    assert caught.value.rolled_back is False, "the previous Look is gone — do not say otherwise"
    assert ledger_store.current_look() is None, "never point back at a Look the tidy-up stripped"
    assert any("tidied up" in text for _stage, text in seen), seen
    assert "Nothing was changed" not in [text for _stage, text in seen]


# -- M1: the tidy-up's own warnings ----------------------------------------


def test_what_the_tidy_up_could_not_do_reaches_the_caller(engine, tmp_path):
    """M1. The sentences existed and nothing read them.

    A Look switch that cannot revert part of the outgoing Look is the case the
    ledger writes "the saved copy of them is gone" for. ``_apply_locked`` read
    only ``notes``, so the apply reported plain success and the user was told
    nothing at all.
    """
    theirs = engine.dest_root / ".config" / "demo" / "theirs.conf"
    theirs.parent.mkdir(parents=True)
    theirs.write_text("the user's own file", encoding="utf-8")

    _apply(
        engine,
        [FileWrite(src=_file(tmp_path, "old", "the outgoing look"), dest="~/.config/demo/theirs.conf")],
        title="OLD",
        name="old",
    )

    # The stored copy disappears — a wiped cache directory, a half-restored
    # backup. The record still claims it, and the restore cannot honour it.
    baseline = Baseline(backend=engine.backend).load()
    blob = baseline.files[str(theirs)]["backup"]
    (baseline.files_dir / blob).unlink()

    seen: list[tuple[Progress, str]] = []
    result = _apply(
        engine,
        [FileWrite(src=_file(tmp_path, "new", "the incoming look"), dest="~/.config/demo/new.conf")],
        title="NEW",
        name="new",
        seen=seen,
    )

    assert result.cleanup_dead == 1
    assert any("saved copy" in line for line in result.cleanup_warnings), result.cleanup_warnings
    assert any("saved copy" in text for _stage, text in seen), seen


# -- M2: claiming something that never changed -----------------------------


def test_a_setting_a_look_did_not_have_to_change_does_not_wedge_the_previous_look(engine):
    """M2. Trigger: the desktop is already dark and a Look "sets" dark.

    The write is a no-op, so no old value is ever recorded — but the key was
    still claimed in the ledger. The next switch then read a claim with no
    recording behind it as "could not be changed back automatically", kept the
    outgoing Look's entry alive, warned about it, and did the identical thing
    on every switch after that, forever.
    """
    engine.backend.set(SCHEME, "'prefer-dark'")
    _apply(
        engine,
        [SettingWrite(key=SCHEME, value="'prefer-dark'", component="colors")],
        title="A",
        name="a",
    )
    assert "A" in ledger_store.read_ledger(), "the claim itself is right (R4)"

    result = _apply(
        engine,
        [SettingWrite(key=ICONS, value="'Papirus'", component="icons")],
        title="B",
        name="b",
    )

    assert result.cleanup_kept == 0, "nothing to change back is a finished job"
    assert result.cleanup_warnings == []
    assert "A" not in ledger_store.read_ledger(), "the outgoing entry is dropped, not rewritten"
    assert engine.backend.get(SCHEME) == "'prefer-dark'", "and nothing was reverted behind them"


def test_something_that_really_failed_to_revert_still_keeps_its_claim(
    engine, tmp_path, monkeypatch
):
    """The other side of M2, and the invariant that must not be traded for it.

    "Nothing to change back" and "could not be changed back" look the same in a
    ledger entry and are opposites. An item that genuinely failed to revert
    keeps its record, its stored copy *and* the entry that claims it, so the
    Undo page can still recover it and the next switch tries again — a cleanup
    that cannot finish must degrade to "you can still undo this", never to
    "that is gone now".
    """
    from gtheme.core.baseline import RestoreOutcome

    _apply(
        engine,
        [FileWrite(src=_file(tmp_path, "old.css", "the outgoing look"), dest="~/.config/demo/old.css")],
        title="OLD",
        name="old",
    )

    monkeypatch.setattr(
        Baseline,
        "restore_only_files",
        lambda self, keys: RestoreOutcome(warnings=[f"could not put back {keys[0]}"]),
    )

    result = _apply(
        engine,
        [FileWrite(src=_file(tmp_path, "new.css", "the incoming look"), dest="~/.config/demo/new.css")],
        title="NEW",
        name="new",
    )

    assert result.cleanup_kept == 1
    assert any("could not be changed back" in line for line in result.cleanup_warnings)
    kept = ledger_store.read_ledger()["OLD"]["files"]
    assert kept == [str(engine.dest_root / ".config" / "demo" / "old.css")]


# -- M12: an unfilled token in a value -------------------------------------


def test_an_unfilled_token_in_a_value_skips_the_setting(engine, tmp_path):
    """M12. ``key_ok`` only ever looked at the key.

    ``docs/preset-format.md``: "Tokens work in key and value too", and an
    unresolvable one means the op is skipped, "never written half-resolved".
    The value half wrote ``file://{{ hoem }}/Pictures/x.png`` to the desktop
    and reported success.
    """
    result = _apply(
        engine,
        [
            FileWrite(src=_file(tmp_path, "a.css", "the look's file"), dest="~/.config/demo/a.css"),
            SettingWrite(key=ICONS, value="'{{ hoem }}-Papirus'", component="icons"),
        ],
        title="NEW",
        name="new",
    )

    assert engine.backend.get(ICONS) == "'Adwaita'", "nothing half-resolved may be written"
    reasons = [reason for _op, reason in result.skipped]
    assert any("hoem" in reason for reason in reasons), reasons
    assert any("not set up on this computer yet" in reason for reason in reasons), reasons


# -- L4 / X1: add-ons before settings --------------------------------------


def test_a_missing_add_on_is_reported_even_with_no_desktop_session(
    engine, tmp_path, monkeypatch
):
    """L4. The skip loop lived inside the phase the no-session guard skipped.

    Reading which add-ons are installed is a directory listing. It needs no
    session, so the user hearing "40 settings were left alone" and nothing at
    all about three add-ons they do not have was an accident of where the loop
    was written.
    """
    monkeypatch.setattr(transaction_module, "can_write_settings", lambda _backend: False)

    result = _apply(
        engine,
        [
            FileWrite(src=_file(tmp_path, "a.css", "the look's file"), dest="~/.config/demo/a.css"),
            SettingWrite(key=ICONS, value="'Papirus'", component="icons"),
            ExtensionInstall(uuid="absent@ext"),
        ],
        title="NEW",
        name="new",
    )

    reasons = [reason for _op, reason in result.skipped]
    assert any("Add-ons page" in reason for reason in reasons), reasons
    assert any("session" in reason for reason in reasons), reasons


def test_add_ons_arrive_before_the_settings_that_configure_them(engine, tmp_path):
    """X1. An add-on's settings do not exist until the add-on does.

    A Look that installs an add-on and then tunes it had every one of those
    settings answered with "that part of your desktop isn't installed here" —
    a skip nobody rendered, on a phase that ran before the add-on arrived. The
    tuning silently never happened and would have worked on a second apply
    nothing suggested.

    The preview still promises nothing about the download: a plan that said
    "and then it will be fetched" would be a promise the person reading it has
    not agreed to yet. Under-promising is the safe direction.
    """

    class LateArrival(SettingsBackend):
        """Refuses an add-on's settings until the add-on is on the machine."""

        def __init__(self, inner: SettingsBackend, uuid: str, keys: set[str]) -> None:
            super().__init__(inner.schema_source)
            self.inner = inner
            self.uuid = uuid
            self.keys = keys

        def _guard(self, key: str) -> None:
            if key in self.keys and self.uuid not in transaction_module.installed_extension_uuids():
                raise BackendError(BackendErrorKind.NO_SCHEMA, "the add-on is not installed")

        def get(self, key: str) -> str:
            self._guard(key)
            return self.inner.get(key)

        def set(self, key: str, value: str) -> None:
            self._guard(key)
            self.inner.set(key, value)

        def reset(self, key: str) -> None:
            self._guard(key)
            self.inner.reset(key)

    fetched: list[str] = []

    def installer(op: ExtensionInstall) -> bool:
        fetched.append(op.uuid)
        engine.install_extension(op.uuid)
        return True

    result = _apply(
        engine,
        [
            ExtensionInstall(uuid="late@ext", ego_pk=1234),
            ExtensionEnable(uuid="late@ext"),
            SettingWrite(key=ICONS, value="'Papirus'", component="addons"),
        ],
        title="NEW",
        name="new",
        backend=LateArrival(engine.backend, "late@ext", {ICONS}),
        installer=installer,
    )

    assert fetched == ["late@ext"]
    assert engine.backend.get(ICONS) == "'Papirus'", "the add-on's own settings were written"
    assert not [reason for _op, reason in result.skipped], result.skipped
    assert "late@ext" in engine.backend.get("gsettings:org.gnome.shell enabled-extensions")


def test_without_an_installer_a_missing_add_on_is_still_only_a_named_skip(engine, tmp_path):
    """Downloading needs the network and consent. The default fetches nothing."""
    result = _apply(
        engine,
        [
            FileWrite(src=_file(tmp_path, "a.css", "the look's file"), dest="~/.config/demo/a.css"),
            ExtensionInstall(uuid="absent@ext"),
        ],
        title="NEW",
        name="new",
    )
    assert [reason for _op, reason in result.skipped] == [
        "this add-on isn't installed yet — install it from the Add-ons page first"
    ]


# -- M16: the AS5 gate asks the backend ------------------------------------


def test_the_settings_phase_asks_the_backend_not_the_environment(
    engine, tmp_path, monkeypatch
):
    """M16. An environment variable could switch off a backend with no bus.

    The in-memory backend the suite installs writes nowhere real and needs no
    session at all, yet unsetting ``DBUS_SESSION_BUS_ADDRESS`` disabled the
    whole settings phase for it — so the suite's verdict depended on the shell
    it was launched from, and a packaged check in a clean chroot failed the
    gate outright.
    """
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "no-bus-here"))

    result = _apply(
        engine,
        [SettingWrite(key=ICONS, value="'Papirus'", component="icons")],
        title="NEW",
        name="new",
    )

    assert engine.backend.get(ICONS) == "'Papirus'"
    assert result.skipped == []


# -- H7: unset is not missing ----------------------------------------------


def test_a_location_that_was_never_written_is_a_change_not_a_missing_add_on(engine):
    """H7, from the transaction's side.

    A ``dconf:`` location that has never been written reads back empty. Reading
    that as "this add-on is not installed" made the write a skip, which left
    the location empty, which made the next apply skip it again — self-sealing,
    and eight of the shipped Looks' keys were in exactly that state on the
    author's own machine.
    """

    class NeverWritten(SettingsBackend):
        """A store where one location exists and holds nothing yet."""

        def __init__(self, path: str) -> None:
            super().__init__(None)
            self.path = path
            self.values: dict[str, str] = {}

        def get(self, key: str) -> str:
            if key not in self.values:
                if key == self.path:
                    raise BackendError(
                        BackendErrorKind.UNSET, "this location has never been set", key=key
                    )
                raise BackendError(BackendErrorKind.NO_KEY, "no such key", key=key)
            return self.values[key]

        def set(self, key: str, value: str) -> None:
            self.values[key] = value

        def reset(self, key: str) -> None:
            self.values.pop(key, None)

    backend = NeverWritten(BLUR)
    tx = Transaction(
        [SettingWrite(key=BLUR, value="true", component="addons")],
        dest_root=str(engine.dest_root),
        label="NEW",
        look="new",
    )
    tx.backend = backend

    entry = tx.plan().entries[0]
    assert (entry.before, entry.after, entry.no_op) == (None, "true", False), (
        "a location with no value yet is a real change, and the preview must say so"
    )

    result = tx.apply(restore_point=False)
    assert result.skipped == []
    assert backend.values[BLUR] == "true"

    # And the recording says "there was nothing here", so undo unsets it again
    # rather than writing back a value nobody chose.
    saved = Baseline(backend=backend).load().settings[BLUR]
    assert saved["saved"] is None


# -- L8: a Look built for a newer desktop ----------------------------------


@pytest.fixture
def _preset_factory() -> Iterator[Any]:
    from gtheme.preset.model import Preset

    def make(min_shell: str | None) -> Preset:
        meta: dict[str, Any] = {
            "name": "demo",
            "title": "DEMO",
            "description": "A Look for a test.",
            "author": "the suite",
            "version": "1.0.0",
        }
        if min_shell is not None:
            meta["min_shell"] = min_shell
        return Preset.model_validate({"format": 2, "meta": meta})

    yield make


def test_a_look_built_for_a_newer_desktop_says_so(tmp_path, _preset_factory):
    """L8. ``min_shell`` was documented, published in the index, and read nowhere.

    It never blocks — the documentation has always said so — and it never
    guesses: a desktop whose version could not be read is not evidence that a
    Look is too new for it.
    """
    from gtheme.preset.compile import compile_preset

    warned = compile_preset(_preset_factory("50"), tmp_path, shell_version="49").warnings
    assert any("newer version" in line for line in warned), warned
    assert not any("newer version" in line for line in warned if "49" not in line)

    assert compile_preset(_preset_factory("50"), tmp_path, shell_version="50").warnings == []
    assert compile_preset(_preset_factory("50"), tmp_path, shell_version=None).warnings == []
    assert compile_preset(_preset_factory(None), tmp_path, shell_version="49").warnings == []
