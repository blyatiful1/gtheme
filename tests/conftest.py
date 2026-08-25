"""Shared fixtures, and the guard that keeps the test suite off the real desktop.

THE CONTRACT IS FROZEN. The rule this file enforces is the reason it is safe to
run this suite on the machine that also runs the desktop being customised:

    a test marked ``mutating`` does not run unless an isolation seam is active.

An isolation seam is one of:

* ``GTHEME_DEST_ROOT`` pointing somewhere that is not the real home — every
  file write is confined below it,
* the ``memory_settings`` fixture in use — settings go to an in-memory GSettings
  backend and reach no store,
* ``GTHEME_CONFIG_DIR`` pointing at a temporary directory — app preferences.

The guard skips rather than fails, so that a suite run without seams is quiet
rather than red; but the skip reason names the missing seam, so a test that was
*meant* to have one cannot be mistaken for a test that passed.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

#: Environment variables that, when set to a temporary location, isolate a
#: test from the live desktop.
SEAM_ENV_VARS = ("GTHEME_DEST_ROOT", "GTHEME_CONFIG_DIR", "GTHEME_STATE_DIR")

#: Fixtures that provide isolation. Requesting any of them is enough.
#:
#: These are checked by NAME rather than by their effect, because the autouse
#: guard below can run before the fixture that sets the environment variable
#: does — pytest does not promise an order between two same-scope fixtures.
#: Checking only the environment made every ``config_dir``-seamed test skip
#: while looking, from the summary line, exactly like a test that had passed.
SEAM_FIXTURES = ("tmp_dest_root", "config_dir", "state_dir", "memory_settings")

#: Set by the ``memory_settings`` fixture for the duration of a test.
_MEMORY_BACKEND_ACTIVE = "_gtheme_memory_backend_active"


def _active_seams(request: pytest.FixtureRequest) -> list[str]:
    """Which isolation seams are in effect for this test."""
    seams = [name for name in SEAM_ENV_VARS if os.environ.get(name)]
    if getattr(request.node, _MEMORY_BACKEND_ACTIVE, False):
        seams.append("memory_settings")
    seams.extend(name for name in SEAM_FIXTURES if name in request.fixturenames)
    return sorted(set(seams))


def enforce_isolation(request: pytest.FixtureRequest) -> None:
    """Skip this test if it is ``mutating`` and nothing isolates it.

    Kept as a plain function so it can be called directly with a stand-in
    request object — the guard is the most safety-critical code in the suite
    and has to be testable without spawning a nested pytest.
    """
    if request.node.get_closest_marker("mutating") is None:
        return
    if _active_seams(request):
        return
    pytest.skip(
        "refusing to run a 'mutating' test with no isolation seam — request the "
        "tmp_dest_root or memory_settings fixture, or set one of "
        + ", ".join(SEAM_ENV_VARS)
    )


@pytest.fixture(autouse=True)
def _mutating_guard(request: pytest.FixtureRequest) -> None:
    """Runs for every test in the suite. See :func:`enforce_isolation`."""
    enforce_isolation(request)


@pytest.fixture
def tmp_dest_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A throwaway destination root. Sets ``GTHEME_DEST_ROOT``.

    Every file a transaction writes must resolve inside this directory; the
    confinement preflight is what makes that true, and pointing the root at a
    tmpdir is what makes testing it safe.
    """
    root = tmp_path / "dest-root"
    root.mkdir()
    monkeypatch.setenv("GTHEME_DEST_ROOT", str(root))
    yield root


@pytest.fixture
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A throwaway app-preferences directory. Sets ``GTHEME_CONFIG_DIR``."""
    path = tmp_path / "config"
    path.mkdir()
    monkeypatch.setenv("GTHEME_CONFIG_DIR", str(path))
    yield path


@pytest.fixture
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A throwaway runtime-state directory. Sets ``GTHEME_STATE_DIR``.

    v2 state lives under ``~/.local/state/gtheme/v2``; v1's files in the parent
    directory are never read for writing and never deleted (DESIGN.md F1).
    """
    path = tmp_path / "state"
    path.mkdir()
    monkeypatch.setenv("GTHEME_STATE_DIR", str(path))
    yield path


@pytest.fixture
def memory_settings(request: pytest.FixtureRequest):
    """A working :class:`MemoryBackend`. Settings go nowhere real.

    Skips when PyGObject is not importable, which is the only environment where
    this fixture cannot be honoured.
    """
    pytest.importorskip("gi", reason="PyGObject is needed for the settings backend")
    from gtheme.core.settings_backend import MemoryBackend

    setattr(request.node, _MEMORY_BACKEND_ACTIVE, True)
    return MemoryBackend()


@pytest.fixture
def schema_source_factory(tmp_path: Path):
    """Compile a throwaway GSettings schema and return a source for it.

    Extension schemas do not live in the system store, so the app has to build
    a schema source per extension directory anyway; this fixture exercises that
    same path with a schema written for the test, which keeps the settings
    tests independent of what happens to be installed on the machine.

    Returns a callable ``(xml_text, schema_id) -> Gio.SettingsSchemaSource``.
    """
    pytest.importorskip("gi", reason="PyGObject is needed for the settings backend")
    import shutil
    import subprocess

    from gi.repository import Gio

    if shutil.which("glib-compile-schemas") is None:
        pytest.skip("glib-compile-schemas is not installed")

    counter = {"n": 0}

    def make(xml_text: str) -> Gio.SettingsSchemaSource:
        counter["n"] += 1
        directory = tmp_path / f"schemas-{counter['n']}"
        directory.mkdir()
        (directory / "test.gschema.xml").write_text(xml_text, encoding="utf-8")
        result = subprocess.run(
            ["glib-compile-schemas", str(directory)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError(f"glib-compile-schemas failed: {result.stderr}")
        return Gio.SettingsSchemaSource.new_from_directory(
            str(directory), Gio.SettingsSchemaSource.get_default(), False
        )

    return make


@pytest.fixture
def repo_root() -> Path:
    """The repository root, for tests that read committed data files."""
    return Path(__file__).resolve().parents[1]
