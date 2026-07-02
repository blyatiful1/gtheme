"""gtheme command-line interface (stdlib argparse; no typer/rich dependency)."""

from __future__ import annotations

import argparse
import difflib
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from pydantic import ValidationError

from . import ansi
from .backup import clear_current, process_lock, read_current
from .engine import apply as engine
from .errors import (
    GthemeError,
    ThemeNotFoundError,
    ThemeSecurityError,
    ThemeValidationError,
)
from .manifest import Theme, load_theme
from .registry import discover, find, format_load_error, load_all
from .validate import validate_dir

_VERBOSE = False


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("gtheme")
    except Exception:  # noqa: BLE001 — fall back when metadata is unavailable
        from . import __version__  # single-sourced in __init__.py

        return __version__


def _die(msg: str) -> None:
    print(ansi.err(msg), file=sys.stderr)
    raise SystemExit(1)


def _vprint(msg: str) -> None:
    if _VERBOSE:
        print(ansi.style(msg, "grey"), file=sys.stderr)


def _tilde(path: str) -> str:
    """Shorten a $HOME-prefixed path to ~ for display."""
    home = str(Path.home())
    if path == home or path.startswith(home + os.sep):
        return "~" + path[len(home):]
    return path


def _not_found(name: str, candidates, what: str = "theme") -> str:
    """The one not-found shape every command uses: typo hint + candidates."""
    names = sorted(candidates)
    close = difflib.get_close_matches(name, names, n=1)
    hint = f"\n  did you mean: {close[0]}?" if close else ""
    return f"{what} not found: {name}{hint}\n  available: {', '.join(names) or '(none)'}"


def _desktop_is_gnome() -> bool:
    """True on GNOME (or when GTHEME_ASSUME_GNOME=1 overrides, e.g. tests/CI)."""
    if os.environ.get("GTHEME_ASSUME_GNOME"):
        return True
    desk = os.environ.get("XDG_CURRENT_DESKTOP", "") + ":" + os.environ.get("DESKTOP_SESSION", "")
    return "gnome" in desk.lower()


def _load_named(name: str) -> Theme:
    path = find(name)
    if path is None:
        _die(_not_found(name, discover()))
    try:
        return load_theme(path)
    except (tomllib.TOMLDecodeError, ValidationError, FileNotFoundError, GthemeError) as exc:
        _vprint(f"load failed for {name} at {path}")
        _die(f"failed to load theme {name!r}: {format_load_error(exc, path)}")


def _parse_only(value: str | None) -> set[str] | None:
    if not value:
        return None
    return {c.strip() for c in value.split(",") if c.strip()}


def _validate_only(theme: Theme, only: set[str] | None) -> None:
    """Reject --only components the theme does not define (instead of no-op)."""
    if only is None:
        return
    valid = set(theme.components())
    unknown = sorted(only - valid)
    if unknown:
        _die(
            f"unknown component(s): {', '.join(unknown)}\n"
            f"  valid components: {', '.join(theme.components()) or '(none)'}"
        )


# ---------------------------------------------------------------- hook consent ---
def _make_hook_gate(assume_yes: bool) -> "engine.HookGate":
    """Return a HookGate closure that prompts on stdin before running a hook.

    On a non-interactive run without --yes the gate denies (returns False) and
    explains that --yes is required.
    """

    def gate(info: dict) -> bool:
        if assume_yes:
            return True
        # Trusted local/bundled non-sudo hooks run unprompted (README contract);
        # anything sudo or downloaded still needs explicit consent.
        if not info.get("untrusted") and not info.get("sudo"):
            return True
        trust = "untrusted" if info.get("untrusted") else "trusted"
        sudo = "yes" if info.get("sudo") else "no"
        print(ansi.header(f"\nhook[{info.get('event')}] wants to run a script"))
        print(f"  script:  {info.get('script')}")
        print(f"  sudo:    {sudo}")
        print(f"  source:  {trust} ({info.get('theme') or '?'})")
        preview = info.get("preview") or ""
        if preview:
            print(ansi.style("  --- preview ---", "grey"))
            for line in preview.splitlines():
                print(ansi.style(f"  | {line}", "grey"))
            print(ansi.style("  ---------------", "grey"))
        if not sys.stdin.isatty():
            print(
                ansi.warn(
                    "stdin is not a TTY; denying hook. Re-run interactively or pass --yes."
                ),
                file=sys.stderr,
            )
            return False
        try:
            answer = input("  run this hook? [y/N] ").strip().lower()
        except EOFError:
            return False
        return answer in ("y", "yes")

    return gate


