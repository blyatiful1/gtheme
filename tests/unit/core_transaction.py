"""Planning and applying: the one code path the preview and the apply share.

A preview computed differently from the apply is a lie waiting to happen, so
``plan()`` produces the :class:`Diff` that the preview dialog renders *and* that
``apply()`` consumes. Everything here is about that agreement holding: what the
preview says will change is what changes, in the order it said, and what it
says will be skipped is skipped.

The defect-tag regressions live in ``tests/regression/``; this file is the
ordinary behaviour underneath them.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from gtheme.core import backends, placeholders
from gtheme.core.settings_backend import MemoryBackend
from gtheme.core.transaction import (
    Diff,
    DiffEntry,
    ExtensionEnable,
    ExtensionInstall,
    FileRemove,
    FileWrite,
    Progress,
    SettingReset,
    SettingWrite,
    Transaction,
    TransactionError,
    installed_extension_uuids,
)

SCHEMA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<schemalist>
  <schema id="org.gnome.shell" path="/org/gnome/shell/">
    <key name="enabled-extensions" type="as"><default>[]</default></key>
  </schema>
  <schema id="org.gtheme.test" path="/org/gtheme/test/">
    <key name="a-word" type="s"><default>'default'</default></key>
    <key name="a-number" type="i"><default>0</default></key>
  </schema>
</schemalist>
"""

