"""Compiling a Look into operations — and never into anything executable."""

from __future__ import annotations

from pathlib import Path

import pytest

from gtheme.core.settings_backend import parse_key
from gtheme.core.transaction import (
    ExtensionEnable,
    ExtensionInstall,
    FileWrite,
    SettingWrite,
)
from gtheme.preset.compile import compile_preset, extension_setting_key
from gtheme.preset.model import (
    Component,
    ExtensionInstallEntry,
    ExtensionsBlock,
    ExtensionSetting,
    FileEntry,
    Meta,
    Preset,
    SettingEntry,
)


def _preset(**extra) -> Preset:
    base = {
        "format": 2,
        "meta": Meta(
            name="t",
            title="T",
            description="",
            author="",
            version="1.0.0",
            screenshots=["s.png"],
        ),
    }
    base.update(extra)
    return Preset(**base)


def _ship(directory: Path, *relatives: str) -> Path:
    """Put real bytes at each relative source, because compiling now checks.

    A Look that names a file it does not ship compiles to *fewer* operations
    plus a warning (see the missing-source tests at the bottom of this file),
    so a test about the shape of a FileWrite has to give it a file that exists.
    """
    for relative in relatives:
        target = Path(directory) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("body\n", encoding="utf-8")
    return Path(directory)


def test_files_become_file_writes_with_absolute_sources(tmp_path):
    preset = _preset(files=[FileEntry(src="a/b.css", dest="~/.config/b.css", mode="0644")])
    result = compile_preset(preset, _ship(tmp_path, "a/b.css"))
    (op,) = result.ops
    assert isinstance(op, FileWrite)
    assert op.src == str(tmp_path / "a/b.css")
    assert Path(op.src).is_absolute()
    assert op.dest == "~/.config/b.css"
    assert op.mode == "0644"


def test_settings_become_setting_writes_that_keep_their_component():
    preset = _preset(
        settings=[
            SettingEntry(
                key="gsettings:org.gnome.desktop.interface color-scheme",
                value="'prefer-dark'",
                component=Component.COLORS,
            )
        ]
    )
    (op,) = compile_preset(preset, ".").ops
    assert isinstance(op, SettingWrite)
    assert op.component == "colors"
    assert op.merge == "none"


def test_a_list_union_setting_keeps_its_merge_mode():
    preset = _preset(
        settings=[
            SettingEntry(
                key="gsettings:org.gnome.shell enabled-extensions",
                value="['a@x']",
                merge="list-union",
            )
        ]
    )
    (op,) = compile_preset(preset, ".").ops
    assert op.merge == "list-union"


def test_files_are_emitted_before_settings(tmp_path):
    preset = _preset(
        files=[FileEntry(src="a", dest="~/a")],
        settings=[SettingEntry(key="gsettings:a.b c", value="1")],
    )
    kinds = [type(op) for op in compile_preset(preset, _ship(tmp_path, "a")).ops]
    assert kinds == [FileWrite, SettingWrite]


def test_nothing_a_look_compiles_to_can_execute(tmp_path):
    """The closed operation set is the guarantee, so assert on the whole set."""
    preset = _preset(
        files=[FileEntry(src="a", dest="~/a", mode="0755")],
        settings=[SettingEntry(key="gsettings:a.b c", value="1")],
        extensions=ExtensionsBlock(enable=["x@y"]),
    )
    allowed = (FileWrite, SettingWrite, ExtensionEnable, ExtensionInstall)
    ops = compile_preset(preset, _ship(tmp_path, "a")).ops
    assert ops and all(isinstance(op, allowed) for op in ops)


# ── a Look that does not ship one of its files ───────────────────────────


def test_a_missing_source_is_skipped_and_named_not_fatal(tmp_path):
    """Pins review finding preset/loader.py:162.

    The loader has always promised a partial apply for a Look missing one of
    its sources ("… is missing, so <dest> will not be written"), but compiling
    emitted the write anyway, and Transaction.plan() then refused the whole
    transaction — the Look could not be previewed or applied at all, not even
    the file that WAS there. Before the fix this compiled two FileWrites and
    warned about nothing.
    """
    preset = _preset(
        files=[
            FileEntry(src="here.css", dest="~/.config/here.css"),
            FileEntry(src="gone.css", dest="~/.config/gone.css"),
        ]
    )
    result = compile_preset(preset, _ship(tmp_path, "here.css"))

    writes = [op for op in result.ops if isinstance(op, FileWrite)]
    assert [op.dest for op in writes] == ["~/.config/here.css"]
    assert result.warnings == ["'gone.css' is missing, so ~/.config/gone.css will not be written"]


def test_a_look_missing_a_file_can_still_be_planned(tmp_path):
    """Pins review finding preset/loader.py:162 — the end-to-end half.

    The compiled transaction has to be plannable, since that is what the Looks
    page needs to show a preview at all; before the fix plan() raised
    TransactionError('this look is missing one of its files').
    """
    directory = _ship(tmp_path / "look", "here.css")
    dest_root = tmp_path / "dest"
    dest_root.mkdir()
    preset = _preset(
        files=[
            FileEntry(src="here.css", dest=f"{dest_root}/here.css"),
            FileEntry(src="gone.css", dest=f"{dest_root}/gone.css"),
        ]
    )
    result = compile_preset(preset, directory, dest_root=str(dest_root))

    diff = result.transaction.plan()
    assert [entry.op.dest for entry in diff.entries] == [f"{dest_root}/here.css"]


