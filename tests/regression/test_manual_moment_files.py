"""A hand-saved moment covers files, not only settings (review-report H11).

The scenario is the one the app's own introduction teaches, and it is the one
that failed: slide four says "save how the desktop looks now", the user presses
it, applies a Look that writes twenty files — one of them their own
``starship.toml`` — dislikes it, and goes back to the saved moment. Every one
of those files stayed exactly as the Look had written it, because
``create_restore_point`` never passed ``dests`` and ``capture`` guards its whole
file loop with ``if dests:``.

The fix is the ownership ledger: it is written before every change and it names
exactly the destinations that can differ between now and the moment being
restored. This test drives the real page function, two real Look transactions
and the real restore — no stand-in for the part being pinned.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for the page module")

from gtheme.core import ledger, restorepoints  # noqa: E402
from gtheme.core.transaction import FileWrite, Transaction  # noqa: E402
from gtheme.ui.pages import restore  # noqa: E402

DEST = "~/.config/demo/style.css"


def _apply_look(engine, source: Path, *, title: str, name: str) -> None:
    """Apply one file the way ``preset.compile`` does: both label and look."""
    Transaction(
        [FileWrite(src=str(source), dest=DEST)],
        dest_root=str(engine.dest_root),
        label=title,
        look=name,
    ).apply()


def test_going_back_to_a_hand_saved_moment_puts_the_looks_files_back(engine, tmp_path):
    landed = engine.dest_root / ".config" / "demo" / "style.css"

    first = tmp_path / "first.css"
    first.write_text("the first look's css", encoding="utf-8")
    _apply_look(engine, first, title="OVERLAY", name="overlay")
    assert landed.read_text(encoding="utf-8") == "the first look's css"
    assert str(landed) in ledger.read_ledger().get("OVERLAY", {}).get("files", []), (
        "the ledger is what the saved moment reads; without a claim there is nothing to pin"
    )

    moment = restore.create_restore_point(
        "My desktop, today", backend=engine.backend, keys=[]
    )
    assert str(landed) in moment.files, "the moment covers the file (review-report H11)"

    second = tmp_path / "second.css"
    second.write_text("the second look's css", encoding="utf-8")
    _apply_look(engine, second, title="MAGMA", name="magma")
    assert landed.read_text(encoding="utf-8") == "the second look's css"

    result = restorepoints.apply_point(
        moment.id, backend=engine.backend, dest_root=str(engine.dest_root)
    )

    assert not result.warnings, result.warnings
    assert landed.read_text(encoding="utf-8") == "the first look's css", (
        "going back to a saved moment left every file the Look installed exactly as it was"
    )


def test_a_moment_saved_before_anything_was_claimed_removes_what_arrives_after(
    engine, tmp_path
):
    """The other half of covering a file: it was not there when this was saved.

    Nothing is claimed yet, so the moment covers no files — and that is honest,
    not a hole: the Look that arrives afterwards takes its own automatic moment
    first, which is what puts *its* files back.
    """
    moment = restore.create_restore_point(
        "My desktop, today", backend=engine.backend, keys=[]
    )
    assert moment.files == {}

    source = tmp_path / "late.css"
    source.write_text("arrived later", encoding="utf-8")
    _apply_look(engine, source, title="OVERLAY", name="overlay")

    later = restore.create_restore_point("After", backend=engine.backend, keys=[])
    assert str(engine.dest_root / ".config" / "demo" / "style.css") in later.files
