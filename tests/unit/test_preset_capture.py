"""Reading the desktop back out — restore points and shareable Looks.

Everything here runs against the in-memory settings backend with a throwaway
schema compiled for the test, so it exercises the real GVariant machinery and
touches nothing on the machine running it.
"""

from __future__ import annotations

import tomllib
from datetime import datetime
from pathlib import Path

import pytest

from gtheme.preset import capture as cap
from gtheme.preset.model import Component, Preset

#: Applied to every test that writes settings or files. The guard in
#: ``tests/conftest.py`` skips a ``mutating`` test unless a seam is active;
#: here the seam is always the in-memory backend or a temporary state folder.
mutating = pytest.mark.mutating

SCHEMA_ID = "org.gtheme.test.capture"
SCHEMA_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<schemalist>
  <schema id="{SCHEMA_ID}" path="/org/gtheme/test/capture/">
    <key name="color-scheme" type="s"><default>'default'</default></key>
    <key name="picture-uri" type="s"><default>''</default></key>
    <key name="api-token" type="s"><default>''</default></key>
    <key name="icon-theme" type="s"><default>'Adwaita'</default></key>
    <key name="empty-list" type="as"><default>[]</default></key>
  </schema>
</schemalist>
"""


@pytest.fixture
def backend(memory_settings, schema_source_factory):
    memory_settings.schema_source = schema_source_factory(SCHEMA_XML)
    return memory_settings


def key(name: str) -> str:
    return f"gsettings:{SCHEMA_ID} {name}"


# ── reading ──────────────────────────────────────────────────────────────


@mutating
def test_values_come_back_as_gvariant_text(backend):
    backend.set(key("color-scheme"), "'prefer-dark'")
    entries, skipped = cap.capture_settings([key("color-scheme")], backend)
    assert skipped == []
    assert entries[0].value == "'prefer-dark'"


@mutating
def test_an_empty_string_list_keeps_its_type(backend):
    """``@as []`` and ``[]`` are not the same thing to a restore."""
    entries, _ = cap.capture_settings([key("empty-list")], backend)
    assert entries[0].value == "@as []"


@mutating
def test_a_key_from_an_add_on_that_is_gone_is_skipped_not_fatal(backend):
    entries, skipped = cap.capture_settings(
        [key("color-scheme"), "gsettings:org.gtheme.not.installed thing"], backend
    )
    assert len(entries) == 1
    assert skipped == [
        ("gsettings:org.gtheme.not.installed thing", "not present on this computer")
    ]


@mutating
def test_an_unknown_key_in_a_known_schema_is_skipped(backend):
    _entries, skipped = cap.capture_settings([key("no-such-key")], backend)
    assert skipped and "not present" in skipped[0][1]


@mutating
def test_components_are_carried_through(backend):
    entries, _ = cap.capture_settings(
        [key("icon-theme")], backend, components={key("icon-theme"): Component.ICONS}
    )
    assert entries[0].component == Component.ICONS


# ── restore points ───────────────────────────────────────────────────────


@mutating
def test_a_restore_point_is_an_ordinary_look(backend, state_dir: Path):
    backend.set(key("color-scheme"), "'prefer-dark'")
    result = cap.capture_restore_point([key("color-scheme")], backend, label="My desktop")
    assert result.path is not None
    reloaded = Preset.model_validate(
        tomllib.loads((result.path / "theme.toml").read_text(encoding="utf-8"))
    )
    assert reloaded.format == 2
    assert reloaded.settings[0].value == "'prefer-dark'"


@mutating
def test_a_restore_point_lands_under_the_v2_state_folder(backend, state_dir: Path):
    cap.capture_restore_point([key("color-scheme")], backend, label="x")
    assert cap.state_dir() == state_dir
    assert cap.restore_points_dir() == state_dir / "restore-points"
    assert len(cap.list_restore_points()) == 1


def test_the_state_folder_never_touches_v1s(monkeypatch, tmp_path):
    monkeypatch.delenv("GTHEME_STATE_DIR", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert cap.state_dir() == tmp_path / "gtheme" / "v2"


def test_the_current_wallpaper_becomes_the_restore_points_picture(tmp_path):
    """A restore point shows the desktop it would bring back."""
    from gtheme.preset.model import SettingEntry

    image = tmp_path / "wall.png"
    image.write_bytes(b"pretend png")
    entry = SettingEntry(
        key="gsettings:org.gnome.desktop.background picture-uri",
        value=f"'file://{image}'",
        component=Component.WALLPAPER,
    )
    assert cap._wallpaper_source([entry]) == image


@pytest.mark.parametrize(
    "value",
    ["''", "'file:///nowhere/gone.png'", "'file:///etc/passwd'", "'a-slideshow.xml'"],
)
def test_a_wallpaper_that_is_not_a_findable_image_is_not_used(value):
    from gtheme.preset.model import SettingEntry

    entry = SettingEntry(
        key="gsettings:org.gnome.desktop.background picture-uri", value=value
    )
    assert cap._wallpaper_source([entry]) is None


@mutating
def test_a_restore_point_with_no_findable_wallpaper_says_so(backend, state_dir: Path):
    result = cap.capture_restore_point([key("color-scheme")], backend, label="x")
    assert any("no picture" in w for w in result.warnings)


@mutating
def test_owned_files_are_snapshotted_into_the_restore_point(backend, state_dir, tmp_path):
    owned = tmp_path / "gnome-shell.css"
    owned.write_text("/* mine */", encoding="utf-8")
    result = cap.capture_restore_point(
        [key("color-scheme")],
        backend,
        label="x",
        owned_files=[(owned, "~/.local/share/themes/X/gnome-shell/gnome-shell.css")],
    )
    assert result.path is not None
    assert (result.path / "files" / "gnome-shell.css").read_text() == "/* mine */"
    assert result.preset.files[0].dest.endswith("gnome-shell.css")


@mutating
def test_enabled_add_ons_are_recorded_so_they_can_be_put_back(backend, state_dir):
    result = cap.capture_restore_point(
        [key("color-scheme")], backend, label="x", enabled_extensions=["a@x", "b@x"]
    )
    assert result.preset.extensions.enable == ["a@x", "b@x"]


@mutating
def test_restore_points_are_capped_oldest_first(backend, state_dir: Path):
    for minute in range(13):
        cap.capture_restore_point(
            [key("color-scheme")],
            backend,
            label="x",
            cap=10,
            now=datetime(2026, 8, 25, 12, minute, 0),
        )
    kept = cap.list_restore_points()
    assert len(kept) == 10
    assert kept[0].name.endswith("-121200")  # newest first
    assert kept[-1].name.endswith("-120300")


@mutating
def test_pruning_reports_what_it_removed(backend, state_dir: Path):
    for minute in range(3):
        cap.capture_restore_point(
            [key("color-scheme")],
            backend,
            label="x",
            cap=0,
            now=datetime(2026, 8, 25, 12, minute, 0),
        )
    removed = cap.prune_restore_points(cap=1)
    assert len(removed) == 2
    assert len(cap.list_restore_points()) == 1


@mutating
def test_listing_an_empty_state_folder_is_not_an_error(state_dir: Path):
    assert cap.list_restore_points() == []


# ── sharing ──────────────────────────────────────────────────────────────


@mutating
def test_a_value_that_looks_like_a_secret_is_left_out(backend, tmp_path):
    backend.set(key("api-token"), "'hunter2'")
    result = cap.capture_share(
        [key("api-token"), key("icon-theme")],
        backend,
        out_dir=tmp_path / "look",
        name="mine",
        title="Mine",
    )
    values = [s.value for s in result.preset.settings]
    assert "'hunter2'" not in values
    assert any("may contain something private" in w for w in result.warnings)


@mutating
def test_a_path_into_this_home_folder_is_made_general(backend, tmp_path):
    backend.set(key("picture-uri"), "'file:///home/somebody/Pictures/w.png'")
    result = cap.capture_share(
        [key("picture-uri")], backend, out_dir=tmp_path / "look", name="mine", title="Mine"
    )
    assert result.preset.settings[0].value == "'file://{{ home }}/Pictures/w.png'"
    assert any("works on other computers" in w for w in result.warnings)


@mutating
def test_a_shared_look_is_valid_and_loadable(backend, tmp_path):
    from gtheme.preset.loader import load

    backend.set(key("icon-theme"), "'Papirus-Dark'")
    out = tmp_path / "look"
    cap.capture_share(
        [key("icon-theme")], backend, out_dir=out, name="mine", title="Mine", author="me"
    )
    result = load(out)
    assert result.preset is not None
    assert result.preset.meta.name == "mine"
    assert result.errors == []


@mutating
def test_a_shared_look_with_no_picture_asks_for_one(backend, tmp_path):
    result = cap.capture_share(
        [key("icon-theme")], backend, out_dir=tmp_path / "look", name="mine", title="Mine"
    )
    assert any("add a screenshot" in w for w in result.warnings)


@pytest.mark.parametrize(
    "name", ["password", "api_key", "auth-thing", "session-id", "some-secret"]
)
def test_the_secret_scanner_is_deliberately_broad(name):
    assert cap._looks_secret(f"gsettings:a.b {name}", "'x'")


def test_an_ordinary_setting_is_not_mistaken_for_a_secret():
    assert not cap._looks_secret("gsettings:org.gnome.desktop.interface icon-theme", "'Adwaita'")