# ------------------------------------------------------------------ commands ---
def cmd_list(args: argparse.Namespace) -> int:
    themes, errors = load_all()
    if not themes and not errors:
        print("no themes found.")
        return 0
    current = read_current()
    print(ansi.header("themes"))
    for t in sorted(themes, key=lambda x: x.meta.name):
        mark = ansi.style("●", "green") if t.meta.name == current else " "
        title = t.meta.title or t.meta.name
        comps = ", ".join(t.components())
        print(f" {mark} {ansi.style(t.meta.name, 'bold'):<22} {title}")
        print(f"     {ansi.style(comps, 'grey')}")
    for name, msg in errors:
        print(ansi.err(f"{name}: {msg}"))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    targets = discover() if args.name in (None, "all") else {args.name: find(args.name)}
    rc = 0
    for name, path in targets.items():
        if path is None:
            print(ansi.err(_not_found(name, discover())))
            rc = 1
            continue
        theme, errors, warnings = validate_dir(Path(path))
        if errors:
            rc = 1
            print(ansi.err(f"{name}: {len(errors)} error(s)"))
            for e in errors:
                print(f"     {e}")
        else:
            print(ansi.ok(f"{name}: valid"))
        for w in warnings:
            print(f"   {ansi.warn(w)}")
    return rc


_GROUP_AT = 5  # collapse NEW file lines per component above this many


def _print_diffs(diffs, show_detail: bool) -> None:
    order = {"new": 0, "changed": 1, "missing-src": 2, "unchanged": 3}
    shown = [
        d for d in sorted(diffs, key=lambda x: (order.get(x.status, 9), x.label))
        if d.status != "unchanged"
    ]
    # Fifty identical "NEW [ascii] <path>" lines bury the CHANGE lines a
    # cautious user actually reviews — collapse those floods per component.
    # CHANGE/MISSING and settings always print; --verbose lists everything.
    grouped: dict[str, list] = {}
    if not _VERBOSE:
        by_comp: dict[str, list] = {}
        for d in shown:
            if d.status == "new" and d.kind == "file":
                by_comp.setdefault(d.component, []).append(d)
        grouped = {c: ds for c, ds in by_comp.items() if len(ds) > _GROUP_AT}
    summarised: set[str] = set()
    for d in shown:
        if d.status == "new" and d.kind == "file" and d.component in grouped:
            if d.component not in summarised:
                summarised.add(d.component)
                ds = grouped[d.component]
                root = os.path.commonpath([x.label for x in ds])
                print(f" {ansi.style('NEW    ', 'green')} [{d.component}] "
                      f"{len(ds)} files under {_tilde(root)}/ (--verbose lists them)")
            continue
        tag = {
            "new": ansi.style("NEW    ", "green"),
            "changed": ansi.style("CHANGE ", "yellow"),
            "missing-src": ansi.style("MISSING", "red"),
        }.get(d.status, d.status)
        label = _tilde(d.label) if d.kind == "file" else d.label
        print(f" {tag} [{d.component}] {label}")
        if show_detail and d.detail:
            for line in d.detail.splitlines():
                print(f"        {ansi.style(line, 'grey')}")
    unchanged = sum(1 for d in diffs if d.status == "unchanged")
    if unchanged:
        print(ansi.style(f" ({unchanged} unchanged)", "grey"))


