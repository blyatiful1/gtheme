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
import re

__all__ = [
    "EMPTY_STRING_LIST",
    "bare_number",
    "canonical",
    "format_string_list",
    "merge_string_lists",
    "parse_string_list",
    "quote",
    "unquote",
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


def unquote(text: str) -> str:
    """``"'Papirus-Dark'"`` becomes ``Papirus-Dark``. The one implementation.

    A GVariant string arrives quoted, and everything that shows one to a person
    — a picker's current entry, the Home card's summary of the desktop, the
    profile name burn-my-windows keeps its settings under — has to take the
    quoting off first. That was written out longhand in eight places
    (review-report L19), one of them inside the *frozen* row library, where a
    fix would have been invisible to the other seven.

    Only a quoted *string* is unquoted, and only when the text really is one. A
    bare number, a boolean, an array and an already-unquoted name all come back
    untouched, which is what makes this safe to call on anything a backend
    returned.

    GLib does the unescaping when it is available, so this is the true inverse
    of :func:`quote`. All eight hand-rolled copies took the two quote characters
    off and stopped there, which is right for every theme name anybody has and
    wrong for a name containing a backslash: ``quote`` writes ``'back\\\\slash'``
    and the naive strip handed back ``back\\\\slash``, one backslash too many.
    The pure-Python fallback keeps the old behaviour for the machine with no
    PyGObject, where nothing can unescape anything anyway.
    """
    stripped = text.strip()
    if not (len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in "'\""):
        return stripped
    try:
        from gi.repository import GLib

        variant = GLib.Variant.parse(None, stripped, None, None)
        if variant.get_type_string() == "s":
            return variant.get_string()
    except Exception:  # noqa: BLE001 - no PyGObject, or not a string after all
        pass
    return stripped[1:-1]


def quote(text: str) -> str:
    """The GVariant text for a plain string. The inverse of :func:`unquote`.

    GLib does the escaping when it is available, so a theme name containing a
    quote character is escaped exactly the way GLib itself would escape it —
    and therefore exactly the way it will be read back. The pure-Python
    fallback is the same one :func:`format_string_list` carries, and for the
    same reason: this module has to keep working on a machine with no
    PyGObject, which is the machine ``gtheme rescue`` runs on.
    """
    try:
        from gi.repository import GLib

        return GLib.Variant("s", text).print_(True)
    except Exception:  # noqa: BLE001 - no PyGObject
        return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def values_equal(current: str | None, wanted: str) -> bool:
    """Is the setting already at the wanted value?

    A key that has never been set has no current value, which is never equal to
    anything: writing it is a real change.

    That sentence was true here and false one layer down: a raw ``dconf:``
    location that had never been written came back from the backend as "no such
    key", which the engine read as "not on this machine" and skipped — so this
    function was never asked. ``BackendErrorKind.UNSET`` is what reunites the
    two (review-report H7): an unset location now reaches here as ``None`` and
    is written, exactly as this docstring always said.
    """
    if current is None:
        return False
    if current == wanted:
        return True
    return canonical(current) == canonical(wanted)


#: GVariant prints a number whose type is not the default ``int32`` with the
#: type in front of it: a ``uint32`` holding 300 comes back as ``"uint32 300"``
#: while an ``int32`` comes back as ``"300"``. That is correct wire format and
#: it is what the backend contract promises — but it is not a number, and every
#: numeric control in the app parses what it reads with ``float()``.
_ANNOTATED_NUMBER = re.compile(
    r"^(?:byte|int16|uint16|int32|uint32|int64|uint64|handle|double)\s+(\S+)$"
)


def bare_number(text: str) -> str:
    """``"uint32 300"`` becomes ``"300"``. Everything else is returned as is.

    Twenty settings on a GNOME 50 desktop are ``uint32``, and every one of them
    is behind a control a person actually moves: the colour temperature of the
    evening warmth, how long before the screen locks, how long before it goes
    dark, the break reminders' intervals. Read literally, ``float("uint32
    300")`` throws, the slider quietly shows its own minimum instead of the real
    value, and nudging it writes a value the person never chose. The pick-one
    row has the same cause and a different symptom: it decides the desktop is
    holding a value it was never offered and labels it "set somewhere else".

    So numbers are bared on the way *in*, here, at the boundary where a widget
    reads. On the way out nothing changes: a bare number is accepted for a
    ``uint32`` by both the native and the command-line backends, because both
    parse against the key's real type.

    This is deliberately *not* a change to what a backend returns. The exact
    printed form is the wire format saved moments are captured in, and baring it
    at the source would change what a saved moment records — and therefore what
    undo puts back.
    """
    stripped = text.strip()
    match = _ANNOTATED_NUMBER.match(stripped)
    if match is None:
        return text
    value = match.group(1)
    if value.lower().startswith("0x"):
        try:
            return str(int(value, 16))
        except ValueError:  # pragma: no cover - GVariant would not print this
            return text
    return value


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
