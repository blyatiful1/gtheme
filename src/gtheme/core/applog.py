"""The log file, and the hooks that make sure a crash reaches it.

Before this module there was no logging anywhere in gtheme — no log file, no
debug flag, no excepthook. That is fine right up until somebody's switch does
nothing and the only record of why is a traceback PyGObject printed to a
console that does not exist (the ``.desktop`` launcher sets ``Terminal=false``).
There was nothing to ask that person for.

So: one rotating file, ``~/.local/state/gtheme/v2/gtheme.log``, next to the
baseline and the restore points, and small enough that it can never become a
problem of its own (:data:`MAX_BYTES` per file, :data:`BACKUP_COUNT` old ones).
The path comes from :func:`gtheme.core.paths.state_dir`, so the test suite's
``GTHEME_STATE_DIR`` seam redirects the log exactly like everything else.

**Nothing is written to the console.** The ``gtheme`` logger does not propagate
to the root logger, so a warning cannot turn into stderr noise in front of a
person who is only trying to change their wallpaper. (Tests therefore read the
file rather than using ``caplog``.)

**What may be logged.** Keys, schema and file paths, add-on names, exception
types and their text. **Never the value of a setting**: what somebody's
password prompt says, what their home directory is called, what a Look wrote
into a terminal profile — none of that is ours to keep on disk. Anything that
logs a write logs *which* key changed, not what it changed to. Keep it that
way; a support log people are asked to paste into a bug report is exactly the
wrong place to be clever.

**Why an excepthook is enough for GTK.** Verified in this tree with a real main
loop: an exception raised inside a ``GLib.idle_add`` callback — the same route
every GTK signal handler takes — reaches ``sys.excepthook``, because PyGObject
prints unhandled callback exceptions through ``PyErr_Print``. So installing
``sys.excepthook`` covers the "the click did nothing and printed a traceback
nobody saw" class outright. :func:`install_excepthooks` also takes
``sys.unraisablehook`` (finalisers) and ``threading.excepthook`` (the apply
worker runs on a thread), and each one chains to the hook it replaced, so
running from a terminal still prints what it always did.

This module is stdlib-only on purpose: :mod:`gtheme.cli` imports it at module
scope, and ``gtheme rescue`` must keep working on a machine with no PyGObject
at all.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import threading
from pathlib import Path
from types import TracebackType
from typing import Any

from . import paths

__all__ = [
    "BACKUP_COUNT",
    "LOGGER_NAME",
    "MAX_BYTES",
    "configure",
    "install_excepthooks",
    "log_file",
    "logger",
    "shutdown",
    "start",
]

#: Every logger in the app hangs below this one.
LOGGER_NAME = "gtheme"

#: Per-file cap. Deliberately small: this is a support log, not telemetry.
MAX_BYTES = 128 * 1024

#: How many rotated files to keep beside the live one.
BACKUP_COUNT = 2

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

#: ``GTHEME_LOG_LEVEL`` accepts these and nothing else; anything unrecognised
#: falls back to INFO rather than failing, because a typo in an environment
#: variable must not stop the app from starting.
_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}

_lock = threading.RLock()
_handler: logging.Handler | None = None
_handler_path: Path | None = None

_hooks_installed = False
_previous_excepthook: Any = None
_previous_unraisablehook: Any = None
_previous_threading_excepthook: Any = None


def log_file() -> Path:
    """Where the log lives. Follows ``GTHEME_STATE_DIR`` like all v2 state."""
    return paths.state_dir() / "gtheme.log"


def logger(name: str | None = None) -> logging.Logger:
    """The logger a module should use — ``applog.logger(__name__)``."""
    if not name:
        return logging.getLogger(LOGGER_NAME)
    if name == LOGGER_NAME or name.startswith(f"{LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{LOGGER_NAME}.{name}")


def _level() -> int:
    return _LEVELS.get(os.environ.get("GTHEME_LOG_LEVEL", "").strip().upper(), logging.INFO)


def configure(*, force: bool = False) -> logging.Logger:
    """Point the ``gtheme`` logger at the rotating file. Safe to call twice.

    Re-attaches when :func:`log_file` has moved since last time, which is what
    makes a test's temporary state directory work; ``force`` re-attaches
    unconditionally (used when a test changes :data:`MAX_BYTES`).

    A state directory that cannot be created is not an error worth crashing
    over — the app falls back to logging nowhere and carries on.
    """
    global _handler, _handler_path

    log = logging.getLogger(LOGGER_NAME)
    log.setLevel(_level())
    # No console spam: nothing of ours reaches the root logger's handlers, and
    # nothing reaches logging.lastResort's stderr either.
    log.propagate = False

    with _lock:
        target = log_file()
        if _handler is not None and _handler_path == target and not force:
            return log
        _detach()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            handler: logging.Handler = logging.handlers.RotatingFileHandler(
                target,
                maxBytes=MAX_BYTES,
                backupCount=BACKUP_COUNT,
                encoding="utf-8",
                delay=True,
            )
        except OSError:
            log.addHandler(logging.NullHandler())
            return log
        handler.setFormatter(logging.Formatter(_FORMAT))
        log.addHandler(handler)
        _handler = handler
        _handler_path = target
    return log


def _detach() -> None:
    """Remove and close whatever we attached. Call with the lock held."""
    global _handler, _handler_path

    log = logging.getLogger(LOGGER_NAME)
    for handler in list(log.handlers):
        log.removeHandler(handler)
        try:
            handler.close()
        except Exception:  # pragma: no cover - closing must never raise upward
            pass
    _handler = None
    _handler_path = None


def start() -> logging.Logger:
    """What an entry point calls: configure the file, install the hooks."""
    log = configure()
    install_excepthooks()
    return log


def install_excepthooks() -> None:
    """Send unhandled exceptions to the log as well as wherever they went.

    Three hooks, because a desktop app loses tracebacks three ways: the main
    thread and every GTK callback (:data:`sys.excepthook`), object finalisers
    (:data:`sys.unraisablehook`), and the apply worker
    (:data:`threading.excepthook`).
    """
    global _hooks_installed
    global _previous_excepthook, _previous_unraisablehook, _previous_threading_excepthook

    with _lock:
        if _hooks_installed:
            return
        _previous_excepthook = sys.excepthook
        _previous_unraisablehook = sys.unraisablehook
        _previous_threading_excepthook = threading.excepthook
        sys.excepthook = _excepthook
        sys.unraisablehook = _unraisablehook
        threading.excepthook = _thread_excepthook
        _hooks_installed = True


def _record(message: str, exc_info: Any) -> None:
    """Log without ever being able to break the hook chain."""
    try:
        logger().error(message, exc_info=exc_info)
    except Exception:  # pragma: no cover - a broken log must not eat a crash
        pass


def _excepthook(
    exc_type: type[BaseException],
    exc: BaseException,
    tb: TracebackType | None,
) -> None:
    # Ctrl+C is a person stopping the app, not a fault.
    if not issubclass(exc_type, KeyboardInterrupt):
        _record("unhandled error", (exc_type, exc, tb))
    previous = _previous_excepthook or sys.__excepthook__
    previous(exc_type, exc, tb)


def _unraisablehook(unraisable: Any) -> None:
    # Only the exception and the message: ``unraisable.object`` is an arbitrary
    # object whose repr could carry a setting's value.
    _record(
        f"unraisable error ({unraisable.err_msg or 'during finalisation'})",
        (type(unraisable.exc_value), unraisable.exc_value, unraisable.exc_traceback)
        if unraisable.exc_value is not None
        else None,
    )
    previous = _previous_unraisablehook or sys.__unraisablehook__
    previous(unraisable)


def _thread_excepthook(args: Any) -> None:
    if not issubclass(args.exc_type, SystemExit):
        name = getattr(args.thread, "name", "?")
        _record(
            f"unhandled error on background work ({name})",
            (args.exc_type, args.exc_value, args.exc_traceback),
        )
    previous = _previous_threading_excepthook or threading.__excepthook__
    previous(args)


def shutdown() -> None:
    """Undo :func:`configure` and :func:`install_excepthooks`.

    For tests and for symmetry; the app itself never needs it.
    """
    global _hooks_installed
    global _previous_excepthook, _previous_unraisablehook, _previous_threading_excepthook

    with _lock:
        _detach()
        if _hooks_installed:
            sys.excepthook = _previous_excepthook or sys.__excepthook__
            sys.unraisablehook = _previous_unraisablehook or sys.__unraisablehook__
            threading.excepthook = _previous_threading_excepthook or threading.__excepthook__
            _previous_excepthook = None
            _previous_unraisablehook = None
            _previous_threading_excepthook = None
            _hooks_installed = False
