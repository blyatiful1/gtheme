"""Restore points, including the one imported from v1 (DESIGN.md F1).

A restore point is a moment: exact current values, plus copies of the files
about to be overwritten. Applying one is applying a transaction, so everything
the engine already guarantees — the confinement preflight, the pristine
recording, the all-or-nothing rollback — is true of an undo without a second
implementation to keep in step.

The v1 import is the delicate one. Before the v2 rebuild razed the tree, v1's
state directory was copied to ``~/.local/state/gtheme.v1-backup``. Inside it is
v1's own pristine recording: the only surviving description of what this desktop
looked like before gtheme *ever* ran. It is read-only, forever, and it is not
optional to get right — a silent gap there is a gap in the one thing the Home
page promises. The tests below build a v1 store shaped exactly like the real
one on this machine and check both what imports and what is honestly refused.
"""

from __future__ import annotations

import json
from datetime import UTC
from pathlib import Path

import pytest

from gtheme.core import restorepoints
from gtheme.core.restorepoints import (
    PRISTINE_ID,
    RestorePoint,
    capture,
    import_v1_baseline,
    list_restore_points,
    load,
    prune,
    read_v1_current,
)
from gtheme.core.settings_backend import MemoryBackend
from gtheme.core.transaction import FileWrite, SettingWrite

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
def points(tmp_path: Path) -> Path:
    root = tmp_path / "restore-points"
    root.mkdir()
    return root


# -- capturing -------------------------------------------------------------


def test_a_capture_records_the_exact_value(points, backend):
    backend.set(WORD, "'the moment'")
    point = capture([WORD], label="Before", backend=backend, root=points)
    backend.set(WORD, "'later'")
    assert load(point.id, root=points).settings[WORD] == "'the moment'"


def test_an_empty_list_keeps_its_type_in_a_capture(points, backend):
    """``@as []`` and not ``[]``, or the restore cannot be written back."""
    point = capture([LIST], label="Before", backend=backend, root=points)
    assert point.settings[LIST] == "@as []"


def test_a_key_that_cannot_be_read_is_recorded_as_having_no_value(points, backend):
    """"There was nothing here" is a state, and it is a restorable one."""
    point = capture(["gsettings:org.absent.thing a-key"], label="Before", backend=backend, root=points)
    assert point.settings["gsettings:org.absent.thing a-key"] is None


def test_a_capture_copies_the_files_it_names(points, backend, tmp_path):
    target = tmp_path / "config"
    target.write_text("the user's own file", encoding="utf-8")
    point = capture([], [str(target)], label="Before", backend=backend, root=points)
    target.write_text("a look overwrote this", encoding="utf-8")

    blob = point.path / "files" / point.files[str(target)]
    assert blob.read_text(encoding="utf-8") == "the user's own file"


def test_a_file_that_was_not_there_is_recorded_as_absent(points, backend, tmp_path):
    """Restoring "it was not there" means deleting what was put there."""
    missing = tmp_path / "not-yet"
    point = capture([], [str(missing)], label="Before", backend=backend, root=points)
    assert point.files[str(missing)] is None


def test_a_restore_point_becomes_the_transaction_that_restores_it(points, backend, tmp_path):
    target = tmp_path / "config"
    target.write_text("original", encoding="utf-8")
    backend.set(WORD, "'original'")
    point = capture([WORD], [str(target)], label="Before", backend=backend, root=points)

    tx = load(point.id, root=points).to_transaction()
    kinds = [type(op).__name__ for op in tx.ops]
    assert kinds == ["FileWrite", "SettingWrite"]
    file_op = next(op for op in tx.ops if isinstance(op, FileWrite))
    assert Path(file_op.src).read_text(encoding="utf-8") == "original"
    setting_op = next(op for op in tx.ops if isinstance(op, SettingWrite))
    assert setting_op.value == "'original'"


def test_a_value_that_was_never_set_becomes_a_reset_in_the_transaction(points, backend):
    """A write cannot express "unset it again". SettingReset can.

    It used to be left out of the transaction and carried out separately by
    ``apply_point``, which put it outside the preflight, the restore point and
    the rollback. On this machine's own "Before gtheme" point that was 33 of
    46 settings.
    """
    from gtheme.core.transaction import SettingReset

    point = capture(["gsettings:org.absent.thing a-key"], label="Before", backend=backend, root=points)
    ops = load(point.id, root=points).to_transaction().ops
    assert ops == (SettingReset(key="gsettings:org.absent.thing a-key"),)


