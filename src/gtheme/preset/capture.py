"""Reading the current desktop back out as a Look.

Reading the settings back is one mechanism (:func:`capture_settings`), used
here for **"Save my current desktop as a Look"**: the same read, curated, with
a scan for anything the user would not want to publish.

Saved moments are *not* here. This module once wrote them too, in its own
format (a ``theme.toml`` in a ``YYYYmmdd-HHMMSS`` folder) into the same
directory :mod:`gtheme.core.restorepoints` writes its own (a
``restore-point.json`` in a ``YYYY-mm-ddTHH-MM-SS`` one) — two formats, two
readers, and two pruners in one folder, each invisible to the other. The pruner
was the dangerous half: this one deleted the oldest folders by name whatever
they were, where the engine's own refuses to touch a moment somebody asked for
by hand or the "Before gtheme" one that cannot be recreated. So saved moments
are the engine's, there is one store, and the wrapper that used to offer a
"Look view" of one lived on here for a while with no caller at all — a feature
in the docstring and nowhere in the app. It is gone; anything wanting a Look
view of a saved moment should build it where the moments are.

The share scan is a real safety feature, not decoration. A captured desktop
carries absolute paths that contain the user's login name, and occasionally a
key or token in some extension's settings. Those are replaced with the
``{{ home }}`` placeholder or held back entirely, and either way the user is
told which values were changed before anything is written.

The scan covers the **files** the Look carries as well as its values, which is
the half that was missing. A bundled file is somebody's real configuration, and
a rendered one is full of this computer's home folder: ``magma`` ships a
slideshow whose template writes ``{{ home }}/.local/share/backgrounds/…`` nine
times, so the file sitting on the desktop that gets saved has the login name in
it nine times. Copied byte for byte, that is a Look which publishes a name and
points at folders the recipient does not have. So the copy inside the Look is
read back, every mention of this home folder is turned into ``{{ home }}``
again, the entry is marked ``template`` so the other machine fills in its own,
and the rewrite is said out loud like every other one. Files that are not text
— a picture, a font — are copied unchanged; there is nothing in them to read.

**A saved desktop is a whole Look, not a wallpaper.** For a long time it was
the wallpaper and nothing else: no ``[[files]]`` beyond the picture and no
``[palette]`` at all, while the four Looks in this repository ship eighteen to
twenty files each. Saving your own desktop and then using it therefore left the
Terminal page permanently blank — it reads its colours from ``[palette]`` — and
threw away every file gtheme had written to produce the desktop being saved
(persona-report 2.7). So the capture now also carries:

* **the files gtheme wrote**, taken from the ownership ledger, which is the one
  record of what this app put on this desktop, and
* **a palette**, from the Look in use if there is one and from whatever the
  terminal adapters can read back if there is not.

Neither is always possible, and the half that matters is saying so. Anything
left out is named in :attr:`CaptureResult.omissions` — a structured list, one
entry per thing, so that a dialog can group and render it rather than parse
sentences. Two rules hold there. A Look may not carry a file from
:mod:`gtheme.core.policy`'s refused tier, so a destination that would arrange
for a program to run is left out rather than quietly published — a captured
Look has to obey the same policy a downloaded one does, or the sentence written
into its header ("it changes settings only; it cannot run programs") is not
true. And nothing is omitted silently: every drop produces an entry.
"""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Literal

from ..core.confine import ConfinementError, confine_src
from ..core.ledger import current_look, read_ledger
from ..core.paths import dest_root
from ..core.policy import file_verdict, setting_verdict
from ..core.settings_backend import BackendError, BackendErrorKind, SettingsBackend
from ..terminal.model import Palette
from .emit import dumps_preset
from .loader import discover, load
from .model import Component, ExtensionsBlock, FileEntry, Meta, Preset, SettingEntry

__all__ = [
    "PRIVATE_SETTING_REASON",
    "REFUSED_SETTING_REASON",
    "SECRET_HINTS",
    "CaptureResult",
    "Omission",
    "capture_settings",
    "capture_share",
]

#: Substrings that make a setting too risky to publish. Deliberately broad:
#: a false positive costs one line in a Look, a false negative costs a secret.
SECRET_HINTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api-key",
    "apikey",
    "api_key",
    "credential",
    "private-key",
    "privatekey",
    "certificate",
    "cookie",
    "session-id",
    "auth",
)

