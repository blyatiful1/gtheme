"""The 24 curated add-on panels are data, and this is what keeps them honest.

Nothing here needs a display, a settings store or a running desktop: the
panels are ``.toml`` files and the ground truth is the committed schema corpus
in ``tests/fixtures/schemas/``, captured from real add-on downloads. That is
deliberate — a made-up key name is the single easiest way to ship a control
that silently does nothing, and it is exactly the kind of mistake a person
reviewing a diff will not catch.
"""

from __future__ import annotations

import pytest
from panels_curated_test_helpers import (
    PANEL_DIR,
    LoadedPanel,
    corpus_enum_nicks,
    corpus_key_types,
    corpus_keys,
    load_panels,
)

from gtheme.panels.descriptor import WidgetKind
from gtheme.ui import jargon

#: DESIGN.md A9: twenty-four curated panels, with DING and its successor
#: sharing one. If this number changes, it changes because a panel was
#: deliberately added or dropped, and this line is where that gets argued.
EXPECTED_PANEL_COUNT = 24

PANELS = load_panels()


def _panel_ids() -> list[str]:
    return [panel.descriptor.id for panel in PANELS]


@pytest.fixture(scope="module")
def panels() -> list[LoadedPanel]:
    return PANELS


def test_every_panel_file_loads_through_the_frozen_model(panels: list[LoadedPanel]) -> None:
    """Parsing happens at import; this asserts we got something from it."""
    assert panels, f"no panel files found under {PANEL_DIR}"
    for panel in panels:
        assert panel.descriptor.rows, f"{panel.path.name}: a panel with no controls is not a panel"


def test_there_are_twenty_four_curated_panels(panels: list[LoadedPanel]) -> None:
    assert len(panels) == EXPECTED_PANEL_COUNT, sorted(_panel_ids())


def test_panel_id_matches_its_filename(panels: list[LoadedPanel]) -> None:
    for panel in panels:
        assert panel.descriptor.id == panel.path.stem


def test_panel_ids_are_unique(panels: list[LoadedPanel]) -> None:
    ids = _panel_ids()
    assert len(ids) == len(set(ids))


def test_at_most_one_panel_per_add_on(panels: list[LoadedPanel]) -> None:
    """No add-on may be claimed by two panels — the gear button needs one answer."""
    owner: dict[str, str] = {}
    for panel in panels:
        for uuid in panel.descriptor.target.uuids:
            assert uuid not in owner, (
                f"{uuid} is claimed by both {owner.get(uuid)} and {panel.descriptor.id}"
            )
            owner[uuid] = panel.descriptor.id


def test_every_add_on_is_in_the_committed_schema_corpus(panels: list[LoadedPanel]) -> None:
    """Panels are written against downloads we kept, not against memory."""
    from panels_curated_test_helpers import FIXTURE_DIR

    for panel in panels:
        for uuid in panel.descriptor.target.uuids:
            assert (FIXTURE_DIR / uuid).is_dir(), (
                f"{panel.descriptor.id}: no captured settings for {uuid}"
            )


def test_every_row_resolves_against_the_corpus(panels: list[LoadedPanel]) -> None:
    """Every (settings id, key) a row names must exist in a real add-on.

    This is the test that makes "never invent a key" enforceable.
    """
    known = corpus_keys()
    problems = []
    for panel in panels:
        for row in panel.descriptor.rows:
            if row.schema_id not in known:
                problems.append(f"{panel.descriptor.id}: unknown settings group {row.schema_id}")
            elif row.key not in known[row.schema_id]:
                problems.append(f"{panel.descriptor.id}: {row.schema_id} has no key {row.key!r}")
    assert not problems, "\n".join(problems)


