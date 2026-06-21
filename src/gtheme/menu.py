"""The interactive ``gtheme`` menu.

Launched when ``gtheme`` is run with no subcommand on a TTY. Every action here
funnels into the same ``cmd_*`` handlers the flag-driven CLI uses — the menu
only gathers arguments (theme name, component filter, confirmations) via
arrow-key widgets, then hands an :class:`argparse.Namespace` to the real
command. No business logic is duplicated.
"""

from __future__ import annotations

import argparse
import sys

from . import ansi, tui
from .backup import read_current
from .registry import load_all


# --------------------------------------------------------------- arg helpers ---
_DEFAULTS = dict(
    name=None, only=None, dry_run=False, no_sudo=False, no_hooks=False,
    yes=False, wipe=False, summary=False, force=False, insecure=False,
    allow_unsafe=False, source=None, query=None, title=None, output=None,
    verbose=False,
)


def _ns(**kw) -> argparse.Namespace:
    ns = argparse.Namespace(**{**_DEFAULTS, **kw})
    # `new --from` lives under the reserved attribute name "from".
    if "from_base" in kw:
        setattr(ns, "from", kw.pop("from_base"))
    elif not hasattr(ns, "from"):
        setattr(ns, "from", None)
    return ns


def _themes() -> list:
    themes, _errors = load_all()
    return sorted(themes, key=lambda t: t.meta.name)


def _theme_label(t) -> str:
    current = read_current()
    mark = ansi.style("●", "green") + " " if t.meta.name == current else "  "
    title = t.meta.title or t.meta.name
    sw = ansi.swatches(t.palette) if t.palette else ""
    name = f"{t.meta.name:<16}"
    return f"{mark}{ansi.style(name, 'bold')} {ansi.style(title, 'grey')}  {sw}"


def _pick_theme(prompt: str):
    themes = _themes()
    if not themes:
        _flash(ansi.warn("no themes available — install or author one first."))
        return None
    return tui.select(prompt, themes, to_label=_theme_label,
                      height=max(6, min(len(themes), 14)))


def _flash(msg: str) -> None:
    print(msg)
    _pause()


def _pause() -> None:
    if not tui.is_interactive():
        return
    print(ansi.style("\n  press any key to return…", "grey"), end="", flush=True)
    try:
        import termios
        import tty

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            tui.read_key(fd)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except Exception:  # noqa: BLE001 - any failure: just fall back to Enter
        try:
            input()
        except EOFError:
            pass
    print()


def _run(cmd, ns: argparse.Namespace) -> None:
    """Run a cmd_* handler, render its output, then pause."""
    tui.clear()
    try:
        cmd(ns)
    except SystemExit:
        pass  # _die() inside a handler already printed the message
    except KeyboardInterrupt:
        print(ansi.style("\n  cancelled", "grey"))
    _pause()


# ------------------------------------------------------------------- actions ---
def _act_apply(cli) -> None:
    theme = _pick_theme("apply a theme")
    if theme is None:
        return
    choice = tui.select(
        f"apply {theme.meta.name}",
        ["Apply now", "Preview first (dry-run)", "Pick components…", "Cancel"],
        footer="↑/↓ move · enter select · q back",
    )
    if choice in (None, "Cancel"):
        return
    if choice == "Preview first (dry-run)":
        _run(cli.cmd_apply, _ns(name=theme.meta.name, dry_run=True))
        return
    only = None
    if choice == "Pick components…":
        comps = theme.components()
        picked = tui.multiselect(f"components of {theme.meta.name}", comps)
        if picked is None:
            return
        only = ",".join(picked) if picked else None
    if not tui.confirm(f"apply {theme.meta.name} to your desktop?", default=True):
        return
    _run(cli.cmd_apply, _ns(name=theme.meta.name, only=only))


def _act_diff(cli) -> None:
    theme = _pick_theme("preview a theme's changes")
    if theme is None:
        return
    _run(cli.cmd_diff, _ns(name=theme.meta.name))


