"""Convert a v1 theme into a v2 Look.

v1 files do not stay valid, and that is the point. The v1 format had a
``[[hooks]]`` section: a Look could name a shell script and gtheme would run
it. v2 has no such section and no machinery to execute one, which is the only
way the sentence *"Looks only change settings. They can't run programs on your
computer."* can be true rather than aspirational (DESIGN.md A4). If v1 files
merely kept validating, that guarantee would be a comment.

So conversion is a real, lossy step — and every loss is named. The importer
never drops anything silently:

* every hook produces its own warning saying what that hook did,
* a folder used as a file source is called out (v2 copies one file at a time),
* required packages, fonts and third-party tools are listed as things the user
  must install themselves,
* v1's ``enabled-extensions`` list setting becomes the ``[extensions]`` block,
  which is what makes the add-on install offer possible at all.

Nothing here reads the legacy package. The v1 shape is re-declared below, so
the importer keeps working long after the v1 source tree is gone.
"""

from __future__ import annotations

import ast
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .emit import dumps_preset
from .model import (
    Component,
    ExtensionInstallEntry,
    ExtensionsBlock,
    FileEntry,
    Meta,
    Preset,
    SettingEntry,
)

__all__ = [
    "EGO_PKS",
    "ConversionResult",
    "classify_setting",
    "convert_dir",
    "convert_v1",
    "parse_string_list",
    "write_look",
]

#: The gsettings key v1 merged add-ons into. In v2 this is not a setting at
#: all — it is the ``[extensions]`` block, so the app can offer to install what
#: is missing instead of writing the name of an add-on nobody has.
ENABLED_EXTENSIONS_KEY = "org.gnome.shell enabled-extensions"

#: extensions.gnome.org ids for the add-ons the bundled Looks ask for, from
#: research/popular-extensions.md (resolved by uuid through ``extension-info``,
#: never by search — the search endpoint is a fuzzy match and lies). A uuid
#: that is absent here still installs; the id only saves one lookup.
EGO_PKS = {
    "blur-my-shell@aunetx": 3193,
    "dash-to-dock@micxgx.gmail.com": 307,
    "just-perfection-desktop@just-perfection": 3843,
    "user-theme@gnome-shell-extensions.gcampax.github.com": 19,
    "tilingshell@ferrarodomenico.com": 7065,
    "burn-my-windows@schneegans.github.com": 4679,
    "logomenu@aryan_k": 4451,
    "impatience@gfxmonk.net": 277,
    "compiz-windows-effect@hermes83.github.com": 3210,
    "compiz-alike-magic-lamp-effect@hermes83.github.com": 3740,
    "caffeine@patapon.info": 517,
    "Vitals@CoreCoding.com": 1460,
    "clipboard-indicator@tudmotu.com": 779,
    "gsconnect@andyholmes.github.io": 1319,
    "appindicatorsupport@rgcjonas.gmail.com": 615,
    "ding@rastersoft.com": 2087,
    "gtk4-ding@smedius.gitlab.com": 5263,
    "rounded-window-corners@fxgn": 7048,
    "nightthemeswitcher@romainvigier.fr": 2236,
    "space-bar@luchrioh": 5090,
    "tophat@fflewddur.github.io": 5219,
    "dash-to-panel@jderose9.github.com": 1160,
    "arcmenu@arcmenu.com": 3628,
    "clipboard-history@alexsaveau.dev": 4839,
    "hidetopbar@mathieu.bidon.ca": 545,
}

#: Add-ons a Look may ask for that are not on extensions.gnome.org under a
#: known id. They still install by uuid; they just have no numeric id here.
_NO_PK = ("hanabi-extension@jeffshee.github.io", "hotedge@jonathan.jdoda.ca")

#: v1's free-text component strings, mapped onto the closed v2 registry. Used
#: only when the key itself does not say what it is.
_V1_COMPONENTS = {
    "wallpaper": Component.WALLPAPER,
    "terminal": Component.TERMINAL,
    "prompt": Component.TERMINAL,
    "monitor": Component.TERMINAL,
    "visualizer": Component.TERMINAL,
    "fastfetch": Component.TERMINAL,
    "shell-cfg": Component.TERMINAL,
    "editor": Component.OTHER,
    "commands": Component.OTHER,
    "ascii": Component.OTHER,
    "gtk": Component.COLORS,
    "desktop": Component.COLORS,
    "shell": Component.SHELL_THEME,
    "dock": Component.ADDONS,
    "effects": Component.ADDONS,
}

