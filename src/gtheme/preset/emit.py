"""Write a Look back out as ``theme.toml``.

gtheme reads TOML with the standard library and has no TOML *writer*
dependency, which is deliberate: the only shape that ever needs writing is
:class:`~gtheme.preset.model.Preset`, that shape is frozen, and a hundred lines
here are cheaper than a dependency in every downstream package.

Two callers rely on it. The v1 importer materialises converted Looks, and
restore-point capture writes the current desktop out as a Look — because a
restore point *is* a Look, which is what lets "undo" reuse the same apply path
as everything else instead of being a second, less-tested engine.

The emitter is checked by round-trip: whatever it writes, ``tomllib`` reads
back and pydantic re-validates into an equal model.
"""

from __future__ import annotations

from .model import Preset

__all__ = ["dumps_preset"]

_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}


def _quote(text: str) -> str:
    """A TOML basic string. Escapes what TOML requires and nothing else."""
    out = []
    for char in text:
        if char in _ESCAPES:
            out.append(_ESCAPES[char])
        elif ord(char) < 0x20 or ord(char) == 0x7F:
            out.append(f"\\u{ord(char):04x}")
        else:
            out.append(char)
    return '"' + "".join(out) + '"'


def _array(values: list[str]) -> str:
    if not values:
        return "[]"
    if len(values) == 1:
        return f"[{_quote(values[0])}]"
    body = ",\n".join(f"    {_quote(v)}" for v in values)
    return f"[\n{body},\n]"


def _kv(key: str, value: object) -> str:
    if isinstance(value, bool):
        return f"{key} = {'true' if value else 'false'}"
    if isinstance(value, int):
        return f"{key} = {value}"
    if isinstance(value, list):
        return f"{key} = {_array([str(v) for v in value])}"
    return f"{key} = {_quote(str(value))}"


def dumps_preset(preset: Preset, *, header: str | None = None) -> str:
    """Render a Look as the text of its ``theme.toml``.

    Args:
        preset: the Look to write.
        header: optional comment block placed at the top. Lines are prefixed
            with ``# `` for you; pass the prose, not the comment markers.
    """
    lines: list[str] = []
    if header:
        lines.extend(f"# {line}".rstrip() for line in header.splitlines())
        lines.append("")

    lines.append("format = 2")
    lines.append("")

    meta = preset.meta
    lines.append("[meta]")
    lines.append(_kv("name", meta.name))
    lines.append(_kv("title", meta.title))
    lines.append(_kv("description", meta.description))
    lines.append(_kv("author", meta.author))
    lines.append(_kv("version", meta.version))
    if meta.min_shell is not None:
        lines.append(_kv("min_shell", meta.min_shell))
    lines.append(_kv("screenshots", meta.screenshots))

    if preset.palette:
        lines.append("")
        lines.append("[palette]")
        for name, value in preset.palette.items():
            lines.append(_kv(name, value))

    for entry in preset.files:
        lines.append("")
        lines.append("[[files]]")
        lines.append(_kv("src", entry.src))
        lines.append(_kv("dest", entry.dest))
        if entry.mode is not None:
            lines.append(_kv("mode", entry.mode))
        if entry.template:
            lines.append(_kv("template", True))

    for setting in preset.settings:
        lines.append("")
        lines.append("[[settings]]")
        lines.append(_kv("key", setting.key))
        lines.append(_kv("value", setting.value))
        if setting.merge != "none":
            lines.append(_kv("merge", setting.merge))
        lines.append(_kv("component", str(setting.component)))

    block = preset.extensions
    if block.enable or block.install or block.settings:
        lines.append("")
        lines.append("[extensions]")
        lines.append(_kv("enable", block.enable))

        for install in block.install:
            lines.append("")
            lines.append("[[extensions.install]]")
            lines.append(_kv("uuid", install.uuid))
            lines.append(_kv("source", install.source))
            if install.ego_pk is not None:
                lines.append(_kv("ego_pk", install.ego_pk))
            if install.alternates:
                lines.append(_kv("alternates", install.alternates))

        for setting in block.settings:
            lines.append("")
            lines.append("[[extensions.settings]]")
            lines.append(_kv("uuid", setting.uuid))
            lines.append(_kv("schema_id", setting.schema_id))
            lines.append(_kv("key", setting.key))
            lines.append(_kv("value", setting.value))
            if setting.path is not None:
                lines.append(_kv("path", setting.path))

    return "\n".join(lines) + "\n"
