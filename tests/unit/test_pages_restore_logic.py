"""Undo & Restore Points: what it saves, and how honestly it describes it.

``root=tmp_path`` tells the restore-point *store* where to live, but undoing
runs a real :class:`~gtheme.core.transaction.Transaction`, and the automatic
restore point, ownership ledger and baseline it writes all resolve from
``GTHEME_STATE_DIR`` rather than from that argument. Half a seam is not a seam:
before :func:`_state_root` was added, ``test_undo_picks_the_newest_and_puts_the_value_back``
was writing into the real ``~/.local/state/gtheme/v2``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for the page modules")

from gtheme.core import restorepoints  # noqa: E402
from gtheme.core.restorepoints import RestorePoint  # noqa: E402
from gtheme.core.settings_backend import MemoryBackend  # noqa: E402
from gtheme.ui import jargon  # noqa: E402
from gtheme.ui.pages import restore  # noqa: E402


@pytest.fixture(autouse=True)
def _state_root(tmp_path, monkeypatch):
    """The engine's state root is the same tmp_path the store is handed."""
    monkeypatch.setenv("GTHEME_STATE_DIR", str(tmp_path))


def test_default_label_is_a_date_a_person_would_say():
    label = restore.default_label(datetime(2026, 8, 25, tzinfo=UTC))
    assert label == "My desktop, 25 August"


def test_the_keys_a_restore_point_covers_are_the_descriptor_corpus():
    """What is not captured cannot be put back, so the lists must be one list."""
    keys = restore.descriptor_keys()
    assert keys, "the shipped corpus must produce keys"
    assert len(set(keys)) == len(keys), "a key covered twice would be recorded twice"
    assert all(key.startswith(("gsettings:", "gsettings-path:", "keyfile:")) for key in keys)
    assert "gsettings:org.gnome.desktop.interface color-scheme" in keys


def test_saving_records_the_current_values(tmp_path, memory_settings):
    memory_settings.set("gsettings:org.gnome.desktop.interface accent-color", "'green'")
    point = restore.create_restore_point(
        "My desktop, today",
        backend=memory_settings,
        root=tmp_path,
        keys=["gsettings:org.gnome.desktop.interface accent-color"],
    )
    assert point.kind == "manual"
    assert point.settings["gsettings:org.gnome.desktop.interface accent-color"] == "'green'"
    assert restorepoints.load(point.id, root=tmp_path) is not None


def test_a_key_with_no_value_is_recorded_as_absence(tmp_path):
    point = restore.create_restore_point(
        "Empty desktop",
        backend=MemoryBackend(),
        root=tmp_path,
        keys=["gsettings:org.gnome.nonexistent a-key"],
    )
    assert point.keys_to_unset == ["gsettings:org.gnome.nonexistent a-key"]


def test_absence_is_said_out_loud():
    point = RestorePoint(
        id="x",
        label="x",
        created=datetime.now(UTC),
        settings={"gsettings:a b": None, "gsettings:c d": "'1'"},
        files={"~/.config/thing": None},
    )
    sentence = restore.absence_sentence(point)
    assert sentence is not None
    assert "1 setting that had never been changed" in sentence
    assert "1 file that was not there" in sentence


def test_a_point_that_only_puts_things_back_says_nothing_extra():
    point = RestorePoint(
        id="x", label="x", created=datetime.now(UTC), settings={"gsettings:a b": "'1'"}
    )
    assert restore.absence_sentence(point) is None


def test_a_point_is_described_by_date_and_size():
    point = RestorePoint(
        id="x",
        label="My desktop, 25 August",
        created=datetime(2026, 8, 25, 12, 30, tzinfo=UTC),
        settings={"gsettings:a b": "'1'", "gsettings:c d": "'2'"},
    )
    described = restore.describe_point(point)
    assert "covers 2 settings" in described
    assert "2026" in described


def test_undo_with_nothing_saved_is_an_honest_no(tmp_path):
    assert restore.undo_last_change(root=tmp_path) == (None, None)


def test_undo_picks_the_newest_and_puts_the_value_back(tmp_path, memory_settings):
    key = "gsettings:org.gnome.desktop.interface accent-color"
    memory_settings.set(key, "'green'")
    saved = restore.create_restore_point(
        "before", backend=memory_settings, root=tmp_path, keys=[key]
    )
    memory_settings.set(key, "'purple'")

    point, result = restore.undo_last_change(root=tmp_path, backend=memory_settings)

    assert point is not None and point.id == saved.id
    assert result is not None and not result.warnings
    assert memory_settings.get(key) == "'green'"


def test_undo_never_reaches_for_the_before_gtheme_point(tmp_path):
    """The nuclear option is chosen deliberately from the list, never by Undo."""
    restorepoints.capture(
        ["gsettings:a b"],
        label="Before gtheme",
        kind="pristine",
        backend=MemoryBackend(),
        root=tmp_path,
        point_id="before-gtheme",
    )
    assert restore.undo_last_change(root=tmp_path) == (None, None)


def test_the_preview_is_the_plan_of_the_real_transaction(tmp_path, memory_settings):
    key = "gsettings:org.gnome.desktop.interface accent-color"
    memory_settings.set(key, "'green'")
    point = restore.create_restore_point(
        "before", backend=memory_settings, root=tmp_path, keys=[key]
    )
    memory_settings.set(key, "'purple'")
    loaded = restorepoints.load(point.id, root=tmp_path)
    assert loaded is not None
    assert restore.preview_lines(loaded, backend=memory_settings)


def test_the_preview_never_raises_into_the_page():
    broken = RestorePoint(id="x", label="x", created=datetime.now(UTC), files={"/nope": "0001"})
    assert restore.preview_lines(broken) == []


def test_every_sentence_on_the_restore_page_is_jargon_free():
    assert jargon.check_all(restore.copy_strings()) == []
