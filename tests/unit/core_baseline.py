"""The recording of what your desktop looked like before gtheme touched it.

The single rule everything else rests on: the first touch records, and nothing
records twice. Apply five Looks, switch between them for a month, and the
recording still describes the state before the first one — not the state before
the fifth.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from gtheme.core.baseline import Baseline, missing_ancestors
from gtheme.core.settings_backend import MemoryBackend

SCHEMA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<schemalist>
  <schema id="org.gtheme.test" path="/org/gtheme/test/">
    <key name="a-word" type="s"><default>'default'</default></key>
    <key name="a-list" type="as"><default>[]</default></key>
  </schema>
</schemalist>
"""

WORD = "gsettings:org.gtheme.test a-word"
LIST = "gsettings:org.gtheme.test a-list"


@pytest.fixture
def backend(schema_source_factory) -> MemoryBackend:
    return MemoryBackend(schema_source=schema_source_factory(SCHEMA_XML))


@pytest.fixture
def baseline(tmp_path: Path, backend: MemoryBackend) -> Baseline:
    return Baseline(tmp_path / "baseline", backend=backend).load()


# -- files -----------------------------------------------------------------


def test_a_file_is_recorded_once_and_only_once(baseline, tmp_path):
    """The rule the whole promise rests on."""
    dest = tmp_path / "target"
    dest.write_text("the original", encoding="utf-8")

    baseline.record_file(dest)
    dest.write_text("a look wrote this", encoding="utf-8")
    baseline.record_file(dest)

    outcome = baseline.restore_files()
    assert dest.read_text(encoding="utf-8") == "the original"
    assert outcome.done == [str(dest)]


