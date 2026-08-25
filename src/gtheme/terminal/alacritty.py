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
from .model import Palette, ReloadSemantics, TerminalState

__all__ = ["AlacrittyAdapter", "render_colors_toml"]

_ANSI_NAMES = ("black", "red", "green", "yellow", "blue", "magenta", "cyan", "white")
_IMPORT_RE = re.compile(r"^[ \t]*import[ \t]*=[ \t]*\[.*?\]", re.DOTALL | re.MULTILINE)
_QUOTED_RE = re.compile(r'"([^"]*)"')


def render_colors_toml(palette: Palette) -> str:
    """The colours file gtheme owns. Regenerated whole every time."""
    cursor = palette.cursor or palette.foreground
    lines = [
        f"# {palette.name} — written by gtheme. This file is regenerated; edit",
        "# alacritty.toml instead if you want to keep a change.",
        "",
        "[colors.primary]",
        f'background = "{palette.background}"',
        f'foreground = "{palette.foreground}"',
        "",
        "[colors.cursor]",
        f'cursor = "{cursor}"',
        f'text = "{palette.background}"',
    ]
    if palette.ansi:
        for offset, section in ((0, "normal"), (8, "bright")):
            lines.extend(["", f"[colors.{section}]"])
            for index, key in enumerate(_ANSI_NAMES):
                lines.append(f'{key} = "{palette.ansi[offset + index]}"')
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
        """Write the colours file, then make sure the config imports it."""
        confine(self.config_dir)
        colours = confine(self.colors_path(palette.name))
        atomic_write_text(colours, render_colors_toml(palette))

        text = _read_text(self.config_path) or ""
        text = _set_import(text, f"~/.config/alacritty/{colours.name}")
        parsed = IniFile.parse(text)
        parsed.set("window", "opacity", f"{palette.opacity:g}")
        parsed.set("window", "blur", "true" if palette.opacity < 1.0 else "false")
        atomic_write_text(confine(self.config_path), parsed.render())

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
    return Palette(
        name=name,
        background=str(background),
        foreground=str(foreground),
        cursor=(table.get("cursor", {}) or {}).get("cursor"),
        ansi=tuple(ansi) if len(ansi) == 16 else (),
        opacity=opacity,
    )