def test_every_required_first_key_resolves_against_the_corpus(
    panels: list[LoadedPanel],
) -> None:
    """A two-key write that names a key that does not exist is worse than no write."""
    known = corpus_keys()
    problems = []
    for panel in panels:
        for row in panel.descriptor.rows:
            for first in row.requires_first:
                if first.key not in known.get(first.schema_id, set()):
                    problems.append(
                        f"{panel.descriptor.id}: {row.key} needs "
                        f"{first.schema_id}/{first.key} first, which does not exist"
                    )
    assert not problems, "\n".join(problems)


def test_panel_settings_groups_are_declared(panels: list[LoadedPanel]) -> None:
    """Rows may only reach into the groups the panel says the add-on owns."""
    problems = []
    for panel in panels:
        target = panel.descriptor.target
        declared = {target.schema_id, *target.child_schemas}
        for row in panel.descriptor.rows:
            if row.schema_id not in declared:
                problems.append(
                    f"{panel.descriptor.id}: row {row.key!r} reaches into "
                    f"{row.schema_id}, which the panel does not declare"
                )
    assert not problems, "\n".join(problems)


def test_declared_settings_groups_exist(panels: list[LoadedPanel]) -> None:
    known = corpus_keys()
    for panel in panels:
        target = panel.descriptor.target
        for schema_id in (target.schema_id, *target.child_schemas):
            assert schema_id in known, f"{panel.descriptor.id}: {schema_id} is not in the corpus"


def test_choice_values_are_values_the_add_on_accepts(panels: list[LoadedPanel]) -> None:
    """A choice offering a value the add-on rejects is a dead control.

    Only checked for keys the add-on declares as a fixed list; free-form
    strings and plain numbers are the app's own business.
    """
    types = corpus_key_types()
    nicks = corpus_enum_nicks()
    problems = []
    for panel in panels:
        for row in panel.descriptor.rows:
            declared = types.get((row.schema_id, row.key), "")
            allowed = nicks.get(declared)
            if allowed is None:
                continue
            for choice in row.choices:
                bare = choice.value.strip().strip("'\"")
                if bare not in allowed:
                    problems.append(
                        f"{panel.descriptor.id}: {row.key} offers {choice.value} "
                        f"but the add-on only accepts {sorted(allowed)}"
                    )
    assert not problems, "\n".join(problems)


def test_conflicts_are_symmetric(panels: list[LoadedPanel]) -> None:
    """If A replaces B, B replaces A. Otherwise the either/or only works one way."""
    by_uuid = {
        uuid: panel.descriptor for panel in panels for uuid in panel.descriptor.target.uuids
    }
    problems = []
    for panel in panels:
        target = panel.descriptor.target
        for other_uuid in target.conflicts:
            other = by_uuid.get(other_uuid)
            if other is None:
                problems.append(
                    f"{panel.descriptor.id}: conflicts with {other_uuid}, "
                    "which no panel covers"
                )
                continue
            if not set(other.target.conflicts) & set(target.uuids):
                problems.append(
                    f"{panel.descriptor.id} rules out {other_uuid}, "
                    f"but {other.id} does not rule it out in return"
                )
    assert not problems, "\n".join(problems)


def test_the_four_known_either_or_pairs_are_present(panels: list[LoadedPanel]) -> None:
    """The pairs the research names must actually be encoded."""
    conflicts: dict[str, set[str]] = {}
    for panel in panels:
        for uuid in panel.descriptor.target.uuids:
            conflicts[uuid] = set(panel.descriptor.target.conflicts)
    expected = [
        ("dash-to-dock@micxgx.gmail.com", "dash-to-panel@jderose9.github.com"),
        ("clipboard-indicator@tudmotu.com", "clipboard-history@alexsaveau.dev"),
        ("Vitals@CoreCoding.com", "tophat@fflewddur.github.io"),
        ("ding@rastersoft.com", "gtk4-ding@smedius.gitlab.com"),
    ]
    for left, right in expected:
        assert right in conflicts.get(left, set()), f"{left} does not rule out {right}"
        assert left in conflicts.get(right, set()), f"{right} does not rule out {left}"


