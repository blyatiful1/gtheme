"""Who owns what: the ownership ledger and the switch cleanup it enables.

The baseline answers "what did this look like before gtheme?". The ledger
answers a different question: "which Look is responsible for this right now?".
Both are needed, and confusing them is how theme managers end up leaving debris
behind.

Switching from one Look to another is the case that needs it. The naive
approach — restore everything, then apply the new Look — flashes the desktop
through an intermediate state and throws away anything the user changed by
hand. The ledger allows the surgical version: revert only what the *outgoing*
Look owned that the *incoming* one does not manage, and leave everything else
alone.

Three properties the cleanup keeps, each of them a v1 lesson:

* **Every entry is walked, not just the current one.** A component overlaid
  from a third Look is still owned by that third Look, and only a full walk
  finds it.
* **Reverting goes through the pristine baseline**, never through a
  "remembered previous value". The baseline originals are never modified.
* **Only what actually reverted is forgotten.** An item that failed to revert
  keeps its record and its stored copy, so the Undo page can still recover it.
  A cleanup that cannot finish must degrade to "you can still undo this", never
  to "that is gone now".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .atomic import atomic_write_json, load_json
from .baseline import Baseline
from .paths import ledger_file

__all__ = ["CleanupReport", "drop_entry", "read_ledger", "switch_cleanup", "write_entry", "write_ledger"]


def read_ledger(path: str | Path | None = None) -> dict[str, dict]:
    """Look name to ``{"files": [...], "settings": [...]}``. Never raises."""
    target = Path(path) if path is not None else ledger_file()
    data, _warning = load_json(target, {})
    return data if isinstance(data, dict) else {}


def write_ledger(ledger: dict[str, dict], path: str | Path | None = None) -> None:
    """Replace the ledger wholesale, atomically."""
    target = Path(path) if path is not None else ledger_file()
    atomic_write_json(target, ledger)


def write_entry(
    name: str,
    files,
    settings,
    path: str | Path | None = None,
) -> None:
    """Record what ``name`` owns, sorted and de-duplicated.

    Called *before* the changes it describes are made (the R4 rule). A crash
    between the two leaves a ledger that claims slightly too much, which costs
    a redundant restore of something already correct. The other order leaves a
    ledger that claims too little, and an unclaimed change is one nothing will
    ever undo.
    """
    ledger = read_ledger(path)
    ledger[name] = {"files": sorted(set(files)), "settings": sorted(set(settings))}
    write_ledger(ledger, path)


def drop_entry(name: str, path: str | Path | None = None) -> None:
    """Forget that ``name`` owns anything."""
    ledger = read_ledger(path)
    if ledger.pop(name, None) is not None:
        write_ledger(ledger, path)


@dataclass
class CleanupReport:
    """What a switch cleanup did, and what it could not do."""

    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: Items that could not be reverted and are therefore still recoverable
    #: from the Undo page. Never silently dropped.
    kept: int = 0


def switch_cleanup(
    incoming: str,
    incoming_files: set[str],
    incoming_settings: set[str],
    baseline: Baseline,
    path: str | Path | None = None,
) -> CleanupReport:
    """Revert what previous Looks owned and the incoming one does not manage.

    Args:
        incoming: the name of the Look being applied.
        incoming_files: destinations the incoming Look will write.
        incoming_settings: setting keys the incoming Look will write.
        baseline: the pristine recording to revert through.
        path: ledger location override.

    Returns:
        A report. This function never raises on a cleanup failure — a Look that
        cannot be applied because tidying up the last one went wrong would be
        the worst of both worlds.
    """
    report = CleanupReport()
    ledger = read_ledger(path)
    outgoing = [
        name
        for name, owned in ledger.items()
        if name != incoming and isinstance(owned, dict)
    ]
    if not outgoing:
        return report

    for name in outgoing:
        owned = ledger[name]
        orphan_files = [f for f in owned.get("files", []) if f not in incoming_files]
        orphan_settings = [s for s in owned.get("settings", []) if s not in incoming_settings]

        if orphan_files:
            outcome = baseline.restore_only_files(orphan_files)
            report.notes.extend(f"tidied up: {line}" for line in outcome.log)
            report.warnings.extend(outcome.warnings)
            baseline.forget_files(outcome.done)
            report.kept += sum(1 for key in orphan_files if key in baseline.files)

        if orphan_settings:
            outcome = baseline.restore_only_settings(orphan_settings)
            report.notes.extend(f"tidied up: {line}" for line in outcome.log)
            report.warnings.extend(outcome.warnings)
            baseline.forget_settings(outcome.done)
            report.kept += sum(1 for key in orphan_settings if key in baseline.settings)

        ledger.pop(name, None)

    write_ledger(ledger, path)
    if report.kept:
        report.warnings.append(
            f"{report.kept} thing(s) from the previous look could not be changed back "
            "automatically — the Undo page can still recover them"
        )
    return report
