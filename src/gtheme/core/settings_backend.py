"""The settings backend seam.

THE CONTRACT IS FROZEN. Every module that reads or writes a desktop setting
goes through :class:`SettingsBackend`; nothing else in gtheme may call
``gsettings``, ``dconf`` or ``Gio.Settings`` directly. Waves 1 and 2 are
parallel-safe precisely because this file does not change under them. Changing
a name, a signature or the key grammar below is a breaking change that has to
go through the integration agent.

Three things are frozen here.

**1. The key grammar.** One string addresses one setting, in three forms::

    gsettings:org.gnome.desktop.interface color-scheme
    dconf:/org/gnome/shell/extensions/blur-my-shell/panel/blur
    gsettings-path:org.gnome.shell.extensions.burn-my-windows-profile:/org/gnome/shell/extensions/burn-my-windows/profiles/1/ name

The third form is for *relocatable* schemas — schemas with no fixed path, of
which burn-my-windows' 163-key per-profile schema is the reason this form
exists. Note the shape: ``schema`` and ``path`` are colon-separated, then a
space, then the key. The ``dconf:`` form addresses a path with no schema at all
and is the last resort: without a schema there is no type information, so
values are handled purely as text.

**2. Values are GVariant text, always.** ``get`` returns, and ``set`` accepts,
the exact string ``GLib.Variant.print_(True)`` produces — ``'true'``,
``'"Adwaita"'``, ``"@as []"``, ``'@ms nothing'``. This is what makes a generic
restore possible without gtheme knowing any key's type, and v1 proved the
round-trip works. Do not "helpfully" accept Python objects: an ``as`` that is
empty must come back as ``@as []`` and not ``[]``, or restore writes a
differently-typed value than the one it captured.

**3. Failures are typed.** Backends raise :class:`BackendError` carrying a
:class:`BackendErrorKind`. Callers branch on the kind. Nothing anywhere may
match on a message string — v1 did that against ``gsettings`` stderr and it
broke under a locale change, which is why every subprocess call in the
subprocess backend pins ``LC_ALL=C`` and still does not trust the text.
"""

from __future__ import annotations

import enum
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

__all__ = [
    "BackendError",
    "BackendErrorKind",
    "GioBackend",
    "KeyKind",
    "MemoryBackend",
    "SettingsBackend",
    "SettingsKey",
    "SubprocessBackend",
    "parse_key",
]


class BackendErrorKind(enum.Enum):
    """Why a backend call failed. The set is closed; callers may exhaust it."""

    #: The schema is not installed. Usually means an extension is not present.
    NO_SCHEMA = "no-schema"
    #: The schema exists but has no such key. Usually a version skew.
    NO_KEY = "no-key"
    #: The write was accepted and then not persisted. dconf's classic failure:
    #: ``gsettings set`` exits 0 while printing "failed to commit changes to
    #: dconf" — v1 was bitten by this, so a zero exit is never proof.
    COMMIT_FAILED = "commit-failed"
    #: Anything else, including a malformed value for the key's type.
    OTHER = "other"


