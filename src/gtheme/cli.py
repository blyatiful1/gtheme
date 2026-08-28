"""Command line entry point.

Three subcommands, and only three:

``gui`` (the default)
    Open the app. This is what the ``.desktop`` launcher runs.

``rescue``
    The "my desktop is broken and the app won't open" exit. Headless, no GTK
    import, runnable from a text console (Ctrl+Alt+F3) when the graphical
    session itself is unusable.

``validate <dir>``
    For people authoring a Look: check a preset folder and print what's wrong.

Whichever of the three runs, the log file and the crash hooks are set up first
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

    return parser


def _cmd_gui(_args: argparse.Namespace) -> int:
    from .app import run  # imported late: the other subcommands must not need GTK

    return run()


def _cmd_rescue(_args: argparse.Namespace) -> int:
    from .core import rescue

    return rescue.run_rescue()


def _cmd_validate(args: argparse.Namespace) -> int:
    from .preset.model import format_validation_errors, load_preset_dir

    try:
        load_preset_dir(args.directory)
    except FileNotFoundError as exc:
        print(f"gtheme: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        for line in format_validation_errors(exc):
            print(line, file=sys.stderr)
        return 1
    print(f"{args.directory}: looks fine.")
    return 0


_COMMANDS = {"gui": _cmd_gui, "rescue": _cmd_rescue, "validate": _cmd_validate}


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
