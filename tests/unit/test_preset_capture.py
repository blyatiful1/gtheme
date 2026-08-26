"""Reading the desktop back out — restore points and shareable Looks.

Everything here runs against the in-memory settings backend with a throwaway
schema compiled for the test, so it exercises the real GVariant machinery and
touches nothing on the machine running it.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from gtheme.core import paths, restorepoints
from gtheme.preset import capture as cap
from gtheme.preset.model import Component

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


# ── saved moments ────────────────────────────────────────────────────────
#
# CONTRACT CHANGED BY RULING (Wave-2 gate, R5): one store, one format, one
# reader. This module used to write saved moments in its own format (a
# theme.toml in a YYYYmmdd-HHMMSS folder) into the same directory
# core.restorepoints writes its own (a restore-point.json in a
# YYYY-mm-ddTHH-MM-SS one), with its own lister and its own pruner. The pruner
# was the dangerous half: it deleted the oldest folders by name whatever they
# were, where the engine's refuses to touch a moment somebody asked for by hand
# or the "Before gtheme" one that cannot be recreated. So these tests moved
# from "capture keeps its own store correctly" to "capture writes into the one
# store".


@mutating
def test_a_moment_captured_here_is_one_the_engine_can_find(backend, state_dir: Path):
    """The unification, stated as the one thing that has to be true."""
    backend.set(key("color-scheme"), "'prefer-dark'")
    result = cap.capture_restore_point([key("color-scheme")], backend, label="My desktop")

    found = restorepoints.list_restore_points()
    assert len(found) == 1
    assert found[0].label == "My desktop"
    assert found[0].path == result.path
    assert found[0].settings[key("color-scheme")] == "'prefer-dark'"


@mutating
def test_a_moment_captured_by_the_engine_appears_in_the_same_list(backend, state_dir: Path):
    """The other direction. One list means both paths are on it.

    The two moments are given different times, which is what a reader of this
    list expects to see. They no longer *have* to be: the same-second collision
    this test used to document — where the second moment landed in the first
    one's folder and overwrote it — is closed in ``core.restorepoints._new_id``
    and pinned by its own test over there, where it belongs.
    """
    backend.set(key("color-scheme"), "'default'")
    cap.capture_restore_point(
        [key("color-scheme")], backend, label="from the page",
        now=datetime(2026, 8, 25, 12, 0, 0),
    )
    restorepoints.capture(
        [key("color-scheme")], label="from the engine", backend=backend,
        when=datetime(2026, 8, 25, 12, 0, 1),
    )

    labels = {point.label for point in restorepoints.list_restore_points()}
    assert labels == {"from the page", "from the engine"}


@mutating
def test_a_captured_moment_is_still_described_as_a_look(backend, state_dir: Path):
    """The Look view is what the pages show; it is no longer a second store."""
    backend.set(key("color-scheme"), "'prefer-dark'")
    result = cap.capture_restore_point([key("color-scheme")], backend, label="My desktop")
    assert result.preset.format == 2
    assert result.preset.settings[0].value == "'prefer-dark'"
    assert result.path is not None
    assert not (result.path / "theme.toml").exists(), "the second format is gone"


@mutating
def test_a_moment_lands_under_the_v2_state_folder(backend, state_dir: Path):
    cap.capture_restore_point([key("color-scheme")], backend, label="x")
    assert paths.state_dir() == state_dir
    assert paths.restore_points_dir() == state_dir / "restore-points"
    assert len(restorepoints.list_restore_points()) == 1


def test_the_state_folder_never_touches_v1s(monkeypatch, tmp_path):
    monkeypatch.delenv("GTHEME_STATE_DIR", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert paths.state_dir() == tmp_path / "gtheme" / "v2"


def test_the_current_wallpaper_becomes_the_moments_picture(tmp_path):
    """A saved moment shows the desktop it would bring back."""
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
def test_a_moment_with_no_findable_wallpaper_says_so(backend, state_dir: Path):
    result = cap.capture_restore_point([key("color-scheme")], backend, label="x")
    assert any("no picture" in w for w in result.warnings)


@mutating
def test_owned_files_are_snapshotted_by_the_engine(backend, state_dir, tmp_path):
    """The copy is the engine's, in the engine's numbered-blob layout."""
    owned = tmp_path / "gnome-shell.css"
    owned.write_text("/* mine */", encoding="utf-8")
    dest = str(tmp_path / "gnome-shell.css")
    result = cap.capture_restore_point(
        [key("color-scheme")], backend, label="x", owned_files=[(owned, dest)]
    )
    point = restorepoints.list_restore_points()[0]
    assert point.files[dest] is not None
    assert (point.path / "files" / point.files[dest]).read_text() == "/* mine */"
    assert result.preset.files[0].dest == dest


@mutating
def test_enabled_add_ons_are_recorded_so_they_can_be_put_back(backend, state_dir):
    result = cap.capture_restore_point(
        [key("color-scheme")], backend, label="x", enabled_extensions=["a@x", "b@x"]
    )
    assert result.preset.extensions.enable == ["a@x", "b@x"]


@mutating
def test_pruning_is_the_engines_and_spares_what_somebody_asked_for(backend, state_dir: Path):
    """The reason there must be one pruner.

    This module's pruner deleted the oldest folders by name whatever they were.
    The engine's refuses to touch a moment a person asked for by hand, so a
    capture from this path defaults to "manual" and survives.
    """
    for minute in range(13):
        cap.capture_restore_point(
            [key("color-scheme")], backend, label="auto", kind="auto", cap=10,
            now=datetime(2026, 8, 25, 12, minute, 0),
        )
    kept = restorepoints.list_restore_points()
    assert len(kept) == 10
    assert kept[0].id.endswith("12-12-00"), kept[0].id  # newest first
    assert kept[-1].id.endswith("12-03-00"), kept[-1].id

    mine = cap.capture_restore_point([key("color-scheme")], backend, label="mine")
    restorepoints.prune(cap=0)
    survivors = [point.label for point in restorepoints.list_restore_points()]
    assert survivors == ["mine"], survivors
    assert mine.path.is_dir()


@mutating
def test_leaving_the_cap_alone_is_the_default(backend, state_dir: Path):
    """A capture taken on the user's behalf does not quietly shorten the list."""
    for minute in range(3):
        cap.capture_restore_point(
            [key("color-scheme")], backend, label="x", kind="auto",
            now=datetime(2026, 8, 25, 12, minute, 0),
        )
    assert len(restorepoints.list_restore_points()) == 3


@mutating
def test_listing_an_empty_state_folder_is_not_an_error(state_dir: Path):
    assert restorepoints.list_restore_points() == []


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
