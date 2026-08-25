"""The floor: what More Settings draws for a setting nobody described.

These tests read the *live* settings definitions installed on this machine —
read-only, through ``Gio.SettingsSchemaSource``, the same way the page does.
Nothing is written anywhere. That is deliberate: the whole point of the floor
is that it draws itself from whatever the desktop actually has, so a fixture
that pretends would test the pretence.
"""

from __future__ import annotations

import pytest

pytest.importorskip("gi", reason="PyGObject is needed to read the desktop's own settings")

from gtheme.panels.descriptor import WidgetKind  # noqa: E402
from gtheme.panels.schema_probe import SchemaProbe  # noqa: E402
from gtheme.ui import jargon, search  # noqa: E402
from gtheme.ui.pages import more  # noqa: E402


@pytest.fixture(scope="module")
def probe() -> SchemaProbe:
    return SchemaProbe()


@pytest.fixture(scope="module")
def floor(probe) -> list[more.FloorKey]:
    return more.floor_keys(probe)


# -- humanising -------------------------------------------------------------


def test_a_setting_name_becomes_a_sentence():
    assert more.humanise("show-battery-percentage") == "Show battery percentage"
    assert more.humanise("enable") == "Enable"
    assert more.humanise("mouse_wheel_zoom") == "Mouse wheel zoom"


# -- the floor itself -------------------------------------------------------


def test_the_floor_draws_a_row_for_every_key_nobody_described(floor):
    assert {entry.id for entry in floor} == set(search.floor_ids())


def test_every_floor_row_has_a_title_and_an_explanation(floor):
    for entry in floor:
        assert entry.title.strip(), f"{entry.id}: no title"
        assert entry.subtitle.strip(), f"{entry.id}: no explanation"


def test_no_floor_row_shows_a_raw_setting_name_as_its_title(floor):
    """A title of ``picture-uri`` is the failure the whole app exists against."""
    for entry in floor:
        assert entry.title != entry.key, f"{entry.id}: the title is the setting's own name"


def test_most_of_the_floor_is_actually_editable(floor):
    """A floor of read-only rows would be a list, not a page."""
    editable = [entry for entry in floor if entry.row is not None]
    assert len(editable) > len(floor) * 0.7


def test_switches_sliders_choices_and_shortcuts_all_appear(floor):
    kinds = {entry.row.kind for entry in floor if entry.row is not None}
    assert WidgetKind.TOGGLE in kinds
    assert WidgetKind.SLIDER in kinds
    assert WidgetKind.CHOICE in kinds
    assert WidgetKind.SHORTCUT in kinds


def test_a_key_combination_is_captured_rather_than_typed(floor):
    """The hardware media keys are shortcuts, and a shortcut is pressed."""
    volume = next(
        entry
        for entry in floor
        if entry.id == "org.gnome.settings-daemon.plugins.media-keys:volume-up-static"
    )
    assert volume.row is not None and volume.row.kind is WidgetKind.SHORTCUT


def test_a_pick_one_row_offers_the_values_the_setting_will_take(floor):
    tracking = next(
        entry for entry in floor if entry.id == "org.gnome.desktop.a11y.magnifier:mouse-tracking"
    )
    assert tracking.row is not None and tracking.row.kind is WidgetKind.CHOICE
    assert [choice.value for choice in tracking.row.choices] == [
        "'none'",
        "'centered'",
        "'proportional'",
        "'push'",
    ]


def test_a_slider_never_reaches_the_user_without_bounds(floor):
    for entry in floor:
        if entry.row is not None and entry.row.kind is WidgetKind.SLIDER:
            assert entry.row.clamp_min is not None and entry.row.clamp_max is not None
            assert entry.row.clamp_min < entry.row.clamp_max


def test_a_list_of_app_names_is_shown_and_not_offered_as_a_text_box(floor):
    """A text box over an ``as`` value is a way to break the desktop by typing."""
    disabled = next(
        entry for entry in floor if entry.id == "org.gnome.desktop.search-providers:disabled"
    )
    assert disabled.row is None


def test_a_setting_this_computer_does_not_have_still_gets_a_row(probe):
    entries = more.floor_keys(probe, ids=["io.github.blyatiful1.Nope:some-key"])
    assert len(entries) == 1
    assert entries[0].title == "Some key"
    assert entries[0].row is None


def test_a_malformed_id_is_skipped_rather_than_drawn(probe):
    assert more.floor_keys(probe, ids=["not-an-identifier"]) == []


# -- the group explainers ---------------------------------------------------


def test_every_group_this_page_will_show_has_a_hand_written_explanation(floor):
    """DESIGN.md C18: the floor's collapsed groups carry mandatory explainers."""
    from gtheme.panels import loader

    corpus = loader.load_corpus()
    authored = {row.id for row in search.page_rows(more.PAGE_ID, corpus=corpus)}
    domains = [
        domain.id
        for domain in corpus.domains
        if any(row.id in authored for row in domain.rows)
    ]
    problems = more.missing_explainers(
        sorted({entry.schema_id for entry in floor}), sorted(domains)
    )
    assert problems == [], "\n".join(problems)


def test_the_explainer_check_would_actually_catch_a_missing_one():
    assert more.missing_explainers(["org.gnome.made.up"], []) == [
        "org.gnome.made.up: no group explanation"
    ]
    assert more.missing_explainers([], ["made-up"]) == ["made-up: no group explanation"]


def test_no_group_explainer_is_a_stub(floor):
    for schema_id in {entry.schema_id for entry in floor}:
        assert len(more.SCHEMA_EXPLAINERS[schema_id]) > 40
        assert more.SCHEMA_EXPLAINERS[schema_id].strip().endswith(".")
        assert more.SCHEMA_TITLES[schema_id].strip()


def test_the_groups_and_headings_speak_plain_english():
    """The words gtheme chooses are linted; the system's own words are not."""
    items = [(f"SCHEMA_TITLES[{k}]", v) for k, v in more.SCHEMA_TITLES.items()]
    items += [(f"SCHEMA_EXPLAINERS[{k}]", v) for k, v in more.SCHEMA_EXPLAINERS.items()]
    items += [(f"GROUP_EXPLAINERS[{k}]", v) for k, v in more.GROUP_EXPLAINERS.items()]
    problems = jargon.check_all(items)
    assert problems == [], "\n".join(problems)


def test_the_floor_says_whose_words_these_are():
    """The system's summaries are shown, and labelled as the system's."""
    assert "your desktop" in more.COPY["floor-description"]
    assert "your desktop" in more.COPY["system-text"]
