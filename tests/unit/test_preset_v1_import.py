"""The v1 importer, and the guarantee that nothing is dropped silently.

The hook tests are the load-bearing ones. v2's promise — *"Looks only change
settings. They can't run programs on your computer."* — is only honest if the
conversion that removes hooks tells the user what it removed, per hook, in
words that say what was lost.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from gtheme.preset.emit import dumps_preset
from gtheme.preset.model import Component, Preset
from gtheme.preset.v1_import import (
    classify_setting,
    convert_dir,
    convert_v1,
    parse_string_list,
    write_look,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "v1" / "demo"
GOLDEN = FIXTURE.parent / "demo-expected.toml"


def _minimal_v1(**extra) -> dict:
    raw = {
        "meta": {"name": "t", "title": "T", "version": "1.0.0"},
        "files": [{"component": "wallpaper", "src": "w.png", "dest": "~/w.png"}],
    }
    raw.update(extra)
    return raw


# ── the golden conversion ────────────────────────────────────────────────


def test_golden_conversion_is_stable():
    """The committed golden is what the converter produces, byte for byte."""
    result = convert_dir(FIXTURE)
    assert dumps_preset(result.preset) == GOLDEN.read_text(encoding="utf-8")


def test_the_golden_is_itself_a_valid_look():
    assert Preset.model_validate(tomllib.loads(GOLDEN.read_text(encoding="utf-8")))


# ── hooks: the doctrine ──────────────────────────────────────────────────


def test_every_hook_produces_its_own_warning():
    result = convert_dir(FIXTURE)
    hook_warnings = [w for w in result.warnings if "was dropped" in w and "-apply step" in w]
    assert len(hook_warnings) == 2, result.warnings


def test_a_hook_warning_names_the_script_and_says_what_it_can_no_longer_do():
    result = convert_dir(FIXTURE)
    joined = "\n".join(result.warnings)
    assert "hooks/post.sh" in joined
    assert "hooks/pre.sh" in joined
    assert "can never run a program on your computer" in joined


def test_a_hook_that_wanted_a_password_says_so():
    result = convert_dir(FIXTURE)
    assert any("asked for your password" in w for w in result.warnings)


def test_the_converted_look_has_no_place_to_put_a_hook():
    """Not a warning test — a format test. There is no field to smuggle into."""
    result = convert_dir(FIXTURE)
    assert "hooks" not in result.preset.model_dump()
    with pytest.raises(ValueError):
        Preset.model_validate(
            {
                **tomllib.loads(GOLDEN.read_text(encoding="utf-8")),
                "hooks": [{"script": "x.sh"}],
            }
        )


# ── the other losses ─────────────────────────────────────────────────────


def test_a_folder_source_is_dropped_with_a_warning():
    result = convert_dir(FIXTURE)
    assert not any(entry.src == "files/bin" for entry in result.preset.files)
    assert any("files/bin" in w and "one file at a time" in w for w in result.warnings)


def test_required_packages_and_fonts_are_named():
    result = convert_dir(FIXTURE)
    joined = "\n".join(result.warnings)
    assert "btop" in joined and "starship" in joined
    assert "Iosevka Nerd Font" in joined


def test_based_on_is_reported():
    result = convert_dir(FIXTURE)
    assert any("based_on" in w for w in result.warnings)


def test_v1_three_digit_mode_becomes_four():
    result = convert_v1(
        _minimal_v1(
            files=[{"component": "commands", "src": "x", "dest": "~/x", "mode": "755"}],
            meta={"name": "t", "title": "T", "version": "1"},
        ),
        screenshots=["s.png"],
    )
    assert result.preset.files[0].mode == "0755"
    assert any("0755" in w for w in result.warnings)


# ── the add-on list ──────────────────────────────────────────────────────


def test_enabled_extensions_becomes_the_extensions_block():
    result = convert_dir(FIXTURE)
    assert result.preset.extensions.enable == [
        "blur-my-shell@aunetx",
        "user-theme@gnome-shell-extensions.gcampax.github.com",
    ]
    assert not any("enabled-extensions" in s.key for s in result.preset.settings)


def test_requires_extensions_are_folded_in_without_duplicating():
    """hyperclass' v1 gap: it listed add-ons but never turned them on."""
    result = convert_v1(
        _minimal_v1(requires={"extensions": ["a@x", "b@x"]}, settings=[]),
        screenshots=["s.png"],
    )
    assert result.preset.extensions.enable == ["a@x", "b@x"]


def test_known_add_ons_carry_their_download_id():
    result = convert_dir(FIXTURE)
    by_uuid = {e.uuid: e for e in result.preset.extensions.install}
    assert by_uuid["blur-my-shell@aunetx"].ego_pk == 3193
    assert by_uuid["blur-my-shell@aunetx"].source == "ego"


def test_a_private_add_on_is_marked_local_only():
    result = convert_v1(
        _minimal_v1(requires={"extensions": ["intellibar@nightbloom.local"]}),
        screenshots=["s.png"],
        local_only=frozenset({"intellibar@nightbloom.local"}),
    )
    assert result.preset.extensions.install[0].source == "local-only"


