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
from datetime import UTC, datetime
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
from gtheme.core.settings_backend import BackendError, BackendErrorKind, MemoryBackend
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


def test_two_moments_saved_in_the_same_second_do_not_overwrite_each_other(points, backend):
    """The Wave-2 gate lead, closed.

    A moment's folder used to be named after the second it was taken in, so two
    saved inside one second landed in the same folder and the second silently
    replaced the first. Somebody clicking "save how my desktop looks" twice, or
    a Look applying while an automatic point is being taken, lost a moment they
    had been promised — and left a ``.bak`` file beside the survivor, which is
    how the bug was found.
    """
    same_second = datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)

    backend.set(WORD, "'first'")
    first = capture([WORD], label="First", backend=backend, root=points, when=same_second)
    backend.set(WORD, "'second'")
    second = capture([WORD], label="Second", backend=backend, root=points, when=same_second)

    assert first.id != second.id
    assert load(first.id, root=points).settings[WORD] == "'first'"
    assert load(second.id, root=points).settings[WORD] == "'second'"
    assert {point.label for point in list_restore_points(points)} == {"First", "Second"}


def test_the_first_moment_of_a_second_still_gets_the_plain_timestamp(points, backend):
    """Uniqueness is not allowed to make the ordinary name unreadable."""
    point = capture(
        [WORD],
        label="Before",
        backend=backend,
        root=points,
        when=datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC),
    )
    assert point.id == "2026-08-25T12-00-00"


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
    worst failure available here. Everything skipped says so.

    (This test used to assert two warnings, one of them for a symlink record
    carrying a perfectly good target. That expectation was the H10 defect
    written down: such a record is importable and is now imported. The link
    case kept here is the genuinely unimportable one — a link v1 recorded
    without its target — so the "everything skipped is named" property is still
    pinned, on records that really are skipped.)
    """
    v1 = _v1_store(
        tmp_path / "gtheme.v1-backup",
        settings={},
        files={
            "/home/someone/.config/ghostty": {
                "existed": True,
                "symlink": True,
                "target": "",
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


# -- H10: "we cannot restore this" must never compile to "delete it" --------


def _file_ops(point) -> dict[str, object]:
    """``dest -> op`` for the file operations this moment would carry out."""
    from gtheme.core.transaction import FileLink, FileRemove, FileWrite

    return {
        op.dest: op
        for op in point.to_transaction().ops
        if isinstance(op, FileWrite | FileRemove | FileLink)
    }


def test_a_v1_symlink_is_imported_as_the_link_it_was(tmp_path, points):
    """review-report H10, half one. Fails on the old importer.

    v1 recorded ``~/.config/ghostty`` as a link into the user's own dotfiles
    repository, target and all. The importer mapped it to ``None`` — which is
    not "not covered", it is *absence*, and ``to_transaction`` compiles absence
    to ``FileRemove``. So pressing the nuclear "Before gtheme" undo deleted the
    user's own shortcut and left a hole, while the warning attached to it said
    that one was not covered here. ``capture()`` has recorded links as
    ``{"link": target}`` since the same bug was fixed on that side.
    """
    from gtheme.core.transaction import FileLink

    link = "/home/someone/.config/ghostty"
    v1 = _v1_store(
        tmp_path / "gtheme.v1-backup",
        settings={},
        files={
            link: {
                "existed": True,
                "symlink": True,
                "target": "/home/someone/nightbloom/ghostty",
                "backup": None,
                "component": "terminal",
                "theme": "nightbloom",
            }
        },
        blobs={},
    )
    point = import_v1_baseline(v1, root=points)

    assert point.files[link] == {"link": "/home/someone/nightbloom/ghostty"}
    assert link not in point.files_to_remove, "the user's own link is not a deletion"
    op = _file_ops(point)[link]
    assert isinstance(op, FileLink), f"restoring it puts the link back, not {op!r}"
    assert op.target == "/home/someone/nightbloom/ghostty"


def test_a_v1_record_whose_saved_copy_is_gone_is_left_alone_not_deleted(tmp_path, points):
    """review-report H10, half two. Fails on the old importer.

    A record whose blob has been lost says "we cannot put this back". The
    importer recorded it as ``None``, which says "this was not here" — and the
    restore then deleted the file whose only saved copy is the thing that went
    missing. The warning stays; the destination is left out of the moment
    entirely, so the restore does not touch it.
    """
    lost = "/home/someone/.config/lost.conf"
    v1 = _v1_store(
        tmp_path / "gtheme.v1-backup",
        settings={},
        files={
            lost: {
                "existed": True,
                "symlink": False,
                "target": None,
                "backup": "9999",
                "component": "terminal",
                "theme": "shoji",
            }
        },
        blobs={},
    )
    point = import_v1_baseline(v1, root=points)

    assert lost not in point.files
    assert point.files_to_remove == []
    assert _file_ops(point) == {}
    assert any("missing" in warning for warning in point.warnings), (
        "still said out loud — a silent gap here is the worst failure available"
    )


def test_an_imported_v1_baseline_removes_only_what_v1_said_was_absent(tmp_path, points):
    """The whole H10 story in one moment, as a v1 upgrader really has it."""
    v1 = _v1_store(
        tmp_path / "gtheme.v1-backup",
        settings={},
        files={
            "/home/someone/.config/ghostty": {
                "existed": True,
                "symlink": True,
                "target": "/home/someone/dotfiles/ghostty",
                "backup": None,
                "component": "terminal",
                "theme": "shoji",
            },
            "/home/someone/.config/lost.conf": {
                "existed": True,
                "symlink": False,
                "target": None,
                "backup": "9999",
                "component": "terminal",
                "theme": "shoji",
            },
            "/home/someone/.config/installed-by-a-look": {
                "existed": False,
                "symlink": False,
                "target": None,
                "backup": None,
                "dirs": [],
                "component": "terminal",
                "theme": "shoji",
            },
        },
        blobs={},
    )
    point = import_v1_baseline(v1, root=points)
    assert point.files_to_remove == ["/home/someone/.config/installed-by-a-look"], (
        "only a file v1 recorded as not existing may be deleted by going back"
    )


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


class _RefusesOneKey(MemoryBackend):
    """A memory backend that refuses to write one named key.

    The refusal is a ``COMMIT_FAILED`` — the dconf failure the engine may not
    treat as "that part of your desktop isn't installed here" — so a write to
    it is a real transaction failure and not a skip.
    """

    def __init__(self, schema_source, doomed: str, *, then_everything: bool = False) -> None:
        super().__init__(schema_source)
        self._doomed = doomed
        #: After the doomed key has been refused, refuse every further write —
        #: which is what a store that has actually gone away looks like, and
        #: the only way to reach a rollback that could not finish.
        self._then_everything = then_everything
        self._broken = False
        #: Off while the test arranges the desktop it is going to restore, so
        #: the setup writes the same way any other test's would.
        self.armed = False

    def set(self, key: str, value: str) -> None:
        if self.armed and (key == self._doomed or self._broken):
            if key == self._doomed and self._then_everything:
                self._broken = True
            raise BackendError(
                BackendErrorKind.COMMIT_FAILED, "the store refused it", key=key
            )
        super().set(key, value)


def _moment_to_go_back_to(points, backend, tmp_dest_root):
    """A moment covering one file and two settings, then a desktop dirtied since.

    Returns ``(point, config_file)``. Everything the moment covers has been
    changed since it was taken, so restoring it is a real change to every one
    of the three — which is what makes a failure partway through observable.
    """
    config = tmp_dest_root / "config"
    config.write_text("the content the moment saved", encoding="utf-8")
    backend.set(LIST, "['from the moment']")
    backend.set(WORD, "'from the moment'")

    point = capture(
        [LIST, WORD], [str(config)], label="Before", backend=backend, root=points
    )

    config.write_text("changed since the moment", encoding="utf-8")
    backend.set(LIST, "['changed since']")
    backend.set(WORD, "'changed since'")
    backend.armed = True
    return point, config


def test_a_restore_that_fails_partway_puts_everything_back(
    points, schema_source_factory, tmp_dest_root, state_dir
):
    """All-or-nothing covers a restore too — including what it already wrote.

    The failure happens *after* something has landed, which is the only
    arrangement that tests anything: the file is written back first, then the
    list setting, and only then does the word setting's write get refused. The
    rollback has to undo the two that succeeded, and the proof it did is that
    both hold the values the desktop had a moment ago rather than the moment's
    own.

    (Written this way after review-report M18. The previous version failed on
    the transaction's *first* operation — the restore's source blob was deleted,
    so ``_rendered`` raised before anything was written — and then asserted that
    a file which had never been touched still held its old text, plus a closing
    ``assert TransactionError is not None`` that a module object can never
    fail. Deleting the entire settings leg of ``_roll_back`` left it green.)
    """
    from gtheme.core import backends
    from gtheme.core.transaction import TransactionError

    backend = _RefusesOneKey(schema_source_factory(SCHEMA_XML), WORD)
    point, config = _moment_to_go_back_to(points, backend, tmp_dest_root)

    transaction = point.to_transaction()
    transaction.dest_root = str(tmp_dest_root)
    transaction.backend = backend
    with backends.use_backend(backend), pytest.raises(TransactionError) as caught:
        transaction.apply()

    assert "could not change" in str(caught.value)
    assert WORD in str(caught.value), "the failure names the setting it was about"
    assert caught.value.rolled_back is True

    assert backend.get(LIST) == "['changed since']", (
        "the setting the restore had already written must come back to what the "
        "desktop held a moment ago, not stay at the moment's value"
    )
    assert backend.get(WORD) == "'changed since'", "the refused write never landed"
    assert config.read_text(encoding="utf-8") == "changed since the moment", (
        "and the file the restore had already written back comes back too"
    )


def test_a_failed_restore_reports_whether_the_desktop_came_back(
    points, schema_source_factory, tmp_dest_root, state_dir
):
    """review-report L1. Fails on the old ``RestoreResult``, which had no answer.

    ``apply_point`` knew whether the engine's rollback finished — the
    ``TransactionError`` says so — and dropped it, so the Undo page could only
    ever say "that did not work". A half-written *undo* is the one failure the
    app must be able to describe: "nothing was changed" and "part of that
    moment was written and part was not" are different sentences.
    """
    from gtheme.core import backends

    backend = _RefusesOneKey(schema_source_factory(SCHEMA_XML), WORD)
    point, config = _moment_to_go_back_to(points, backend, tmp_dest_root)

    with backends.use_backend(backend):
        result = restorepoints.apply_point(
            point.id, root=points, backend=backend, dest_root=str(tmp_dest_root)
        )

    assert result.warnings, "a restore that could not finish must say so"
    assert result.rolled_back is True
    assert backend.get(LIST) == "['changed since']"
    assert config.read_text(encoding="utf-8") == "changed since the moment"


def test_a_restore_whose_rollback_could_not_finish_does_not_claim_it_did(
    points, schema_source_factory, tmp_dest_root, state_dir
):
    """The serious half of L1: the desktop is somewhere in between, and says so.

    The store stops accepting writes altogether partway through the restore, so
    the rollback cannot put back the setting the restore had already changed.
    ``rolled_back`` is False, and a page that reads it may not print "Your
    desktop is exactly as it was".
    """
    from gtheme.core import backends

    backend = _RefusesOneKey(
        schema_source_factory(SCHEMA_XML), WORD, then_everything=True
    )
    point, _config = _moment_to_go_back_to(points, backend, tmp_dest_root)

    with backends.use_backend(backend):
        result = restorepoints.apply_point(
            point.id, root=points, backend=backend, dest_root=str(tmp_dest_root)
        )

    assert result.warnings
    assert result.rolled_back is False, (
        "the rollback could not put the list setting back, and saying otherwise "
        "is the lie the whole failure-copy design exists to prevent"
    )


# -- what a hand-saved moment covers ----------------------------------------


def test_a_hand_saved_moment_covers_what_the_ownership_ledger_claims(
    points, backend, state_dir
):
    """review-report M14. Fails on the old ``capture``.

    A manual moment's key list came from the descriptor corpus, which is derived
    from GNOME's own schemas and holds no third-party add-on keys at all — while
    the four shipped Looks write between 15 and 24 such keys each. "How my whole
    desktop looked" could not put any of them back. The ownership ledger knows
    exactly which ones gtheme has touched, so a manual moment unions them in.
    """
    from gtheme.core import ledger as ledger_store

    backend.set(LIST, "['what the look wrote']")
    ledger_store.write_entry("MAGMA", [], [LIST])

    point = capture([WORD], label="My desktop", kind="manual", backend=backend, root=points)

    assert point.settings[LIST] == "['what the look wrote']"
    assert point.settings[WORD] == "'default'", "and what was asked for is still there"


def test_an_automatic_moment_covers_exactly_what_its_change_touches(
    points, backend, state_dir
):
    """The union is deliberately manual-only.

    An automatic moment is built from a transaction's diff and already covers
    what is about to change; widening it to the whole ledger would make every
    apply save (and prune, and copy) far more than the change it protects.
    """
    from gtheme.core import ledger as ledger_store

    ledger_store.write_entry("MAGMA", [], [LIST])
    point = capture([WORD], label="Before your last change", backend=backend, root=points)
    assert LIST not in point.settings
