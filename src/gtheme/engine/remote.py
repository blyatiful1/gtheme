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
import shutil
import subprocess
import sys
import re
import tempfile
from pathlib import Path

from .. import ansi
from ..errors import GthemeError, ThemeSecurityError, ThemeValidationError
from ..paths import (
    BUNDLED_THEMES_DIR,
    INSTALLED_THEMES_DIR,
    ORIGIN_FILE,
    read_origin,
    safe_theme_name,
)
from ..validate import validate_dir

DEFAULT_REMOTE = "https://github.com/blyatiful1/gtheme"

# How long (seconds) a single git network operation may take before we give up.
GIT_TIMEOUT = 120

# scp-style git remote, e.g. git@github.com:user/repo.git
_SCP_RE = re.compile(r"^[\w.-]+@[\w.-]+:.+$")


def _is_url(s: str) -> bool:
    """True if ``s`` should be treated as a git URL rather than a local path.

    An existing local path always wins, so a real directory named ``foo.git``
    (or any path that exists on disk) is never force-routed to ``git clone``.
    """
    if Path(s).expanduser().exists():
        return False
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


def _git_env() -> dict:
    # GIT_TERMINAL_PROMPT=0 so a missing/private repo fails fast instead of
    # blocking on an interactive credential prompt.
    return {**os.environ, "GIT_TERMINAL_PROMPT": "0"}


def _run_git(args: list[str], *, what: str) -> subprocess.CompletedProcess:
    """Run a git command, turning every failure into a clean GthemeError.

    Surfaces git's own stderr (repo-not-found, auth, host, no-space) instead of
    the opaque "exit status 128", and bounds network ops with a timeout so a
    stalled remote can't hang forever.
    """
    if shutil.which("git") is None:
        raise GthemeError("git is required for remote theme installs but was not found on PATH")
    try:
        return subprocess.run(
            ["git", *args],
            check=True, capture_output=True, text=True,
            env=_git_env(), timeout=GIT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise GthemeError(f"git {what} timed out after {GIT_TIMEOUT}s (network stalled?)")
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise GthemeError(f"git {what} failed:\n{detail}" if detail else f"git {what} failed (exit {exc.returncode})")
    except FileNotFoundError:
        raise GthemeError("git is required for remote theme installs but was not found on PATH")


def _git_clone(url: str, into: Path) -> tuple[Path, str]:
    """Shallow-clone ``url`` into ``into``; return (path, resolved commit hash)."""
    print(ansi.bullet(f"fetching {url} …"))
    # "--" terminates options so a URL like "-x.git" can't be read as a git flag.
    _run_git(["clone", "--depth", "1", "--", url, str(into)], what=f"clone {url}")
    rev = _run_git(["-C", str(into), "rev-parse", "HEAD"], what="rev-parse")
    return into, rev.stdout.strip()


def _remote_head(url: str) -> str | None:
    """Return the remote's HEAD commit via ls-remote, or None if undeterminable."""
    try:
        out = _run_git(["ls-remote", url, "HEAD"], what=f"ls-remote {url}").stdout.strip()
    except GthemeError:
        return None
    return out.split()[0] if out else None


def _force_rmtree(path: Path) -> None:
    """rmtree that also clears read-only modes so a protected dir can't strand us."""
    path = Path(path)
    if not (path.exists() or path.is_symlink()):
        return

    def _retry(func, p, _exc):
        try:
            os.chmod(p, 0o700)
            func(p)
        except OSError:
            pass

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=lambda f, p, e: _retry(f, p, e))
    else:  # pragma: no cover - 3.11 fallback
        shutil.rmtree(path, onerror=lambda f, p, e: _retry(f, p, e))


def _copy_theme(src: Path, name: str, origin: dict, *, force: bool = False) -> Path:
    """Install the theme dir ``src`` as ``name`` under INSTALLED_THEMES_DIR.

    Atomic and overlap-safe: copies into a hidden staging sibling (preserving
    symlinks rather than dereferencing them), writes the origin marker, then
    swaps it into place with ``os.replace``. On any failure the staging copy is
    removed and the previously-installed theme is left untouched.
    """
    name = safe_theme_name(name)  # never let a name escape INSTALLED_THEMES_DIR
    src = Path(src)
    dest = INSTALLED_THEMES_DIR / name
    INSTALLED_THEMES_DIR.mkdir(parents=True, exist_ok=True)

    src_r, dest_r = src.resolve(), dest.resolve()
    if src_r == dest_r:
        # Installing a theme from its own installed location: just refresh origin.
        (dest / ORIGIN_FILE).write_text(json.dumps(origin, indent=2) + "\n", encoding="utf-8")
        return dest
    # Never let src and dest overlap, or rmtree(dest) could destroy the source.
    if src_r.is_relative_to(dest_r) or dest_r.is_relative_to(src_r):
        raise ThemeSecurityError(
            f"refusing install: source {src} overlaps destination {dest}"
        )
    if dest.exists() and not force:
        raise FileExistsError(
            f"theme {name!r} is already installed; pass --force to overwrite "
            f"(local edits will be lost)"
        )

    staging = INSTALLED_THEMES_DIR / f".{name}.staging"
    _force_rmtree(staging)
    try:
        shutil.copytree(src, staging, symlinks=True)
        (staging / ORIGIN_FILE).write_text(json.dumps(origin, indent=2) + "\n", encoding="utf-8")
        _force_rmtree(dest)
        os.replace(staging, dest)
    except BaseException:
        _force_rmtree(staging)
        raise
    return dest


