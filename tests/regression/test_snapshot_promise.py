"""The promise made before the first byte moves, and the two layers of a plan.

Two findings, one theme: the app said something to the person and then behaved
as if it had not.

* **X3** (persona-report §2.5) — the apply dialog says "Before anything
  changes, gtheme saves how your desktop looks right now. You can put it back
  with one click." ``_capture_restore_point`` then caught ``OSError``, returned
  None and let the apply run anyway. The promise was already made, the person
  had already agreed on the strength of it, and the only sign that it had been
  withdrawn was a missing button on an eight-second toast. A moment that was
  saved only *in part* was worse still: the point records what it could not
  cover in its own warnings, and the engine read them and dropped them.
* **U4** (persona-report §2.4) — ``DiffEntry`` has carried ``before`` and
  ``after`` since the first contract and nothing ever rendered them, because
  the summary's "Never a key name" was read as "the app never shows the real
  thing anywhere". These pin the amended contract: the novice line stays a
  novice line, and the machine's own values stay available for the second
  layer behind "Show exactly what changes".

Every test here runs against the ``engine`` fixture, so settings go to an
in-memory store, files go under a temporary root and moments go to a temporary
state directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gtheme.core import restorepoints
from gtheme.core.transaction import (
    DiffEntry,
    FileWrite,
    SettingWrite,
    Transaction,
    TransactionError,
)

ICONS = "gsettings:org.gnome.desktop.interface icon-theme"


def _look(tmp_path: Path, engine, *, body: str = "the look's file") -> Transaction:
    """A Look that writes one file and one setting, the ordinary shape."""
    source = tmp_path / "look" / "demo.conf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(body, encoding="utf-8")
    return Transaction(
        [
            FileWrite(src=str(source), dest="~/.config/demo/demo.conf"),
            SettingWrite(key=ICONS, value="'Papirus-Dark'", component="icons"),
        ],
        dest_root=str(engine.dest_root),
        label="DEMO",
        look="demo",
    )


# -- X3: the moment is saved, or nothing happens ---------------------------


def test_a_moment_that_cannot_be_saved_stops_the_apply(engine, tmp_path, monkeypatch):
    """The dialog promised the way back. Without it, the change does not start.

    Before the fix this returned None and carried straight on: the file was
    written, the setting was written, and the person had been told they could
    put it back with one click over a moment that does not exist.
    """

    def full_disk(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(restorepoints, "capture_from_diff", full_disk)

    with pytest.raises(TransactionError) as caught:
        _look(tmp_path, engine).apply()

    assert caught.value.rolled_back is True, "nothing had been written yet to unwind"
    assert "No space left on device" in str(caught.value)
    assert "nothing was changed" in str(caught.value)

    written = engine.dest_root / ".config" / "demo" / "demo.conf"
    assert not written.exists(), "the apply must not have started"
    assert engine.backend.get(ICONS) == "'Adwaita'", "the setting is untouched"


def test_a_moment_saved_only_in_part_says_what_it_missed(engine, tmp_path, monkeypatch):
    """``point.warnings`` reaches the caller instead of being dropped.

    A restore point can be taken and still be incomplete — one file it could
    not read, one setting the desktop would not report. The point says so in
    its own words; the engine used to keep only the id.
    """
    real = restorepoints.capture_from_diff

    def holey(*args, **kwargs):
        point = real(*args, **kwargs)
        point.warnings.append("one picture could not be saved")
        return point

    monkeypatch.setattr(restorepoints, "capture_from_diff", holey)

    narrated: list[str] = []
    result = _look(tmp_path, engine).apply(lambda _stage, text: narrated.append(text))

    assert result.restore_point, "the moment was still taken"
    assert result.restore_warnings == ["one picture could not be saved"]
    assert "one picture could not be saved" in narrated


def test_an_ordinary_apply_carries_no_snapshot_warnings(engine, tmp_path):
    """The honest empty case: a moment saved whole says nothing extra."""
    result = _look(tmp_path, engine).apply()
    assert result.restore_point
    assert result.restore_warnings == []


# -- U4: the contract has two layers, and both are written down ------------


def test_the_summary_is_still_the_novice_line_and_the_values_are_still_there():
    """The amendment, in one assertion each way.

    ``summary`` never becomes a key name — that half of the frozen contract is
    unchanged and is what ``Diff.to_novice_lines`` renders. ``before`` and
    ``after`` carry the machine's own values, which is what makes a truthful
    second layer possible at all; a plan that only carried the phrase could
    never show anyone what it was about to do.
    """
    entry = DiffEntry(
        op=SettingWrite(key=ICONS, value="'Papirus-Dark'", component="icons"),
        component="icons",
        summary="Icons",
        before="'Adwaita'",
        after="'Papirus-Dark'",
    )
    assert "icon-theme" not in entry.summary
    assert entry.summary == "Icons"
    assert (entry.before, entry.after) == ("'Adwaita'", "'Papirus-Dark'")
    assert entry.op.key == ICONS, "the real key stays reachable for the detail layer"


def test_the_amendment_is_recorded_where_the_contract_is():
    """A contract changed in code and not in its own words is a trap.

    "Never a key name" was true, load-bearing, and read as a wider ban than it
    ever was. The docstring now says which layer it governs and why the second
    one exists, so the next person to read it is not left deciding for
    themselves whether rendering ``before``/``after`` breaks the promise.
    """
    doc = DiffEntry.__doc__ or ""
    assert "Never a key name" in doc, "the novice line is still the novice line"
    assert "Show exactly what changes" in doc, "and the second layer is named"
    assert "two layers" in doc
