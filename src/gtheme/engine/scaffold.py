"""`gtheme new` — scaffold a fresh theme from a palette."""

from __future__ import annotations

import tomllib
from pathlib import Path

from ..color import is_dark
from ..paths import INSTALLED_THEMES_DIR, safe_theme_name
from ..registry import find

_DEFAULT_PALETTE = """# {name} palette — define your colours here, then run `gtheme build {name}`.
# Structural roles
bg = "#101014"
surface1 = "#16161c"
surface2 = "#22222c"
fg = "#e6e6ea"
fg_dim = "#9a9aa6"
fg_bright = "#ffffff"
accent = "#7aa2f7"
accent_bright = "#9cb8ff"
selection = "#2a2a38"
comment = "#5a5a6a"
warn = "#e0a13b"
info = "#6d8fb3"
error = "#e0563b"
# ANSI terminal hues
ansi_black = "#1a1a22"
red = "#e0563b"
green = "#7da862"
yellow = "#e0a13b"
blue = "#6d8fb3"
magenta = "#b27e93"
cyan = "#6fa8a3"
ansi_white = "#c9c9d2"
"""


# Appended when the seeded palette is dark — vanilla GNOME defaults to the
# light scheme, and a dark theme without this looks half-applied there.
_DARK_SCHEME_SETTING = """
[[settings]]
component = "desktop"
backend = "gsettings"
key = "org.gnome.desktop.interface color-scheme"
value = "'prefer-dark'"
"""


def _manifest(name: str, title: str, *, dark: bool = False) -> str:
    Name = name.capitalize()
    manifest = f"""# {title} — scaffolded by `gtheme new`. Palette lives in palette.toml;
# `gtheme build {name}` renders the files/ below from it.

[meta]
name = "{name}"
title = "{title}"
description = ""
author = ""
version = "0.1.0"

[requires]
packages = ["alacritty", "btop", "micro"]

[build]
managed = ["terminal", "monitor", "editor", "gtk"]

[[files]]
component = "terminal"
src = "files/alacritty/{name}.toml"
dest = "~/.config/alacritty/{name}.toml"

[[files]]
component = "terminal"
src = "files/ptyxis/{Name}.palette"
dest = "~/.local/share/org.gnome.Ptyxis/palettes/{Name}.palette"

[[files]]
component = "monitor"
src = "files/btop/{name}.theme"
dest = "~/.config/btop/themes/{name}.theme"

[[files]]
component = "editor"
src = "files/micro/{name}.micro"
dest = "~/.config/micro/colorschemes/{name}.micro"

[[files]]
component = "gtk"
src = "files/gtk/gtk.css"
dest = "~/.config/gtk-4.0/gtk.css"

[[files]]
component = "gtk"
src = "files/gtk/gtk.css"
dest = "~/.config/gtk-3.0/gtk.css"

# Terminal palette selection (Ptyxis). The accent below is a GNOME enum
# (blue|teal|green|yellow|orange|red|pink|purple|slate) — pick the nearest.
[[settings]]
component = "terminal"
backend = "dconf"
key = "/org/gnome/Ptyxis/Profiles/{{{{ ptyxis_default_profile }}}}/palette"
value = "'{Name}'"

[[settings]]
component = "desktop"
backend = "gsettings"
key = "org.gnome.desktop.interface accent-color"
value = "'blue'"
"""
    if dark:
        manifest += _DARK_SCHEME_SETTING
    return manifest


def _palette_is_dark(palette_path: Path) -> bool:
    """Best-effort: does the seeded palette have a dark ``bg``?"""
    try:
        bg = tomllib.loads(palette_path.read_text(encoding="utf-8")).get("bg")
        return isinstance(bg, str) and is_dark(bg)
    except (OSError, tomllib.TOMLDecodeError, ValueError):
        return False


def new_theme(name: str, from_base: str | None = None, title: str | None = None,
              dest_dir: Path | None = None) -> Path:
    name = safe_theme_name(name)
    target = (dest_dir or INSTALLED_THEMES_DIR) / name
    if target.exists():
        raise FileExistsError(f"theme already exists: {target}")
    target.mkdir(parents=True)

    # palette: copy from a base theme, or write the default.
    if from_base:
        base = find(from_base)
        if base is None:
            raise FileNotFoundError(f"--from theme not found: {from_base}")
        base_palette = base / "palette.toml"
        if base_palette.is_file():
            (target / "palette.toml").write_text(base_palette.read_text())
        else:
            (target / "palette.toml").write_text(_DEFAULT_PALETTE.format(name=name))
    else:
        (target / "palette.toml").write_text(_DEFAULT_PALETTE.format(name=name))

    dark = _palette_is_dark(target / "palette.toml")
    (target / "theme.toml").write_text(_manifest(name, title or name, dark=dark))
    return target