def _themes_in_collection(root: Path) -> dict[str, Path]:
    """Map theme-name -> dir for a collection root or a single-theme dir."""
    # A repo/dir whose theme.toml sits at the root (no themes/ wrapper).
    if (root / "theme.toml").is_file():
        return {root.name: root}
    base = root / "themes" if (root / "themes").is_dir() else root
    out: dict[str, Path] = {}
    if not base.is_dir():
        return out
    for child in sorted(base.iterdir()):
        if (child / "theme.toml").is_file():
            out[child.name] = child
    return out


def _install_one(
    theme_dir: Path, name: str, origin: dict, *, force: bool, allow_unsafe: bool
) -> Path:
    """Validate a theme dir then copy it in. Raises on validation errors."""
    _theme, errors, warnings = validate_dir(theme_dir)
    for w in warnings:
        print(ansi.warn(w))
    if errors and not allow_unsafe:
        bullets = "\n  - ".join(errors)
        raise ThemeValidationError(
            f"refusing to install {name!r}: theme failed validation:\n  - {bullets}\n"
            f"(pass --allow-unsafe to install anyway)"
        )
    if errors:
        print(ansi.warn(f"installing {name!r} despite {len(errors)} validation error(s) (--allow-unsafe)"))
    return _copy_theme(theme_dir, name, origin, force=force)


def install(
    source: str,
    name: str | None = None,
    insecure: bool = False,
    force: bool = False,
    allow_unsafe: bool = False,
) -> list[str]:
    """Install one or more themes. Returns the installed theme names."""
    kw = {"force": force, "allow_unsafe": allow_unsafe}
    p = Path(source).expanduser()

    # 1) a path to a single theme directory
    if (p / "theme.toml").is_file():
        nm = name or p.name
        _install_one(p, nm, {"type": "path", "source": str(p.resolve())}, **kw)
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
            for nm in wanted:
                if nm not in available:
                    raise FileNotFoundError(
                        f"theme {nm!r} not in {source}; available: {', '.join(available) or '(none)'}"
                    )
            # Per-theme isolation: one bad theme must not abort the batch.
            installed: list[str] = []
            failed: list[str] = []
            for nm in wanted:
                try:
                    _install_one(available[nm], nm, {**origin_base, "name": nm}, **kw)
                    installed.append(nm)
                except (GthemeError, OSError, shutil.Error) as exc:
                    failed.append(nm)
                    print(ansi.err(f"failed to install {nm}: {exc}"))
            if not installed:
                raise GthemeError(f"installed nothing from {source} ({len(failed)} failed)")
            return installed

    # 3) a bare name already in the bundled or installed collection -> copy in
    if BUNDLED_THEMES_DIR.is_dir() and (BUNDLED_THEMES_DIR / source / "theme.toml").is_file():
        _install_one(BUNDLED_THEMES_DIR / source, source, {"type": "bundled", "name": source}, **kw)
        return [source]
    if (INSTALLED_THEMES_DIR / source / "theme.toml").is_file():
        # Re-installing an already-installed bundled/local theme is a no-op refresh.
        return [source]

    # 4) Not a path, URL, or known local theme: a bare name we can't resolve.
    # Do NOT silently clone the default remote (a typo would become a surprise
    # network fetch with a misleading error). Tell the user what IS available.
    from ..registry import discover

    raise FileNotFoundError(
        f"no such theme {source!r}; available: {', '.join(discover()) or '(none)'}\n"
        f"(to install from a remote, pass a git URL, e.g. {DEFAULT_REMOTE})"
    )


def update(name: str | None = None, insecure: bool = False, force: bool = False) -> list[str]:
    """Refetch installed themes using their recorded origin.

    Each theme is refetched independently so one bad origin does not abort the
    rest. Git origins are skipped when the remote HEAD already matches the
    recorded commit (unless ``force``), so an up-to-date theme is never need-
    lessly re-cloned and its local edits are preserved.
    """
    updated: list[str] = []
    targets: list[Path] = []
    if name:
        targets = [INSTALLED_THEMES_DIR / name]
    elif INSTALLED_THEMES_DIR.is_dir():
        targets = [d for d in INSTALLED_THEMES_DIR.iterdir() if (d / ORIGIN_FILE).is_file()]
    for d in targets:
        origin = read_origin(d)
        if origin is None:
            print(ansi.warn(f"skipping {d.name}: missing or unreadable origin"))
            continue
        otype = origin.get("type")
        src = origin.get("source")
        nm = origin.get("name", d.name)
        try:
            if otype == "bundled":
                install(nm, insecure=insecure, force=True)
            elif otype == "git" and src:
                head = _remote_head(src)
                if head and not force and head == origin.get("commit"):
                    print(ansi.bullet(f"{d.name} already up to date ({head[:12]})"))
                    continue
                print(ansi.warn(f"updating {d.name} replaces its contents; local edits will be lost"))
                install(src, name=nm, insecure=insecure, force=True)
            elif otype == "path" and src:
                sp = Path(src)
                if not (sp / "theme.toml").is_file() and not (sp / "themes").is_dir():
                    print(ansi.warn(f"skipping {d.name}: origin path no longer exists ({src})"))
                    continue
                print(ansi.warn(f"updating {d.name} replaces its contents; local edits will be lost"))
                install(src, name=nm, insecure=insecure, force=True)
            else:
                print(ansi.warn(f"skipping {d.name}: origin has no usable source"))
                continue
        except Exception as exc:  # one bad origin must not abort the rest
            print(ansi.err(f"failed to update {d.name}: {exc}"))
            continue
        updated.append(d.name)
    return updated
