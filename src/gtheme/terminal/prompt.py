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

from .fsio import config_root, confine
from .model import (
    FileChange,
    Palette,
    ReloadSemantics,
    TerminalState,
    TerminalWrites,
    check_toml_edit,
    hex6,
    read_palette,
    toml_string,
)

__all__ = [
    "FISH_COLOR_MAP",
    "FishAdapter",
    "StarshipAdapter",
    "fish_env",
]

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
    """fish wants ``rrggbb``, with or without the hash. Validate, then strip it.

    Both halves are the shared ones every adapter uses
    (:func:`~gtheme.terminal.model.hex6`, which validates through
    :func:`~gtheme.terminal.model.check_colour`) rather than a second opinion
    kept here; only the missing hash is fish's own.
    """
    return hex6(colour).lstrip("#")


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

    @property
    def variables_path(self) -> Path:
        """Where fish keeps the colours: its own universal-variables file.

        gtheme never writes it — fish does, when the script below runs. It is
        named here so that what it held *before* can be recorded first, which
        is the difference between a change ``gtheme rescue`` can put back and
        one it has never heard of (review-report H8).
        """
        return config_root() / "fish" / "fish_variables"

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

    def plan(self, palette: Palette) -> TerminalWrites:
        """One fish invocation that sets every colour in :data:`FISH_COLOR_MAP`.

        The one adapter that hands back something to *run* rather than
        something to write. fish's colours are universal variables: they live
        in fish's own store, and the supported way to change them is to run
        fish. There is no file for the engine to write and no setting for it to
        set — so what the engine can do instead is save what the store held
        first, which is what ``records`` asks for.

        The script is rendered here, at plan time, so a colour that is not a
        colour is refused before the batch changes anything at all: these
        values are interpolated into a shell command, and anything that is not
        obviously a colour is refused rather than escaped.

        Raises:
            ValueError: a colour was not a plain hex value. Nothing is run.
        """
        script = self.script(palette)
        return TerminalWrites(
            runs=(lambda: self._runner(["fish", "-c", script]),),
            records=(str(self.variables_path),),
        )

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
        return read_palette(
            name=active,
            background=str(background),
            foreground=str(foreground),
            cursor=table.get("cursor"),
            ansi=ansi if len(ansi) == 16 else (),
        )

    def plan(self, palette: Palette) -> TerminalWrites:
        """gtheme's palette table and the line selecting it, keeping the rest.

        Raises:
            ValueError: the edit would leave a file starship cannot read. It
                used to be written with no parse validation at all
                (review-report H8) — over a file that can name a command to run
                on every prompt, which is the last file in this app that should
                be rewritten hopefully.
        """
        path = confine(self.config_path)
        original = ""
        if path.is_file():
            try:
                original = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                original = ""
        text = _replace_table(original, f"palettes.{self.palette_name}", self._table(palette))
        text = _set_root_scalar(text, "palette", f'"{self.palette_name}"')
        check_toml_edit(original, text, what="Starship prompt")
        return TerminalWrites(files=(FileChange(str(path), text.encode("utf-8")),))

    def _table(self, palette: Palette) -> str:
        """gtheme's palette table, with every value written as a TOML string.

        starship's file can hold a ``[custom.…]`` module that names a command
        to run on every prompt, so a value that closed its own quote here would
        be arbitrary code execution from a downloaded Look.
        :class:`~gtheme.terminal.model.Palette` refuses such a value long before
        this point; :func:`~gtheme.terminal.model.toml_string` makes sure that
        even one that got here anyway lands as a string and not as a table.
        """
        cursor = palette.cursor or palette.foreground
        lines = [
            f"background = {toml_string(palette.background)}",
            f"foreground = {toml_string(palette.foreground)}",
            f"cursor = {toml_string(cursor)}",
        ]
        for index, colour in enumerate(palette.ansi):
            lines.append(f"color{index} = {toml_string(colour)}")
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