def cmd_diff(args: argparse.Namespace) -> int:
    theme = _load_named(args.name)
    only = _parse_only(args.only)
    _validate_only(theme, only)
    diffs = engine.compute_diffs(theme, only)
    _print_diffs(diffs, show_detail=not args.summary)
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    theme = _load_named(args.name)
    only = _parse_only(args.only)
    _validate_only(theme, only)
    assume_yes = getattr(args, "yes", False)

    if args.dry_run:
        print(ansi.header(f"dry-run: {theme.meta.name}"))
        _print_diffs(engine.compute_diffs(theme, only), show_detail=True)
        res = engine.apply(theme, only, dry_run=True)
        for w in res.warnings:
            print(f"   {ansi.warn(w)}")
        for n in res.notes:
            print(f"   {ansi.style(n, 'grey')}")
        print(ansi.style("\n(no changes written — dry run)", "grey"))
        return 0

    # Applying on KDE/XFCE would leave GNOME settings inert but still overwrite
    # real terminal/GTK config files — make sure that's what the user wants.
    if not _desktop_is_gnome():
        desk = os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("DESKTOP_SESSION") or "unknown"
        print(ansi.warn(
            f"this doesn't look like a GNOME desktop (detected: {desk}).\n"
            f"   gtheme is built for GNOME: its desktop settings would do nothing here,\n"
            f"   but terminal/GTK config files WOULD still be overwritten."
        ))
        if not assume_yes:
            if not sys.stdin.isatty():
                _die(
                    "refusing to apply outside GNOME without confirmation "
                    "(re-run interactively or pass --yes)"
                )
            try:
                answer = input("  apply anyway? [y/N] ").strip().lower()
            except EOFError:
                answer = ""
            if answer not in ("y", "yes"):
                print("aborted.")
                return 0

    print(ansi.header(f"applying: {theme.meta.title or theme.meta.name}"))
    res = engine.apply(
        theme, only,
        dry_run=False,
        do_hooks=not args.no_hooks,
        allow_sudo=not args.no_sudo,
        hook_gate=_make_hook_gate(assume_yes),
        assume_yes=assume_yes,
    )
    if res.hooks_run:
        print(ansi.ok(f"hooks: {', '.join(res.hooks_run)}"))
    for w in res.warnings:
        print(f"   {ansi.warn(w)}")
    for n in res.notes:
        print(f"   {ansi.style(n, 'grey')}")
    if res.failed:
        print(ansi.err("apply did not complete cleanly (see warnings above)"), file=sys.stderr)
        return 1
    print(ansi.ok(f"{res.applied_files} file(s), {res.applied_settings} setting(s) applied"))
    print(ansi.style("\nopen a new terminal for shell/prompt changes; restart GTK apps for css.", "grey"))
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    from .backup import Baseline

    only = _parse_only(getattr(args, "only", None))
    assume_yes = getattr(args, "yes", False)

    # Nothing ever applied: one friendly line, not a warning + "✓ reverted 0
    # item(s)" + hooks-skipped contradiction (same check engine.restore makes).
    baseline = Baseline().load()
    if baseline.is_empty and not baseline.hooks:
        for w in baseline.warnings:
            print(f"   {ansi.warn(w)}")
        print("nothing to restore — no theme has been applied yet")
        return 0

    print(ansi.header("restoring pristine baseline"))
    log, warnings, hard_failed = engine.restore(
        only=only,
        wipe=args.wipe,
        allow_sudo=not args.no_sudo,
        hook_gate=_make_hook_gate(assume_yes),
        assume_yes=assume_yes,
    )
    for line in log:
        print(ansi.bullet(line))
    for w in warnings:
        print(f"   {ansi.warn(w)}")
    # Exit 1 only when a file/setting actually failed to revert — not for soft
    # hook notices (missing/declined/--no-sudo restore hooks).
    if hard_failed:
        print(ansi.err("restore did not complete cleanly (see warnings above)"), file=sys.stderr)
        return 1
    print(ansi.ok(f"reverted {len(log)} item(s) to pre-gtheme state"))
    # Footer only for an actual hook skip, not for any warning whatsoever.
    if any("hook" in w and ("skip" in w or "refus" in w or "missing" in w) for w in warnings):
        print(ansi.style("  (some restore hooks were skipped — see warnings)", "grey"))
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    from .engine.scaffold import new_theme

    try:
        path = new_theme(args.name, from_base=getattr(args, "from"), title=args.title)
    except (FileExistsError, FileNotFoundError) as exc:
        _die(str(exc))
    print(ansi.ok(f"created theme at {path}"))
    print(ansi.style("  edit palette.toml, then:", "grey"))
    print(f"    gtheme build {args.name}")
    print(f"    gtheme apply {args.name} --dry-run")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    from .engine import render

    theme = _load_named(args.name)
    try:
        res = render.build(theme, force=args.force)
    except (ValueError, GthemeError) as exc:
        # e.g. a malformed palette hex (parse_hex) must not dump a raw traceback.
        _die(f"build failed: {exc}")
    print(ansi.header(f"build: {theme.meta.name}"))
    for w in res.written:
        print(ansi.ok(f"rendered {w}"))
    if not res.written:
        print(ansi.warn("nothing rendered — is [build].managed set?"))
    for s in res.skipped:
        print(ansi.style(f"  · skipped {s}", "grey"))
    return 0