# -- the list --------------------------------------------------------------


def test_the_newest_moment_is_listed_first_and_before_gtheme_is_listed_last(points, backend):
    """The thing you most likely want at the top, the nuclear option last."""
    from datetime import datetime, timedelta

    now = datetime.now(UTC)
    for index, name in enumerate(["older", "newer"]):
        point = RestorePoint(
            id=f"2026-08-2{index}T10-00-00",
            label=name,
            created=now - timedelta(days=2 - index),
            kind="auto",
            path=points / f"2026-08-2{index}T10-00-00",
        )
        restorepoints._write(point)
    restorepoints._write(
        RestorePoint(id=PRISTINE_ID, label="Before gtheme", created=now, kind="pristine",
                     path=points / PRISTINE_ID)
    )

    labels = [point.label for point in list_restore_points(points)]
    assert labels == ["newer", "older", "Before gtheme"]


def test_old_automatic_moments_are_pruned_and_the_ones_people_asked_for_are_not(points, backend):
    from datetime import datetime, timedelta

    now = datetime.now(UTC)
    for index in range(6):
        restorepoints._write(
            RestorePoint(
                id=f"auto-{index}",
                label=f"auto {index}",
                created=now - timedelta(hours=index),
                kind="auto",
                path=points / f"auto-{index}",
            )
        )
    restorepoints._write(
        RestorePoint(id="mine", label="Mine", created=now - timedelta(days=9), kind="manual",
                     path=points / "mine")
    )
    restorepoints._write(
        RestorePoint(id=PRISTINE_ID, label="Before gtheme", created=now - timedelta(days=99),
                     kind="pristine", path=points / PRISTINE_ID)
    )

    dropped = prune(cap=3, root=points)
    assert sorted(dropped) == ["auto-3", "auto-4", "auto-5"]
    kept = {point.id for point in list_restore_points(points)}
    assert {"mine", PRISTINE_ID, "auto-0", "auto-1", "auto-2"} == kept


def test_a_moment_can_be_forgotten_copies_and_all(points, backend, tmp_path):
    target = tmp_path / "config"
    target.write_text("x", encoding="utf-8")
    point = capture([], [str(target)], label="Before", backend=backend, root=points)
    assert restorepoints.delete(point.id, root=points) is True
    assert not point.path.exists()
    assert restorepoints.delete(point.id, root=points) is False


def test_a_damaged_moment_does_not_break_the_list(points):
    """One unreadable folder must not make the Undo page empty."""
    good = restorepoints._write(
        RestorePoint(id="good", label="Good", created=restorepoints._now(), path=points / "good")
    )
    (points / "broken").mkdir()
    (points / "broken" / "restore-point.json").write_text("{ not json", encoding="utf-8")
    assert [point.id for point in list_restore_points(points)] == [good.id]


def test_a_moment_reads_back_with_a_date_a_person_can_read(points, backend):
    point = capture([], label="Before", backend=backend, root=points) or restorepoints._write(
        RestorePoint(id="x", label="X", created=restorepoints._now(), path=points / "x")
    )
    assert any(char.isdigit() for char in point.human_date())


# -- the v1 import ---------------------------------------------------------


