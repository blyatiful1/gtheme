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
  keeps its record, its stored copy *and the ledger entry that claims it*, so
  the Undo page can still recover it and the next switch tries again. A cleanup
  that cannot finish must degrade to "you can still undo this", never to "that
  is gone now".
* **The user's own edits are not a previous Look.** The ``__manual__`` entry
  records what somebody changed from a page. Switching Looks walks past it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .atomic import atomic_write_json, load_json
from .baseline import Baseline
from .paths import current_file, ledger_file

__all__ = [
    "MANUAL_OWNER",
    "CleanupReport",
    "clear_current_look",
    "current_look",
    "current_record",
    "drop_entry",
    "read_ledger",
    "set_current_look",
    "switch_cleanup",
    "write_entry",
    "write_ledger",
]


#: Ledger owner name for changes that came from a page rather than a Look, and
#: for putting a saved moment back. Switching Looks tidies up after other
#: Looks; it never tidies up after the user's own deliberate edits, which is
#: why this entry is skipped by :func:`switch_cleanup` — a Look that does not
#: manage the accent colour has no business putting back the one the user chose
#: on the Colours page an hour ago.
#:
#: Lives here rather than in ``core.transaction`` because the cleanup that has
#: to exclude it lives here; ``core.transaction`` re-exports it.
MANUAL_OWNER = "__manual__"


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
    #: Items that could not be reverted *this time* and are therefore still
    #: recorded, still owned, and still recoverable from the Undo page. Never
    #: silently dropped: the entry that claims them is kept so a later switch
    #: tries again.
    kept: int = 0
    #: Items that can never be reverted through the baseline — the saved copy
    #: is gone, or the setting no longer exists on this machine. Counted
    #: separately from :attr:`kept` because telling somebody "the Undo page can
    #: still recover them" about these would be untrue.
    dead: int = 0


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
        # MANUAL_OWNER is not a previous Look. It is the user's own deliberate
        # edits, and tidying those away on a Look switch is how a theme manager
        # silently undoes the accent colour somebody picked this morning.
        if name != incoming and name != MANUAL_OWNER and isinstance(owned, dict)
    ]
    if not outgoing:
        return report

    for name in outgoing:
        owned = ledger[name]
        orphan_files = [f for f in owned.get("files", []) if f not in incoming_files]
        orphan_settings = [s for s in owned.get("settings", []) if s not in incoming_settings]
        kept_files: list[str] = []
        kept_settings: list[str] = []

        if orphan_files:
            outcome = baseline.restore_only_files(orphan_files)
            report.notes.extend(f"tidied up: {line}" for line in outcome.log)
            report.warnings.extend(outcome.warnings)
            # A dead record can never be put back by trying again, so it is
            # forgotten alongside the ones that worked — keeping it would block
            # a fresh recording of that destination for good.
            baseline.forget_files([*outcome.done, *outcome.dead])
            done = set(outcome.done)
            dead = set(outcome.dead)
            kept_files = [key for key in orphan_files if key not in done and key not in dead]
            report.dead += sum(1 for key in orphan_files if key in dead)

        if orphan_settings:
            outcome = baseline.restore_only_settings(orphan_settings)
            report.notes.extend(f"tidied up: {line}" for line in outcome.log)
            report.warnings.extend(outcome.warnings)
            baseline.forget_settings([*outcome.done, *outcome.dead])
            done = set(outcome.done)
            dead = set(outcome.dead)
            kept_settings = [key for key in orphan_settings if key not in done and key not in dead]
            report.dead += sum(1 for key in orphan_settings if key in dead)

        report.kept += len(kept_files) + len(kept_settings)
        if kept_files or kept_settings:
            # Only what actually reverted is forgotten. An item that failed to
            # revert keeps its record *and* the entry that claims it, so the
            # next switch tries again — dropping the entry here is how a
            # leftover change becomes one nothing will ever undo.
            ledger[name] = {
                "files": sorted(set(kept_files)),
                "settings": sorted(set(kept_settings)),
            }
        else:
            ledger.pop(name, None)

    write_ledger(ledger, path)
    if report.kept:
        report.warnings.append(
            f"{report.kept} thing(s) from the previous look could not be changed back "
            "automatically — the Undo page can still recover them"
        )
    if report.dead:
        report.warnings.append(
            f"{report.dead} thing(s) from the previous look could not be changed back: "
            "the saved copy of them is gone"
        )
    return report


# ---------------------------------------------------------------------------
# which Look is applied right now
# ---------------------------------------------------------------------------
#
# A third question, and the one the app was answering by guessing. The ledger
# above says what each Look owns, and stays true for every Look that still has
# a file or a setting on the desktop. "Which Look am I using" is a different
# question with one answer or none, and it was being inferred by intersecting
# the ledger's keys with the list of installed Looks — which fails silently
# whenever a Look's title differs from its folder name (the ledger is keyed by
# title), whenever two Looks still own something, and whenever a saved moment's
# label happens to match a Look's name. v1 kept a file for this. So does v2.


def current_look(path: str | Path | None = None) -> str | None:
    """The name of the Look applied right now, or None.

    None is a real answer and a common one: a desktop nobody has applied a Look
    to, or one that has been put back to a saved moment since.
    """
    target = Path(path) if path is not None else current_file()
    data, _warning = load_json(target, None)
    if not isinstance(data, dict):
        return None
    name = data.get("name")
    return str(name) if name else None


def current_record(path: str | Path | None = None) -> dict:
    """Everything recorded about the current Look. ``{}`` when there is none."""
    target = Path(path) if path is not None else current_file()
    data, _warning = load_json(target, {})
    return data if isinstance(data, dict) else {}


def set_current_look(name: str, *, label: str | None = None, path: str | Path | None = None) -> None:
    """Record that ``name`` is the Look now applied.

    Both the name and the label are kept. The name is the Look's folder name,
    which is what a lookup matches on; the label is what a person was shown
    when they picked it, which is what to say back to them. Storing only one of
    the two is how the guess this replaces went wrong.
    """
    target = Path(path) if path is not None else current_file()
    atomic_write_json(target, {"name": name, "label": label or name})


def clear_current_look(path: str | Path | None = None) -> None:
    """Forget which Look is applied. No Look is a state, not a missing value."""
    target = Path(path) if path is not None else current_file()
    target.unlink(missing_ok=True)
    target.with_name(target.name + ".bak").unlink(missing_ok=True)
