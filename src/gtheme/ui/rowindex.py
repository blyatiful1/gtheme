"""Where every rendered row can be found again.

THE CONTRACT IS FROZEN (DESIGN.md F8). Three features depend on being able to
go from a descriptor id to the actual widget on screen:

* **Search.** Ctrl+F indexes every descriptor in the app. A hit has to open the
  right page, scroll to the row and flash it — which means the row must be
  findable by id after it was built.
* **Live mirroring.** If someone changes the highlight colour in GNOME's own
  Settings while gtheme is open, gtheme's row must follow. The Gio.Settings
  ``changed`` signal gives a ``(schema, key)``; this index turns that back into
  the row to refresh.
* **Per-row reset.** A row's "put this back" button needs to re-read its own
  value afterwards, without rebuilding the page.

Deliberately GTK-free: widgets are held as opaque objects. That keeps this
testable in the plain unit tier, and keeps the index honest — it is a lookup
table, not a place to put behaviour.

Registrations are per page and are dropped when a page is torn down, so a page
that is rebuilt does not leave stale widgets behind.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

__all__ = ["RowEntry", "RowIndex"]


@dataclass
class RowEntry:
    """One rendered row.

    Args:
        page_id: the page it lives on, from ``ui.registry``.
        descriptor_id: ``schema:key``, from ``panels.descriptor``.
        widget: the widget itself. Opaque here.
        refresh: called with no arguments to re-read the current value and
            update the widget. None for rows that cannot go stale.
        search_text: title, subtitle and synonyms, pre-joined and lowercased.
    """

    page_id: str
    descriptor_id: str
    widget: Any
    refresh: Callable[[], None] | None = None
    search_text: str = ""
    _extra: dict[str, Any] = field(default_factory=dict)


class RowIndex:
    """Registry of rendered rows, keyed by descriptor id.

    One instance lives on the application window. Registering the same
    descriptor id twice replaces the earlier entry — the same setting can
    legitimately appear on a named page and again in a search result, and the
    most recently built widget is the one worth flashing.
    """

    def __init__(self) -> None:
        self._by_id: dict[str, RowEntry] = {}
        self._by_page: dict[str, list[RowEntry]] = {}

    # -- registration ------------------------------------------------------

    def register(
        self,
        page_id: str,
        descriptor_id: str,
        widget: Any,
        *,
        refresh: Callable[[], None] | None = None,
        search_text: str = "",
        **extra: Any,
    ) -> RowEntry:
        """Record a row that has just been built. Returns the entry."""
        entry = RowEntry(
            page_id=page_id,
            descriptor_id=descriptor_id,
            widget=widget,
            refresh=refresh,
            search_text=search_text.lower(),
            _extra=dict(extra),
        )
        previous = self._by_id.get(descriptor_id)
        if previous is not None:
            page_rows = self._by_page.get(previous.page_id)
            if page_rows is not None and previous in page_rows:
                page_rows.remove(previous)
        self._by_id[descriptor_id] = entry
        self._by_page.setdefault(page_id, []).append(entry)
        return entry

    def unregister_page(self, page_id: str) -> int:
        """Forget every row of a page. Returns how many were dropped."""
        entries = self._by_page.pop(page_id, [])
        for entry in entries:
            if self._by_id.get(entry.descriptor_id) is entry:
                del self._by_id[entry.descriptor_id]
        return len(entries)

    def clear(self) -> None:
        self._by_id.clear()
        self._by_page.clear()

    # -- lookup ------------------------------------------------------------

    def lookup(self, descriptor_id: str) -> RowEntry | None:
        """The row for a descriptor id, or None if it is not on screen."""
        return self._by_id.get(descriptor_id)

    def lookup_key(self, schema_id: str, key: str) -> RowEntry | None:
        """The row for a ``(schema, key)`` pair — what a changed-signal gives."""
        return self._by_id.get(f"{schema_id}:{key}")

    def page_of(self, descriptor_id: str) -> str | None:
        """Which page to open to reach a descriptor. The deep-link target."""
        entry = self._by_id.get(descriptor_id)
        return entry.page_id if entry else None

    def for_page(self, page_id: str) -> list[RowEntry]:
        """Every row of a page, in the order they were built."""
        return list(self._by_page.get(page_id, ()))

    def search(self, text: str) -> list[RowEntry]:
        """Rows whose title, subtitle or synonyms contain ``text``.

        Substring, case-insensitive, and deliberately not fuzzy: a novice
        typing "taskbar" should find the dock because "taskbar" is in the row's
        synonyms, not because an edit distance happened to be small.
        """
        needle = text.strip().lower()
        if not needle:
            return []
        return [e for e in self._by_id.values() if needle in e.search_text]

    # -- refresh -----------------------------------------------------------

    def refresh(self, descriptor_id: str) -> bool:
        """Re-read one row. Returns False if it is not on screen."""
        entry = self._by_id.get(descriptor_id)
        if entry is None or entry.refresh is None:
            return False
        entry.refresh()
        return True

    def refresh_page(self, page_id: str) -> int:
        """Re-read every row of a page. Returns how many were refreshed."""
        count = 0
        for entry in self._by_page.get(page_id, ()):
            if entry.refresh is not None:
                entry.refresh()
                count += 1
        return count

    def refresh_all(self) -> int:
        """Re-read everything on screen. Returns how many were refreshed."""
        count = 0
        for entry in self._by_id.values():
            if entry.refresh is not None:
                entry.refresh()
                count += 1
        return count

    # -- dunder ------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._by_id)

    def __iter__(self) -> Iterator[RowEntry]:
        return iter(self._by_id.values())

    def __contains__(self, descriptor_id: object) -> bool:
        return descriptor_id in self._by_id
