"""Reading the descriptor corpus, including what happens when a file is wrong.

The corpus itself is authored by other agents; these tests are about the
reading. The one test that looks at the shipped files asserts the thing that
matters for the whole architecture: whatever is committed must parse, and every
row of it must name a setting that really exists.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gtheme.panels.loader import (
    Corpus,
    data_dir,
    load_corpus,
    load_domains,
    load_panels,
)

PANEL_TOML = """
id = "example"

[target]
uuids = ["example@example.com"]
schema_id = "org.gnome.shell.extensions.example"
category = "looks"
summary = "Makes the corners of windows round."

[[row]]
schema_id = "org.gnome.shell.extensions.example"
key = "corner-radius"
title = "Corner roundness"
subtitle = "How rounded the corners of every window are."
kind = "slider"
clamp_min = 0
clamp_max = 32
"""

DOMAIN_TOML = """
id = "colors"
title = "Colours & Style"

[[row]]
schema_id = "org.gnome.desktop.interface"
key = "color-scheme"
title = "Dark mode"
subtitle = "Use dark colours everywhere."
kind = "toggle"
"""


@pytest.fixture
def corpus_dir(tmp_path: Path) -> Path:
    (tmp_path / "panels").mkdir()
    (tmp_path / "domains").mkdir()
    (tmp_path / "panels" / "example.toml").write_text(PANEL_TOML, encoding="utf-8")
    (tmp_path / "domains" / "colors.toml").write_text(DOMAIN_TOML, encoding="utf-8")
    return tmp_path


def test_a_panel_file_becomes_a_panel(corpus_dir: Path):
    panels, problems = load_panels(corpus_dir / "panels")
    assert problems == []
    assert [panel.id for panel in panels] == ["example"]
    assert panels[0].descriptor_ids == ["org.gnome.shell.extensions.example:corner-radius"]


def test_a_domain_file_becomes_a_domain(corpus_dir: Path):
    domains, problems = load_domains(corpus_dir / "domains")
    assert problems == []
    assert [domain.id for domain in domains] == ["colors"]


def test_both_halves_load_together(corpus_dir: Path):
    corpus = load_corpus(corpus_dir)
    assert corpus.problems == []
    assert corpus.descriptor_ids() == [
        "org.gnome.shell.extensions.example:corner-radius",
        "org.gnome.desktop.interface:color-scheme",
    ]


def test_a_broken_file_is_named_and_the_rest_still_load(corpus_dir: Path):
    """One bad panel must not cost the other twenty-three."""
    (corpus_dir / "panels" / "broken.toml").write_text("id = = =", encoding="utf-8")
    panels, problems = load_panels(corpus_dir / "panels")
    assert [panel.id for panel in panels] == ["example"]
    assert len(problems) == 1
    assert "broken.toml" in problems[0]


def test_a_row_with_no_explanation_is_a_problem_not_a_row(corpus_dir: Path):
    (corpus_dir / "domains" / "silent.toml").write_text(
        """
        id = "silent"
        title = "Silent"

        [[row]]
        schema_id = "org.gnome.desktop.interface"
        key = "cursor-size"
        title = "Pointer size"
        kind = "slider"
        clamp_min = 16
        clamp_max = 96
        """,
        encoding="utf-8",
    )
    domains, problems = load_domains(corpus_dir / "domains")
    assert [domain.id for domain in domains] == ["colors"]
    assert "subtitle" in problems[0]


def test_either_spelling_of_the_row_table_works(corpus_dir: Path):
    """The plan writes ``[[row]]``; the model's field is ``rows``."""
    (corpus_dir / "domains" / "spelled.toml").write_text(
        DOMAIN_TOML.replace("[[row]]", "[[rows]]").replace('id = "colors"', 'id = "spelled"'),
        encoding="utf-8",
    )
    domains, problems = load_domains(corpus_dir / "domains")
    assert problems == []
    assert {domain.id for domain in domains} == {"colors", "spelled"}
    assert all(len(domain.rows) == 1 for domain in domains)


def test_using_both_spellings_at_once_is_a_problem(corpus_dir: Path):
    (corpus_dir / "domains" / "muddled.toml").write_text(
        DOMAIN_TOML + DOMAIN_TOML.split("\n", 3)[3].replace("[[row]]", "[[rows]]"),
        encoding="utf-8",
    )
    _domains, problems = load_domains(corpus_dir / "domains")
    assert any("muddled.toml" in problem for problem in problems)


def test_an_empty_corpus_is_empty_not_an_error(tmp_path: Path):
    assert load_panels(tmp_path) == ([], [])
    assert Corpus().rows == []


def test_the_data_directory_can_be_pointed_somewhere_else(corpus_dir: Path, monkeypatch):
    monkeypatch.setenv("GTHEME_DATA_DIR", str(corpus_dir))
    assert data_dir() == corpus_dir


def test_the_repository_s_own_data_directory_is_found(monkeypatch):
    monkeypatch.delenv("GTHEME_DATA_DIR", raising=False)
    found = data_dir()
    assert found is not None
    assert (found / "domains").is_dir()


# -- the committed corpus --------------------------------------------------


def test_whatever_is_committed_parses(monkeypatch):
    """Authored by other agents; unreadable at any point is a broken build."""
    monkeypatch.delenv("GTHEME_DATA_DIR", raising=False)
    assert load_corpus().problems == []


def test_every_committed_row_names_a_setting_that_exists(monkeypatch):
    """The rule that makes 'nothing was left out' checkable.

    Resolved against the committed fixture corpus of real add-on settings plus
    this machine's own system settings, so a descriptor naming a key that was
    renamed two versions ago fails here rather than greying out for a user.
    """
    pytest.importorskip("gi", reason="PyGObject is needed for schema lookups")
    from gtheme.panels.schema_probe import Presence, SchemaProbe

    monkeypatch.delenv("GTHEME_DATA_DIR", raising=False)
    corpus = load_corpus()
    if not corpus.rows:
        pytest.skip("the descriptor corpus has not been authored yet")

    fixtures = Path(__file__).resolve().parents[1] / "fixtures" / "schemas"
    probe = SchemaProbe([fixtures])
    unresolved = [
        f"{row.id}: {probe.availability(row).presence}"
        for row in corpus.rows
        if probe.availability(row).presence
        in (Presence.MISSING_ADDON, Presence.MISSING_SETTING)
    ]
    assert unresolved == []