WORD = "gsettings:org.gtheme.test a-word"
NUMBER = "gsettings:org.gtheme.test a-number"
ENABLED = "gsettings:org.gnome.shell enabled-extensions"


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
    """A transaction bench that reaches nothing real.

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


def _tx(bench: Bench, ops, label: str = "DEMO") -> Transaction:
    """A Look being applied.

    ``look=`` is passed as well as ``label=``, and that is the point rather than
    boilerplate: ``look`` is what says "a whole Look is being applied" and is
    what turns the switch cleanup and the current-Look record on. ``label`` is
    only a name for a saved moment, and every saved moment has one — which is
    why keying the cleanup on it made putting one back strip the Look off the
    desktop. Tests that mean "one change made from a page" build a
    ``Transaction`` with neither.
    """
    return Transaction(ops, dest_root=str(bench.root), label=label, look=label.lower())


#: Everything here is declared ``mutating`` and every test is seamed. The
#: handful that touch neither settings nor files still ask for ``state_dir``,
#: because the guard in ``tests/conftest.py`` reads fixture names and a test
#: that quietly skipped would look, from the summary line, exactly like one
#: that passed.
pytestmark = pytest.mark.mutating


# -- the diff --------------------------------------------------------------


def test_a_plan_reads_the_current_value_and_the_wanted_one(bench):
    bench.backend.set(WORD, "'before'")
    diff = _tx(bench, [SettingWrite(key=WORD, value="'after'", component="colors")]).plan()
    entry = diff.entries[0]
    assert (entry.before, entry.after, entry.no_op) == ("'before'", "'after'", False)


def test_a_value_already_at_its_target_is_kept_in_the_diff_as_a_no_op(bench):
    """"Nothing to do" is worth showing as such, not worth hiding."""
    bench.backend.set(WORD, "'same'")
    diff = _tx(bench, [SettingWrite(key=WORD, value="'same'")]).plan()
    assert diff.entries[0].no_op is True
    assert diff.changes == []


def test_planning_touches_nothing(bench):
    bench.backend.set(WORD, "'before'")
    source = bench.add_file("f", "content")
    _tx(bench, [SettingWrite(key=WORD, value="'after'"), FileWrite(src=source, dest="~/f")]).plan()
    assert bench.backend.get(WORD) == "'before'"
    assert not (bench.root / "f").exists()


def test_the_diff_is_in_the_order_the_work_happens(bench):
    """Files, then settings, then add-ons — in the preview and in the apply."""
    source = bench.add_file("f", "content")
    bench.install("a@b")
    diff = _tx(
        bench,
        [
            ExtensionEnable(uuid="a@b"),
            SettingWrite(key=WORD, value="'x'"),
            FileWrite(src=source, dest="~/f"),
        ],
    ).plan()
    kinds = [type(entry.op).__name__ for entry in diff.entries]
    assert kinds == ["FileWrite", "SettingWrite", "ExtensionEnable"]


def test_a_setting_for_something_not_installed_is_planned_as_a_no_op(bench):
    """The preview must not promise a change the apply is going to skip."""
    diff = _tx(bench, [SettingWrite(key="gsettings:org.absent.thing a-key", value="'x'")]).plan()
    assert diff.entries[0].no_op is True


def test_novice_lines_group_by_part_of_the_desktop_and_count_add_ons(state_dir):
    diff = Diff(
        entries=[
            DiffEntry(op=SettingWrite(key="a", value="1"), component="colors", summary=""),
            DiffEntry(op=SettingWrite(key="b", value="2"), component="colors", summary=""),
            DiffEntry(op=SettingWrite(key="c", value="3"), component="wallpaper", summary=""),
            DiffEntry(op=ExtensionEnable(uuid="a@b"), component="addons", summary=""),
            DiffEntry(op=ExtensionEnable(uuid="c@d"), component="addons", summary=""),
            DiffEntry(op=ExtensionEnable(uuid="e@f"), component="addons", summary=""),
        ]
    )
    assert diff.to_novice_lines() == ["Background picture", "Colours", "3 add-ons"]


def test_novice_lines_say_nothing_about_what_does_not_change(state_dir):
    diff = Diff(
        entries=[
            DiffEntry(op=SettingWrite(key="a", value="1"), component="colors", summary="", no_op=True)
        ]
    )
    assert diff.to_novice_lines() == []


def test_every_component_a_look_can_declare_has_words_for_it(state_dir):
    """A component with no phrase would vanish from the preview silently."""
    from gtheme.core.transaction import _COMPONENT_PHRASES
    from gtheme.preset.model import Component

    for member in Component:
        assert member.value in _COMPONENT_PHRASES, f"no plain-words phrase for {member.value!r}"


def test_the_words_shown_to_a_user_pass_the_jargon_rules(state_dir):
    """The preview is the most-read text in the app; it may not say "shell"."""
    from gtheme.core.transaction import _COMPONENT_PHRASES
    from gtheme.ui import jargon

    for singular, plural in _COMPONENT_PHRASES.values():
        assert jargon.check(singular) == []
        assert jargon.check(plural.replace("{count}", "3")) == []


# -- applying --------------------------------------------------------------


def test_files_are_written_before_settings(bench):
    """A Look that points a setting at a file it ships must ship it first."""
    source = bench.add_file("theme.css", "the look's stylesheet")
    order: list[Progress] = []

    _tx(
        bench,
        [
            SettingWrite(key=WORD, value="'points at the file'"),
            FileWrite(src=source, dest="~/.config/demo/theme.css"),
        ],
    ).apply(lambda stage, _text: order.append(stage), restore_point=False)

    assert order.index(Progress.WRITING_FILES) < order.index(Progress.WRITING_SETTINGS)


def test_the_progress_callback_narrates_the_whole_run(bench):
    source = bench.add_file("f", "content")
    bench.install("a@b")
    seen: list[tuple[Progress, str]] = []
    _tx(
        bench,
        [
            FileWrite(src=source, dest="~/f"),
            SettingWrite(key=WORD, value="'x'"),
            ExtensionEnable(uuid="a@b"),
        ],
    ).apply(lambda stage, text: seen.append((stage, text)), restore_point=False)

    stages = [stage for stage, _text in seen]
    assert stages[0] is Progress.PLANNING
    assert stages[-1] is Progress.DONE
    assert all(text for _stage, text in seen), "every step must say something"


def test_a_templated_file_has_its_tokens_filled_in(bench):
    source = bench.add_file("wall.xml", "<file>{{ home }}/pictures/a.jpg</file>")
    _tx(bench, [FileWrite(src=source, dest="~/.local/wall.xml", template=True)]).apply(
        restore_point=False
    )
    written = (bench.root / ".local" / "wall.xml").read_text(encoding="utf-8")
    assert "{{" not in written
    assert str(bench.root) in written


def test_templating_something_that_is_not_text_fails_before_it_truncates(bench):
    """v1's bug: the destination was emptied and the error came afterwards."""
    source = bench.look / "binary"
    source.write_bytes(b"\x00\x01\x02\xff")
    dest = bench.root / "binary"
    dest.write_text("the user's file", encoding="utf-8")

    with pytest.raises(TransactionError, match="not text"):
        _tx(bench, [FileWrite(src=str(source), dest="~/binary", template=True)]).apply(
            restore_point=False
        )
    assert dest.read_text(encoding="utf-8") == "the user's file"


