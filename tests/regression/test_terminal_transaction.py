"""The Terminal page changes things through the engine (review-report H8/H12).

The terminal adapters were the second of two subsystems living outside the
transaction ``docs/architecture.md`` calls "the only path by which anything
changes" — and the worse of the two, because these are not gtheme's files.
``apply_all`` called each adapter's ``apply()``, which regex-edited the user's
own ``alacritty.toml``, rewrote their ``starship.toml``, overwrote a dozen fish
colours and replaced the Ptyxis profile's palette. Nothing was recorded: not
the pristine copy ``gtheme rescue`` restores, not the ownership ledger, not a
saved moment, not even the process lock, so a card on this page could race a
Look being applied on the worker thread.

Every test here drives the real :func:`gtheme.terminal.apply_all` against a
real :class:`~gtheme.core.transaction.Transaction`, a real
:class:`~gtheme.core.baseline.Baseline` and the real restore machinery. Each
one fails against the old shape — most of them fail at ``adapter.apply`` not
existing, and the four that pin behaviour rather than shape (the recording, the
ledger claim, the undo, the all-or-nothing) fail on their assertions if the
writing is ever moved back inside the adapters.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gtheme.core import ledger, restorepoints
from gtheme.core.baseline import Baseline
from gtheme.core.ledger import MANUAL_OWNER
from gtheme.terminal import apply_all
from gtheme.terminal.alacritty import AlacrittyAdapter
from gtheme.terminal.model import Palette, ReloadSemantics, TerminalState, TerminalWrites
from gtheme.terminal.prompt import FishAdapter, StarshipAdapter

ANSI = tuple(f"#{i:02x}{i:02x}{i:02x}" for i in range(16))
LOOK = Palette(
    name="Nightbloom",
    background="#0A100C",
    foreground="#E8E4D6",
    cursor="#F5C04A",
    ansi=ANSI,
    opacity=0.82,
)

THEIRS = """# my own config, hand written
[window]
opacity = 0.5
padding = { x = 4, y = 4 }
"""


def _alacritty(engine) -> tuple[AlacrittyAdapter, Path]:
    """An Alacritty the user has already configured by hand."""
    config = engine.dest_root / ".config" / "alacritty"
    config.mkdir(parents=True)
    (config / "alacritty.toml").write_text(THEIRS, encoding="utf-8")
    return AlacrittyAdapter(), config / "alacritty.toml"


def _run(engine, adapters):
    return apply_all(
        LOOK, adapters, backend=engine.backend, dest_root=str(engine.dest_root)
    )


# -- what the engine gives it ----------------------------------------------


def test_what_was_there_is_recorded_before_it_is_overwritten(engine):
    """The pristine copy ``gtheme rescue`` puts back. There was none at all."""
    adapter, config = _alacritty(engine)

    report = _run(engine, [adapter])

    assert report.problems == {"alacritty": None}
    assert config.read_text(encoding="utf-8") != THEIRS, "the look was applied"

    recorded = Baseline(backend=engine.backend).load()
    entry = recorded.files.get(str(config))
    assert entry is not None, "the user's own config was overwritten with no copy of it"
    saved = recorded.files_dir / entry["backup"]
    assert saved.read_text(encoding="utf-8") == THEIRS


def test_the_destinations_are_claimed_as_the_users_own_doing(engine):
    """MANUAL_OWNER, so a Look applied later never quietly reverts them."""
    adapter, config = _alacritty(engine)

    _run(engine, [adapter])

    owned = ledger.read_ledger().get(MANUAL_OWNER, {})
    assert str(config) in owned.get("files", [])


def test_the_change_can_be_undone(engine):
    """A saved moment is taken first, and going back to it really goes back."""
    adapter, config = _alacritty(engine)

    report = _run(engine, [adapter])
    assert report.restore_point, "no saved moment was taken"

    result = restorepoints.apply_point(
        report.restore_point, backend=engine.backend, dest_root=str(engine.dest_root)
    )

    assert not result.warnings, result.warnings
    assert config.read_text(encoding="utf-8") == THEIRS


def test_one_write_failing_leaves_every_program_as_it_was(engine):
    """All or nothing, and every card says so — never a silent absence of Done."""
    adapter, config = _alacritty(engine)
    # A directory where starship's file goes: the write cannot happen, and it
    # is discovered after alacritty's two files have already been written.
    (engine.dest_root / ".config" / "starship.toml").mkdir(parents=True, exist_ok=True)

    report = _run(engine, [adapter, StarshipAdapter()])

    assert report.problems["starship"] is not None
    assert report.problems["alacritty"] is not None, (
        "the batch did not happen, so the program that was in it must not read as changed"
    )
    assert config.read_text(encoding="utf-8") == THEIRS, "rolled back to the user's own config"
    assert report.restore_point is None


# -- one program refusing, and one misbehaving (H12) -----------------------


class _Misbehaving:
    """An adapter that raises something nobody predicted."""

    id = "misbehaving"
    name = "Misbehaving"
    reload_semantics = ReloadSemantics.RESTART

    def detect(self) -> TerminalState:
        return TerminalState(installed=True)

    def current(self) -> Palette | None:
        return None

    def plan(self, _palette: Palette) -> TerminalWrites:
        raise RuntimeError("bytes must be in range(0, 256)")


def test_an_unpredicted_failure_stops_neither_the_others_nor_the_report(engine):
    """``apply_all`` used to catch three exception types and let the rest fly.

    ``PtyxisAdapter`` raised ``BackendError`` and ``FishAdapter`` raised
    ``RuntimeError``, neither of which was caught: the click ended in a
    traceback nobody saw, with the remaining programs unstyled.
    """
    adapter, config = _alacritty(engine)

    report = _run(engine, [_Misbehaving(), adapter])

    assert report.problems["misbehaving"] is not None
    assert report.problems["alacritty"] is None
    assert config.read_text(encoding="utf-8") != THEIRS


def test_an_unpredicted_failure_is_not_shown_as_machine_wreckage(engine):
    """The person gets a sentence; the traceback goes to the log."""
    report = _run(engine, [_Misbehaving()])

    said = report.problems["misbehaving"]
    assert said is not None
    assert "range(0, 256)" not in said
    assert said.endswith(".")


# -- the one whose store is not a file (fish) ------------------------------


def test_fishs_own_variables_file_is_recorded_before_fish_rewrites_it(engine):
    """fish's colours are set by running fish, so the file is saved first.

    ``FishAdapter.colors()`` could always have captured them and ``apply`` never
    called it (review-report H8). Recording the file fish keeps them in is the
    same guarantee, made by the machinery that already knows how to put a file
    back.
    """
    variables = engine.dest_root / ".config" / "fish" / "fish_variables"
    variables.parent.mkdir(parents=True)
    variables.write_text("SETUVAR fish_color_command:blue\n", encoding="utf-8")

    ran: list[list[str]] = []
    adapter = FishAdapter(lambda argv: ran.append(list(argv)) or "")

    report = _run(engine, [adapter])

    assert report.problems == {"fish": None}
    assert ran and ran[0][:2] == ["fish", "-c"]
    assert "fish_color_command" in ran[0][2]

    recorded = Baseline(backend=engine.backend).load()
    entry = recorded.files.get(str(variables))
    assert entry is not None, "fish was asked to overwrite its colours with no copy of them"
    saved = recorded.files_dir / entry["backup"]
    assert "fish_color_command:blue" in saved.read_text(encoding="utf-8")


def test_fish_is_not_run_when_the_batch_it_was_part_of_failed(engine):
    """It runs after the transaction lands, so a failed batch never reaches it."""
    (engine.dest_root / ".config" / "starship.toml").mkdir(parents=True, exist_ok=True)
    ran: list[list[str]] = []

    report = _run(engine, [FishAdapter(lambda argv: ran.append(list(argv)) or ""), StarshipAdapter()])

    assert ran == []
    assert report.problems["fish"] is not None


# -- the settings-driven half ----------------------------------------------

PTYXIS_SCHEMAS = """<?xml version="1.0" encoding="UTF-8"?>
<schemalist>
  <schema id="org.gnome.Ptyxis" path="/org/gnome/Ptyxis/">
    <key name="default-profile-uuid" type="s"><default>'2b9c'</default></key>
  </schema>
  <schema id="org.gnome.Ptyxis.Profile">
    <key name="palette" type="s"><default>'gnome'</default></key>
    <key name="opacity" type="d"><default>1.0</default></key>
  </schema>
</schemalist>
"""


@pytest.mark.mutating
def test_a_terminals_settings_are_recorded_and_claimed_too(
    engine, schema_source_factory, monkeypatch
):
    """Ptyxis wrote two settings straight through the backend, unrecorded."""
    from gtheme.core.settings_backend import MemoryBackend
    from gtheme.terminal.ptyxis import PtyxisAdapter, profile_key

    backend = MemoryBackend(schema_source=schema_source_factory(PTYXIS_SCHEMAS))
    key = profile_key("2b9c", "palette")
    backend.set(key, "'catppuccin'")

    report = apply_all(
        LOOK,
        [PtyxisAdapter(backend)],
        backend=backend,
        dest_root=str(engine.dest_root),
    )

    assert report.problems == {"ptyxis": None}
    assert backend.get(key) == "'Nightbloom'"

    recorded = Baseline(backend=backend).load()
    assert recorded.settings.get(key, {}).get("saved") == "'catppuccin'"
    assert key in ledger.read_ledger().get(MANUAL_OWNER, {}).get("settings", [])
