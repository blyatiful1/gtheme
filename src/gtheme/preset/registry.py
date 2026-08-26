"""The community registry — ``themes/index.json``.

There is no server. The registry is one JSON file in the gtheme repository,
fetched raw from GitHub, and that is the entire community-sharing story: no
account, no upload endpoint, no moderation queue, nothing to keep running in
five years' time. The URL is load-bearing, which is why the repo is not being
renamed and why ``themes/`` is still called ``themes/`` (DESIGN.md A1/A2).

The v2 index is a *superset* of v1's: the six fields v1 clients read are still
there and still mean the same thing, with four added — ``format``,
``screenshots``, ``min_shell`` and ``provenance``. A v1 client will read a v2
index and see six familiar fields per entry; it will refuse the top-level
``version = 2``, which is the documented break (DESIGN.md F17).

Fetching is asynchronous on the main loop via libsoup3 — never a thread, never
a blocking read. Parsing is a pure function so the interesting half is testable
without a network.
"""

from __future__ import annotations

import json
import os
import shutil
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

from pydantic import ValidationError

from ..core.confine import ConfinementError, confine_src, safe_name
from .loader import ORIGIN_FILENAME, load, user_themes_dir
from .model import PRESET_FILENAME, Component, Preset

__all__ = [
    "INDEX_URL",
    "INDEX_VERSION",
    "LOOK_BASE_URL",
    "MAX_LOOK_FILE_BYTES",
    "ORIGIN_FILENAME",
    "IndexEntry",
    "LookFetchError",
    "build_index",
    "entry_for",
    "fetch_index_async",
    "fetch_look_async",
    "install_look",
    "look_url",
    "parse_index",
    "wanted_files",
    "write_index",
]

#: Where the registry lives. Hardcoded in v1 as well; changing it orphans every
#: existing install.
INDEX_URL = "https://raw.githubusercontent.com/blyatiful1/gtheme/main/themes/index.json"

#: Top-level version of the index document itself.
INDEX_VERSION = 2


@dataclass(frozen=True)
class IndexEntry:
    """One Look as the registry describes it.

    The first six attributes are v1's, unchanged. The rest are v2 additions.
    """

    name: str
    title: str
    description: str
    author: str
    version: str
    components: list[str] = field(default_factory=list)
    format: int = 2
    screenshots: list[str] = field(default_factory=list)
    min_shell: str | None = None
    provenance: str = "bundled"

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "author": self.author,
            "version": self.version,
            "components": list(self.components),
            "format": self.format,
            "screenshots": list(self.screenshots),
            "min_shell": self.min_shell,
            "provenance": self.provenance,
        }


def _components(preset: Preset) -> list[str]:
    """Which parts of the desktop this Look touches, in registry order.

    Derived from the closed component registry rather than from free text, so
    two Looks that change the same things describe themselves the same way.
    """
    seen = {str(s.component) for s in preset.settings}
    if preset.extensions.enable:
        seen.add(str(Component.ADDONS))
    if any("backgrounds" in entry.dest for entry in preset.files):
        seen.add(str(Component.WALLPAPER))
    order = [str(c) for c in Component]
    return [c for c in order if c in seen]


def entry_for(preset: Preset, *, provenance: str = "bundled") -> IndexEntry:
    """Describe one loaded Look as a registry entry."""
    meta = preset.meta
    return IndexEntry(
        name=meta.name,
        title=meta.title or meta.name,
        description=meta.description,
        author=meta.author,
        version=meta.version,
        components=_components(preset),
        format=preset.format,
        screenshots=list(meta.screenshots),
        min_shell=meta.min_shell,
        provenance=provenance,
    )


def build_index(themes_dir: str | Path) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    """Build the registry document for a folder of Looks.

    A Look that does not load is left out of the index rather than failing the
    build, and the reason comes back as the second return value so the tool
    that writes the file can print it. The reasons stay out of the document
    itself — this file is published, and publishing a broken entry would make
    every client's Browse tab offer a Look nobody can install.

    Returns:
        ``(document, [(name, reason), ...])``.
    """
    directory = Path(themes_dir)
    entries: list[dict[str, Any]] = []
    skipped: list[tuple[str, str]] = []
    for child in sorted(directory.iterdir()):
        if not (child / "theme.toml").is_file():
            continue
        result = load(child)
        if result.preset is None:
            skipped.append((child.name, "; ".join(result.errors)))
            continue
        entries.append(entry_for(result.preset).to_json())
    return {"version": INDEX_VERSION, "themes": entries}, skipped


