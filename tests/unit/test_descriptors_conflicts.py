"""Add-ons that cannot live together, and the one combination that breaks capture."""

from __future__ import annotations

import pytest

from gtheme.panels.conflicts import (
    CONFLICTS,
    HAZARDS,
    Conflict,
    active_conflicts,
    active_hazards,
    conflicts_with,
    from_panels,
    replacement_question,
)
from gtheme.panels.descriptor import PanelDescriptor
from gtheme.ui import jargon

DOCK = "dash-to-dock@micxgx.gmail.com"
PANEL = "dash-to-panel@jderose9.github.com"
BLUR = "blur-my-shell@aunetx"
HIDE = "hidetopbar@mathieu.bidon.ca"
PANEL_BLUR = "org.gnome.shell.extensions.blur-my-shell.panel:blur"


def test_the_four_known_either_or_pairs_are_all_here():
    pairs = {conflict.pair for conflict in CONFLICTS}
    assert frozenset({DOCK, PANEL}) in pairs
    assert frozenset({"clipboard-indicator@tudmotu.com", "clipboard-history@alexsaveau.dev"}) in pairs
    assert frozenset({"Vitals@CoreCoding.com", "tophat@fflewddur.github.io"}) in pairs
    assert frozenset({"ding@rastersoft.com", "gtk4-ding@smedius.gitlab.com"}) in pairs
    assert len(pairs) == len(CONFLICTS)


def test_a_pair_reads_the_same_from_either_side():
    assert conflicts_with(DOCK) == [PANEL]
    assert conflicts_with(PANEL) == [DOCK]
    assert conflicts_with("caffeine@patapon.info") == []


def test_both_being_on_is_reported_once():
    found = active_conflicts([DOCK, PANEL, "caffeine@patapon.info"])
    assert [conflict.pair for conflict in found] == [frozenset({DOCK, PANEL})]


def test_nothing_is_reported_when_only_one_is_on():
    assert active_conflicts([DOCK, BLUR]) == []


def test_the_offer_names_both_by_their_own_names():
    assert replacement_question("Dash to Dock", "Dash to Panel") == (
        "Dash to Dock replaces Dash to Panel. Turn Dash to Panel off?"
    )


def test_every_explanation_is_in_plain_words():
    for conflict in CONFLICTS:
        assert jargon.check(conflict.explain, where=f"{conflict.a}/{conflict.b}") == []
    for hazard in HAZARDS:
        assert jargon.check(hazard.explain, where="/".join(hazard.uuids)) == []


# -- the screen-capture hazard ---------------------------------------------


def test_blurring_a_hidden_top_bar_is_warned_about():
    """Both on plus the blur switched on: recording quietly stops working."""
    hazards = active_hazards([BLUR, HIDE], is_true=lambda descriptor: descriptor == PANEL_BLUR)
    assert len(hazards) == 1
    assert "screen recording" in hazards[0].explain


def test_the_hazard_is_quiet_when_the_blur_is_off():
    assert active_hazards([BLUR, HIDE], is_true=lambda _descriptor: False) == []


def test_the_hazard_is_quiet_when_only_one_add_on_is_on():
    assert active_hazards([BLUR], is_true=lambda _descriptor: True) == []


def test_with_nothing_to_check_against_the_warning_still_shows():
    """Warning without evidence beats silence without evidence."""
    assert len(active_hazards([BLUR, HIDE])) == 1


# -- pairs that come from panel files --------------------------------------


def _panel(uuid: str, conflicts: list[str]) -> PanelDescriptor:
    return PanelDescriptor.model_validate(
        {
            "id": uuid.split("@")[0],
            "target": {
                "uuids": [uuid],
                "schema_id": "org.gnome.shell.extensions.example",
                "conflicts": conflicts,
                "category": "looks",
                "summary": "Does one thing to how the desktop looks.",
            },
        }
    )


def test_a_panel_can_introduce_a_pair_without_a_code_change():
    extra = from_panels([_panel("new@example.com", ["other@example.com"])])
    assert len(extra) == 1
    assert extra[0].pair == frozenset({"new@example.com", "other@example.com"})
    assert active_conflicts(["new@example.com", "other@example.com"], extra) == extra


def test_a_pair_that_is_already_written_out_properly_is_not_duplicated():
    assert from_panels([_panel(DOCK, [PANEL])]) == []


def test_a_panel_that_conflicts_with_nothing_adds_nothing():
    assert from_panels([_panel("lonely@example.com", [])]) == []


@pytest.mark.parametrize("conflict", CONFLICTS, ids=lambda c: c.a.split("@")[0])
def test_no_pair_names_the_same_add_on_twice(conflict: Conflict):
    assert conflict.a != conflict.b
