"""Shared fixtures, and the guard that keeps the test suite off the real desktop.

THE CONTRACT IS FROZEN. The rule this file enforces is the reason it is safe to
run this suite on the machine that also runs the desktop being customised:

    a test marked ``mutating`` does not run unless an isolation seam is active.

An isolation seam is one of:

* ``GTHEME_DEST_ROOT`` pointing somewhere that is not the real home — every
  file write is confined below it,
* the ``memory_settings`` fixture in use — settings go to an in-memory GSettings
  backend and reach no store,
* ``GTHEME_CONFIG_DIR`` pointing at a temporary directory — app preferences,
* one of the ``tests/sandbox/`` session fixtures — the whole test runs inside a
  private D-Bus session with its own XDG roots, and the live canary asserts
  afterwards that the real desktop did not move.

The guard skips rather than fails, so that a suite run without seams is quiet
rather than red; but the skip reason names the missing seam, so a test that was
*meant* to have one cannot be mistaken for a test that passed.

TWO LAYERS BELOW THAT GUARD, ADDED AFTER A REAL LEAK. Wave 2 shipped three
tests that handed a page ``root=tmp_path`` and believed that was the whole
seam. It was half of one: the page read saved moments from the temporary
directory, but the transaction the page then ran took its *automatic* restore
point through :func:`gtheme.core.paths.restore_points_dir`, which reads the
environment and not the page's argument. Seven junk restore points recording
the real desktop appeared in ``~/.local/state/gtheme/v2`` during a plain suite
run. So:

* :func:`_quarantine_state_dir` gives **every** test its own throwaway v2 state
  root, whether it asked for one or not. A test that wants a specific one still
  requests the ``state_dir`` fixture and wins; a test that deliberately probes
  the default still ``delenv``\\ s the variable and wins.
* :func:`_live_state_dir_unchanged` photographs the real
  ``~/.local/state/gtheme/v2`` before the first test and again after the last
  one, and fails the run — loudly, by name — if a single byte moved.

Because the quarantine sets ``GTHEME_STATE_DIR`` for everything, that variable
on its own can no longer *prove* a test is isolated. :func:`_active_seams`
therefore ignores the value the quarantine parked there and counts only a value
some test chose for itself. The ``mutating`` guard is exactly as strict as it
was before.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

#: Environment variables that, when set to a temporary location, isolate a
#: test from the live desktop.
SEAM_ENV_VARS = (
    "GTHEME_DEST_ROOT",
    "GTHEME_CONFIG_DIR",
    "GTHEME_STATE_DIR",
    # The add-on library writes here: its download cache, and the staging area
    # where an update waits for the next login. Both point into the real
    # ~/.local/share by default, so redirecting them is a genuine seam.
    "GTHEME_CACHE_DIR",
    "GTHEME_EXTENSION_UPDATES_DIR",
)

#: Fixtures that provide isolation. Requesting any of them is enough.
#:
#: These are checked by NAME rather than by their effect, because the autouse
#: guard below can run before the fixture that sets the environment variable
#: does — pytest does not promise an order between two same-scope fixtures.
#: Checking only the environment made every ``config_dir``-seamed test skip
#: while looking, from the summary line, exactly like a test that had passed.
#: The last three belong to ``tests/sandbox/`` and isolate differently: rather
#: than redirecting a path, they put the whole test inside a private D-Bus
#: session with its own XDG roots and a headless shell, with the live canary
#: asserting afterwards that the real desktop did not move. That is a stronger
#: seam than any of the first four, not a weaker one, so a sandbox test may say
#: ``mutating`` out loud instead of having to stay quiet about what it does.
SEAM_FIXTURES = (
    "tmp_dest_root",
    "config_dir",
    "state_dir",
    "memory_settings",
    "sandbox_shared_data",
    "sandbox_private_data",
    "broadway_session",
    # Two sandbox modules build their own private session rather than sharing
    # one, because installing a test schema and running the runtime-load
    # experiment both have to happen before a shell starts. Same seam, same
    # canary, different owner.
    "golden_session",
    "experiment",
)

#: Set by the ``memory_settings`` fixture for the duration of a test.
_MEMORY_BACKEND_ACTIVE = "_gtheme_memory_backend_active"

#: Where :func:`_quarantine_state_dir` parked this test's throwaway v2 state
#: root. Recorded on the node so :func:`_active_seams` can tell "the harness
#: put a safety net under you" apart from "you asked for isolation".
_AUTO_STATE_DIR = "_gtheme_auto_state_dir"


def _active_seams(request: pytest.FixtureRequest) -> list[str]:
    """Which isolation seams are in effect for this test.

    ``GTHEME_STATE_DIR`` counts only when the test chose the value. Every test
    gets a quarantined state root from :func:`_quarantine_state_dir`, and a
    safety net nobody asked for is not evidence that a test is isolated.
    """
    auto_state_dir = getattr(request.node, _AUTO_STATE_DIR, None)
    seams = [
        name
        for name in SEAM_ENV_VARS
        if os.environ.get(name)
        and not (name == "GTHEME_STATE_DIR" and os.environ[name] == auto_state_dir)
    ]
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


def live_state_dir() -> Path:
    """The real v2 state root this machine's gtheme uses.

    Deliberately *not* :func:`gtheme.core.paths.state_dir`: that function reads
    ``GTHEME_STATE_DIR``, which the quarantine below always sets, so asking it
    would only ever photograph the throwaway directory.
    """
    base = os.environ.get("XDG_STATE_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".local" / "state"
    return root / "gtheme" / "v2"


def _fingerprint(root: Path) -> dict[str, str]:
    """Path to content hash for every file under ``root``. Empty if absent."""
    if not root.exists():
        return {}
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        rel = str(path.relative_to(root))
        if path.is_dir():
            out[rel + "/"] = "dir"
        else:
            try:
                out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as exc:  # pragma: no cover - unreadable is a change
                out[rel] = f"unreadable: {exc}"
    return out


@pytest.fixture(scope="session", autouse=True)
def _live_state_dir_unchanged() -> Iterator[None]:
    """Fail the whole run if the suite moved the real v2 state directory.

    The ``mutating`` guard protects the desktop's *settings*; this protects
    gtheme's own record of them — the restore points a person's undo depends
    on. A test that writes here has escaped its seam even if every assertion
    passed, so this is an error, not a warning.
    """
    root = live_state_dir()
    before = _fingerprint(root)
    yield
    after = _fingerprint(root)
    if before == after:
        return
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(k for k in set(before) & set(after) if before[k] != after[k])
    raise AssertionError(
        f"the test suite changed the REAL state directory {root}.\n"
        f"  added:   {added}\n"
        f"  removed: {removed}\n"
        f"  changed: {changed}\n"
        "Some test reached past its seam: a page's root= argument does not "
        "reach the transaction machinery, which resolves GTHEME_STATE_DIR."
    )


@pytest.fixture(autouse=True)
def _quarantine_state_dir(
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Point ``GTHEME_STATE_DIR`` at a throwaway directory for every test.

    Declared before :func:`_mutating_guard` so the node attribute exists by the
    time the guard reads it, and before the ``state_dir`` fixture — which is
    not autouse and therefore runs later, so a test that asks for a specific
    state root still gets exactly that one.
    """
    path = tmp_path_factory.mktemp("auto-state")
    monkeypatch.setenv("GTHEME_STATE_DIR", str(path))
    setattr(request.node, _AUTO_STATE_DIR, str(path))


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
