"""`gtheme capture` — freeze the current live config into a new theme.

This is the reverse of apply: it snapshots the desktop look you have *right now*
into a fresh theme directory, so you can tweak GNOME by hand and then bottle it
up to back up or share. Coverage is comprehensive — it captures the full set of
files and gsettings/dconf keys that any gtheme theme can manage (derived from
the union of all installed/bundled theme manifests, plus a curated baseline) and
records whatever is actually present/set.

The captured theme is a starting point — refine its manifest and add a palette
afterwards. Use ``gtheme export`` to bundle it into a single shareable archive.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from urllib.parse import unquote, urlparse

from ..paths import DEST_ROOT, INSTALLED_THEMES_DIR, expand_dest, safe_theme_name
from ..settings import ResolvedSetting
from ..manifest import Setting

# Standard user-config files a theme controls (component, live dest, theme-rel
# path). Theme-specific variants, wallpapers, and theme-provided assets (ascii,
# bin, shell svgs) are intentionally excluded — wallpapers are bundled from the
# live background URI below, the rest are theme content, not captured user state.
_CURATED_FILES = [
    ("terminal", "~/.config/alacritty/alacritty.toml", "files/alacritty/alacritty.toml"),
    ("prompt", "~/.config/starship.toml", "files/starship.toml"),
    ("shell-cfg", "~/.config/fish/config.fish", "files/fish/config.fish"),
    ("monitor", "~/.config/btop/btop.conf", "files/btop/btop.conf"),
    ("editor", "~/.config/micro/settings.json", "files/micro/settings.json"),
    ("gtk", "~/.config/gtk-4.0/gtk.css", "files/gtk/gtk4.css"),
    ("gtk", "~/.config/gtk-3.0/gtk.css", "files/gtk/gtk3.css"),
    ("fastfetch", "~/.config/fastfetch/config.jsonc", "files/fastfetch/config.jsonc"),
]

# Curated baseline of high-value settings so capture works even with no themes
# installed. The full long tail (every extension knob) is merged in from the
# installed/bundled theme manifests at runtime — see _setting_targets().
_CURATED_SETTINGS = [
    ("desktop", "gsettings", "org.gnome.desktop.interface accent-color"),
    ("desktop", "gsettings", "org.gnome.desktop.interface color-scheme"),
    ("desktop", "gsettings", "org.gnome.desktop.interface icon-theme"),
    ("desktop", "gsettings", "org.gnome.desktop.interface gtk-theme"),
    ("desktop", "gsettings", "org.gnome.desktop.interface cursor-theme"),
    ("desktop", "gsettings", "org.gnome.desktop.interface cursor-size"),
    ("desktop", "gsettings", "org.gnome.desktop.interface font-name"),
    ("desktop", "gsettings", "org.gnome.desktop.interface monospace-font-name"),
    ("desktop", "gsettings", "org.gnome.desktop.interface document-font-name"),
    ("shell", "gsettings", "org.gnome.shell enabled-extensions"),
    ("wallpaper", "gsettings", "org.gnome.desktop.background picture-uri"),
    ("wallpaper", "gsettings", "org.gnome.desktop.background picture-uri-dark"),
    ("wallpaper", "gsettings", "org.gnome.desktop.background picture-options"),
    ("wallpaper", "gsettings", "org.gnome.desktop.background primary-color"),
    ("wallpaper", "gsettings", "org.gnome.desktop.background secondary-color"),
]

# Keys whose value is a wallpaper file:// URI we try to bundle.
_WALLPAPER_URI_KEYS = {
    "org.gnome.desktop.background picture-uri",
    "org.gnome.desktop.background picture-uri-dark",
}


def _toml_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _retemplatize_home(value: str) -> str:
    """Replace the literal home path with {{ home }} so the value is portable."""
    home = str(DEST_ROOT)
    if home and home in value:
        return value.replace(home, "{{ home }}")
    return value


def _setting_targets() -> list[tuple[str, str, str]]:
    """The (component, backend, key) settings to try capturing, de-duplicated.

    Curated baseline first, then the union of every setting key used by any
    installed/bundled theme manifest — so capture covers the full surface that
    gtheme themes can manage (all extension knobs, fonts, cursor, etc.).
    """
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str, str]] = []

    def add(component: str, backend: str, key: str) -> None:
        ident = (backend, key)
        if ident not in seen:
            seen.add(ident)
            out.append((component, backend, key))

    for component, backend, key in _CURATED_SETTINGS:
        add(component, backend, key)
    try:
        from ..registry import load_all

        themes, _ = load_all()
        for t in themes:
            for s in t.settings:
                add(s.component, s.backend, s.key)
    except Exception:  # noqa: BLE001 — capture must work even if discovery fails
        pass
    return out


def _local_file_from_uri(value: str) -> Path | None:
    """If ``value`` is a GVariant string wrapping a local ``file://`` URI,
    return the referenced filesystem path, else None."""
    inner = value.strip().strip("'").strip('"')
    if not inner.startswith("file://"):
        return None
    parsed = urlparse(inner)
    if parsed.netloc not in ("", "localhost"):
        return None  # remote / non-local host
    return Path(unquote(parsed.path))


def capture(name: str, title: str | None = None, dest_dir: Path | None = None) -> tuple[Path, list[str]]:
    name = safe_theme_name(name)
    target = (dest_dir or INSTALLED_THEMES_DIR) / name
    if target.exists():
        raise FileExistsError(f"theme already exists: {target}")
    # Create the theme dir up front: even if no curated files are present (a
    # minimal/headless box), we still write a valid theme.toml below.
    target.mkdir(parents=True)
    notes: list[str] = []

    # --- files: copy each present curated config file into the theme ---
    file_entries: list[tuple[str, str, str]] = []
    bundled_wallpapers: dict[str, str] = {}  # source path -> theme-relative dest
    for component, live, rel in _CURATED_FILES:
        src = expand_dest(live)
        if not src.is_file():
            notes.append(f"skipped {live} (not present)")
            continue
        out = target / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)
        file_entries.append((component, rel, live))

    # --- settings: snapshot the current value of every manageable key set ---
    setting_entries: list[tuple[str, str, str, str]] = []
    for component, backend, key in _setting_targets():
        stub = Setting(component=component, backend=backend, key=key, value="")
        rs = ResolvedSetting(stub)
        if "{{" in rs.key:
            # An unresolved token (e.g. Ptyxis not present) — can't read it.
            continue
        cur = rs.get_current()
        if cur is None:
            continue
        if key in _WALLPAPER_URI_KEYS:
            cur = _bundle_wallpaper(cur, key, target, file_entries, bundled_wallpapers, notes)
        else:
            cur = _retemplatize_home(cur)
        setting_entries.append((component, backend, key, cur))

    # --- write the manifest ---
    lines = [
        f"# {title or name} — captured from the live system by `gtheme capture`.",
        "# Review the files/, settings, and add a palette.toml before sharing.",
        f"# Captured {len(file_entries)} file(s) and {len(setting_entries)} setting(s).\n",
        "[meta]",
        f'name = "{name}"',
        f"title = {_toml_str(title or name)}",
        'description = "Captured from a live GNOME session."',
        'version = "0.1.0"\n',
    ]
    for component, rel, live in file_entries:
        lines += ["[[files]]", f"component = {_toml_str(component)}",
                  f"src = {_toml_str(rel)}", f"dest = {_toml_str(live)}", ""]
    for component, backend, key, value in setting_entries:
        lines += ["[[settings]]", f"component = {_toml_str(component)}",
                  f"backend = {_toml_str(backend)}", f"key = {_toml_str(key)}",
                  f"value = {_toml_str(value)}", ""]
    (target / "theme.toml").write_text("\n".join(lines), encoding="utf-8")
    notes.append(f"captured {len(file_entries)} file(s) and {len(setting_entries)} setting(s)")
    return target, notes


def _bundle_wallpaper(
    value: str,
    key: str,
    target: Path,
    file_entries: list[tuple[str, str, str]],
    bundled: dict[str, str],
    notes: list[str],
) -> str:
    """Bundle a local wallpaper image into the theme and rewrite its URI.

    For a local ``file://`` image, copy it under ``files/wallpaper/``, emit a
    ``[[files]]`` entry, and rewrite the captured URI to use ``{{ home }}`` so
    the theme is shareable. ``.xml`` slideshows and non-local URIs are left
    as-is (just noted). Returns the (possibly rewritten) GVariant value.
    """
    src = _local_file_from_uri(value)
    if src is None:
        notes.append(f"{key}: wallpaper URI is not a local file, left as-is")
        return _retemplatize_home(value)
    if src.suffix.lower() == ".xml":
        notes.append(
            f"{key}: wallpaper is an .xml slideshow ({src}); not bundled, "
            "may reference other paths"
        )
        return _retemplatize_home(value)
    if not src.is_file():
        notes.append(f"{key}: wallpaper {src} not found, left as-is")
        return _retemplatize_home(value)

    key_src = str(src)
    dedup = key_src in bundled
    if dedup:
        rel = bundled[key_src]
    else:
        rel = f"files/wallpaper/{src.name}"
        out = target / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        # Avoid clobbering a different image that happens to share a name.
        if out.exists() and not _same_file(src, out):
            stem, suffix = src.stem, src.suffix
            i = 1
            while True:
                rel = f"files/wallpaper/{stem}-{i}{suffix}"
                out = target / rel
                if not out.exists() or _same_file(src, out):
                    break
                i += 1
            out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)
        bundled[key_src] = rel

    dest = f"~/.local/share/backgrounds/{target.name}/{Path(rel).name}"
    if not dedup:  # one [[files]] entry per distinct bundled image
        file_entries.append(("wallpaper", rel, dest))
        notes.append(f"{key}: bundled wallpaper {src.name}")
    return f"'file://{{{{ home }}}}/{dest[2:]}'"


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.stat().st_size == b.stat().st_size and a.read_bytes() == b.read_bytes()
    except OSError:
        return False
