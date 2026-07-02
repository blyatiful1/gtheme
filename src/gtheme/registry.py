"""Discovery of themes across the installed and bundled search paths."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from pydantic import ValidationError

from .manifest import Theme, load_theme
from .paths import theme_search_paths


def discover() -> dict[str, Path]:
    """Map theme name -> directory. Installed paths win over bundled ones."""
    found: dict[str, Path] = {}
    for base in theme_search_paths():
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if (child / "theme.toml").is_file() and child.name not in found:
                found[child.name] = child
    return found


def find(name: str) -> Path | None:
    return discover().get(name)


def _short(s: str, limit: int = 60) -> str:
    return s if len(s) <= limit else s[:limit] + "…"


def format_load_error(exc: Exception, theme_dir: Path) -> str:
    """Readable one-line-per-problem load error that names the file at fault.

    pydantic's str() dumps the internal model name, ``type=`` noise and a
    third-party URL; theme authors need ``<dir>/theme.toml: [meta].name: msg``.
    Bare TOML syntax errors get the file path prefixed (palette.toml errors
    are already prefixed by the loader).
    """
    manifest = Path(theme_dir) / "theme.toml"
    if isinstance(exc, ValidationError):
        lines = []
        for e in exc.errors():
            loc = e.get("loc") or ()
            if loc:
                head, *rest = loc
                where = f"[{head}]" + "".join(
                    f"[{part}]" if isinstance(part, int) else f".{part}" for part in rest
                )
            else:
                where = "(top level)"
            got = e.get("input")
            show = "" if isinstance(got, (dict, list)) else f" (got {_short(repr(got))})"
            lines.append(f"{manifest}: {where}: {e.get('msg', 'invalid value')}{show}")
        return "\n".join(lines)
    if isinstance(exc, tomllib.TOMLDecodeError):
        return f"{manifest}: {exc}"
    return str(exc)


def load_all() -> tuple[list[Theme], list[tuple[str, str]]]:
    """Return (loaded themes, [(name, error)]) — invalid themes don't abort."""
    themes: list[Theme] = []
    errors: list[tuple[str, str]] = []
    for name, path in discover().items():
        try:
            themes.append(load_theme(path))
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            errors.append((name, format_load_error(exc, path)))
    return themes, errors


def build_index(themes_dir: Path) -> dict:
    """Build the registry index for a collection directory (for the repo)."""
    entries = []
    for child in sorted(Path(themes_dir).iterdir()):
        if not (child / "theme.toml").is_file():
            continue
        try:
            t = load_theme(child)
        except Exception:  # noqa: BLE001
            continue
        entries.append(
            {
                "name": t.meta.name,
                "title": t.meta.title or t.meta.name,
                "description": t.meta.description,
                "author": t.meta.author,
                "version": t.meta.version,
                "components": t.components(),
            }
        )
    return {"version": 1, "themes": entries}


def write_index(themes_dir: Path) -> Path:
    index = build_index(themes_dir)
    out = Path(themes_dir) / "index.json"
    out.write_text(json.dumps(index, indent=2) + "\n")
    return out
