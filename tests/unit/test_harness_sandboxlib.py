"""The sandbox harness's pure logic, tested where it always runs.

Same argument as ``test_harness_canary.py``: the sandbox tier is local-only, so
the parts of it that can be checked without a shell are checked here instead.

The environment builder gets the most attention, because every mistake it could
make is one that has already been made once. Dropping the system entries from
``XDG_DATA_DIRS`` leaves the shell with no icons and no stylesheet. Leaving
``DISPLAY`` set lets a sandbox client connect to the real session. Letting a
``GTHEME_*`` seam variable through redirects writes somewhere the canary is not
looking.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest

SANDBOX_DIR = Path(__file__).resolve().parents[1] / "sandbox"


def _load(name: str) -> ModuleType:
    path = SANDBOX_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"gtheme_sandbox_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sandboxlib = _load("sandboxlib")


def _env(tmp_path: Path, mode=None, **kwargs) -> dict[str, str]:
    return sandboxlib.sandbox_env(
        root=tmp_path,
        mode=mode or sandboxlib.DataMode.SHARED,
        bus="unix:path=/tmp/private",
        wayland_display="gtheme-test",
        **kwargs,
    )


def test_shared_mode_reroots_settings_but_not_data(tmp_path: Path):
    env = _env(tmp_path)
    assert env["XDG_CONFIG_HOME"] == str(tmp_path / "config")
    assert env["XDG_CACHE_HOME"] == str(tmp_path / "cache")
    assert env["XDG_STATE_HOME"] == str(tmp_path / "state")
    assert env.get("XDG_DATA_HOME") == os.environ.get("XDG_DATA_HOME")


def test_private_mode_reroots_the_data_home_too(tmp_path: Path):
    env = _env(tmp_path, mode=sandboxlib.DataMode.PRIVATE)
    assert env["XDG_DATA_HOME"] == str(tmp_path / "data")


def test_the_system_data_dirs_are_kept(tmp_path: Path):
    """Drop them and the shell comes up with no icons and no stylesheet."""
    env = _env(tmp_path)
    entries = env["XDG_DATA_DIRS"].split(os.pathsep)
    assert str(sandboxlib.EXT_ROOT) in entries
    # The session's own value may carry trailing slashes ("/usr/share/") and
    # flatpak exports; what matters is that the system prefix is still there.
    system = [i for i, entry in enumerate(entries) if entry.rstrip("/") == "/usr/share"]
    assert system, entries
    # ext-root must come before the system dirs, or a same-named directory in
    # /usr/share would win.
    assert entries.index(str(sandboxlib.EXT_ROOT)) < system[0]


def test_a_per_session_schema_root_comes_first(tmp_path: Path):
    """So a test can compile a gschema the machine does not have installed."""
    entries = _env(tmp_path)["XDG_DATA_DIRS"].split(os.pathsep)
    assert entries[0] == str(tmp_path / "share")


def test_the_live_display_is_removed(tmp_path: Path):
    """A sandbox client with DISPLAY set can reach the real X session."""
    env = _env(tmp_path)
    assert "DISPLAY" not in env
    assert env["WAYLAND_DISPLAY"] == "gtheme-test"


def test_the_private_bus_address_is_used(tmp_path: Path):
    env = _env(tmp_path)
    assert env["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/tmp/private"


def test_test_suite_seams_do_not_leak_into_the_sandbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A seam variable inherited from the test process would redirect writes.

    They would go somewhere real but unwatched, which is worse than going
    nowhere: the canary would report the desktop untouched and be right.
    """
    monkeypatch.setenv("GTHEME_DEST_ROOT", "/somewhere/real")
    monkeypatch.setenv("GTHEME_CONFIG_DIR", "/somewhere/real")
    monkeypatch.setenv("GTHEME_STATE_DIR", "/somewhere/real")
    env = _env(tmp_path)
    assert "GTHEME_DEST_ROOT" not in env
    assert "GTHEME_CONFIG_DIR" not in env
    assert "GTHEME_STATE_DIR" not in env


