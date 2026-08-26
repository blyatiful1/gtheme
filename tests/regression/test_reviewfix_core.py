"""The safety engine's second net: one test per confirmed review finding.

Every test in this file pins a bug the 47-agent paranoid review confirmed
against the running code, and each names its finding in its docstring. They sit
beside the v1 defect-tag regressions because they are the same kind of thing —
a lesson that must not be re-learned — only these were paid for by v2 rather
than by v1.

The spine of the group is the label-versus-look confusion. ``Transaction.label``
is a *name for a saved moment*; ``Transaction.look`` is "a whole Look is being
applied". Keying the Look-switch cleanup on ``label`` meant every saved moment
being put back ran the cleanup, so undoing one small tweak reverted the entire
applied Look — the app's headline promise, broken. Several findings collapse
into that one distinction, and the tests below hold each of them down
separately so the next person to touch the flag learns it from a failure and
not from a stripped desktop.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from gtheme.core import backends, placeholders, restorepoints
from gtheme.core import ledger as ledger_store
from gtheme.core.baseline import Baseline
from gtheme.core.settings_backend import (
    BackendError,
    BackendErrorKind,
    MemoryBackend,
)
from gtheme.core.transaction import (
    ExtensionEnable,
    FileWrite,
    Progress,
    SettingWrite,
    Transaction,
    TransactionError,
)

SCHEMA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<schemalist>
  <schema id="org.gnome.shell" path="/org/gnome/shell/">
    <key name="enabled-extensions" type="as"><default>[]</default></key>
  </schema>
  <schema id="org.gnome.desktop.interface" path="/org/gnome/desktop/interface/">
    <key name="icon-theme" type="s"><default>'Adwaita'</default></key>
  </schema>
  <schema id="org.gnome.Ptyxis" path="/org/gnome/Ptyxis/">
    <key name="default-profile-uuid" type="s"><default>''</default></key>
  </schema>
  <schema id="org.gtheme.test" path="/org/gtheme/test/">
    <key name="a-word" type="s"><default>'default'</default></key>
  </schema>
  <schema id="org.gtheme.test.profile">
    <key name="palette" type="s"><default>'none'</default></key>
  </schema>
  <schema id="org.gtheme.test.owned" path="/org/gtheme/test/owned/">
    <key name="a-word" type="s"><default>'default'</default></key>
  </schema>
</schemalist>
"""

WORD = "gsettings:org.gtheme.test a-word"
ICONS = "gsettings:org.gnome.desktop.interface icon-theme"
PTYXIS_DEFAULT = "gsettings:org.gnome.Ptyxis default-profile-uuid"
#: A Look's terminal-palette key, token and all — the shape hyperclass, magma
#: and netrunner all ship.
TOKEN_KEY = (
    "gsettings-path:org.gtheme.test.profile:"
    "/org/gtheme/profiles/{{ ptyxis_default_profile }}/ palette"
)


@dataclass
class Bench:
    backend: MemoryBackend
    root: Path
    look: Path
    extensions: Path

    def add_file(self, name: str, body: str) -> str:
        target = self.look / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        return str(target)

    def install(self, uuid: str) -> None:
        (self.extensions / uuid).mkdir(parents=True, exist_ok=True)


@pytest.fixture
def bench(
    memory_settings,
    tmp_dest_root: Path,
    state_dir: Path,
    schema_source_factory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Bench]:
    """An engine that reaches nothing real.

    ``memory_settings``, ``tmp_dest_root`` and ``state_dir`` are requested for
    the isolation guard in ``tests/conftest.py``, which reads fixture names.
    """
    del memory_settings
    backend = MemoryBackend(schema_source=schema_source_factory(SCHEMA_XML))
    look = tmp_path / "look"
    look.mkdir()
    data_home = tmp_path / "data"
    extensions = data_home / "gnome-shell" / "extensions"
    extensions.mkdir(parents=True)
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    placeholders.clear_cache()
    with backends.use_backend(backend):
        yield Bench(backend=backend, root=tmp_dest_root, look=look, extensions=extensions)
    placeholders.clear_cache()


pytestmark = pytest.mark.mutating


def _apply_look(bench: Bench, ops, *, title: str, name: str, restore_point: bool = False):
    """Apply ``ops`` the way ``preset.compile`` does: both label and look."""
    return Transaction(
        ops, dest_root=str(bench.root), label=title, look=name
    ).apply(restore_point=restore_point)


