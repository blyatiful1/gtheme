"""Command line entry point.

Four subcommands, and only four:

``gui`` (the default)
    Open the app. This is what the ``.desktop`` launcher runs.

``rescue``
    The "my desktop is broken and the app won't open" exit. Headless, no GTK
    import, runnable from a text console (Ctrl+Alt+F3) when the graphical
    session itself is unusable.

``validate <dir>``
    For people authoring a Look: check a preset folder and print what's wrong.

``apply <name|folder> [--dry-run]``
    Use a Look without opening the app, for anyone who keeps their setup in a
    repository or rebuilds a machine from a script. Same compiler, same
    refusals and same restore point as the button in the window; see
    :mod:`gtheme.headless_apply`. Imported late, like ``gui``, because the
    rescue path must not pay for anything it does not need.

Whichever of them runs, the log file and the crash hooks are set up first
(:mod:`gtheme.core.applog`) — including for ``rescue``, which is the one people
run when something has already gone wrong. That import is stdlib-only, so it
cannot cost the rescue path its independence from PyGObject.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from . import __version__
from .core import applog

#: Returned when a subcommand exists but its implementation has not landed yet.
#: Distinct from 1 (real failure) so scripts can tell the two apart.
EXIT_NOT_IMPLEMENTED = 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gtheme",
        description="Change how your desktop looks — safely.",
    )
    parser.add_argument("--version", action="version", version=f"gtheme {__version__}")
    subs = parser.add_subparsers(dest="command")

    subs.add_parser("gui", help="open the app (this is the default)")

    subs.add_parser(
        "rescue",
        help="put your desktop back the way it was, without opening the app",
    )

    validate = subs.add_parser("validate", help="check a Look folder for mistakes")
    validate.add_argument("directory", help="folder containing theme.toml")

    apply_look = subs.add_parser(
        "apply",
        help="use a Look, without opening the app",
        description=(
            "Use a Look on this desktop. Takes the name of a Look you have, or "
            "the folder one lives in. A saved moment is taken first, so the Undo "
            "page can put your desktop back."
        ),
    )
    apply_look.add_argument("look", help="the name of a Look, or the folder one lives in")
    apply_look.add_argument(
        "--dry-run",
        action="store_true",
        help="say what would change, and change nothing",
    )

    return parser


def _cmd_gui(_args: argparse.Namespace) -> int:
    from .app import run  # imported late: the other subcommands must not need GTK

    return run()


def _cmd_rescue(_args: argparse.Namespace) -> int:
    from .core import rescue

    return rescue.run_rescue()


def _cmd_validate(args: argparse.Namespace) -> int:
    from .preset.model import (
        format_validation_errors,
        load_preset_dir,
        palette_contrast_warnings,
    )

    try:
        preset = load_preset_dir(args.directory)
    except FileNotFoundError as exc:
        print(f"gtheme: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        for line in format_validation_errors(exc):
            print(line, file=sys.stderr)
        return 1
    # Warnings, not errors, and the exit code stays 0 on purpose: none of this
    # makes a Look invalid, and a check that can block publishing a palette
    # somebody chose would be switched off rather than acted on. It is said out
    # loud because until now nothing measured contrast anywhere in gtheme, and
    # one of the app's own bundled Looks ships a dimmed-text colour nobody can
    # read (persona-report §2.10).
    warnings = palette_contrast_warnings(preset.palette)
    for line in warnings:
        print(f"warning: {line}", file=sys.stderr)
    if warnings:
        count = len(warnings)
        print(
            f"{args.directory}: valid, with {count} colour"
            f"{'s' if count != 1 else ''} worth another look."
        )
        return 0
    print(f"{args.directory}: looks fine.")
    return 0


def _cmd_apply(args: argparse.Namespace) -> int:
    from .headless_apply import run_apply

    return run_apply(args.look, dry_run=args.dry_run)


_COMMANDS = {
    "gui": _cmd_gui,
    "rescue": _cmd_rescue,
    "validate": _cmd_validate,
    "apply": _cmd_apply,
}


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    command = args.command or "gui"
    log = applog.start()
    # The command name and the version, never the arguments: a Look folder path
    # is a path, but it is still somebody's home directory.
    log.info("gtheme %s: %s", __version__, command)
    handler = _COMMANDS[command]
    try:
        result = handler(args)
    except NotImplementedError as exc:
        log.error("%s is not finished yet: %s", command, exc)
        print(f"gtheme: this is not finished yet — {exc}", file=sys.stderr)
        return EXIT_NOT_IMPLEMENTED
    log.info("%s finished with %s", command, result)
    return result


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
