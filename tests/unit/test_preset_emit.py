"""The TOML emitter is only trustworthy if it round-trips, so that is the test."""

from __future__ import annotations

import tomllib

import pytest

from gtheme.preset.emit import dumps_preset
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


def _full_preset() -> Preset:
    """A Look using every part of the format, including the awkward ones."""
    return Preset(
        format=2,
        meta=Meta(
            name="round-trip",
            title='A "quoted" title — with an em dash',
            description="Line one.\nLine two, with a backslash \\ in it.",
            author="tester",
            version="1.0.0",
            min_shell="49",
            screenshots=["screenshots/one.png", "screenshots/two.png"],
        ),
        palette={"bg": "#101a14", "accent": "#7fd6a2"},
        files=[
            FileEntry(src="a/b.css", dest="~/.config/a/b.css"),
            FileEntry(src="bin/x", dest="~/.local/bin/x", mode="0755", template=True),
        ],
        settings=[
            SettingEntry(
                key="gsettings:org.gnome.desktop.interface color-scheme",
                value="'prefer-dark'",
                component=Component.COLORS,
            ),
            SettingEntry(
                key="gsettings:org.gnome.shell enabled-extensions",
                value="@as []",
                merge="list-union",
                component=Component.ADDONS,
            ),
        ],
        extensions=ExtensionsBlock(
            enable=["blur-my-shell@aunetx", "ding@rastersoft.com"],
            install=[
                ExtensionInstallEntry(uuid="blur-my-shell@aunetx", ego_pk=3193),
                ExtensionInstallEntry(
                    uuid="ding@rastersoft.com",
                    source="local-only",
                    alternates=["gtk4-ding@smedius.gitlab.com"],
                ),
            ],
            settings=[
                ExtensionSetting(
                    uuid="blur-my-shell@aunetx",
                    schema_id="org.gnome.shell.extensions.blur-my-shell.panel",
                    key="blur",
                    value="true",
                ),
                ExtensionSetting(
                    uuid="blur-my-shell@aunetx",
                    schema_id="org.gnome.shell.extensions.burn-my-windows-profile",
                    key="name",
                    value="'iris'",
                    path="/org/gnome/shell/extensions/burn-my-windows/profiles/1/",
                ),
            ],
        ),
    )


def test_round_trips_through_tomllib():
    original = _full_preset()
    reloaded = Preset.model_validate(tomllib.loads(dumps_preset(original)))
    assert reloaded == original


def test_header_becomes_comments_and_does_not_disturb_parsing():
    text = dumps_preset(_full_preset(), header="A note.\nA second line.")
    assert text.splitlines()[0] == "# A note."
    assert text.splitlines()[1] == "# A second line."
    assert Preset.model_validate(tomllib.loads(text)).meta.name == "round-trip"


@pytest.mark.parametrize(
    "value",
    [
        "'@as []'",
        'a "quoted" string',
        "a\\backslash",
        "tab\there",
        "newline\nhere",
        "unicode — ẞ ✿",
    ],
)
def test_awkward_values_survive(value):
    preset = _full_preset().model_copy(update={"palette": {"weird": value}})
    reloaded = Preset.model_validate(tomllib.loads(dumps_preset(preset)))
    assert reloaded.palette["weird"] == value


def test_a_minimal_look_omits_the_optional_sections():
    minimal = Preset(
        format=2,
        meta=Meta(
            name="minimal",
            title="Minimal",
            description="",
            author="",
            version="1.0.0",
            screenshots=["a.png"],
        ),
    )
    text = dumps_preset(minimal)
    assert "[palette]" not in text
    assert "[[files]]" not in text
    assert "[extensions]" not in text
    assert Preset.model_validate(tomllib.loads(text)) == minimal
