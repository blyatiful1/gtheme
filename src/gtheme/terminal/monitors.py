"""The things that live *inside* a terminal: btop, cava, fastfetch.

None of these are terminals, and all three are part of what a terminal look
means in practice — a rice that themes the terminal and leaves the system
monitor in default green is not finished. They are grouped here because they
share a shape: a small config file gtheme edits in place, and a restart story
that has to be told honestly.

* **btop** reads its config when it starts. A running btop keeps the old
  colours, so the adapter says "close it and open it again" rather than
  pretending.
* **cava** is the same: the gradient changes for the next run.
* **fastfetch** is not a running program at all — it prints once and exits — so
  the next time it is run, it is already themed. That is
  :attr:`~gtheme.terminal.model.ReloadSemantics.ONE_SHOT`: "run it again to see
  this", with nothing to close and nothing to reload.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from .fsio import config_root, confine
from .ghostty import slugify
from .kv import IniFile, KeyValueFile
from .model import (
    FileChange,
    Palette,
    ReloadSemantics,
    TerminalState,
    TerminalWrites,
    hex6,
    one_line,
    read_palette,
)

__all__ = [
    "BtopAdapter",
    "CavaAdapter",
    "FastfetchAdapter",
    "cava_gradient",
    "render_btop_theme",
]

#: Which ANSI slots the cava gradient climbs through, bottom to top. Chosen so
#: the bars read as one rising colour rather than a rainbow: the palette's
#: green, cyan, blue, magenta, then its yellow as the tip.
_CAVA_SLOTS = (2, 6, 4, 5, 3)


def _slot(palette: Palette, index: int, fallback: str) -> str:
    return palette.ansi[index] if index < len(palette.ansi) else fallback


def render_btop_theme(palette: Palette) -> str:
    """A btop ``.theme`` file — ``theme[name]="#rrggbb"``, one per line.

    Only the colours btop needs to look like the palette are set; every key btop
    does not find here it fills in from its own default, which is how btop
    themes are meant to work.
    """
    fg = palette.foreground
    bg = palette.background
    accent = palette.cursor or _slot(palette, 3, fg)
    entries: dict[str, str] = {
        "main_bg": bg,
        "main_fg": fg,
        "title": fg,
        "hi_fg": accent,
        "selected_bg": _slot(palette, 8, bg),
        "selected_fg": fg,
        "inactive_fg": _slot(palette, 8, fg),
        "graph_text": fg,
        "meter_bg": _slot(palette, 8, bg),
        "proc_misc": _slot(palette, 6, fg),
        "cpu_box": _slot(palette, 4, fg),
        "mem_box": _slot(palette, 2, fg),
        "net_box": _slot(palette, 5, fg),
        "proc_box": _slot(palette, 6, fg),
        "div_line": _slot(palette, 8, fg),
        "temp_start": _slot(palette, 2, fg),
        "temp_mid": _slot(palette, 3, fg),
        "temp_end": _slot(palette, 1, fg),
        "cpu_start": _slot(palette, 2, fg),
        "cpu_mid": _slot(palette, 3, fg),
        "cpu_end": _slot(palette, 1, fg),
        "free_start": _slot(palette, 2, fg),
        "free_end": _slot(palette, 10, fg),
        "cached_start": _slot(palette, 6, fg),
        "cached_end": _slot(palette, 14, fg),
        "available_start": _slot(palette, 4, fg),
        "available_end": _slot(palette, 12, fg),
        "used_start": _slot(palette, 1, fg),
        "used_end": _slot(palette, 9, fg),
        "download_start": _slot(palette, 5, fg),
        "download_end": _slot(palette, 13, fg),
        "upload_start": _slot(palette, 3, fg),
        "upload_end": _slot(palette, 11, fg),
        "process_start": _slot(palette, 6, fg),
        "process_end": _slot(palette, 14, fg),
    }
    # btop's own parser takes the text between the quotes as it finds it, so a
    # value carrying a quote or a newline would not be a broken colour — it
    # would be extra lines in a file gtheme wrote. Palette has already refused
    # anything of the sort; this refuses it a second time rather than escaping
    # into a format that has no escapes.
    name = one_line(palette.name, what="the look name")
    lines = [f"# {name} — written by gtheme"]
    for key, value in entries.items():
        safe = one_line(value, what=key, forbid='"')
        lines.append(f'theme[{key}]="{safe}"')
    return "\n".join(lines) + "\n"


def cava_gradient(palette: Palette) -> list[str]:
    """The colours cava's bars climb through, bottom to top."""
    if palette.ansi:
        return [palette.ansi[slot] for slot in _CAVA_SLOTS]
    return [palette.foreground, palette.cursor or palette.foreground]