#: The shape a login folder has on an ordinary distribution. This was once the
#: *whole* home-folder scan, and that was L3: on a Silverblue machine the home
#: folder is ``/var/home/you``, a relocated ``$HOME`` or one on a mounted
#: volume is somewhere else again, and none of them match — so every captured
#: path went out with the login name still in it, pointing at a folder the
#: person receiving the Look does not have. It stays as the second half of the
#: scan, because it is the only thing that finds *somebody else's* home folder
#: in a captured value.
_HOME_SHAPE = r"/home/[^/'\"\s]+"

#: Why a setting did not travel. Written once and used in three places — the
#: skip reason, the omission, and the line the user reads — because the line the
#: user reads is chosen by matching on it.
REFUSED_SETTING_REASON = "a Look is not allowed to change this"
PRIVATE_SETTING_REASON = "it may contain something private, like a password"

#: ``(reason, one, many)`` for every reason a setting is left out. Settings are
#: counted rather than listed in the sentences a person reads: a setting's name
#: is its schema and key (``org.gnome.desktop.lockdown disable-show-password``),
#: which is an address for a programmer and nothing anybody saving their desktop
#: can act on — and one of them is left out of *every* save, so that line was
#: shown to everyone, every time, twice. The keys themselves stay in
#: :attr:`CaptureResult.omissions` for a dialog that wants to show them.
_SETTING_NOTES: tuple[tuple[str, str, str], ...] = (
    (
        PRIVATE_SETTING_REASON,
        "one setting was left out because it may contain something private, "
        "like a password",
        "{count} settings were left out because they may contain something private, "
        "like a password",
    ),
    (
        REFUSED_SETTING_REASON,
        "one setting was left out because a Look is not allowed to change it",
        "{count} settings were left out because a Look is not allowed to change them",
    ),
)

_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
_WALLPAPER_KEY = "gsettings:org.gnome.desktop.background picture-uri"
_WALLPAPER_DARK_KEY = "gsettings:org.gnome.desktop.background picture-uri-dark"

#: The sixteen ANSI colours in the order every palette lists them, bright ones
#: being the same eight again. What a Look calls them is read back by
#: ``gtheme.ui.pages.terminal``, which accepts ``ansi_red`` and ``red`` alike;
#: a capture writes the ``ansi_`` spelling, which is the unambiguous one.
_ANSI_NAMES = (
    "black",
    "red",
    "green",
    "yellow",
    "blue",
    "magenta",
    "cyan",
    "white",
)


def _home_re() -> re.Pattern[str]:
    """What counts as this computer's home folder inside a captured value.

    The real destination root first, the ``/home/<name>`` shape second, so that
    a home folder which *is* under ``/home`` is replaced whole rather than down
    to its first two components, and one that is not is replaced at all.

    Built per call rather than once at import: the root is an environment
    override (:func:`gtheme.core.paths.dest_root`), and a pattern frozen at
    import time would answer for whatever the root was then.
    """
    root = str(dest_root()).rstrip("/")
    shapes = [_HOME_SHAPE]
    if root and root != "/":
        shapes.insert(0, re.escape(root))
    return re.compile("|".join(shapes))


@dataclass(frozen=True)
class Omission:
    """One thing the capture could not carry into the Look.

    Structured rather than prose so that whatever renders it can group by
    :attr:`kind` and show a path as a path. :meth:`sentence` is there for a
    caller that only wants a line.

    Attributes:
        kind: ``"file"``, ``"setting"``, ``"palette"`` or ``"picture"``.
        what: the thing itself, named — a destination, a setting key, or a
            short phrase for something that has no name of its own.
        reason: one clause saying why it was left out, in the words of somebody
            who has never heard of a shell.
    """

    kind: Literal["file", "setting", "palette", "picture"]
    what: str
    reason: str

    def sentence(self) -> str:
        """The whole omission as one line."""
        return f"{self.what}: {self.reason}"