def test_permissions_are_honoured_and_privilege_bits_are_stripped(bench):
    """A Look may choose permissions. It may not hand itself privileges.

    The destination used to be ``~/bin/script``, with a ``#!/bin/sh`` body —
    which review-report C1 cited as the repository's own proof that a Look
    could write a program onto the command path and have the suite call it
    correct. A Look may no longer write there at all (the test below pins
    that), so this one keeps what it was really about — the mode bits — at a
    destination a Look legitimately owns.
    """
    source = bench.add_file("emblem.svg", "<svg/>\n")
    _tx(
        bench,
        [FileWrite(src=source, dest="~/.local/share/gtheme/assets/emblem.svg", mode="4755")],
    ).apply(restore_point=False)
    written = bench.root / ".local" / "share" / "gtheme" / "assets" / "emblem.svg"
    assert written.stat().st_mode & 0o7777 == 0o755


def test_a_look_that_is_missing_one_of_its_own_files_fails_before_writing(bench):
    good = bench.add_file("good", "content")
    with pytest.raises(TransactionError, match="missing one of its files"):
        _tx(
            bench,
            [
                FileWrite(src=good, dest="~/good"),
                FileWrite(src=str(bench.look / "not-here"), dest="~/bad"),
            ],
        ).apply(restore_point=False)
    assert not (bench.root / "good").exists()


def test_a_list_union_setting_adds_to_what_is_there(bench):
    bench.backend.set(ENABLED, "['mine@user']")
    _tx(
        bench,
        [SettingWrite(key=ENABLED, value="['theirs@look']", merge="list-union")],
    ).apply(restore_point=False)
    assert bench.backend.get(ENABLED) == "['mine@user', 'theirs@look']"


def test_a_plain_setting_replaces_what_is_there(bench):
    bench.backend.set(ENABLED, "['mine@user']")
    _tx(bench, [SettingWrite(key=ENABLED, value="['theirs@look']")]).apply(restore_point=False)
    assert bench.backend.get(ENABLED) == "['theirs@look']"


def test_a_wrongly_typed_value_is_a_failure_not_a_silent_skip(bench):
    with pytest.raises(TransactionError):
        _tx(bench, [SettingWrite(key=NUMBER, value="'not a number'")]).apply(restore_point=False)


# -- add-ons ---------------------------------------------------------------


def test_the_first_acceptable_add_on_that_is_present_wins(bench):
    """ding and gtk4-ding do the same job; a Look should get whichever is here."""
    bench.install("gtk4-ding@smedius.gitlab.com")
    _tx(
        bench,
        [ExtensionEnable(uuid="ding@rastersoft.com", alternates=("gtk4-ding@smedius.gitlab.com",))],
    ).apply(restore_point=False)
    assert "gtk4-ding@smedius.gitlab.com" in bench.backend.get(ENABLED)


def test_an_add_on_that_is_not_installed_is_a_named_skip(bench):
    source = bench.add_file("f", "content")
    result = _tx(
        bench,
        [FileWrite(src=source, dest="~/f"), ExtensionEnable(uuid="not-here@nowhere")],
    ).apply(restore_point=False)
    assert any("isn't installed" in reason for _op, reason in result.skipped)


