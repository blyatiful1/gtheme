"""The row index: deep links, live mirroring and per-row refresh depend on it."""

from __future__ import annotations

from gtheme.ui.rowindex import RowIndex


class _Widget:
    """Stand-in for a real row. The index holds widgets opaquely on purpose."""

    def __init__(self, name: str) -> None:
        self.name = name


def test_register_and_look_up():
    index = RowIndex()
    widget = _Widget("dark-mode")
    entry = index.register("colors", "org.gnome.desktop.interface:color-scheme", widget)
    assert index.lookup("org.gnome.desktop.interface:color-scheme") is entry
    assert entry.widget is widget
    assert len(index) == 1


def test_lookup_by_schema_and_key_is_what_a_changed_signal_gives():
    index = RowIndex()
    index.register("colors", "org.gnome.desktop.interface:color-scheme", _Widget("w"))
    found = index.lookup_key("org.gnome.desktop.interface", "color-scheme")
    assert found is not None
    assert found.page_id == "colors"


def test_page_of_is_the_deep_link_target():
    index = RowIndex()
    index.register("wallpaper", "org.gnome.desktop.background:picture-uri", _Widget("w"))
    assert index.page_of("org.gnome.desktop.background:picture-uri") == "wallpaper"
    assert index.page_of("nothing:here") is None


def test_missing_lookups_return_none_rather_than_raising():
    assert RowIndex().lookup("not:registered") is None


def test_for_page_preserves_build_order():
    index = RowIndex()
    for i in range(3):
        index.register("fonts", f"org.a:{i}", _Widget(str(i)))
    assert [e.descriptor_id for e in index.for_page("fonts")] == ["org.a:0", "org.a:1", "org.a:2"]


def test_registering_the_same_descriptor_twice_replaces_it():
    index = RowIndex()
    index.register("colors", "org.a:k", _Widget("first"))
    index.register("more", "org.a:k", _Widget("second"))
    assert index.lookup("org.a:k").widget.name == "second"
    assert index.page_of("org.a:k") == "more"
    assert index.for_page("colors") == []
    assert len(index) == 1


def test_unregister_page_drops_only_that_page():
    index = RowIndex()
    index.register("colors", "org.a:1", _Widget("a"))
    index.register("fonts", "org.b:1", _Widget("b"))
    assert index.unregister_page("colors") == 1
    assert index.lookup("org.a:1") is None
    assert index.lookup("org.b:1") is not None


def test_unregister_an_unknown_page_is_harmless():
    assert RowIndex().unregister_page("never-built") == 0


def test_refresh_calls_the_hook():
    index = RowIndex()
    calls = []
    index.register("colors", "org.a:k", _Widget("w"), refresh=lambda: calls.append(1))
    assert index.refresh("org.a:k") is True
    assert calls == [1]


def test_refresh_of_an_unregistered_row_is_false_not_an_error():
    assert RowIndex().refresh("nope:nope") is False


def test_refresh_of_a_row_with_no_hook_is_false():
    index = RowIndex()
    index.register("colors", "org.a:k", _Widget("w"))
    assert index.refresh("org.a:k") is False


def test_refresh_page_and_refresh_all_count_what_they_did():
    index = RowIndex()
    calls = []
    index.register("colors", "org.a:1", _Widget("a"), refresh=lambda: calls.append("a"))
    index.register("colors", "org.a:2", _Widget("b"), refresh=lambda: calls.append("b"))
    index.register("fonts", "org.b:1", _Widget("c"))  # no hook
    assert index.refresh_page("colors") == 2
    assert index.refresh_all() == 2
    assert calls == ["a", "b", "a", "b"]


def test_search_matches_synonyms_case_insensitively():
    index = RowIndex()
    index.register(
        "topbar",
        "org.gnome.shell.extensions.dash-to-dock:dock-position",
        _Widget("dock"),
        search_text="Where the app icons sit taskbar dock",
    )
    assert [e.descriptor_id for e in index.search("TASKBAR")] == [
        "org.gnome.shell.extensions.dash-to-dock:dock-position"
    ]


def test_search_on_empty_text_returns_nothing():
    index = RowIndex()
    index.register("colors", "org.a:k", _Widget("w"), search_text="dark mode")
    assert index.search("   ") == []


def test_membership_and_iteration():
    index = RowIndex()
    index.register("colors", "org.a:k", _Widget("w"))
    assert "org.a:k" in index
    assert [e.descriptor_id for e in index] == ["org.a:k"]


def test_clear_empties_everything():
    index = RowIndex()
    index.register("colors", "org.a:k", _Widget("w"))
    index.clear()
    assert len(index) == 0
    assert index.for_page("colors") == []


def test_extra_metadata_is_carried_along():
    index = RowIndex()
    entry = index.register("colors", "org.a:k", _Widget("w"), group="Appearance")
    assert entry._extra["group"] == "Appearance"
