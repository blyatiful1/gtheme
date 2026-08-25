"""Stand-ins for the network and the desktop, so the ego tests need neither.

``RecordedTransport`` answers out of ``tests/fixtures/ego/`` and raises on a URL
nobody recorded — a test that silently gained a network dependency fails here
rather than passing on a good day and failing in CI.

``FakeShellProxy`` implements the same abstract class the real D-Bus proxy does,
so anything the tests exercise is the code that runs against a live desktop,
with only the eight-method boundary replaced.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from gtheme.ego.client import EgoError, EgoErrorKind
from gtheme.ego.install import CommandResult
from gtheme.ego.shelldbus import ShellError, ShellProxy

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ego"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def fixture_json(name: str) -> Any:
    return json.loads(fixture_bytes(name))


class RecordedTransport:
    """A transport that only knows the URLs somebody recorded.

    Args:
        routes: URL (or URL fragment) -> fixture filename, raw bytes, or an
            :class:`EgoError` to answer with.
        match_prefix: match a route when the request URL starts with it, which
            keeps the tests from restating query strings character by character.
    """

    def __init__(
        self,
        routes: dict[str, str | bytes | EgoError],
        *,
        match_prefix: bool = True,
    ) -> None:
        self.routes = routes
        self.match_prefix = match_prefix
        self.requests: list[str] = []
        self.posts: list[tuple[str, dict[str, Any]]] = []

    def _answer(self, url: str) -> str | bytes | EgoError | None:
        if url in self.routes:
            return self.routes[url]
        if self.match_prefix:
            for route, answer in self.routes.items():
                if url.startswith(route) or route in url:
                    return answer
        return None

    def _deliver(self, url: str, callback: Callable[..., None]) -> None:
        answer = self._answer(url)
        if answer is None:
            raise AssertionError(f"no recorded response for {url!r}")
        if isinstance(answer, EgoError):
            callback(None, answer)
            return
        body = answer if isinstance(answer, bytes) else fixture_bytes(answer)
        callback(body, None)

    def get(self, url: str, callback: Callable[..., None]) -> None:
        self.requests.append(url)
        self._deliver(url, callback)

    def post_json(
        self, url: str, payload: dict[str, Any], callback: Callable[..., None]
    ) -> None:
        self.requests.append(url)
        self.posts.append((url, payload))
        self._deliver(url, callback)


def collect(box: list[Any]) -> Callable[..., None]:
    """A callback that appends ``(value, error)`` to ``box``."""

    def _callback(value: Any, error: Any = None) -> None:
        box.append((value, error))

    return _callback


class FakeShellProxy(ShellProxy):
    """The desktop's add-on service, in a dictionary.

    ``install_remote`` is scripted: each call pops the next scripted answer,
    which is how the tests reproduce a confirmation box that is answered, one
    that is refused, and one that outlives the reply timeout.
    """

    def __init__(
        self,
        extensions: dict[str, dict[str, Any]] | None = None,
        *,
        version: str = "50.4",
    ) -> None:
        self.extensions = dict(extensions or {})
        self.version = version
        self.install_script: list[tuple[str | None, ShellError | None]] = []
        self.install_calls: list[str] = []
        self.enable_calls: list[str] = []
        self.disable_calls: list[str] = []
        self.uninstall_calls: list[str] = []
        self.prefs_calls: list[tuple[str, str]] = []
        self.handlers: dict[int, Callable[[str, dict[str, Any]], None]] = {}
        self._next_token = 1

    # -- ShellProxy ----------------------------------------------------

    def shell_version(self) -> str:
        return self.version

    def list_extensions(self) -> dict[str, dict[str, Any]]:
        return {uuid: dict(info) for uuid, info in self.extensions.items()}

    def get_extension_info(self, uuid: str) -> dict[str, Any]:
        return dict(self.extensions.get(uuid, {}))

    def enable_extension(self, uuid: str) -> bool:
        self.enable_calls.append(uuid)
        info = self.extensions.get(uuid)
        if info is None:
            return False
        info["state"] = 1.0
        info["enabled"] = True
        return True

    def disable_extension(self, uuid: str) -> bool:
        self.disable_calls.append(uuid)
        info = self.extensions.get(uuid)
        if info is None:
            return False
        info["state"] = 2.0
        info["enabled"] = False
        return True

    def uninstall_extension(self, uuid: str) -> bool:
        self.uninstall_calls.append(uuid)
        return self.extensions.pop(uuid, None) is not None

    def open_prefs(self, uuid: str, parent_window: str = "") -> None:
        self.prefs_calls.append((uuid, parent_window))

    def install_remote(
        self, uuid: str, callback: Callable[[str | None, ShellError | None], None]
    ) -> None:
        self.install_calls.append(uuid)
        if not self.install_script:
            raise AssertionError(f"unscripted install of {uuid!r}")
        result, error = self.install_script.pop(0)
        callback(result, error)

    def connect_state_changed(
        self, handler: Callable[[str, dict[str, Any]], None]
    ) -> int:
        token = self._next_token
        self._next_token += 1
        self.handlers[token] = handler
        return token

    def disconnect_state_changed(self, token: int) -> None:
        self.handlers.pop(token, None)

    # -- test helpers --------------------------------------------------

    def emit_state(self, uuid: str, info: dict[str, Any]) -> None:
        """Pretend the desktop announced a state change."""
        if info:
            self.extensions[uuid] = dict(info)
        for handler in list(self.handlers.values()):
            handler(uuid, dict(info))

    def arrive(self, uuid: str, **info: Any) -> None:
        """Make an add-on appear as the desktop's own install would."""
        payload = {"uuid": uuid, "name": uuid, "state": 1.0, "type": 2.0}
        payload.update(info)
        self.emit_state(uuid, payload)


class FakeRunner:
    """A command runner that records instead of running."""

    def __init__(self, result: CommandResult | None = None) -> None:
        self.result = result or CommandResult(0)
        self.calls: list[list[str]] = []

    def run(self, argv: Any) -> CommandResult:
        self.calls.append(list(argv))
        return self.result


def network_error(kind: EgoErrorKind = EgoErrorKind.NETWORK) -> EgoError:
    return EgoError(kind, "the test asked for a failure")