_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


def parse_string_list(text: str) -> list[str]:
    """Read a GVariant string-array literal into a Python list.

    ``"@as []"`` is the empty list written with its type annotation, which is
    what an empty ``as`` prints as; a bare ``[]`` is the same thing. Anything
    that does not parse as a list of strings returns empty rather than raising,
    because a malformed value in a v1 file must not abort the import — it
    becomes a warning at the call site.
    """
    stripped = text.strip()
    if stripped in {"@as []", "[]", ""}:
        return []
    if stripped.startswith("@as "):
        stripped = stripped[4:].strip()
    try:
        parsed = ast.literal_eval(stripped)
    except (ValueError, SyntaxError):
        return []
    if not isinstance(parsed, (list, tuple)):
        return []
    return [str(item) for item in parsed]


def classify_setting(key: str, v1_component: str) -> Component:
    """Which part of the desktop a v1 setting belongs to.

    The key is trusted over v1's ``component`` field, because v1 used that
    field for authoring convenience — magma files the accent colour, the icon
    theme and the system monospace font all under ``desktop`` — while v2 uses
    it to *describe the change to a human*, where those are three different
    sentences.
    """
    lowered = key.lower()
    if "org.gnome.desktop.background" in lowered or "hanabi" in lowered:
        return Component.WALLPAPER
    if "org.gnome.desktop.screensaver" in lowered:
        return Component.WALLPAPER
    if lowered.endswith(" icon-theme"):
        return Component.ICONS
    if lowered.endswith(" cursor-theme") or lowered.endswith(" cursor-size"):
        return Component.CURSOR
    if lowered.endswith("font-name") or "font" in lowered.rsplit(" ", 1)[-1]:
        return Component.FONTS
    if lowered.endswith(" accent-color") or lowered.endswith(" color-scheme"):
        return Component.COLORS
    if lowered.endswith(" gtk-theme"):
        return Component.COLORS
    if "/user-theme/" in lowered or lowered.endswith("user-theme name"):
        return Component.SHELL_THEME
    if "ptyxis" in lowered:
        return Component.TERMINAL
    if "/org/gnome/shell/extensions/" in lowered or lowered.startswith("/io/github/"):
        return Component.ADDONS
    if lowered.startswith("org.gnome.shell "):
        return Component.ADDONS
    return _V1_COMPONENTS.get(v1_component, Component.OTHER)


@dataclass
class ConversionResult:
    """A converted Look and everything that did not survive the conversion.

    Attributes:
        preset: the v2 Look.
        warnings: one sentence per lost or changed thing. Never empty for a
            Look that had hooks — that is the guarantee.
        sources: relative ``src`` paths the converted Look still needs, so a
            caller materialising it knows exactly what to copy.
    """

    preset: Preset
    warnings: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


def _normalise_mode(mode: str | None, warnings: list[str], dest: str) -> str | None:
    """v1 wrote ``"755"``; v2's format is four octal digits, ``"0755"``."""
    if mode is None:
        return None
    text = str(mode)
    if len(text) == 3 and all(c in "01234567" for c in text):
        text = "0" + text
        warnings.append(f"permissions for {dest} written as {text} (v1 wrote {mode})")
    return text


def _pick_screenshots(raw: dict, directory: Path | None) -> list[str]:
    """Find something to show for a Look whose v1 manifest had no pictures.

    v1 had no screenshots field, and v2 requires one, because a Look nobody can
    look at first is precisely the thing this app exists to spare people. A
    ``screenshots/`` folder wins; otherwise the Look's own wallpaper is a
    truthful, if partial, picture of what applying it does.
    """
    if directory is not None:
        shots_dir = directory / "screenshots"
        if shots_dir.is_dir():
            found = sorted(
                f"screenshots/{p.name}"
                for p in shots_dir.iterdir()
                if p.suffix.lower() in _IMAGE_SUFFIXES
            )
            if found:
                return found
    for entry in raw.get("files", []):
        src = str(entry.get("src", ""))
        if entry.get("component") == "wallpaper" and src.lower().endswith(_IMAGE_SUFFIXES):
            return [src]
    for entry in raw.get("files", []):
        src = str(entry.get("src", ""))
        if src.lower().endswith(_IMAGE_SUFFIXES):
            return [src]
    return []


