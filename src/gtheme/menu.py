"""The interactive ``gtheme`` menu.

Launched when ``gtheme`` is run with no subcommand. Every action here funnels
into the same ``cmd_*`` handlers the flag-driven CLI uses — the menu only
gathers arguments (theme name, component filter, confirmations) via arrow-key
widgets, then hands an :class:`argparse.Namespace` to the real command. No
business logic is duplicated.

The session runs on the terminal's alternate screen; command output (diffs,
apply logs) is printed on the normal screen so it survives in scrollback
after the menu exits. Screens are drawn one at a time with a breadcrumb
title (``gtheme › apply › jojo``) instead of stacking widgets.
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
    verbose=False, remote=False, all=False,
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


# ------------------------------------------------------------- theme labels ---
_NAME_W = 14
_TITLE_W = 26


def _theme_label(t, current: str | None, selected: bool = False) -> str:
    """One picker row: activity dot, name and title columns, palette swatches.

    Name/title sit at fixed columns so the swatch strips align into the
    comparable palette grid that is this tool's signature moment.
    """
    active = t.meta.name == current
    name = ansi.pad(t.meta.name[:_NAME_W], _NAME_W)
    title = ansi.pad(ansi.truncate(t.meta.title or "", _TITLE_W), _TITLE_W)
    sw = ansi.swatches(t.palette) if t.palette else ""
    if selected:
        mark = ansi.GLYPH["active"] + " " if active else "  "
        return f"{ansi.reverse(f'{mark}{name} {title}')} {sw}"
    mark = ansi.fg(ansi.GLYPH["active"], "#22c55e") + " " if active else "  "
    return f"{mark}{ansi.style(name, 'bold')} {ansi.style(title, 'grey')} {sw}"


def _theme_panel(t) -> list[str]:
    """Detail lines for the highlighted theme in the picker."""
    lines = []
    if t.meta.description:
        lines.append(ansi.style(t.meta.description, "grey"))
    comps = ", ".join(t.components())
    if comps:
        lines.append(ansi.style(f"components: {comps}", "grey"))
    return lines


def _pick_theme(crumb: str):
    themes = _themes()
    if not themes:
        _flash(ansi.warn("no themes available — install or author one first."))
        return None
    current = read_current()
    tui.clear()
    return tui.select(
        crumb, themes,
        to_label=lambda t: _theme_label(t, current),
        to_label_sel=lambda t: _theme_label(t, current, selected=True),
        panel=_theme_panel,
        right=ansi.style(f"{len(themes)} themes", "grey"),
        footer=tui._default_footer(),
    )


# ------------------------------------------------------------------ helpers ---
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


def _run(cmd, ns: argparse.Namespace, crumb: str = "") -> None:
    """Run a cmd_* handler on the NORMAL screen (so its output lands in
    scrollback), pause, then return to the alternate screen."""
    tui.leave_alt()
    print()
    if crumb:
        print("  " + ansi.style(f"gtheme {ansi.GLYPH['crumb']} {crumb}", "grey"))
    try:
        cmd(ns)
    except SystemExit:
        pass  # _die() inside a handler already printed the message
    except KeyboardInterrupt:
        print(ansi.style("\n  cancelled", "grey"))
    _pause()
    tui.enter_alt()


def _submenu(crumb: str, options: list[str], **kw):
    tui.clear()
    return tui.select(crumb, options, **kw)


# ------------------------------------------------------------------- actions ---
def _act_apply(cli) -> None:
    theme = _pick_theme("gtheme › apply")
    if theme is None:
        return
    name = theme.meta.name
    choice = _submenu(
        f"gtheme › apply › {name}",
        ["Apply now", "Preview first (dry-run)", "Pick components…", "Back"],
    )
    if choice in (None, "Back"):
        return
    if choice == "Preview first (dry-run)":
        _run(cli.cmd_apply, _ns(name=name, dry_run=True), f"apply {name} --dry-run")
        return
    comps = theme.components()
    only = None
    scope = f"all {len(comps)} components" if comps else "everything"
    if choice == "Pick components…":
        tui.clear()
        picked = tui.multiselect(
            f"gtheme › apply › {name} › components", comps, require_one=True,
        )
        if not picked:
            return
        only = ",".join(picked)
        scope = f"{len(picked)} of {len(comps)} components"
    tui.clear()
    if not tui.confirm(f"apply {name} ({scope}) to your desktop?", default=True):
        return
    _run(cli.cmd_apply, _ns(name=name, only=only), f"apply {name}")


def _act_diff(cli) -> None:
    theme = _pick_theme("gtheme › preview")
    if theme is None:
        return
    _run(cli.cmd_diff, _ns(name=theme.meta.name), f"diff {theme.meta.name}")


def _act_restore(cli) -> None:
    tui.clear()
    if not tui.confirm("revert your desktop to its pristine pre-gtheme state?", default=False):
        return
    _run(cli.cmd_restore, _ns(), "restore")


def _act_author(cli) -> None:
    choice = _submenu(
        "gtheme › author",
        ["New (scaffold from a palette)", "Build (render from palette)",
         "Capture (freeze the live desktop)", "Back"],
    )
    if choice in (None, "Back"):
        return
    if choice.startswith("New"):
        tui.clear()
        name = tui.prompt_text("new theme name")
        if not name:
            return
        bases = _themes()
        base = None
        if bases and tui.confirm("seed the palette from an existing theme?", default=True):
            picked = _pick_theme("gtheme › author › seed from")
            base = picked.meta.name if picked else None
        _run(cli.cmd_new, _ns(name=name, from_base=base), f"new {name}")
    elif choice.startswith("Build"):
        theme = _pick_theme("gtheme › author › build")
        if theme:
            _run(cli.cmd_build, _ns(name=theme.meta.name), f"build {theme.meta.name}")
    elif choice.startswith("Capture"):
        tui.clear()
        name = tui.prompt_text("name for the captured theme")
        if not name:
            return
        _run(cli.cmd_capture, _ns(name=name), f"capture {name}")


def _act_manage(cli) -> None:
    choice = _submenu(
        "gtheme › manage",
        ["Install (name, path, .zip, or git URL)", "Update installed themes",
         "Remove an installed theme", "Export to a .zip",
         "Validate", "Search", "Back"],
    )
    if choice in (None, "Back"):
        return
    if choice.startswith("Install"):
        tui.clear()
        source = tui.prompt_text("source (theme name, path, .zip, or git URL)")
        if source:
            _run(cli.cmd_install, _ns(source=source), f"install {source}")
    elif choice.startswith("Update"):
        _run(cli.cmd_update, _ns(), "update")
    elif choice.startswith("Remove"):
        from .paths import INSTALLED_THEMES_DIR

        installed = sorted(
            p.name for p in (INSTALLED_THEMES_DIR.iterdir() if INSTALLED_THEMES_DIR.is_dir() else [])
            if (p / "theme.toml").is_file()
        )
        if not installed:
            _flash(ansi.warn("no themes to remove."))
            return
        picked = _submenu("gtheme › manage › remove", installed)
        if picked:
            tui.clear()
            if tui.confirm(f"remove {picked}?", default=False):
                _run(cli.cmd_remove, _ns(name=picked, yes=True), f"remove {picked}")
    elif choice.startswith("Export"):
        theme = _pick_theme("gtheme › manage › export")
        if theme:
            _run(cli.cmd_export, _ns(name=theme.meta.name), f"export {theme.meta.name}")
    elif choice.startswith("Validate"):
        _run(cli.cmd_validate, _ns(name="all"), "validate")
    elif choice.startswith("Search"):
        tui.clear()
        q = tui.prompt_text("search query")
        if q:
            _run(cli.cmd_search, _ns(query=q), f"search {q}")


# ----------------------------------------------------------------- main loop ---
_LABEL_W = 22


def _item(label: str, note: str, selected: bool = False) -> str:
    body = ansi.pad(label, _LABEL_W)
    if selected:
        return ansi.reverse(body) + ("  " + ansi.style(note, "grey") if note else "")
    return ansi.style(body, "bold") + ("  " + ansi.style(note, "grey") if note else "")


def _status_chip() -> str:
    """Right-side header chip: the applied theme's name + palette strip."""
    current = read_current()
    if not current:
        return ansi.style("no theme applied", "grey")
    t = next((x for x in _themes() if x.meta.name == current), None)
    sw = ansi.swatches(t.palette, limit=6, width=1) if t and t.palette else ""
    dot = ansi.fg(ansi.GLYPH["active"], "#22c55e")
    return f"{sw} {dot} {ansi.style(current, 'bold')}"