def test_extra_values_win(tmp_path: Path):
    env = _env(tmp_path, extra={"GDK_BACKEND": "broadway"})
    assert env["GDK_BACKEND"] == "broadway"


def test_the_output_locale_is_pinned(tmp_path: Path):
    """Values are compared as bytes; they must not move under a locale."""
    assert _env(tmp_path)["LC_ALL"] == "C"


def test_wayland_display_names_are_unique():
    """Two shells sharing XDG_RUNTIME_DIR cannot share a socket name."""
    names = {sandboxlib.unique_wayland_display() for _ in range(50)}
    assert len(names) == 50
    assert all(name.startswith("gtheme-sb-") for name in names)


def test_the_window_list_parser_handles_a_gdbus_reply():
    """``gdbus call`` wraps the extension's JSON in a tuple and escapes it."""
    payload = json.dumps(
        [{"id": 42, "wm_class": "io.github.blyatiful1.Gtheme", "title": "Gtheme"}]
    )
    reply = "('" + payload.replace("'", "\\'") + "',)\n"
    windows = sandboxlib._parse_window_list(reply)
    assert windows == [
        {"id": 42, "wm_class": "io.github.blyatiful1.Gtheme", "title": "Gtheme"}
    ]


def test_the_window_list_parser_survives_rubbish():
    for text in ("", "()", "Error: GDBus.Error:...NoReply", "('not json',)"):
        assert sandboxlib._parse_window_list(text) == []


def test_the_frame_rect_parser_reads_a_zero_rect():
    """0x0 right after map is the normal answer, not a parse failure."""
    reply = "('{\"x\":0,\"y\":0,\"width\":0,\"height\":0}',)"
    assert sandboxlib._parse_gdbus_json(reply) == {
        "x": 0, "y": 0, "width": 0, "height": 0
    }


def test_a_probe_extension_is_loadable_shaped(tmp_path: Path):
    directory = sandboxlib.make_probe_extension(tmp_path / "p", "p@gtheme.local", "P")
    metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["uuid"] == "p@gtheme.local"
    assert "50" in metadata["shell-version"]
    source = (directory / "extension.js").read_text(encoding="utf-8")
    assert "PROBE_P_ENABLE_MARKER" in source
    assert "export default class" in source


def test_an_extension_zip_is_flat(tmp_path: Path):
    """e.g.o serves flat zips; ``gnome-extensions install`` expects that shape."""
    import zipfile

    source = sandboxlib.make_probe_extension(tmp_path / "p", "p@gtheme.local", "P")
    archive = sandboxlib.zip_extension(source, tmp_path / "p.zip")
    with zipfile.ZipFile(archive) as zf:
        names = sorted(zf.namelist())
    assert names == ["extension.js", "metadata.json"]


def test_the_sandbox_extension_ships_with_its_warning():
    """The never-install README is part of the deliverable, not decoration."""
    ext = sandboxlib.EXT_ROOT / "gnome-shell/extensions" / sandboxlib.SANDBOX_EXT_UUID
    assert (ext / "metadata.json").is_file()
    assert (ext / "extension.js").is_file()
    warning = (ext / "DO-NOT-INSTALL.md").read_text(encoding="utf-8")
    assert "DO NOT INSTALL" in warning
    assert "unsafe_mode" in warning
    root_readme = (sandboxlib.EXT_ROOT / "README.md").read_text(encoding="utf-8")
    assert "NEVER BE COPIED INTO A REAL SESSION" in root_readme


def test_the_sandbox_extension_turns_unsafe_mode_off_again():
    """It is the only thing standing between a crashed test and a hot shell."""
    ext = sandboxlib.EXT_ROOT / "gnome-shell/extensions" / sandboxlib.SANDBOX_EXT_UUID
    source = (ext / "extension.js").read_text(encoding="utf-8")
    assert "global.context.unsafe_mode = true" in source
    assert "global.context.unsafe_mode = false" in source