@dataclass
class CaptureResult:
    """What a capture produced.

    Attributes:
        preset: the Look describing the captured desktop.
        path: where it was written, when it was written.
        skipped: ``(key, reason)`` for every setting that could not be read —
            almost always an add-on that is not installed, which is not an
            error and must not read like one.
        warnings: sentences for the user, including every value the share scan
            changed or withheld.
        omissions: everything the Look does *not* carry that a person might
            reasonably have expected it to, one entry each. Every omission is
            also *accounted for* in :attr:`warnings`, so the dialog that exists
            today says something — settings by the count and the reason rather
            than by name, since a setting's name is a schema path. A dialog that
            wants to lay them out properly should render this list, which is the
            one place the keys themselves survive.
    """

    preset: Preset
    path: Path | None = None
    skipped: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    omissions: list[Omission] = field(default_factory=list)


def _omission_notes(omissions: Sequence[Omission]) -> list[str]:
    """The things left out, as lines for the dialog the user actually sees.

    Not one :meth:`Omission.sentence` each, which is what this was. A setting
    names itself with its schema and its key, and one setting — "which program
    opens a command window" — is refused on *every* save, so every person who
    saved a desktop was shown ``gsettings:org.gnome.desktop.default-applications
    .terminal exec: a Look is not allowed to change this``, and a second, nearly
    identical line whenever something looked private. So settings are counted by
    reason and said in words here, while :attr:`CaptureResult.omissions` keeps
    every key for a dialog that wants to lay them out properly.

    Files and colours keep their sentence: a path and "the colours" are things
    the person already has words for.

    The missing picture is left to the caller — it has its own, longer sentence,
    and saying it twice would read like two different problems.
    """
    notes: list[str] = []
    counted = {reason for reason, _one, _many in _SETTING_NOTES}
    for reason, one, many in _SETTING_NOTES:
        count = sum(1 for o in omissions if o.kind == "setting" and o.reason == reason)
        if count == 1:
            notes.append(one)
        elif count:
            notes.append(many.format(count=count))
    notes.extend(
        o.sentence()
        for o in omissions
        if o.kind != "picture" and not (o.kind == "setting" and o.reason in counted)
    )
    return notes


def _looks_secret(key: str, value: str) -> bool:
    haystack = f"{key} {value}".lower()
    return any(hint in haystack for hint in SECRET_HINTS)


def capture_settings(
    keys: Iterable[str],
    backend: SettingsBackend,
    *,
    components: dict[str, Component] | None = None,
) -> tuple[list[SettingEntry], list[tuple[str, str]]]:
    """Read every key that can be read. Returns ``(entries, skipped)``.

    A missing schema or key is skipped with a reason rather than raised: a
    restore point taken on a machine where one add-on has since been removed is
    still a perfectly good restore point for everything else, and refusing to
    take one at all would leave the user with no undo precisely when the
    desktop is in an unusual state.

    A setting no Look may write is skipped for a different reason and reported
    as its own sentence: what comes out of here becomes a Look, and a Look
    carrying one of those does not apply at all (``core.policy``). "Which
    program opens a command window" is the live example — gtheme describes that
    setting on its own page, so it is in the corpus this reads, and capturing
    it would produce a saved desktop that could never be put back on. The
    header written into a saved Look says "it changes settings only; it cannot
    run programs", and this is part of what makes that true.
    """
    lookup = components or {}
    entries: list[SettingEntry] = []
    skipped: list[tuple[str, str]] = []
    for key in keys:
        verdict = setting_verdict(key)
        if verdict.refused:
            skipped.append((key, REFUSED_SETTING_REASON))
            continue
        try:
            value = backend.get(key)
        except BackendError as exc:
            if exc.kind in (BackendErrorKind.NO_SCHEMA, BackendErrorKind.NO_KEY):
                skipped.append((key, "not present on this computer"))
            else:
                skipped.append((key, str(exc)))
            continue
        entries.append(
            SettingEntry(
                key=key,
                value=value,
                component=lookup.get(key, Component.OTHER),
            )
        )
    return entries, skipped


def _image_at(value: str) -> Path | None:
    """The picture a ``picture-uri`` value points at, if it is one that exists."""
    raw = value.strip().strip("'\"")
    if raw.startswith("file://"):
        raw = raw[len("file://") :]
    if not raw.startswith("/"):
        return None
    candidate = Path(raw)
    if candidate.is_file() and candidate.suffix.lower() in _IMAGE_SUFFIXES:
        return candidate
    return None


