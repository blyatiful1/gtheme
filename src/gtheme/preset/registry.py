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

import hashlib
import json
import os
import shutil
import tomllib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

from pydantic import ValidationError

from ..core.confine import ConfinementError, confine_src, safe_name
from .loader import ORIGIN_FILENAME, bundled_themes_dir, load, user_themes_dir
from .model import PRESET_FILENAME, Component, Preset

__all__ = [
    "INDEX_URL",
    "INDEX_VERSION",
    "LOOK_BASE_URL",
    "MAX_LOOK_FILE_BYTES",
    "ORIGIN_FILENAME",
    "PROVENANCES",
    "PROVENANCE_BUNDLED",
    "PROVENANCE_COMMUNITY",
    "PROVENANCE_USER",
    "IndexEntry",
    "LookFetchError",
    "LookNameTaken",
    "browsable",
    "build_index",
    "bundled_look_names",
    "cached_screenshot",
    "entry_for",
    "fetch_index_async",
    "fetch_look_async",
    "fetch_screenshot_async",
    "install_look",
    "look_url",
    "name_conflict",
    "parse_index",
    "screenshot_cache_dir",
    "screenshot_url",
    "wanted_files",
    "write_index",
]

#: Where the registry lives. Hardcoded in v1 as well; changing it orphans every
#: existing install.
INDEX_URL = "https://raw.githubusercontent.com/blyatiful1/gtheme/main/themes/index.json"

#: Top-level version of the index document itself.
INDEX_VERSION = 2

#: The three answers to "who published this Look". ``bundled`` means it ships
#: inside gtheme itself, ``community`` means somebody else wrote it, ``user``
#: means this machine made it. They are the same three words
#: :class:`gtheme.preset.loader.LoadResult` uses, because a Look does not change
#: its origin by being listed.
PROVENANCE_BUNDLED = "bundled"
PROVENANCE_COMMUNITY = "community"
PROVENANCE_USER = "user"
PROVENANCES = (PROVENANCE_BUNDLED, PROVENANCE_COMMUNITY, PROVENANCE_USER)


