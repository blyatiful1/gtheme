"""Alacritty — the one that reloads itself.

Alacritty watches its own config file and picks up changes on save, so a look
applied here shows up in windows that are already open, without the user doing
anything. That is worth saying out loud on the page: it is the difference
between "done" and "done, now go and reload your terminal".

The colours are written to a separate file — ``gtheme-<look>.toml`` — which the
main ``alacritty.toml`` imports. That keeps gtheme's writes in one file it owns
completely, and leaves the config the user actually maintains holding a single
line of gtheme's making. Two settings do have to live in the main file, because
Alacritty does not read them from an import in a way that survives being
overridden: the window opacity, and the compositor blur request (which, unlike
ghostty's, is real on this desktop).
"""

from __future__ import annotations

import re
import shutil
import tomllib
from pathlib import Path

from .fsio import atomic_write_text, config_root, confine
from .ghostty import slugify
from .kv import IniFile
from .model import Palette, ReloadSemantics, TerminalState, one_line, read_palette, toml_string

__all__ = ["AlacrittyAdapter", "render_colors_toml"]

_ANSI_NAMES = ("black", "red", "green", "yellow", "blue", "magenta", "cyan", "white")
_IMPORT_RE = re.compile(r"^[ \t]*import[ \t]*=[ \t]*\[.*?\]", re.DOTALL | re.MULTILINE)
_QUOTED_RE = re.compile(r'"([^"]*)"')
_TABLE_HEADER_RE = re.compile(r"^[ \t]*\[", re.MULTILINE)


def render_colors_toml(palette: Palette) -> str:
    """The colours file gtheme owns. Regenerated whole every time.

    Every value goes through :func:`~gtheme.terminal.model.toml_string`, so a
    colour that is somehow not a colour lands as an escaped string rather than
    closing gtheme's quote and opening a table of its own.
    """
    cursor = palette.cursor or palette.foreground
    lines = [
        f"# {one_line(palette.name, what='the look name')} — written by gtheme. "
        "This file is regenerated; edit",
        "# alacritty.toml instead if you want to keep a change.",
        "",
        "[colors.primary]",
        f"background = {toml_string(palette.background)}",
        f"foreground = {toml_string(palette.foreground)}",
        "",
        "[colors.cursor]",
        f"cursor = {toml_string(cursor)}",
        f"text = {toml_string(palette.background)}",
    ]
    if palette.ansi:
        for offset, section in ((0, "normal"), (8, "bright")):
            lines.extend(["", f"[colors.{section}]"])
            for index, key in enumerate(_ANSI_NAMES):
                lines.append(f"{key} = {toml_string(palette.ansi[offset + index])}")
    return "\n".join(lines) + "\n"