def test_a_folder_where_a_file_was_promised_is_skipped_and_named(tmp_path):
    """Pins review finding preset/loader.py:162 (the folder half).

    A Look copies one file at a time; a src that is a directory used to reach
    the transaction and break it in the same way a missing one did.
    """
    (tmp_path / "adir").mkdir()
    preset = _preset(files=[FileEntry(src="adir", dest="~/.config/adir")])
    result = compile_preset(preset, tmp_path)

    assert list(result.ops) == []
    assert result.warnings == [
        "'adir' is a folder — a Look copies one file at a time, "
        "so ~/.config/adir will not be written"
    ]


# ── add-ons ──────────────────────────────────────────────────────────────


def test_with_no_knowledge_of_the_machine_every_add_on_is_just_enabled():
    preset = _preset(extensions=ExtensionsBlock(enable=["a@x", "b@x"]))
    result = compile_preset(preset, ".")
    assert [op.uuid for op in result.ops] == ["a@x", "b@x"]
    assert all(isinstance(op, ExtensionEnable) for op in result.ops)
    assert result.warnings == []


def test_a_missing_ego_add_on_becomes_an_install_offer():
    preset = _preset(
        extensions=ExtensionsBlock(
            enable=["a@x"],
            install=[ExtensionInstallEntry(uuid="a@x", ego_pk=42)],
        )
    )
    result = compile_preset(preset, ".", installed_extensions=set())
    install, enable = result.ops
    assert isinstance(install, ExtensionInstall)
    assert install.ego_pk == 42 and install.source == "ego"
    assert isinstance(enable, ExtensionEnable)


def test_a_missing_private_add_on_is_a_named_skip_not_an_offer():
    preset = _preset(
        extensions=ExtensionsBlock(
            enable=["intellibar@nightbloom.local"],
            install=[
                ExtensionInstallEntry(uuid="intellibar@nightbloom.local", source="local-only")
            ],
        )
    )
    result = compile_preset(preset, ".", installed_extensions=set())
    assert result.ops == ()
    assert len(result.warnings) == 1
    warning = result.warnings[0]
    assert "intellibar@nightbloom.local" in warning
    assert "won't apply" in warning


def test_an_installed_add_on_is_enabled_with_no_offer():
    preset = _preset(extensions=ExtensionsBlock(enable=["a@x"]))
    result = compile_preset(preset, ".", installed_extensions={"a@x"})
    assert [type(op) for op in result.ops] == [ExtensionEnable]


def test_an_alternate_that_is_installed_wins():
    preset = _preset(
        extensions=ExtensionsBlock(
            enable=["ding@rastersoft.com"],
            install=[
                ExtensionInstallEntry(
                    uuid="ding@rastersoft.com",
                    alternates=["gtk4-ding@smedius.gitlab.com"],
                )
            ],
        )
    )
    result = compile_preset(
        preset, ".", installed_extensions={"gtk4-ding@smedius.gitlab.com"}
    )
    (op,) = result.ops
    assert op.uuid == "gtk4-ding@smedius.gitlab.com"
    assert result.warnings == []


def test_add_on_settings_are_dropped_when_the_add_on_will_not_be_there():
    preset = _preset(
        extensions=ExtensionsBlock(
            enable=["p@x"],
            install=[ExtensionInstallEntry(uuid="p@x", source="local-only")],
            settings=[
                ExtensionSetting(uuid="p@x", schema_id="a.b.c", key="k", value="true")
            ],
        )
    )
    result = compile_preset(preset, ".", installed_extensions=set())
    assert result.ops == ()


def test_add_on_settings_survive_when_the_add_on_will_be_there():
    preset = _preset(
        extensions=ExtensionsBlock(
            enable=["p@x"],
            settings=[
                ExtensionSetting(uuid="p@x", schema_id="a.b.c", key="k", value="true")
            ],
        )
    )
    result = compile_preset(preset, ".", installed_extensions={"p@x"})
    setting, enable = result.ops
    assert isinstance(setting, SettingWrite)
    assert setting.key == "gsettings:a.b.c k"
    assert setting.component == "addons"
    assert isinstance(enable, ExtensionEnable)


# ── the key grammar ──────────────────────────────────────────────────────


def test_a_plain_add_on_setting_uses_the_schema_form():
    setting = ExtensionSetting(
        uuid="b@x",
        schema_id="org.gnome.shell.extensions.blur-my-shell.panel",
        key="blur",
        value="true",
    )
    key = extension_setting_key(setting)
    assert key == "gsettings:org.gnome.shell.extensions.blur-my-shell.panel blur"
    assert parse_key(key)


def test_a_relocatable_add_on_setting_carries_its_path():
    setting = ExtensionSetting(
        uuid="b@x",
        schema_id="org.gnome.shell.extensions.burn-my-windows-profile",
        key="name",
        value="'iris'",
        path="/org/gnome/shell/extensions/burn-my-windows/profiles/1/",
    )
    key = extension_setting_key(setting)
    assert key.startswith("gsettings-path:")
    parsed = parse_key(key)
    assert parsed.path == "/org/gnome/shell/extensions/burn-my-windows/profiles/1/"


def test_a_relocatable_path_must_be_a_path():
    with pytest.raises(ValueError):
        ExtensionSetting(uuid="b@x", schema_id="a.b", key="k", value="1", path="no-slashes")


# ── the transaction it produces ──────────────────────────────────────────


def test_the_transaction_carries_the_destination_root_and_a_human_label(tmp_path):
    preset = _preset()
    result = compile_preset(preset, ".", dest_root=str(tmp_path))
    assert result.transaction.dest_root == str(tmp_path)
    assert result.transaction.label == "T"
