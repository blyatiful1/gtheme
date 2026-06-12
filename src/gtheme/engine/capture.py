"""`gtheme capture` — freeze the current live config into a new theme.

This is the reverse of apply: it snapshots a curated set of dotfiles and
GNOME settings as they are *right now* into a fresh theme directory, so you can
tweak your desktop by hand and then bottle it. The captured theme is a starting
point — refine its manifest and palette afterwards.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from ..paths import INSTALLED_THEMES_DIR, expand_dest
from ..settings import ResolvedSetting, gsettings_get
from ..manifest import Setting

# (component, live dest, theme-relative path under files/)
_FILES = [
    ("terminal", "~/.config/alacritty/alacritty.toml", "files/alacritty/alacritty.toml"),
    ("prompt", "~/.config/starship.toml", "files/starship.toml"),
    ("shell-cfg", "~/.config/fish/config.fish", "files/fish/config.fish"),
    ("monitor", "~/.config/btop/btop.conf", "files/btop/btop.conf"),
    ("editor", "~/.config/micro/settings.json", "files/micro/settings.json"),
    ("gtk", "~/.config/gtk-4.0/gtk.css", "files/gtk/gtk4.css"),
    ("gtk", "~/.config/gtk-3.0/gtk.css", "files/gtk/gtk3.css"),
]

# (component, backend, key)
_SETTINGS = [
    ("desktop", "gsettings", "org.gnome.desktop.interface accent-color"),
    ("wallpaper", "gsettings", "org.gnome.desktop.background picture-uri"),
    ("wallpaper", "gsettings", "org.gnome.desktop.background picture-uri-dark"),
    ("wallpaper", "gsettings", "org.gnome.desktop.background picture-options"),
    ("wallpaper", "gsettings", "org.gnome.desktop.background primary-color"),
]


def _toml_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def capture(name: str, title: str | None = None, dest_dir: Path | None = None) -> tuple[Path, list[str]]:
    target = (dest_dir or INSTALLED_THEMES_DIR) / name
    if target.exists():
        raise FileExistsError(f"theme already exists: {target}")
    notes: list[str] = []

    file_entries: list[tuple[str, str, str]] = []
    for component, live, rel in _FILES:
        src = expand_dest(live)
        if not src.is_file():
            notes.append(f"skipped {live} (not present)")
            continue
        out = target / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)
        file_entries.append((component, rel, live))

    setting_entries: list[tuple[str, str, str, str]] = []
    for component, backend, key in _SETTINGS:
        stub = Setting(component=component, backend=backend, key=key, value="")
        rs = ResolvedSetting(stub)
        cur = rs.get_current()
        if cur is None:
            notes.append(f"skipped {key} (unset)")
            continue
        setting_entries.append((component, backend, key, cur))

    lines = [
        f"# {title or name} — captured from the live system by `gtheme capture`.",
        "# Review the files/, settings, and add a palette.toml before sharing.\n",
        "[meta]",
        f'name = "{name}"',
        f'title = {_toml_str(title or name)}',
        'description = "Captured from a live GNOME session."',
        'version = "0.1.0"\n',
    ]
    for component, rel, live in file_entries:
        lines += ["[[files]]", f'component = {_toml_str(component)}',
                  f'src = {_toml_str(rel)}', f'dest = {_toml_str(live)}', ""]
    for component, backend, key, value in setting_entries:
        lines += ["[[settings]]", f'component = {_toml_str(component)}',
                  f'backend = {_toml_str(backend)}', f'key = {_toml_str(key)}',
                  f'value = {_toml_str(value)}', ""]
    (target / "theme.toml").write_text("\n".join(lines))
    return target, notes
