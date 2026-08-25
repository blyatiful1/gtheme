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
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .loader import load
from .model import Component, Preset

__all__ = [
    "INDEX_URL",
    "INDEX_VERSION",
    "IndexEntry",
    "build_index",
    "entry_for",
    "fetch_index_async",
    "parse_index",
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
