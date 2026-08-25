"""``python -m gtheme`` — same entry point as the installed ``gtheme`` command."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
