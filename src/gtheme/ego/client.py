"""Talking to extensions.gnome.org, without ever blocking the window.

Everything here is asynchronous and callback-shaped, and everything runs on the
main loop. That is not a stylistic choice: libsoup 3's own async API is
main-loop based, the results end up in widgets, and a worker thread would buy
nothing but the obligation to marshal back. Threads in gtheme are for CPU work
(thumbnails), never for HTTP.

The network itself sits behind :class:`Transport`, which has exactly two
methods. The unit tests inject a transport that answers out of recorded JSON in
``tests/fixtures/ego/`` and fails loudly if asked for a URL nobody recorded, so
the suite never touches the network and never depends on the site being up.

Four site behaviours are handled here rather than left to callers, because each
one has a wrong-looking-but-plausible alternative:

* **Pagination is driven by ``numpages``.** ``total`` is the number of items on
  the page you are holding. Paging until ``len(extensions) < n_per_page``
  happens to work and breaks on the day a page comes back short.
* **``n_per_page`` is capped at 25** server-side. Asking for 200 gets 25 and a
  page count computed as if you had asked for 25, so the client asks for 25.
* **Compatibility is decided locally** from ``shell_version_map``. See
  :meth:`ExtensionRecord.supports`.
* **A 200 is not success.** ``msg.get_status()`` is checked on every response;
  libsoup does not raise for 4xx, and a 404 body parsed as JSON is a confusing
  crash three frames away from the cause.
"""

from __future__ import annotations

import enum
import hashlib
import json
import os
import time
import urllib.parse
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from .models import BASE_URL, Comment, ExtensionRecord, QueryPage, Rating, shell_major

__all__ = [
    "DEFAULT_TTL",
    "MAX_N_PER_PAGE",
    "SORTS",
    "DiskCache",
    "EgoClient",
    "EgoError",
    "EgoErrorKind",
    "SoupTransport",
    "Transport",
    "cache_dir",
    "download_url",
]

#: The server's hard cap. Asking for more is silently ignored.
MAX_N_PER_PAGE = 25

#: Sort orders the site understands. An unknown value is *accepted silently*
#: and behaves like the default, so a typo never surfaces as an error — which
#: is exactly why this tuple exists and is validated against.
SORTS = ("downloads", "popularity", "recent", "name", "relevance")

#: How long a cached listing stays fresh. Long enough that paging back and
#: forth is instant, short enough that a day-old star rating is not shown.
DEFAULT_TTL = 60 * 60  # one hour


class EgoErrorKind(enum.Enum):
    """Why a call failed. Closed set; the UI branches on it."""

    #: No answer at all — offline, DNS, TLS, timeout.
    NETWORK = "network"
    #: An answer with a status that is not 200.
    HTTP_STATUS = "http-status"
    #: A 200 whose body is not what the endpoint promises.
    MALFORMED = "malformed"
    #: The add-on is not on extensions.gnome.org (404 on a detail lookup).
    NOT_FOUND = "not-found"


