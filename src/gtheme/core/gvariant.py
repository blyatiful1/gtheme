"""GVariant text: the wire format that makes a generic undo possible.

gtheme does not know what type ``org.gnome.desktop.interface font-name`` has,
and does not need to. It reads the exact string GLib prints, keeps it, and
writes that string back later. The round-trip is the whole safety model: a
snapshot taken with no type knowledge restores correctly anyway.

That only works if nothing along the way "helpfully" normalises the string.
``@as []`` is an empty string array; ``[]`` is untyped and cannot be written at
all. ``@ms nothing`` is a maybe-type holding nothing; ``nothing`` on its own is
meaningless. Pango's ``'Cantarell 11 @wght=460'`` must come back with its axis
intact. The golden round-trip tests exist to pin exactly this.

Comparison is the one place canonicalisation is right: ``"zoom"`` and
``'zoom'`` are the same value written two ways, and reporting that as a change
would put a line in every preview that says nothing changed.

The list-union is the second thing here, and it exists for one key.
``org.gnome.shell enabled-extensions`` is shared global state: every add-on the
user turned on themselves lives in that list. A Look that writes its own list
over the top turns all of them off, and the user experiences that as "the app
deleted my dock". So a Look unions into it — and the baseline still records the
exact pre-union value, so undo puts back what was there rather than computing a
difference. That is the X1 defect, and it generalises to any shared list, which
is why this function is not named after extensions.
"""

from __future__ import annotations

import ast

__all__ = [
    "EMPTY_STRING_LIST",
    "canonical",
    "format_string_list",
    "merge_string_lists",
    "parse_string_list",
    "values_equal",
]

#: How GLib prints an empty array of strings. Not ``[]``, which has no type.
EMPTY_STRING_LIST = "@as []"


def canonical(text: str) -> str:
    """A comparable form of GVariant text.

    Falls back to the trimmed original when PyGObject is missing or the text
    does not parse — a fallback that can only ever make the comparison
    stricter, never looser, so an unparseable value is reported as changed
    rather than silently assumed equal.
    """
    try:
        from gi.repository import GLib

        return GLib.Variant.parse(None, text, None, None).print_(False)
    except Exception:  # noqa: BLE001 - missing gi, bad syntax, untyped literal
        return text.strip()


def values_equal(current: str | None, wanted: str) -> bool:
    """Is the setting already at the wanted value?

    A key that has never been set has no current value, which is never equal to
    anything: writing it is a real change.
    """
    if current is None:
        return False
    if current == wanted:
        return True
    return canonical(current) == canonical(wanted)


def parse_string_list(text: str | None) -> list[str] | None:
    """Read GVariant text as a list of strings, or None if it is not one.

    GVariant's array-of-string syntax is a Python list literal, so
    ``ast.literal_eval`` reads it without executing anything. ``@as []`` is
    special-cased because the type annotation is not Python syntax.

    Returns None — never a guess — on anything unexpected. Every caller treats
    None as "do not merge, this is not a list I understand".
    """
    if text is None:
        return None
    stripped = text.strip()
    if not stripped:
        return None
    if stripped.startswith("@as "):
        stripped = stripped[4:].strip()
    try:
        value = ast.literal_eval(stripped)
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return value


def format_string_list(items: list[str]) -> str:
    """Render a list of strings as GVariant text GLib will accept back.

    An empty list becomes ``@as []`` rather than ``[]``: a bare pair of
    brackets has no inferable type and ``gsettings set`` refuses it.

    GLib does the quoting when it is available, so an add-on identifier
    containing a quote character is escaped the way GLib itself would escape
    it. The pure-Python fallback exists only so this module keeps working on a
    machine with no PyGObject, which is the machine ``gtheme rescue`` runs on.
    """
    if not items:
        return EMPTY_STRING_LIST
    try:
        from gi.repository import GLib

        return GLib.Variant("as", items).print_(True)
    except Exception:  # noqa: BLE001 - no PyGObject
        body = ", ".join("'" + item.replace("\\", "\\\\").replace("'", "\\'") + "'" for item in items)
        return f"[{body}]"


def merge_string_lists(current: str | None, wanted: str) -> str | None:
    """Union two GVariant string lists, keeping the current one's order first.

    The user's members come first and keep their order; the wanted list's new
    members are appended in their own order. Nothing is removed — removal is
    what undo is for, and undo restores the recorded pre-merge value.

    Returns:
        The merged GVariant text, or None when either side is not a string
        list. None means "I do not understand this well enough to merge it";
        the caller then writes the wanted value as-is, which is what would have
        happened without a merge at all.
    """
    wanted_items = parse_string_list(wanted)
    if wanted_items is None:
        return None
    current_items = parse_string_list(current)
    if current_items is None:
        # No usable current value (unset, or something exotic). The wanted list
        # is the whole answer, and saying so explicitly beats returning None:
        # the caller writes the same thing either way.
        current_items = []
    merged = current_items + [item for item in wanted_items if item not in current_items]
    return format_string_list(merged)