def convert_v1(
    raw: dict,
    *,
    directory: Path | None = None,
    screenshots: list[str] | None = None,
    local_only: frozenset[str] = frozenset(),
) -> ConversionResult:
    """Convert a parsed v1 ``theme.toml`` into a v2 Look.

    Args:
        raw: the v1 document, already read from TOML.
        directory: the theme's folder, when it is available. Used to tell a
            folder source from a file source and to find screenshots; the
            conversion works without it, with weaker warnings.
        screenshots: override the pictures rather than deriving them.
        local_only: uuids that are private add-ons (DESIGN.md F12) — these are
            marked ``source = "local-only"`` so a machine without them gets a
            named skip instead of a download offer for something that is not
            published anywhere.

    Raises:
        ValueError: the v1 document has no ``[meta].name``, or nothing that
            could serve as a picture and none was supplied.
    """
    warnings: list[str] = []
    meta_raw = dict(raw.get("meta", {}))
    name = str(meta_raw.get("name", "")).strip()
    if not name:
        raise ValueError("this theme has no [meta].name, so it cannot be converted")

    if meta_raw.get("based_on"):
        warnings.append(
            f"'based_on = {meta_raw['based_on']}' is not part of the new format; "
            "the Look now stands on its own"
        )

    for hook in raw.get("hooks", []):
        event = hook.get("event", "post")
        script = hook.get("script", "(unnamed)")
        sudo = " (it asked for your password)" if hook.get("sudo") else ""
        warnings.append(
            f"the {event}-apply step '{script}'{sudo} was dropped — Looks only change "
            "settings now and can never run a program on your computer; "
            "whatever it did, you will have to do by hand"
        )

    requires = raw.get("requires", {})
    packages = [str(p) for p in requires.get("packages", [])]
    fonts = [str(f) for f in requires.get("fonts", [])]
    if packages:
        warnings.append(
            "this Look was made for a computer that already has these programs "
            "installed, and cannot install them for you: " + ", ".join(sorted(packages))
        )
    if fonts:
        warnings.append(
            "it also expects these fonts, which you may need to install yourself: "
            + ", ".join(sorted(fonts))
        )
    if raw.get("build", {}).get("managed"):
        warnings.append(
            "the author's own file-generation settings ([build].managed) were dropped; "
            "they were only used by the old command-line tool"
        )

    shots = screenshots if screenshots is not None else _pick_screenshots(raw, directory)
    if not shots:
        raise ValueError(
            f"{name} has no picture to show and none was supplied — a Look needs at "
            "least one screenshot"
        )

    files: list[FileEntry] = []
    sources: list[str] = []
    for entry in raw.get("files", []):
        src = str(entry.get("src", ""))
        dest = str(entry.get("dest", ""))
        if directory is not None and (directory / src).is_dir():
            warnings.append(
                f"the folder '{src}' was dropped: a Look copies one file at a time. "
                f"Nothing will be written to {dest}"
            )
            continue
        files.append(
            FileEntry(
                src=src,
                dest=dest,
                mode=_normalise_mode(entry.get("mode"), warnings, dest),
                template=bool(entry.get("template", False)),
            )
        )
        sources.append(src)

    settings: list[SettingEntry] = []
    enable: list[str] = []
    for entry in raw.get("settings", []):
        backend = str(entry.get("backend", "gsettings"))
        key = str(entry.get("key", ""))
        value = str(entry.get("value", ""))
        component_raw = str(entry.get("component", ""))

        if backend == "gsettings" and key.strip() == ENABLED_EXTENSIONS_KEY:
            listed = parse_string_list(value)
            if not listed:
                warnings.append(
                    "the add-on list could not be read and was skipped: " + value
                )
            enable.extend(u for u in listed if u not in enable)
            continue

        if backend == "dconf":
            full_key = f"dconf:{key}"
        elif backend == "gsettings":
            full_key = f"gsettings:{key}"
        else:
            warnings.append(f"unknown setting kind {backend!r} for {key} — skipped")
            continue

        settings.append(
            SettingEntry(
                key=full_key,
                value=value,
                component=classify_setting(key, component_raw),
            )
        )

    for uuid in requires.get("extensions", []):
        text = str(uuid)
        if text not in enable:
            enable.append(text)

    install = [
        ExtensionInstallEntry(
            uuid=uuid,
            source="local-only" if uuid in local_only else "ego",
            ego_pk=EGO_PKS.get(uuid),
        )
        for uuid in enable
    ]
    for uuid in enable:
        if uuid not in EGO_PKS and uuid not in local_only and uuid in _NO_PK:
            warnings.append(
                f"the add-on {uuid} has no known id on extensions.gnome.org; "
                "gtheme will look it up by name when you apply this Look"
            )

    preset = Preset(
        format=2,
        meta=Meta(
            name=name,
            title=str(meta_raw.get("title") or name),
            description=str(meta_raw.get("description", "")),
            author=str(meta_raw.get("author", "")),
            version=str(meta_raw.get("version", "0.1.0")),
            min_shell=str(meta_raw["min_shell"]) if meta_raw.get("min_shell") else None,
            screenshots=shots,
        ),
        palette={str(k): str(v) for k, v in (raw.get("palette") or {}).items()},
        files=files,
        settings=settings,
        extensions=ExtensionsBlock(enable=enable, install=install),
    )
    return ConversionResult(preset=preset, warnings=warnings, sources=sources)


