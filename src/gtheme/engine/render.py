"""Palette-driven render engine.

Define a palette (structural roles + ANSI hues) and the engine renders a whole
coherent desktop — terminal, monitor, editor, GTK css — from shared Jinja
templates. Missing roles are derived from the ones you do provide, so a small
palette still produces a complete theme.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .. import color
from ..manifest import Theme
from ..paths import TEMPLATES_DIR


# The roles a template may rely on; any not in the palette are derived here.
def build_context(palette: dict[str, str]) -> dict[str, str]:
    p = dict(palette)

    def need(role: str, default: str) -> None:
        p.setdefault(role, default)

    bg = p.get("bg", "#101014")
    fg = p.get("fg", "#e8e8e8")
    accent = p.get("accent", "#7aa2f7")
    p.setdefault("bg", bg)
    p.setdefault("fg", fg)
    p.setdefault("accent", accent)

    need("surface1", color.lighten(bg, 6))
    need("surface2", color.lighten(bg, 12))
    need("surface3", color.lighten(bg, 18))
    need("fg_dim", color.mix(fg, bg, 0.35))
    need("fg_bright", color.lighten(fg, 25))
    need("accent_bright", color.lighten(accent, 15))
    need("comment", p.get("bright_black", color.lighten(bg, 30)))
    need("selection", p["surface2"])
    need("cursor", accent)

    # ANSI normal hues fall back to reasonable defaults if unspecified.
    hue_defaults = {
        "red": "#e0563b", "green": "#7da862", "yellow": "#e0a13b",
        "blue": "#6d8fb3", "magenta": "#b27e93", "cyan": "#6fa8a3",
    }
    for role, default in hue_defaults.items():
        need(role, default)
    need("ansi_black", p["surface1"])
    need("ansi_white", p["fg_dim"])
    # Bright variants derive from their normal hue unless given.
    for hue in ("red", "green", "yellow", "blue", "magenta", "cyan"):
        need(f"bright_{hue}", color.lighten(p[hue], 15))
    need("bright_black", p["comment"])
    need("bright_white", p["fg_bright"])
    return p


@dataclass
class TemplateSpec:
    src: str
    out: str           # may contain {name} (theme name) / {Name} (capitalised)
    component: str


def load_template_specs() -> list[TemplateSpec]:
    reg = TEMPLATES_DIR / "_templates.toml"
    data = tomllib.loads(reg.read_text(encoding="utf-8"))
    return [TemplateSpec(**t) for t in data.get("template", [])]


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["lighten"] = color.lighten
    env.filters["darken"] = color.darken
    env.filters["mix"] = color.mix
    env.filters["alpha"] = color.alpha
    env.filters["hex8"] = color.hex8
    env.filters["nohash"] = lambda v: v.lstrip("#")
    env.filters["rgb"] = lambda v: ", ".join(str(c) for c in color.parse_hex(v))
    return env


@dataclass
class RenderResult:
    written: list[str]
    skipped: list[str]


def build(theme: Theme, force: bool = False) -> RenderResult:
    """Render the theme's managed component files from its palette."""
    ctx = build_context(theme.palette)
    ctx["name"] = theme.meta.name
    ctx["Name"] = theme.meta.name.capitalize()
    # meta.title is free text that lands verbatim in rendered config files —
    # strip control chars so a stray newline can't inject an extra directive.
    title = theme.meta.title or theme.meta.name
    ctx["title"] = "".join(c for c in title if c.isprintable())
    env = _env()
    managed = set(theme.build.managed)
    written: list[str] = []
    skipped: list[str] = []

    for spec in load_template_specs():
        if managed and spec.component not in managed:
            skipped.append(f"{spec.src} (component '{spec.component}' not managed)")
            continue
        # Isolate each template: a StrictUndefined/render/write failure on one
        # template must not abort the whole build. Record it in skipped with an
        # "ERROR " prefix so the CLI surfaces it without a new field.
        try:
            out_rel = spec.out.format(name=theme.meta.name, Name=theme.meta.name.capitalize())
            out_path = theme.path / out_rel
            rendered = env.get_template(spec.src).render(**ctx)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(rendered, encoding="utf-8")
            written.append(out_rel)
        except Exception as exc:  # noqa: BLE001 - one bad template shouldn't kill the build
            skipped.append(f"ERROR {spec.src}: {exc}")
    return RenderResult(written, skipped)