def write_index(themes_dir: str | Path) -> Path:
    """Write ``index.json`` next to the Looks. Returns the path written."""
    directory = Path(themes_dir)
    document, _skipped = build_index(directory)
    out = directory / "index.json"
    out.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def parse_index(text: str | bytes) -> list[IndexEntry]:
    """Read a fetched registry document.

    Unknown fields are ignored and a missing optional field is defaulted, so a
    newer index published by a newer gtheme does not break an older one. An
    entry missing a *required* field is dropped rather than crashing the Browse
    tab; one malformed Look must not hide the other twenty.

    Raises:
        ValueError: the document is not a registry at all.
    """
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"the list of community Looks could not be read: {exc}") from exc
    if not isinstance(document, dict) or not isinstance(document.get("themes"), list):
        raise ValueError("the list of community Looks is not in the expected format")

    entries: list[IndexEntry] = []
    for raw in document["themes"]:
        if not isinstance(raw, dict):
            continue
        try:
            entries.append(
                IndexEntry(
                    name=str(raw["name"]),
                    title=str(raw.get("title") or raw["name"]),
                    description=str(raw.get("description", "")),
                    author=str(raw.get("author", "")),
                    version=str(raw.get("version", "")),
                    components=[str(c) for c in raw.get("components", [])],
                    format=int(raw.get("format", 1)),
                    screenshots=[str(s) for s in raw.get("screenshots", [])],
                    min_shell=str(raw["min_shell"]) if raw.get("min_shell") else None,
                    provenance=str(raw.get("provenance", "community")),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return entries


def fetch_index_async(
    on_done: Callable[[list[IndexEntry] | None, str | None], None],
    *,
    url: str = INDEX_URL,
    timeout: int = 10,
) -> None:
    """Fetch the registry without blocking the interface.

    Calls ``on_done(entries, None)`` on success and ``on_done(None, message)``
    on failure, always on the main loop. libsoup3 is asynchronous natively —
    the status code is checked explicitly because it does not raise on 404, and
    a 404 that is treated as an empty registry looks to the user like nobody
    has ever published a Look.
    """
    try:
        import gi

        gi.require_version("Soup", "3.0")
        from gi.repository import GLib, Soup
    except (ImportError, ValueError):  # pragma: no cover - needs PyGObject
        on_done(None, "gtheme cannot reach the internet on this system")
        return

    session = Soup.Session()
    session.set_timeout(timeout)
    message = Soup.Message.new("GET", url)

    def _finished(source: Any, result: Any) -> None:
        try:
            body = source.send_and_read_finish(result)
        except GLib.Error as exc:
            on_done(None, f"the list of community Looks could not be downloaded: {exc.message}")
            return
        status = message.get_status()
        if int(status) != 200:
            on_done(None, f"the list of community Looks is not available right now ({status})")
            return
        try:
            on_done(parse_index(bytes(body.get_data() or b"")), None)
        except ValueError as exc:
            on_done(None, str(exc))

    session.send_and_read_async(message, GLib.PRIORITY_DEFAULT, None, _finished)


# ---------------------------------------------------------------------------
# downloading a community Look
# ---------------------------------------------------------------------------
#
# v1 downloaded a Look by cloning the whole repository with git and copying one
# folder out of it. That is not available here — there is no git in a Flatpak
# and no reason to fetch forty megabytes to get one Look — so the transport is
# the one this module already uses for the registry, and what is ported from v1
# is the part that mattered: validate the payload, then move it, atomically,
# through a staging folder that is never the destination.
#
# The rule that a Look cannot run code is not enforced here by inspection. It
# is enforced by the format: `Preset` forbids unknown fields, so a v1 file with
# a `[hooks]` section does not validate as v2 and there is no path by which a
# downloaded Look can smuggle a command onto somebody's machine. Validating
# before installing is what turns that from a property of the format into a
# property of the download.

#: Where a Look's own files live, beside the registry that lists them. Derived
#: from :data:`INDEX_URL` rather than written out again: two spellings of one
#: location is one of them going stale.
LOOK_BASE_URL = INDEX_URL.rsplit("/", 1)[0]

#: A downloaded Look is one folder. Nothing may reach outside it, and nothing
#: may be enormous: a Look is settings text and a picture.
MAX_LOOK_FILE_BYTES = 40 * 1024 * 1024


class LookFetchError(Exception):
    """A Look could not be downloaded or could not be trusted."""


def look_url(name: str, relative: str, *, base_url: str = LOOK_BASE_URL) -> str:
    """The address of one file inside one published Look.

    The name is checked before it becomes part of a URL *and* before it becomes
    part of a path, because they are different checks and only one of them is
    :func:`~gtheme.core.confine.safe_name`'s job.
    """
    safe = safe_name(name)
    parts = [quote(part, safe="") for part in PurePosixPath(relative).parts]
    if not parts or ".." in PurePosixPath(relative).parts:
        raise LookFetchError(f"this look asked for a file outside itself: {relative}")
    return f"{base_url.rstrip('/')}/{quote(safe, safe='')}/{'/'.join(parts)}"


def wanted_files(preset: Preset) -> list[str]:
    """Everything a Look's own description says it carries, in fetch order.

    Only what the Look declares. There is no directory listing and there is
    deliberately no attempt to make one: a Look is a declaration, and anything
    the declaration does not mention is not part of it.
    """
    seen: dict[str, None] = {}
    for entry in preset.files:
        seen.setdefault(entry.src, None)
    for shot in preset.meta.screenshots:
        seen.setdefault(shot, None)
    return list(seen)


def install_look(
    entry: IndexEntry,
    files: Mapping[str, bytes],
    *,
    into: Path | str | None = None,
) -> Path:
    """Write a downloaded Look into place. The pure half, and the careful one.

    Args:
        entry: the registry entry it came from — its name is the folder name.
        files: ``{relative path: contents}``. ``theme.toml`` must be among them.
        into: the Looks folder to install under. Defaults to the user's.

    Returns:
        The installed Look's folder.

    Raises:
        LookFetchError: the name is unusable, a file would land outside the
            Look's own folder, or the Look does not validate. Nothing is
            written in any of those cases — validation happens against the
            staging folder, and the staging folder is discarded.

    Four things are ported from v1's installer, each of them a bug it had
    already paid for: the name is checked before it becomes a path component;
    the source and destination are never allowed to overlap; the copy is
    assembled in a hidden sibling of the destination, on the same filesystem,
    so the last step is one atomic rename; and the staging folder is cleaned up
    from a ``BaseException`` handler, so an interrupt cannot strand it.
    """
    try:
        name = safe_name(entry.name)
    except ConfinementError as exc:
        raise LookFetchError(f"that look's name cannot be used as a folder: {exc}") from exc

    root = Path(into) if into is not None else user_themes_dir()
    root.mkdir(parents=True, exist_ok=True)
    destination = root / name
    staging = root / f".{name}.downloading"

    if PRESET_FILENAME not in files:
        raise LookFetchError("that look has no description file, so there is nothing to install")

    shutil.rmtree(staging, ignore_errors=True)
    try:
        staging.mkdir(parents=True)
        for relative, payload in files.items():
            target = _confined(relative, staging)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)

        # Validate the folder, not the bytes: this is the same loader the app
        # uses, so a Look that installs is a Look that opens.
        result = load(staging)
        if result.preset is None or result.errors:
            problems = "; ".join(result.errors) or "it could not be read"
            raise LookFetchError(f"that look could not be used: {problems}")

        (staging / ORIGIN_FILENAME).write_text(
            json.dumps(
                {"provenance": "community", "name": entry.name, "author": entry.author},
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        shutil.rmtree(destination, ignore_errors=True)
        os.replace(staging, destination)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return destination


def _confined(relative: str, staging: Path) -> Path:
    """Where one downloaded file may be written, or an honest refusal.

    Every one of these strings came off the internet inside a document somebody
    else wrote. ``files/wallpaper/first-light.png`` is the benign shape;
    ``../../.bashrc`` is the shape being refused.
    """
    if PurePosixPath(relative).is_absolute() or ".." in PurePosixPath(relative).parts:
        raise LookFetchError(f"that look tried to write outside its own folder: {relative}")
    try:
        return confine_src(relative, staging)
    except ConfinementError as exc:
        raise LookFetchError(str(exc)) from exc


def _soup_fetch(url: str, on_done: Callable[[bytes | None, str | None], None], timeout: int) -> None:
    """Fetch one address. The only place in this module that touches a socket.

    Separated from :func:`fetch_look_async` so the interesting half — which
    files to ask for, what to refuse, where they land — is testable with no
    network, which is the same split the registry fetch already uses.
    """
    try:
        import gi

        gi.require_version("Soup", "3.0")
        from gi.repository import GLib, Soup
    except (ImportError, ValueError):  # pragma: no cover - needs PyGObject
        on_done(None, "gtheme cannot reach the internet on this system")
        return

    session = Soup.Session()
    session.set_timeout(timeout)
    message = Soup.Message.new("GET", url)

    def _finished(source: Any, result: Any) -> None:
        # ``session`` is referenced here on purpose: the closure is what keeps
        # it alive for exactly as long as the request it belongs to. A Look is
        # several requests one after another, and a session collected between
        # two of them is how the second one fails.
        keep_alive = session
        assert keep_alive is not None
        try:
            body = source.send_and_read_finish(result)
        except GLib.Error as exc:
            on_done(None, f"it could not be downloaded: {exc.message}")
            return
        status = int(message.get_status())
        if status != 200:
            on_done(None, f"it is not available right now ({status})")
            return
        data = bytes(body.get_data() or b"")
        if len(data) > MAX_LOOK_FILE_BYTES:
            on_done(None, "one of its files is far larger than a look should be")
            return
        on_done(data, None)

    session.send_and_read_async(message, GLib.PRIORITY_DEFAULT, None, _finished)


def fetch_look_async(
    entry: IndexEntry,
    on_done: Callable[[Path | None, str | None], None],
    *,
    base_url: str = LOOK_BASE_URL,
    into: Path | str | None = None,
    timeout: int = 30,
    fetch: Callable[[str, Callable[[bytes | None, str | None], None], int], None] | None = None,
) -> None:
    """Download one community Look and install it. Never blocks the interface.

    Calls ``on_done(path, None)`` when the Look is installed and
    ``on_done(None, message)`` when it is not, always on the main loop, and
    always exactly once.

    The description file is fetched first and validated before anything else is
    asked for, because it is the description that says what else there is. A
    Look that declares a file outside its own folder is refused at that point,
    before a single byte of it has been requested.

    Args:
        fetch: how to get one address. The seam the tests use; the default
            talks to libsoup3 asynchronously, never a thread — HTTP on a thread
            is how a slow network becomes a frozen window.
    """
    getter = fetch if fetch is not None else _soup_fetch
    collected: dict[str, bytes] = {}

    def fail(reason: str) -> None:
        on_done(None, f"{entry.title or entry.name} could not be downloaded — {reason}")

    def finish() -> None:
        try:
            path = install_look(entry, collected, into=into)
        except LookFetchError as exc:
            fail(str(exc))
        except OSError as exc:
            fail(f"it could not be saved: {exc}")
        else:
            on_done(path, None)

    def next_file(remaining: list[str]) -> None:
        if not remaining:
            finish()
            return
        relative, rest = remaining[0], remaining[1:]
        try:
            url = look_url(entry.name, relative, base_url=base_url)
        except (LookFetchError, ConfinementError) as exc:
            fail(str(exc))
            return

        def landed(payload: bytes | None, error: str | None) -> None:
            if error is not None or payload is None:
                # One missing picture must not lose the whole Look: the
                # description is the only file that is not optional, and it has
                # already arrived by the time this runs.
                collected.setdefault(relative, b"")
                del collected[relative]
                next_file(rest)
                return
            collected[relative] = payload
            next_file(rest)

        getter(url, landed, timeout)

    def described(payload: bytes | None, error: str | None) -> None:
        if error is not None or payload is None:
            fail(error or "it could not be downloaded")
            return
        collected[PRESET_FILENAME] = payload
        try:
            preset = Preset.model_validate(tomllib.loads(payload.decode("utf-8")))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            fail(f"its description file could not be read: {exc}")
            return
        except ValidationError:
            fail("its description file is not one this version of gtheme understands")
            return
        wanted = wanted_files(preset)
        for relative in wanted:
            if PurePosixPath(relative).is_absolute() or ".." in PurePosixPath(relative).parts:
                fail(f"it asks for a file outside its own folder: {relative}")
                return
        next_file(wanted)

    try:
        described_url = look_url(entry.name, PRESET_FILENAME, base_url=base_url)
    except (LookFetchError, ConfinementError) as exc:
        fail(str(exc))
        return
    getter(described_url, described, timeout)