def _wallpaper_sources(entries: Sequence[SettingEntry]) -> dict[str, Path]:
    """Map each wallpaper key the capture read to the picture it points at."""
    found: dict[str, Path] = {}
    for entry in entries:
        if entry.key not in (_WALLPAPER_KEY, _WALLPAPER_DARK_KEY):
            continue
        picture = _image_at(entry.value)
        if picture is not None:
            found[entry.key] = picture
    return found


def _wallpaper_source(entries: Sequence[SettingEntry]) -> Path | None:
    """The image file the captured desktop is currently showing, if any."""
    for picture in _wallpaper_sources(entries).values():
        return picture
    return None


@dataclass(frozen=True)
class _Bundled:
    """One file that travels inside the captured Look.

    Attributes:
        source: where it is being read from on this computer.
        dest: where the Look will write it, as a ``~/...`` path.
        rel: where it sits inside the Look's own folder.
    """

    source: Path
    dest: str
    rel: str


def _claimed_files() -> list[str]:
    """Every file destination the ownership ledger claims, sorted.

    Read through the ledger module's own API, never by parsing its file — the
    same rule ``core.restorepoints`` follows for the settings half.

    Every owner is walked rather than only the Look in use. An entry is written
    *before* the change it describes, so everything named here is a file gtheme
    put on this desktop and has not since put back: the Look currently applied,
    the user's own page edits under ``__manual__``, and anything an earlier Look
    left behind that a switch could not revert. All three are part of the
    desktop somebody is asking to save, and leaving any of them out would save
    a desktop that is not the one on the screen.
    """
    claimed: dict[str, None] = {}
    for owned in read_ledger().values():
        if not isinstance(owned, dict):
            continue
        for dest in owned.get("files", []):
            if isinstance(dest, str) and dest:
                claimed.setdefault(dest, None)
    return sorted(claimed)


def _home_bases(root: Path) -> list[Path]:
    """Both spellings of the home folder: as written, and with links followed.

    A destination the ledger recorded was built on the resolved root, while
    ``dest_root()`` is the root as written. On a machine where the home folder
    is reached through a link those are two spellings of one place, and
    measuring against only one of them would call every file gtheme wrote
    "outside your home folder".
    """
    try:
        resolved = root.resolve()
    except OSError:  # pragma: no cover - an unreadable home folder
        return [root]
    return [root] if resolved == root else [root, resolved]


def _below_home(claimed: str, bases: Sequence[Path]) -> PurePosixPath | None:
    """``claimed`` as a path under one of ``bases``, or None if it is not one.

    Three things have to agree, and a ledger entry is only a string, so none of
    them can be assumed:

    * the path with ``..`` worked out — ``<home>/../../elsewhere/x`` is
      *lexically* under the home folder and names a file that is not. Taken at
      face value it produced ``files/../../elsewhere/x`` as the place inside the
      Look, and the copy landed outside the Look folder entirely;
    * the path with links followed, for the same reason one step further out: a
      claim reached through a shortcut pointing away from the home folder would
      siphon whatever it points at into a Look meant to be given away — the H5
      rule, in the one direction that had never been asked;
    * and the result, which may then contain no ``..`` at all.

    A claim that fails any of them is *not* silently dropped: the caller names
    it, in the same words it uses for a file that was never in the home folder,
    because that is what it is.
    """
    source = Path(os.path.normpath(claimed))
    try:
        resolved = source.resolve()
    except OSError:  # pragma: no cover - a symlink loop in a ledger claim
        return None
    for base in bases:
        try:
            relative = PurePosixPath(source.relative_to(base).as_posix())
        except ValueError:
            continue
        if ".." in relative.parts:
            return None
        try:
            resolved.relative_to(base.resolve())
        except (OSError, ValueError):
            return None
        return relative
    return None


