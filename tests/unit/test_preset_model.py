"""Preset format v2. The format is frozen; these tests are what freezes it."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from gtheme.preset.model import (
    Component,
    ExtensionsBlock,
    Preset,
    format_validation_errors,
    load_preset_dir,
)

MINIMAL = {
    "format": 2,
    "meta": {
        "name": "nightbloom",
        "title": "NIGHTBLOOM",
        "description": "A solarpunk glasshouse at dusk.",
        "author": "blyatiful1",
        "version": "1.0.0",
        "screenshots": ["screenshots/desktop-light.png"],
    },
}


def test_a_minimal_look_validates():
    preset = Preset.model_validate(MINIMAL)
    assert preset.format == 2
    assert preset.meta.title == "NIGHTBLOOM"
    assert preset.files == []
    assert preset.extensions.enable == []


def test_screenshots_may_be_empty_in_the_model():
    """Because a restore point is this model too, and has nothing to photograph.

    "A Look nobody can preview is the thing this app exists to spare people"
    is still true, and is still enforced — at PUBLISH time, by
    ``tools/build_index.py``. See ``test_preset_registry.py``. Enforcing it
    here instead made every machine-written capture claim a picture file it
    had not written, which the loader then warned about on every load.
    """
    preset = Preset.model_validate({**MINIMAL, "meta": {**MINIMAL["meta"], "screenshots": []}})
    assert preset.meta.screenshots == []


def test_screenshots_key_may_be_omitted_entirely():
    meta = {k: v for k, v in MINIMAL["meta"].items() if k != "screenshots"}
    assert Preset.model_validate({**MINIMAL, "meta": meta}).meta.screenshots == []


def test_screenshots_must_still_be_a_list_of_strings():
    with pytest.raises(ValidationError, match="screenshots"):
        Preset.model_validate({**MINIMAL, "meta": {**MINIMAL["meta"], "screenshots": "one.png"}})


def test_hooks_are_not_a_thing_any_more():
    """The safety promise, as a test.

    "Looks only change settings. They can't run programs on your computer." is
    true because ``extra='forbid'`` makes a hooks section a validation error,
    not because everybody remembered not to add one.
    """
    with pytest.raises(ValidationError) as caught:
        Preset.model_validate({**MINIMAL, "hooks": {"post_apply": ["rm -rf /"]}})
    assert "hooks" in str(caught.value)


def test_a_typo_is_an_error_not_a_shrug():
    meta = {**MINIMAL["meta"], "descriptoin": "typo"}
    with pytest.raises(ValidationError, match="descriptoin"):
        Preset.model_validate({**MINIMAL, "meta": meta})


def test_format_1_is_not_valid_v2():
    with pytest.raises(ValidationError):
        Preset.model_validate({**MINIMAL, "format": 1})


def test_name_must_be_a_safe_slug():
    for bad in ["../escape", "Has Spaces", "UPPER", "/absolute"]:
        with pytest.raises(ValidationError):
            Preset.model_validate({**MINIMAL, "meta": {**MINIMAL["meta"], "name": bad}})


def test_settings_carry_a_component_from_the_closed_registry():
    preset = Preset.model_validate(
        {
            **MINIMAL,
            "settings": [
                {
                    "key": "gsettings:org.gnome.desktop.interface color-scheme",
                    "value": "'prefer-dark'",
                    "component": "colors",
                }
            ],
        }
    )
    assert preset.settings[0].component is Component.COLORS


def test_an_unknown_component_is_rejected():
    with pytest.raises(ValidationError):
        Preset.model_validate(
            {
                **MINIMAL,
                "settings": [{"key": "gsettings:a.b c", "value": "1", "component": "vibes"}],
            }
        )


def test_settings_default_to_no_merge():
    preset = Preset.model_validate(
        {**MINIMAL, "settings": [{"key": "gsettings:a.b c", "value": "1"}]}
    )
    assert preset.settings[0].merge == "none"
    assert preset.settings[0].component is Component.OTHER


def test_list_union_merge_is_allowed():
    preset = Preset.model_validate(
        {
            **MINIMAL,
            "settings": [
                {
                    "key": "gsettings:org.gnome.shell enabled-extensions",
                    "value": "['blur-my-shell@aunetx']",
                    "merge": "list-union",
                    "component": "addons",
                }
            ],
        }
    )
    assert preset.settings[0].merge == "list-union"


def test_an_invented_merge_mode_is_rejected():
    with pytest.raises(ValidationError):
        Preset.model_validate(
            {**MINIMAL, "settings": [{"key": "gsettings:a.b c", "value": "1", "merge": "clobber"}]}
        )


def test_file_mode_must_look_like_a_permission_string():
    with pytest.raises(ValidationError):
        Preset.model_validate(
            {**MINIMAL, "files": [{"src": "a", "dest": "~/a", "mode": "rwxr-xr-x"}]}
        )


# -- extensions ------------------------------------------------------------


def test_extension_source_defaults_to_ego():
    block = ExtensionsBlock.model_validate({"enable": ["a@b"]})
    assert block.install_for("a@b").source == "ego"


def test_local_only_source_is_allowed():
    block = ExtensionsBlock.model_validate(
        {
            "enable": ["intellibar@nightbloom.local"],
            "install": [{"uuid": "intellibar@nightbloom.local", "source": "local-only"}],
        }
    )
    assert block.install_for("intellibar@nightbloom.local").source == "local-only"


def test_an_invented_source_is_rejected():
    with pytest.raises(ValidationError):
        ExtensionsBlock.model_validate(
            {"enable": ["a@b"], "install": [{"uuid": "a@b", "source": "some-random-website"}]}
        )


def test_extension_settings_must_name_an_enabled_add_on():
    with pytest.raises(ValidationError, match="not in extensions.enable"):
        ExtensionsBlock.model_validate(
            {
                "enable": ["a@b"],
                "settings": [{"uuid": "c@d", "schema_id": "org.x", "key": "k", "value": "1"}],
            }
        )


def test_install_entries_must_name_an_enabled_add_on():
    with pytest.raises(ValidationError, match="not in extensions.enable"):
        ExtensionsBlock.model_validate({"enable": ["a@b"], "install": [{"uuid": "c@d"}]})


def test_duplicate_install_entries_are_rejected():
    with pytest.raises(ValidationError, match="two"):
        ExtensionsBlock.model_validate(
            {"enable": ["a@b"], "install": [{"uuid": "a@b"}, {"uuid": "a@b"}]}
        )


def test_child_schemas_are_addressed_by_schema_and_key():
    """blur-my-shell has eight child schemas and 'blur' in several of them."""
    block = ExtensionsBlock.model_validate(
        {
            "enable": ["blur-my-shell@aunetx"],
            "settings": [
                {
                    "uuid": "blur-my-shell@aunetx",
                    "schema_id": "org.gnome.shell.extensions.blur-my-shell.panel",
                    "key": "blur",
                    "value": "true",
                },
                {
                    "uuid": "blur-my-shell@aunetx",
                    "schema_id": "org.gnome.shell.extensions.blur-my-shell.overview",
                    "key": "blur",
                    "value": "false",
                },
            ],
        }
    )
    assert {s.schema_id for s in block.settings} == {
        "org.gnome.shell.extensions.blur-my-shell.panel",
        "org.gnome.shell.extensions.blur-my-shell.overview",
    }


def test_relocatable_path_must_be_bracketed_by_slashes():
    with pytest.raises(ValidationError, match="start and end with"):
        ExtensionsBlock.model_validate(
            {
                "enable": ["burn-my-windows@schneegans.github.com"],
                "settings": [
                    {
                        "uuid": "burn-my-windows@schneegans.github.com",
                        "schema_id": "org.gnome.shell.extensions.burn-my-windows-profile",
                        "key": "fire-enable-effect",
                        "value": "true",
                        "path": "org/gnome/no/leading/slash",
                    }
                ],
            }
        )


# -- loading ---------------------------------------------------------------


def test_load_preset_dir_reads_a_folder(tmp_path):
    (tmp_path / "theme.toml").write_text(
        """
        format = 2
        [meta]
        name = "demo"
        title = "Demo"
        description = "A demo."
        author = "someone"
        version = "1.0.0"
        screenshots = ["a.png"]
        """,
        encoding="utf-8",
    )
    assert load_preset_dir(tmp_path).meta.name == "demo"


def test_load_preset_dir_says_which_file_is_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="theme.toml"):
        load_preset_dir(tmp_path)


def test_broken_toml_is_reported_as_such(tmp_path):
    (tmp_path / "theme.toml").write_text("format = = 2", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid TOML"):
        load_preset_dir(tmp_path)


def test_errors_are_formatted_for_a_human():
    lines: list[str] = []
    try:
        Preset.model_validate({**MINIMAL, "meta": {**MINIMAL["meta"], "screenshots": 7}})
    except ValidationError as exc:
        lines = format_validation_errors(exc)
    assert lines
    assert any("meta.screenshots" in line for line in lines)


def test_format_validation_errors_passes_other_exceptions_through():
    assert format_validation_errors(ValueError("plain")) == ["plain"]
