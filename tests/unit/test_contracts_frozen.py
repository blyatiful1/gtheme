"""The frozen contracts: shapes that exist now, bodies that land in Wave 1.

Two things are checked here. First, that the dataclasses and signatures Waves 1
and 2 code against really exist and really have the fields the plan froze —
a contract nobody can construct is not a contract. Second, that the parts not
built yet fail *loudly* with ``NotImplementedError`` rather than quietly
returning None, which would look like success.
"""

from __future__ import annotations

import inspect

import pytest

from gtheme.core import rescue
from gtheme.core.transaction import (
    Diff,
    DiffEntry,
    ExtensionEnable,
    ExtensionInstall,
    FileWrite,
    Progress,
    SettingWrite,
    Transaction,
    TransactionError,
    TransactionResult,
)
from gtheme.terminal.model import Palette, ReloadSemantics, TerminalAdapter, TerminalState

# -- operations ------------------------------------------------------------


def test_file_write_fields():
    op = FileWrite(src="ghostty/config", dest="~/.config/ghostty/config", template=True)
    assert (op.src, op.dest, op.template, op.mode, op.merge) == (
        "ghostty/config",
        "~/.config/ghostty/config",
        True,
        None,
        "none",
    )


def test_setting_write_fields_and_merge_default():
    op = SettingWrite(key="gsettings:org.a.b c", value="'x'")
    assert op.merge == "none"
    assert op.component is None
    assert SettingWrite(key="k", value="v", merge="list-union").merge == "list-union"


def test_extension_ops_carry_what_install_needs():
    assert ExtensionEnable(uuid="a@b").alternates == ()
    install = ExtensionInstall(uuid="a@b", ego_pk=3193)
    assert (install.ego_pk, install.source) == (3193, "ego")
    assert ExtensionInstall(uuid="x@y.local", source="local-only").source == "local-only"


def test_operations_are_immutable():
    """A planned operation that could be edited after the preview is a lie."""
    op = SettingWrite(key="k", value="v")
    with pytest.raises(Exception):  # noqa: B017 - dataclasses raise FrozenInstanceError
        op.value = "something else"


def test_progress_stages_cover_the_whole_run():
    assert {p.value for p in Progress} >= {
        "planning",
        "snapshotting",
        "writing-files",
        "writing-settings",
        "extensions",
        "done",
        "rolled-back",
    }


# -- diff ------------------------------------------------------------------


def test_diff_separates_real_changes_from_no_ops():
    diff = Diff(
        entries=[
            DiffEntry(op=SettingWrite(key="a", value="1"), component="colors", summary="Colours"),
            DiffEntry(
                op=SettingWrite(key="b", value="2"),
                component="fonts",
                summary="Text",
                no_op=True,
            ),
        ]
    )
    assert len(diff.entries) == 2
    assert [e.summary for e in diff.changes] == ["Colours"]


def test_novice_rendering_groups_and_counts():
    """Wave 1 landed the body; the shape it renders is still the contract."""
    diff = Diff(
        entries=[
            DiffEntry(op=SettingWrite(key="a", value="1"), component="wallpaper", summary="x"),
            DiffEntry(op=SettingWrite(key="b", value="2"), component="colors", summary="x"),
            DiffEntry(op=ExtensionEnable(uuid="a@b"), component="addons", summary="x"),
            DiffEntry(op=ExtensionEnable(uuid="c@d"), component="addons", summary="x"),
            DiffEntry(
                op=SettingWrite(key="c", value="3"), component="fonts", summary="x", no_op=True
            ),
        ]
    )
    assert diff.to_novice_lines() == ["Background picture", "Colours", "2 add-ons"]


# -- transaction -----------------------------------------------------------


def test_a_transaction_holds_its_operations_immutably():
    tx = Transaction([SettingWrite(key="a", value="1")], label="NIGHTBLOOM")
    assert isinstance(tx.ops, tuple)
    assert tx.label == "NIGHTBLOOM"


def test_an_empty_transaction_plans_and_applies_to_nothing(tmp_dest_root, state_dir):
    """Wave 1 landed the bodies. An empty transaction is still a valid one.

    Both seams are requested deliberately: without them this would plan against
    the real home directory and apply against the real state directory.
    """
    tx = Transaction(dest_root=str(tmp_dest_root))
    assert tx.plan().changes == []
    result = tx.apply(restore_point=False)
    assert result.applied == [] and result.skipped == []


def test_apply_takes_a_progress_callback_and_a_restore_point_switch():
    """F4 froze this signature; Wave 1 fills the body, not the shape."""
    params = inspect.signature(Transaction.apply).parameters
    assert "progress_cb" in params
    assert params["restore_point"].default is True
    assert params["restore_point"].kind is inspect.Parameter.KEYWORD_ONLY


def test_transaction_error_says_whether_the_desktop_was_put_back():
    err = TransactionError("nope", op=SettingWrite(key="a", value="1"), rolled_back=False)
    assert err.rolled_back is False
    assert TransactionError("nope").rolled_back is True


def test_transaction_result_records_skips_with_reasons():
    op = ExtensionInstall(uuid="x@y.local", source="local-only")
    result = TransactionResult(diff=Diff(), skipped=[(op, "that add-on isn't installed here")])
    assert result.skipped[0][1]


# -- rescue ----------------------------------------------------------------


def test_rescue_speaks_plainly_when_there_is_nothing_to_undo(state_dir, capsys):
    """Wave 1 landed the rescue. What a frightened user reads still matters."""
    assert rescue.run_rescue() == 0
    message = capsys.readouterr().out
    assert "nothing to put back" in message
    for internal in ("NotImplementedError", "baseline", "dconf", "traceback"):
        assert internal not in message


def test_rescue_never_needs_gtk():
    """The rescue path exists for the case where the graphical session is dead."""
    source = inspect.getsource(rescue)
    assert "gi.repository" not in source
    assert "import gi" not in source


# -- terminal --------------------------------------------------------------


def test_the_terminal_protocol_names_the_four_operations():
    for name in ("detect", "current", "apply"):
        assert hasattr(TerminalAdapter, name)
    assert "reload_semantics" in TerminalAdapter.__annotations__


def test_reload_semantics_all_have_a_plain_sentence():
    for member in ReloadSemantics:
        sentence = member.sentence()
        assert sentence.endswith(".")
        assert sentence[0].isupper()


def test_a_palette_must_have_sixteen_ansi_colours_or_none():
    Palette(name="ok", background="#000000", foreground="#ffffff")
    Palette(name="ok", background="#000", foreground="#fff", ansi=tuple("#000000" for _ in range(16)))
    with pytest.raises(ValueError, match="16 colours"):
        Palette(name="bad", background="#000", foreground="#fff", ansi=("#000000",))


def test_opacity_is_bounded():
    with pytest.raises(ValueError, match="between 0 and 1"):
        Palette(name="bad", background="#000", foreground="#fff", opacity=1.5)


def test_terminal_state_records_a_foreign_config_root():
    """F7: ~/.config/ghostty is a symlink into a separate rice repository here."""
    from pathlib import Path

    state = TerminalState(
        installed=True,
        config_path=Path("~/.config/ghostty").expanduser(),
        foreign_root=Path("~/nightbloom/ghostty").expanduser(),
    )
    assert state.foreign_root is not None
    assert state.notes == []