class BackendError(Exception):
    """A typed settings failure.

    Attributes:
        kind: which of the four closed failure modes this is.
        key: the key string the call was about, when there was one.
    """

    def __init__(
        self,
        kind: BackendErrorKind,
        message: str,
        *,
        key: str | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.key = key

    def __str__(self) -> str:  # pragma: no cover - trivial
        base = super().__str__()
        return f"{base} [{self.kind.value}]" if self.kind else base


class KeyKind(enum.Enum):
    """Which of the three address forms a key string uses."""

    GSETTINGS = "gsettings"
    DCONF = "dconf"
    GSETTINGS_PATH = "gsettings-path"


@dataclass(frozen=True)
class SettingsKey:
    """A parsed key string.

    ``schema`` and ``key`` are set for the two schema-backed forms; ``path`` is
    set for :attr:`KeyKind.DCONF` (the full dconf path) and for
    :attr:`KeyKind.GSETTINGS_PATH` (the schema's instance path, which always
    ends in ``/``).
    """

    kind: KeyKind
    schema: str | None = None
    key: str | None = None
    path: str | None = None

    def as_text(self) -> str:
        """Render back to the canonical key string. Round-trips ``parse_key``."""
        if self.kind is KeyKind.GSETTINGS:
            return f"gsettings:{self.schema} {self.key}"
        if self.kind is KeyKind.DCONF:
            return f"dconf:{self.path}"
        return f"gsettings-path:{self.schema}:{self.path} {self.key}"


_SCHEMA_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*(\.[A-Za-z0-9_\-]+)+$")
_KEY_RE = re.compile(r"^[a-z0-9]([a-z0-9\-]*[a-z0-9])?$")


def parse_key(text: str) -> SettingsKey:
    """Parse a key string into a :class:`SettingsKey`.

    Raises:
        BackendError: with kind :attr:`BackendErrorKind.OTHER` if the string is
            not one of the three forms. Malformed keys are a programming error
            in a descriptor or preset, so they fail loudly rather than being
            skipped.
    """
    prefix, sep, rest = text.partition(":")
    if not sep:
        raise BackendError(
            BackendErrorKind.OTHER,
            f"not a settings key: {text!r} (expected 'gsettings:', 'dconf:' "
            "or 'gsettings-path:' prefix)",
            key=text,
        )

    if prefix == KeyKind.DCONF.value:
        if not rest.startswith("/") or rest.endswith("/"):
            raise BackendError(
                BackendErrorKind.OTHER,
                f"dconf key must be an absolute path to a key: {text!r}",
                key=text,
            )
        return SettingsKey(KeyKind.DCONF, path=rest)

    if prefix == KeyKind.GSETTINGS.value:
        schema, space, key = rest.partition(" ")
        if not space or not _SCHEMA_RE.match(schema) or not _KEY_RE.match(key):
            raise BackendError(
                BackendErrorKind.OTHER,
                f"expected 'gsettings:SCHEMA KEY', got {text!r}",
                key=text,
            )
        return SettingsKey(KeyKind.GSETTINGS, schema=schema, key=key)

    if prefix == KeyKind.GSETTINGS_PATH.value:
        schema, sep2, tail = rest.partition(":")
        path, space, key = tail.partition(" ")
        if (
            not sep2
            or not space
            or not _SCHEMA_RE.match(schema)
            or not _KEY_RE.match(key)
            or not path.startswith("/")
            or not path.endswith("/")
        ):
            raise BackendError(
                BackendErrorKind.OTHER,
                "expected 'gsettings-path:SCHEMA:/instance/path/ KEY' "
                f"(path must start and end with '/'), got {text!r}",
                key=text,
            )
        return SettingsKey(KeyKind.GSETTINGS_PATH, schema=schema, key=key, path=path)

    raise BackendError(
        BackendErrorKind.OTHER,
        f"unknown key prefix {prefix!r} in {text!r}",
        key=text,
    )


class SettingsBackend(ABC):
    """Read and write desktop settings. FROZEN — see the module docstring.

    Args:
        schema_source: an optional ``Gio.SettingsSchemaSource`` to look schemas
            up in before the system default. Extensions keep their schemas in
            their own ``schemas/`` directory rather than in the system store,
            so panels build a source per extension and hand it in here.
    """

    def __init__(self, schema_source: Any | None = None) -> None:
        self.schema_source = schema_source

    @abstractmethod
    def get(self, key: str) -> str:
        """Return the current value as GVariant text.

        Raises:
            BackendError: NO_SCHEMA / NO_KEY / OTHER.
        """

    @abstractmethod
    def set(self, key: str, value: str) -> None:
        """Write a value given as GVariant text.

        Raises:
            BackendError: NO_SCHEMA / NO_KEY / COMMIT_FAILED / OTHER. A backend
                must verify the write landed before returning; exiting zero is
                not proof.
        """

    @abstractmethod
    def reset(self, key: str) -> None:
        """Return the key to its schema default.

        Raises:
            BackendError: NO_SCHEMA / NO_KEY / COMMIT_FAILED / OTHER.
        """


class MemoryBackend(SettingsBackend):
    """A real GSettings backend that writes nowhere. The test seam.

    Backed by ``Gio.memory_settings_backend_new()``, so values go through the
    genuine GVariant type machinery — a wrongly-typed write fails here exactly
    as it would against dconf — while the live desktop is untouched. This is
    what the unit tier uses, and what the ``mutating`` guard in
    ``tests/conftest.py`` accepts as an isolation seam.

    Schemas still have to exist: the memory backend replaces the *store*, not
    the schema source. Tests that need a schema the machine does not have
    compile a throwaway one and pass it in as ``schema_source``.

    Note that ``gi`` is imported inside the methods, not at module scope. The
    guard test ``tests/unit/test_core_no_gtk.py`` asserts that importing
    anything under ``gtheme.core`` pulls in no Gtk/Adw, and keeping the import
    lazy also means ``import gtheme.core.settings_backend`` works on a machine
    with no PyGObject at all — which the ``rescue`` path depends on.
    """

    def __init__(self, schema_source: Any | None = None) -> None:
        super().__init__(schema_source)
        self._backend: Any | None = None
        self._settings: dict[tuple[str, str | None], tuple[Any, Any]] = {}

    def _gio(self) -> tuple[Any, Any]:
        from gi.repository import Gio, GLib

        return Gio, GLib

    def _make_backend(self) -> Any:
        if self._backend is None:
            Gio, _ = self._gio()
            self._backend = Gio.memory_settings_backend_new()
        return self._backend

    def _schema(self, parsed: SettingsKey) -> Any:
        Gio, _ = self._gio()
        source = self.schema_source or Gio.SettingsSchemaSource.get_default()
        if source is None:  # pragma: no cover - no schemas installed at all
            raise BackendError(
                BackendErrorKind.NO_SCHEMA,
                "no GSettings schemas are installed on this system",
                key=parsed.as_text(),
            )
        schema = source.lookup(parsed.schema, True)
        if schema is None:
            raise BackendError(
                BackendErrorKind.NO_SCHEMA,
                f"schema {parsed.schema!r} is not installed",
                key=parsed.as_text(),
            )
        return schema

    def _settings_for(self, key: str) -> tuple[Any, Any, SettingsKey]:
        """``(settings, schema, parsed)`` for a key, cached per schema instance.

        The schema object is kept alongside the ``Gio.Settings`` deliberately.
        ``Gio.Settings`` has no ``get_settings_schema()`` method in PyGObject —
        the schema is reachable only as the ``settings-schema`` *property* —
        and the source it came from may be a per-extension one that
        ``Gio.SettingsSchemaSource.get_default()`` cannot see at all.
        """
        parsed = parse_key(key)
        if parsed.kind is KeyKind.DCONF:
            raise BackendError(
                BackendErrorKind.OTHER,
                "the memory backend cannot address raw dconf paths — a "
                "schema-less key has no type information to validate against",
                key=key,
            )
        Gio, _ = self._gio()
        cache_key = (parsed.schema or "", parsed.path)
        cached = self._settings.get(cache_key)
        if cached is None:
            schema = self._schema(parsed)
            if parsed.kind is KeyKind.GSETTINGS_PATH:
                settings = Gio.Settings.new_full(schema, self._make_backend(), parsed.path)
            else:
                if not schema.get_path():
                    raise BackendError(
                        BackendErrorKind.NO_SCHEMA,
                        f"schema {parsed.schema!r} is relocatable and needs a path — "
                        "use the 'gsettings-path:SCHEMA:/path/ KEY' form",
                        key=key,
                    )
                settings = Gio.Settings.new_full(schema, self._make_backend(), None)
            cached = (settings, schema)
            self._settings[cache_key] = cached
        settings, schema = cached
        if not schema.has_key(parsed.key):
            raise BackendError(
                BackendErrorKind.NO_KEY,
                f"schema {parsed.schema!r} has no key {parsed.key!r}",
                key=key,
            )
        return settings, schema, parsed

    def get(self, key: str) -> str:
        settings, _schema, parsed = self._settings_for(key)
        return settings.get_value(parsed.key).print_(True)

    def set(self, key: str, value: str) -> None:
        settings, schema, parsed = self._settings_for(key)
        _, GLib = self._gio()
        expected = schema.get_key(parsed.key).get_value_type()
        try:
            variant = GLib.Variant.parse(expected, value, None, None)
        except GLib.Error as exc:
            raise BackendError(
                BackendErrorKind.OTHER,
                f"{value!r} is not a valid {expected.dup_string()} for {key}: {exc}",
                key=key,
            ) from exc
        if not settings.set_value(parsed.key, variant):
            raise BackendError(
                BackendErrorKind.COMMIT_FAILED,
                f"the backend refused the write to {key}",
                key=key,
            )

    def reset(self, key: str) -> None:
        settings, _schema, parsed = self._settings_for(key)
        settings.reset(parsed.key)


class GioBackend(SettingsBackend):
    """The primary backend: native ``Gio.Settings`` against the real store.

    Lands with the core engine port (Wave 1 Agent A). It must produce values
    byte-identical to :class:`SubprocessBackend` — a parity test against a real
    dconf inside the sandbox tier is what proves it, because the exact-string
    round-trip is what generic restore rests on.
    """

    def get(self, key: str) -> str:
        raise NotImplementedError("GioBackend.get")

    def set(self, key: str, value: str) -> None:
        raise NotImplementedError("GioBackend.set")

    def reset(self, key: str) -> None:
        raise NotImplementedError("GioBackend.reset")


class SubprocessBackend(SettingsBackend):
    """The fallback backend: ``gsettings`` and ``dconf`` as child processes.

    Slower and clumsier than :class:`GioBackend`, and kept anyway, because it
    is the code path v1 shipped and proved. It is also the only backend that
    can address the ``dconf:`` form. Two rules the implementation must keep:
    pin ``LC_ALL=C`` on every call, and never conclude a write succeeded from
    the exit status alone.

    Lands with the core engine port (Wave 1 Agent A).
    """

    def get(self, key: str) -> str:
        raise NotImplementedError("SubprocessBackend.get")

    def set(self, key: str, value: str) -> None:
        raise NotImplementedError("SubprocessBackend.set")

    def reset(self, key: str) -> None:
        raise NotImplementedError("SubprocessBackend.reset")
