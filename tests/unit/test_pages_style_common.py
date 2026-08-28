"""The scaffolding the three style pages share.

Nothing here is presented. Widgets are constructed and inspected, every value
goes to an in-memory settings store, and the live desktop is never read from or
written to.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for the page library")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from gtheme.core.backends import use_backend  # noqa: E402
from gtheme.core.settings_backend import (  # noqa: E402
    BackendError,
    BackendErrorKind,
    MemoryBackend,
)
from gtheme.core.transaction import SettingWrite  # noqa: E402
from gtheme.panels.descriptor import Row, WidgetKind  # noqa: E402
from gtheme.prefs import Prefs  # noqa: E402
from gtheme.ui import registry  # noqa: E402
from gtheme.ui.pages import _style_common as common  # noqa: E402
from gtheme.ui.rowindex import RowIndex  # noqa: E402
from gtheme.ui.widgets.rows import (  # noqa: E402
    PUT_BACK_DEFAULT,
    PUT_BACK_RECORDED,
    key_for,
)

pytestmark = pytest.mark.gtk


class FakeWindow:
    """Everything a page asks of its window, and nothing else.

    Deliberately not a real ``Window``: a page that reaches for something the
    window happens to have is a page the integration wave cannot move, and this
    stand-in is what catches that at the moment it happens.
    """

    def __init__(self, prefs_path: Any = None) -> None:
        self.rows = RowIndex()
        self.prefs = Prefs(prefs_path)
        self.said: list[str] = []

    def toast(self, text: str, **_kwargs: Any) -> None:
        self.said.append(text)


def make_window(tmp_path: Any) -> FakeWindow:
    return FakeWindow(tmp_path / "prefs.json")


def build_page(module: Any, window: FakeWindow, backend: Any) -> Gtk.Widget:
    """Build a page against a settings store that goes nowhere."""
    with use_backend(backend):
        return module.build(window)


# --------------------------------------------------------------------------
# the coverage join
# --------------------------------------------------------------------------


def test_the_page_manifest_and_the_coverage_manifest_agree():
    """Every surfaced disposition names a page that exists. The join, proven."""
    dispositions = common.coverage_dispositions()
    assert dispositions, "coverage.toml was not found — the join cannot be checked"
    resolved = registry.resolve_surfaced(dispositions)
    assert set(resolved) == set(registry.page_ids())


@pytest.mark.parametrize("page_id", ["colors", "icons", "fonts"])
def test_each_style_page_owns_at_least_one_setting(page_id):
    assert common.surfaced_ids(page_id)


def test_every_surfaced_id_of_these_pages_is_in_the_corpus():
    """A page cannot render a descriptor nobody wrote."""
    rows = common.corpus_rows()
    missing = [
        descriptor_id
        for page_id in ("colors", "icons", "fonts")
        for descriptor_id in common.surfaced_ids(page_id)
        if descriptor_id not in rows
    ]
    assert missing == []


# --------------------------------------------------------------------------
# small pure helpers
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stored", "expected"),
    [("'Adwaita'", "Adwaita"), ('"x"', "x"), ("24", "24"), ("  'y' ", "y")],
)
def test_unquote_strips_only_the_quoting(stored, expected):
    assert common.unquote(stored) == expected


def test_quote_round_trips_through_unquote():
    for text in ("Papirus-Dark", "adw-gtk3", "", "a 'quoted' name"):
        assert common.unquote(common.quote(text)) == text


def test_search_text_carries_the_words_a_person_would_type():
    row = common.corpus_rows()["org.gnome.desktop.interface:icon-theme"]
    text = common.search_text(row).lower()
    assert "icon set" in text
    assert "papirus" in text  # a synonym, which is the whole point


# --------------------------------------------------------------------------
# the picker
# --------------------------------------------------------------------------


def _picker_row_descriptor() -> Row:
    return Row(
        schema_id="org.gnome.desktop.interface",
        key="gtk-theme",
        title="App style",
        subtitle="Sets how buttons and menus look.",
        kind=WidgetKind.PICKER,
    )


@pytest.mark.mutating
def test_picker_writes_the_chosen_value(memory_settings):
    row = _picker_row_descriptor()
    memory_settings.set(key_for(row), "'adw-gtk3'")
    widget, _refresh = common.picker_row(
        memory_settings, row, [("adw-gtk3", "adw-gtk3"), ("adw-gtk3-dark", "adw-gtk3-dark")]
    )
    assert widget.get_selected() == 0
    widget.set_selected(1)
    assert memory_settings.get(key_for(row)) == "'adw-gtk3-dark'"


@pytest.mark.mutating
def test_picker_shows_a_value_that_is_not_installed_rather_than_lying(memory_settings):
    """The trap every combo row falls into: an unknown value clamped to index 0."""
    row = _picker_row_descriptor()
    memory_settings.set(key_for(row), "'SomethingElse'")
    widget, _refresh = common.picker_row(memory_settings, row, [("adw-gtk3", "adw-gtk3")])
    model = widget.get_model()
    assert model.get_n_items() == 2
    assert widget.get_selected() == 1
    assert "not on this computer" in model.get_string(1)
    # And the value it did not offer was left exactly as it was.
    assert memory_settings.get(key_for(row)) == "'SomethingElse'"


@pytest.mark.mutating
def test_picker_offers_the_empty_answer_when_empty_is_a_real_answer(memory_settings):
    row = _picker_row_descriptor()
    memory_settings.set(key_for(row), "''")
    widget, _refresh = common.picker_row(
        memory_settings, row, [("adw-gtk3", "adw-gtk3")], empty_label="The one it came with"
    )
    assert widget.get_selected() == 0
    assert widget.get_model().get_string(0) == "The one it came with"


@pytest.mark.mutating
def test_picker_carries_the_put_this_back_button(memory_settings):
    row = _picker_row_descriptor()
    widget, _refresh = common.picker_row(memory_settings, row, [("adw-gtk3", "adw-gtk3")])
    buttons = [w for w in _walk(widget) if isinstance(w, Gtk.Button)]
    # Either wording is the reset button; which one it says depends on whether
    # gtheme has a pristine value recorded for this setting yet, and a picker
    # built against a store nobody has touched has none (review-report H3).
    assert any(
        b.get_tooltip_text() in (PUT_BACK_RECORDED, PUT_BACK_DEFAULT) for b in buttons
    ), "a hand-built picker must get the same reset button every other row gets"


def _walk(widget: Gtk.Widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from _walk(child)
        child = child.get_next_sibling()


# --------------------------------------------------------------------------
# the shell
# --------------------------------------------------------------------------


@pytest.mark.mutating
def test_the_first_visit_explainer_is_shown_once_and_then_never_again(
    tmp_path, memory_settings
):
    window = make_window(tmp_path)
    with use_backend(memory_settings):
        first = common.PageShell(
            window, "colors", banner_id="first-visit-colors", banner_text="Hello."
        )
        assert first.banner is not None
        first.banner.emit("button-clicked")
        second = common.PageShell(
            window, "colors", banner_id="first-visit-colors", banner_text="Hello."
        )
    assert second.banner is None
    assert window.prefs.banner_seen("first-visit-colors")


@pytest.mark.mutating
def test_a_page_registers_what_it_built_and_forgets_it_on_teardown(
    tmp_path, memory_settings
):
    window = make_window(tmp_path)
    with use_backend(memory_settings):
        shell = common.PageShell(window, "colors")
        group = shell.group("Ease of use")
        shell.add_descriptor_row(group, "org.gnome.desktop.a11y.interface:high-contrast")
        widget = shell.finish()
    assert "org.gnome.desktop.a11y.interface:high-contrast" in window.rows
    assert window.rows.page_of("org.gnome.desktop.a11y.interface:high-contrast") == "colors"
    widget.run_dispose()
    assert len(window.rows) == 0


@pytest.mark.mutating
def test_the_idle_probe_is_started_and_removed_with_the_page(tmp_path, memory_settings):
    """A probe left running after teardown would call back into dead widgets."""
    window = make_window(tmp_path)
    with use_backend(memory_settings):
        shell = common.PageShell(window, "colors")
        group = shell.group("Ease of use")
        shell.add_descriptor_row(group, "org.gnome.desktop.a11y.interface:high-contrast")
        widget = shell.finish()
    assert shell._source_id is not None
    widget.run_dispose()
    assert shell._source_id is None


@pytest.mark.mutating
def test_an_unknown_descriptor_does_not_take_the_page_down(tmp_path, memory_settings):
    window = make_window(tmp_path)
    with use_backend(memory_settings):
        shell = common.PageShell(window, "colors")
        group = shell.group("Nothing here")
        assert shell.add_descriptor_row(group, "org.example.nope:missing") is None
        shell.finish()


@pytest.mark.mutating
def test_the_advanced_expander_says_what_is_inside_it(tmp_path, memory_settings):
    window = make_window(tmp_path)
    with use_backend(memory_settings):
        shell = common.PageShell(window, "colors")
        expander = shell.advanced(shell.group("Ease of use"))
    assert isinstance(expander, Adw.ExpanderRow)
    assert expander.get_title() == common.ADVANCED_TITLE
    assert expander.get_subtitle() == common.ADVANCED_SUBTITLE


@pytest.mark.mutating
def test_one_probe_is_shared_by_every_page_of_a_window(tmp_path, memory_settings):
    window = make_window(tmp_path)
    with use_backend(memory_settings):
        first = common.PageShell(window, "colors")
        second = common.PageShell(window, "icons")
    assert first.probe is second.probe


def test_apply_ops_with_nothing_to_do_changes_nothing_and_says_nothing(tmp_path):
    window = make_window(tmp_path)
    assert common.apply_ops(window, [], done="never shown") is True
    assert window.said == []


# --------------------------------------------------------------------------
# apply_ops, driven for real
# --------------------------------------------------------------------------
#
# review-report M17: the only test this function had passed ``[]`` and returned
# at the ``if not ops`` guard, before the transaction, before the toast, and
# before the failure branch — so the two controls that go through it (the dark
# mode switch and the window-heading lettering) were covered by nothing at all.
# These four drive the real ``Transaction``: one change that lands, and the two
# halves of the sentence a change that did not land is allowed to say.

APPLY_SCHEMA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<schemalist>
  <schema id="io.github.blyatiful1.GthemeApplyOps"
          path="/io/github/blyatiful1/gtheme-apply-ops/">
    <key name="first" type="s"><default>'one'</default></key>
    <key name="second" type="s"><default>'two'</default></key>
  </schema>
</schemalist>
"""