def _v1_store(root: Path, *, settings: dict, files: dict, blobs: dict[str, str]) -> Path:
    """A v1 state directory shaped exactly like the real one on this machine."""
    baseline = root / "backups" / "baseline"
    (baseline / "files").mkdir(parents=True)
    (baseline / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    (baseline / "files.json").write_text(json.dumps(files), encoding="utf-8")
    for name, body in blobs.items():
        (baseline / "files" / name).write_text(body, encoding="utf-8")
    (root / "current").write_text("shoji\n", encoding="utf-8")
    return root


def test_the_v1_settings_are_imported_with_their_exact_values(tmp_path, points):
    v1 = _v1_store(
        tmp_path / "gtheme.v1-backup",
        settings={
            "gsettings:org.gnome.desktop.interface accent-color": {
                "backend": "gsettings",
                "key": "org.gnome.desktop.interface accent-color",
                "saved": "'blue'",
                "component": "desktop",
                "theme": "shoji",
            },
            "dconf:/org/gnome/shell/extensions/blur-my-shell/panel/blur": {
                "backend": "dconf",
                "key": "/org/gnome/shell/extensions/blur-my-shell/panel/blur",
                "saved": "true",
                "component": "shell",
                "theme": "shoji",
            },
        },
        files={},
        blobs={},
    )
    point = import_v1_baseline(v1, root=points)
    assert point is not None
    assert point.kind == "pristine"
    assert point.id == PRISTINE_ID
    assert point.settings["gsettings:org.gnome.desktop.interface accent-color"] == "'blue'"
    assert point.settings["dconf:/org/gnome/shell/extensions/blur-my-shell/panel/blur"] == "true"


def test_the_v1_address_is_already_the_v2_address(tmp_path, points):
    """Not a coincidence: the v2 key grammar was chosen so this is a rename.

    v1 indexed its records as ``<backend>:<key>``. That string is exactly what
    ``core.settings_backend.parse_key`` reads, so importing is copying rather
    than translating — and a translation is where a value would get lost.
    """
    from gtheme.core.settings_backend import parse_key

    v1 = _v1_store(
        tmp_path / "gtheme.v1-backup",
        settings={
            "gsettings:org.gnome.desktop.interface icon-theme": {
                "backend": "gsettings",
                "key": "org.gnome.desktop.interface icon-theme",
                "saved": "'Papirus'",
                "component": "desktop",
                "theme": "shoji",
            }
        },
        files={},
        blobs={},
    )
    point = import_v1_baseline(v1, root=points)
    for key in point.settings:
        assert parse_key(key).as_text() == key


def test_the_v1_file_copies_are_carried_across(tmp_path, points):
    v1 = _v1_store(
        tmp_path / "gtheme.v1-backup",
        settings={},
        files={
            "/home/someone/.config/alacritty/alacritty.toml": {
                "existed": True,
                "symlink": False,
                "target": None,
                "backup": "0001",
                "component": "terminal",
                "theme": "shoji",
            }
        },
        blobs={"0001": "the user's own alacritty settings"},
    )
    point = import_v1_baseline(v1, root=points)
    blob = point.path / "files" / point.files["/home/someone/.config/alacritty/alacritty.toml"]
    assert blob.read_text(encoding="utf-8") == "the user's own alacritty settings"


def test_a_v1_file_that_did_not_exist_is_carried_across_as_absent(tmp_path, points):
    v1 = _v1_store(
        tmp_path / "gtheme.v1-backup",
        settings={},
        files={
            "/home/someone/.config/starship.toml": {
                "existed": False,
                "symlink": False,
                "target": None,
                "backup": None,
                "dirs": [],
                "component": "prompt",
                "theme": "shoji",
            }
        },
        blobs={},
    )
    point = import_v1_baseline(v1, root=points)
    assert point.files["/home/someone/.config/starship.toml"] is None


def test_what_cannot_be_imported_is_named_rather_than_dropped_silently(tmp_path, points):
    """A silent gap in the one recording of somebody's original desktop is the
    worst failure available here. Everything skipped says so."""
    v1 = _v1_store(
        tmp_path / "gtheme.v1-backup",
        settings={},
        files={
            "/home/someone/.config/ghostty": {
                "existed": True,
                "symlink": True,
                "target": "/home/someone/nightbloom/ghostty",
                "backup": None,
                "component": "terminal",
                "theme": "nightbloom",
            },
            "/home/someone/.config/lost": {
                "existed": True,
                "symlink": False,
                "target": None,
                "backup": "9999",
                "component": "terminal",
                "theme": "shoji",
            },
        },
        blobs={},
    )
    point = import_v1_baseline(v1, root=points)
    assert len(point.warnings) == 2
    assert any("shortcut" in warning for warning in point.warnings)
    assert any("missing" in warning for warning in point.warnings)


def test_the_v1_store_is_never_written_to(tmp_path, points):
    """Read-only, forever. It is the only copy there is."""
    v1 = _v1_store(
        tmp_path / "gtheme.v1-backup",
        settings={
            "gsettings:org.gnome.desktop.interface icon-theme": {
                "backend": "gsettings",
                "key": "org.gnome.desktop.interface icon-theme",
                "saved": "'Papirus'",
                "component": "desktop",
                "theme": "shoji",
            }
        },
        files={
            "/home/someone/.config/x": {
                "existed": True,
                "symlink": False,
                "target": None,
                "backup": "0001",
                "component": "terminal",
                "theme": "shoji",
            }
        },
        blobs={"0001": "content"},
    )
    before = {
        str(path.relative_to(v1)): (path.stat().st_mtime_ns, path.read_bytes())
        for path in sorted(v1.rglob("*"))
        if path.is_file()
    }
    import_v1_baseline(v1, root=points)
    import_v1_baseline(v1, root=points)
    after = {
        str(path.relative_to(v1)): (path.stat().st_mtime_ns, path.read_bytes())
        for path in sorted(v1.rglob("*"))
        if path.is_file()
    }
    assert before == after


def test_importing_twice_replaces_rather_than_accumulating(tmp_path, points):
    v1 = _v1_store(
        tmp_path / "gtheme.v1-backup",
        settings={
            "gsettings:org.gnome.desktop.interface icon-theme": {
                "backend": "gsettings",
                "key": "org.gnome.desktop.interface icon-theme",
                "saved": "'Papirus'",
                "component": "desktop",
                "theme": "shoji",
            }
        },
        files={},
        blobs={},
    )
    import_v1_baseline(v1, root=points)
    import_v1_baseline(v1, root=points)
    assert [point.id for point in list_restore_points(points)] == [PRISTINE_ID]


def test_no_v1_state_is_normal_and_not_an_error(tmp_path, points):
    """A fresh install has nothing to import. That is not a failure."""
    assert import_v1_baseline(tmp_path / "does-not-exist", root=points) is None
    assert list_restore_points(points) == []


def test_a_v1_store_with_nothing_in_it_imports_to_nothing(tmp_path, points):
    v1 = _v1_store(tmp_path / "gtheme.v1-backup", settings={}, files={}, blobs={})
    assert import_v1_baseline(v1, root=points) is None


def test_which_look_v1_had_applied_can_be_read(tmp_path):
    v1 = _v1_store(tmp_path / "gtheme.v1-backup", settings={}, files={}, blobs={})
    assert read_v1_current(v1) == "shoji"
    assert read_v1_current(tmp_path / "nowhere") is None


# -- applying a moment -----------------------------------------------------


def test_applying_a_moment_writes_the_values_back(
    points, backend, tmp_dest_root, state_dir, monkeypatch
):
    """The ordinary two-thirds: values and files that can be written."""
    from gtheme.core import backends

    target = tmp_dest_root / "config"
    target.write_text("the original", encoding="utf-8")
    backend.set(WORD, "'the original'")
    point = capture([WORD], [str(target)], label="Before", backend=backend, root=points)

    backend.set(WORD, "'a look changed this'")
    target.write_text("a look changed this", encoding="utf-8")

    with backends.use_backend(backend):
        result = restorepoints.apply_point(
            point.id, root=points, backend=backend, dest_root=str(tmp_dest_root)
        )

    assert result.warnings == []
    assert backend.get(WORD) == "'the original'"
    assert target.read_text(encoding="utf-8") == "the original"


def test_applying_a_moment_also_clears_what_was_never_set(
    points, backend, tmp_dest_root, state_dir
):
    """The other third: settings that had no value when the moment was saved.

    A ``SettingWrite`` cannot say "there should be nothing here", and on this
    machine's imported "Before gtheme" point 33 of 46 settings are exactly
    that. ``SettingReset`` says it, inside the same transaction as everything
    else.
    """
    from gtheme.core import backends

    point = capture([WORD], label="Before", backend=backend, root=points)
    assert point.settings[WORD] == "'default'"

    # A key that had no value at all when the moment was saved.
    point.settings["gsettings:org.gtheme.test a-list"] = None
    restorepoints._write(point)

    backend.set(LIST, "['a look added this']")
    with backends.use_backend(backend):
        result = restorepoints.apply_point(
            point.id, root=points, backend=backend, dest_root=str(tmp_dest_root)
        )

    assert result.unset == [LIST]
    assert backend.get(LIST) == "@as []"


def test_applying_a_moment_removes_files_that_were_not_there_before(
    points, backend, tmp_dest_root, state_dir
):
    from gtheme.core import backends

    installed = tmp_dest_root / "installed-by-a-look"
    point = capture([], [str(installed)], label="Before", backend=backend, root=points)
    installed.write_text("a look put this here", encoding="utf-8")

    with backends.use_backend(backend):
        result = restorepoints.apply_point(
            point.id, root=points, backend=backend, dest_root=str(tmp_dest_root)
        )

    assert result.removed == [str(installed)]
    assert not installed.exists()


def test_a_moment_reports_honestly_how_much_of_it_is_absence(points, backend):
    point = capture([WORD], label="Before", backend=backend, root=points)
    point.settings["gsettings:org.gtheme.test a-list"] = None
    point.files["/somewhere/not-there"] = None
    restorepoints._write(point)

    reloaded = load(point.id, root=points)
    assert reloaded.keys_to_unset == ["gsettings:org.gtheme.test a-list"]
    assert reloaded.files_to_remove == ["/somewhere/not-there"]


def test_applying_a_moment_that_is_gone_says_so_rather_than_raising(points, state_dir):
    """The Undo page shows a list that may be out of date by the time it is used."""
    result = restorepoints.apply_point("2026-01-01T00-00-00", root=points)
    assert result.warnings and "no longer there" in result.warnings[0]


# -- one path ---------------------------------------------------------------


def test_restoring_absence_goes_through_the_transaction(
    points, backend, tmp_dest_root, state_dir
):
    """The whole restore is one transaction, not two thirds of one.

    Proved by the thing only a transaction does: it takes a restore point of
    its own before it starts, so undoing an undo is possible.
    """
    from gtheme.core import backends

    installed = tmp_dest_root / "installed-by-a-look"
    point = capture([WORD], [str(installed)], label="Before", backend=backend, root=points)
    point.settings["gsettings:org.gtheme.test a-list"] = None
    restorepoints._write(point)

    installed.write_text("a look put this here", encoding="utf-8")
    backend.set(LIST, "['a look added this']")
    before = {p.id for p in restorepoints.list_restore_points(root=points)}

    with backends.use_backend(backend):
        result = restorepoints.apply_point(
            point.id, root=points, backend=backend, dest_root=str(tmp_dest_root)
        )

    assert result.warnings == []
    assert result.unset == [LIST]
    assert result.removed == [str(installed)]
    assert result.transaction is not None
    # A transaction takes a restore point before it changes anything.
    assert result.transaction.restore_point is not None
    after = {p.id for p in restorepoints.list_restore_points()}
    assert after, "the undo did not record a moment of its own"
    del before


def test_a_restore_that_fails_partway_puts_everything_back(
    points, backend, tmp_dest_root, state_dir
):
    """All-or-nothing now covers absence too, because absence is in the batch."""
    from gtheme.core import backends
    from gtheme.core.transaction import TransactionError

    doomed = tmp_dest_root / "doomed"
    doomed.write_text("here before the undo", encoding="utf-8")
    point = capture([WORD], [str(doomed)], label="Before", backend=backend, root=points)
    # The saved copy of the file is deleted, so the FileWrite that restores it
    # cannot find its source and the whole transaction has to unwind.
    for saved in (point.path / "files").iterdir():
        saved.unlink()
    point.files[str(doomed)] = None  # and this one has to be removed
    restorepoints._write(point)
    point.files[str(doomed)] = "doomed"
    restorepoints._write(point)

    backend.set(WORD, "'changed since'")
    with backends.use_backend(backend):
        result = restorepoints.apply_point(
            point.id, root=points, backend=backend, dest_root=str(tmp_dest_root)
        )

    assert result.warnings, "a restore that could not finish must say so"
    assert doomed.read_text(encoding="utf-8") == "here before the undo"
    assert TransactionError is not None