class EgoError(Exception):
    """A typed failure from the site.

    Attributes:
        kind: which of the four closed failure modes this is.
        status: the HTTP status, when there was one.
        url: what was being fetched.
    """

    def __init__(
        self,
        kind: EgoErrorKind,
        message: str,
        *,
        status: int | None = None,
        url: str | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.url = url

    def user_text(self) -> str:
        """One sentence a first-time user can act on."""
        if self.kind is EgoErrorKind.NETWORK:
            return "Could not reach the add-on library. Check your internet connection."
        if self.kind is EgoErrorKind.NOT_FOUND:
            return "That add-on is not in the online library any more."
        return "The add-on library sent back something gtheme did not understand."


#: What a transport hands back: raw bytes, or a typed failure. Exactly one of
#: the two is ever set.
BytesCallback = Callable[[bytes | None, EgoError | None], None]


class Transport(Protocol):
    """The two HTTP verbs gtheme needs. Injectable, so tests never go online."""

    def get(self, url: str, callback: BytesCallback) -> None:
        """Fetch ``url``; call back with the body or a typed error."""

    def post_json(self, url: str, payload: dict[str, Any], callback: BytesCallback) -> None:
        """POST a JSON body to ``url``; call back with the body or an error."""


class SoupTransport:
    """The real transport: libsoup 3, asynchronous, on the main loop.

    ``gi`` is imported inside the methods so that importing this module — and
    therefore anything under ``gtheme.ego`` — works on a machine with no
    PyGObject, which is what lets the unit tier run anywhere.
    """

    def __init__(self, user_agent: str = "gtheme") -> None:
        self._user_agent = user_agent
        self._session: Any | None = None

    def _soup(self) -> tuple[Any, Any]:
        from gi.repository import GLib, Soup

        return GLib, Soup

    def _get_session(self) -> Any:
        if self._session is None:
            _GLib, Soup = self._soup()
            self._session = Soup.Session(user_agent=self._user_agent)
        return self._session

    def _send(self, message: Any, url: str, callback: BytesCallback) -> None:
        GLib, _Soup = self._soup()
        session = self._get_session()

        def _done(session_: Any, result: Any, _data: Any = None) -> None:
            try:
                body = session_.send_and_read_finish(result)
            except GLib.Error as exc:
                callback(None, EgoError(EgoErrorKind.NETWORK, str(exc), url=url))
                return
            # libsoup does not raise on 4xx/5xx. Checking the status is the
            # only thing standing between a 404 HTML page and json.loads.
            status = int(message.get_status())
            if status != 200:
                kind = (
                    EgoErrorKind.NOT_FOUND if status == 404 else EgoErrorKind.HTTP_STATUS
                )
                callback(None, EgoError(kind, f"HTTP {status} for {url}", status=status, url=url))
                return
            callback(bytes(body.get_data() or b""), None)

        session.send_and_read_async(message, GLib.PRIORITY_DEFAULT, None, _done, None)

    def get(self, url: str, callback: BytesCallback) -> None:
        _GLib, Soup = self._soup()
        self._send(Soup.Message.new("GET", url), url, callback)

    def post_json(self, url: str, payload: dict[str, Any], callback: BytesCallback) -> None:
        GLib, Soup = self._soup()
        message = Soup.Message.new("POST", url)
        body = json.dumps(payload).encode("utf-8")
        message.set_request_body_from_bytes("application/json", GLib.Bytes.new(body))
        self._send(message, url, callback)


# -- cache -----------------------------------------------------------------


def cache_dir() -> Path:
    """Where fetched listings are kept. ``GTHEME_CACHE_DIR`` overrides.

    Read on every call rather than resolved at import, so a test that sets the
    variable after importing still gets a throwaway directory.
    """
    override = os.environ.get("GTHEME_CACHE_DIR")
    if override:
        return Path(override)
    base = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    return Path(base) / "gtheme" / "ego"


class DiskCache:
    """A time-limited cache of response bodies, keyed by URL.

    Deliberately dumb: one file per URL, the file's own mtime is the timestamp,
    a corrupt or unreadable entry is a miss. A cache that can fail a request is
    worse than no cache, so every operation here swallows its own errors.
    """

    def __init__(self, directory: str | Path | None = None, ttl: float = DEFAULT_TTL) -> None:
        self._directory = Path(directory) if directory is not None else None
        self.ttl = ttl

    @property
    def directory(self) -> Path:
        return self._directory if self._directory is not None else cache_dir()

    @staticmethod
    def key_for(url: str, payload: dict[str, Any] | None = None) -> str:
        """A filename-safe key. The URL already carries search, sort and page."""
        material = url
        if payload is not None:
            material += "\n" + json.dumps(payload, sort_keys=True)
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]

    def get(self, key: str) -> bytes | None:
        path = self.directory / f"{key}.body"
        try:
            age = time.time() - path.stat().st_mtime
            if age > self.ttl:
                return None
            return path.read_bytes()
        except OSError:
            return None

    def put(self, key: str, body: bytes) -> None:
        path = self.directory / f"{key}.body"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(body)
            os.replace(tmp, path)
        except OSError:
            return

    def clear(self) -> None:
        try:
            for entry in self.directory.glob("*.body"):
                entry.unlink(missing_ok=True)
        except OSError:
            return


def download_url(uuid: str, version_tag: int) -> str:
    """The zip URL for one exact release.

    By version tag, never by desktop version: the tag pins the build the user
    was shown, whereas ``?shell_version=`` lets the server pick again — and it
    picks fuzzily enough to hand back a build for a different desktop entirely.
    Two redirects follow; the transport handles them.
    """
    return f"{BASE_URL}/download-extension/{uuid}.shell-extension.zip?version_tag={version_tag}"


# -- the client ------------------------------------------------------------