def test_the_screen_recording_hazard_is_written_down(panels: list[LoadedPanel]) -> None:
    """The one hazard this machine actually has must be on both add-ons.

    Frosting the top bar while it is also set to hide starves screen capture
    on this box. A person who hits it has no way to guess the cause, so both
    halves of the combination say so.
    """
    warned = {
        panel.descriptor.id: " ".join(
            [panel.descriptor.target.warn or ""] + [row.warn or "" for row in panel.descriptor.rows]
        ).lower()
        for panel in panels
    }
    for panel_id in ("blur-my-shell", "hidetopbar"):
        text = warned.get(panel_id, "")
        assert "screen recording" in text, f"{panel_id} does not mention the recording hazard"


def test_every_row_has_a_plain_language_subtitle(panels: list[LoadedPanel]) -> None:
    for panel in panels:
        for row in panel.descriptor.rows:
            assert len(row.subtitle.split()) >= 4, (
                f"{panel.descriptor.id}: {row.key!r} has a subtitle too short to explain anything"
            )
            assert row.subtitle.strip().endswith((".", "!", "?")), (
                f"{panel.descriptor.id}: {row.key!r} subtitle should read as a sentence"
            )


def test_sliders_are_clamped_and_choices_have_options(panels: list[LoadedPanel]) -> None:
    """Belt and braces over the model's own validator, per panel rather than per row."""
    for panel in panels:
        for row in panel.descriptor.rows:
            if row.kind is WidgetKind.SLIDER:
                assert row.clamp_min is not None and row.clamp_max is not None
                assert row.clamp_min < row.clamp_max, f"{panel.descriptor.id}: {row.key}"
            if row.kind is WidgetKind.CHOICE:
                assert len(row.choices) >= 2, (
                    f"{panel.descriptor.id}: {row.key!r} is a choice of one"
                )


def test_choice_labels_are_unique_within_a_row(panels: list[LoadedPanel]) -> None:
    for panel in panels:
        for row in panel.descriptor.rows:
            labels = [choice.label for choice in row.choices]
            assert len(labels) == len(set(labels)), f"{panel.descriptor.id}: {row.key}"


def test_a_row_is_not_listed_twice(panels: list[LoadedPanel]) -> None:
    """One setting, one control — except where a dictionary holds several."""
    for panel in panels:
        seen = [(row.schema_id, row.key, row.dict_key) for row in panel.descriptor.rows]
        assert len(seen) == len(set(seen)), f"{panel.descriptor.id} lists a control twice"


def test_relocatable_panels_declare_a_location_template(panels: list[LoadedPanel]) -> None:
    """burn-my-windows keeps one copy of its settings per profile file."""
    burn = next(p.descriptor for p in panels if p.descriptor.id == "burn-my-windows")
    template = burn.target.relocatable_path_template
    assert template is not None
    assert template.startswith("/") and template.endswith("/")
    assert "{profile}" in template


def test_burn_my_windows_shows_a_handful_not_a_hundred(panels: list[LoadedPanel]) -> None:
    """The 163-setting surface stays hidden; gtheme shows an effect and a speed."""
    burn = next(p.descriptor for p in panels if p.descriptor.id == "burn-my-windows")
    assert len(burn.rows) <= 20, "the whole point was not to render the raw settings"
    everyday = [row for row in burn.rows if not row.advanced]
    assert 4 <= len(everyday) <= 10


def test_window_outline_rows_are_kept_out_of_the_way(panels: list[LoadedPanel]) -> None:
    """House taste: calm window chrome. The outline is offered, never pushed."""
    tiling = next(p.descriptor for p in panels if p.descriptor.id == "tilingshell")
    outline = [
        row
        for row in tiling.rows
        if row.key in {"enable-window-border", "window-border-color", "window-border-width"}
    ]
    assert len(outline) == 3
    for row in outline:
        assert row.advanced, f"{row.key} should sit behind the advanced expander"


