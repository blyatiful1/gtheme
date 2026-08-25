"""Finding Looks on disk, and loading them without ever aborting the app.

Two rules shape this module.

**Installed beats bundled.** A Look the user saved or downloaded shadows a
bundled one of the same name, so "Save my current desktop as a Look" can
legitimately be called ``nightbloom`` and win. Discovery walks the search path
in priority order and the first folder to claim a name keeps it.

**Errors and warnings are different things.** A Look whose ``theme.toml`` does
not validate cannot be applied — that is an error, and the Look is listed as
broken rather than silently vanishing, because a Look that disappears looks
like a bug in gtheme rather than a typo in the Look. A Look that validates but
references a file it does not ship, or was built for a newer GNOME, is a
*warning*: it still applies, and the parts that cannot are named up front.
Nothing here raises for a bad Look; the caller gets a
:class:`LoadResult` and decides.

The v2 namespace under the user's data directory is deliberate: v1 owned
``~/.local/share/gtheme/themes`` and deleted it wholesale on update, so v2
never writes there (DESIGN.md F1).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .model import PRESET_FILENAME, Preset, format_validation_errors, load_preset_dir

__all__ = [
    "LoadResult",
    "bundled_themes_dir",
    "discover",
    "load",
    "load_all",
    "search_paths",
    "user_themes_dir",
]


def _env_dir(name: str) -> Path | None:
    raw = os.environ.get(name)
    return Path(raw).expanduser() if raw else None


def bundled_themes_dir() -> Path:
    """Where the Looks that ship with gtheme live.

    In an installed wheel these are force-included into the package as
    ``gtheme/_bundled_themes``; running from a checkout they are the repo's
    ``themes/`` folder. Both are tried, in that order.
    """
    override = _env_dir("GTHEME_BUNDLED_THEMES_DIR")
    if override is not None:
        return override
    packaged = Path(__file__).resolve().parents[1] / "_bundled_themes"
    if packaged.is_dir():
        return packaged
    return Path(__file__).resolve().parents[3] / "themes"


def user_themes_dir() -> Path:
    """Where Looks the user saved or downloaded live."""
    override = _env_dir("GTHEME_THEMES_DIR")
    if override is not None:
        return override
    data_home = _env_dir("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return data_home / "gtheme" / "v2" / "themes"


def search_paths() -> list[Path]:
    """Directories to look for Looks in, highest priority first."""
    return [user_themes_dir(), bundled_themes_dir()]


def discover() -> dict[str, Path]:
    """Map a Look's name to its folder. Installed shadows bundled."""
    found: dict[str, Path] = {}
    for base in search_paths():
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if child.name in found or not (child / PRESET_FILENAME).is_file():
                continue
            found[child.name] = child
    return found


@dataclass
class LoadResult:
    """One Look, as far as it could be loaded.

    Attributes:
        path: the folder it came from.
        preset: the validated Look, or None when it could not be loaded.
        errors: why it cannot be applied at all. Non-empty means broken.
        warnings: things that will not apply, named so nobody is surprised.
        provenance: ``"bundled"`` or ``"user"`` — what the Looks page badges.
    """

    path: Path
    preset: Preset | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    provenance: str = "user"

    @property
    def ok(self) -> bool:
        return self.preset is not None and not self.errors

    @property
    def name(self) -> str:
        return self.preset.meta.name if self.preset else self.path.name


def _provenance_for(path: Path) -> str:
    try:
        bundled = bundled_themes_dir().resolve()
    except OSError:  # pragma: no cover - unreadable bundled dir
        return "user"
    try:
        path.resolve().relative_to(bundled)
    except ValueError:
        return "user"
    return "bundled"


def _check_contents(preset: Preset, directory: Path) -> list[str]:
    """Warn about anything the Look promises but does not ship."""
    warnings: list[str] = []
    for shot in preset.meta.screenshots:
        if not (directory / shot).is_file():
            warnings.append(f"the picture {shot!r} is missing, so this Look cannot be previewed")
    for entry in preset.files:
        src = directory / entry.src
        if src.is_dir():
            warnings.append(
                f"{entry.src!r} is a folder — a Look copies one file at a time, "
                "so this entry does nothing"
            )
        elif not src.is_file():
            warnings.append(f"{entry.src!r} is missing, so {entry.dest} will not be written")
    if preset.meta.name != directory.name:
        warnings.append(
            f"the folder is called {directory.name!r} but the Look calls itself "
            f"{preset.meta.name!r}; the folder name is what gtheme uses"
        )
    return warnings


def load(directory: str | Path) -> LoadResult:
    """Load one Look folder. Never raises for a bad Look."""
    path = Path(directory)
    result = LoadResult(path=path, provenance=_provenance_for(path))
    try:
        preset = load_preset_dir(path)
    except FileNotFoundError as exc:
        result.errors.append(str(exc))
        return result
    except ValueError as exc:
        result.errors.extend(format_validation_errors(exc))
        return result
    result.preset = preset
    result.warnings.extend(_check_contents(preset, path))
    return result


def load_all() -> list[LoadResult]:
    """Load every discoverable Look, broken ones included, name-sorted."""
    return [load(path) for _name, path in sorted(discover().items())]