def _retint() -> None:
    """Tint the header gradient with the applied theme's accent colours."""
    current = read_current()
    t = next((x for x in _themes() if x.meta.name == current), None) if current else None
    if not (t and t.palette and t.palette.get("accent")):
        tui.set_brand(None)
        return
    a = t.palette["accent"]
    b = t.palette.get("accent_bright") or t.palette.get("blue") or a
    tui.set_brand(a, b)


def run() -> int:
    """Top-level interactive loop. Returns a process exit code."""
    from . import cli  # late import to avoid a cycle (cli -> menu -> cli)

    d = ansi.GLYPH["dot"]
    actions = [
        ("Apply a theme", "pick, preview, confirm", lambda: _act_apply(cli)),
        ("Preview changes", "dry-run, writes nothing", lambda: _act_diff(cli)),
        ("Browse themes", "the local collection", lambda: _run(cli.cmd_list, _ns(), "list")),
        ("Author a theme", f"new {d} build {d} capture", lambda: _act_author(cli)),
        ("Manage themes", f"install {d} update {d} remove {d} export", lambda: _act_manage(cli)),
        ("Restore my desktop", "back to the pre-gtheme state", lambda: _act_restore(cli)),
        ("Quit", "", None),
    ]

    with tui.alt_screen():
        while True:
            _retint()
            tui.clear()
            choice = tui.select(
                "gtheme",
                actions,
                to_label=lambda a: _item(a[0], a[1]),
                to_label_sel=lambda a: _item(a[0], a[1], selected=True),
                right=_status_chip(),
                footer=tui._default_footer(back="quit"),
            )
            if choice is None or choice[2] is None:
                break
            choice[2]()

    print(ansi.gradient(f"\n  {ansi.GLYPH['star']} see you next theme", tui.BRAND_A, tui.BRAND_B))
    return 0
