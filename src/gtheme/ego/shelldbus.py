"""The desktop's own add-on service, behind an interface tests can replace.

Everything gtheme knows about the add-ons that are actually running comes from
one D-Bus interface, ``org.gnome.Shell.Extensions``. This module wraps it and —
importantly — wraps it behind :class:`ShellProxy`, an abstract class with eight
methods. The unit tier injects a fake; no test in the suite has ever opened a
bus connection, which is what makes it safe to run the suite on the machine
whose desktop is being customised.

Four things about this interface are surprising enough to be worth stating:

* **Numbers arrive as doubles.** ``state`` comes back as ``1.0`` and ``version``
  as ``72.0``. Comparing ``state == 1`` happens to work in Python and comparing
  ``version == 72`` does too, but anything that formats them shows "72.0" to a
  user. They are cast on the way in, once, here.
* **An unknown add-on is an empty dictionary, not an error.** ``GetExtensionInfo``
  answers ``{}`` for a uuid the desktop has never scanned. That empty dictionary
  is the single most load-bearing signal in the whole install path — see
  :meth:`ShellExtensions.knows`.
* **``EnableExtension`` returns False rather than raising** when the desktop has
  never scanned the add-on. That is not an error to report; it is the "you have
  to log out first" case, and :class:`EnableResult` names it.
* **``ReloadExtension`` is a stub** that answers ``NotSupported``. There is no
  way to make a running desktop re-read its add-on folder. This is the whole
  reason the install path looks the way it does; the experiment that pinned it
  is in ``research/runtime-load-experiment.md``.

State is kept live from the ``ExtensionStateChanged`` signal. Nothing here
polls.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "BUS_NAME",
    "INTERFACE",
    "OBJECT_PATH",
    "EnableResult",
    "ExtensionState",
    "ExtensionType",
    "GDBusShellProxy",
    "InstalledExtension",
    "ShellError",
    "ShellErrorKind",
    "ShellExtensions",
    "ShellProxy",
    "UninstallResult",
]

BUS_NAME = "org.gnome.Shell"
OBJECT_PATH = "/org/gnome/Shell"
INTERFACE = "org.gnome.Shell.Extensions"

#: GDBus's "wait forever". ``-1`` means *default* (25 seconds), not infinite —
#: a distinction that costs an afternoon exactly once. The install call is
#: gated on a person clicking a dialog, so it needs the real thing.
G_MAXINT = 2147483647


class ExtensionState(enum.IntEnum):
    """The states an add-on can be in, as the desktop reports them."""

    ACTIVE = 1
    INACTIVE = 2
    ERROR = 3
    OUT_OF_DATE = 4
    DOWNLOADING = 5
    INITIALIZED = 6
    DEACTIVATING = 7
    ACTIVATING = 8
    UNINSTALLED = 99

    @classmethod
    def from_dbus(cls, value: Any) -> ExtensionState | None:
        """Cast a D-Bus double to a state, or None if it is not one we know."""
        try:
            return cls(int(value))
        except (TypeError, ValueError):
            return None


class ExtensionType(enum.IntEnum):
    """Where an add-on is installed. Only per-user ones can be removed."""

    SYSTEM = 1
    PER_USER = 2


class ShellErrorKind(enum.Enum):
    """Why a call to the desktop failed. Closed set."""

    #: The desktop is not answering — not GNOME, or not running.
    UNAVAILABLE = "unavailable"
    #: Installing add-ons is switched off system-wide.
    NOT_ALLOWED = "not-allowed"
    #: The library could not be reached, or the package would not download.
    DOWNLOAD_FAILED = "download-failed"
    #: The package downloaded but could not be unpacked.
    EXTRACT_FAILED = "extract-failed"
    #: It installed but would not start.
    ENABLE_FAILED = "enable-failed"
    #: The call has not been answered yet. NOT a failure — see install.py.
    NO_REPLY = "no-reply"
    #: Anything else.
    OTHER = "other"


_ERROR_NAMES = {
    "org.gnome.Shell.Extensions.Error.InfoDownloadFailed": ShellErrorKind.DOWNLOAD_FAILED,
    "org.gnome.Shell.Extensions.Error.DownloadFailed": ShellErrorKind.DOWNLOAD_FAILED,
    "org.gnome.Shell.Extensions.Error.ExtractFailed": ShellErrorKind.EXTRACT_FAILED,
    "org.gnome.Shell.Extensions.Error.EnableFailed": ShellErrorKind.ENABLE_FAILED,
    "org.gnome.Shell.Extensions.Error.NotAllowed": ShellErrorKind.NOT_ALLOWED,
    "org.freedesktop.DBus.Error.NoReply": ShellErrorKind.NO_REPLY,
    "org.freedesktop.DBus.Error.ServiceUnknown": ShellErrorKind.UNAVAILABLE,
    "org.freedesktop.DBus.Error.NameHasNoOwner": ShellErrorKind.UNAVAILABLE,
}


class ShellError(Exception):
    """A typed failure from the desktop's add-on service."""

    def __init__(self, kind: ShellErrorKind, message: str, *, uuid: str | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.uuid = uuid

    @classmethod
    def from_dbus_name(cls, name: str, message: str, *, uuid: str | None = None) -> ShellError:
        """Map a D-Bus error name onto the closed set. Never matches on text."""
        return cls(_ERROR_NAMES.get(name, ShellErrorKind.OTHER), message, uuid=uuid)


class EnableResult(enum.Enum):
    """What happened when gtheme tried to switch an add-on on."""

    #: It is on now, and saying so is truthful.
    ENABLED_NOW = "enabled-now"
    #: It is installed and switched on, but the running desktop has never
    #: scanned it, so nothing happens until the user logs out and back in.
    NEEDS_RELOGIN = "needs-relogin"
    #: The desktop knows it and still refused.
    FAILED = "failed"


class UninstallResult(enum.Enum):
    """What happened when gtheme tried to remove an add-on."""

    REMOVED = "removed"
    #: Installed for everyone on the machine; gtheme cannot remove it.
    SYSTEM_WIDE = "system-wide"
    #: The desktop has never heard of it.
    NOT_KNOWN = "not-known"


@dataclass(frozen=True)
class InstalledExtension:
    """One add-on as the running desktop describes it."""

    uuid: str
    name: str = ""
    description: str = ""
    state: ExtensionState | None = None
    type: ExtensionType | None = None
    version: int | None = None
    version_name: str | None = None
    path: str = ""
    error: str = ""
    has_prefs: bool = False
    has_update: bool = False
    can_change: bool = True
    enabled: bool = False
    settings_schema: str | None = None
    #: Marker written by extensions.gnome.org's packager. Its presence means
    #: the whole-number version is comparable with the library's, which is what
    #: the update check needs; add-ons installed from source often carry only a
    #: name-shaped version and must be left out of that comparison.
    from_library: bool = False

    @classmethod
    def from_info(cls, uuid: str, info: dict[str, Any]) -> InstalledExtension | None:
        """Parse one info dictionary. Returns None for the empty-dict answer.

        An empty dictionary means the desktop has never scanned this add-on —
        it is not an error and not a state, and conflating it with
        ``UNINSTALLED`` would make the installer lie about what happens next.
        """
        if not info:
            return None
        version = info.get("version")
        return cls(
            uuid=uuid,
            name=str(info.get("name") or uuid),
            description=str(info.get("description") or ""),
            state=ExtensionState.from_dbus(info.get("state")),
            type=_as_type(info.get("type")),
            version=int(version) if isinstance(version, (int, float)) else None,
            version_name=str(info["version-name"]) if info.get("version-name") else None,
            path=str(info.get("path") or ""),
            error=str(info.get("error") or ""),
            has_prefs=bool(info.get("hasPrefs")),
            has_update=bool(info.get("hasUpdate")),
            can_change=bool(info.get("canChange", True)),
            enabled=bool(info.get("enabled")),
            settings_schema=str(info["settings-schema"]) if info.get("settings-schema") else None,
            from_library=bool(info.get("_generated")),
        )

    @property
    def is_running(self) -> bool:
        return self.state is ExtensionState.ACTIVE

    @property
    def display_version(self) -> str:
        """What to show a person. The name-shaped version wins when there is one."""
        if self.version_name:
            return self.version_name
        return str(self.version) if self.version is not None else ""


def _as_type(value: Any) -> ExtensionType | None:
    try:
        return ExtensionType(int(value))
    except (TypeError, ValueError):
        return None


class ShellProxy(ABC):
    """The desktop's add-on service. Abstract so the tests can stand in for it."""

    @abstractmethod
    def shell_version(self) -> str:
        """``"50.4"``. The source of truth for which builds are compatible."""

    @abstractmethod
    def list_extensions(self) -> dict[str, dict[str, Any]]:
        """Every add-on the desktop scanned at start-up, uuid -> info."""

    @abstractmethod
    def get_extension_info(self, uuid: str) -> dict[str, Any]:
        """Info for one add-on. ``{}`` when the desktop has never scanned it."""

    @abstractmethod
    def enable_extension(self, uuid: str) -> bool:
        """Switch it on. False when the desktop does not know it."""

    @abstractmethod
    def disable_extension(self, uuid: str) -> bool:
        """Switch it off. False when the desktop does not know it."""

    @abstractmethod
    def uninstall_extension(self, uuid: str) -> bool:
        """Remove it. False for unknown add-ons and for machine-wide ones."""

    @abstractmethod
    def open_prefs(self, uuid: str, parent_window: str = "") -> None:
        """Open the add-on author's own settings window."""

    @abstractmethod
    def install_remote(
        self,
        uuid: str,
        callback: Callable[[str | None, ShellError | None], None],
    ) -> None:
        """Ask the desktop to download and start an add-on from the library.

        Answers only after the person has clicked the desktop's own dialog, so
        implementations must use an effectively infinite timeout. The reply is
        ``"successful"`` or ``"cancelled"``.
        """

    @abstractmethod
    def connect_state_changed(
        self, handler: Callable[[str, dict[str, Any]], None]
    ) -> int:
        """Subscribe to add-on state changes. Returns an unsubscribe token."""

    @abstractmethod
    def disconnect_state_changed(self, token: int) -> None:
        """Stop listening."""


class GDBusShellProxy(ShellProxy):
    """The real thing, over the session bus.

    ``gi`` is imported inside the methods, so importing ``gtheme.ego`` on a
    machine without PyGObject still works — the rescue path depends on that.
    """

    def __init__(self, proxy: Any | None = None) -> None:
        self._proxy = proxy
        self._handlers: dict[int, int] = {}
        self._next_token = 1

    def _gi(self) -> tuple[Any, Any]:
        from gi.repository import Gio, GLib

        return Gio, GLib

    def proxy(self) -> Any:
        """The ``Gio.DBusProxy``, built on first use.

        Raises:
            ShellError: UNAVAILABLE when there is no session bus or no desktop
                answering on it.
        """
        if self._proxy is None:
            Gio, GLib = self._gi()
            try:
                self._proxy = Gio.DBusProxy.new_for_bus_sync(
                    Gio.BusType.SESSION,
                    Gio.DBusProxyFlags.NONE,
                    None,
                    BUS_NAME,
                    OBJECT_PATH,
                    INTERFACE,
                    None,
                )
            except GLib.Error as exc:  # pragma: no cover - needs a live bus
                raise ShellError(ShellErrorKind.UNAVAILABLE, str(exc)) from exc
        return self._proxy

    def _call(self, method: str, params: Any = None, *, uuid: str | None = None) -> Any:
        Gio, GLib = self._gi()
        try:
            return self.proxy().call_sync(
                method, params, Gio.DBusCallFlags.NONE, -1, None
            )
        except GLib.Error as exc:  # pragma: no cover - needs a live bus
            name = Gio.DBusError.get_remote_error(exc) or ""
            raise ShellError.from_dbus_name(name, str(exc), uuid=uuid) from exc

    def shell_version(self) -> str:  # pragma: no cover - needs a live bus
        value = self.proxy().get_cached_property("ShellVersion")
        return str(value.get_string()) if value is not None else ""

    def list_extensions(self) -> dict[str, dict[str, Any]]:  # pragma: no cover
        return dict(self._call("ListExtensions").unpack()[0])

    def get_extension_info(self, uuid: str) -> dict[str, Any]:  # pragma: no cover
        _Gio, GLib = self._gi()
        result = self._call("GetExtensionInfo", GLib.Variant("(s)", (uuid,)), uuid=uuid)
        return dict(result.unpack()[0])

    def _bool_call(self, method: str, uuid: str) -> bool:  # pragma: no cover
        _Gio, GLib = self._gi()
        return bool(self._call(method, GLib.Variant("(s)", (uuid,)), uuid=uuid).unpack()[0])

    def enable_extension(self, uuid: str) -> bool:  # pragma: no cover
        return self._bool_call("EnableExtension", uuid)

    def disable_extension(self, uuid: str) -> bool:  # pragma: no cover
        return self._bool_call("DisableExtension", uuid)

    def uninstall_extension(self, uuid: str) -> bool:  # pragma: no cover
        return self._bool_call("UninstallExtension", uuid)

    def open_prefs(self, uuid: str, parent_window: str = "") -> None:  # pragma: no cover
        _Gio, GLib = self._gi()
        self._call(
            "OpenExtensionPrefs",
            GLib.Variant("(ssa{sv})", (uuid, parent_window, {})),
            uuid=uuid,
        )

    def install_remote(
        self,
        uuid: str,
        callback: Callable[[str | None, ShellError | None], None],
    ) -> None:  # pragma: no cover - needs a live bus
        Gio, GLib = self._gi()

        def _done(proxy: Any, result: Any, _data: Any = None) -> None:
            try:
                reply = proxy.call_finish(result)
            except GLib.Error as exc:
                name = Gio.DBusError.get_remote_error(exc) or ""
                callback(None, ShellError.from_dbus_name(name, str(exc), uuid=uuid))
                return
            callback(str(reply.unpack()[0]), None)

        self.proxy().call(
            "InstallRemoteExtension",
            GLib.Variant("(s)", (uuid,)),
            Gio.DBusCallFlags.NONE,
            G_MAXINT,
            None,
            _done,
            None,
        )

    def connect_state_changed(
        self, handler: Callable[[str, dict[str, Any]], None]
    ) -> int:  # pragma: no cover - needs a live bus
        def _on_signal(_proxy: Any, _sender: str, signal: str, params: Any) -> None:
            if signal != "ExtensionStateChanged":
                return
            uuid, info = params.unpack()
            handler(str(uuid), dict(info))

        signal_id = self.proxy().connect("g-signal", _on_signal)
        token = self._next_token
        self._next_token += 1
        self._handlers[token] = signal_id
        return token

    def disconnect_state_changed(self, token: int) -> None:  # pragma: no cover
        signal_id = self._handlers.pop(token, None)
        if signal_id is not None:
            self.proxy().disconnect(signal_id)


class ShellExtensions:
    """What is installed and what is running, kept live.

    Reads the full list once, then follows the ``ExtensionStateChanged`` signal.
    Polling this interface would be both wasteful and wrong: the signal carries
    the same payload as ``GetExtensionInfo``, so following it is strictly more
    information than asking repeatedly.

    Args:
        proxy: the desktop service, real or injected.
    """

    def __init__(self, proxy: ShellProxy) -> None:
        self.proxy = proxy
        self._extensions: dict[str, InstalledExtension] = {}
        self._listeners: list[Callable[[InstalledExtension], None]] = []
        self._token: int | None = None
        self._loaded = False

    # -- lifecycle -----------------------------------------------------

    def load(self) -> dict[str, InstalledExtension]:
        """Read the full list once and start following changes."""
        raw = self.proxy.list_extensions()
        self._extensions = {}
        for uuid, info in raw.items():
            parsed = InstalledExtension.from_info(str(uuid), dict(info))
            if parsed is not None:
                self._extensions[str(uuid)] = parsed
        if self._token is None:
            self._token = self.proxy.connect_state_changed(self._on_state_changed)
        self._loaded = True
        return dict(self._extensions)

    def close(self) -> None:
        """Stop following changes."""
        if self._token is not None:
            self.proxy.disconnect_state_changed(self._token)
            self._token = None

    def connect(self, listener: Callable[[InstalledExtension], None]) -> None:
        """Call ``listener(extension)`` whenever one changes state."""
        self._listeners.append(listener)

    def disconnect(self, listener: Callable[[InstalledExtension], None]) -> bool:
        """Stop calling one listener. Returns whether it was listening.

        The counterpart to :meth:`connect`, and it exists because this object
        can outlive the page that subscribed to it: the window owns one of
        these and lends it to the Add-ons page, so a page going away has to be
        able to take its own callback with it rather than relying on the
        object being thrown away.
        """
        if listener in self._listeners:
            self._listeners.remove(listener)
            return True
        return False

    def _on_state_changed(self, uuid: str, info: dict[str, Any]) -> None:
        parsed = InstalledExtension.from_info(uuid, info)
        if parsed is None:
            self._extensions.pop(uuid, None)
            return
        if parsed.state is ExtensionState.UNINSTALLED:
            self._extensions.pop(uuid, None)
        else:
            self._extensions[uuid] = parsed
        for listener in list(self._listeners):
            listener(parsed)

    # -- queries -------------------------------------------------------

    @property
    def all(self) -> dict[str, InstalledExtension]:
        return dict(self._extensions)

    def get(self, uuid: str) -> InstalledExtension | None:
        """What is known about one add-on, asking the desktop if need be."""
        known = self._extensions.get(uuid)
        if known is not None:
            return known
        parsed = InstalledExtension.from_info(uuid, self.proxy.get_extension_info(uuid))
        if parsed is not None:
            self._extensions[uuid] = parsed
        return parsed

    def knows(self, uuid: str) -> bool:
        """Whether the running desktop has this add-on loaded at all.

        This is the question that decides what the installer is allowed to
        promise. The desktop scans its add-on folders exactly once, at start-up;
        a folder that appeared afterwards is invisible to it, with no error and
        no signal of any kind. So: a real answer here means gtheme can switch
        the add-on on right now and say so. An empty answer means it cannot,
        whatever the folder on disk says, and the honest words are "after you
        log out and back in".
        """
        return self.get(uuid) is not None

    def running(self) -> list[InstalledExtension]:
        return [ext for ext in self._extensions.values() if ext.is_running]

    def from_library(self) -> dict[str, int]:
        """``uuid -> whole-number version`` for add-ons the library packaged.

        This is exactly the map the update check sends. Add-ons installed from
        source are left out: their version numbers are not comparable with the
        library's, and asking about them produces confident nonsense.
        """
        return {
            uuid: ext.version
            for uuid, ext in self._extensions.items()
            if ext.from_library and ext.version is not None
        }

    # -- actions -------------------------------------------------------

    def enable(self, uuid: str) -> EnableResult:
        """Switch an add-on on, and be honest about whether that worked.

        The desktop answers False for an add-on it never scanned. That is the
        common case right after an install and it is not a failure, so it gets
        its own result rather than an error.
        """
        if not self.knows(uuid):
            return EnableResult.NEEDS_RELOGIN
        if self.proxy.enable_extension(uuid):
            return EnableResult.ENABLED_NOW
        return EnableResult.FAILED

    def disable(self, uuid: str) -> bool:
        """Switch an add-on off. This always works for a loaded add-on."""
        return self.proxy.disable_extension(uuid)

    def uninstall(self, uuid: str) -> UninstallResult:
        """Remove an add-on, distinguishing the two ways it can refuse.

        The desktop returns a bare False both for an add-on it does not know
        and for one installed for every user on the machine. Those need
        different sentences, so the local record decides which happened.
        """
        known = self.get(uuid)
        if known is None:
            return UninstallResult.NOT_KNOWN
        if known.type is ExtensionType.SYSTEM:
            return UninstallResult.SYSTEM_WIDE
        if self.proxy.uninstall_extension(uuid):
            self._extensions.pop(uuid, None)
            return UninstallResult.REMOVED
        return UninstallResult.SYSTEM_WIDE


@dataclass
class StateWatcher:
    """A pre-armed wait for one add-on to start running.

    Armed *before* the install call is issued, never after: the desktop can
    finish installing and emit the signal while the call itself is still
    unanswered, and a watcher armed afterwards misses it entirely.
    """

    uuid: str
    shell: ShellExtensions
    on_active: Callable[[InstalledExtension], None] | None = None
    seen: list[ExtensionState] = field(default_factory=list)
    _token: int | None = None

    def arm(self) -> None:
        if self._token is None:
            self._token = self.shell.proxy.connect_state_changed(self._on_signal)

    def disarm(self) -> None:
        if self._token is not None:
            self.shell.proxy.disconnect_state_changed(self._token)
            self._token = None

    def _on_signal(self, uuid: str, info: dict[str, Any]) -> None:
        if uuid != self.uuid:
            return
        parsed = InstalledExtension.from_info(uuid, info)
        if parsed is None or parsed.state is None:
            return
        self.seen.append(parsed.state)
        if parsed.state is ExtensionState.ACTIVE and self.on_active is not None:
            self.on_active(parsed)

    @property
    def became_active(self) -> bool:
        return ExtensionState.ACTIVE in self.seen