class BtopAdapter:
    """Theme btop: write a theme file, then name it in ``btop.conf``."""

    id = "btop"
    name = "btop system monitor"
    reload_semantics = ReloadSemantics.RESTART

    def __init__(self, config_dir: Path | None = None) -> None:
        self._config_dir = Path(config_dir) if config_dir is not None else None

    @property
    def config_dir(self) -> Path:
        return self._config_dir if self._config_dir is not None else config_root() / "btop"

    @property
    def config_path(self) -> Path:
        return self.config_dir / "btop.conf"

    @property
    def themes_dir(self) -> Path:
        return self.config_dir / "themes"

    def detect(self) -> TerminalState:
        installed = shutil.which("btop") is not None or self.config_path.exists()
        return TerminalState(
            installed=installed,
            config_path=self.config_path if installed else None,
            foreign_root=None,
            current=self.current() if installed else None,
            notes=[
                self.reload_semantics.sentence(),
                "btop rewrites its own settings file when it closes, so close it "
                "before applying a look.",
            ],
        )

    def current(self) -> Palette | None:
        """The theme btop is set to, as a name only.

        A btop theme file has no single "foreground" to read back into a
        palette, so this reports the two colours that do map cleanly and leaves
        the rest empty rather than guessing.
        """
        parsed = _parse_kv(self.config_path)
        if parsed is None:
            return None
        theme = (parsed.value("color_theme") or "").strip('"')
        if not theme:
            return None
        entries = _parse_btop_theme(self.themes_dir / f"{theme}.theme")
        if not entries:
            return None
        background = entries.get("main_bg")
        foreground = entries.get("main_fg")
        if not background or not foreground:
            return None
        return read_palette(
            name=theme,
            background=background,
            foreground=foreground,
            cursor=entries.get("hi_fg"),
        )

    def plan(self, palette: Palette) -> TerminalWrites:
        confine(self.config_dir)
        slug = slugify(palette.name)
        theme = confine(self.themes_dir / f"{slug}.theme")

        parsed = _parse_kv(self.config_path) or KeyValueFile.parse("")
        parsed.set("color_theme", f'"{slug}"')
        if palette.opacity < 1.0:
            # Let the terminal's own glass show through the gauges instead of
            # painting a second background on top of it.
            parsed.set("theme_background", "False")
        return TerminalWrites(
            files=(
                FileChange(str(theme), render_btop_theme(palette).encode("utf-8")),
                FileChange(str(confine(self.config_path)), parsed.render().encode("utf-8")),
            )
        )


class CavaAdapter:
    """Theme cava: rewrite the gradient in the ``[color]`` section."""

    id = "cava"
    name = "cava audio visualiser"
    reload_semantics = ReloadSemantics.RESTART

    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = Path(config_path) if config_path is not None else None

    @property
    def config_path(self) -> Path:
        if self._config_path is not None:
            return self._config_path
        return config_root() / "cava" / "config"

    def detect(self) -> TerminalState:
        installed = shutil.which("cava") is not None or self.config_path.exists()
        return TerminalState(
            installed=installed,
            config_path=self.config_path if installed else None,
            foreign_root=None,
            current=self.current() if installed else None,
            notes=[self.reload_semantics.sentence()],
        )

    def current(self) -> Palette | None:
        """cava has a gradient, not a palette — so this reports None."""
        return None

    def gradient(self) -> list[str]:
        """The gradient cava is currently set to, bottom to top."""
        parsed = _parse_ini(self.config_path)
        if parsed is None:
            return []
        try:
            count = int(parsed.value("color", "gradient_count") or 0)
        except ValueError:
            return []
        found = []
        for index in range(1, count + 1):
            value = parsed.value("color", f"gradient_color_{index}")
            if value:
                found.append(value.strip("'\""))
        return found

    def plan(self, palette: Palette) -> TerminalWrites:
        path = confine(self.config_path)
        text = _read_text(path) or ""
        parsed = IniFile.parse(text)
        colours = cava_gradient(palette)
        # Old stops have to go first: a shorter gradient would otherwise keep a
        # stale colour above its own top.
        parsed.remove_prefixed("color", "gradient_color_")
        parsed.set("color", "gradient", "1")
        parsed.set("color", "gradient_count", str(len(colours)))
        for index, colour in enumerate(colours, start=1):
            # cava wraps its colours in apostrophes and has no escape for one.
            safe = one_line(colour, what=f"gradient colour {index}", forbid="'")
            parsed.set("color", f"gradient_color_{index}", f"'{safe}'")
        return TerminalWrites(files=(FileChange(str(path), parsed.render().encode("utf-8")),))


