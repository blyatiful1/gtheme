"""Every sentence these five pages write themselves, through the jargon lint.

DESIGN.md A7: the reader has never used Linux. The corpus has its own lint;
this is the same lint over the copy the *pages* choose — group headings, the
explanations under them, the one-shot banners, the buttons.

Two things are deliberately out of scope, and both for the same reason as the
corpus lint's exemption for synonyms:

* **Third-party product names.** "Blur My Shell" is what its author calls it.
  Renaming somebody's add-on would make it unfindable by the name printed on
  its own page.
* **The system's own descriptions.** The floor page shows them on purpose,
  passed through the translator and labelled as coming from the desktop rather
  than from gtheme. Requiring them to pass would mean hiding two thirds of the
  desktop's settings, which is the promise the floor exists to keep.
"""

from __future__ import annotations

import pytest

from gtheme.ui import jargon
from gtheme.ui import search as search_module
from gtheme.ui.pages import more, nightlight, power, sound, terminal

#: Every module with a ``COPY`` table this lint is responsible for.
MODULES = (nightlight, sound, power, terminal, more, search_module)


def _copy_items() -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for module in MODULES:
        name = module.__name__.rsplit(".", 1)[-1]
        for key, text in getattr(module, "COPY", {}).items():
            items.append((f"{name}.COPY[{key!r}]", text))
    return items


def test_the_lint_is_actually_looking_at_something():
    """A lint over an empty list passes vacuously. This is the guard."""
    items = _copy_items()
    assert len(items) > 40, f"only {len(items)} sentences were collected"


def test_every_sentence_these_pages_write_is_plain_english():
    problems = jargon.check_all(_copy_items())
    assert problems == [], "\n".join(problems)


def test_the_standing_headings_are_plain_english():
    problems = jargon.check_all(
        [
            ("ADVANCED_TITLE", search_module.ADVANCED_TITLE),
            ("ADVANCED_SUBTITLE", search_module.ADVANCED_SUBTITLE),
            ("BANNER_DISMISS", search_module.BANNER_DISMISS),
            *[(f"KIND_LABELS[{k}]", v) for k, v in search_module.KIND_LABELS.items()],
        ]
    )
    assert problems == [], "\n".join(problems)


def test_the_lint_would_catch_what_these_pages_are_likely_to_leak():
    """The four words a page about terminals and settings nearly writes."""
    for text in (
        "Edit the ghostty config file",
        "This writes a dconf key",
        "Reload the shell to see this",
        "The symlink points elsewhere",
    ):
        assert jargon.check(text), f"the lint let {text!r} through"


#: Copy slots that hold prose rather than a label. A heading is not a sentence
#: and a button is not a sentence; an explanation is, and an explanation that
#: trails off reads as a bug in the app.
SENTENCE_SUFFIXES = ("description", "body", "banner", "warning", "none", "text")


@pytest.mark.parametrize("module", MODULES)
def test_no_explanation_is_a_fragment(module):
    for key, text in getattr(module, "COPY", {}).items():
        if not key.endswith(SENTENCE_SUFFIXES):
            continue
        stripped = text.strip()
        assert stripped.endswith((".", "?")), f"{module.__name__}.COPY[{key!r}]"
        assert len(stripped.split()) >= 5, f"{module.__name__}.COPY[{key!r}] explains nothing"


def test_every_page_explains_its_groups():
    """competitor-ux P4: no group of controls ships without a word about it."""
    for module, expected in (
        (nightlight, ("switch-description", "schedule-description")),
        (sound, ("sets-description", "when-description", "alerts-description")),
        (power, ("screen-description", "sleep-description", "lock-description")),
        (terminal, ("app-description", "colours-none")),
        (more, ("floor-description",)),
    ):
        for key in expected:
            assert len(module.COPY[key]) > 40, f"{module.__name__}.COPY[{key!r}] is a stub"


def test_a_warning_says_what_will_happen_rather_than_what_failed():
    """competitor-ux P5: consequences, never mechanisms."""
    assert "ask for your password" in power.COPY["lock-warning"]
    assert len(power.COPY["lock-warning"]) > 40