def test_an_unreadable_add_on_list_warns_instead_of_exploding():
    result = convert_v1(
        _minimal_v1(
            settings=[
                {
                    "component": "shell",
                    "backend": "gsettings",
                    "key": "org.gnome.shell enabled-extensions",
                    "value": "<not a list>",
                }
            ]
        ),
        screenshots=["s.png"],
    )
    assert result.preset.extensions.enable == []
    assert any("could not be read" in w for w in result.warnings)


# ── key grammar and classification ───────────────────────────────────────


def test_keys_are_rewritten_into_the_frozen_grammar():
    result = convert_dir(FIXTURE)
    keys = [s.key for s in result.preset.settings]
    assert "gsettings:org.gnome.desktop.interface color-scheme" in keys
    assert "dconf:/org/gnome/shell/extensions/dash-to-dock/dock-position" in keys


def test_every_converted_key_parses():
    from gtheme.core.settings_backend import parse_key

    for setting in convert_dir(FIXTURE).preset.settings:
        assert parse_key(setting.key)


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("org.gnome.desktop.background picture-uri", Component.WALLPAPER),
        ("/io/github/jeffshee/hanabi-extension/video-path", Component.WALLPAPER),
        ("org.gnome.desktop.interface icon-theme", Component.ICONS),
        ("org.gnome.desktop.interface cursor-theme", Component.CURSOR),
        ("org.gnome.desktop.interface monospace-font-name", Component.FONTS),
        ("org.gnome.desktop.interface accent-color", Component.COLORS),
        ("org.gnome.desktop.interface gtk-theme", Component.COLORS),
        ("/org/gnome/shell/extensions/user-theme/name", Component.SHELL_THEME),
        ("/org/gnome/Ptyxis/Profiles/x/palette", Component.TERMINAL),
        ("/org/gnome/shell/extensions/dash-to-dock/dock-position", Component.ADDONS),
    ],
)
def test_the_key_decides_the_component_not_the_v1_label(key, expected):
    assert classify_setting(key, "desktop") == expected


def test_an_unknown_key_falls_back_to_the_v1_label():
    assert classify_setting("some.other.schema key", "monitor") == Component.TERMINAL
    assert classify_setting("some.other.schema key", "nonsense") == Component.OTHER


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("@as []", []),
        ("[]", []),
        ("", []),
        ("['a', 'b']", ["a", "b"]),
        ("@as ['a']", ["a"]),
        ("nonsense", []),
        ("'a string'", []),
    ],
)
def test_string_list_parsing(text, expected):
    assert parse_string_list(text) == expected


# ── screenshots ──────────────────────────────────────────────────────────


def test_a_v1_theme_with_no_pictures_borrows_its_wallpaper():
    result = convert_v1(_minimal_v1())
    assert result.preset.meta.screenshots == ["w.png"]


def test_a_theme_with_nothing_to_show_refuses_to_convert():
    with pytest.raises(ValueError, match="no picture"):
        convert_v1(_minimal_v1(files=[]))


def test_a_screenshots_folder_wins(tmp_path):
    theme = tmp_path / "t"
    (theme / "screenshots").mkdir(parents=True)
    (theme / "screenshots" / "b.png").write_bytes(b"x")
    (theme / "screenshots" / "a.png").write_bytes(b"x")
    (theme / "theme.toml").write_text(
        '[meta]\nname="t"\ntitle="T"\nversion="1"\n', encoding="utf-8"
    )
    assert convert_dir(theme).preset.meta.screenshots == [
        "screenshots/a.png",
        "screenshots/b.png",
    ]


def test_a_theme_without_a_name_refuses_to_convert():
    with pytest.raises(ValueError, match="no \\[meta\\].name"):
        convert_v1({"meta": {}})


# ── materialising a converted Look ───────────────────────────────────────


def test_write_look_copies_only_what_the_look_still_needs(tmp_path):
    out = tmp_path / "demo"
    result = write_look(FIXTURE, out)
    assert (out / "theme.toml").is_file()
    assert (out / "files/wallpaper/demo.png").is_file()
    assert (out / "files/theme.css").is_file()
    # the dropped folder is not carried over
    assert not (out / "files/bin").exists()
    assert result.preset.meta.name == "demo"


def test_write_look_produces_a_look_that_loads(tmp_path):
    from gtheme.preset.loader import load

    write_look(FIXTURE, tmp_path / "demo")
    loaded = load(tmp_path / "demo")
    assert loaded.ok, loaded.errors
    assert loaded.warnings == []


def test_skipping_a_program_is_reported(tmp_path):
    result = write_look(FIXTURE, tmp_path / "demo", skip=frozenset({"files/theme.css"}))
    assert not (tmp_path / "demo" / "files/theme.css").exists()
    assert any("it is a program" in w for w in result.warnings)


def test_convert_dir_needs_a_manifest(tmp_path):
    with pytest.raises(FileNotFoundError):
        convert_dir(tmp_path)


def test_the_full_set_of_warnings_is_pinned():
    """A golden list, so nobody can quietly stop warning about something."""
    expected = (GOLDEN.parent / "demo-expected-warnings.txt").read_text(encoding="utf-8")
    assert "\n".join(convert_dir(FIXTURE).warnings) + "\n" == expected