def test_a_private_add_on_says_it_is_private_rather_than_offering_a_download(bench):
    """F12: a ``local-only`` add-on can never be fetched, and saying "install
    it from the Add-ons page" about one would send the user somewhere useless."""
    source = bench.add_file("f", "content")
    result = _tx(
        bench,
        [
            FileWrite(src=source, dest="~/f"),
            ExtensionInstall(uuid="intellibar@nightbloom.local", source="local-only"),
        ],
    ).apply(restore_point=False)
    reasons = [reason for _op, reason in result.skipped]
    assert any("private add-on" in reason for reason in reasons)


def test_a_downloadable_add_on_points_at_the_page_that_can_fetch_it(bench):
    source = bench.add_file("f", "content")
    result = _tx(
        bench,
        [
            FileWrite(src=source, dest="~/f"),
            ExtensionInstall(uuid="blur-my-shell@aunetx", ego_pk=3193),
        ],
    ).apply(restore_point=False)
    assert any("Add-ons page" in reason for _op, reason in result.skipped)


def test_an_add_on_that_is_already_here_is_not_reported_as_a_problem(bench):
    bench.install("blur-my-shell@aunetx")
    source = bench.add_file("f", "content")
    result = _tx(
        bench,
        [FileWrite(src=source, dest="~/f"), ExtensionInstall(uuid="blur-my-shell@aunetx")],
    ).apply(restore_point=False)
    assert result.skipped == []


def test_which_add_ons_are_present_is_read_from_where_they_are_unpacked(bench):
    bench.install("a@b")
    bench.install("c@d")
    assert {"a@b", "c@d"} <= installed_extension_uuids()


# -- the ledger ------------------------------------------------------------


def test_a_change_made_from_a_page_does_not_tidy_up_after_a_look(bench):
    """Switching Looks tidies up. A single deliberate edit is not a switch.

    v1's rule, and the reason it matters: a ``--only`` overlay that stripped
    the rest of the desktop would turn "change my highlight colour" into
    "revert everything else I had".
    """
    source = bench.add_file("f", "the look's file")
    _tx(bench, [FileWrite(src=source, dest="~/.config/demo/f")], label="LOOK").apply(
        restore_point=False
    )
    assert (bench.root / ".config" / "demo" / "f").is_file()

    Transaction(
        [SettingWrite(key=WORD, value="'a single edit'")],
        dest_root=str(bench.root),
    ).apply(restore_point=False)

    assert (bench.root / ".config" / "demo" / "f").is_file()
    from gtheme.core.ledger import read_ledger

    assert "LOOK" in read_ledger()


# -- absence: SettingReset and FileRemove ----------------------------------
#
# Two thirds of a pristine restore point is things that were NOT there. Before
# these two ops existed, undoing that part happened outside the transaction —
# no confinement preflight, no restore point, no rollback. These tests are the
# proof that it happens inside now.


def test_a_reset_puts_a_setting_back_to_having_no_value(bench):
    bench.backend.set(WORD, "'meddled'")
    result = _tx(bench, [SettingReset(key=WORD)]).apply(restore_point=False)
    assert result.applied == [SettingReset(key=WORD)]
    assert bench.backend.get(WORD) == "'default'"


def test_a_reset_is_a_no_op_when_the_setting_is_already_where_it_would_land(bench):
    """Already at the schema's own value is already right, and the preview says so."""
    diff = _tx(bench, [SettingReset(key=WORD)]).plan()
    assert diff.entries[0].no_op is True
    assert diff.changes == []


def test_a_reset_of_a_missing_setting_is_a_named_skip_not_a_crash(bench):
    """AS8, from the other side: skipped with a sentence, alongside real work."""
    bench.backend.set(WORD, "'meddled'")
    result = _tx(
        bench,
        [SettingReset(key="gsettings:org.absent.thing a-key"), SettingReset(key=WORD)],
    ).apply(restore_point=False)
    assert result.applied == [SettingReset(key=WORD)]
    assert [reason for _op, reason in result.skipped] == [
        "that part of your desktop isn't installed here"
    ]


def test_a_reset_of_a_missing_setting_alone_is_the_AS4_refusal(bench):
    """Nothing applied and something skipped is "nothing could be changed"."""
    with pytest.raises(TransactionError, match="nothing could be changed"):
        _tx(bench, [SettingReset(key="gsettings:org.absent.thing a-key")]).apply(
            restore_point=False
        )


