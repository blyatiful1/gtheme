"""What a saved Look carries, and what a saved moment carries (review-report H13).

Two places in the app write down how the desktop is set right now, and they
were two loops over the same data written months apart. Run against the shipped
corpus they disagreed by 174 keys — every ``compound`` key among them — and the
first of those is
``gsettings:org.gnome.desktop.interface color-scheme``, which is the light-or-dark
switch gtheme's own Colours & Style page writes.

The user-visible failure is quiet and total: somebody on a dark desktop saves it
as a Look and applies it on a light one. The Look brings the wallpaper, the
accent, the icons, the fonts and the dark *app style* — and not the switch — so
their apps go dark while the rest of the desktop stays light, and nothing
re-derives it at apply time. The invariant was asserted for restore points
(``test_pages_restore_logic.py``: "or undo cannot put back light-or-dark"); the
Looks side had one test, over a two-row synthetic corpus, that could not see the
gap.

These run against the in-memory settings store, a temporary Looks folder and a
temporary state folder. Nothing here reads or writes the desktop running the
suite.
"""

from __future__ import annotations

import pytest

from gtheme.core.settings_backend import MemoryBackend
from gtheme.panels import keyset
from gtheme.panels.loader import captured_keys, load_corpus
from gtheme.preset.capture import capture_share

COLOUR_SCHEME = "gsettings:org.gnome.desktop.interface color-scheme"
#: A ``floor`` key: the More Settings page can change it, and a Look given to
#: somebody else has no business carrying it.
A_FLOOR_KEY = "gsettings:org.gnome.desktop.a11y.applications screen-reader-enabled"


# ── the two lists are one list ────────────────────────────────────────────


def test_a_look_saved_from_a_dark_desktop_carries_light_or_dark(tmp_path):
    """The whole finding, end to end, through the real capture.

    Fails on the old code: ``capture_keys`` was built from the descriptor
    corpus alone, ``color-scheme`` is dispositioned ``compound`` and has no
    corpus row, so the key was never read and never written into the Look.
    """
    from gtheme.ui.pages import looks

    backend = MemoryBackend()
    backend.set(COLOUR_SCHEME, "'prefer-dark'")

    result = capture_share(
        looks.capture_keys(),
        backend,
        out_dir=tmp_path / "mine",
        name="mine",
        title="Mine",
    )

    carried = {entry.key: entry.value for entry in result.preset.settings}
    assert carried.get(COLOUR_SCHEME) == "'prefer-dark'", (
        "a Look saved on a dark desktop that does not carry the light-or-dark "
        "switch applies as a dark app style on a light desktop"
    )


def test_the_look_list_is_the_moment_list_minus_the_floor():
    """One derivation, one named difference. Not two loops that drifted."""
    moment = keyset.moment_keys()
    look = keyset.look_keys()

    assert set(look) < set(moment), "a Look may not carry more than a moment records"
    missing = set(moment) - set(look)
    assert missing == keyset.floor_keys(), (
        "the only thing a shareable Look leaves out is the floor tier, "
        "deliberately — anything else is drift"
    )
    assert A_FLOOR_KEY in missing
    assert COLOUR_SCHEME in look


def test_the_looks_page_and_the_undo_page_ask_the_same_question():
    """Both pages consume the one helper rather than each rolling its own."""
    from gtheme.ui.pages import looks, restore

    assert restore.descriptor_keys() == keyset.moment_keys()
    assert looks.capture_keys() == keyset.look_keys()


def test_every_compound_key_reaches_both_lists():
    """``compound`` is the tier that has no corpus row, which is why it was lost."""
    compound = {
        f"gsettings:{descriptor_id.replace(':', ' ', 1)}"
        for descriptor_id, disposition in _dispositions().items()
        if str(disposition).partition("(")[0].strip() == "compound"
    }
    assert compound, "the shipped manifest must have compound keys or this is vacuous"
    assert compound <= set(keyset.look_keys())
    assert compound <= set(keyset.moment_keys())


def _dispositions() -> dict[str, str]:
    from gtheme.panels.loader import load_dispositions

    return load_dispositions()


# ── the guards that keep the derivation honest ────────────────────────────


def test_the_floor_set_is_really_a_subset_of_what_the_manifest_yields():
    """A silent filter is a filter that stops filtering and says nothing.

    :func:`keyset.floor_keys` subtracts from :func:`captured_keys`'s answer, and
    the two build their key strings separately. If either spelling ever moved,
    the subtraction would quietly remove nothing and a shareable Look would
    start carrying somebody's accessibility settings again — with every test
    above this one still green.
    """
    floor = keyset.floor_keys()
    assert floor, "the shipped manifest must have floor keys or this is vacuous"
    assert floor <= set(captured_keys())


def test_a_manifest_that_is_not_there_leaves_only_the_corpus(tmp_path):
    """The seam the page tests use: an empty folder means an empty manifest."""
    only_corpus = keyset.look_keys(directory=tmp_path)
    assert only_corpus == keyset.corpus_keys()
    assert COLOUR_SCHEME not in only_corpus


@pytest.mark.gtk
def test_the_key_a_row_makes_is_the_key_the_row_library_makes():
    """The one duplication in this design, held together by measurement.

    ``keyset`` cannot call ``ui.widgets.rows.key_for``: that module imports GTK,
    and a saved moment has to be derivable from a text console where importing
    GTK may itself fail. So the grammar is rebuilt through
    ``SettingsKey.as_text`` — and checked here against every row gtheme ships,
    including the relocatable and settings-file forms, rather than against three
    hand-picked examples.
    """
    pytest.importorskip("gi", reason="the row library needs PyGObject")
    from gtheme.panels.descriptor import Row, WidgetKind
    from gtheme.ui.widgets.rows import key_for

    rows = [row for row in load_corpus().rows if row.schema_id and row.key]
    assert len(rows) > 100, "the shipped corpus must have rows or this is vacuous"
    # Every shipped row is the plain form today, so the two rarer spellings —
    # the relocatable schema and the add-on's own settings file — are made here
    # rather than trusted to turn up.
    rows += [
        Row(
            schema_id="org.gnome.shell.extensions.burn-my-windows-profile",
            path="/org/gnome/shell/extensions/burn-my-windows/profiles/1/",
            key="name",
            title="Which effect",
            subtitle="The effect this profile uses.",
            kind=WidgetKind.TEXT,
        ),
        Row(
            keyfile="/home/someone/.config/burn-my-windows/profiles/123.conf",
            schema_id="org.gnome.shell.extensions.burn-my-windows-profile",
            path="/burn-my-windows/profile/",
            key="fire-enable-effect",
            title="Fire",
            subtitle="Windows burn when they close.",
            kind=WidgetKind.TOGGLE,
        ),
    ]
    shapes = {key_for(row).partition(":")[0] for row in rows}
    assert {"gsettings", "gsettings-path", "keyfile"} <= shapes
    assert [keyset.row_key(row) for row in rows] == [key_for(row) for row in rows]
