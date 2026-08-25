"""Reading the current desktop back out as a Look.

One mechanism, two uses, and that is the point (DESIGN.md A8):

* **Restore points.** Before every transaction, gtheme writes down the exact
  current value of every setting it knows how to touch. Undo is then just
  *applying a Look* — the same code path, the same preflight, the same
  confinement, the same tests. A second, separate restore engine would be the
  least-exercised code in the app and the one that has to work on the worst day
  someone has.
* **"Save my current desktop as a Look."** The same capture, curated, with a
  scan for anything the user would not want to publish.

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
from datetime import datetime
from pathlib import Path

from ..core.settings_backend import BackendError, BackendErrorKind, SettingsBackend
from .emit import dumps_preset
from .model import Component, ExtensionsBlock, FileEntry, Meta, Preset, SettingEntry

__all__ = [
    "SECRET_HINTS",
    "CaptureResult",
    "capture_restore_point",
    "capture_settings",
    "capture_share",
    "list_restore_points",
    "prune_restore_points",
    "restore_points_dir",
    "state_dir",
]

#: How many restore points are kept. Older ones are removed oldest-first; the
#: pristine "before gtheme" baseline is NOT one of these and is never pruned.
RESTORE_POINT_CAP = 10

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
_WALLPAPER_KEY = "gsettings:org.gnome.desktop.background picture-uri"
_WALLPAPER_DARK_KEY = "gsettings:org.gnome.desktop.background picture-uri-dark"


def state_dir() -> Path:
    """Where v2 keeps its runtime state.

    v1's files sit in the parent directory and are never written or removed
    (DESIGN.md F1); v2 lives in its own ``v2/`` below it.
    """
    import os

    override = os.environ.get("GTHEME_STATE_DIR")
    if override:
        return Path(override).expanduser()
    base = os.environ.get("XDG_STATE_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".local" / "state"
    return root / "gtheme" / "v2"


def restore_points_dir() -> Path:
    """The folder restore points are written into."""
    return state_dir() / "restore-points"


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
    """
    lookup = components or {}
    entries: list[SettingEntry] = []
    skipped: list[tuple[str, str]] = []
    for key in keys:
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


def _wallpaper_source(entries: Sequence[SettingEntry]) -> Path | None:
    """The image file the captured desktop is currently showing, if any."""
    for entry in entries:
        if entry.key not in (_WALLPAPER_KEY, _WALLPAPER_DARK_KEY):
            continue
        raw = entry.value.strip().strip("'\"")
        if raw.startswith("file://"):
            raw = raw[len("file://") :]
        if not raw.startswith("/"):
            continue
        candidate = Path(raw)
        if candidate.is_file() and candidate.suffix.lower() in (
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
        ):
            return candidate
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
    for source, dest in owned_files:
        if not source.is_file():
            continue
        rel = f"files/{source.name}"
        target = out_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        files.append(FileEntry(src=rel, dest=dest))

    screenshots = list(preset.meta.screenshots)
    if wallpaper is not None and wallpaper.is_file():
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


def capture_restore_point(
    keys: Iterable[str],
    backend: SettingsBackend,
    *,
    label: str,
    components: dict[str, Component] | None = None,
    owned_files: Sequence[tuple[Path, str]] = (),
    enabled_extensions: Sequence[str] = (),
    directory: Path | None = None,
    cap: int = RESTORE_POINT_CAP,
    now: datetime | None = None,
) -> CaptureResult:
    """Write down exactly how the desktop is right now.

    Args:
        keys: every setting gtheme knows how to change. What is not captured
            cannot be restored, which is why the descriptor corpus and this
            list are the same list.
        label: what the restore point is called in the list — the Home page
            shows it as "My desktop, 25 August", so this is prose.
        owned_files: ``(source, destination)`` pairs for files gtheme wrote and
            would need to put back.
        directory: where to write. Defaults to a timestamped folder under the
            state directory.
        cap: how many restore points to keep afterwards.

    Returns:
        The captured Look and where it was written.
    """
    moment = now or datetime.now()
    stamp = moment.strftime("%Y%m%d-%H%M%S")
    out_dir = Path(directory) if directory is not None else restore_points_dir() / stamp

    entries, skipped = capture_settings(keys, backend, components=components)
    preset = Preset(
        format=2,
        meta=Meta(
            name=f"restore-{stamp}",
            title=label,
            description=f"How this desktop looked on {moment:%d %B %Y at %H:%M}.",
            author="you",
            version=stamp,
            # Filled in by _write_look if there is a wallpaper to copy. Naming
            # a file that was never written is how a restore point ends up
            # warning about its own missing picture on every load.
            screenshots=[],
        ),
        settings=entries,
        extensions=ExtensionsBlock(enable=list(enabled_extensions)),
    )
    wallpaper = _wallpaper_source(entries)
    final = _write_look(
        preset,
        out_dir,
        wallpaper=wallpaper,
        owned_files=owned_files,
        header=(
            "A restore point. gtheme wrote this by reading your desktop; applying it "
            "puts every setting listed here back exactly as it was.\n"
            "It is an ordinary Look, which is why undo uses the same code as everything "
            "else."
        ),
    )
    result = CaptureResult(preset=final, path=out_dir, skipped=skipped)
    if wallpaper is None:
        result.warnings.append(
            "your current wallpaper could not be found, so this restore point has no "
            "picture to show in the list"
        )
    if cap:
        removed = prune_restore_points(cap=cap)
        if removed:
            result.warnings.append(
                f"the {len(removed)} oldest restore point(s) were removed to keep the list short"
            )
    return result


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
    """
    entries, skipped = capture_settings(keys, backend, components=components)
    warnings: list[str] = []
    safe: list[SettingEntry] = []
    for entry in entries:
        if _looks_secret(entry.key, entry.value):
            warnings.append(
                f"one setting was left out because it may contain something private "
                f"({entry.key})"
            )
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
            # See capture_restore_point: only a picture that gets copied in
            # gets listed.
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
        owned_files=(),
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


def list_restore_points(directory: Path | None = None) -> list[Path]:
    """Restore-point folders, newest first."""
    base = Path(directory) if directory is not None else restore_points_dir()
    if not base.is_dir():
        return []
    found = [p for p in base.iterdir() if (p / "theme.toml").is_file()]
    return sorted(found, key=lambda p: p.name, reverse=True)


def prune_restore_points(*, cap: int = RESTORE_POINT_CAP, directory: Path | None = None) -> list[str]:
    """Keep the newest ``cap`` restore points. Returns the names removed."""
    points = list_restore_points(directory)
    removed: list[str] = []
    for stale in points[cap:]:
        shutil.rmtree(stale, ignore_errors=True)
        removed.append(stale.name)
    return removed