class EgoClient:
    """The add-on library, as five methods.

    Args:
        transport: how requests are made. Tests inject a recorded one.
        shell_version: the desktop version, from the ``ShellVersion`` property
            (``"50.4"``). Only its major part is ever sent.
        cache: a :class:`DiskCache`, or None to fetch every time.
    """

    def __init__(
        self,
        transport: Transport,
        shell_version: str,
        cache: DiskCache | None = None,
    ) -> None:
        self.transport = transport
        self.shell_version = shell_version
        self.cache = cache

    @property
    def shell_major(self) -> str:
        return shell_major(self.shell_version)

    # -- plumbing ------------------------------------------------------

    def _fetch_json(
        self,
        url: str,
        callback: Callable[[Any | None, EgoError | None], None],
        *,
        use_cache: bool = True,
    ) -> None:
        """GET ``url``, hand back parsed JSON, serving from cache when fresh."""
        key = DiskCache.key_for(url)
        if use_cache and self.cache is not None:
            cached = self.cache.get(key)
            if cached is not None:
                self._decode(cached, url, callback, store=None, key=None)
                return

        def _got(body: bytes | None, error: EgoError | None) -> None:
            if error is not None or body is None:
                callback(None, error or EgoError(EgoErrorKind.NETWORK, "no response", url=url))
                return
            self._decode(
                body,
                url,
                callback,
                store=self.cache if use_cache else None,
                key=key,
            )

        self.transport.get(url, _got)

    @staticmethod
    def _decode(
        body: bytes,
        url: str,
        callback: Callable[[Any | None, EgoError | None], None],
        *,
        store: DiskCache | None,
        key: str | None,
    ) -> None:
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            callback(None, EgoError(EgoErrorKind.MALFORMED, f"{url}: {exc}", url=url))
            return
        if store is not None and key is not None:
            store.put(key, body)
        callback(parsed, None)

    # -- browse and search ---------------------------------------------

    def query_url(
        self,
        *,
        search: str | None = None,
        sort: str = "downloads",
        page: int = 1,
        n_per_page: int = MAX_N_PER_PAGE,
    ) -> str:
        """Build a listing URL. Public so the cache key is inspectable."""
        if sort not in SORTS:
            raise ValueError(f"unknown sort {sort!r}; the site accepts {SORTS}")
        params: dict[str, str] = {
            "shell_version": self.shell_major,
            "sort": sort,
            "page": str(max(1, int(page))),
            "n_per_page": str(min(MAX_N_PER_PAGE, max(1, int(n_per_page)))),
        }
        if search:
            params["search"] = search
        return f"{BASE_URL}/extension-query/?{urllib.parse.urlencode(params)}"

    def query(
        self,
        callback: Callable[[QueryPage | None, EgoError | None], None],
        *,
        search: str | None = None,
        sort: str = "downloads",
        page: int = 1,
        n_per_page: int = MAX_N_PER_PAGE,
    ) -> None:
        """One page of results. Paging is driven by :attr:`QueryPage.numpages`.

        A page past the end is a 200 with an empty list and ``numpages`` 0 — not
        a 404 — so "no more results" and "no results at all" look the same on
        the wire and are told apart by the page number that was asked for.
        """
        capped = min(MAX_N_PER_PAGE, max(1, int(n_per_page)))
        url = self.query_url(search=search, sort=sort, page=page, n_per_page=capped)

        def _parsed(raw: Any | None, error: EgoError | None) -> None:
            if error is not None:
                callback(None, error)
                return
            if not isinstance(raw, dict):
                callback(None, EgoError(EgoErrorKind.MALFORMED, f"{url}: not an object", url=url))
                return
            callback(QueryPage.from_json(raw, page=max(1, int(page)), n_per_page=capped), None)

        self._fetch_json(url, _parsed)

    # -- one add-on ----------------------------------------------------

    def info(
        self,
        uuid: str,
        callback: Callable[[ExtensionRecord | None, EgoError | None], None],
    ) -> None:
        """Detail for one add-on, including the exact release to download.

        The ``shell_version`` parameter is what makes ``version``,
        ``version_tag`` and ``download_url`` appear at all. It does **not** make
        the answer trustworthy: check :meth:`ExtensionRecord.supports` before
        offering anything, because this endpoint never reports incompatibility.
        """
        params = urllib.parse.urlencode({"uuid": uuid, "shell_version": self.shell_major})
        url = f"{BASE_URL}/extension-info/?{params}"

        def _parsed(raw: Any | None, error: EgoError | None) -> None:
            if error is not None:
                callback(None, error)
                return
            try:
                record = ExtensionRecord.from_json(raw if isinstance(raw, dict) else {})
            except ValueError as exc:
                callback(None, EgoError(EgoErrorKind.MALFORMED, f"{url}: {exc}", url=url))
                return
            callback(record, None)

        self._fetch_json(url, _parsed)

    def rating(
        self,
        uuid: str,
        callback: Callable[[Rating | None, EgoError | None], None],
    ) -> None:
        """Stars and dates. Only ``/api/v1/`` has them, and it cannot search."""
        url = f"{BASE_URL}/api/v1/extensions/{urllib.parse.quote(uuid)}/"

        def _parsed(raw: Any | None, error: EgoError | None) -> None:
            if error is not None:
                callback(None, error)
                return
            if not isinstance(raw, dict):
                callback(None, EgoError(EgoErrorKind.MALFORMED, f"{url}: not an object", url=url))
                return
            callback(Rating.from_json(raw), None)

        self._fetch_json(url, _parsed)

    def comments(
        self,
        pk: int,
        callback: Callable[[tuple[Comment, ...] | None, EgoError | None], None],
        *,
        all_of_them: bool = False,
    ) -> None:
        """Reviews for one add-on, newest first.

        Takes the numeric id, not the uuid. Five most recent by default; the
        full set can be hundreds of kilobytes, which is why it is opt-in. The
        app is read-only here — posting a review needs a website login, so the
        UI links out instead of pretending it can.
        """
        params: dict[str, str] = {"pk": str(int(pk))}
        if all_of_them:
            params["all"] = "true"
        url = f"{BASE_URL}/comments/all/?{urllib.parse.urlencode(params)}"

        def _parsed(raw: Any | None, error: EgoError | None) -> None:
            if error is not None:
                callback(None, error)
                return
            if not isinstance(raw, list):
                callback(None, EgoError(EgoErrorKind.MALFORMED, f"{url}: not a list", url=url))
                return
            callback(tuple(Comment.from_json(entry) for entry in raw if isinstance(entry, dict)), None)

        self._fetch_json(url, _parsed)

    # -- bytes ---------------------------------------------------------

    def download(
        self,
        uuid: str,
        version_tag: int,
        callback: BytesCallback,
    ) -> None:
        """Fetch one release's zip. Never cached; it is verified, not trusted.

        The body is checked for the zip magic number before it is handed on. A
        redirect that lands on an HTML error page is a 200 full of ``<html>``,
        and unzipping that produces a baffling error much later.
        """
        url = download_url(uuid, version_tag)

        def _got(body: bytes | None, error: EgoError | None) -> None:
            if error is not None or body is None:
                callback(None, error or EgoError(EgoErrorKind.NETWORK, "no response", url=url))
                return
            if not body.startswith(b"PK\x03\x04"):
                callback(
                    None,
                    EgoError(
                        EgoErrorKind.MALFORMED,
                        f"{url} did not return an add-on package",
                        url=url,
                    ),
                )
                return
            callback(body, None)

        self.transport.get(url, _got)

    # -- updates -------------------------------------------------------

    def update_info(
        self,
        installed: dict[str, int],
        callback: Callable[[dict[str, str] | None, EgoError | None], None],
        *,
        disable_version_validation: bool = False,
    ) -> None:
        """Ask about many add-ons at once: which have a different release.

        The desktop version goes in the **query string** and the installed
        versions go in the **body**. Swapping them is a 400, and that is the
        usual reason this endpoint gets written off as broken. GET is 405.

        Up-to-date add-ons are omitted from the answer entirely. Values are
        ``"upgrade"``, ``"downgrade"`` (both mean "there is a different build")
        and ``"blacklist"`` (the add-on was withdrawn — say that, do not offer
        an update).
        """
        params = urllib.parse.urlencode(
            {
                "shell_version": self.shell_version,
                "disable_version_validation": "true" if disable_version_validation else "false",
            }
        )
        url = f"{BASE_URL}/update-info/?{params}"
        payload = {uuid: {"version": int(version)} for uuid, version in installed.items()}
        if not payload:
            callback({}, None)
            return

        def _got(body: bytes | None, error: EgoError | None) -> None:
            if error is not None or body is None:
                callback(None, error or EgoError(EgoErrorKind.NETWORK, "no response", url=url))
                return
            try:
                parsed = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                callback(None, EgoError(EgoErrorKind.MALFORMED, f"{url}: {exc}", url=url))
                return
            if not isinstance(parsed, dict):
                callback(None, EgoError(EgoErrorKind.MALFORMED, f"{url}: not an object", url=url))
                return
            callback({str(k): str(v) for k, v in parsed.items()}, None)

        self.transport.post_json(url, payload, _got)