def test_a_symlink_is_recorded_as_a_link_and_restored_as_one(baseline, tmp_path):
    """Never dereferenced. Following it would edit whatever it points at."""
    target = tmp_path / "elsewhere"
    target.write_text("somebody else's file", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(target)

    baseline.record_file(link)
    link.unlink()
    link.write_text("a real file now", encoding="utf-8")

    baseline.restore_files()
    assert link.is_symlink()
    assert link.readlink() == target
    assert target.read_text(encoding="utf-8") == "somebody else's file"


def test_a_file_that_did_not_exist_is_removed_again(baseline, tmp_path):
    dest = tmp_path / "new" / "deep" / "file"
    baseline.record_file(dest)
    dest.parent.mkdir(parents=True)
    dest.write_text("installed", encoding="utf-8")

    baseline.restore_files()
    assert not dest.exists()


def test_only_the_directories_the_apply_created_are_removed(baseline, tmp_path):
    """A folder that already existed — even an empty one — must survive.

    Recording which parents were missing *before* the ``mkdir`` is the only way
    to know the difference; guessing afterwards deletes somebody's empty folder.
    """
    existing = tmp_path / "already-here"
    existing.mkdir()
    dest = existing / "made" / "file"

    baseline.record_file(dest)
    dest.parent.mkdir(parents=True)
    dest.write_text("installed", encoding="utf-8")

    baseline.restore_files()
    assert not dest.parent.exists()
    assert existing.is_dir()


def test_a_directory_that_is_still_in_use_is_left_alone(baseline, tmp_path):
    """``rmdir`` refuses a non-empty folder, which is exactly right here."""
    dest = tmp_path / "shared" / "mine"
    baseline.record_file(dest)
    dest.parent.mkdir(parents=True)
    dest.write_text("mine", encoding="utf-8")
    (dest.parent / "somebody-elses").write_text("theirs", encoding="utf-8")

    baseline.restore_files()
    assert dest.parent.is_dir()
    assert (dest.parent / "somebody-elses").is_file()


def test_a_special_file_is_refused_rather_than_snapshotted(baseline, tmp_path):
    """F1. What cannot be copied cannot be put back, so it is not touched."""
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    assert baseline.record_file(fifo) is False
    assert str(fifo) not in baseline.files


def test_a_restore_never_writes_through_a_link_planted_at_the_destination(
    baseline, tmp_path
):
    """Somebody could put a link where the file goes between apply and undo."""
    dest = tmp_path / "target"
    dest.write_text("the original", encoding="utf-8")
    baseline.record_file(dest)

    elsewhere = tmp_path / "elsewhere"
    elsewhere.write_text("must not be overwritten", encoding="utf-8")
    dest.unlink()
    dest.symlink_to(elsewhere)

    baseline.restore_files()
    assert dest.read_text(encoding="utf-8") == "the original"
    assert elsewhere.read_text(encoding="utf-8") == "must not be overwritten"


def test_stored_copies_are_numbered_so_a_deletion_cannot_cause_a_reuse(baseline, tmp_path):
    """Counting the files instead would hand out a number twice."""
    first = tmp_path / "one"
    second = tmp_path / "two"
    first.write_text("one", encoding="utf-8")
    second.write_text("two", encoding="utf-8")
    baseline.record_file(first)
    baseline.record_file(second)
    baseline.forget_files([str(first)])

    third = tmp_path / "three"
    third.write_text("three", encoding="utf-8")
    reloaded = Baseline(baseline.dir, backend=baseline.backend).load()
    reloaded.record_file(third)

    assert reloaded.files[str(third)]["backup"] != reloaded.files[str(second)]["backup"]
    assert (reloaded.files_dir / reloaded.files[str(second)]["backup"]).read_text() == "two"


def test_forgetting_a_file_deletes_its_stored_copy(baseline, tmp_path):
    dest = tmp_path / "target"
    dest.write_text("original", encoding="utf-8")
    baseline.record_file(dest)
    blob = baseline.files_dir / baseline.files[str(dest)]["backup"]
    assert blob.is_file()

    baseline.forget_files([str(dest)])
    assert not blob.exists()


def test_a_restore_can_be_narrowed_to_one_part_of_the_desktop(baseline, tmp_path):
    keep = tmp_path / "keep"
    revert = tmp_path / "revert"
    keep.write_text("keep-original", encoding="utf-8")
    revert.write_text("revert-original", encoding="utf-8")
    baseline.record_file(keep, "fonts")
    baseline.record_file(revert, "wallpaper")
    keep.write_text("changed", encoding="utf-8")
    revert.write_text("changed", encoding="utf-8")

    baseline.restore_files(only={"wallpaper"})
    assert revert.read_text(encoding="utf-8") == "revert-original"
    assert keep.read_text(encoding="utf-8") == "changed"


# -- settings --------------------------------------------------------------


def test_a_setting_is_recorded_once_and_restored_exactly(baseline, backend):
    backend.set(WORD, "'before'")
    baseline.record_setting(WORD)
    backend.set(WORD, "'after'")
    baseline.record_setting(WORD)
    backend.set(WORD, "'later still'")

    baseline.restore_settings()
    assert backend.get(WORD) == "'before'"


def test_an_empty_list_keeps_its_type_through_the_recording(baseline, backend):
    """``@as []`` and not ``[]``, or the restore cannot be written back."""
    baseline.record_setting(LIST)
    assert baseline.settings[LIST]["saved"] == "@as []"
    backend.set(LIST, "['a', 'b']")
    baseline.restore_settings()
    assert backend.get(LIST) == "@as []"


def test_a_setting_that_never_existed_is_recorded_as_having_no_value(baseline):
    """"There was nothing here" is a state, and restoring it means unsetting."""
    baseline.record_setting("gsettings:org.gtheme.absent a-key")
    assert baseline.settings["gsettings:org.gtheme.absent a-key"]["saved"] is None


def test_restoring_a_setting_whose_add_on_is_gone_is_dead_not_a_failure(baseline):
    """R5. Re-running can never fix it, so it must not block the restore."""
    baseline.settings["gsettings:org.gtheme.absent a-key"] = {
        "key": "gsettings:org.gtheme.absent a-key",
        "saved": "'something'",
        "component": "",
        "label": "",
    }
    outcome = baseline.restore_settings()
    assert outcome.dead == ["gsettings:org.gtheme.absent a-key"]
    assert outcome.done == []


def test_unsetting_a_key_whose_add_on_is_gone_is_already_done(baseline):
    """Nothing was there and nothing is there. That is the state we wanted."""
    baseline.settings["gsettings:org.gtheme.absent a-key"] = {
        "key": "gsettings:org.gtheme.absent a-key",
        "saved": None,
        "component": "",
        "label": "",
    }
    outcome = baseline.restore_settings()
    assert outcome.done == ["gsettings:org.gtheme.absent a-key"]
    assert outcome.dead == []


# -- persistence -----------------------------------------------------------


def test_each_record_persists_itself_immediately(baseline, tmp_path, backend):
    """No "save at the end" that a crash could skip."""
    dest = tmp_path / "target"
    dest.write_text("original", encoding="utf-8")
    baseline.record_file(dest)
    backend.set(WORD, "'before'")
    baseline.record_setting(WORD)

    fresh = Baseline(baseline.dir, backend=backend).load()
    assert str(dest) in fresh.files
    assert WORD in fresh.settings


def test_a_damaged_index_is_a_warning_not_a_crash(tmp_path, backend):
    directory = tmp_path / "baseline"
    first = Baseline(directory, backend=backend).load()
    first.record_setting(WORD)
    first.record_setting(LIST)
    (directory / "settings.json").write_text("{ not json", encoding="utf-8")

    second = Baseline(directory, backend=backend).load()
    assert second.warnings
    assert WORD in second.settings


def test_the_missing_ancestors_helper_lists_deepest_first(tmp_path):
    target = tmp_path / "a" / "b" / "c"
    listed = missing_ancestors(target)
    assert listed == [str(tmp_path / "a" / "b" / "c"), str(tmp_path / "a" / "b"), str(tmp_path / "a")]


def test_the_missing_ancestors_helper_stops_at_what_exists(tmp_path):
    (tmp_path / "a").mkdir()
    assert missing_ancestors(tmp_path / "a") == []


# -- a recording that cannot be made (review-report H1) --------------------
#
# The rule these pin: the recording comes first, so a recording that failed
# means the change must not happen. Silence here is the worst outcome
# available — the caller writes over the file believing it is covered, and the
# only copy of what was there is gone.


def _boom(*_args, **_kwargs):
    raise OSError(28, "No space left on device")


def test_a_copy_that_cannot_be_made_is_raised_not_swallowed(baseline, tmp_path, monkeypatch):
    """``shutil.copy2`` used to run unguarded: a full disk raised a bare
    ``OSError`` out of the middle of an apply, which skipped the rollback."""
    from gtheme.core.baseline import BaselineError

    dest = tmp_path / "target"
    dest.write_text("the only copy there is", encoding="utf-8")
    monkeypatch.setattr("gtheme.core.baseline.shutil.copy2", _boom)

    with pytest.raises(BaselineError) as caught:
        baseline.record_file(dest)

    assert "could not save a copy" in str(caught.value)
    assert str(dest) in str(caught.value), "the message names the file"
    assert str(dest) not in baseline.files, "a failed recording claims nothing"
    assert list(baseline.files_dir.glob("*")) == [], "and leaves no half-copy behind"
    assert dest.read_text(encoding="utf-8") == "the only copy there is"


def test_an_index_that_cannot_be_written_is_raised_not_swallowed(baseline, tmp_path, monkeypatch):
    """A record only in memory is a record a crash loses, so it is a failure.

    The blob is on disk and the entry is in memory, but nothing on disk says
    the destination is covered. Proceeding to write the file would leave a
    changed desktop that the recording does not admit to.
    """
    from gtheme.core.baseline import BaselineError

    dest = tmp_path / "target"
    dest.write_text("original", encoding="utf-8")
    monkeypatch.setattr("gtheme.core.baseline.atomic_write_json", _boom)

    with pytest.raises(BaselineError) as caught:
        baseline.record_file(dest)
    assert "could not write down what was at" in str(caught.value)


def test_a_setting_record_that_cannot_be_written_is_raised_not_swallowed(
    baseline, backend, monkeypatch
):
    from gtheme.core.baseline import BaselineError

    backend.set(WORD, "'before'")
    monkeypatch.setattr("gtheme.core.baseline.atomic_write_json", _boom)

    with pytest.raises(BaselineError) as caught:
        baseline.record_setting(WORD)
    assert WORD in str(caught.value)


def test_a_shortcut_that_cannot_be_read_is_refused_rather_than_recorded_blank(
    baseline, tmp_path, monkeypatch
):
    """A link recorded with no target restores as "cannot put this back".

    Writing over it anyway would destroy somebody's own shortcut with no way to
    recreate it, so the recording refuses instead of recording a blank target.
    """
    from gtheme.core.baseline import BaselineError

    link = tmp_path / "link"
    link.symlink_to(tmp_path / "elsewhere")
    monkeypatch.setattr("gtheme.core.baseline.os.readlink", _boom)

    with pytest.raises(BaselineError):
        baseline.record_file(link)
    assert str(link) not in baseline.files


def test_a_failed_recording_is_not_an_oserror(baseline, tmp_path, monkeypatch):
    """Deliberate: an ``except OSError`` written to guard the *write* must not
    swallow the failure of the recording that has to precede it."""
    from gtheme.core.baseline import BaselineError

    dest = tmp_path / "target"
    dest.write_text("original", encoding="utf-8")
    monkeypatch.setattr("gtheme.core.baseline.shutil.copy2", _boom)

    with pytest.raises(BaselineError) as caught:
        baseline.record_file(dest)
    assert not isinstance(caught.value, OSError)
    assert isinstance(caught.value.cause, OSError), "the real cause is kept"


# -- a location that has never been written (review-report H7) -------------


class _NeverWrittenDconf(MemoryBackend):
    """A backend where every ``dconf:`` path reads as never having been set.

    Which is what the real subprocess backend does for a path nothing has
    written: ``dconf read`` exits 0 and prints nothing.
    """

    def get(self, key: str) -> str:
        from gtheme.core.settings_backend import BackendError, BackendErrorKind

        if key.startswith("dconf:"):
            raise BackendError(
                BackendErrorKind.UNSET, f"{key} has never been set", key=key
            )
        return super().get(key)


DCONF_KEY = "dconf:/org/gnome/shell/extensions/blur-my-shell/panel/blur"


def test_a_location_never_written_records_as_having_no_value(tmp_path, schema_source_factory):
    """It is not "missing" — the recording still has to say what was there.

    Before H7 this read came back as NO_KEY, which meant "not on this machine",
    which meant the write was skipped entirely. Now the write happens, so the
    recording of what was there first has to be right: no value, restoring by
    unsetting it again.
    """
    backend = _NeverWrittenDconf(schema_source=schema_source_factory(SCHEMA_XML))
    baseline = Baseline(tmp_path / "baseline", backend=backend).load()

    baseline.record_setting(DCONF_KEY)

    assert baseline.settings[DCONF_KEY]["saved"] is None


def test_putting_back_a_location_that_was_never_written_is_already_done(
    tmp_path, schema_source_factory
):
    """Nothing was there and nothing is there: that is the state we wanted.

    It must count as done rather than dead, or a rescue would report a thing it
    could never put back and refuse to finish.
    """
    backend = _NeverWrittenDconf(schema_source=schema_source_factory(SCHEMA_XML))
    baseline = Baseline(tmp_path / "baseline", backend=backend).load()
    baseline.settings[DCONF_KEY] = {
        "key": DCONF_KEY,
        "saved": None,
        "component": "",
        "label": "",
    }

    outcome = baseline.restore_settings()

    assert outcome.done == [DCONF_KEY]
    assert outcome.dead == []


# -- the API this class does not have (review-report L18) ------------------


def test_the_baseline_offers_no_way_to_delete_the_whole_recording():
    """``wipe()`` was an unexercised ``rmtree`` of the pristine recording on the
    public API of this class — one careless call from making "Before gtheme"
    unrecoverable, for a job ``forget_files``/``forget_settings`` already do
    record by record. It has no callers and must not grow one."""
    assert not hasattr(Baseline, "wipe")
