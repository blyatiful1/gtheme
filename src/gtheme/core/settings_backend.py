"""The settings backend seam.

THE CONTRACT IS FROZEN. Every module that reads or writes a desktop setting
goes through :class:`SettingsBackend`; nothing else in gtheme may call
``gsettings``, ``dconf`` or ``Gio.Settings`` directly. Waves 1 and 2 are
parallel-safe precisely because this file does not change under them. Changing
a name, a signature or the key grammar below is a breaking change that has to
go through the integration agent.

Three things are frozen here.

**1. The key grammar.** One string addresses one setting, in four forms::

    gsettings:org.gnome.desktop.interface color-scheme
    dconf:/org/gnome/shell/extensions/blur-my-shell/panel/blur
    gsettings-path:org.gnome.shell.extensions.burn-my-windows-profile:/org/gnome/shell/extensions/burn-my-windows/profiles/1/ name
    keyfile:/home/you/.config/burn-my-windows/profiles/123.conf:org.gnome.shell.extensions.burn-my-windows-profile:/burn-my-windows/profile/ fire-enable-effect

The third form is for *relocatable* schemas — schemas with no fixed path, of
which burn-my-windows' 163-key per-profile schema is the reason this form
exists. Note the shape: ``schema`` and ``path`` are colon-separated, then a
space, then the key. The ``dconf:`` form addresses a path with no schema at all
and is the last resort: without a schema there is no type information, so
values are handled purely as text.

The fourth form addresses a setting that has a perfectly ordinary schema and
does not live in the settings store at all. burn-my-windows keeps each of its
effect profiles in its own ``.conf`` file under
``~/.config/burn-my-windows/profiles/`` and reads it through
``Gio.keyfile_settings_backend_new`` (its ``src/ProfileManager.js``). Verified
on this machine: the profile file holds real values while
``dconf dump /org/gnome/shell/extensions/burn-my-windows-profile/`` is empty. A
row written in the ``gsettings-path:`` form would report success, change
nothing, and be undiagnosable — so the file is named in the key, and the
backend opens it. Shape: ``keyfile:<file>:<schema>:<root-path>/`` then a space
and the key. Only :class:`GioBackend` can address this form; ``gsettings`` and
``dconf`` have no way to reach it, so :class:`SubprocessBackend` returns a
typed refusal and ``core.backends.AutoBackend`` routes it to Gio.

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
import os
import re
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
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
    KEYFILE = "keyfile"


@dataclass(frozen=True)
class SettingsKey:
    """A parsed key string.

    ``schema`` and ``key`` are set for the three schema-backed forms; ``path``
    is set for :attr:`KeyKind.DCONF` (the full dconf path), for
    :attr:`KeyKind.GSETTINGS_PATH` (the schema's instance path) and for
    :attr:`KeyKind.KEYFILE` (the root path inside the file), and always ends in
    ``/`` for the latter two. ``file`` is set only for
    :attr:`KeyKind.KEYFILE`: the absolute path of the ``.conf`` the values
    actually live in.
    """

    kind: KeyKind
    schema: str | None = None
    key: str | None = None
    path: str | None = None
    file: str | None = None

    def as_text(self) -> str:
        """Render back to the canonical key string. Round-trips ``parse_key``."""
        if self.kind is KeyKind.GSETTINGS:
            return f"gsettings:{self.schema} {self.key}"
        if self.kind is KeyKind.DCONF:
            return f"dconf:{self.path}"
        if self.kind is KeyKind.KEYFILE:
            return f"keyfile:{self.file}:{self.schema}:{self.path} {self.key}"
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

    if prefix == KeyKind.KEYFILE.value:
        # keyfile:<absolute file>:<schema>:<root path>/ KEY
        # The file path is absolute, so it starts with "/" and may itself
        # contain no colon; splitting from the right on the schema separator
        # would be wrong for a path with a colon in it, and a settings file
        # with a colon in its name is not a thing worth supporting.
        file_path, sep2, tail = rest.partition(":")
        schema, sep3, tail2 = tail.partition(":")
        path, space, key = tail2.partition(" ")
        if (
            not sep2
            or not sep3
            or not space
            or not file_path.startswith("/")
            or not _SCHEMA_RE.match(schema)
            or not _KEY_RE.match(key)
            or not path.startswith("/")
            or not path.endswith("/")
        ):
            raise BackendError(
                BackendErrorKind.OTHER,
                "expected 'keyfile:/absolute/file.conf:SCHEMA:/root/path/ KEY' "
                f"(file must be absolute, path must start and end with '/'), got {text!r}",
                key=text,
            )
        return SettingsKey(
            KeyKind.KEYFILE, schema=schema, key=key, path=path, file=file_path
        )

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
        self._settings: dict[tuple[str, str | None, str | None], tuple[Any, Any]] = {}

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
        cache_key = (parsed.schema or "", parsed.path, parsed.file)
        cached = self._settings.get(cache_key)
        if cached is None:
            schema = self._schema(parsed)
            if parsed.kind is KeyKind.KEYFILE:
                # A ``keyfile:`` key names a real file on disk. This backend
                # exists so that tests reach nothing real, so the values are
                # held in memory at the schema's own path instead — the seam
                # doing what a seam is for. A test that has to prove the file
                # itself is written uses GioBackend and a throwaway file.
                if not schema.get_path():
                    raise BackendError(
                        BackendErrorKind.NO_SCHEMA,
                        f"schema {parsed.schema!r} has no path of its own, so it "
                        "cannot be addressed inside a settings file",
                        key=key,
                    )
                settings = Gio.Settings.new_full(schema, self._make_backend(), None)
            elif parsed.kind is KeyKind.GSETTINGS_PATH:
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


def _gio_settings_for(
    parsed: SettingsKey,
    schema_source: Any | None,
    store: Any | None,
) -> tuple[Any, Any]:
    """``(settings, schema)`` for a parsed key against ``store``.

    ``store`` is the GSettings backend object to bind to: the memory backend
    for tests, or None to mean "whatever the system uses", which is dconf.

    The schema object comes back alongside the settings object on purpose.
    ``Gio.Settings`` exposes no ``get_settings_schema()`` in PyGObject — the
    schema is reachable only through the ``settings-schema`` property — and
    when the source is a per-add-on one, ``SettingsSchemaSource.get_default()``
    cannot find that schema at all.

    Raises:
        BackendError: NO_SCHEMA when the schema is not installed or is
            relocatable and was addressed without a path.
    """
    from gi.repository import Gio

    source = schema_source or Gio.SettingsSchemaSource.get_default()
    if source is None:  # pragma: no cover - a system with no schemas at all
        raise BackendError(
            BackendErrorKind.NO_SCHEMA,
            "no settings descriptions are installed on this system",
            key=parsed.as_text(),
        )
    schema = source.lookup(parsed.schema, True)
    if schema is None:
        raise BackendError(
            BackendErrorKind.NO_SCHEMA,
            f"schema {parsed.schema!r} is not installed",
            key=parsed.as_text(),
        )
    if parsed.kind is KeyKind.KEYFILE:
        # The values live in a file the add-on owns, not in the settings store,
        # so `store` (memory backend or dconf) is not the backend to use here —
        # the whole point of the form is that it is a different store.
        #
        # Two different paths are in play and confusing them silently writes to
        # the wrong group of the file. ``parsed.path`` is the keyfile
        # backend's ROOT: everything below it becomes a group name in the file,
        # so root ``/org/gnome/shell/extensions/`` turns the schema's own path
        # ``/org/gnome/shell/extensions/burn-my-windows-profile/`` into the
        # group ``[burn-my-windows-profile]``. The Settings object itself is
        # then built with NO path, so it uses the schema's — which is exactly
        # what burn-my-windows does (``src/ProfileManager.js``, line 181).
        if not schema.get_path():
            raise BackendError(
                BackendErrorKind.NO_SCHEMA,
                f"schema {parsed.schema!r} has no path of its own, so it cannot be "
                "addressed inside a settings file",
                key=parsed.as_text(),
            )
        keyfile = Gio.keyfile_settings_backend_new(parsed.file, parsed.path, None)
        return Gio.Settings.new_full(schema, keyfile, None), schema
    if parsed.kind is KeyKind.GSETTINGS_PATH:
        return Gio.Settings.new_full(schema, store, parsed.path), schema
    if not schema.get_path():
        raise BackendError(
            BackendErrorKind.NO_SCHEMA,
            f"schema {parsed.schema!r} is relocatable and needs a path — "
            "use the 'gsettings-path:SCHEMA:/path/ KEY' form",
            key=parsed.as_text(),
        )
    return Gio.Settings.new_full(schema, store, None), schema


class GioBackend(SettingsBackend):
    """The primary backend: native ``Gio.Settings`` against the real store.

    Faster than shelling out (no process per key) and, more importantly,
    honest: a missing schema is a missing schema object, not a sentence in
    English that a locale change could rewrite. Values are produced by
    ``GLib.Variant.print_(True)``, which is the same function ``gsettings get``
    prints with, so the two backends agree byte for byte — asserted by a parity
    test here against the memory backend, and again in the sandbox tier against
    a real dconf.

    Raw ``dconf:`` paths are refused: without a schema there is no type to
    parse a value against. :class:`SubprocessBackend` handles those, and
    ``core.backends.AutoBackend`` routes them there automatically.
    """

    def __init__(self, schema_source: Any | None = None) -> None:
        super().__init__(schema_source)
        self._cache: dict[tuple[str, str | None, str | None], tuple[Any, Any]] = {}

    def _resolve(self, key: str) -> tuple[Any, Any, SettingsKey]:
        parsed = parse_key(key)
        if parsed.kind is KeyKind.DCONF:
            raise BackendError(
                BackendErrorKind.OTHER,
                "a location with no settings description cannot be read this way — "
                "it has no type information to check a value against",
                key=key,
            )
        cache_key = (parsed.schema or "", parsed.path, parsed.file)
        entry = self._cache.get(cache_key)
        if entry is None:
            entry = _gio_settings_for(parsed, self.schema_source, None)
            self._cache[cache_key] = entry
        settings, schema = entry
        if not schema.has_key(parsed.key):
            raise BackendError(
                BackendErrorKind.NO_KEY,
                f"schema {parsed.schema!r} has no key {parsed.key!r}",
                key=key,
            )
        return settings, schema, parsed

    def get(self, key: str) -> str:
        settings, _schema, parsed = self._resolve(key)
        return settings.get_value(parsed.key).print_(True)

    def set(self, key: str, value: str) -> None:
        settings, schema, parsed = self._resolve(key)
        from gi.repository import GLib

        expected = schema.get_key(parsed.key).get_value_type()
        try:
            variant = GLib.Variant.parse(expected, value, None, None)
        except GLib.Error as exc:
            raise BackendError(
                BackendErrorKind.OTHER,
                f"{value!r} is not a valid value for {key}: {exc}",
                key=key,
            ) from exc
        if not settings.set_value(parsed.key, variant):
            raise BackendError(
                BackendErrorKind.COMMIT_FAILED,
                f"the settings store refused the change to {key}",
                key=key,
            )
        settings.sync()
        # Exiting without an error is not proof the value landed: dconf can
        # accept a write and fail to commit it. Read it back.
        if settings.get_value(parsed.key) != variant:
            raise BackendError(
                BackendErrorKind.COMMIT_FAILED,
                f"the change to {key} did not stick",
                key=key,
            )

    def reset(self, key: str) -> None:
        settings, _schema, parsed = self._resolve(key)
        settings.reset(parsed.key)
        settings.sync()


class SubprocessBackend(SettingsBackend):
    """The fallback backend: ``gsettings`` and ``dconf`` as child processes.

    Slower and clumsier than :class:`GioBackend`, and kept anyway, because it
    is the code path v1 shipped and proved, and because it is the only backend
    that can address the ``dconf:`` form — a location with no schema, which
    ``Gio.Settings`` has no way to open. It is also the only backend that
    *cannot* address the ``keyfile:`` form, for the mirror-image reason: there
    is no command-line tool that reads an add-on's own settings file. Those
    keys come back as a typed refusal, and ``core.backends.AutoBackend`` sends
    them to :class:`GioBackend`.

    Two rules, both learned the hard way. ``LC_ALL=C`` is pinned on every call,
    because this is the one place in gtheme where a failure has to be
    classified from English text and a translated "No such schema" would be
    classified as OTHER. And a zero exit status is never taken as proof: v1 was
    bitten by ``gsettings set`` exiting 0 while printing "failed to commit
    changes to dconf", so every write is read back.

    Args:
        schema_source: for this backend, optionally a directory path
            containing compiled schemas, passed on as ``--schemadir``. A
            ``Gio.SettingsSchemaSource`` object cannot be handed to a child
            process and is ignored.
    """

    #: Printed on a zero exit that did not persist. The trap v1 fell into.
    _COMMIT_FAILED_TEXT = "failed to commit changes to dconf"

    def _schemadir_args(self) -> list[str]:
        source = self.schema_source
        if isinstance(source, (str, Path)):
            return ["--schemadir", str(source)]
        return []

    def _run(self, args: list[str]) -> tuple[int, str, str]:
        env = {
            **os.environ,
            "LC_ALL": "C",
            "LC_MESSAGES": "C",
            "LANGUAGE": "C",
        }
        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env,
                check=False,
            )
        except FileNotFoundError as exc:
            raise BackendError(
                BackendErrorKind.OTHER,
                f"{args[0]} is not installed on this system",
            ) from exc
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()

    @classmethod
    def _classify(cls, stderr: str, key: str) -> BackendError:
        """Turn a child process's complaint into a typed failure.

        This is the only place in gtheme that reads an error message. It is
        contained here, under a pinned locale, and every caller of this backend
        still verifies the outcome by reading the value back — so a
        misclassification cannot turn a failed write into a reported success.
        """
        lowered = stderr.lower()
        if "no such schema" in lowered:
            kind = BackendErrorKind.NO_SCHEMA
        elif "no such key" in lowered:
            kind = BackendErrorKind.NO_KEY
        elif cls._COMMIT_FAILED_TEXT in lowered:
            kind = BackendErrorKind.COMMIT_FAILED
        else:
            kind = BackendErrorKind.OTHER
        return BackendError(kind, stderr or "the settings command failed", key=key)

    def _argv(self, parsed: SettingsKey, verb: str, value: str | None = None) -> list[str]:
        if parsed.kind is KeyKind.KEYFILE:
            # There is no command-line tool for this. ``gsettings`` and
            # ``dconf`` both talk to the settings store; a ``keyfile:`` key is
            # precisely a setting that is NOT in the settings store. Refusing
            # with a typed error is the honest answer — ``AutoBackend`` reads
            # it and sends the key to Gio, which can open the file.
            raise BackendError(
                BackendErrorKind.OTHER,
                "this setting is kept in the add-on's own file, which the "
                "command-line settings tools cannot open",
                key=parsed.as_text(),
            )
        if parsed.kind is KeyKind.DCONF:
            dconf_verb = {"get": "read", "set": "write", "reset": "reset"}[verb]
            args = ["dconf", dconf_verb, parsed.path or ""]
        else:
            target = (
                f"{parsed.schema}:{parsed.path}"
                if parsed.kind is KeyKind.GSETTINGS_PATH
                else str(parsed.schema)
            )
            args = ["gsettings", *self._schemadir_args(), verb, target, str(parsed.key)]
        if value is not None:
            args.append(value)
        return args

    def get(self, key: str) -> str:
        parsed = parse_key(key)
        code, out, err = self._run(self._argv(parsed, "get"))
        if code != 0:
            raise self._classify(err, key)
        if parsed.kind is KeyKind.DCONF and out == "":
            # dconf prints nothing and exits 0 for a location that has never
            # been written. There is no value to hand back.
            raise BackendError(
                BackendErrorKind.NO_KEY,
                f"{parsed.path} has never been set",
                key=key,
            )
        return out

    def set(self, key: str, value: str) -> None:
        parsed = parse_key(key)
        code, _out, err = self._run(self._argv(parsed, "set", value))
        if code != 0:
            raise self._classify(err, key)
        if self._COMMIT_FAILED_TEXT in err.lower():
            raise BackendError(
                BackendErrorKind.COMMIT_FAILED,
                f"the change to {key} was accepted and then not saved",
                key=key,
            )
        try:
            written = self.get(key)
        except BackendError:  # pragma: no cover - readable if it was writable
            return
        from .gvariant import values_equal

        if not values_equal(written, value):
            raise BackendError(
                BackendErrorKind.COMMIT_FAILED,
                f"the change to {key} did not stick",
                key=key,
            )

    def reset(self, key: str) -> None:
        parsed = parse_key(key)
        code, _out, err = self._run(self._argv(parsed, "reset"))
        if code != 0:
            raise self._classify(err, key)
        if self._COMMIT_FAILED_TEXT in err.lower():
            raise BackendError(
                BackendErrorKind.COMMIT_FAILED,
                f"the change to {key} was accepted and then not saved",
                key=key,
            )