def convert_dir(
    directory: str | Path,
    *,
    screenshots: list[str] | None = None,
    local_only: frozenset[str] = frozenset(),
) -> ConversionResult:
    """Convert a v1 theme folder in place (reads only).

    The palette lives in its own ``palette.toml`` in v1 and is folded into the
    Look here, because v2 keeps the whole Look in one file.
    """
    path = Path(directory)
    manifest = path / "theme.toml"
    if not manifest.is_file():
        raise FileNotFoundError(f"{manifest} does not exist")
    raw = tomllib.loads(manifest.read_text(encoding="utf-8"))
    palette_file = path / "palette.toml"
    if palette_file.is_file() and not raw.get("palette"):
        palette_raw = tomllib.loads(palette_file.read_text(encoding="utf-8"))
        flat = {k: v for k, v in palette_raw.items() if isinstance(v, str)}
        for section in ("colors", "palette", "ansi"):
            nested = palette_raw.get(section)
            if isinstance(nested, dict):
                flat.update({k: v for k, v in nested.items() if isinstance(v, str)})
        raw["palette"] = flat
    return convert_v1(raw, directory=path, screenshots=screenshots, local_only=local_only)


def write_look(
    src_dir: str | Path,
    out_dir: str | Path,
    *,
    screenshots: list[str] | None = None,
    local_only: frozenset[str] = frozenset(),
    header: str | None = None,
    skip: frozenset[str] = frozenset(),
) -> ConversionResult:
    """Convert a v1 theme folder and materialise the v2 Look at ``out_dir``.

    Copies exactly the files the converted Look still references, plus its
    screenshots. Files the v1 theme shipped but the Look no longer needs are
    simply not copied — the converted Look carries nothing it cannot explain.

    Args:
        skip: relative ``src`` paths to drop deliberately, each producing a
            warning. Used for payloads that exist only to be executed.
    """
    source = Path(src_dir)
    out = Path(out_dir)
    result = convert_dir(source, screenshots=screenshots, local_only=local_only)

    if skip:
        kept = []
        for entry in result.preset.files:
            if entry.src in skip:
                result.warnings.append(
                    f"'{entry.src}' was left behind on purpose; it is a program, and a "
                    "Look only changes settings"
                )
                continue
            kept.append(entry)
        result.preset = result.preset.model_copy(update={"files": kept})
        result.sources = [s for s in result.sources if s not in skip]

    out.mkdir(parents=True, exist_ok=True)
    wanted = list(dict.fromkeys([*result.sources, *result.preset.meta.screenshots]))
    for rel in wanted:
        origin = source / rel
        if not origin.is_file():
            result.warnings.append(f"'{rel}' is missing from the original theme and was not copied")
            continue
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, target)

    (out / "theme.toml").write_text(dumps_preset(result.preset, header=header), encoding="utf-8")
    return result
