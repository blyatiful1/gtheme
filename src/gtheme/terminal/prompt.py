"""The prompt: fish's own colours, and starship's palette.

Two very different mechanisms sit behind one idea — the colours of the text you
type and the line you type it on.

**fish** keeps its colours in *universal variables*, which are not a config file
gtheme can write: they live in fish's own store and are set by running fish.
So this adapter shells out, and it does so through a seam — a callable that can
be replaced in tests — because the whole point of the test suite is that it
never touches the shell the user is actually running. The default runner also
reroots ``XDG_CONFIG_HOME`` onto gtheme's config root, so even a real fish
invoked under a test destination root writes into the throwaway tree.

**starship** is a TOML file re-read on every prompt draw, so a write here shows
up on the next line the user sees. gtheme owns exactly one table in it —
``[palettes.gtheme]`` — plus the one line that selects it. Everything else in
that file is the user's and comes back out unchanged.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tomllib
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from .fsio import atomic_write_text, config_root, confine
from .model import Palette, ReloadSemantics, TerminalState

__all__ = [
    "FISH_COLOR_MAP",
    "FishAdapter",
    "StarshipAdapter",
    "fish_env",
]

_HEX_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")

#: Which ANSI slot each fish colour variable is drawn from.
#:
#: fish names its colours by role, not by number, so the mapping is a judgement
#: call and it is written down here rather than buried in the code: commands in
#: bright blue, arguments in cyan, errors in red, autosuggestions in the dim
#: grey that bright-black is for. ``None`` means "the palette's foreground".
FISH_COLOR_MAP: dict[str, int | None] = {
    "fish_color_normal": None,
    "fish_color_command": 12,
    "fish_color_keyword": 5,
    "fish_color_quote": 2,
    "fish_color_redirection": 6,
    "fish_color_end": 3,
    "fish_color_error": 1,
    "fish_color_param": 6,
    "fish_color_comment": 8,
    "fish_color_operator": 5,
    "fish_color_autosuggestion": 8,
    "fish_color_selection": 4,
}


def _bare(colour: str) -> str:
    """fish wants ``rrggbb``, with or without the hash. Validate, then strip it."""
    if not _HEX_RE.match(colour):
        raise ValueError(f"not a colour gtheme will pass to a shell: {colour!r}")
    return colour.lstrip("#").lower()


def fish_env() -> dict[str, str]:
    """The environment fish is run with.

    ``XDG_CONFIG_HOME`` points at gtheme's config root, which is the real one in
    normal use and a throwaway directory under test. fish keeps its universal
    variables under that directory, so this is what stops a test from editing
    the colours of the shell the user is sitting in.
    """
    env = dict(os.environ)
    env["XDG_CONFIG_HOME"] = str(config_root())
    return env


def _default_runner(argv: Sequence[str]) -> str:
    result = subprocess.run(  # noqa: S603 - argv is built here, never user text
        list(argv),
        capture_output=True,
        text=True,
        env=fish_env(),
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{argv[0]} failed: {result.stderr.strip()}")
    return result.stdout


class FishAdapter:
    """Colour the fish shell by setting its universal variables.

    Args:
        runner: runs a command and returns its output. The seam; tests pass a
            recorder and nothing is executed.
    """

    id = "fish"
    name = "fish"
    reload_semantics = ReloadSemantics.LIVE

    def __init__(self, runner: Callable[[Sequence[str]], str] | None = None) -> None:
        self._runner = runner or _default_runner

    def detect(self) -> TerminalState:
        installed = shutil.which("fish") is not None
        return TerminalState(
            installed=installed,
            config_path=config_root() / "fish" if installed else None,
            foreign_root=None,
            current=None,
            notes=[
                "Terminals you already have open pick this up the next time "
                "they show a prompt.",
            ],
        )

    def current(self) -> Palette | None:
        """None, honestly.

        fish stores the colours of *text*, not a background and a foreground,
        so there is no palette here to hand back — reporting a made-up one
        would make the Terminal page claim fish is wearing a look it is not.
        Use :meth:`colors` for what fish actually has.
        """
        return None

    def colors(self) -> dict[str, str]:
        """The ``fish_color_*`` universal variables fish currently has."""
        try:
            output = self._runner(["fish", "-c", "set --universal"])
        except (OSError, RuntimeError):
            return {}
        found: dict[str, str] = {}
        for line in output.splitlines():
            name, _, value = line.strip().partition(" ")
            if name.startswith("fish_color_"):
                found[name] = value.strip()
        return found

    def apply(self, palette: Palette) -> None:
        """Set every colour in :data:`FISH_COLOR_MAP` in one fish invocation.

        Raises:
            ValueError: a colour was not a plain hex value. Nothing is run —
                these values are interpolated into a shell command, so anything
                that is not obviously a colour is refused rather than escaped.
        """
        self._runner(["fish", "-c", self.script(palette)])

    def script(self, palette: Palette) -> str:
        """The fish script :meth:`apply` runs. Separated so it can be read."""
        lines = []
        for variable, slot in FISH_COLOR_MAP.items():
            if slot is None:
                colour = palette.foreground
            elif slot < len(palette.ansi):
                colour = palette.ansi[slot]
            else:
                continue
            lines.append(f"set --universal {variable} {_bare(colour)}")
        return "\n".join(lines)


class StarshipAdapter:
    """Give starship a ``[palettes.gtheme]`` table and select it."""

    id = "starship"
    name = "Starship prompt"
    reload_semantics = ReloadSemantics.LIVE

    #: The palette table gtheme owns. Nothing else in the file is touched.
    palette_name = "gtheme"

    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = Path(config_path) if config_path is not None else None

    @property
    def config_path(self) -> Path:
        if self._config_path is not None:
            return self._config_path
        return config_root() / "starship.toml"

    def detect(self) -> TerminalState:
        installed = shutil.which("starship") is not None or self.config_path.exists()
        return TerminalState(
            installed=installed,
            config_path=self.config_path if installed else None,
            foreign_root=None,
            current=self.current() if installed else None,
            notes=[self.reload_semantics.sentence()],
        )

    def current(self) -> Palette | None:
        data = self._load()
        if data is None:
            return None
        active = data.get("palette")
        if not isinstance(active, str):
            return None
        table = (data.get("palettes") or {}).get(active)
        if not isinstance(table, Mapping):
            return None
        background = table.get("background")
        foreground = table.get("foreground")
        if not background or not foreground:
            return None
        ansi = tuple(str(table[f"color{i}"]) for i in range(16) if f"color{i}" in table)
        return Palette(
            name=active,
            background=str(background),
            foreground=str(foreground),
            cursor=table.get("cursor"),
            ansi=ansi if len(ansi) == 16 else (),
        )

    def apply(self, palette: Palette) -> None:
        """Rewrite gtheme's palette table and select it, keeping the rest."""
        path = confine(self.config_path)
        text = ""
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                text = ""
        text = _replace_table(text, f"palettes.{self.palette_name}", self._table(palette))
        text = _set_root_scalar(text, "palette", f'"{self.palette_name}"')
        atomic_write_text(path, text)

    def _table(self, palette: Palette) -> str:
        cursor = palette.cursor or palette.foreground
        lines = [
            f'background = "{palette.background}"',
            f'foreground = "{palette.foreground}"',
            f'cursor = "{cursor}"',
        ]
        for index, colour in enumerate(palette.ansi):
            lines.append(f'color{index} = "{colour}"')
        return "\n".join(lines)

    def _load(self) -> dict | None:
        try:
            return tomllib.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            return None