def _page_edit(bench: Bench, ops, *, restore_point: bool = True):
    """One change made from a page: neither a label nor a look."""
    return Transaction(ops, dest_root=str(bench.root)).apply(restore_point=restore_point)


# -- the spine: a saved moment is not a Look --------------------------------


def test_undoing_one_page_edit_does_not_revert_the_whole_look(bench):
    """Pins transaction.py:883 — undo of one tweak stripped the applied Look.

    ``switch_cleanup`` was gated on ``self.label``, and every saved moment has a
    label, so putting one back ran the Look-switch cleanup: it reverted
    everything the applied Look owned that the moment did not cover. Pressing
    "Undo the last change" after one unrelated tick therefore threw the whole
    Look off the desktop.
    """
    style = bench.add_file("style.css", "the look's css")
    _apply_look(
        bench,
        [
            FileWrite(src=style, dest="~/.config/demo/style.css"),
            SettingWrite(key=ICONS, value="'Papirus'"),
        ],
        title="MAGMA — Molten Glass",
        name="magma",
    )

    result = _page_edit(bench, [SettingWrite(key=WORD, value="'tweaked'")])
    assert result.restore_point, "a page edit takes its own saved moment"

    restorepoints.apply_point(
        result.restore_point, backend=bench.backend, dest_root=str(bench.root)
    )

    assert bench.backend.get(WORD) == "'default'", "the tweak itself came back"
    assert bench.backend.get(ICONS) == "'Papirus'", "the Look's setting must survive"
    assert (bench.root / ".config" / "demo" / "style.css").is_file()
    assert "MAGMA — Molten Glass" in ledger_store.read_ledger()


def test_putting_a_saved_moment_back_does_not_own_it_under_the_moments_name(bench):
    """Pins restorepoints.py:166 — a restore ran as a labelled "Look".

    ``to_transaction`` passed the point's label, which made the point's name the
    ledger owner (indistinguishable from a real Look's entry) and armed the
    switch cleanup, which then consumed unrelated Looks' entries.
    """
    ledger_store.write_entry("OTHER LOOK", [], [ICONS])
    bench.backend.set(ICONS, "'Papirus'")
    point = restorepoints.capture([WORD], label="NIGHTBLOOM", backend=bench.backend)

    bench.backend.set(WORD, "'changed since'")
    restorepoints.apply_point(point.id, backend=bench.backend, dest_root=str(bench.root))

    ledger = ledger_store.read_ledger()
    assert "NIGHTBLOOM" not in ledger, "a saved moment's name never owns anything"
    assert "OTHER LOOK" in ledger, "a restore tidies up after nobody"
    assert bench.backend.get(ICONS) == "'Papirus'", "and reverts nothing it does not cover"
    assert ledger_store.current_look() is None
    assert bench.backend.get(WORD) == "'default'", "the moment itself was restored"


def test_applying_a_look_leaves_the_users_own_page_edit_alone(bench):
    """Pins ledger.py:127 — a Look apply reverted the user's deliberate edits.

    ``switch_cleanup`` walked every ledger entry that was not the incoming
    Look's, which included ``__manual__`` — the entry the engine writes for a
    change made from a page. transaction.py's own contract says the opposite:
    "Switching Looks tidies up after other Looks; it never tidies up after the
    user's own deliberate edits."
    """
    _page_edit(bench, [SettingWrite(key=WORD, value="'the user picked this'")])
    assert ledger_store.MANUAL_OWNER in ledger_store.read_ledger()

    _apply_look(
        bench,
        [SettingWrite(key=ICONS, value="'Papirus'")],
        title="NIGHTBLOOM",
        name="nightbloom",
    )

    assert bench.backend.get(WORD) == "'the user picked this'"
    assert ledger_store.MANUAL_OWNER in ledger_store.read_ledger()


def test_a_labelled_transaction_that_is_not_a_look_tidies_up_after_nobody(bench):
    """Pins the engine half of ego/install.py:217 — a label armed the cleanup.

    ``enable_transaction`` and the Looks page's add-on batch build transactions
    of nothing but ``ExtensionEnable`` ops that carry a Look's *title*. With the
    cleanup keyed on the label, applying one reverted every file and setting
    other Looks owned — the current Look stripped off the desktop by a button
    that only meant to switch an add-on on. The engine now keys on ``look``, so
    such a transaction is harmless whatever label it carries; this test holds
    that end of the contract down from the core side.
    """
    style = bench.add_file("style.css", "the look's css")
    _apply_look(
        bench,
        [
            FileWrite(src=style, dest="~/.config/demo/style.css"),
            SettingWrite(key=ICONS, value="'Papirus'"),
        ],
        title="NIGHTBLOOM",
        name="nightbloom",
    )
    bench.install("extra@ext")

    # The label the Looks page hands it is the tile the user clicked, which is
    # not the Look that is on the desktop — exactly the shape of the repro.
    Transaction(
        [ExtensionEnable(uuid="extra@ext")],
        dest_root=str(bench.root),
        label="SOME OTHER LOOK",
    ).apply(restore_point=False)

    assert bench.backend.get(ICONS) == "'Papirus'"
    assert (bench.root / ".config" / "demo" / "style.css").is_file()
    assert "NIGHTBLOOM" in ledger_store.read_ledger()


