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


def test_files_become_file_writes_with_absolute_sources(tmp_path):
    preset = _preset(files=[FileEntry(src="a/b.css", dest="~/.config/b.css", mode="0644")])
    result = compile_preset(preset, tmp_path)
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


def test_files_are_emitted_before_settings():
    preset = _preset(
        files=[FileEntry(src="a", dest="~/a")],
        settings=[SettingEntry(key="gsettings:a.b c", value="1")],
    )
    kinds = [type(op) for op in compile_preset(preset, ".").ops]
    assert kinds == [FileWrite, SettingWrite]


def test_nothing_a_look_compiles_to_can_execute():
    """The closed operation set is the guarantee, so assert on the whole set."""
    preset = _preset(
        files=[FileEntry(src="a", dest="~/a", mode="0755")],
        settings=[SettingEntry(key="gsettings:a.b c", value="1")],
        extensions=ExtensionsBlock(enable=["x@y"]),
    )
    allowed = (FileWrite, SettingWrite, ExtensionEnable, ExtensionInstall)
    assert all(isinstance(op, allowed) for op in compile_preset(preset, ".").ops)


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