def test_a_removal_deletes_the_file(bench):
    (bench.root / "gone.conf").write_text("x", encoding="utf-8")
    result = _tx(bench, [FileRemove(dest="~/gone.conf")]).apply(restore_point=False)
    assert result.applied == [FileRemove(dest="~/gone.conf")]
    assert not (bench.root / "gone.conf").exists()


def test_removing_something_that_is_already_gone_is_not_an_error(bench):
    result = _tx(bench, [FileRemove(dest="~/never-there")]).apply(restore_point=False)
    assert result.applied == [FileRemove(dest="~/never-there")]
    assert result.skipped == []


def test_a_removal_outside_the_destination_root_is_refused_before_anything_happens(bench):
    """Deleting outside the root is a worse accident than writing outside it."""
    outside = bench.look / "not-yours"
    outside.write_text("someone else's file", encoding="utf-8")
    victim = bench.root / "also-here"
    victim.write_text("x", encoding="utf-8")
    with pytest.raises(TransactionError):
        _tx(bench, [FileRemove(dest=str(outside)), FileRemove(dest="~/also-here")]).apply(
            restore_point=False
        )
    assert outside.is_file(), "the escaping removal happened anyway"
    assert victim.is_file(), "the preflight let work start before checking every op"


def test_a_removal_leaves_alone_anything_that_is_not_an_ordinary_file(bench):
    """F1: what cannot be copied cannot be put back, so it is not deleted."""
    import os

    fifo = bench.root / "a-pipe"
    os.mkfifo(fifo)
    (bench.root / "ordinary.conf").write_text("x", encoding="utf-8")
    result = _tx(
        bench, [FileRemove(dest="~/a-pipe"), FileRemove(dest="~/ordinary.conf")]
    ).apply(restore_point=False)
    assert result.applied == [FileRemove(dest="~/ordinary.conf")]
    assert "not an ordinary file" in result.skipped[0][1]
    assert fifo.exists()
    assert not (bench.root / "ordinary.conf").exists()


def test_a_failure_after_a_removal_puts_the_file_back(bench):
    """The rollback covers removals like every other operation."""
    target = bench.root / "precious.conf"
    target.write_text("the original contents", encoding="utf-8")
    with pytest.raises(TransactionError):
        _tx(
            bench,
            [
                FileRemove(dest="~/precious.conf"),
                FileWrite(src=str(bench.look / "missing-source"), dest="~/other"),
            ],
        ).apply(restore_point=False)
    assert target.read_text(encoding="utf-8") == "the original contents"


def test_a_failure_after_a_reset_puts_the_value_back(bench):
    bench.backend.set(WORD, "'the value the user chose'")
    with pytest.raises(TransactionError):
        _tx(
            bench,
            [
                SettingReset(key=WORD),
                FileWrite(src=str(bench.look / "missing-source"), dest="~/other"),
            ],
        ).apply(restore_point=False)
    assert bench.backend.get(WORD) == "'the value the user chose'"


def test_the_preview_says_put_back_and_remove_in_plain_words(bench):
    bench.backend.set(WORD, "'meddled'")
    (bench.root / "leftover.conf").write_text("x", encoding="utf-8")
    diff = _tx(
        bench, [SettingReset(key=WORD), FileRemove(dest="~/leftover.conf")]
    ).plan()
    lines = diff.to_novice_lines()
    assert "Put back to how the system had it" in lines
    assert "Remove leftover.conf" in lines


def test_several_removals_are_counted_rather_than_listed(bench):
    for name in ("one.conf", "two.conf", "three.conf"):
        (bench.root / name).write_text("x", encoding="utf-8")
    diff = _tx(bench, [FileRemove(dest=f"~/{n}") for n in ("one.conf", "two.conf", "three.conf")]).plan()
    assert diff.to_novice_lines() == ["Remove 3 files"]


def test_the_new_ops_pass_the_jargon_rules(state_dir):
    from gtheme.ui import jargon

    for text in ("Put back to how the system had it", "Remove 3 files", "Remove a-file.conf"):
        assert jargon.check(text) == []


