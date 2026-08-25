"""Fixtures for the sandbox tier — and the canary wrapped around every one of them.

This tier is LOCAL ONLY. It boots a real ``gnome-shell --headless`` on a private
D-Bus session and drives it. It is excluded from a plain ``pytest`` run by
``addopts = -m "not sandbox"`` and never runs in CI; ``verify.sh --full`` opts
in explicitly.

Two data modes exist, per DESIGN.md F6, and choosing between them is a safety
decision, not a performance one:

``sandbox_shared_data``
    Config, cache and state are private; ``XDG_DATA_HOME`` is left alone, so the
    user's real extensions, themes and wallpapers are visible READ-ONLY. Use for
    rendering and page-walking, where seeing the real machine is the point.

``sandbox_private_data``
    ``XDG_DATA_HOME`` is private too, with ``window-calls`` copied in from the
    user's directory and the committed fixture corpus seeded alongside it. Use
    for anything that installs, enables, stages or uninstalls an extension —
    that is, anything that could write into the real extensions directory if it
    were wrong.

Both are session-scoped and lazily started, because a headless shell costs
several seconds to boot and the isolation guarantee does not weaken with reuse:
the canary runs per test either way.
"""

from __future__ import annotations

import os
import shutil
import time
from collections.abc import Iterator
from pathlib import Path

import canary
import pytest
import sandboxlib
from sandboxlib import DataMode, SandboxSession, SandboxUnavailable

from tests.conftest import SEAM_FIXTURES

#: The fixtures in this file that isolate a test from the live desktop. They are
#: also in ``tests/conftest.py``'s ``SEAM_FIXTURES``, so a test here may be
#: marked ``mutating`` and actually run. :func:`pytest_collection_modifyitems`
#: catches the case where a new sandbox fixture is added here and forgotten
#: there, which would silently downgrade such a test to a skip.
SANDBOX_SEAM_FIXTURES = ("sandbox_shared_data", "sandbox_private_data", "broadway_session")


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Refuse to let a sandbox test be quietly skipped by the mutating guard.

    ``tests/conftest.py`` skips a ``mutating`` test unless one of the names in
    its ``SEAM_FIXTURES`` is in play. The sandbox fixtures are on that list, so
    the ordinary case runs; but a sandbox module that builds its own session
    under a name nobody added there would report as an ordinary skip — the
    exact failure mode the guard's own tests were written about. Fail
    collection instead, with the fix in the message.
    """
    offenders = []
    for item in items:
        if Path(str(item.path)).parent != Path(__file__).parent:
            continue
        if item.get_closest_marker("mutating") is None:
            continue
        if set(item.fixturenames) & set(SEAM_FIXTURES):
            continue
        offenders.append(item.nodeid)
    if offenders:
        raise pytest.UsageError(
            "these sandbox tests are marked 'mutating' but none of "
            f"{SEAM_FIXTURES} is in play, so the guard in tests/conftest.py would "
            "SKIP them while the summary line called them passes:\n  "
            + "\n  ".join(offenders)
            + "\nEither drop the 'mutating' marker (the sandbox marker plus the "
            "live canary is the stronger guarantee here) or add the fixture "
            "that isolates them to SEAM_FIXTURES in tests/conftest.py, next to "
            f"{SANDBOX_SEAM_FIXTURES}."
        )


@pytest.fixture(autouse=True)
def live_canary(request: pytest.FixtureRequest) -> Iterator[canary.Snapshot]:
    """DESIGN.md F6: prove the live desktop is untouched, around EVERY test.

    Autouse, so no sandbox test can forget it, and so a test that leaks state is
    reported as a failure of itself rather than as a mysterious failure of
    whatever runs next.
    """
    before = canary.snapshot()
    yield before
    after = canary.snapshot()
    canary.assert_unchanged(before, after, context=request.node.name)


def _session(
    tmp_path_factory: pytest.TempPathFactory,
    *,
    mode: DataMode,
    seed_fixtures: bool,
) -> Iterator[SandboxSession]:
    try:
        sandboxlib.require_tools()
    except SandboxUnavailable as exc:
        pytest.skip(str(exc))
    root = tmp_path_factory.mktemp(f"sandbox-{mode.value}-")
    session = SandboxSession(
        root=root, mode=mode, seed_fixture_extensions=seed_fixtures
    )
    try:
        session.start()
    except SandboxUnavailable as exc:
        session.stop()
        pytest.skip(f"sandbox unavailable: {exc}")
    try:
        session.wait_for_startup_complete()
        session.hide_overview()
        yield session
    finally:
        session.stop()


@pytest.fixture(scope="session")
def sandbox_shared_data(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[SandboxSession]:
    """Private settings, the user's real data directory visible read-only."""
    yield from _session(tmp_path_factory, mode=DataMode.SHARED, seed_fixtures=False)


@pytest.fixture(scope="session")
def sandbox_private_data(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[SandboxSession]:
    """Everything private, seeded with window-calls and the fixture corpus."""
    yield from _session(tmp_path_factory, mode=DataMode.PRIVATE, seed_fixtures=True)


@pytest.fixture
def sandbox_run_dir(tmp_path: Path) -> Path:
    """Somewhere for a test to drop screenshots and logs it wants to keep."""
    path = tmp_path / "run"
    path.mkdir()
    return path


@pytest.fixture(scope="session")
def broadway_session(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[dict[str, str]]:
    """The cheap offscreen variant: ``gtk4-broadwayd`` instead of a whole shell.

    No compositor, no shell, no extensions — a GTK4 app renders to an HTML5
    backend and can be started, driven and killed in under a second. This is
    what the CI ``gtk`` job uses (archlinux container, ``dbus-run-session``),
    and what a page author should iterate against; the full shell is for the
    things that genuinely need a shell, like screenshots with real chrome and
    anything involving extensions.

    Yields the environment a client must run with.
    """
    import subprocess

    if shutil.which("gtk4-broadwayd") is None:
        pytest.skip("gtk4-broadwayd is not installed")
    if shutil.which("dbus-run-session") is None:
        pytest.skip("dbus-run-session is not installed")

    root = tmp_path_factory.mktemp("broadway-")
    for sub in ("config", "cache", "state"):
        (root / sub).mkdir()
    # Display :N maps to a socket in XDG_RUNTIME_DIR; pick one from the pid so
    # two test processes do not fight over it.
    display = f":{5000 + (os.getpid() % 2000)}"
    log = (root / "broadwayd.log").open("wb")
    env = dict(
        os.environ,
        XDG_CONFIG_HOME=str(root / "config"),
        XDG_CACHE_HOME=str(root / "cache"),
        XDG_STATE_HOME=str(root / "state"),
    )
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)
    proc = subprocess.Popen(  # noqa: S603
        ["gtk4-broadwayd", display],
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    client_env = dict(env, GDK_BACKEND="broadway", BROADWAY_DISPLAY=display)

    # The daemon creates its socket a beat after it starts; a client that
    # connects first fails with "cannot open display" and looks like a bug in
    # the app rather than a race in the fixture.
    socket = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / f"broadway{display[1:]}.socket"
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        if socket.exists():
            break
        if proc.poll() is not None:
            pytest.skip(f"gtk4-broadwayd exited: {(root / 'broadwayd.log').read_text()[-500:]}")
        time.sleep(0.1)

    try:
        yield client_env
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