@pytest.mark.parametrize("panel", PANELS, ids=_panel_ids())
def test_panel_copy_passes_the_jargon_lint(panel: LoadedPanel) -> None:
    """Every word a person will read, checked against the banned list."""
    where = panel.descriptor.id
    items: list[tuple[str, str]] = [(f"{where}: summary", panel.descriptor.target.summary)]
    if panel.descriptor.target.warn:
        items.append((f"{where}: warning", panel.descriptor.target.warn))
    for row in panel.descriptor.rows:
        items.append((f"{where}: {row.key} title", row.title))
        items.append((f"{where}: {row.key} subtitle", row.subtitle))
        if row.warn:
            items.append((f"{where}: {row.key} warning", row.warn))
        for choice in row.choices:
            items.append((f"{where}: {row.key} option", choice.label))
            if choice.subtitle:
                items.append((f"{where}: {row.key} option note", choice.subtitle))
        for first in row.requires_first:
            items.append((f"{where}: {row.key} explanation", first.explain))
    problems = jargon.check_all(items)
    assert not problems, "\n".join(problems)


def test_categories_are_plain_words(panels: list[LoadedPanel]) -> None:
    """Categories group the add-ons list; they are read by the same person."""
    for panel in panels:
        category = panel.descriptor.target.category
        assert category == category.lower()
        assert not jargon.find_banned(category), f"{panel.descriptor.id}: {category!r}"


def test_every_panel_can_be_offered_for_install(panels: list[LoadedPanel]) -> None:
    """A curated panel with no download reference cannot offer to install it."""
    for panel in panels:
        assert panel.descriptor.target.ego_pk, f"{panel.descriptor.id} has no download reference"


def test_download_reference_matches_the_recorded_provenance(panels: list[LoadedPanel]) -> None:
    """The install offer must point at the add-on the panel is actually for.

    ``MANIFEST.toml`` records what was downloaded and when; a panel that names
    a different reference would offer to install something else entirely.
    """
    import tomllib

    from panels_curated_test_helpers import FIXTURE_DIR

    with (FIXTURE_DIR / "MANIFEST.toml").open("rb") as handle:
        manifest = tomllib.load(handle)
    recorded = {entry["uuid"]: entry["pk"] for entry in manifest["extension"]}

    for panel in panels:
        target = panel.descriptor.target
        expected = {recorded[uuid] for uuid in target.uuids if uuid in recorded}
        assert expected, f"{panel.descriptor.id}: nothing recorded for {target.uuids}"
        assert target.ego_pk in expected, (
            f"{panel.descriptor.id}: says {target.ego_pk}, recorded {sorted(expected)}"
        )


def test_alternates_are_uuids_the_panel_covers(panels: list[LoadedPanel]) -> None:
    for panel in panels:
        target = panel.descriptor.target
        assert set(target.alternates) <= set(target.uuids), panel.descriptor.id
        if target.alternates:
            assert set(target.alternates) == set(target.uuids), (
                f"{panel.descriptor.id}: a preference order must rank every add-on it covers"
            )


def test_synonyms_are_lowercase_and_unique(panels: list[LoadedPanel]) -> None:
    """Search matches on these, and a duplicate just weights one row oddly."""
    for panel in panels:
        for row in panel.descriptor.rows:
            assert row.synonyms == [word.lower() for word in row.synonyms], (
                f"{panel.descriptor.id}: {row.key}"
            )
            assert len(row.synonyms) == len(set(row.synonyms)), (
                f"{panel.descriptor.id}: {row.key}"
            )


def test_descriptor_ids_are_globally_unique_per_panel(panels: list[LoadedPanel]) -> None:
    """Deep-links resolve by descriptor id, so the same id must not be in two panels."""
    owner: dict[str, str] = {}
    for panel in panels:
        for row in panel.descriptor.rows:
            previous = owner.get(row.id)
            assert previous is None, f"{row.id} appears in both {previous} and {panel.descriptor.id}"
            owner[row.id] = panel.descriptor.id