@dataclass(frozen=True)
class IndexEntry:
    """One Look as the registry describes it.

    The first six attributes are v1's, unchanged. The rest are v2 additions.

    ``provenance`` defaults to ``"community"`` and not to ``"bundled"``. The
    difference is not cosmetic: "bundled" is gtheme vouching for a Look as its
    own, and an entry that never said where it came from has not earned that.
    Guessing the other way is harmless — a stranger's Look shown as a
    stranger's.
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
    provenance: str = PROVENANCE_COMMUNITY

    @property
    def is_bundled(self) -> bool:
        """True when this entry claims to be one of the Looks gtheme ships."""
        return self.provenance == PROVENANCE_BUNDLED

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


def entry_for(preset: Preset, *, provenance: str) -> IndexEntry:
    """Describe one loaded Look as a registry entry.

    ``provenance`` has no default, on purpose. It used to default to
    ``"bundled"``, so the moment somebody else's Look was merged into the
    ``themes/`` folder the published index called it one of gtheme's own — and
    the Browse tab then badged it "Already on this computer" for everyone.
    Nothing inside a ``theme.toml`` says who published it; the caller is the one
    who knows which folder it came out of, so the caller says.

    Raises:
        ValueError: ``provenance`` is not one of :data:`PROVENANCES`. A typo
            here would be published to every install.
    """
    if provenance not in PROVENANCES:
        raise ValueError(
            f"a Look is bundled, community or user, not {provenance!r} — "
            "say where this one came from"
        )
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


def _declared_provenance(folder: Path, fallback: str) -> str:
    """What a Look folder says about its own origin, if it says anything.

    A Look that was downloaded carries :data:`ORIGIN_FILENAME` naming whoever
    published it. Copying such a folder into the folder being indexed does not
    make it gtheme's, so the marker wins over the caller's answer for the whole
    directory.
    """
    try:
        recorded = json.loads((folder / ORIGIN_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback
    given = recorded.get("provenance") if isinstance(recorded, dict) else None
    return given if given in PROVENANCES else fallback


def build_index(
    themes_dir: str | Path, *, provenance: str = PROVENANCE_BUNDLED
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    """Build the registry document for a folder of Looks.

    A Look that does not load is left out of the index rather than failing the
    build, and the reason comes back as the second return value so the tool
    that writes the file can print it. The reasons stay out of the document
    itself — this file is published, and publishing a broken entry would make
    every client's Browse tab offer a Look nobody can install.

    Args:
        provenance: who published the Looks in this folder. The default is the
            answer for gtheme's own ``themes/`` folder, which is what the build
            tool indexes; anyone publishing an index of Looks they collected
            passes ``"community"``. Either way a folder carrying an origin
            marker keeps the origin the marker records.

    Returns:
        ``(document, [(name, reason), ...])``.
    """
    if provenance not in PROVENANCES:
        raise ValueError(f"a Look is bundled, community or user, not {provenance!r}")
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
        origin = _declared_provenance(child, provenance)
        entries.append(entry_for(result.preset, provenance=origin).to_json())
    return {"version": INDEX_VERSION, "themes": entries}, skipped


def write_index(themes_dir: str | Path, *, provenance: str = PROVENANCE_BUNDLED) -> Path:
    """Write ``index.json`` next to the Looks. Returns the path written."""
    directory = Path(themes_dir)
    document, _skipped = build_index(directory, provenance=provenance)
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
    fetch: Callable[[str, Callable[[bytes | None, str | None], None], int], None] | None = None,
) -> None:
    """Fetch the registry without blocking the interface.

    Calls ``on_done(entries, None)`` on success and ``on_done(None, message)``
    on failure, always on the main loop. libsoup3 is asynchronous natively —
    the status code is checked explicitly because it does not raise on 404, and
    a 404 that is treated as an empty registry looks to the user like nobody
    has ever published a Look.

    Args:
        fetch: how to get one address. The same seam
            :func:`fetch_look_async` takes, and for the same reason: what is
            worth testing here is what happens to the bytes, not whether
            libsoup can open a socket.
    """
    getter = fetch if fetch is not None else _soup_fetch

    def landed(payload: bytes | None, error: str | None) -> None:
        if error is not None or payload is None:
            on_done(None, f"the list of community Looks {error or 'could not be downloaded'}")
            return
        try:
            on_done(parse_index(payload), None)
        except ValueError as exc:
            on_done(None, str(exc))

    getter(url, landed, timeout)


# ---------------------------------------------------------------------------
# what the Browse tab may honestly offer
# ---------------------------------------------------------------------------
#
# Today's published index lists exactly the four Looks that ship inside gtheme,
# so a Browse grid that shows every entry shows the user four Looks they
# already have, each badged "Already on this computer", and clicking one bounces
# back to the tab they came from. That is worse than an empty grid: an empty
# grid says nobody has published a Look yet, which is true, and invites them to
# be the first. So the filter lives here, beside the parsing, rather than in the
# page — the rule is about what the registry contains, and the same rule has to
# hold for anything else that reads it.


def bundled_look_names() -> frozenset[str]:
    """The names of the Looks that ship inside this gtheme.

    Read from the folder rather than written down, so adding a Look to the
    project does not need this list edited. An unreadable folder answers "none
    known" — the cost is a mirrored tile, which is the state we are already in,
    and it is not worth an empty Browse tab.
    """
    try:
        root = bundled_themes_dir()
        return frozenset(
            child.name for child in root.iterdir() if (child / PRESET_FILENAME).is_file()
        )
    except OSError:
        return frozenset()


def browsable(
    entries: Iterable[IndexEntry], *, shipped: Iterable[str] | None = None
) -> list[IndexEntry]:
    """The entries worth showing under "Get more Looks", in registry order.

    Three things are dropped, and each of them would otherwise be a small lie
    told to somebody looking for something new:

    * anything whose provenance is ``bundled`` — it is already installed, it
      came with the app, and offering it as a discovery is a mirror;
    * anything named after a Look this gtheme ships, whatever the index calls
      it, so a stale or mislabelled entry cannot smuggle a mirror back in;
    * anything with no picture. Nobody should be asked to install a desktop
      they cannot see first (DESIGN.md A8), and the same rule already gates
      publishing.

    Args:
        shipped: the bundled names to exclude. Defaults to reading them off
            disk; passing them keeps a caller that already knows off the
            filesystem, and lets a test say what "shipped" means.
    """
    known = frozenset(shipped) if shipped is not None else bundled_look_names()
    return [
        entry
        for entry in entries
        if not entry.is_bundled and entry.name not in known and entry.screenshots
    ]


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


class LookNameTaken(LookFetchError):
    """A Look of that name is already here, and nobody has said to replace it.

    Not a failure — a question. v1 answered it with ``--force`` on a command
    line, which meant that in the app the answer was always "yes, silently":
    downloading a community Look called ``magma`` replaced the user's own
    ``magma``, or shadowed the built-in one of that name, with no dialog and
    nothing in the interface afterwards to say which one was now which.

    Attributes:
        name: the folder name both Looks want.
        held_by: ``"yours"`` when a Look already in the user's own folder would
            be overwritten, ``"built-in"`` when one that ships with gtheme
            would be shadowed. Different sentences, different consequences: the
            first destroys something, the second only hides it.
    """

    def __init__(self, name: str, held_by: str) -> None:
        super().__init__(
            f"a look called {name} is already here"
            + (" and would be replaced" if held_by == "yours" else " and would be hidden")
        )
        self.name = name
        self.held_by = held_by


def name_conflict(name: str, *, into: Path | str | None = None) -> str | None:
    """Who already owns this Look name here, if anyone.

    Asked *before* a download rather than after it, so the question reaches the
    person while cancelling still costs nothing.

    Returns:
        ``"yours"`` if a Look of that name is already in the user's own folder —
        installing would overwrite it. ``"built-in"`` if one of gtheme's own
        Looks has that name — installing would not delete it, but the user's
        folder wins in discovery, so it would disappear from the list.
        ``None`` when the name is free.
    """
    try:
        safe = safe_name(name)
    except ConfinementError:
        return None
    root = Path(into) if into is not None else user_themes_dir()
    if (root / safe / PRESET_FILENAME).is_file():
        return "yours"
    if (bundled_themes_dir() / safe / PRESET_FILENAME).is_file():
        return "built-in"
    return None


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


# ---------------------------------------------------------------------------
# the picture on a Browse tile
# ---------------------------------------------------------------------------
#
# A community tile with no picture is drawn as a neutral grey card, which tells
# a person nothing about the desktop behind it. The picture is already named in
# the index — ``screenshots[0]`` — and already addressable with look_url(); all
# that was missing was fetching it and putting it somewhere a widget can point
# at. Nothing here decodes an image or touches GTK: this layer answers with a
# path on disk, and the page turns that into a texture on the main loop, where
# that work belongs.


#: Which suffixes may name a cached picture. Anything else is stored under a
#: neutral one rather than trusted: the string came out of a document somebody
#: else wrote, and it ends up as a filename here.
_PICTURE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"})

#: The first bytes of the formats GdkTexture can actually open. Checked before
#: anything is cached, so a proxy's HTML error page is refused as what it is
#: instead of being saved as ``something.png`` and failing to load forever.
_PICTURE_MAGIC = (
    b"\x89PNG\r\n\x1a\n",  # PNG
    b"\xff\xd8\xff",  # JPEG
    b"GIF87a",
    b"GIF89a",
)


def screenshot_cache_dir() -> Path:
    """Where fetched Look pictures are kept. ``GTHEME_CACHE_DIR`` overrides.

    Read on every call rather than resolved at import, so a test that sets the
    variable after importing still gets a throwaway directory — the same rule
    the rest of gtheme's path helpers follow.
    """
    override = os.environ.get("GTHEME_CACHE_DIR")
    if override:
        return Path(override) / "looks"
    base = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    return Path(base) / "gtheme" / "looks"


def _is_a_picture(data: bytes) -> bool:
    if data.startswith(_PICTURE_MAGIC):
        return True
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    head = data[:512].lstrip()
    return head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in data[:2048])


def screenshot_url(entry: IndexEntry, *, base_url: str = LOOK_BASE_URL) -> str | None:
    """The address of the picture that represents this Look, if it has one.

    ``None`` rather than an exception when there is no picture or the entry
    points somewhere outside its own folder: a bad picture path is a reason to
    draw the fallback card, never a reason to lose the tile.
    """
    if not entry.screenshots:
        return None
    try:
        return look_url(entry.name, entry.screenshots[0], base_url=base_url)
    except (LookFetchError, ConfinementError):
        return None


def _screenshot_cache_path(entry: IndexEntry, url: str, directory: Path) -> Path:
    suffix = PurePosixPath(entry.screenshots[0]).suffix.lower()
    if suffix not in _PICTURE_SUFFIXES:
        suffix = ".img"
    # The version is part of the key so that a Look publishing a new picture at
    # the same address is not shown last year's desktop forever.
    digest = hashlib.sha256(f"{url}\n{entry.version}".encode()).hexdigest()[:16]
    readable = "".join(c for c in entry.name.lower() if c.isalnum() or c in "-_")[:32] or "look"
    return directory / f"{readable}-{digest}{suffix}"


def cached_screenshot(
    entry: IndexEntry,
    *,
    base_url: str = LOOK_BASE_URL,
    cache_dir: Path | str | None = None,
) -> Path | None:
    """This Look's picture if it is already on disk, without asking anybody.

    The synchronous half, so a page can draw a tile it has drawn before without
    starting a request it will only have to wait for.
    """
    url = screenshot_url(entry, base_url=base_url)
    if url is None:
        return None
    directory = Path(cache_dir) if cache_dir is not None else screenshot_cache_dir()
    path = _screenshot_cache_path(entry, url, directory)
    try:
        return path if path.stat().st_size > 0 else None
    except OSError:
        return None


def fetch_screenshot_async(
    entry: IndexEntry,
    on_done: Callable[[Path | None, str | None], None],
    *,
    base_url: str = LOOK_BASE_URL,
    cache_dir: Path | str | None = None,
    timeout: int = 15,
    fetch: Callable[[str, Callable[[bytes | None, str | None], None], int], None] | None = None,
) -> None:
    """Get this Look's picture onto disk. Never blocks the interface.

    Calls ``on_done(path, None)`` with a file a texture can be loaded from, or
    ``on_done(None, reason)`` when there is no picture to show — always exactly
    once. A picture that cannot be fetched is not an error worth a dialog: the
    caller keeps the palette card it already draws and the tile stays usable,
    which is why the reason comes back as a sentence rather than an exception.

    A picture already in the cache answers immediately, without a request.

    Args:
        fetch: how to get one address — the same seam the registry and Look
            downloads take, and the reason this whole module is testable with
            no network. The default talks to libsoup3 asynchronously.
    """
    label = entry.title or entry.name
    url = screenshot_url(entry, base_url=base_url)
    if url is None:
        on_done(None, f"{label} has no picture to show")
        return

    directory = Path(cache_dir) if cache_dir is not None else screenshot_cache_dir()
    path = _screenshot_cache_path(entry, url, directory)
    try:
        if path.stat().st_size > 0:
            on_done(path, None)
            return
    except OSError:
        pass

    def landed(payload: bytes | None, error: str | None) -> None:
        if error is not None or payload is None:
            on_done(None, f"{label}'s picture {error or 'could not be downloaded'}")
            return
        if len(payload) > MAX_LOOK_FILE_BYTES:
            on_done(None, f"{label}'s picture is far larger than a picture should be")
            return
        if not _is_a_picture(payload):
            on_done(None, f"{label}'s picture is not an image gtheme can show")
            return
        partial = path.with_name(f".{path.name}.part")
        try:
            directory.mkdir(parents=True, exist_ok=True)
            partial.write_bytes(payload)
            os.replace(partial, path)
        except OSError as exc:
            # Written to a hidden sibling and renamed, so a tile never points
            # at a file that is still being written.
            partial.unlink(missing_ok=True)
            on_done(None, f"{label}'s picture could not be saved: {exc}")
            return
        on_done(path, None)

    getter = fetch if fetch is not None else _soup_fetch
    getter(url, landed, timeout)


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
    replace: bool = False,
) -> Path:
    """Write a downloaded Look into place. The pure half, and the careful one.

    Args:
        entry: the registry entry it came from — its name is the folder name.
        files: ``{relative path: contents}``. ``theme.toml`` must be among them.
        into: the Looks folder to install under. Defaults to the user's.
        replace: proceed even though a Look of that name is already here. This
            is v1's ``--force``, made explicit and made *asked for*: the check
            lives here rather than in the page, so no caller can install over
            somebody's Look by forgetting to look first.

    Returns:
        The installed Look's folder.

    Raises:
        LookNameTaken: a Look of that name is already here and ``replace`` is
            false. Nothing is written, and the caller is expected to ask.
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
    if name.startswith("."):
        # A dot-leading folder is hidden, and discover() skips those so an
        # abandoned staging folder is never mistaken for a Look. A downloaded
        # Look called ".magma" would install and then be invisible.
        raise LookFetchError("that look's name cannot start with a dot")

    root = Path(into) if into is not None else user_themes_dir()
    held_by = name_conflict(name, into=root)
    if held_by is not None and not replace:
        raise LookNameTaken(name, held_by)

    root.mkdir(parents=True, exist_ok=True)
    destination = root / name
    staging = root / f".{name}.downloading"
    superseded = root / f".{name}.replaced"

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
        # Replacing moves the old copy aside rather than deleting it first: a
        # failure between the delete and the rename used to lose both the Look
        # that was there and the one that was just validated.
        if destination.exists():
            shutil.rmtree(superseded, ignore_errors=True)
            os.replace(destination, superseded)
        try:
            os.replace(staging, destination)
        except BaseException:
            if superseded.exists() and not destination.exists():
                os.replace(superseded, destination)
            raise
        shutil.rmtree(superseded, ignore_errors=True)
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
    replace: bool = False,
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
        replace: install even though a Look of that name is already here. The
            caller is expected to have asked first — :func:`name_conflict`
            answers before a byte is fetched, which is when cancelling is still
            free.
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
            path = install_look(entry, collected, into=into, replace=replace)
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
