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
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ..core.policy import setting_verdict
from ..core.settings_backend import BackendError, BackendErrorKind, SettingsBackend
from .emit import dumps_preset
from .model import Component, ExtensionsBlock, FileEntry, Meta, Preset, SettingEntry

__all__ = [
    "SECRET_HINTS",
    "CaptureResult",
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

_HOME_RE = re.compile(r"/home/[^/'\"\s]+")
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
_WALLPAPER_KEY = "gsettings:org.gnome.desktop.background picture-uri"
_WALLPAPER_DARK_KEY = "gsettings:org.gnome.desktop.background picture-uri-dark"


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
    """

    preset: Preset
    path: Path | None = None
    skipped: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


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
            skipped.append((key, "a Look is not allowed to change this"))
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


def _write_look(
    preset: Preset,
    out_dir: Path,
    *,
    wallpaper: Path | None,
    owned_files: Sequence[tuple[Path, str]],
    header: str,
) -> Preset:
    """Materialise a captured Look, copying in its picture and owned files."""
    out_dir.mkdir(parents=True, exist_ok=True)
    files = list(preset.files)
    copied: dict[Path, str] = {}
    for source, dest in owned_files:
        if not source.is_file():
            continue
        rel = f"files/{source.name}"
        target = out_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied[source] = rel
        files.append(FileEntry(src=rel, dest=dest))

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
    return final


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
    """
    entries, skipped = capture_settings(keys, backend, components=components)
    warnings: list[str] = []

    # (source, dest) for each distinct picture the desktop is showing, plus the
    # rewritten value for each key that pointed at one.
    owned_files: list[tuple[Path, str]] = []
    bundled_dest: dict[Path, str] = {}
    rewritten: dict[str, str] = {}
    for key, picture in _wallpaper_sources(entries).items():
        dest = bundled_dest.get(picture)
        if dest is None:
            dest = f"~/.local/share/backgrounds/{name}/{picture.name}"
            bundled_dest[picture] = dest
            owned_files.append((picture, dest))
        rewritten[key] = "'file://{{ home }}/" + dest.removeprefix("~/") + "'"
    if owned_files:
        warnings.append(
            f"your wallpaper picture was copied into this Look ({len(owned_files)} file(s)), "
            "so it still shows up on somebody else's computer"
        )

    safe: list[SettingEntry] = []
    for entry in entries:
        if _looks_secret(entry.key, entry.value):
            warnings.append(
                f"one setting was left out because it may contain something private "
                f"({entry.key})"
            )
            continue
        if entry.key in rewritten:
            safe.append(entry.model_copy(update={"value": rewritten[entry.key]}))
            continue
        if _HOME_RE.search(entry.value):
            replaced = _HOME_RE.sub("{{ home }}", entry.value)
            warnings.append(
                "a file path in this Look pointed at your own home folder and was made "
                "general so it works on other computers"
            )
            safe.append(entry.model_copy(update={"value": replaced}))
            continue
        safe.append(entry)

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
        settings=safe,
        extensions=ExtensionsBlock(enable=list(enabled_extensions)),
    )
    wallpaper = _wallpaper_source(entries)
    final = _write_look(
        preset,
        Path(out_dir),
        wallpaper=wallpaper,
        owned_files=owned_files,
        header=(
            "Made with gtheme by saving a desktop as a Look. It changes settings only; "
            "it cannot run programs."
        ),
    )
    result = CaptureResult(preset=final, path=Path(out_dir), skipped=skipped, warnings=warnings)
    if wallpaper is None:
        result.warnings.append(
            "no wallpaper picture could be found, so add a screenshot before sharing this Look"
        )
    return result
