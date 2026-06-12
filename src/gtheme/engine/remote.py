"""Installing themes from the bundled collection, a local path, or a git remote.

A theme `source` can be:
  * a bare name already present in the bundled/installed collection (copied in),
  * a path to a theme directory (contains theme.toml) or a collection (themes/),
  * a git URL or local git repo (cloned shallow, then its themes/ copied in).

Installed themes record where they came from in ``.gtheme-origin.json`` so
``update`` can refetch them.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..paths import BUNDLED_THEMES_DIR, INSTALLED_THEMES_DIR

DEFAULT_REMOTE = "https://github.com/crocco/gtheme"
ORIGIN_FILE = ".gtheme-origin.json"


def _is_url(s: str) -> bool:
    return "://" in s or s.endswith(".git") or s.startswith("git@")


def _git_clone(url: str, into: Path) -> Path:
    subprocess.run(
        ["git", "clone", "--depth", "1", url, str(into)],
        check=True, capture_output=True, text=True,
    )
    return into


def _copy_theme(src: Path, name: str, origin: dict) -> Path:
    dest = INSTALLED_THEMES_DIR / name
    INSTALLED_THEMES_DIR.mkdir(parents=True, exist_ok=True)
    # Updating a theme that is its own source (already installed) is a no-op copy.
    if dest.resolve() != src.resolve():
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
    (dest / ORIGIN_FILE).write_text(json.dumps(origin, indent=2) + "\n")
    return dest


def _themes_in_collection(root: Path) -> dict[str, Path]:
    base = root / "themes" if (root / "themes").is_dir() else root
    out: dict[str, Path] = {}
    for child in sorted(base.iterdir()):
        if (child / "theme.toml").is_file():
            out[child.name] = child
    return out


def install(source: str, name: str | None = None) -> list[str]:
    """Install one or more themes. Returns the installed theme names."""
    # 1) a path to a single theme directory
    p = Path(source).expanduser()
    if (p / "theme.toml").is_file():
        nm = name or p.name
        _copy_theme(p, nm, {"type": "path", "source": str(p.resolve())})
        return [nm]

    # 2) a git URL or repo / a local collection directory
    if _is_url(source) or (p / "themes").is_dir() or (p / ".git").is_dir():
        with tempfile.TemporaryDirectory() as tmp:
            if _is_url(source):
                root = _git_clone(source, Path(tmp) / "repo")
                origin_base = {"type": "git", "source": source}
            else:
                root = p
                origin_base = {"type": "path", "source": str(p.resolve())}
            available = _themes_in_collection(root)
            if not available:
                raise FileNotFoundError(f"no themes found in {source}")
            wanted = [name] if name else list(available)
            installed = []
            for nm in wanted:
                if nm not in available:
                    raise FileNotFoundError(f"theme '{nm}' not in {source}")
                _copy_theme(available[nm], nm, {**origin_base, "name": nm})
                installed.append(nm)
            return installed

    # 3) a bare name in the bundled collection -> copy in
    bundled = BUNDLED_THEMES_DIR / source
    if (bundled / "theme.toml").is_file():
        _copy_theme(bundled, source, {"type": "bundled", "name": source})
        return [source]

    # 4) fall back to the default remote, picking the named theme
    with tempfile.TemporaryDirectory() as tmp:
        root = _git_clone(DEFAULT_REMOTE, Path(tmp) / "repo")
        available = _themes_in_collection(root)
        if source not in available:
            raise FileNotFoundError(f"theme '{source}' not found in {DEFAULT_REMOTE}")
        _copy_theme(available[source], source, {"type": "git", "source": DEFAULT_REMOTE, "name": source})
        return [source]


def update(name: str | None = None) -> list[str]:
    """Refetch installed themes using their recorded origin."""
    updated: list[str] = []
    targets = []
    if name:
        targets = [INSTALLED_THEMES_DIR / name]
    elif INSTALLED_THEMES_DIR.is_dir():
        targets = [d for d in INSTALLED_THEMES_DIR.iterdir() if (d / ORIGIN_FILE).is_file()]
    for d in targets:
        origin_path = d / ORIGIN_FILE
        if not origin_path.is_file():
            continue
        origin = json.loads(origin_path.read_text())
        src = origin.get("source")
        nm = origin.get("name", d.name)
        if origin["type"] == "bundled":
            install(nm)
        elif src:
            install(src, name=nm)
        updated.append(d.name)
    return updated