def _install_from_community(args: argparse.Namespace) -> list[str] | None:
    """Bare name unknown locally: offer it from the official collection.

    Returns installed names, [] when the user declines, or None when the
    fallback doesn't apply (path-like source, offline, or not in the index).
    """
    from .engine import remote

    source = args.source
    if not source or not all(c.isalnum() or c in "-_" for c in source):
        return None  # only bare theme names get the community lookup
    try:
        entries = remote.fetch_index()
    except GthemeError as exc:
        _vprint(str(exc))
        return None  # offline: keep the plain not-found error
    entry = next((e for e in entries if e.get("name") == source), None)
    if entry is None:
        return None
    print(f"{source!r} is not local, but the community collection has it: "
          f"{entry.get('title') or source}")
    if not getattr(args, "yes", False):
        if not sys.stdin.isatty():
            _die(f"pass --yes to fetch {source!r} from {remote.DEFAULT_REMOTE} non-interactively")
        try:
            answer = input(f"  install {source!r} from {remote.DEFAULT_REMOTE}? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in ("y", "yes"):
            return []
    try:
        return remote.install(
            remote.DEFAULT_REMOTE, name=source, insecure=args.insecure,
            force=getattr(args, "force", False),
            allow_unsafe=getattr(args, "allow_unsafe", False),
        )
    except (GthemeError, FileNotFoundError, FileExistsError, OSError, shutil.Error) as exc:
        _die(f"install failed: {exc}")


def cmd_install(args: argparse.Namespace) -> int:
    from .engine import remote

    try:
        names = remote.install(
            args.source, name=args.name, insecure=args.insecure,
            force=getattr(args, "force", False),
            allow_unsafe=getattr(args, "allow_unsafe", False),
            install_all=getattr(args, "all", False),
        )
    except FileNotFoundError as exc:
        names = _install_from_community(args)
        if names is None:
            _vprint(f"install source: {args.source}")
            _die(f"install failed: {exc}")
        if not names:
            print("aborted.")
            return 0
    except (GthemeError, FileExistsError, OSError, shutil.Error) as exc:
        _vprint(f"install source: {args.source}")
        _die(f"install failed: {exc}")
    for nm in names:
        print(ansi.ok(f"installed {nm}"))
    print(ansi.style(f"  apply with: gtheme apply {names[0]}", "grey"))
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    from .engine import remote
    from .paths import INSTALLED_THEMES_DIR, ORIGIN_FILE, read_origin

    if args.name:
        installed_dir = INSTALLED_THEMES_DIR / args.name
        if not (installed_dir / "theme.toml").is_file():
            if find(args.name) is not None:
                _die(
                    f"{args.name!r} is a bundled theme, not an installed one; "
                    f"it updates together with gtheme itself"
                )
            _die(_not_found(args.name, discover()))
        if read_origin(installed_dir) is None:
            _die(
                f"{args.name!r} was installed manually (no recorded origin); "
                f"re-install it from its source to update it"
            )
    try:
        names = remote.update(
            args.name, insecure=args.insecure, force=getattr(args, "force", False),
            assume_yes=getattr(args, "yes", False),
        )
    except (GthemeError, FileExistsError, OSError, shutil.Error) as exc:
        _die(f"update failed: {exc}")
    if not names:
        # Only claim "nothing has an origin" when that's true — an all-up-to-
        # date run already printed a bullet per theme and needs no epilogue.
        had_origins = INSTALLED_THEMES_DIR.is_dir() and any(
            (d / ORIGIN_FILE).is_file() for d in INSTALLED_THEMES_DIR.iterdir()
        )
        if not args.name and not had_origins:
            print("no installed themes have a recorded origin to update.")
        return 0
    for nm in names:
        print(ansi.ok(f"updated {nm}"))
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    from .paths import BUNDLED_THEMES_DIR, INSTALLED_THEMES_DIR

    name = args.name
    installed = INSTALLED_THEMES_DIR / name
    if not (installed / "theme.toml").is_file():
        # Distinguish "bundled-only" from "not found at all" for a clean message.
        if (BUNDLED_THEMES_DIR / name / "theme.toml").is_file():
            _die(
                f"refusing to remove bundled theme {name!r}: it ships with gtheme "
                f"and is not under the installed themes dir"
            )
        removable = [
            d.name for d in INSTALLED_THEMES_DIR.iterdir()
            if (d / "theme.toml").is_file()
        ] if INSTALLED_THEMES_DIR.is_dir() else []
        _die(_not_found(name, removable, what="installed theme"))

    # Never rmtree outside INSTALLED_THEMES_DIR — confirm containment.
    target = installed.resolve()
    root = INSTALLED_THEMES_DIR.resolve()
    if not target.is_relative_to(root) or target == root:
        _die(f"refusing to remove path outside the installed themes dir: {target}")

    if not getattr(args, "yes", False):
        if not sys.stdin.isatty():
            _die("removal needs confirmation; re-run interactively or pass --yes")
        try:
            answer = input(f"remove installed theme {name!r} from {target}? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in ("y", "yes"):
            print("aborted.")
            return 0

    # R2: run (and forget) this theme's recorded restore hooks BEFORE deleting it,
    # so privileged boot changes aren't orphaned with the only copy of their undo.
    # L1: same inter-process lock as apply/restore, so a concurrent apply can't
    # interleave with the hook-forgetting + rmtree.
    from .backup import Baseline

    with process_lock():
        baseline = Baseline().load()
        theme_hooks = baseline.hooks_for_theme(name, str(target))
        if theme_hooks:
            print(ansi.warn(f"{name} has {len(theme_hooks)} recorded restore hook(s); running them before removal"))
            hlog, hwarn, ran = engine._run_recorded_hooks(
                theme_hooks,
                allow_sudo=not getattr(args, "no_sudo", False),
                hook_gate=_make_hook_gate(getattr(args, "yes", False)),
                assume_yes=getattr(args, "yes", False),
            )
            for line in hlog:
                print(ansi.bullet(line))
            for w in hwarn:
                print(f"   {ansi.warn(w)}")
            if ran:
                baseline.forget_hooks(ran)
            orphaned = [r for r in theme_hooks if r not in ran]
            if orphaned:
                print(ansi.warn(
                    f"{len(orphaned)} restore hook(s) did not run; their (possibly "
                    f"privileged) changes will be orphaned after removal"
                ))

        shutil.rmtree(target)
        print(ansi.ok(f"removed {name}"))
        if read_current() == name:
            clear_current()
            print(ansi.style("  it was the current theme; cleared current.", "grey"))
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    from .engine.export import export_theme

    try:
        out, count = export_theme(args.name, out=args.output)
    except (GthemeError, OSError) as exc:
        _die(f"export failed: {exc}")
    size_kib = out.stat().st_size // 1024
    print(ansi.ok(f"exported {args.name} → {out} ({count} files, {size_kib} KiB)"))
    print(ansi.style(f"  share the .zip — install it elsewhere with: "
                     f"gtheme install {out.name}", "grey"))
    return 0


def _search_remote(query: str) -> int:
    from .engine import remote

    try:
        entries = remote.fetch_index()
    except GthemeError as exc:
        _die(str(exc))
    q = query.lower()
    hits = [
        e for e in entries
        if q in str(e.get("name", "")).lower()
        or q in str(e.get("title") or "").lower()
        or q in str(e.get("description") or "").lower()
    ]
    if not hits:
        print(f"no community themes match {query!r}")
        return 1
    print(ansi.header("community collection"))
    for e in sorted(hits, key=lambda x: str(x.get("name", ""))):
        print(f" {ansi.style(e['name'], 'bold'):<22} {e.get('title') or ''}")
        if e.get("description"):
            print(ansi.style(f"     {e['description']}", "grey"))
    print(ansi.style("\n  install with: gtheme install <name>", "grey"))
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    if getattr(args, "remote", False):
        return _search_remote(args.query)
    themes, _ = load_all()
    q = args.query.lower()
    hits = [
        t for t in themes
        if q in t.meta.name.lower()
        or q in (t.meta.title or "").lower()
        or q in (t.meta.description or "").lower()
    ]
    if not hits:
        print(f"no local themes match {args.query!r}")
        print(ansi.style(f"  try the community collection: gtheme search --remote {args.query}", "grey"))
        return 1
    for t in sorted(hits, key=lambda x: x.meta.name):
        print(f" {ansi.style(t.meta.name, 'bold'):<22} {t.meta.title or ''}")
        if t.meta.description:
            print(ansi.style(f"     {t.meta.description}", "grey"))
    return 0


def _require_source_checkout(action: str) -> None:
    """Refuse packaged-mode writes into the bundled (read-only) collection."""
    from .paths import BUNDLED_THEMES_DIR, REPO_ROOT

    is_checkout = (REPO_ROOT / ".git").exists() or (REPO_ROOT / "pyproject.toml").is_file()
    writable = BUNDLED_THEMES_DIR.is_dir() and os.access(BUNDLED_THEMES_DIR, os.W_OK)
    if not (is_checkout and writable):
        _vprint(f"REPO_ROOT={REPO_ROOT} BUNDLED_THEMES_DIR={BUNDLED_THEMES_DIR}")
        _die(
            f"{action} require a writable source checkout, not an installed package "
            f"(bundled collection at {BUNDLED_THEMES_DIR} is not writable)"
        )


def cmd_index(args: argparse.Namespace) -> int:
    from .paths import BUNDLED_THEMES_DIR
    from .registry import write_index

    _require_source_checkout("index")
    out = write_index(BUNDLED_THEMES_DIR)
    print(ansi.ok(f"wrote {out}"))
    return 0


def cmd_capture(args: argparse.Namespace) -> int:
    from .engine.capture import capture

    try:
        path, notes = capture(args.name, title=args.title)
    except FileExistsError as exc:
        _die(str(exc))
    print(ansi.ok(f"captured live config -> {path}"))
    for n in notes:
        print(ansi.style(f"  · {n}", "grey"))
    print(ansi.style(f"  add a palette.toml and refine theme.toml, then: "
                     f"gtheme apply {args.name} --dry-run", "grey"))
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    from .paths import BUNDLED_THEMES_DIR, REPO_ROOT
    from .registry import find, write_index

    _require_source_checkout("publish")

    src = find(args.name)
    if src is None:
        _die(f"theme not found: {args.name}")
    dest = BUNDLED_THEMES_DIR / args.name
    if src.resolve() != dest.resolve():
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".gtheme-origin.json"))
        print(ansi.ok(f"copied {args.name} into the collection at {dest}"))
    write_index(BUNDLED_THEMES_DIR)
    print(ansi.ok("regenerated themes/index.json"))
    has_gh = shutil.which("gh") is not None
    print(ansi.header("\nto contribute it upstream:"))
    branch = f"theme/{args.name}"
    steps = [
        f"cd {REPO_ROOT}",
        f"git checkout -b {branch}",
        f"git add themes/{args.name} themes/index.json",
        f'git commit -m "Add {args.name} theme"',
    ]
    if has_gh:
        steps += ["git push -u origin " + branch, f'gh pr create --fill --title "Add {args.name} theme"']
    else:
        steps += [
            "git push -u origin " + branch + "   # set a remote first if needed",
            "# then open a pull request on GitHub (gh CLI not installed)",
        ]
    for s in steps:
        print(f"  {s}")
    return 0