class FastfetchAdapter:
    """Recolour fastfetch's logo slots and its key/value colours.

    ``config.jsonc`` is JSON *with comments*, which no JSON parser will read
    back out again unchanged — so the file is edited as text, by finding the
    colour objects and replacing the values inside them. Comments, key order,
    and every module in the config survive.
    """

    id = "fastfetch"
    name = "fastfetch"
    reload_semantics = ReloadSemantics.ONE_SHOT

    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = Path(config_path) if config_path is not None else None

    @property
    def config_path(self) -> Path:
        if self._config_path is not None:
            return self._config_path
        return config_root() / "fastfetch" / "config.jsonc"

    def detect(self) -> TerminalState:
        installed = shutil.which("fastfetch") is not None or self.config_path.exists()
        return TerminalState(
            installed=installed,
            config_path=self.config_path if installed else None,
            foreign_root=None,
            current=None,
            notes=[self.reload_semantics.sentence()],
        )

    def current(self) -> Palette | None:
        """None: a logo's numbered colour slots are not a palette."""
        return None

    def plan(self, palette: Palette) -> TerminalWrites:
        """Replace the colour values, leaving the structure exactly as it was.

        Raises:
            PermissionError: the config has no colour block to recolour. Adding
                one would mean inventing a logo the user never chose, so gtheme
                says so instead of guessing.
        """
        path = confine(self.config_path)
        text = _read_text(path)
        if text is None:
            raise PermissionError(
                "fastfetch has no settings file yet, so gtheme has nothing to recolour."
            )
        ramp = _fastfetch_ramp(palette)
        updated = _recolour_json_block(text, ("logo", "color"), ramp)
        display = {
            "keys": _sgr(_slot(palette, 6, palette.foreground)),
            "output": _sgr(palette.foreground),
        }
        updated = _recolour_json_block(updated, ("display", "color"), display)
        if updated == text:
            raise PermissionError(
                "fastfetch's settings file has no colours gtheme knows how to change."
            )
        return TerminalWrites(files=(FileChange(str(path), updated.encode("utf-8")),))


# -- shared file helpers ---------------------------------------------------


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _parse_kv(path: Path) -> KeyValueFile | None:
    text = _read_text(path)
    return None if text is None else KeyValueFile.parse(text)


def _parse_ini(path: Path) -> IniFile | None:
    text = _read_text(path)
    return None if text is None else IniFile.parse(text)


_BTOP_ENTRY_RE = re.compile(r'theme\[([a-z_]+)\]\s*=\s*"([^"]*)"')


def _parse_btop_theme(path: Path) -> dict[str, str]:
    text = _read_text(path)
    if text is None:
        return {}
    return dict(_BTOP_ENTRY_RE.findall(text))


def _sgr(colour: str) -> str:
    """A truecolour SGR sequence — what fastfetch configs use for exact colours.

    Every spelling :class:`~gtheme.terminal.model.Palette` accepts is handled
    by the shared :func:`~gtheme.terminal.model.hex6`: ``#abc`` is spelled out,
    and the alpha of an eight-digit colour is dropped because a terminal escape
    has nowhere to put it.
    """
    value = hex6(colour).lstrip("#")
    red, green, blue = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    return f"38;2;{red};{green};{blue}"


def _fastfetch_ramp(palette: Palette) -> dict[str, str]:
    """Colours for the numbered ``$1``-``$9`` slots a logo file uses."""
    fallback = palette.foreground
    slots = (2, 8, 6, 4, 5, 7, 3, 1, 12)
    return {str(index): _sgr(_slot(palette, slot, fallback)) for index, slot in enumerate(slots, 1)}


def _json_block_span(text: str, path: tuple[str, ...]) -> tuple[int, int] | None:
    """The ``{...}`` span of a nested JSON key, matching braces as it goes."""
    start = 0
    end = len(text)
    for key in path:
        match = re.compile(rf'"{re.escape(key)}"\s*:\s*\{{').search(text, start, end)
        if match is None:
            return None
        open_at = match.end() - 1
        depth = 0
        close_at = None
        for index in range(open_at, end):
            char = text[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    close_at = index
                    break
        if close_at is None:
            return None
        start, end = open_at + 1, close_at
    return (start, end)


def _recolour_json_block(text: str, path: tuple[str, ...], values: dict[str, str]) -> str:
    """Replace the string values of known keys inside one JSON object."""
    span = _json_block_span(text, path)
    if span is None:
        return text
    start, end = span
    block = text[start:end]
    for key, value in values.items():
        pattern = re.compile(rf'("{re.escape(key)}"\s*:\s*")[^"]*(")')
        block, count = pattern.subn(rf"\g<1>{value}\g<2>", block, count=1)
        if not count:
            continue
    return text[:start] + block + text[end:]
