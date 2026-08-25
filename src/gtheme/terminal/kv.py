"""Editors for hand-written config files that must survive being edited.

Ghostty's ``config``, btop's ``btop.conf`` and cava's ``config`` are all files
people write by hand, comment heavily, and care about. gtheme understands maybe
a dozen keys in each of them; everything else — the comments explaining *why* a
setting is what it is, the keys gtheme has never heard of, the blank lines that
make the file readable — has to come back out unchanged.

So neither editor here parses a file into a dictionary and prints a new one.
Both keep the original lines and change only the ones they were asked to change,
in place. A key that was not present is appended; a key that was present keeps
its position in the file.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["IniFile", "KeyValueFile"]


@dataclass
class _Line:
    raw: str
    key: str | None = None
    value: str | None = None


@dataclass
class KeyValueFile:
    """A flat ``key = value`` file with comments, in file order.

    Args:
        separator: what to put between key and value on lines this class
            writes. Existing lines keep whatever they already had.
        comment_prefixes: line prefixes that mean "not a setting".

    Ghostty allows a key to repeat — ``palette``, ``font-family``,
    ``custom-shader`` all accumulate — so both a single-valued and a
    repeated-block setter are provided, and they mean different things.
    """

    separator: str = " = "
    comment_prefixes: tuple[str, ...] = ("#",)
    _lines: list[_Line] = field(default_factory=list)

    @classmethod
    def parse(
        cls,
        text: str,
        *,
        separator: str = " = ",
        comment_prefixes: tuple[str, ...] = ("#",),
    ) -> KeyValueFile:
        out = cls(separator=separator, comment_prefixes=comment_prefixes)
        for raw in text.splitlines():
            stripped = raw.strip()
            if not stripped or stripped.startswith(comment_prefixes):
                out._lines.append(_Line(raw))
                continue
            key, sep, value = raw.partition("=")
            if not sep:
                out._lines.append(_Line(raw))
                continue
            out._lines.append(_Line(raw, key=key.strip(), value=value.strip()))
        return out

    # -- reading -----------------------------------------------------------

    def values(self, key: str) -> list[str]:
        """Every value this key has, in file order. Empty when absent."""
        return [line.value for line in self._lines if line.key == key and line.value is not None]

    def value(self, key: str) -> str | None:
        """The last value for ``key`` — later lines win in every format here."""
        found = self.values(key)
        return found[-1] if found else None

    def has(self, key: str) -> bool:
        return any(line.key == key for line in self._lines)

    def keys(self) -> list[str]:
        """Every key present, first occurrence order."""
        seen: list[str] = []
        for line in self._lines:
            if line.key is not None and line.key not in seen:
                seen.append(line.key)
        return seen

    # -- writing -----------------------------------------------------------

    def _format(self, key: str, value: str) -> _Line:
        return _Line(f"{key}{self.separator}{value}", key=key, value=value)

    def set(self, key: str, value: str) -> None:
        """Give ``key`` exactly one value, keeping its place in the file.

        Duplicates of a single-valued key are removed: leaving a second
        ``theme =`` line below the one we just wrote would silently win.
        """
        indexes = [i for i, line in enumerate(self._lines) if line.key == key]
        if not indexes:
            self._append(self._format(key, value))
            return
        first = indexes[0]
        self._lines[first] = self._format(key, value)
        for index in reversed(indexes[1:]):
            del self._lines[index]

    def set_repeated(self, key: str, values: list[str]) -> None:
        """Replace every line for ``key`` with one line per value.

        The block lands where the first existing occurrence was, so a palette
        block stays under the comment that introduces it.
        """
        indexes = [i for i, line in enumerate(self._lines) if line.key == key]
        block = [self._format(key, value) for value in values]
        if not indexes:
            for line in block:
                self._append(line)
            return
        first = indexes[0]
        for index in reversed(indexes):
            del self._lines[index]
        self._lines[first:first] = block

    def remove(self, key: str) -> bool:
        """Delete every line for ``key``. Returns whether there were any."""
        indexes = [i for i, line in enumerate(self._lines) if line.key == key]
        for index in reversed(indexes):
            del self._lines[index]
        return bool(indexes)

    def _append(self, line: _Line) -> None:
        if self._lines and self._lines[-1].raw.strip() == "":
            self._lines.insert(len(self._lines) - 1, line)
        else:
            self._lines.append(line)

    def render(self) -> str:
        """The file back as text, with a trailing newline."""
        body = "\n".join(line.raw for line in self._lines)
        return body + "\n" if body else ""


@dataclass
class IniFile:
    """An INI file (``[section]`` then ``key = value``) that keeps its comments.

    cava's config is the reason this exists: it is INI-shaped, heavily
    commented, and gtheme only ever wants to rewrite the ``[color]`` gradient.
    """

    separator: str = " = "
    comment_prefixes: tuple[str, ...] = ("#", ";")
    _lines: list[_Line] = field(default_factory=list)
    _sections: dict[str, tuple[int, int]] = field(default_factory=dict)

    @classmethod
    def parse(
        cls,
        text: str,
        *,
        separator: str = " = ",
        comment_prefixes: tuple[str, ...] = ("#", ";"),
    ) -> IniFile:
        out = cls(separator=separator, comment_prefixes=comment_prefixes)
        for raw in text.splitlines():
            stripped = raw.strip()
            if not stripped or stripped.startswith(comment_prefixes):
                out._lines.append(_Line(raw))
            elif stripped.startswith("[") and stripped.endswith("]"):
                out._lines.append(_Line(raw, key="[section]", value=stripped[1:-1].strip()))
            else:
                key, sep, value = raw.partition("=")
                out._lines.append(
                    _Line(raw, key=key.strip(), value=value.strip())
                    if sep
                    else _Line(raw)
                )
        return out

    def _bounds(self, section: str) -> tuple[int, int] | None:
        """``(first_line_after_header, end)`` for a section, or None."""
        start: int | None = None
        for index, line in enumerate(self._lines):
            if line.key == "[section]":
                if start is not None:
                    return (start, index)
                if line.value == section:
                    start = index + 1
        if start is None:
            return None
        return (start, len(self._lines))

    def value(self, section: str, key: str) -> str | None:
        bounds = self._bounds(section)
        if bounds is None:
            return None
        start, end = bounds
        for line in self._lines[start:end]:
            if line.key == key and line.value is not None:
                return line.value
        return None

    def set(self, section: str, key: str, value: str) -> None:
        """Set one key inside one section, creating the section if needed."""
        bounds = self._bounds(section)
        new = _Line(f"{key}{self.separator}{value}", key=key, value=value)
        if bounds is None:
            if self._lines and self._lines[-1].raw.strip() != "":
                self._lines.append(_Line(""))
            self._lines.append(_Line(f"[{section}]", key="[section]", value=section))
            self._lines.append(new)
            return
        start, end = bounds
        for index in range(start, end):
            if self._lines[index].key == key:
                self._lines[index] = new
                return
        insert_at = end
        while insert_at > start and self._lines[insert_at - 1].raw.strip() == "":
            insert_at -= 1
        self._lines.insert(insert_at, new)

    def remove_prefixed(self, section: str, prefix: str) -> int:
        """Delete every key in ``section`` starting with ``prefix``.

        Rewriting a gradient means the old ``gradient_color_5`` has to go, or a
        shorter gradient keeps a stale colour at the top.
        """
        bounds = self._bounds(section)
        if bounds is None:
            return 0
        start, end = bounds
        doomed = [
            index
            for index in range(start, end)
            if self._lines[index].key and self._lines[index].key.startswith(prefix)
        ]
        for index in reversed(doomed):
            del self._lines[index]
        return len(doomed)

    def render(self) -> str:
        body = "\n".join(line.raw for line in self._lines)
        return body + "\n" if body else ""
