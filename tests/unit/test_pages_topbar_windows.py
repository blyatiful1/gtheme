"""Top Bar & Overview and Windows & Desktops — DESIGN.md A6/§C step 16.

Marked ``gtk`` because both pages build real libadwaita widgets; nothing here
presents a window (DESIGN.md forbids that in a unit test), and every value
goes through a :class:`MemoryBackend` so nothing reaches the real desktop.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for the page modules")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from gtheme.core import backends  # noqa: E402
from gtheme.core.settings_backend import MemoryBackend  # noqa: E402
from gtheme.prefs import Prefs  # noqa: E402
from gtheme.ui import jargon  # noqa: E402
from gtheme.ui.pages import topbar, windows  # noqa: E402
from gtheme.ui.rowindex import RowIndex  # noqa: E402

pytestmark = pytest.mark.gtk


@pytest.fixture(autouse=True, scope="module")
def _adw():
    if not Gtk.init_check():
        pytest.skip("no display is available for GTK — run under gtk4-broadwayd")
    Adw.init()


class FakeWindow:
    """The slice of ``gtheme.window.Window`` a page actually touches.

    Real ``Window`` construction pulls in the whole sidebar and the other
    fourteen pages' placeholders; this is the same (``prefs``, ``rows``,
    ``show_page``) surface without any of that, so a test failure here always
    points at these two pages and never at somebody else's.
    """

    def __init__(self, prefs: Prefs) -> None:
        self.prefs = prefs
        self.rows = RowIndex()
        self.shown: list[str] = []

    def show_page(self, page_id: str) -> None:
        self.shown.append(page_id)


@pytest.fixture
def prefs(config_dir: Path) -> Prefs:
    del config_dir  # isolation seam only
    return Prefs()


@pytest.fixture
def backend(memory_settings) -> MemoryBackend:
    del memory_settings  # isolation seam only; a fresh instance is used below
    return MemoryBackend()


@pytest.fixture
def window(prefs: Prefs) -> FakeWindow:
    return FakeWindow(prefs)


# -- construction -------------------------------------------------------


def test_windows_page_builds_and_registers_every_row(window: FakeWindow, backend: MemoryBackend):
    with backends.use_backend(backend):
        widget = windows.build(window)
    assert isinstance(widget, Gtk.Widget)
    # windows.toml (25) + shortcuts.toml (123) + mediakeys.toml (52), plus the
    # one hand-authored link row this page adds next to the animation toggle.
    assert len(window.rows) == 25 + 123 + 52 + 1


def test_topbar_page_builds_and_registers_every_row(window: FakeWindow, backend: MemoryBackend):
    with backends.use_backend(backend):
        widget = topbar.build(window)
    assert isinstance(widget, Gtk.Widget)
    # topbar.toml (11) + the one topbarstyle.toml row.
    assert len(window.rows) == 11 + 1


def test_both_pages_are_reachable_through_the_registry_manifest():
    """The factory strings the manifest already names really resolve."""
    from gtheme.ui import registry

    assert registry.load_factory("windows") is windows.build
    assert registry.load_factory("topbar") is topbar.build


# -- the button-layout row is the five curated options, no visual builder ---


def test_button_layout_offers_exactly_the_five_curated_layouts(
    window: FakeWindow, backend: MemoryBackend
):
    with backends.use_backend(backend):
        windows.build(window)
    entry = window.rows.lookup("org.gnome.desktop.wm.preferences:button-layout")
    assert entry is not None
    assert isinstance(entry.widget, Adw.ComboRow)
    assert entry.widget.get_model().get_n_items() == 5


# -- the workspace count is gated by dynamic-workspaces (requires_first) ----


def test_fixed_workspace_count_turns_off_dynamic_workspaces_first(
    window: FakeWindow, backend: MemoryBackend
):
    with backends.use_backend(backend):
        windows.build(window)
        assert backend.get("gsettings:org.gnome.mutter dynamic-workspaces") == "true"
        count_entry = window.rows.lookup("org.gnome.desktop.wm.preferences:num-workspaces")
        count_entry.widget.set_value(6)  # the schema default is 4 — pick a value that changes
        assert backend.get("gsettings:org.gnome.mutter dynamic-workspaces") == "false"
        assert backend.get("gsettings:org.gnome.desktop.wm.preferences num-workspaces") == "6"


# -- the impatience cross-link -------------------------------------------


def test_the_animation_row_is_followed_by_a_link_to_the_addons_page(
    window: FakeWindow, backend: MemoryBackend
):
    with backends.use_backend(backend):
        windows.build(window)
    link = window.rows.lookup("link:page:addons")
    assert link is not None
    assert isinstance(link.widget, Adw.ActionRow)
    link.widget.activate()
    assert window.shown == ["addons"]


def test_the_link_row_reads_no_setting_and_has_no_reset_button():
    """A link goes somewhere; it does not have a value to put back."""
    # Regression for the one row on this page that is not descriptor-driven:
    # it must still honour the "reset only on a real setting" rule the frozen
    # row library enforces for every other row.
    from gtheme.panels.descriptor import Row, WidgetKind

    row = Row(title="x", subtitle="y", kind=WidgetKind.LINK, link_target="page:addons", reset=False)
    assert row.schema_id is None and row.key is None


# -- shortcuts and media keys are folded, not a wall of 175 rows ------------


def test_shortcuts_and_mediakeys_are_folded_into_named_collapsed_sections(
    window: FakeWindow, backend: MemoryBackend
):
    """Rewritten deliberately, and the old expectation was the defect.

    This used to assert that each of the two domains rendered as *one*
    collapsed expander carrying the domain's title. That is exactly the shape
    persona-report §3.2 called out: opening one gave back 123 corpus-ordered
    rows with no headings and no way to narrow them. The domain title now
    belongs to the group, and the collapsed rows underneath are named sections
    — so what this test guards is unchanged in spirit (nothing is a wall of
    rows, nothing starts open) and changed in structure on purpose.
    """
    with backends.use_backend(backend):
        widget = windows.build(window)

    groups = _find_all(widget, Adw.PreferencesGroup)
    group_titles = {group.get_title() for group in groups}
    assert "Keyboard Shortcuts" in group_titles
    assert "Sound &amp; Media Keys" in group_titles or "Sound & Media Keys" in group_titles

    expanders = _find_all(widget, Adw.ExpanderRow)
    titles = {row.get_title() for row in expanders}
    assert {"The window you are using", "Desktops and screens", "Sound"} <= titles
    assert not any(row.get_expanded() for row in expanders), "nothing opens itself"


def _find_all(widget: Gtk.Widget, kind: type) -> list:
    found = []
    if isinstance(widget, kind):
        found.append(widget)
    child = widget.get_first_child()
    while child is not None:
        found.extend(_find_all(child, kind))
        child = child.get_next_sibling()
    return found


def _find_buttons_labelled(widget: Gtk.Widget, label: str) -> list[Gtk.Button]:
    return [b for b in _find_all(widget, Gtk.Button) if b.get_label() == label]


# -- ampersands in a domain title must not break Adw's markup parser --------


def test_a_domain_title_with_an_ampersand_does_not_crash_the_group(
    window: FakeWindow, backend: MemoryBackend
):
    """windows.toml, mediakeys.toml and topbar.toml all say "&" in their own
    title — a real value straight off disk, not a fixture invented to cover
    this. If it is ever handed to an ``Adw`` widget unescaped, GTK logs a
    critical markup-parse warning instead of the title appearing at all."""
    with backends.use_backend(backend):
        widget = windows.build(window)
    groups = _find_all(widget, Adw.PreferencesGroup)
    assert any(g.get_title() == "Windows &amp; Desktops" for g in groups)


# -- the shell-theme picker (topbarstyle.toml, kind=picker) ------------------


def test_the_top_bar_style_is_a_way_through_to_colours_and_style(
    window: FakeWindow, backend: MemoryBackend
):
    """CONTRACT CHANGED BY RULING (Wave-2 gate, R7): one owner for one setting.

    This page used to build its own picker for the top bar's style, and so
    does Colours & Style. Two pickers on one setting is two lists of installed
    styles that can disagree — and only one of the two knew that the setting
    does nothing until the User Themes add-on is switched on, and offered to
    switch it on. A person who changes the style on the page without that
    offer sees nothing happen.

    So the owner is the page with the fix in it, and this page signposts.
    """
    with backends.use_backend(backend):
        topbar.build(window)

    assert window.rows.lookup("org.gnome.shell.extensions.user-theme:name") is None, (
        "this page must not own the top bar style row any more"
    )
    entry = window.rows.lookup("link:page:colors")
    assert entry is not None, "the signpost is missing"
    assert isinstance(entry.widget, Adw.ActionRow)
    assert not isinstance(entry.widget, Adw.ComboRow), "still a picker"
    assert entry.widget.get_activatable()


def test_the_signpost_actually_goes_to_colours_and_style(
    window: FakeWindow, backend: MemoryBackend
):
    """A link that says where it goes and does not go there is worse than none."""
    with backends.use_backend(backend):
        topbar.build(window)
    entry = window.rows.lookup("link:page:colors")
    entry.widget.emit("activated")
    assert window.shown == ["colors"]


def test_the_turn_it_on_offer_belongs_to_the_one_owner_now(
    window: FakeWindow, backend: MemoryBackend
):
    """CONTRACT CHANGED BY RULING (Wave-2 gate, R7).

    The add-on offer moved with the setting. It is covered where it now lives,
    in ``test_pages_colors.py``; asserted absent here so the two pages cannot
    quietly grow a second copy of it again.
    """
    with backends.use_backend(backend):
        widget = topbar.build(window)
    assert _find_buttons_labelled(widget, "Turn it on") == []


# -- one-shot first-visit banners -------------------------------------------


def test_the_first_visit_banner_shows_once_and_then_never_again(
    window: FakeWindow, backend: MemoryBackend
):
    with backends.use_backend(backend):
        first = windows.build(window)
    assert _find_all(first, Adw.Banner), "nothing was shown on a genuinely first visit"
    assert window.prefs.banner_seen(windows.BANNER_ID) is False

    dismiss = _find_buttons_labelled(first, "Got it")
    assert dismiss
    dismiss[0].emit("clicked")
    assert window.prefs.banner_seen(windows.BANNER_ID) is True

    second_window = FakeWindow(window.prefs)
    with backends.use_backend(backend):
        second = windows.build(second_window)
    assert not _find_all(second, Adw.Banner), "the banner came back after being dismissed"


# -- every hand-authored string on these two pages is plain language --------


def test_every_string_this_page_writes_itself_is_plain_language():
    """Descriptor copy is linted in ``domains_jargon_test.py`` already; this
    covers the handful of sentences these two page modules author directly."""
    hand_written = [
        # The two explainers are read off the modules rather than copied here:
        # a copy would go stale silently, and both are now named constants
        # because the shared explainer widget takes the sentence as an argument
        # (review-report M28).
        ("windows.py banner", windows.BANNER_TEXT),
        ("topbar.py banner", topbar.BANNER_TEXT),
        # The collapsed tier's own wording is no longer this page's: it says
        # what every other page says, and search.ADVANCED_* is linted where it
        # is defined (review-report M29).
        ("windows.py link title", "Want finer control over how fast things move?"),
        (
            "windows.py link subtitle",
            "The Impatience add-on lets you set an exact speed instead of just on or off.",
        ),
        ("topbar.py fix-button", "To use this, gtheme needs to turn on one add-on."),
        ("topbar.py built-in label", "The one your desktop comes with"),
    ]
    problems = jargon.check_all(hand_written)
    assert problems == [], "\n".join(problems)
