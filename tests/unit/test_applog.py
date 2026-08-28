"""The log file and the crash hooks.

Every test here writes into a throwaway state directory (the ``state_dir``
seam), so the real ``~/.local/state/gtheme/v2/gtheme.log`` is never touched.
Nothing here opens the app: the one test that covers ``app.run`` replaces the
module's ``Adw``, ``Gtk`` and ``Application`` names, so no window is ever
created.

Note that these tests read the log *file* rather than using ``caplog``: the
``gtheme`` logger deliberately does not propagate, which is the same property
that keeps warnings off a person's console.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import textwrap
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from gtheme.core import applog


@pytest.fixture(autouse=True)
def _clean_logging():
    """No test may inherit another's handler or hooks."""
    applog.shutdown()
    yield
    applog.shutdown()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_the_log_lands_in_the_v2_state_directory(state_dir):
    log = applog.configure()
    log.info("a line worth keeping")

    assert applog.log_file() == state_dir / "gtheme.log"
    assert "a line worth keeping" in _read(applog.log_file())


def test_the_log_records_the_level_and_the_time(state_dir):
    applog.configure().warning("something went sideways")

    line = _read(applog.log_file()).strip()
    assert "WARNING" in line
    assert "gtheme" in line
    assert line[:2].isdigit()  # the timestamp leads the line


def test_configure_follows_the_state_directory_when_it_moves(tmp_path, monkeypatch):
    first = tmp_path / "one"
    second = tmp_path / "two"
    monkeypatch.setenv("GTHEME_STATE_DIR", str(first))
    applog.configure().info("first home")
    monkeypatch.setenv("GTHEME_STATE_DIR", str(second))
    applog.configure().info("second home")

    assert "second home" not in _read(first / "gtheme.log")
    assert "second home" in _read(second / "gtheme.log")


def test_configuring_twice_does_not_double_the_handlers(state_dir):
    applog.configure()
    applog.configure()
    log = logging.getLogger(applog.LOGGER_NAME)
    log.info("said once")

    assert len(log.handlers) == 1
    assert _read(applog.log_file()).count("said once") == 1


def test_the_log_rotates_and_stays_small(state_dir, monkeypatch):
    """A support log that can fill somebody's disk is a bug, not a feature."""
    monkeypatch.setattr(applog, "MAX_BYTES", 2048)
    log = applog.configure(force=True)
    for index in range(400):
        log.info("%s %s", index, "x" * 120)

    files = sorted(p.name for p in state_dir.iterdir())
    assert files == ["gtheme.log", "gtheme.log.1", "gtheme.log.2"]
    for name in files:
        # One record may overshoot the cap: the handler rolls after writing.
        assert (state_dir / name).stat().st_size < 2048 + 512


def test_nothing_reaches_the_console(state_dir, capsys):
    log = applog.configure()
    log.warning("this belongs in the file")
    log.error("so does this")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert "this belongs in the file" in _read(applog.log_file())


def test_a_state_directory_that_cannot_be_made_does_not_stop_the_app(tmp_path, monkeypatch):
    """A read-only or occupied state path costs the log, never the app."""
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("i am a file", encoding="utf-8")
    monkeypatch.setenv("GTHEME_STATE_DIR", str(blocker / "state"))

    log = applog.configure()
    log.error("nowhere to write this")  # must not raise

    assert not (blocker / "state").exists()


def test_the_excepthook_writes_the_traceback_and_still_chains(state_dir, monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(sys, "excepthook", lambda t, e, tb: seen.append(str(e)))
    applog.start()

    try:
        raise ValueError("the switch could not be written")
    except ValueError:
        sys.excepthook(*sys.exc_info())

    text = _read(applog.log_file())
    assert "unhandled error" in text
    assert "ValueError: the switch could not be written" in text
    assert "Traceback (most recent call last)" in text
    assert seen == ["the switch could not be written"], "the previous hook must still run"


def test_ctrl_c_is_not_logged_as_an_error(state_dir, monkeypatch):
    monkeypatch.setattr(sys, "excepthook", lambda t, e, tb: None)
    log = applog.start()
    log.info("the app started")  # so there is a file to look in either way

    try:
        raise KeyboardInterrupt
    except KeyboardInterrupt:
        sys.excepthook(*sys.exc_info())

    text = _read(applog.log_file())
    assert "the app started" in text
    assert "KeyboardInterrupt" not in text


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_crash_on_a_background_thread_reaches_the_log(state_dir):
    """The apply worker is a thread; its tracebacks used to go nowhere."""
    applog.start()

    def boom() -> None:
        raise RuntimeError("the apply worker fell over")

    worker = threading.Thread(target=boom, name="apply-worker")
    worker.start()
    worker.join()

    text = _read(applog.log_file())
    assert "apply-worker" in text
    assert "RuntimeError: the apply worker fell over" in text


def test_the_hooks_are_installed_once_and_removed_cleanly(state_dir, monkeypatch):
    original = lambda t, e, tb: None  # noqa: E731
    monkeypatch.setattr(sys, "excepthook", original)

    applog.install_excepthooks()
    installed = sys.excepthook
    applog.install_excepthooks()
    assert sys.excepthook is installed

    applog.shutdown()
    assert sys.excepthook is original


def test_the_command_line_writes_a_log(state_dir, tmp_path, capsys):
    """Every subcommand — including rescue — starts logging before it runs."""
    from gtheme.cli import main

    (tmp_path / "theme.toml").write_text(
        """
        format = 2
        [meta]
        name = "demo"
        title = "Demo"
        description = "A demo Look."
        author = "someone"
        version = "1.0.0"
        screenshots = ["shot.png"]
        """,
        encoding="utf-8",
    )
    assert main(["validate", str(tmp_path)]) == 0
    capsys.readouterr()

    text = _read(applog.log_file())
    assert "validate" in text
    assert "validate finished with 0" in text


@pytest.mark.gtk
def test_opening_the_app_configures_logging(state_dir, monkeypatch):
    """``app.run`` must set the log up before any GTK callback can raise."""
    pytest.importorskip("gi", reason="PyGObject is needed to import the app module")
    from gtheme import app

    monkeypatch.setattr(app, "Adw", SimpleNamespace(init=lambda: None))
    monkeypatch.setattr(app, "Gtk", SimpleNamespace(init=lambda: None))
    monkeypatch.setattr(app, "Application", lambda: SimpleNamespace(run=lambda argv: 0))

    assert app.run([]) == 0

    text = _read(applog.log_file())
    assert "opening gtheme" in text
    assert "the app closed with 0" in text


def test_an_exception_in_a_gtk_callback_reaches_the_log(state_dir):
    """The decisive one, in a real main loop.

    A signal handler that raises is exactly the failure the audit found being
    printed to a console nobody sees. PyGObject routes it through
    ``sys.excepthook``, so the log has to catch it — proven here rather than
    argued, in a separate process with its own state directory.
    """
    pytest.importorskip("gi", reason="PyGObject is needed for the main loop")
    script = textwrap.dedent(
        """
        from gtheme.core import applog
        applog.start()
        from gi.repository import GLib

        loop = GLib.MainLoop()

        def callback():
            raise ValueError("the switch could not be written")

        def stop():
            loop.quit()
            return False

        GLib.idle_add(callback)
        GLib.timeout_add(500, stop)
        loop.run()
        print("survived")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, "GTHEME_STATE_DIR": str(state_dir)},
        check=False,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "survived", "the app must survive the callback"
    text = _read(state_dir / "gtheme.log")
    assert "ValueError: the switch could not be written" in text
    assert "Traceback (most recent call last)" in text