def _table_span(text: str, header: str) -> tuple[int, int] | None:
    """Where ``[header]`` starts and where the next table begins."""
    pattern = re.compile(rf"^[ \t]*\[{re.escape(header)}\][ \t]*$", re.MULTILINE)
    match = pattern.search(text)
    if match is None:
        return None
    following = re.compile(r"^[ \t]*\[", re.MULTILINE).search(text, match.end())
    return (match.start(), following.start() if following else len(text))


def _replace_table(text: str, header: str, body: str) -> str:
    """Replace one TOML table wholesale, or append it at the end."""
    block = f"[{header}]\n{body}\n"
    span = _table_span(text, header)
    if span is None:
        separator = "" if not text or text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
        return text + separator + block
    start, end = span
    return text[:start] + block + ("\n" if text[end:] else "") + text[end:]


def _set_root_scalar(text: str, key: str, value: str) -> str:
    """Set a top-level key, which in TOML means before the first table header."""
    first_table = re.compile(r"^[ \t]*\[", re.MULTILINE).search(text)
    head_end = first_table.start() if first_table else len(text)
    head, tail = text[:head_end], text[head_end:]
    pattern = re.compile(rf"^[ \t]*{re.escape(key)}[ \t]*=.*$", re.MULTILINE)
    if pattern.search(head):
        return pattern.sub(f"{key} = {value}", head, count=1) + tail
    line = f"{key} = {value}\n"
    if head and not head.endswith("\n"):
        head += "\n"
    return head + line + ("\n" if tail and not head.endswith("\n\n") else "") + tail
