"""Reading the desktop back out — restore points and shareable Looks.

Everything here runs against the in-memory settings backend with a throwaway
schema compiled for the test, so it exercises the real GVariant machinery and
touches nothing on the machine running it.
"""

from __future__ import annotations

import os
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
  <schema id="org.gnome.desktop.background" path="/org/gtheme/test/background/">
    <key name="picture-uri" type="s"><default>''</default></key>
    <key name="picture-uri-dark" type="s"><default>''</default></key>
  </schema>
</schemalist>
"""


@pytest.fixture
def backend(memory_settings, schema_source_factory, tmp_dest_root):
    """The in-memory backend, and a throwaway home folder to go with it.

    ``tmp_dest_root`` is not decoration here. ``capture_share`` reads a palette
    back from the terminal when no Look is applied, and the terminal adapters
    resolve their configuration through ``terminal.fsio.config_root()``, which
    is the *real* ``~/.config`` unless ``GTHEME_DEST_ROOT`` says otherwise. Nine
    tests in this file call ``capture_share``; without the root they read the
    developer's own ghostty colours and their result depends on the machine —
    the one property ``tests/conftest.py`` exists to guarantee.
    """
    del tmp_dest_root  # requested for its environment, not its value
    memory_settings.schema_source = schema_source_factory(SCHEMA_XML)
    return memory_settings


def key(name: str) -> str:
    return f"gsettings:{SCHEMA_ID} {name}"


def bg_key(name: str) -> str:
    """A real wallpaper key. The bundling in capture_share matches on these."""
    return f"gsettings:org.gnome.desktop.background {name}"


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


# ── where things live, and finding the wallpaper ─────────────────────────
#
# CONTRACT CHANGED BY RULING (Wave-2 gate, R5): one store, one format, one
# reader. This module used to write saved moments in its own format (a
# theme.toml in a YYYYmmdd-HHMMSS folder) into the same directory
# core.restorepoints writes its own (a restore-point.json in a
# YYYY-mm-ddTHH-MM-SS one), with its own lister and its own pruner.
#
# CONTRACT CHANGED AGAIN (review finding capture.py:195): the wrapper left
# behind, capture_restore_point, had no caller anywhere in the app — every real
# path goes through restore.create_restore_point -> restorepoints.capture. It
# and its tests are gone rather than left standing as a feature that never ran;
# the store's own behaviour is tested in tests/unit/test_restorepoints.py.


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
def test_a_save_here_reads_nothing_off_the_machine_running_the_suite(backend, tmp_path):
    """The ``backend`` fixture's second half, pinned.

    ``capture_share`` falls back to the colours a terminal on this computer is
    wearing, and the terminal adapters resolve their configuration through
    ``terminal.fsio.config_root()`` — the developer's real ``~/.config`` unless
    ``GTHEME_DEST_ROOT`` says otherwise. Nine tests in this file call
    ``capture_share``; without that root they read whatever ghostty config the
    machine happens to have, and their result depends on who ran them.
    """
    from gtheme.terminal import fsio

    root = Path(os.environ["GTHEME_DEST_ROOT"])
    assert fsio.config_root().is_relative_to(root)

    result = cap.capture_share(
        [key("icon-theme")], backend, out_dir=tmp_path / "look", name="mine", title="Mine"
    )
    assert result.preset.palette == {}
    assert [o.kind for o in result.omissions if o.kind == "palette"] == ["palette"]


@mutating
def test_a_shared_look_with_no_picture_asks_for_one(backend, tmp_path):
    result = cap.capture_share(
        [key("icon-theme")], backend, out_dir=tmp_path / "look", name="mine", title="Mine"
    )
    assert any("add a screenshot" in w for w in result.warnings)


#: Refused by ``core.policy`` — gtheme describes this setting on its own page,
#: so it is in the corpus every save reads, and every save leaves it out.
TERMINAL_EXEC = "gsettings:org.gnome.desktop.default-applications.terminal exec"
TERMINAL_EXEC_ARG = "gsettings:org.gnome.desktop.default-applications.terminal exec-arg"


@mutating
def test_the_notes_after_a_save_say_each_thing_once_and_in_words(backend, tmp_path):
    """The dialog after "save my desktop" is read by a person, not a programmer.

    It said the same omission twice — once as "one setting was left out …
    (gsettings:org.gnome.desktop.lockdown disable-show-password)" and once as
    "gsettings:org.gnome.desktop.lockdown disable-show-password: it may contain
    something private…" — and it showed a raw schema path to everybody who ever
    saved a desktop, because one refused setting is left out of every single
    save. The keys stay in ``omissions`` for a dialog that wants to lay them
    out; the sentences say what happened.
    """
    backend.set(key("api-token"), "'hunter2'")
    result = cap.capture_share(
        [key("api-token"), key("icon-theme"), TERMINAL_EXEC],
        backend,
        out_dir=tmp_path / "look",
        name="mine",
        title="Mine",
    )

    assert [w for w in result.warnings if "something private" in w] == [
        "one setting was left out because it may contain something private, like a password"
    ]
    assert [w for w in result.warnings if "not allowed to change" in w] == [
        "one setting was left out because a Look is not allowed to change it"
    ]
    assert len(set(result.warnings)) == len(result.warnings), result.warnings
    assert not [w for w in result.warnings if "gsettings:" in w or "org.gnome" in w]
    assert {o.what for o in result.omissions if o.kind == "setting"} == {
        key("api-token"),
        TERMINAL_EXEC,
    }


def test_the_lines_a_save_shows_are_words_the_app_is_allowed_to_say():
    """The jargon lint reaches ``gtheme.ui``; these sentences are written here.

    That is how ``gsettings:org.gnome.…`` ended up in a dialog with nothing red
    anywhere. The generated half of the copy gets the same lint as the written
    half.
    """
    from gtheme.ui import jargon

    for _reason, one, many in cap._SETTING_NOTES:
        assert jargon.find_banned(one) == [], one
        assert jargon.find_banned(many) == [], many


@mutating
def test_settings_left_out_for_the_same_reason_are_counted_together(backend, tmp_path):
    result = cap.capture_share(
        [TERMINAL_EXEC, TERMINAL_EXEC_ARG],
        backend,
        out_dir=tmp_path / "look",
        name="mine",
        title="Mine",
    )
    assert [w for w in result.warnings if "not allowed to change" in w] == [
        "2 settings were left out because a Look is not allowed to change them"
    ]


@pytest.mark.parametrize(
    "name", ["password", "api_key", "auth-thing", "session-id", "some-secret"]
)
def test_the_secret_scanner_is_deliberately_broad(name):
    assert cap._looks_secret(f"gsettings:a.b {name}", "'x'")


def test_an_ordinary_setting_is_not_mistaken_for_a_secret():
    assert not cap._looks_secret("gsettings:org.gnome.desktop.interface icon-theme", "'Adwaita'")


# ── the wallpaper travels with the Look ──────────────────────────────────


@mutating
def test_a_shared_look_bundles_the_wallpaper_it_points_at(backend, tmp_path):
    """Pins review finding preset/capture.py:297 (v1 regression).

    capture_share used to copy the wallpaper in only as a preview picture and
    ship the captured picture-uri with the original path merely genericised —
    'file://{{ home }}/Pictures/w.png' — which resolves, on the machine the
    Look is given to, to a file that was never there. The Look's most visible
    part silently did nothing. v1 bundled the image and rewrote the URI to the
    bundled destination; so does this again.
    """
    picture = tmp_path / "Pictures" / "w.png"
    picture.parent.mkdir(parents=True)
    picture.write_bytes(b"pretend png")
    backend.set(bg_key("picture-uri"), f"'file://{picture}'")

    out = tmp_path / "look"
    result = cap.capture_share(
        [bg_key("picture-uri")], backend, out_dir=out, name="mine", title="Mine"
    )

    bundled = result.preset.files
    assert [(f.src, f.dest) for f in bundled] == [
        ("files/w.png", "~/.local/share/backgrounds/mine/w.png")
    ]
    assert (out / "files" / "w.png").read_bytes() == b"pretend png"
    assert result.preset.settings[0].value == (
        "'file://{{ home }}/.local/share/backgrounds/mine/w.png'"
    )
    assert any("copied into this Look" in w for w in result.warnings)


@mutating
def test_the_bundled_wallpaper_is_also_the_looks_picture(backend, tmp_path):
    """One copy, not two: the shipped image is what the grid shows."""
    picture = tmp_path / "w.png"
    picture.write_bytes(b"pretend png")
    backend.set(bg_key("picture-uri"), f"'file://{picture}'")

    out = tmp_path / "look"
    result = cap.capture_share(
        [bg_key("picture-uri")], backend, out_dir=out, name="mine", title="Mine"
    )
    assert result.preset.meta.screenshots == ["files/w.png"]
    assert not (out / "picture.png").exists()


@mutating
def test_a_light_and_dark_wallpaper_are_both_bundled(backend, tmp_path):
    """Pins preset/capture.py:297 for the dark key, which shares the code."""
    light = tmp_path / "day.png"
    dark = tmp_path / "night.png"
    light.write_bytes(b"day")
    dark.write_bytes(b"night")
    backend.set(bg_key("picture-uri"), f"'file://{light}'")
    backend.set(bg_key("picture-uri-dark"), f"'file://{dark}'")

    out = tmp_path / "look"
    result = cap.capture_share(
        [bg_key("picture-uri"), bg_key("picture-uri-dark")],
        backend,
        out_dir=out,
        name="mine",
        title="Mine",
    )
    assert sorted(f.src for f in result.preset.files) == ["files/day.png", "files/night.png"]
    assert sorted(s.value for s in result.preset.settings) == [
        "'file://{{ home }}/.local/share/backgrounds/mine/day.png'",
        "'file://{{ home }}/.local/share/backgrounds/mine/night.png'",
    ]


@mutating
def test_a_shared_look_that_bundles_its_wallpaper_still_loads(backend, tmp_path):
    """The bundled file entry and picture have to survive the loader's checks."""
    from gtheme.preset.loader import load

    picture = tmp_path / "w.png"
    picture.write_bytes(b"pretend png")
    backend.set(bg_key("picture-uri"), f"'file://{picture}'")

    out = tmp_path / "mine"  # the folder is the Look's name, as the app writes it
    cap.capture_share([bg_key("picture-uri")], backend, out_dir=out, name="mine", title="Mine")
    result = load(out)
    assert result.errors == []
    assert result.warnings == []


def test_capture_exposes_nothing_the_app_never_calls():
    """Pins review finding preset/capture.py:195.

    capture_restore_point sat in __all__ describing a "Look view of a saved
    moment" that no page ever asked for — every real path goes through
    restore.create_restore_point -> restorepoints.capture. Dead code that
    documents a feature is worse than no code, so this walks the package and
    fails if a public name here is referenced nowhere but its own module.
    """
    import ast

    import gtheme

    source_root = Path(gtheme.__file__).resolve().parent

    # Only real uses count. A name in __all__ is an ast.Constant string and a
    # definition is a FunctionDef, so neither makes a function look used — the
    # claim is exactly what is being checked.
    used: set[str] = set()
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                used.add(node.id)
            elif isinstance(node, ast.Attribute):
                used.add(node.attr)
            elif isinstance(node, ast.alias):
                used.add(node.name.rsplit(".", 1)[-1])

    assert not hasattr(cap, "capture_restore_point")
    assert [name for name in cap.__all__ if name not in used] == []