# -- honest accounting ------------------------------------------------------


def test_an_add_on_that_is_not_installed_is_never_reported_as_turned_on(bench):
    """Pins transaction.py:1285 — a skipped enable was also recorded as applied.

    ``_write_extensions`` appended unresolvable ops to ``skipped`` and then
    extended ``applied`` with the *full* op list, so an add-on that is not on
    the machine landed in both — breaking the applied-xor-skipped invariant and
    letting the AS4 "nothing was applied" gate be bypassed.
    """
    bench.install("here@ext")
    result = _apply_look(
        bench,
        [ExtensionEnable(uuid="here@ext"), ExtensionEnable(uuid="absent@ext")],
        title="ADDONS",
        name="addons",
    )

    applied = {op.uuid for op in result.applied if isinstance(op, ExtensionEnable)}
    skipped = {op.uuid for op, _reason in result.skipped if isinstance(op, ExtensionEnable)}
    assert applied == {"here@ext"}
    assert skipped == {"absent@ext"}
    assert not applied & skipped, "an op is applied or skipped, never both"
    assert "absent@ext" not in (bench.backend.get("gsettings:org.gnome.shell enabled-extensions") or "")


def test_a_tidy_up_that_really_happened_is_never_reported_as_nothing_changed(
    bench, monkeypatch
):
    """Pins transaction.py:938 — AS4 claimed a rollback after a real cleanup.

    The switch cleanup runs *before* the ops. With no session bus every setting
    op is skipped, so AS4 fired and reported "Nothing was changed" with
    ``rolled_back=True`` — while the outgoing Look's file had genuinely been
    deleted from the desktop moments earlier.
    """
    from gtheme.core import transaction as transaction_module

    old = bench.add_file("old.css", "the outgoing look's file")
    _apply_look(
        bench,
        [FileWrite(src=old, dest="~/.config/demo/old.css")],
        title="OLD",
        name="old",
    )
    victim = bench.root / ".config" / "demo" / "old.css"
    assert victim.is_file()

    monkeypatch.setattr(transaction_module, "has_session_bus", lambda: False)
    seen: list[tuple[Progress, str]] = []
    with pytest.raises(TransactionError) as caught:
        Transaction(
            [SettingWrite(key=ICONS, value="'Papirus'")],
            dest_root=str(bench.root),
            label="NEW",
            look="new",
        ).apply(lambda stage, text: seen.append((stage, text)))

    assert not victim.exists(), "the cleanup really did revert the outgoing Look"
    assert caught.value.rolled_back is False, "nothing was rolled back — say so"
    assert "Nothing was changed" not in [text for _stage, text in seen]


def test_a_rollback_that_did_not_finish_keeps_the_ledger_claim(bench, monkeypatch):
    """Pins transaction.py:921 — a failed rollback withdrew the claim anyway.

    ``_restore_ledger`` ran unconditionally, so a change that could NOT be
    rolled back stayed on the desktop owned by nobody. R4's cost model is
    explicit about which way to err: over-claiming costs one redundant restore,
    under-claiming orphans a change forever.
    """
    from gtheme.core.baseline import RestoreOutcome

    monkeypatch.setattr(
        Baseline,
        "restore_files",
        lambda self, only=None: RestoreOutcome(
            warnings=["the saved copy of it is gone; left it as it is"]
        ),
    )

    def refuse(self, key, value):
        raise BackendError(BackendErrorKind.COMMIT_FAILED, "the store refused it", key=key)

    monkeypatch.setattr(MemoryBackend, "set", refuse)

    source = bench.add_file("f", "the look's content")
    with pytest.raises(TransactionError) as caught:
        _apply_look(
            bench,
            [
                FileWrite(src=source, dest="~/.config/demo/f"),
                SettingWrite(key=ICONS, value="'Papirus'"),
            ],
            title="STUCK",
            name="stuck",
        )

    assert caught.value.rolled_back is False
    landed = bench.root / ".config" / "demo" / "f"
    assert landed.is_file(), "the leftover change is still on the desktop"
    claimed = ledger_store.read_ledger().get("STUCK", {}).get("files", [])
    assert str(landed) in claimed, "and something still claims it"


