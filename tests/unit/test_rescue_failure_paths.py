"""``gtheme rescue`` when it cannot finish (review-report M19).

Rescue is the last resort: no window, no GTK, a person at a text console
looking at a desktop they cannot use. It is also the only code that calls
``forget_files``/``forget_settings`` on records it has classified as dead —
which deletes the only pre-gtheme copy of somebody's file. Every existing test
of it asserted ``== 0`` and was arranged to reach the clean full-restore path,
so the two branches that matter when something goes wrong were never executed:

* a **transient** failure must return 1 and change nothing else — the baseline
  records and their stored copies, the ownership ledger and ``current.json``
  all stay exactly as they were, because the leftover change is still on the
  desktop and those are what will undo it on the next attempt. If
  ``write_ledger({})`` were ever moved above the ``if stuck:`` return, a
  half-succeeded rescue would erase the ownership ledger with the changes still
  in place, and the suite would have stayed green.
* the **lock** branch must say so rather than proceeding: another gtheme is
  mid-apply, and a rescue racing it is how two writers destroy one recording.

Nothing here touches the real desktop: settings go to a memory-backed store,
files to a temporary directory, state to the ``state_dir`` seam.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gtheme.core import backends
from gtheme.core import ledger as ledger_store
from gtheme.core.baseline import Baseline
from gtheme.core.lock import process_lock
from gtheme.core.rescue import run_rescue
from gtheme.core.settings_backend import BackendError, BackendErrorKind, MemoryBackend

pytestmark = pytest.mark.mutating

SCHEMA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<schemalist>
  <schema id="org.gtheme.test" path="/org/gtheme/test/">
    <key name="a-word" type="s"><default>'default'</default></key>
  </schema>
</schemalist>
"""

WORD = "gsettings:org.gtheme.test a-word"


class _RefusesWrites(MemoryBackend):
    """A store that has stopped accepting writes — the transient failure.

    ``COMMIT_FAILED`` deliberately: a *missing* schema would be classified as
    dead and dropped, which is the branch that is allowed to forget a record.
    This one is the branch that may not.
    """

    def __init__(self, schema_source) -> None:
        super().__init__(schema_source)
        self.armed = False

    def set(self, key: str, value: str) -> None:
        if self.armed:
            raise BackendError(
                BackendErrorKind.COMMIT_FAILED,
                "the settings store is not accepting changes right now",
                key=key,
            )
        super().set(key, value)


@pytest.fixture
def backend(schema_source_factory) -> _RefusesWrites:
    return _RefusesWrites(schema_source_factory(SCHEMA_XML))


@pytest.fixture
def changed_desktop(backend, state_dir: Path, tmp_path: Path) -> dict:
    """A desktop a Look has changed, with everything recorded as it should be.

    One file and one setting, a ledger entry claiming both, and a
    ``current.json`` naming the Look — the state a real rescue runs into.
    """
    config = tmp_path / "config"
    config.write_text("what was there before gtheme", encoding="utf-8")

    baseline = Baseline(backend=backend).load()
    baseline.record_file(config, "files", "MAGMA")
    backend.set(WORD, "'before gtheme'")
    baseline.record_setting(WORD, "other", "MAGMA")

    config.write_text("what the look wrote", encoding="utf-8")
    backend.set(WORD, "'what the look wrote'")

    ledger_store.write_entry("MAGMA", [str(config)], [WORD])
    ledger_store.set_current_look("magma", label="MAGMA")

    del state_dir  # requested for the seam; the paths come from the environment
    return {"config": config, "baseline": baseline}


def test_a_rescue_that_could_not_finish_says_so_and_keeps_everything(
    backend, changed_desktop, capsys
):
    """Exit 1, and not one record, copy, claim or Look name thrown away."""
    config = changed_desktop["config"]
    backend.armed = True

    with backends.use_backend(backend):
        code = run_rescue()

    assert code == 1
    printed = capsys.readouterr().out
    assert "could not be put back" in printed
    assert "Nothing was lost" in printed

    after = Baseline(backend=backend).load()
    assert WORD in after.settings, "the record of the only pre-gtheme value stays"
    assert after.settings[WORD]["saved"] == "'before gtheme'"
    assert str(config) in after.files
    blob = after.files_dir / after.files[str(config)]["backup"]
    assert blob.read_text(encoding="utf-8") == "what was there before gtheme", (
        "and so does the stored copy — forgetting a record destroys it"
    )

    assert ledger_store.read_ledger() == {
        "MAGMA": {"files": [str(config)], "settings": [WORD]}
    }, "the leftover change is still owned, or nothing will ever undo it"
    assert ledger_store.current_look() == "magma"


def test_a_rescue_that_could_not_finish_keeps_what_it_did_manage(
    backend, changed_desktop
):
    """The file leg ran before the settings leg refused, and it stays run.

    Rescue is resumable, not atomic: what came back stays back, what did not is
    still recorded, and running it again once the cause is fixed finishes the
    job. That is what "run this again" in the message promises.
    """
    config = changed_desktop["config"]
    backend.armed = True

    with backends.use_backend(backend):
        assert run_rescue() == 1

    assert config.read_text(encoding="utf-8") == "what was there before gtheme"
    assert backend.get(WORD) == "'what the look wrote'", "the refused write did not land"


def test_a_second_rescue_finishes_the_job_once_the_cause_is_fixed(
    backend, changed_desktop
):
    """The claim the failure message makes, actually exercised."""
    backend.armed = True
    with backends.use_backend(backend):
        assert run_rescue() == 1

    backend.armed = False
    with backends.use_backend(backend):
        assert run_rescue() == 0

    assert backend.get(WORD) == "'before gtheme'"
    assert Baseline(backend=backend).load().is_empty
    assert ledger_store.read_ledger() == {}
    assert ledger_store.current_look() is None


def test_a_rescue_that_cannot_take_the_lock_says_so_rather_than_racing(
    backend, changed_desktop, capsys
):
    """Another gtheme is mid-apply. Two writers destroy one recording.

    The rescue must report that and leave everything alone — including the
    ledger and the current Look, which it never reaches.
    """
    config = changed_desktop["config"]

    with process_lock(), backends.use_backend(backend):
        code = run_rescue()

    assert code == 1
    assert "already changing your desktop" in capsys.readouterr().out

    assert config.read_text(encoding="utf-8") == "what the look wrote", (
        "nothing was restored behind the other process's back"
    )
    assert WORD in Baseline(backend=backend).load().settings
    assert ledger_store.current_look() == "magma"


def test_a_rescue_with_nothing_recorded_never_takes_the_lock_at_all(
    backend, state_dir: Path, capsys
):
    """A rescue on a machine gtheme has not touched leaves no lock file behind.

    Held here because the early return above the lock is what makes the lock
    branch reachable only in the case that deserves it.
    """
    with process_lock(), backends.use_backend(backend):
        assert run_rescue() == 0
    assert "has not changed anything yet" in capsys.readouterr().out
    del state_dir