class AlacrittyAdapter:
    """Restyle Alacritty by writing a colours file and importing it."""

    id = "alacritty"
    name = "Alacritty"
    reload_semantics = ReloadSemantics.AUTO_RELOAD

    def __init__(self, config_dir: Path | None = None) -> None:
        self._config_dir = Path(config_dir) if config_dir is not None else None

    @property
    def config_dir(self) -> Path:
        return self._config_dir if self._config_dir is not None else config_root() / "alacritty"

    @property
    def config_path(self) -> Path:
        return self.config_dir / "alacritty.toml"

    def colors_path(self, palette_name: str) -> Path:
        return self.config_dir / f"gtheme-{slugify(palette_name)}.toml"

    # -- the protocol ------------------------------------------------------

    def detect(self) -> TerminalState:
        installed = shutil.which("alacritty") is not None or self.config_path.exists()
        return TerminalState(
            installed=installed,
            config_path=self.config_path if installed else None,
            foreign_root=None,
            current=self.current() if installed else None,
            notes=[self.reload_semantics.sentence()],
        )

    def current(self) -> Palette | None:
        config = self._load(self.config_path)
        if config is None:
            return None
        opacity = _as_float(config.get("window", {}).get("opacity"), 1.0)
        imports = config.get("general", {}).get("import") or config.get("import") or []
        for entry in imports:
            path = Path(str(entry)).expanduser()
            if not path.name.startswith("gtheme-"):
                continue
            # The written entry is "~/.config/alacritty/…" because that is what
            # Alacritty itself has to be able to follow. Under a test
            # destination root that expands to the real home, so the file is
            # also looked up beside the config it was imported from.
            for candidate in (path, self.config_dir / path.name):
                colours = self._load(candidate)
                if colours is None:
                    continue
                palette = _palette_from(colours, name=path.stem[len("gtheme-") :], opacity=opacity)
                if palette is not None:
                    return palette
        return None

    def apply(self, palette: Palette) -> None:
        """Write the colours file, then make sure the config imports it.

        The edit to ``alacritty.toml`` is worked out in full *before* anything
        is written, and refused if it would leave a file Alacritty cannot read
        — a config that does not parse costs the user their whole terminal
        setup, which is far worse than a look that did not apply.

        Raises:
            ValueError: the edit would have broken a config that parsed before.
        """
        confine(self.config_dir)
        colours = confine(self.colors_path(palette.name))
        rendered = render_colors_toml(palette)

        original = _read_text(self.config_path) or ""
        text = _set_import(original, f"~/.config/alacritty/{colours.name}")
        text = _set_window(
            text,
            {
                "opacity": f"{palette.opacity:g}",
                "blur": "true" if palette.opacity < 1.0 else "false",
            },
        )
        _refuse_if_broken(original, text)

        atomic_write_text(colours, rendered)
        atomic_write_text(confine(self.config_path), text)

    # -- helpers -----------------------------------------------------------

    def _load(self, path: Path) -> dict | None:
        try:
            return tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            return None


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _set_import(text: str, entry: str) -> str:
    """Ensure ``entry`` is the only gtheme file in the import list.

    Alacritty's import list may be written across several lines, which is why
    this is a span replacement rather than a line edit: rewriting the first line
    of a multi-line array and leaving the rest behind would produce a config
    Alacritty refuses to load. Every non-gtheme entry keeps its place and its
    order; a previous gtheme look is dropped so two palettes cannot fight.
    """
    match = _IMPORT_RE.search(text)
    existing = [] if match is None else _QUOTED_RE.findall(match.group(0))
    kept = [item for item in existing if not Path(item).name.startswith("gtheme-")]
    kept.append(entry)
    rendered = "import = [" + ", ".join(f'"{item}"' for item in kept) + "]"
    if match is not None:
        return text[: match.start()] + rendered + text[match.end() :]
    prefix = text if text.endswith("\n") or not text else text + "\n"
    if "[general]" in text:
        return re.sub(r"^\[general\][ \t]*$", f"[general]\n{rendered}", prefix, count=1, flags=re.M)
    return prefix + ("\n" if prefix else "") + "[general]\n" + rendered + "\n"


def _head_end(text: str) -> int:
    """Where the top-level part of a TOML file stops: the first table header.

    Everything after that belongs to some table, so a ``window.opacity`` line
    down there is not the ``window`` table gtheme is looking for.
    """
    match = _TABLE_HEADER_RE.search(text)
    return match.start() if match else len(text)


def _inline_span(text: str, start: int) -> tuple[int, int] | None:
    """The inside of the ``{...}`` that begins at ``start``, braces matched."""
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return (start + 1, index)
    return None


def _inline_items(body: str) -> list[str]:
    """The key/value pairs of an inline table, split on its own commas.

    Splitting on every comma would cut ``padding = { x = 4, y = 4 }`` in half,
    so the depth is counted as it goes.
    """
    items: list[str] = []
    depth = 0
    current = ""
    for char in body:
        if char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
        if char == "," and depth == 0:
            items.append(current)
            current = ""
            continue
        current += char
    if current.strip():
        items.append(current)
    return [item for item in items if item.strip()]


