"""Choosing a settings backend, and the seam that lets tests replace it.

:class:`~gtheme.core.transaction.Transaction` takes no backend argument — the
signature is frozen and a UI page has no business choosing one. So the choice
lives here, in one place, with one override.

:class:`AutoBackend` is the default, and it is a router rather than a third
implementation. Native ``Gio.Settings`` handles everything that has a schema;
raw ``dconf:`` locations have no schema, so ``Gio.Settings`` cannot open them
at all and they go to the subprocess backend. When PyGObject is missing
entirely — the machine ``gtheme rescue`` is for — everything goes to the
subprocess backend, which still works because it only needs the ``gsettings``
and ``dconf`` commands.

:func:`use_backend` is the test seam and the only supported way to point the
engine somewhere else. ``tests/conftest.py`` hands it a ``MemoryBackend`` and
the whole engine writes nowhere.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from .settings_backend import (
    BackendError,
    BackendErrorKind,
    GioBackend,
    KeyKind,
    SettingsBackend,
    SubprocessBackend,
    parse_key,
)

__all__ = [
    "AutoBackend",
    "get_backend",
    "has_session_bus",
    "is_missing",
    "set_backend",
    "use_backend",
]

_OVERRIDE: SettingsBackend | None = None
_DEFAULT: SettingsBackend | None = None


def _pygobject_available() -> bool:
    try:
        import gi.repository.Gio  # noqa: F401
    except Exception:  # noqa: BLE001 - no PyGObject, no typelib, no anything
        return False
    return True


class AutoBackend(SettingsBackend):
    """Native where possible, subprocess where necessary.

    Args:
        schema_source: passed to whichever backend handles the call. A
            ``Gio.SettingsSchemaSource`` for the native leg; the subprocess leg
            uses it only if it is a directory path.
    """

    def __init__(self, schema_source: Any | None = None) -> None:
        super().__init__(schema_source)
        self._gio: GioBackend | None = (
            GioBackend(schema_source) if _pygobject_available() else None
        )
        self._subprocess = SubprocessBackend(schema_source)

    def _pick(self, key: str) -> SettingsBackend:
        """Which backend can address this key at all.

        Two forms decide it, in opposite directions. ``dconf:`` names a
        location with no schema, which ``Gio.Settings`` cannot open, so it goes
        to the child process. ``keyfile:`` names a setting kept in an add-on's
        own file rather than in the settings store, which no command-line tool
        can open, so it must go to Gio. Everything else prefers Gio because it
        is faster and its failures are typed rather than translated.

        With no PyGObject at all — the rescue path — a ``keyfile:`` key reaches
        the subprocess backend and comes back as a typed refusal. That is the
        truth, and better than a silent no-op.
        """
        if self._gio is None:
            return self._subprocess
        kind = parse_key(key).kind
        if kind is KeyKind.DCONF:
            return self._subprocess
        return self._gio

    def get(self, key: str) -> str:
        return self._pick(key).get(key)

    def set(self, key: str, value: str) -> None:
        self._pick(key).set(key, value)

    def reset(self, key: str) -> None:
        self._pick(key).reset(key)


def get_backend() -> SettingsBackend:
    """The backend the engine should use right now.

    An override set by :func:`set_backend` or :func:`use_backend` always wins.
    Otherwise a single :class:`AutoBackend` is built once and reused, because
    ``Gio.Settings`` objects are worth caching and building one per key is how
    a preview of forty rows becomes slow.
    """
    global _DEFAULT
    if _OVERRIDE is not None:
        return _OVERRIDE
    if _DEFAULT is None:
        _DEFAULT = AutoBackend()
    return _DEFAULT


def set_backend(backend: SettingsBackend | None) -> None:
    """Force a backend for the whole process, or pass None to stop forcing."""
    global _OVERRIDE
    _OVERRIDE = backend


@contextmanager
def use_backend(backend: SettingsBackend) -> Iterator[SettingsBackend]:
    """Force a backend for the duration of the block, then put it back."""
    global _OVERRIDE
    previous = _OVERRIDE
    _OVERRIDE = backend
    try:
        yield backend
    finally:
        _OVERRIDE = previous


def has_session_bus() -> bool:
    """Is there a desktop session to write settings into? (The AS5 check.)

    Without one, every single write fails the same way. Discovering that forty
    times over and reporting forty failures is noise; the useful answer is one
    sentence saying the settings were skipped and why, which is what
    :class:`~gtheme.core.transaction.Transaction` does with this.
    """
    if os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        return True
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime:
        return False
    return os.path.exists(os.path.join(runtime, "bus"))


def is_missing(error: BackendError) -> bool:
    """Does this failure mean "not on this machine" rather than "broke"?

    A missing schema or key is what an add-on the user does not have looks
    like, or a GNOME version that predates a setting. It is a skip with a
    sentence (the AS8 rule), never a failed apply.
    """
    return error.kind in (BackendErrorKind.NO_SCHEMA, BackendErrorKind.NO_KEY)
