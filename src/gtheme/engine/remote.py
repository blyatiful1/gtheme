"""Installing themes from the bundled collection, a local path, or a git remote.

A theme `source` can be:
  * a bare name already present in the bundled/installed collection (copied in),
  * a path to a theme directory (contains theme.toml) or a collection (themes/),
  * a git URL or local git repo (cloned shallow, then its themes/ copied in).

Installed themes record where they came from in ``.gtheme-origin.json`` so
``update`` can refetch them. Git origins also record the resolved ``commit``
and the transport ``scheme`` so ``update`` can tell whether anything changed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .. import ansi
from ..errors import ThemeSecurityError
from ..paths import (
    BUNDLED_THEMES_DIR,
    INSTALLED_THEMES_DIR,
    ORIGIN_FILE,
    safe_theme_name,
)

DEFAULT_REMOTE = "https://github.com/blyatiful1/gtheme"

# scp-style git remote, e.g. git@github.com:user/repo.git
_SCP_RE = re.compile(r"^[\w.-]+@[\w.-]+:.+$")


def _is_url(s: str) -> bool:
    return "://" in s or s.endswith(".git") or s.startswith("git@")


def _scheme(s: str) -> str | None:
    """Return the URL scheme (lowercased) for ``s``, or None for local paths.

    scp-style ``git@host:path`` is reported as the synthetic scheme ``"scp"``.
    """
    m = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*)://", s)
    if m:
        return m.group(1).lower()
    if _SCP_RE.match(s):
        return "scp"
    return None


def _check_scheme(source: str, *, insecure: bool) -> str:
    """Enforce the transport allowlist for ``source``; return its scheme.

    Allows https/ssh/scp-style and plain local paths unconditionally; allows
    file:// with a warning; rejects http:// and any other scheme unless
    ``insecure`` is set. Returns the scheme string ("local" for local paths).
    """
    scheme = _scheme(source)
    if scheme is None:
        return "local"
    if scheme in ("https", "ssh", "scp"):
        return scheme
    if scheme == "file":
        print(ansi.warn(f"file:// source is unverified: {source}"))
        return scheme
    if insecure:
        print(ansi.warn(f"allowing insecure transport '{scheme}://': {source}"))
        return scheme
    raise ThemeSecurityError(
        f"refusing insecure transport '{scheme}://' for {source}; "
        "use https/ssh, or pass --insecure to override"
    )


def _git_clone(url: str, into: Path) -> tuple[Path, str]:
    """Shallow-clone ``url`` into ``into``; return (path, resolved commit hash).

    Runs with ``GIT_TERMINAL_PROMPT=0`` so a missing/private repo fails fast
    instead of blocking on an interactive credential prompt.
    """
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    # "--" terminates options so a URL like "-x.git" can't be read as a git flag.
    subprocess.run(
        ["git", "clone", "--depth", "1", "--", url, str(into)],
        check=True, capture_output=True, text=True, env=env,
    )
    rev = subprocess.run(
        ["git", "-C", str(into), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True, env=env,
    )
    return into, rev.stdout.strip()


def _copy_theme(src: Path, name: str, origin: dict) -> Path:
    name = safe_theme_name(name)  # never let a name escape INSTALLED_THEMES_DIR
    dest = INSTALLED_THEMES_DIR / name
    INSTALLED_THEMES_DIR.mkdir(parents=True, exist_ok=True)
    # Updating a theme that is its own source (already installed) is a no-op copy.
    if dest.resolve() != src.resolve():
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
    (dest / ORIGIN_FILE).write_text(json.dumps(origin, indent=2) + "\n", encoding="utf-8")
    return dest


def _themes_in_collection(root: Path) -> dict[str, Path]:
    base = root / "themes" if (root / "themes").is_dir() else root
    out: dict[str, Path] = {}
    for child in sorted(base.iterdir()):
        if (child / "theme.toml").is_file():
            out[child.name] = child
    return out


def install(source: str, name: str | None = None, insecure: bool = False) -> list[str]:
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
                scheme = _check_scheme(source, insecure=insecure)
                root, commit = _git_clone(source, Path(tmp) / "repo")
                print(ansi.bullet(f"fetched {source} @ {commit[:12]}"))
                origin_base = {"type": "git", "source": source,
                               "commit": commit, "scheme": scheme}
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
        scheme = _check_scheme(DEFAULT_REMOTE, insecure=insecure)
        root, commit = _git_clone(DEFAULT_REMOTE, Path(tmp) / "repo")
        print(ansi.bullet(f"fetched {DEFAULT_REMOTE} @ {commit[:12]}"))
        available = _themes_in_collection(root)
        if source not in available:
            raise FileNotFoundError(f"theme '{source}' not found in {DEFAULT_REMOTE}")
        _copy_theme(available[source], source,
                    {"type": "git", "source": DEFAULT_REMOTE, "name": source,
                     "commit": commit, "scheme": scheme})
        return [source]


def update(name: str | None = None, insecure: bool = False) -> list[str]:
    """Refetch installed themes using their recorded origin.

    Each theme is refetched independently so one bad origin does not abort the
    rest. A theme whose tree may carry local modifications we cannot safely
    detect is reported (its content is replaced) rather than silently clobbered.
    """
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
        try:
            origin = json.loads(origin_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(ansi.warn(f"skipping {d.name}: unreadable origin ({exc})"))
            continue
        otype = origin.get("type")
        src = origin.get("source")
        nm = origin.get("name", d.name)
        # Refetching replaces the whole theme tree (_copy_theme rmtrees the
        # dest); any local edits under the installed copy will be lost.
        print(ansi.warn(
            f"updating {d.name} replaces its contents; local edits will be lost"
        ))
        try:
            if otype == "bundled":
                install(nm, insecure=insecure)
            elif src:
                install(src, name=nm, insecure=insecure)
            else:
                print(ansi.warn(f"skipping {d.name}: origin has no source"))
                continue
        except Exception as exc:  # one bad origin must not abort the rest
            print(ansi.err(f"failed to update {d.name}: {exc}"))
            continue
        updated.append(d.name)
    return updated
