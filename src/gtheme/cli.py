"""gtheme command-line interface (stdlib argparse; no typer/rich dependency)."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from pydantic import ValidationError

from . import ansi
from .backup import clear_current, read_current
from .engine import apply as engine
from .errors import (
    GthemeError,
    ThemeNotFoundError,
    ThemeSecurityError,
    ThemeValidationError,
)
from .manifest import Theme, load_theme
from .registry import discover, find, load_all
from .validate import validate_dir

_VERBOSE = False


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("gtheme")
    except Exception:  # noqa: BLE001 — fall back when metadata is unavailable
        return "0.1.0"


def _die(msg: str) -> None:
    print(ansi.err(msg), file=sys.stderr)
    raise SystemExit(1)


def _vprint(msg: str) -> None:
    if _VERBOSE:
        print(ansi.style(msg, "grey"), file=sys.stderr)


def _load_named(name: str) -> Theme:
    path = find(name)
    if path is None:
        _die(f"theme not found: {name}\n  available: {', '.join(discover()) or '(none)'}")
    try:
        return load_theme(path)
    except (tomllib.TOMLDecodeError, ValidationError, FileNotFoundError, GthemeError) as exc:
        _vprint(f"load failed for {name} at {path}")
        _die(f"failed to load theme {name!r}: {exc}")


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
            print(ansi.err(f"{name}: not found"))
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


def _print_diffs(diffs, show_detail: bool) -> None:
    order = {"new": 0, "changed": 1, "missing-src": 2, "unchanged": 3}
    for d in sorted(diffs, key=lambda x: (order.get(x.status, 9), x.label)):
        if d.status == "unchanged":
            continue
        tag = {
            "new": ansi.style("NEW    ", "green"),
            "changed": ansi.style("CHANGE ", "yellow"),
            "missing-src": ansi.style("MISSING", "red"),
        }.get(d.status, d.status)
        print(f" {tag} [{d.component}] {d.label}")
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

    assume_yes = getattr(args, "yes", False)
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
    only = _parse_only(getattr(args, "only", None))
    assume_yes = getattr(args, "yes", False)
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
    if warnings:
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


def cmd_install(args: argparse.Namespace) -> int:
    from .engine import remote

    try:
        names = remote.install(
            args.source, name=args.name, insecure=args.insecure,
            force=getattr(args, "force", False),
            allow_unsafe=getattr(args, "allow_unsafe", False),
        )
    except (GthemeError, FileNotFoundError, FileExistsError, OSError, shutil.Error) as exc:
        _vprint(f"install source: {args.source}")
        _die(f"install failed: {exc}")
    for nm in names:
        print(ansi.ok(f"installed {nm}"))
    print(ansi.style(f"  apply with: gtheme apply {names[0]}", "grey"))
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    from .engine import remote

    names = remote.update(args.name, insecure=args.insecure, force=getattr(args, "force", False))
    if not names:
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
        _die(f"theme not found among installed themes: {name}")

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
    from .backup import Baseline

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


def cmd_search(args: argparse.Namespace) -> int:
    themes, _ = load_all()
    q = args.query.lower()
    hits = [
        t for t in themes
        if q in t.meta.name.lower()
        or q in (t.meta.title or "").lower()
        or q in (t.meta.description or "").lower()
    ]
    if not hits:
        print(f"no themes match {args.query!r}")
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
    print(ansi.style("  add a palette.toml and refine theme.toml, then `gtheme apply`.", "grey"))
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
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gtheme", description="GNOME desktop theme system")
    p.add_argument("--version", action="version", version=f"gtheme {_version()}")
    p.add_argument("-v", "--verbose", action="store_true", help="print extra context on errors")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("list", help="list available themes")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("validate", help="validate a theme (or all)")
    sp.add_argument("name", nargs="?", default="all")
    sp.set_defaults(func=cmd_validate)

    sp = sub.add_parser("diff", help="show what applying a theme would change")
    sp.add_argument("name")
    sp.add_argument("--only", help="comma-separated component filter")
    sp.add_argument("--summary", action="store_true", help="hide per-line detail")
    sp.set_defaults(func=cmd_diff)

    sp = sub.add_parser("apply", help="apply a theme")
    sp.add_argument("name")
    sp.add_argument("--only", help="comma-separated component filter")
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--no-sudo", action="store_true", help="skip sudo hooks")
    sp.add_argument("--no-hooks", action="store_true", help="skip all hooks")
    sp.add_argument("-y", "--yes", action="store_true", help="approve hooks without prompting")
    sp.set_defaults(func=cmd_apply)

    sp = sub.add_parser("switch", help="switch to a theme (alias for apply)")
    sp.add_argument("name")
    sp.add_argument("--only", help="comma-separated component filter")
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--no-sudo", action="store_true")
    sp.add_argument("--no-hooks", action="store_true")
    sp.add_argument("-y", "--yes", action="store_true", help="approve hooks without prompting")
    sp.set_defaults(func=cmd_apply)

    sp = sub.add_parser("restore", help="revert to the pristine pre-gtheme state")
    sp.add_argument("--only", help="comma-separated component filter")
    sp.add_argument("--wipe", action="store_true", help="also discard the baseline snapshot")
    sp.add_argument("--no-sudo", action="store_true", help="skip sudo restore hooks")
    sp.add_argument("-y", "--yes", action="store_true", help="approve restore hooks without prompting")
    sp.set_defaults(func=cmd_restore)

    sp = sub.add_parser("current", help="show the active theme")
    sp.set_defaults(func=cmd_current)

    sp = sub.add_parser("install", help="install a theme (name, path, or git URL)")
    sp.add_argument("source")
    sp.add_argument("--name", help="pick a single theme from a collection/repo")
    sp.add_argument("--insecure", action="store_true", help="allow insecure transports (e.g. http://)")
    sp.add_argument("--force", action="store_true", help="overwrite an already-installed theme (local edits lost)")
    sp.add_argument("--allow-unsafe", action="store_true", help="install even if the theme fails validation")
    sp.set_defaults(func=cmd_install)

    sp = sub.add_parser("update", help="refetch installed themes from their origin")
    sp.add_argument("name", nargs="?")
    sp.add_argument("--insecure", action="store_true", help="allow insecure transports (e.g. http://)")
    sp.add_argument("--force", action="store_true", help="re-fetch even if already up to date")
    sp.set_defaults(func=cmd_update)

    sp = sub.add_parser("remove", aliases=["uninstall"], help="remove an installed theme")
    sp.add_argument("name")
    sp.add_argument("-y", "--yes", action="store_true", help="remove without confirmation")
    sp.add_argument("--no-sudo", action="store_true", help="skip sudo restore hooks during removal")
    sp.set_defaults(func=cmd_remove)

    sp = sub.add_parser("search", help="search themes by name/title/description")
    sp.add_argument("query")
    sp.set_defaults(func=cmd_search)

    sp = sub.add_parser("index", help="(re)generate themes/index.json for the collection")
    sp.set_defaults(func=cmd_index)

    sp = sub.add_parser("new", help="scaffold a new theme from a palette")
    sp.add_argument("name")
    sp.add_argument("--from", help="seed the palette from an existing theme")
    sp.add_argument("--title", help="human-readable title")
    sp.set_defaults(func=cmd_new)

    sp = sub.add_parser("build", help="render component files from the palette")
    sp.add_argument("name")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_build)

    sp = sub.add_parser("capture", help="freeze the current live config into a new theme")
    sp.add_argument("name")
    sp.add_argument("--title", help="human-readable title")
    sp.set_defaults(func=cmd_capture)

    sp = sub.add_parser("publish", help="add a theme to the collection + print contribute steps")
    sp.add_argument("name")
    sp.set_defaults(func=cmd_publish)

    return p


def main(argv: list[str] | None = None) -> int:
    global _VERBOSE
    parser = build_parser()
    args = parser.parse_args(argv)
    _VERBOSE = getattr(args, "verbose", False)
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
