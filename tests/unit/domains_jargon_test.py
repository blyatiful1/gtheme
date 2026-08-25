"""Plain-language lint over the whole core-GNOME descriptor corpus.

The reader we are writing for has never used Linux (DESIGN.md A7, competitor-ux
P3/P4). Every string in ``data/domains/*.toml`` that a person can actually read
goes through ``gtheme.ui.jargon``: titles, subtitles, the label and subtitle of
every option, the sentence shown when a second setting has to be changed first,
and every warning.

**Synonyms are deliberately exempt.** They exist so that somebody typing
"taskbar", "hinting" or "gtk theme" into the search box finds the right row.
Linting them would forbid the corpus from knowing the words the user knows,
which is the opposite of the goal.
"""

from __future__ import annotations

import re
import tomllib

from domains_corpus_test import domain_files, load_domains

from gtheme.ui import jargon


def readable_strings() -> list[tuple[str, str]]:
    """Every ``(where, text)`` pair a person can read, across the corpus."""
    items: list[tuple[str, str]] = []
    for domain in load_domains():
        items.append((f"{domain.id} (title)", domain.title))
        for row in domain.rows:
            items.append((f"{row.id} (title)", row.title))
            items.append((f"{row.id} (subtitle)", row.subtitle))
            if row.warn:
                items.append((f"{row.id} (warning)", row.warn))
            for choice in row.choices:
                items.append((f"{row.id} → {choice.value} (label)", choice.label))
                if choice.subtitle:
                    items.append((f"{row.id} → {choice.value} (subtitle)", choice.subtitle))
            for req in row.requires_first:
                items.append((f"{row.id} (also changes {req.key})", req.explain))
    return items


def test_the_corpus_speaks_plain_english():
    problems = jargon.check_all(readable_strings())
    assert problems == [], "\n".join(problems)


def test_the_lint_is_actually_looking_at_something():
    """A lint over an empty list passes vacuously; this is the guard against that."""
    items = readable_strings()
    assert len(items) > 800, f"only {len(items)} readable strings were collected"


def test_the_lint_would_catch_the_words_that_matter_here():
    """The four words this corpus is most likely to leak, each proven to fail."""
    for text in (
        "Sets the gtk-theme schema key",
        "Blurs the shell panel",
        "Controls font hinting",
        "Enables the extension by its uuid",
    ):
        assert jargon.check(text), f"the lint let {text!r} through"


#: Whole words that only ever come from a setting's internal name. Matching on
#: whole words, not fragments, is deliberate: "favourites" contains "uri" and
#: "Double-click speed" contains "double-click", and neither is a leak. What is a
#: leak is a label that says "picture-uri" or carries an underscore.
MACHINE_WORDS = frozenset({"uri", "uris", "exec", "xkb", "dconf", "gschema", "gsettings", "org.gnome"})

_WORDS = re.compile(r"[a-z0-9.\-_]+")


def _machine_words(text: str) -> list[str]:
    return [word for word in _WORDS.findall(text.lower()) if word in MACHINE_WORDS or "_" in word]


def test_no_row_leaks_a_setting_name_into_what_the_user_reads():
    for domain in load_domains():
        for row in domain.rows:
            assert not _machine_words(row.title), f"{row.id}: the title is written in machine words"
            assert not _machine_words(row.subtitle), (
                f"{row.id}: the subtitle is written in machine words"
            )
            assert row.schema_id not in row.subtitle, f"{row.id}: the subtitle names the settings group"


def test_warnings_describe_a_consequence_not_a_mechanism():
    """competitor-ux P5: say "your top bar may disappear", never "the call failed"."""
    for domain in load_domains():
        for row in domain.rows:
            if not row.warn:
                continue
            assert row.warn.strip().endswith("."), f"{row.id}: the warning is not a sentence"
            assert len(row.warn) > 40, f"{row.id}: the warning does not say what will happen"


def test_the_corpus_has_no_stray_smart_quotes_or_tabs():
    """These files are hand-edited; a stray tab in a TOML string is invisible."""
    for path in domain_files():
        text = path.read_text(encoding="utf-8")
        assert "\t" not in text, f"{path.name}: contains a tab"
        parsed = tomllib.loads(text)
        assert parsed["title"], f"{path.name}: no title"
