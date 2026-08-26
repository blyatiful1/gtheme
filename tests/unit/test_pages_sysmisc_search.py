"""The index and the join that feeds every page in the System section.

No GTK here on purpose. Which settings land on which page, and what the search
box can find, are data questions — and answering them without a display means
they are answered in the ordinary test tier that runs everywhere.
"""

from __future__ import annotations

import pytest

from gtheme.panels.descriptor import Choice, DomainDescriptor, PanelDescriptor, Row, WidgetKind
from gtheme.panels.loader import Corpus, load_corpus
from gtheme.ui import registry, search


def _row(schema_id: str, key: str, **overrides) -> Row:
    base = {
        "schema_id": schema_id,
        "key": key,
        "title": "A setting",
        "subtitle": "What it does, in plain words.",
        "kind": WidgetKind.TOGGLE,
    }
    base.update(overrides)
    return Row(**base)


def _corpus(rows: list[Row], panels: list[PanelDescriptor] | None = None) -> Corpus:
    return Corpus(
        panels=panels or [],
        domains=[DomainDescriptor(id="d", title="A domain", rows=rows)],
    )


# -- coverage_dispositions --------------------------------------------------


def test_the_shipped_manifest_dispositions_every_key_of_the_universe():
    given = search.coverage_dispositions()
    assert len(given) > 500, "the coverage manifest did not load"


def test_a_missing_manifest_is_empty_rather_than_fatal(tmp_path, monkeypatch):
    """A packaging mistake must show as empty pages, never as a refusal to open."""
    monkeypatch.setenv(search.DATA_DIR_ENV, str(tmp_path))
    (tmp_path / "domains").mkdir()
    assert search.coverage_dispositions() == {}


def test_an_unreadable_manifest_is_empty_rather_than_fatal(tmp_path, monkeypatch):
    monkeypatch.setenv(search.DATA_DIR_ENV, str(tmp_path))
    (tmp_path / "domains").mkdir()
    (tmp_path / "domains" / "coverage.toml").write_text("this is not = = toml", encoding="utf-8")
    assert search.coverage_dispositions() == {}


# -- the join ---------------------------------------------------------------


def test_page_rows_returns_only_the_rows_that_page_was_promised():
    rows = [_row("a.b", "one"), _row("a.b", "two"), _row("a.b", "three")]
    resolved = search.page_rows(
        "sound",
        corpus=_corpus(rows),
        dispositions={
            "a.b:one": "surfaced(sound)",
            "a.b:two": "surfaced(power)",
            "a.b:three": "surfaced(sound)",
        },
    )
    assert [row.id for row in resolved] == ["a.b:one", "a.b:three"]


def test_page_rows_keeps_the_order_somebody_authored():
    rows = [_row("a.b", "z"), _row("a.b", "a")]
    resolved = search.page_rows(
        "sound",
        corpus=_corpus(rows),
        dispositions={"a.b:z": "surfaced(sound)", "a.b:a": "surfaced(sound)"},
    )
    assert [row.key for row in resolved] == ["z", "a"], "corpus order is authoring order"


def test_floor_keys_are_the_ones_nobody_wrote_a_row_for():
    rows = [_row("a.b", "written")]
    dispositions = {"a.b:written": "floor", "a.b:unwritten": "floor"}
    assert search.floor_ids(corpus=_corpus(rows), dispositions=dispositions) == ["a.b:unwritten"]
    assert search.page_rows(
        registry.FLOOR_PAGE_ID, corpus=_corpus(rows), dispositions=dispositions
    ) == rows


def test_the_real_floor_and_the_real_authored_rows_do_not_overlap():
    """Every floored key must be a key with no descriptor, and vice versa."""
    authored = {row.id for row in search.page_rows(registry.FLOOR_PAGE_ID)}
    floored = set(search.floor_ids())
    assert authored and floored
    assert authored & floored == set()


def test_every_system_page_actually_has_rows():
    """A page of the System section with no settings on it is a bug, not a page."""
    for page_id in ("nightlight", "sound", "power", "terminal"):
        assert search.page_rows(page_id), f"{page_id} resolved to no rows at all"


# -- search text ------------------------------------------------------------


def test_search_text_includes_the_words_a_switcher_would_type():
    row = _row("a.b", "c", synonyms=["taskbar", "start menu"])
    text = search.row_search_text(row)
    assert "taskbar" in text and "start menu" in text


def test_search_text_includes_the_labels_of_a_pick_one_row():
    row = _row(
        "a.b",
        "c",
        kind=WidgetKind.CHOICE,
        choices=[Choice(value="'x'", label="Go to sleep")],
    )
    assert "go to sleep" in search.row_search_text(row)


# -- the index --------------------------------------------------------------


def _index() -> search.SearchIndex:
    rows = [
        _row("a.b", "dark", title="Dark mode", subtitle="Makes windows dark."),
        _row("a.b", "dock", title="Keep the icons on screen", synonyms=["taskbar"]),
    ]
    return search.SearchIndex.build(
        corpus=_corpus(rows),
        dispositions={"a.b:dark": "surfaced(colors)", "a.b:dock": "surfaced(addons)"},
        looks=(),
    )