def _act_restore(cli) -> None:
    if not tui.confirm("revert your desktop to its pristine pre-gtheme state?", default=False):
        return
    _run(cli.cmd_restore, _ns())


def _act_author(cli) -> None:
    choice = tui.select(
        "author a theme",
        ["Build (render from palette)", "New (scaffold from a palette)",
         "Capture (freeze the live desktop)", "Back"],
    )
    if choice in (None, "Back"):
        return
    if choice.startswith("Build"):
        theme = _pick_theme("build which theme")
        if theme:
            _run(cli.cmd_build, _ns(name=theme.meta.name))
    elif choice.startswith("New"):
        name = tui.prompt_text("new theme name")
        if not name:
            return
        bases = _themes()
        base = None
        if bases and tui.confirm("seed the palette from an existing theme?", default=True):
            picked = tui.select("seed from", bases, to_label=_theme_label)
            base = picked.meta.name if picked else None
        _run(cli.cmd_new, _ns(name=name, from_base=base))
    elif choice.startswith("Capture"):
        name = tui.prompt_text("name for the captured theme")
        if not name:
            return
        _run(cli.cmd_capture, _ns(name=name))


def _act_manage(cli) -> None:
    choice = tui.select(
        "manage themes",
        ["Install (name, path, or git URL)", "Update installed themes",
         "Remove an installed theme", "Export to a .zip",
         "Validate", "Search", "Back"],
        height=8,
    )
    if choice in (None, "Back"):
        return
    if choice.startswith("Install"):
        source = tui.prompt_text("source (theme name, path, or git URL)")
        if source:
            _run(cli.cmd_install, _ns(source=source))
    elif choice.startswith("Update"):
        _run(cli.cmd_update, _ns())
    elif choice.startswith("Remove"):
        from .paths import INSTALLED_THEMES_DIR

        installed = sorted(
            p.name for p in (INSTALLED_THEMES_DIR.iterdir() if INSTALLED_THEMES_DIR.is_dir() else [])
            if (p / "theme.toml").is_file()
        )
        if not installed:
            _flash(ansi.warn("no themes to remove."))
            return
        picked = tui.select("remove which theme", installed)
        if picked and tui.confirm(f"remove {picked}?", default=False):
            _run(cli.cmd_remove, _ns(name=picked, yes=True))
    elif choice.startswith("Export"):
        theme = _pick_theme("export which theme")
        if theme:
            _run(cli.cmd_export, _ns(name=theme.meta.name))
    elif choice.startswith("Validate"):
        _run(cli.cmd_validate, _ns(name="all"))
    elif choice.startswith("Search"):
        q = tui.prompt_text("search query")
        if q:
            _run(cli.cmd_search, _ns(query=q))


# ----------------------------------------------------------------- main loop ---
def run() -> int:
    """Top-level interactive loop. Returns a process exit code."""
    from . import cli  # late import to avoid a cycle (cli -> menu -> cli)

    current = read_current()
    sub = f"current theme: {current}" if current else "no theme applied yet"

    actions = [
        ("Apply / switch a theme", lambda: _act_apply(cli)),
        ("Preview a theme's changes", lambda: _act_diff(cli)),
        ("Browse themes", lambda: _run(cli.cmd_list, _ns())),
        ("Current theme", lambda: _run(cli.cmd_current, _ns())),
        ("Author a theme", lambda: _act_author(cli)),
        ("Manage themes", lambda: _act_manage(cli)),
        ("Restore pristine state", lambda: _act_restore(cli)),
        ("Quit", None),
    ]
    labels = [a[0] for a in actions]

    while True:
        tui.clear()
        choice = tui.select(
            "gtheme",
            labels,
            subtitle=sub,
            footer="↑/↓ move · enter select · q quit",
        )
        if choice is None or choice == "Quit":
            tui.clear()
            print(ansi.gradient("  see you next rice ✦", tui.BRAND_A, tui.BRAND_B))
            return 0
        handler = dict(actions)[choice]
        if handler:
            handler()
        # refresh the subtitle in case the current theme changed
        current = read_current()
        sub = f"current theme: {current}" if current else "no theme applied yet"