def test_switch_cleanup_keeps_the_entry_for_what_it_could_not_revert(
    bench, tmp_path
):
    """Pins ledger.py:151 — the entry was dropped even when nothing reverted.

    ``ledger.pop(name)`` ran unconditionally, so a Look whose items failed to
    revert was forgotten and nothing ever retried them. The ``kept`` count also
    included records the restore marked *dead* — the saved copy is gone — under
    a warning promising the Undo page could still recover them, which is untrue
    for exactly those.
    """
    baseline = Baseline(tmp_path / "baseline", backend=bench.backend)
    guarded = bench.root / "guarded" / "keeps.conf"
    guarded.parent.mkdir(parents=True)
    guarded.write_text("original", encoding="utf-8")
    lost = bench.root / "lost.conf"
    lost.write_text("original", encoding="utf-8")

    baseline.record_file(guarded)
    baseline.record_file(lost)
    baseline.save()
    # One record whose stored copy is gone for good...
    for blob in (baseline.files_dir / baseline.files[str(lost)]["backup"],):
        blob.unlink()
    # ... and one that merely cannot be written today.
    guarded.write_text("what the look put there", encoding="utf-8")
    guarded.parent.chmod(0o500)
    try:
        ledger_store.write_entry("OUTGOING", [str(guarded), str(lost)], [])
        report = ledger_store.switch_cleanup("INCOMING", set(), set(), baseline)
    finally:
        guarded.parent.chmod(0o700)

    entry = ledger_store.read_ledger().get("OUTGOING")
    assert entry is not None, "an item that failed to revert keeps its owner"
    assert entry["files"] == [str(guarded)]
    assert str(lost) not in entry["files"], "a dead record is not retried forever"
    assert report.kept == 1
    assert report.dead == 1
    recoverable = [line for line in report.warnings if "Undo page can still recover" in line]
    assert recoverable and "1 thing(s)" in recoverable[0], (
        "only the genuinely recoverable item may be promised to the Undo page"
    )


# -- restore points record what is really there -----------------------------


def test_a_restore_point_saves_the_key_the_transaction_will_really_write(bench):
    """Pins restorepoints.py:405 — a token-bearing key was captured unresolved.

    ``capture_from_diff`` appended the raw ``op.key``, so a Look writing
    ``.../{{ ptyxis_default_profile }}/palette`` produced a moment recording the
    *literal* token path, which reads as "no value". Putting that moment back
    resolved the token and issued a reset on the real key — wiping the value the
    moment existed to protect.
    """
    bench.backend.set(PTYXIS_DEFAULT, "'abcd1234'")
    placeholders.clear_cache()
    resolved = placeholders.resolve(TOKEN_KEY, placeholders.runtime_context(bench.backend))
    assert "abcd1234" in resolved and "{{" not in resolved
    bench.backend.set(resolved, "'the user chose this'")

    result = Transaction(
        [SettingWrite(key=TOKEN_KEY, value="'the look wants this'")],
        dest_root=str(bench.root),
        label="NETRUNNER",
        look="netrunner",
    ).apply()

    point = restorepoints.load(result.restore_point)
    assert point is not None
    assert point.settings.get(resolved) == "'the user chose this'"
    assert TOKEN_KEY not in point.settings, "the literal token path saves nothing"

    restorepoints.apply_point(point.id, backend=bench.backend, dest_root=str(bench.root))
    assert bench.backend.get(resolved) == "'the user chose this'"


