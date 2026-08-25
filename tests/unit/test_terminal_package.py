"""The set of adapters as a whole: does every one of them honour the contract?"""

from __future__ import annotations

from pathlib import Path

import pytest

from gtheme.terminal import adapters, apply_all
from gtheme.terminal.model import Palette, ReloadSemantics, TerminalAdapter
from gtheme.terminal.ptyxis import PtyxisAdapter

LOOK = Palette(
    name="Nightbloom",
    background="#0A100C",
    foreground="#E8E4D6",
    cursor="#F5C04A",
    ansi=tuple(f"#{i:02x}{i:02x}{i:02x}" for i in range(16)),
    opacity=0.82,
)


def test_every_adapter_satisfies_the_frozen_protocol():
    for adapter in adapters():
        assert isinstance(adapter, TerminalAdapter), adapter
        assert isinstance(adapter.reload_semantics, ReloadSemantics)
        assert adapter.id and adapter.name


def test_adapter_ids_are_unique():
    ids = [adapter.id for adapter in adapters()]
    assert len(ids) == len(set(ids))


def test_no_name_shown_to_a_user_contains_jargon():
    """The Terminal page shows these names; they have to be words, not ids."""
    from gtheme.ui.jargon import find_banned

    for adapter in adapters():
        assert find_banned(adapter.name) == []


def test_ptyxis_is_left_out_when_there_is_no_settings_seam():
    """An adapter that invents its own backend can reach the real store."""
    assert not any(isinstance(a, PtyxisAdapter) for a in adapters())
    from gtheme.core.settings_backend import MemoryBackend

    assert any(isinstance(a, PtyxisAdapter) for a in adapters(MemoryBackend()))


@pytest.mark.mutating
def test_every_adapter_reports_a_reload_sentence(tmp_dest_root: Path):
    for adapter in adapters():
        state = adapter.detect()
        assert state.notes, adapter.id


@pytest.mark.mutating
def test_nothing_an_adapter_says_out_loud_is_jargon(tmp_dest_root: Path):
    """These notes go straight onto the page, so they get the same lint."""
    from gtheme.ui.jargon import find_banned

    for adapter in adapters():
        for note in adapter.detect().notes:
            assert find_banned(note) == [], f"{adapter.id}: {note}"
    for semantics in ReloadSemantics:
        assert find_banned(semantics.sentence()) == []


@pytest.mark.mutating
def test_one_refusal_does_not_stop_the_others(tmp_dest_root: Path, tmp_path: Path):
    """The case that actually happens: ghostty is managed by another tool."""
    rice = tmp_path / "nightbloom" / "ghostty"
    rice.mkdir(parents=True)
    (rice / "config").write_text("theme = nightbloom\n", encoding="utf-8")
    (tmp_dest_root / ".config").mkdir(parents=True)
    (tmp_dest_root / ".config" / "ghostty").symlink_to(rice)

    from gtheme.terminal import AlacrittyAdapter, GhosttyAdapter, StarshipAdapter

    outcome = apply_all(LOOK, [GhosttyAdapter(), AlacrittyAdapter(), StarshipAdapter()])
    assert outcome["ghostty"] is not None
    assert "managed by another tool" in outcome["ghostty"]
    assert outcome["alacritty"] is None
    assert outcome["starship"] is None
    assert (rice / "config").read_text() == "theme = nightbloom\n"
