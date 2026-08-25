"""GTK-marked test for gtheme.system.fontscan.scan_font_families — needs Pango."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gtk


def test_scan_font_families_returns_sorted_unique_entries() -> None:
    pytest.importorskip("gi", reason="PyGObject is needed for Pango font enumeration")
    import gi

    gi.require_version("PangoCairo", "1.0")

    from gtheme.system.fontscan import scan_font_families

    entries = scan_font_families()

    assert entries, "expected at least one installed font family"
    names = [e.name for e in entries]
    assert names == sorted(names, key=str.casefold)
    assert len(names) == len(set(names))
    assert any(e.is_monospace for e in entries)