def _owned_files(root: Path) -> tuple[list[_Bundled], list[Omission]]:
    """The files gtheme wrote that this Look can carry, and what it cannot.

    Three things stop a file travelling, and each of them is named rather than
    dropped:

    * it is not inside the home folder — really inside it, ``..`` worked out and
      links followed (:func:`_below_home`) — so a Look could not write it
      anywhere;
    * :mod:`gtheme.core.policy` refuses the destination — a captured Look obeys
      the same tiers a downloaded one does, or the promise in its own header is
      not true;
    * it is not there any more, which is ordinary: the ledger is written before
      the change it describes, so it can outlive the file by design.
    """
    bases = _home_bases(root)
    bundled: list[_Bundled] = []
    left_out: list[Omission] = []
    for claimed in _claimed_files():
        source = Path(os.path.normpath(claimed))
        relative = _below_home(claimed, bases)
        if relative is None:
            left_out.append(
                Omission(
                    "file",
                    claimed,
                    "it is not inside your home folder, and a Look only writes there",
                )
            )
            continue
        written = "~/" + relative.as_posix()
        verdict = file_verdict(written, root=root)
        if verdict.refused:
            left_out.append(Omission("file", written, verdict.reason))
            continue
        if not source.is_file():
            left_out.append(Omission("file", written, "it is not on this computer any more"))
            continue
        bundled.append(
            # The path below the home folder, kept whole: two terminals both
            # call their settings file "config", and flattening to the file
            # name would have one of them overwrite the other inside the Look.
            _Bundled(source=source, dest=written, rel=f"files/{relative.as_posix()}")
        )
    return bundled, left_out


def _palette_table(palette: Palette) -> dict[str, str]:
    """A terminal palette, spelled the way a Look's ``[palette]`` spells one.

    Read back by ``gtheme.ui.pages.terminal.palette_from_look``, which is what
    makes the Terminal page work under a Look somebody saved themselves.
    """
    table = {"bg": palette.background, "fg": palette.foreground}
    if palette.cursor:
        table["cursor"] = palette.cursor
    for index, colour in enumerate(palette.ansi):
        prefix = "ansi_bright_" if index >= len(_ANSI_NAMES) else "ansi_"
        table[prefix + _ANSI_NAMES[index % len(_ANSI_NAMES)]] = colour
    if palette.opacity < 1.0:
        table["opacity"] = f"{palette.opacity:g}"
    return table


def _terminal_palette(backend: SettingsBackend) -> Palette | None:
    """The colours a terminal on this computer is actually wearing, if any.

    Imported here rather than at the top of the module because the adapters
    pull in every terminal gtheme knows about, and a capture that finds its
    colours in the applied Look never needs them.
    """
    from ..terminal import adapters

    for adapter in adapters(backend):
        try:
            found = adapter.current()
        except (OSError, ValueError, PermissionError):
            # An unreadable config is not a reason to fail a save. The next
            # adapter may know, and if none of them do the capture says so.
            continue
        if found is not None:
            return found
    return None


def _captured_palette(backend: SettingsBackend) -> tuple[dict[str, str], Omission | None]:
    """The colours to write into the captured Look, and what was missed.

    The applied Look's own palette first: it is the one somebody chose, it is
    already in the spelling a Look uses, and it carries names (``accent``,
    ``surface1``) that no terminal has. Failing that, whatever a terminal can
    be asked for. Failing both, nothing — and an omission saying so, because a
    Look with no colours leaves the Terminal page with nothing to show.
    """
    name = current_look()
    if name:
        folder = discover().get(name)
        if folder is not None:
            result = load(folder)
            if result.preset is not None and result.preset.palette:
                return dict(result.preset.palette), None
    palette = _terminal_palette(backend)
    if palette is not None:
        return _palette_table(palette), None
    return {}, Omission(
        "palette",
        "the colours",
        "gtheme could not read a set of colours from the look you are using or from "
        "your terminal, so this Look carries none",
    )


def _free_name(rel: str, taken: set[str]) -> str:
    """``rel``, or the first numbered variant of it nothing else has claimed.

    Two files inside one Look cannot share a name, and the second one landing
    on the first would not fail — it would ship the wrong picture.
    """
    if rel not in taken:
        return rel
    path = PurePosixPath(rel)
    for number in range(2, 1000):
        candidate = str(path.with_name(f"{path.stem}-{number}{path.suffix}"))
        if candidate not in taken:
            return candidate
    raise ValueError(f"no free name inside the Look for {rel}")


def _generalise_copy(target: Path, home_re: re.Pattern[str]) -> bool:
    """Rewrite this computer's home folder out of a file already copied in.

    Returns whether anything was rewritten, which is also whether the Look has
    to render the file as a template on the machine it lands on.

    The copy is made first and read back afterwards, rather than the source
    being read and written out: ``shutil.copy2`` carries the file's permissions,
    and writing over a file that already exists keeps them. A file that is not
    UTF-8 text is a picture or a font — nothing to read, nothing to rewrite, and
    the transaction refuses to template one anyway.
    """
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    if not home_re.search(text):
        return False
    target.write_text(home_re.sub("{{ home }}", text), encoding="utf-8")
    return True