def cmd_current(args: argparse.Namespace) -> int:
    name = read_current()
    if not name:
        print("no theme currently applied.")
        return 0
    theme = _load_named(name)
    print(f"{ansi.style(theme.meta.name, 'bold')} — {theme.meta.title or ''}")
    if theme.palette:
        swatches = "  ".join(f"{r}={v}" for r, v in list(theme.palette.items())[:6])
        print(ansi.style(f"  {swatches}", "grey"))
    return 0


# -------------------------------------------------------------------- parser ---
def cmd_menu(args: argparse.Namespace) -> int:
    from . import menu

    return menu.run()


_EPILOG = """\
examples:
  gtheme                        open the interactive menu
  gtheme apply nsx --dry-run    preview a theme without changing anything
  gtheme install https://github.com/you/yourtheme
                                install a theme from a git URL (or a .zip / folder)
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gtheme",
        description="GNOME desktop theme system — run with no command for an interactive menu",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version=f"gtheme {_version()}")
    p.add_argument("-v", "--verbose", action="store_true", help="print extra context on errors")
    p.add_argument("--plain", action="store_true",
                   help="plain numbered prompts (screen-reader friendly)")
    # -v is also accepted after the subcommand. SUPPRESS is load-bearing: a
    # plain default would copy verbose=False over a root-level `gtheme -v`
    # (argparse merges subparser defaults into the shared namespace).
    vp = argparse.ArgumentParser(add_help=False)
    vp.add_argument("-v", "--verbose", action="store_true", default=argparse.SUPPRESS,
                    help="print extra context on errors")
    # Not required: a bare `gtheme` launches the interactive menu.
    # metavar collapses the unreadable 21-command {brace,blob} in usage lines.
    sub = p.add_subparsers(dest="command", metavar="<command>")

    sp = sub.add_parser("menu", aliases=["ui", "i"], parents=[vp],
                        help="launch the interactive arrow-key menu")
    sp.set_defaults(func=cmd_menu)

    sp = sub.add_parser("list", parents=[vp], help="list available themes")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("apply", aliases=["switch"], parents=[vp],
                        help="apply a theme (alias: switch)")
    sp.add_argument("name", help="theme to apply — see `gtheme list`")
    sp.add_argument("--only", help="comma-separated component filter (e.g. terminal,gtk)")
    sp.add_argument("--dry-run", action="store_true",
                    help="show what would change without writing anything")
    sp.add_argument("--no-sudo", action="store_true", help="skip sudo hooks")
    sp.add_argument("--no-hooks", action="store_true", help="skip all hooks")
    sp.add_argument("-y", "--yes", action="store_true",
                    help="skip confirmation prompts (hooks, non-GNOME warning)")
    sp.set_defaults(func=cmd_apply)

    sp = sub.add_parser("diff", parents=[vp], help="show what applying a theme would change")
    sp.add_argument("name", help="theme to compare against the current setup")
    sp.add_argument("--only", help="comma-separated component filter (e.g. terminal,gtk)")
    sp.add_argument("--summary", action="store_true", help="hide per-line detail")
    sp.set_defaults(func=cmd_diff)

    sp = sub.add_parser("restore", parents=[vp],
                        help="revert to the pristine pre-gtheme state")
    sp.add_argument("--only", help="comma-separated component filter (e.g. terminal,gtk)")
    sp.add_argument("--wipe", action="store_true", help="also discard the baseline snapshot")
    sp.add_argument("--no-sudo", action="store_true", help="skip sudo restore hooks")
    sp.add_argument("-y", "--yes", action="store_true",
                    help="approve restore hooks without prompting")
    sp.set_defaults(func=cmd_restore)

    sp = sub.add_parser("current", parents=[vp], help="show the active theme")
    sp.set_defaults(func=cmd_current)

    sp = sub.add_parser("install", parents=[vp],
                        help="install a theme (name, folder, .zip, or git URL)")
    sp.add_argument("source", help="theme name, path to a theme folder or .zip, or a git URL")
    sp.add_argument("--name", help="pick a single theme from a collection/repo")
    sp.add_argument("--all", action="store_true",
                    help="install every theme from a multi-theme source")
    sp.add_argument("--insecure", action="store_true",
                    help="allow insecure transports (e.g. http://)")
    sp.add_argument("--force", action="store_true",
                    help="overwrite an already-installed theme (local edits lost)")
    sp.add_argument("--allow-unsafe", action="store_true",
                    help="install even if the theme fails validation")
    sp.add_argument("-y", "--yes", action="store_true",
                    help="skip confirmation prompts (e.g. community-collection fetch)")
    sp.set_defaults(func=cmd_install)

    sp = sub.add_parser("update", parents=[vp],
                        help="refetch installed themes from their origin")
    sp.add_argument("name", nargs="?",
                    help="installed theme to update (default: all with a recorded origin)")
    sp.add_argument("--insecure", action="store_true",
                    help="allow insecure transports (e.g. http://)")
    sp.add_argument("--force", action="store_true", help="re-fetch even if already up to date")
    sp.add_argument("-y", "--yes", action="store_true",
                    help="replace themes without asking (local edits are lost)")
    sp.set_defaults(func=cmd_update)

    sp = sub.add_parser("remove", aliases=["uninstall"], parents=[vp],
                        help="remove an installed theme (alias: uninstall)")
    sp.add_argument("name", help="installed theme to delete")
    sp.add_argument("-y", "--yes", action="store_true", help="remove without confirmation")
    sp.add_argument("--no-sudo", action="store_true",
                    help="skip sudo restore hooks during removal")
    sp.set_defaults(func=cmd_remove)

    sp = sub.add_parser("search", parents=[vp],
                        help="search themes by name/title/description")
    sp.add_argument("query", help="text to match in names, titles and descriptions")
    sp.add_argument("--remote", action="store_true",
                    help="search the online community collection")
    sp.set_defaults(func=cmd_search)

    sp = sub.add_parser("validate", parents=[vp], help="validate a theme (or all)")
    sp.add_argument("name", nargs="?", default="all",
                    help="theme to check (default: all)")
    sp.set_defaults(func=cmd_validate)

    sp = sub.add_parser("new", parents=[vp], help="scaffold a new theme from a palette")
    sp.add_argument("name", help="name for the new theme (letters, digits, - or _)")
    sp.add_argument("--from", help="seed the palette from an existing theme")
    sp.add_argument("--title", help="human-readable title")
    sp.set_defaults(func=cmd_new)

    sp = sub.add_parser("build", parents=[vp],
                        help="render component files from the palette")
    sp.add_argument("name", help="theme whose files to render from its palette")
    sp.add_argument("--force", action="store_true", help="overwrite files edited by hand")
    sp.set_defaults(func=cmd_build)

    sp = sub.add_parser("capture", parents=[vp],
                        help="freeze the current live config into a new theme")
    sp.add_argument("name", help="name for the captured theme")
    sp.add_argument("--title", help="human-readable title")
    sp.set_defaults(func=cmd_capture)

    sp = sub.add_parser("export", parents=[vp],
                        help="bundle a theme into a shareable .zip archive")
    sp.add_argument("name", help="theme to pack into a .zip")
    sp.add_argument("-o", "--output", help="output path (default: <name>.zip in the current dir)")
    sp.set_defaults(func=cmd_export)

    # Contributor commands last, so newbie commands lead the help listing.
    sp = sub.add_parser("index", parents=[vp],
                        help="(contributors) regenerate themes/index.json for the collection")
    sp.set_defaults(func=cmd_index)

    sp = sub.add_parser("publish", parents=[vp],
                        help="(contributors) add a theme to the collection + print PR steps")
    sp.add_argument("name", help="theme to copy into the bundled collection")
    sp.set_defaults(func=cmd_publish)

    p.commands = sorted(sub.choices)  # for the did-you-mean pre-scan in main()
    return p


def main(argv: list[str] | None = None) -> int:
    global _VERBOSE
    # Non-UTF-8 locales must degrade (glyphs -> '?'), not die in UnicodeEncodeError.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except (OSError, ValueError):
                pass
    parser = build_parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    # 'did you mean' for a mistyped command — argparse's own invalid-choice
    # error dumps all 21 names. No root flag takes a value, so the first
    # non-dash token is the command.
    known = getattr(parser, "commands", [])
    first = next((a for a in argv if not a.startswith("-")), None)
    if first is not None and known and first not in known:
        close = difflib.get_close_matches(first, known, n=1)
        if close:
            print(ansi.err(f"unknown command: {first!r} — did you mean {close[0]!r}?"),
                  file=sys.stderr)
            print("  (see `gtheme --help` for all commands)", file=sys.stderr)
            return 2
    args = parser.parse_args(argv)
    _VERBOSE = getattr(args, "verbose", False)
    if getattr(args, "plain", False):
        os.environ["GTHEME_PLAIN"] = "1"  # accessibility: numbered prompts in the tui
    if getattr(args, "command", None) is None:
        # No subcommand: the menu — its tui degrades to a plain numbered
        # prompt when there's no TTY (pipes/CI), per the README contract.
        from . import menu

        try:
            return menu.run()
        except KeyboardInterrupt:
            print("\naborted", file=sys.stderr)
            return 130
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\naborted", file=sys.stderr)
        return 130
    except (
        GthemeError,
        ThemeSecurityError,
        ThemeValidationError,
        ThemeNotFoundError,
        ValidationError,
        tomllib.TOMLDecodeError,
        subprocess.CalledProcessError,
        OSError,
    ) as exc:
        print(ansi.err(str(exc)), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