def test_a_shortcut_at_a_destination_is_put_back_rather_than_deleted(bench):
    """Pins restorepoints.py:331 — a pre-existing symlink was recorded absent.

    ``capture`` recorded a symlinked destination as ``None``, so restoring the
    moment emitted a removal and unlinked the user's own shortcut — the one
    pointing into their dotfiles repository — and never recreated it.
    """
    from gtheme.core.transaction import FileLink  # lazy: the op is part of the fix

    dotfiles = bench.root / "dotfiles"
    dotfiles.mkdir()
    real = dotfiles / "app.conf"
    real.write_text("the user's own configuration", encoding="utf-8")
    link = bench.root / ".config" / "app.conf"
    link.parent.mkdir(parents=True)
    link.symlink_to(real)

    source = bench.add_file("app.conf", "the look's configuration")
    result = _apply_look(
        bench,
        [FileWrite(src=source, dest="~/.config/app.conf")],
        title="OVERLAY",
        name="overlay",
        restore_point=True,
    )
    point = restorepoints.load(result.restore_point)
    assert point is not None
    assert point.files[str(link)] == {"link": str(real)}
    assert any(isinstance(op, FileLink) for op in point.to_transaction().ops)

    restorepoints.apply_point(point.id, backend=bench.backend, dest_root=str(bench.root))

    assert link.is_symlink(), "the user's own shortcut is put back, not deleted"
    assert link.readlink() == real
    assert real.read_text(encoding="utf-8") == "the user's own configuration", (
        "and nothing was written through it"
    )


def test_a_setting_that_could_not_be_read_is_not_recorded_as_unset(bench):
    """Pins restorepoints.py:324 — any read failure was recorded as "no value".

    A transient failure (the settings service momentarily unreachable) is not
    the same as "there was nothing here", and recording it as absence made
    restoring the moment *clear* a key that held a real value — silently, with
    no warning, in flat contradiction of capture()'s own docstring.
    """
    unreadable = "gsettings:org.gtheme.test a-word"
    absent = "gsettings:org.absent.thing a-key"

    class Flaky(MemoryBackend):
        def get(self, key: str) -> str | None:
            if key == unreadable:
                raise BackendError(
                    BackendErrorKind.OTHER, "dconf-service momentarily unreachable", key=key
                )
            return super().get(key)

    flaky = Flaky(schema_source=bench.backend.schema_source)
    point = restorepoints.capture([unreadable, absent], label="Before", backend=flaky)

    assert unreadable not in point.settings, "an unknown value is not a recorded absence"
    assert point.warnings and any(unreadable in line for line in point.warnings)
    assert point.settings[absent] is None, "a key that is genuinely not there still records"
    assert unreadable not in {op.key for op in point.to_transaction().ops}


# -- the confinement boundary ----------------------------------------------


def test_a_settings_file_key_cannot_write_outside_the_destination_root(
    bench, tmp_path, schema_source_factory
):
    """Pins settings_backend.py:489 — ``keyfile:`` wrote to any absolute path.

    A Look's ``[[settings]]`` key is an unconstrained string, and the
    transaction's confinement preflight covers file operations only. A
    ``keyfile:`` key therefore reached
    ``Gio.keyfile_settings_backend_new(<attacker path>, ...)`` and created or
    modified a file anywhere the user can write — contradicting confine.py's
    stated invariant that nothing gtheme writes escapes the destination root.
    """
    from gtheme.core.settings_backend import GioBackend

    escape = tmp_path / "outside" / "escape.conf"
    key = f"keyfile:{escape}:org.gtheme.test.owned:/org/gtheme/test/ a-word"
    backend = GioBackend(schema_source=schema_source_factory(SCHEMA_XML))

    with pytest.raises(BackendError) as caught:
        backend.set(key, "'planted'")
    assert caught.value.kind is BackendErrorKind.OTHER
    assert not escape.exists(), "and not a byte was written"

    inside = bench.root / ".config" / "inside.conf"
    inside.parent.mkdir(parents=True, exist_ok=True)
    allowed = f"keyfile:{inside}:org.gtheme.test.owned:/org/gtheme/test/ a-word"
    backend.set(allowed, "'fine'")
    assert backend.get(allowed) == "'fine'", "the real add-on case still works"


# -- rescue -----------------------------------------------------------------


def test_a_full_rescue_forgets_which_look_was_applied(bench):
    """Pins rescue.py:121 — the ledger was cleared but current.json survived.

    After a complete ``gtheme rescue`` the desktop is pristine, but the Home
    page's "Look" row and the Terminal page both read ``current.json`` — and it
    still named the last Look, so the app announced a Look on a desktop that no
    longer had a trace of one.
    """
    from gtheme.core.rescue import run_rescue

    source = bench.add_file("f", "the look's file")
    _apply_look(
        bench,
        [
            FileWrite(src=source, dest="~/.config/demo/f"),
            SettingWrite(key=ICONS, value="'Papirus'"),
        ],
        title="NIGHTBLOOM",
        name="nightbloom",
    )
    assert ledger_store.current_look() == "nightbloom"

    assert run_rescue() == 0

    assert ledger_store.read_ledger() == {}
    assert ledger_store.current_look() is None
    assert bench.backend.get(ICONS) == "'Adwaita'"