def _set_inline(body: str, values: dict[str, str]) -> str:
    """Set keys inside an inline table, keeping every other pair as it was."""
    items = _inline_items(body)
    remaining = dict(values)
    rendered: list[str] = []
    for item in items:
        key, sep, _ = item.partition("=")
        name = key.strip().strip('"').strip("'")
        if sep and name in remaining:
            rendered.append(f"{name} = {remaining.pop(name)}")
        else:
            rendered.append(item.strip())
    rendered.extend(f"{key} = {value}" for key, value in remaining.items())
    return " " + ", ".join(rendered) + " "


def _set_dotted(head: str, table: str, values: dict[str, str]) -> str:
    """Set ``table.key`` lines in the top-level part of the file."""
    for key, value in values.items():
        dotted = rf"^[ \t]*{re.escape(table)}\.{re.escape(key)}[ \t]*=.*$"
        pattern = re.compile(dotted, re.MULTILINE)
        line = f"{table}.{key} = {value}"
        if pattern.search(head):
            head = pattern.sub(line, head, count=1)
            continue
        anchor = None
        for match in re.finditer(rf"^[ \t]*{re.escape(table)}\.[^=\n]*=.*$", head, re.MULTILINE):
            anchor = match
        if anchor is not None:
            head = head[: anchor.end()] + "\n" + line + head[anchor.end() :]
        else:
            head = head + ("" if not head or head.endswith("\n") else "\n") + line + "\n"
    return head


def _set_window(text: str, values: dict[str, str]) -> str:
    """Set keys of the ``window`` table, however the user wrote that table.

    ``alacritty.toml`` is TOML, and TOML lets one table be spelled three ways:
    a ``[window]`` section, an inline ``window = { … }``, or dotted
    ``window.opacity =`` lines. The line-based :class:`~gtheme.terminal.kv.IniFile`
    only knows the first, and used to append a ``[window]`` section beside the
    other two — declaring the same table twice, which TOML forbids and
    Alacritty refuses, costing the user their whole config to apply a look.
    So the shape is worked out first, and the edit is made in the shape that is
    already there.
    """
    head_end = _head_end(text)
    head, tail = text[:head_end], text[head_end:]

    if re.search(r"^[ \t]*\[window\][ \t]*$", text, re.MULTILINE):
        parsed = IniFile.parse(text)
        for key, value in values.items():
            parsed.set("window", key, value)
        return parsed.render()

    inline = re.search(r"^[ \t]*window[ \t]*=[ \t]*\{", head, re.MULTILINE)
    if inline is not None:
        span = _inline_span(head, inline.end() - 1)
        if span is not None:
            start, end = span
            return head[:start] + _set_inline(head[start:end], values) + head[end:] + tail
    if re.search(r"^[ \t]*window\.[^=\n]*=", head, re.MULTILINE):
        return _set_dotted(head, "window", values) + tail

    parsed = IniFile.parse(text)
    for key, value in values.items():
        parsed.set("window", key, value)
    return parsed.render()


def _refuse_if_broken(original: str, rendered: str) -> None:
    """Refuse an edit that would leave a config Alacritty cannot read.

    A config that was already broken is not made gtheme's problem — the edit
    goes ahead, because refusing would mean a user with one stray line could
    never apply a look again. What is refused is *breaking* one that worked.

    Raises:
        ValueError: the file parsed before the edit and does not after.
    """
    if _parses(original) and not _parses(rendered):
        raise ValueError(
            "gtheme could not change your Alacritty settings without breaking "
            "them, so it has not changed anything."
        )


def _parses(text: str) -> bool:
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return False
    return True


def _as_float(value: object, fallback: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


def _palette_from(colours: dict, *, name: str, opacity: float) -> Palette | None:
    table = colours.get("colors", {})
    primary = table.get("primary", {})
    background = primary.get("background")
    foreground = primary.get("foreground")
    if not background or not foreground:
        return None
    ansi: list[str] = []
    for section in ("normal", "bright"):
        block = table.get(section, {})
        ansi.extend(str(block[key]) for key in _ANSI_NAMES if key in block)
    return read_palette(
        name=name,
        background=str(background),
        foreground=str(foreground),
        cursor=(table.get("cursor", {}) or {}).get("cursor"),
        ansi=tuple(ansi) if len(ansi) == 16 else (),
        opacity=opacity,
    )
