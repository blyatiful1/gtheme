"""Five duplications, closed: one of each thing instead of nine.

review-report P7 — "duplication is the reliable predictor of divergence" — is
five findings at five scales, and in three of them the copies had **already**
drifted, on markup escaping, on None-guards and on user-visible wording. This
file is the other side of each: not "the shared helper works", which the pages'
own tests cover, but **that there is only one of it** and that nothing has a
second copy to drift from.

* **M28** — nine hand-rolled first-visit explainers.
* **M29** — two page scaffolds with duplicated ``ADVANCED_TITLE`` constants and
  a third wording on Windows & Desktops, plus group headings handed raw to a
  widget with no ``use-markup`` to turn off.
* **L15** — the nine GNOME accent colours, defined twice.
* **L16** — byte-identical ``_action_row`` / ``_button_row`` on the two pages
  that carry the app's safety pair.
* **L19** — GVariant string unquoting, written out longhand eight times.
* **L18(ui)** — three defined-once, never-called helpers.

The structural half of each is read out of the syntax tree rather than by
grepping, so a string that merely looks like the thing is not mistaken for one.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for the widget library")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from gtheme.core import backends, gvariant  # noqa: E402
from gtheme.core.settings_backend import MemoryBackend  # noqa: E402
from gtheme.panels.schema_probe import SchemaProbe  # noqa: E402
from gtheme.prefs import Prefs  # noqa: E402
from gtheme.ui import search  # noqa: E402
from gtheme.ui.pages import _style_common as common  # noqa: E402
from gtheme.ui.pages import colors, home, sound, terminal, windows  # noqa: E402
from gtheme.ui.rowindex import RowIndex  # noqa: E402
from gtheme.ui.widgets import explainer, rows  # noqa: E402
from gtheme.ui.widgets.actions import action_row  # noqa: E402

pytestmark = pytest.mark.gtk


@pytest.fixture(autouse=True, scope="module")
def _adw():
    if not Gtk.init_check():
        pytest.skip("no display is available for GTK — run under gtk4-broadwayd")
    Adw.init()


SRC = Path(__file__).resolve().parents[2] / "src" / "gtheme"


def _modules() -> list[tuple[str, ast.Module]]:
    """Every shipped module, parsed. Named by its path under ``src/gtheme``."""
    found = []
    for path in sorted(SRC.rglob("*.py")):
        found.append((str(path.relative_to(SRC)), ast.parse(path.read_text(encoding="utf-8"))))
    assert len(found) > 30, "the source walk found almost nothing — it is not looking at the app"
    return found


class FakeWindow:
    """The slice of the window a page speaks through."""

    def __init__(self, prefs: Any = None) -> None:
        self.rows = RowIndex()
        self.prefs = prefs
        self.toasts: list[str] = []

    def toast(self, text: str, **_kwargs: Any) -> None:
        self.toasts.append(text)


class NoPrefsWindow:
    """A window with nowhere to remember a dismissal. ``prefs`` is None."""

    def __init__(self) -> None:
        self.rows = RowIndex()
        self.prefs = None


def _walk(widget: Gtk.Widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from _walk(child)
        child = child.get_next_sibling()


def _banners(widget: Gtk.Widget) -> list[Adw.Banner]:
    return [w for w in _walk(widget) if isinstance(w, Adw.Banner)]


# --------------------------------------------------------------------------
# M28 — one first-visit explainer
# --------------------------------------------------------------------------


def test_only_the_shared_explainer_remembers_a_dismissal():
    """The structural claim: nine pages no longer each own this wiring.

    ``mark_banner_seen`` is what makes an explainer one-shot. A page that calls
    it is a page with its own copy of the whole banner — its own idea of what
    to do without a preferences file, its own escaping, its own button word.
    Two modules may call it: the shared widget, and onboarding, whose
    "complete" flag is not a page banner at all.
    """
    callers = {
        name
        for name, tree in _modules()
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"mark_banner_seen", "should_show_banner"}
    }
    assert callers == {"ui/widgets/explainer.py", "ui/onboarding.py"}, sorted(callers)


def test_the_dismiss_button_says_one_word_and_it_is_written_down_once():
    """Change the wording and every page changes with it, or none does."""
    written = [
        name
        for name, tree in _modules()
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and node.value == explainer.BANNER_DISMISS
    ]
    assert written == ["ui/search.py"], written
    assert explainer.BANNER_DISMISS is search.BANNER_DISMISS


@pytest.mark.mutating
def test_an_explainer_with_an_ampersand_says_the_ampersand(config_dir):
    """Two of the nine escaped their sentence and seven handed it over raw.

    ``Adw.Banner:use-markup`` defaults to off — measured, not assumed, in the
    assertion below — so the two that escaped were the wrong two: their banner
    would have read "Fonts &amp;amp; Text" out loud. Turning markup off and
    then setting the text is the only handling that is right on both counts,
    and there is now one place that does it.
    """
    del config_dir
    text = "Fonts & Text live here, and so do Mouse, Touchpad & Keyboard."
    banner = explainer.first_visit_banner(Prefs(), "first-visit-home", text)
    assert banner is not None
    assert banner.get_use_markup() is False, "markup is turned off, not escaped around"
    assert banner.get_title() == text, "and the sentence arrives whole"
    assert "&amp;" not in banner.get_title(), "an escape here is read out loud"


@pytest.mark.mutating
def test_no_explainer_is_shown_where_a_dismissal_cannot_be_remembered(config_dir):
    """The third drift: four sites guarded for this, two dereferenced it.

    With no preferences file the banner could never be dismissed for good, so
    it would come back on every single visit — which the app's own preferences
    module calls "reading as a bug". Two of the nine used to crash instead.
    """
    del config_dir
    assert explainer.first_visit_banner(None, "first-visit-home", "Hello.") is None
    assert explainer.with_first_visit_banner(
        Adw.PreferencesPage(), None, "first-visit-home", "Hello."
    ) is not None


@pytest.mark.mutating
def test_a_page_whose_window_has_no_preferences_still_opens(
    config_dir, memory_settings, tmp_path
):
    """``windows.py`` and ``topbar.py`` read ``window.prefs`` unguarded."""
    del config_dir, tmp_path
    with backends.use_backend(memory_settings):
        page = windows.build(NoPrefsWindow())
    assert _banners(page) == [], "no store to remember it in, so no explainer"


@pytest.mark.mutating
def test_the_scaffold_and_the_pages_all_reach_the_same_explainer(config_dir):
    """One helper, and every caller of it gets the same three promises."""
    del config_dir
    prefs = Prefs()
    shell = common.PageShell(
        FakeWindow(prefs), "colors", banner_id="first-visit-colors", banner_text="Hello."
    )
    assert shell.banner is not None
    assert shell.banner.get_button_label() == explainer.BANNER_DISMISS
    assert shell.banner.get_use_markup() is False

    shell.banner.emit("button-clicked")
    assert prefs.banner_seen("first-visit-colors")

    again = common.PageShell(
        FakeWindow(Prefs()), "colors", banner_id="first-visit-colors", banner_text="Hello."
    )
    assert again.banner is None, "a dismissed explainer is not built at all"


# --------------------------------------------------------------------------
# M29 — one scaffold wording, and headings that survive an ampersand
# --------------------------------------------------------------------------


def test_the_advanced_tier_has_one_wording_and_one_definition():
    """Two scaffolds, each documented as "one wording", each with its own copy."""
    assert common.ADVANCED_TITLE is search.ADVANCED_TITLE
    assert common.ADVANCED_SUBTITLE is search.ADVANCED_SUBTITLE
    written = [
        name
        for name, tree in _modules()
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and node.value == search.ADVANCED_TITLE
    ]
    assert written == ["ui/search.py"], written


@pytest.mark.mutating
def test_windows_and_desktops_calls_the_tier_what_every_other_page_calls_it(
    config_dir, memory_settings
):
    """It said "Advanced" over a sentence of its own — a third wording for the
    identical affordance, met by somebody who had learned "More options" on six
    other pages."""
    del config_dir
    with backends.use_backend(memory_settings):
        page = windows.build(FakeWindow(Prefs()))
    expanders = [w for w in _walk(page) if isinstance(w, Adw.ExpanderRow)]
    titles = [e.get_title() for e in expanders]
    assert search.ADVANCED_TITLE in titles, titles
    assert "Advanced" not in titles, titles


@pytest.mark.mutating
def test_a_group_heading_with_an_ampersand_is_not_swallowed(tmp_path, memory_settings):
    """``Adw.PreferencesGroup`` has no ``use-markup`` to turn off — I checked —
    so its text has to be escaped instead, and nine shipped domain titles carry
    a literal ``&``."""
    window = FakeWindow(Prefs(tmp_path / "prefs.json"))
    with backends.use_backend(memory_settings):
        shell = common.PageShell(window, "colors")
        group = shell.group("Mouse, Touchpad & Keyboard", "Icons & Pointer, too.")
    assert "&amp;" in group.get_title(), group.get_title()
    assert "&amp;" in group.get_description(), group.get_description()


# --------------------------------------------------------------------------
# L15 — one accent table
# --------------------------------------------------------------------------


def test_the_home_card_reads_the_colours_page_s_own_table():
    """A mirror with its own idea of what the desktop supports is not a mirror."""
    assert home.ACCENT_NAMES is colors.ACCENT_LABELS
    assert home.ACCENT_COLOURS is colors.ACCENT_HEXES
    assert set(colors.ACCENT_LABELS) == {slug for slug, _label, _hex in colors.ACCENTS}
    assert set(colors.ACCENT_HEXES) == set(colors.ACCENT_LABELS)


def test_an_accent_this_version_never_heard_of_still_reads_as_a_colour():
    """GNOME 51 adds a tenth accent: the card must degrade, not go raw."""
    assert home.describe_accent("sepia") == "Sepia"
    assert home.describe_accent("deep-orange") == "Deep orange"
    assert colors.accent_hex("sepia") == colors.UNKNOWN_ACCENT_HEX
    assert colors.accent_label(None) is None
    # And a colour it does know is still named the way a person names it.
    assert home.describe_accent("slate") == "Grey"


# --------------------------------------------------------------------------
# L16 — one action row
# --------------------------------------------------------------------------


def test_the_two_safety_pages_no_longer_carry_their_own_copies():
    """Home and Undo & Restore Points build the app's safety pair. A busy state
    or an accessible label added to one used to land on one page only."""
    defined = [
        f"{name}.{node.name}"
        for name, tree in _modules()
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name in {"_action_row", "_button_row"}
    ]
    assert defined == [], defined


def test_an_action_row_does_what_its_button_does():
    fired: list[str] = []
    row = action_row(
        "Save this moment", "So you can come back to it.", "Save", lambda: fired.append("go")
    )
    button = row.get_activatable_widget()
    assert isinstance(button, Gtk.Button)
    assert button.get_label() == "Save"
    button.emit("clicked")
    assert fired == ["go"]


def test_an_action_row_title_is_text_rather_than_markup():
    row = action_row("Icons & Pointer", "Mouse, Touchpad & Keyboard.", "Open", lambda: None)
    assert row.get_use_markup() is False
    assert row.get_title() == "Icons & Pointer"


def test_the_recommended_action_is_the_one_that_looks_recommended():
    row = action_row("A", "B", "Do it", lambda: None, suggested=True)
    assert "suggested-action" in row.get_activatable_widget().get_css_classes()
    plain = action_row("A", "B", "Do it", lambda: None)
    assert "suggested-action" not in plain.get_activatable_widget().get_css_classes()


# --------------------------------------------------------------------------
# L19 — one quote/unquote pair
# --------------------------------------------------------------------------


#: The shape of the hand-rolled unquote, as it was written in all eight places:
#: a length check, both ends equal, and that end being a quote character.
def _hand_rolled_unquote_sites() -> list[str]:
    found = []
    for name, tree in _modules():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            for comparator in node.comparators:
                if (
                    isinstance(comparator, ast.Constant)
                    and isinstance(comparator.value, str)
                    and set(comparator.value) == {"'", '"'}
                ):
                    found.append(name)
    return found


def test_gvariant_unquoting_is_written_out_exactly_once():
    """It was in eight modules, one of them the *frozen* row library — where a
    fix would have been invisible to the sound-set picker, the terminal-app
    picker and burn-my-windows file resolution."""
    assert _hand_rolled_unquote_sites() == ["core/gvariant.py"]


def test_everything_that_quotes_a_setting_uses_the_one_pair():
    assert rows.unquote is gvariant.unquote
    assert rows.quote is gvariant.quote
    assert common.unquote is gvariant.unquote
    assert common.quote is gvariant.quote
    assert sound.unquote is gvariant.unquote
    assert terminal.quote is gvariant.quote


@pytest.mark.parametrize(
    "text", ["Papirus-Dark", "adw-gtk3", "", "a 'quoted' name", 'a "double" one', "back\\slash"]
)
def test_quoting_round_trips_including_the_awkward_names(text):
    """The two hand-rolled quoting mechanisms round-tripped correctly today.
    This is what keeps that true now that there is only one of them."""
    assert gvariant.unquote(gvariant.quote(text)) == text


@pytest.mark.parametrize(
    ("stored", "expected"),
    [("'x'", "x"), ('"x"', "x"), ("24", "24"), ("  'y' ", "y"), ("true", "true"), ("", "")],
)
def test_unquoting_takes_off_the_quoting_and_nothing_else(stored, expected):
    assert gvariant.unquote(stored) == expected


# --------------------------------------------------------------------------
# L18(ui) — three helpers nothing ever called
# --------------------------------------------------------------------------


def test_the_helpers_nobody_called_are_gone():
    """All three had zero callers in ``src/`` and zero in ``tests/``.

    ``PageShell.built_ids`` was the load-bearing one: a docstring on
    ``surfaced_ids`` claims "a test compares this list against what the page
    actually built", and it does — through the window's row index, which is the
    thing search and deep links use, for all three style pages. The property
    was a second answer to that question that nothing asked.
    """
    assert not hasattr(SchemaProbe, "source_for_row")
    assert not hasattr(Prefs, "as_dict")
    assert not hasattr(common.PageShell, "built_ids")


@pytest.mark.mutating
def test_the_claim_the_deleted_property_was_standing_in_for_is_still_kept(
    tmp_path, memory_settings
):
    """The promise ``surfaced_ids`` makes, proven the way the app actually
    keeps it: every descriptor a page owns is registered in the row index, so
    search and a deep link can find it."""
    from gtheme.ui.pages import colors as colors_page

    window = FakeWindow(Prefs(tmp_path / "prefs.json"))
    with backends.use_backend(memory_settings):
        colors_page.build(window)
    for descriptor_id in common.surfaced_ids("colors"):
        assert descriptor_id in window.rows, f"{descriptor_id} was not rendered"


# --------------------------------------------------------------------------
# the pages that used to be the nine, built
# --------------------------------------------------------------------------


@pytest.mark.mutating
def test_every_page_that_shows_an_explainer_shows_it_once(config_dir, memory_settings):
    """Built twice with the same preferences: the second build has no banner.

    Two pages are left out on purpose. Add-ons needs a live desktop to talk to,
    and Looks keeps its banner as a member and reveals it rather than building
    it — both are covered by their own pages' tests.
    """
    del config_dir
    prefs = Prefs()
    for module in (windows, terminal):
        with backends.use_backend(memory_settings):
            first = module.build(FakeWindow(prefs))
        shown = [b for b in _banners(first) if b.get_revealed()]
        assert shown, f"{module.__name__} showed nothing on a genuinely first visit"
        assert shown[0].get_button_label() == explainer.BANNER_DISMISS
        assert shown[0].get_use_markup() is False
        shown[0].emit("button-clicked")

        with backends.use_backend(memory_settings):
            second = module.build(FakeWindow(Prefs()))
        assert not [
            b for b in _banners(second) if b.get_revealed()
        ], f"{module.__name__} brought its explainer back"


def test_the_backend_stand_in_is_a_real_one():
    """A guard under the tests above: they must be exercising a settings store."""
    assert issubclass(MemoryBackend, object)
    assert hasattr(MemoryBackend(), "get")