# -- which Look is applied right now ---------------------------------------
#
# A third question the state directory answers, and the one the app used to
# guess at. The ledger says what each Look owns and stays true for every Look
# that still has anything on the desktop; this says which one the person chose,
# and has one answer or none.


def test_applying_a_look_records_which_look_it_was(bench):
    from gtheme.core.ledger import current_look, current_record

    assert current_look() is None, "nothing applied, nothing recorded"

    source = bench.add_file("f", "the look's file")
    Transaction(
        [FileWrite(src=source, dest="~/.config/demo/f")],
        dest_root=str(bench.root),
        label="MAGMA — Molten Glass",
        look="magma",
    ).apply(restore_point=False)

    assert current_look() == "magma"
    # Both are kept: the name is what a lookup matches on, the label is what
    # the person was shown. Recording only one of the two is how the guess
    # this replaced went wrong.
    assert current_record() == {"name": "magma", "label": "MAGMA — Molten Glass"}


def test_a_change_made_from_a_page_is_not_a_look_and_records_none(bench):
    """One deliberate edit does not make the desktop "a Look"."""
    from gtheme.core.ledger import current_look

    Transaction(
        [SettingWrite(key=WORD, value="'a single edit'")], dest_root=str(bench.root)
    ).apply(restore_point=False)
    assert current_look() is None


def test_a_page_edit_does_not_clear_the_look_you_are_using(bench):
    """Changing one thing by hand leaves you on the Look you picked."""
    from gtheme.core.ledger import current_look, set_current_look

    set_current_look("magma", label="MAGMA — Molten Glass")
    Transaction(
        [SettingWrite(key=WORD, value="'a single edit'")], dest_root=str(bench.root)
    ).apply(restore_point=False)
    assert current_look() == "magma"


def test_switching_looks_replaces_the_recorded_one(bench):
    from gtheme.core.ledger import current_look

    for name, label in (("magma", "MAGMA"), ("netrunner", "NETRUNNER")):
        Transaction(
            [SettingWrite(key=WORD, value=f"'{name}'")],
            dest_root=str(bench.root),
            label=label,
            look=name,
        ).apply(restore_point=False)
    assert current_look() == "netrunner"


def test_a_look_that_applied_nothing_is_not_recorded_as_the_one_you_are_using(bench):
    """AS4's other half.

    A transaction where everything was skipped did not apply anything, and
    recording it as the current Look would be a lie the Undo page then has to
    live with — v1's exact bug, which wrote the theme name into ``current``
    before finding out nothing worked.
    """
    from gtheme.core.ledger import current_look

    with pytest.raises(TransactionError, match="nothing could be changed"):
        Transaction(
            [SettingReset(key="gsettings:org.absent.thing a-key")],
            dest_root=str(bench.root),
            label="GHOST",
            look="ghost",
        ).apply(restore_point=False)
    assert current_look() is None


def test_a_failed_switch_leaves_you_on_the_look_you_had(bench):
    from gtheme.core.ledger import current_look, set_current_look

    set_current_look("magma", label="MAGMA")
    with pytest.raises(TransactionError):
        Transaction(
            [SettingReset(key="gsettings:org.absent.thing a-key")],
            dest_root=str(bench.root),
            label="GHOST",
            look="ghost",
        ).apply(restore_point=False)
    assert current_look() == "magma"


def test_going_back_to_a_saved_moment_means_you_are_on_no_look(bench):
    """You are using the desktop as it was, which nothing here can name."""
    from gtheme.core import restorepoints
    from gtheme.core.ledger import current_look, set_current_look

    set_current_look("magma", label="MAGMA")
    bench.backend.set(WORD, "'before'")
    point = restorepoints.capture([WORD], label="My desktop, 25 August", kind="manual")
    bench.backend.set(WORD, "'after'")

    restorepoints.apply_point(point.id, backend=bench.backend, dest_root=str(bench.root))

    assert bench.backend.get(WORD) == "'before'"
    assert current_look() is None