def test_the_index_finds_a_setting_by_a_word_in_its_title():
    hits = _index().search("dark")
    assert hits and hits[0].descriptor_id == "a.b:dark"
    assert hits[0].page_id == "colors"


def test_the_index_finds_a_setting_by_a_word_the_user_would_use():
    """P7: "taskbar" has to find the dock, because that is what people call it."""
    hits = _index().search("taskbar")
    assert [hit.descriptor_id for hit in hits] == ["a.b:dock"]


def test_the_index_finds_pages_by_name():
    hits = [hit for hit in _index().search("night") if hit.kind == "page"]
    assert hits and hits[0].page_id == "nightlight"


def test_an_empty_query_answers_nothing_rather_than_everything():
    assert _index().search("") == []
    assert _index().search("   ") == []


def test_a_title_match_outranks_an_explanation_match():
    rows = [
        _row("a.b", "one", title="Something else", subtitle="This mentions sleep."),
        _row("a.b", "two", title="Sleep", subtitle="Unrelated."),
    ]
    index = search.SearchIndex.build(
        corpus=_corpus(rows),
        dispositions={"a.b:one": "surfaced(power)", "a.b:two": "surfaced(power)"},
        looks=(),
    )
    assert index.search("sleep")[0].descriptor_id == "a.b:two"


def test_the_index_survives_a_manifest_that_names_a_page_that_does_not_exist():
    """Losing search entirely over one bad line would be the worse answer."""
    index = search.SearchIndex.build(
        corpus=_corpus([_row("a.b", "c")]),
        dispositions={"a.b:c": "surfaced(nowhere)"},
        looks=(),
    )
    assert [hit.kind for hit in index.hits if hit.kind == "page"]


def test_the_real_index_covers_settings_pages_looks_and_add_ons():
    index = search.SearchIndex.build()
    kinds = {hit.kind for hit in index.hits}
    assert kinds == {"setting", "page", "look", "add-on"}
    assert len(index) > 400


def test_every_hit_names_a_page_that_exists():
    known = set(registry.page_ids())
    for hit in search.SearchIndex.build().hits:
        assert hit.page_id in known, f"{hit.title!r} points at page {hit.page_id!r}"


def test_a_hit_promises_a_row_only_when_a_page_really_registers_one():
    """Pins the ui/search.py:269 finding (dead deep-links to add-on settings).

    This test used to assert that EVERY ``kind="setting"`` hit carries a
    ``descriptor_id`` — which is the buggy contract itself: the 215 curated
    add-on rows were indexed that way, their controls are built only inside an
    add-on's own settings dialog, and that dialog is not open when a search
    result lands, so ``window.go_to`` had nothing to scroll to or flash. The
    assertion is inverted rather than loosened: a hit may name a row only when
    it is a row some page actually puts on screen, and no hit of any kind may
    name an add-on panel row.
    """
    corpus = load_corpus()
    panel_row_ids = {row.id for panel in corpus.panels for row in panel.rows}
    assert panel_row_ids, "the shipped corpus has curated add-on panels"

    registered = {
        descriptor_id
        for page_id in registry.page_ids()
        for descriptor_id in search.surfaced_ids(page_id)
    }
    promised = 0
    for hit in search.SearchIndex.build().hits:
        if hit.kind != "setting":
            assert hit.descriptor_id is None
            continue
        if hit.descriptor_id is None:
            continue
        promised += 1
        assert hit.descriptor_id not in panel_row_ids, hit.title
        assert hit.descriptor_id in registered, hit.title
    assert promised > 100, "the desktop's own settings are still deep-linkable"


@pytest.mark.parametrize(
    ("query", "expected_page"),
    [
        ("wallpaper", "wallpaper"),
        ("sleep", "power"),
        ("night light", "nightlight"),
        ("volume", "sound"),
    ],
)
def test_the_real_index_answers_the_questions_people_actually_ask(query, expected_page):
    hits = search.SearchIndex.build().search(query)
    assert any(hit.page_id == expected_page for hit in hits), f"{query!r} found nothing useful"


# -- markup safety ----------------------------------------------------------


def test_an_ampersand_is_escaped_before_it_reaches_a_widget():
    """Unescaped, "Mouse, Touchpad & Keyboard" renders as an empty heading."""
    pytest.importorskip("gi", reason="PyGObject is needed for the markup escaper")
    assert search.escape_markup("Mouse, Touchpad & Keyboard") == (
        "Mouse, Touchpad &amp; Keyboard"
    )
    assert search.escape_markup("") == ""


def test_the_shipped_corpus_contains_text_that_needs_escaping():
    """The guard against the escaping being untested because nothing needs it."""
    from gtheme.panels import loader

    titles = [domain.title for domain in loader.load_corpus().domains]
    assert any("&" in title for title in titles)