def _write_look(
    preset: Preset,
    out_dir: Path,
    *,
    wallpaper: Path | None,
    bundle: Sequence[_Bundled],
    header: str,
    home_re: re.Pattern[str],
) -> tuple[Preset, list[Omission], list[str]]:
    """Materialise a captured Look, copying in its picture and its files.

    Returns the Look as written, an omission for every file that could not be
    copied after all — a file gtheme was allowed to read a moment ago and cannot
    read now is rare, and reporting it is cheaper than explaining a Look that
    quietly ships one file fewer than it lists — and the destinations of the
    files whose *contents* had to be made general, for the caller to say out
    loud.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    files = list(preset.files)
    copied: dict[Path, str] = {}
    left_out: list[Omission] = []
    generalised: list[str] = []
    for item in bundle:
        try:
            # Where inside the Look this may land. Every other source path in
            # the app is confined; this one was not, and ``item.rel`` is built
            # from a destination the ledger claimed, so a claim that walked
            # upwards wrote a file next to the Look rather than into it. The
            # claim is refused before it gets here now — this is the second
            # lock on the same door, and it says so rather than writing.
            target = confine_src(item.rel, out_dir)
        except ConfinementError:
            left_out.append(
                Omission("file", item.dest, "gtheme could not put it inside this Look")
            )
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item.source, target)
        except OSError as exc:
            left_out.append(
                Omission("file", item.dest, f"gtheme could not copy it ({exc.strerror or exc})")
            )
            continue
        copied[item.source] = item.rel
        templated = _generalise_copy(target, home_re)
        if templated:
            generalised.append(item.dest)
        files.append(FileEntry(src=item.rel, dest=item.dest, template=templated))

    screenshots = list(preset.meta.screenshots)
    if wallpaper is not None and wallpaper.is_file():
        already = copied.get(wallpaper)
        if already is not None:
            # The picture is already in the folder because the Look ships it;
            # a second copy of the same wallpaper is just weight.
            screenshots = [already]
        else:
            shot = f"picture{wallpaper.suffix.lower()}"
            shutil.copy2(wallpaper, out_dir / shot)
            screenshots = [shot]

    final = preset.model_copy(
        update={
            "files": files,
            "meta": preset.meta.model_copy(update={"screenshots": screenshots}),
        }
    )
    (out_dir / "theme.toml").write_text(dumps_preset(final, header=header), encoding="utf-8")
    return final, left_out, generalised


def capture_share(
    keys: Iterable[str],
    backend: SettingsBackend,
    *,
    out_dir: Path,
    name: str,
    title: str,
    description: str = "",
    author: str = "",
    version: str = "1.0.0",
    components: dict[str, Component] | None = None,
    enabled_extensions: Sequence[str] = (),
) -> CaptureResult:
    """Capture the desktop as a Look meant to be given to someone else.

    Every captured value is scanned. Anything that looks like a secret is left
    out entirely; anything containing this computer's home directory has the
    path replaced with the ``{{ home }}`` placeholder, which is what makes the
    Look work on a machine with a different login name. Both are reported.

    The wallpaper is *copied into the Look*, and the captured ``picture-uri``
    is rewritten to point at where the copy will land. Genericising the path
    alone is not enough: ``{{ home }}`` resolves to the *other* person's home,
    where that picture never was, so a shared Look would silently apply
    everything except the one thing anybody looks at.

    Every file gtheme wrote for this desktop travels with it too, taken from
    the ownership ledger, and so do the colours — from the applied Look if
    there is one, from the terminal if there is not. Whatever cannot travel is
    named in :attr:`CaptureResult.omissions`.

    A bundled file's *contents* are scanned like a value: every mention of this
    computer's home folder becomes ``{{ home }}`` again and the entry is marked
    ``template``, so the Look neither publishes the login name nor lands
    pointing at folders the recipient does not have.
    """
    entries, skipped = capture_settings(keys, backend, components=components)
    warnings: list[str] = []
    omissions: list[Omission] = []
    home_re = _home_re()
    root = dest_root()

    # A setting a Look may not carry is already skipped with its reason; it is
    # also a thing the user's saved desktop does not have, which is what the
    # omissions list is for. The other skip reasons ("not present on this
    # computer") are an add-on that is not installed, which is not a loss.
    omissions.extend(
        Omission("setting", key, reason) for key, reason in skipped if setting_verdict(key).refused
    )

    bundle, missed = _owned_files(root)
    omissions.extend(missed)
    taken = {item.rel for item in bundle}
    owned_dest = {item.source: item.dest for item in bundle}
    if bundle:
        warnings.append(
            f"the {len(bundle)} file(s) gtheme wrote for this desktop were copied into "
            "this Look, so it looks the same on somebody else's computer"
        )

    # The rewritten value for each key that points at a picture, and one copy
    # of each distinct picture.
    bundled_dest: dict[Path, str] = {}
    wallpapers = 0
    rewritten: dict[str, str] = {}
    for key, picture in _wallpaper_sources(entries).items():
        dest = bundled_dest.get(picture)
        if dest is None:
            # A wallpaper the Look already carries because gtheme wrote it
            # keeps the destination it has. Copying it a second time under a
            # second name would double the Look's weight for one picture.
            dest = owned_dest.get(picture)
            if dest is None:
                rel = _free_name(f"files/{picture.name}", taken)
                taken.add(rel)
                dest = f"~/.local/share/backgrounds/{name}/{picture.name}"
                bundle.append(_Bundled(source=picture, dest=dest, rel=rel))
                wallpapers += 1
            bundled_dest[picture] = dest
        rewritten[key] = "'file://{{ home }}/" + dest.removeprefix("~/") + "'"
    if wallpapers:
        warnings.append(
            f"your wallpaper picture was copied into this Look ({wallpapers} file(s)), "
            "so it still shows up on somebody else's computer"
        )

    safe: list[SettingEntry] = []
    for entry in entries:
        if _looks_secret(entry.key, entry.value):
            # Said once, by the omission pass at the end. Saying it here as
            # well put the identical fact in the dialog twice, once with the
            # schema path in brackets and once with it in front of a colon.
            omissions.append(Omission("setting", entry.key, PRIVATE_SETTING_REASON))
            continue
        if entry.key in rewritten:
            safe.append(entry.model_copy(update={"value": rewritten[entry.key]}))
            continue
        if home_re.search(entry.value):
            replaced = home_re.sub("{{ home }}", entry.value)
            warnings.append(
                "a file path in this Look pointed at your own home folder and was made "
                "general so it works on other computers"
            )
            safe.append(entry.model_copy(update={"value": replaced}))
            continue
        safe.append(entry)

    palette, no_colours = _captured_palette(backend)
    if no_colours is not None:
        omissions.append(no_colours)

    preset = Preset(
        format=2,
        meta=Meta(
            name=name,
            title=title,
            description=description,
            author=author,
            version=version,
            # Only a picture that actually gets copied into the folder gets
            # listed; _write_look fills this in.
            screenshots=[],
        ),
        palette=palette,
        settings=safe,
        extensions=ExtensionsBlock(enable=list(enabled_extensions)),
    )
    wallpaper = _wallpaper_source(entries)
    final, uncopied, generalised = _write_look(
        preset,
        Path(out_dir),
        wallpaper=wallpaper,
        bundle=bundle,
        header=(
            "Made with gtheme by saving a desktop as a Look. It changes settings only; "
            "it cannot run programs."
        ),
        home_re=home_re,
    )
    omissions.extend(uncopied)
    if generalised:
        warnings.append(
            f"the place your home folder lives was written inside {len(generalised)} of "
            "those file(s), and was made general so they work on somebody else's computer"
        )
    if wallpaper is None:
        warnings.append(
            "no wallpaper picture could be found, so add a screenshot before sharing this Look"
        )
        omissions.append(
            Omission(
                "picture",
                "a picture of this desktop",
                "gtheme could not find a wallpaper file to use as one",
            )
        )
    # Said as well as recorded: the dialog that exists today reads warnings,
    # and a saved Look that quietly left something behind is the failure this
    # list was added to stop.
    warnings.extend(_omission_notes(omissions))
    return CaptureResult(
        preset=final,
        path=Path(out_dir),
        skipped=skipped,
        warnings=warnings,
        omissions=omissions,
    )
