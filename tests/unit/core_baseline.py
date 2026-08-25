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