APPLY_ID = "io.github.blyatiful1.GthemeApplyOps"
FIRST = f"gsettings:{APPLY_ID} first"
SECOND = f"gsettings:{APPLY_ID} second"

#: The half-sentence the failure branch adds when the desktop is NOT known to
#: be as it was. Written out here rather than imported so that changing the
#: wording in the page has to be a deliberate edit in both places.
MAYBE_CHANGED = "Some of it may have been changed anyway."


class RefusesEveryWrite(MemoryBackend):
    """A locked-down store: reads fine, refuses every write, from op one."""

    def set(self, key: str, value: str) -> None:
        raise BackendError(BackendErrorKind.COMMIT_FAILED, f"refused {key}", key=key)


class RefusesAfterTheFirstWrite(MemoryBackend):
    """Lets one write through, then refuses — the rollback included.

    This is the shape of the failure the second half of the sentence exists
    for: op one landed, op two did not, and putting op one back was refused as
    well, so the desktop is genuinely half-changed and nobody may say it is not.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.writes = 0

    def seed(self, key: str, value: str) -> None:
        """Put a starting value in without spending the one allowed write."""
        super().set(key, value)

    def set(self, key: str, value: str) -> None:
        self.writes += 1
        if self.writes == 1:
            super().set(key, value)
            return
        raise BackendError(BackendErrorKind.COMMIT_FAILED, f"refused {key}", key=key)


@pytest.mark.mutating
def test_a_compound_change_really_moves_the_settings_and_says_it_did(
    tmp_path, tmp_dest_root, state_dir, schema_source_factory
):
    """The success path, end to end: two keys, one transaction, both moved."""
    backend = MemoryBackend(schema_source=schema_source_factory(APPLY_SCHEMA_XML))
    backend.set(FIRST, "'one'")
    backend.set(SECOND, "'two'")
    window = make_window(tmp_path)

    with use_backend(backend):
        done = common.apply_ops(
            window,
            [
                SettingWrite(key=FIRST, value="'moved'", component="colours"),
                SettingWrite(key=SECOND, value="'also moved'", component="colours"),
            ],
            done="Changed.",
        )

    assert done is True
    assert backend.get(FIRST) == "'moved'"
    assert backend.get(SECOND) == "'also moved'"
    assert window.said == ["Changed."]


@pytest.mark.mutating
def test_a_refused_change_is_reported_and_nothing_is_left_behind(
    tmp_path, tmp_dest_root, state_dir, schema_source_factory
):
    """Refused at op one: the desktop really is untouched, so nothing hedges."""
    backend = RefusesEveryWrite(schema_source=schema_source_factory(APPLY_SCHEMA_XML))
    window = make_window(tmp_path)

    with use_backend(backend):
        done = common.apply_ops(
            window,
            [SettingWrite(key=FIRST, value="'moved'", component="colours")],
            done="never shown",
        )

    assert done is False, "the page must know the change did not happen"
    assert window.said, "and the person must be told"
    said = window.said[-1]
    assert "could not be made" in said
    assert MAYBE_CHANGED not in said, (
        "the desktop was never written to; hedging here teaches a person to "
        "distrust the one sentence that means something"
    )


@pytest.mark.mutating
def test_a_half_applied_change_admits_the_desktop_may_have_moved(
    tmp_path, tmp_dest_root, state_dir, schema_source_factory
):
    """The other half of M17: ``rolled_back`` False must reach the sentence."""
    backend = RefusesAfterTheFirstWrite(
        schema_source=schema_source_factory(APPLY_SCHEMA_XML)
    )
    backend.seed(FIRST, "'one'")
    backend.seed(SECOND, "'two'")
    window = make_window(tmp_path)

    with use_backend(backend):
        done = common.apply_ops(
            window,
            [
                SettingWrite(key=FIRST, value="'moved'", component="colours"),
                SettingWrite(key=SECOND, value="'also moved'", component="colours"),
            ],
            done="never shown",
        )

    assert done is False
    said = window.said[-1]
    assert "could not be made" in said
    assert MAYBE_CHANGED in said, (
        "op one landed and could not be put back — saying nothing about that "
        "is the failure this clause exists to prevent"
    )
    assert backend.get(FIRST) == "'moved'", "the premise of the test: it is still there"


def test_a_change_that_cannot_even_start_says_the_desktop_is_untouched(tmp_path):
    """``OSError`` out of the lock file, from before the guarded section.

    Kept next to its siblings because it is the same branch seen from the third
    side: a failure that is not a ``TransactionError`` at all.
    """
    window = make_window(tmp_path)

    class _NoRoom:
        def __init__(self, ops) -> None:
            self.ops = ops

        def apply(self, *_args: Any, **_kwargs: Any) -> None:
            raise PermissionError(13, "Permission denied")

    original = common.Transaction
    common.Transaction = _NoRoom
    try:
        done = common.apply_ops(
            window, [SettingWrite(key=FIRST, value="'moved'")], done="never shown"
        )
    finally:
        common.Transaction = original

    assert done is False
    assert "exactly as it was" in window.said[-1]
    assert MAYBE_CHANGED not in window.said[-1]
