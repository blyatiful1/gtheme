"""The headless "put it back" path — ``gtheme rescue``.

This runs when the desktop is unusable and the app's window cannot be opened,
so it must never import GTK, never need a graphical session, and never need
anything gtheme itself wrote to still be readable. Two steps, in order:

1. Restore the v2 pristine baseline (the snapshot taken the first time gtheme
   touched each setting or file), if one exists.
2. Turn off every extension gtheme itself turned on, returning
   ``enabled-extensions`` to its exact pre-gtheme value.

Implementation lands with the core engine port (Wave 1 Agent A). The signature
below is the contract the CLI codes against and does not change.
"""

from __future__ import annotations

import os


def run_rescue(state_dir: str | None = None) -> int:
    """Restore the pristine baseline and undo gtheme's extension changes.

    Args:
        state_dir: override for ``~/.local/state/gtheme/v2``. Test seam.

    Returns:
        Process exit code: 0 when the desktop was restored (or there was
        nothing to restore), non-zero when something could not be put back.

    Prints what it is doing in plain sentences as it goes. Somebody running
    this is looking at a broken desktop in a text console and needs to be told
    what happened, not handed a silent exit code.

    Imports are deliberately inside the function. This module is imported by
    the command-line entry point on a machine that may have no PyGObject and no
    graphical session at all, and nothing should be loaded until the rescue is
    actually asked for.
    """
    if state_dir:
        os.environ["GTHEME_STATE_DIR"] = state_dir

    from .baseline import Baseline
    from .lock import LockBusy, process_lock

    # Read before locking. Taking the lock creates the state directory, and a
    # rescue on a machine where gtheme has never changed anything has nothing
    # to lock against and no business leaving a directory behind.
    baseline = Baseline().load()
    if baseline.is_empty:
        print("There is nothing to put back — this app has not changed anything yet.")
        return 0

    try:
        with process_lock():
            # Re-read under the lock: another gtheme may have been finishing an
            # apply between the check above and the lock being granted.
            return _rescue_locked(Baseline().load())
    except LockBusy as exc:
        print(str(exc))
        return 1


def _rescue_locked(baseline) -> int:
    """The body of the rescue, holding the lock.

    The order matters. Files first, then settings: a setting that points at a
    file wants the file to be there when it takes effect, which is the same
    ordering rule an apply follows.

    Step two of the rescue — turning off the add-ons gtheme turned on — needs
    no separate pass. ``enabled-extensions`` is an ordinary recorded setting,
    and what was recorded is the exact list from *before* any Look unioned into
    it, so putting settings back turns off exactly what gtheme turned on and
    leaves the user's own add-ons alone.
    """
    from .ledger import write_ledger

    if baseline.is_empty:
        print("There is nothing to put back — this app has not changed anything yet.")
        return 0

    for warning in baseline.warnings:
        print(warning)

    files = baseline.restore_files()
    settings = baseline.restore_settings()

    for line in files.log + settings.log:
        print(line)
    for line in files.warnings + settings.warnings:
        print(line)

    # A dead record can never be put back by trying again — the saved copy is
    # gone, or the setting no longer exists on this machine. Dropping it lets
    # the rescue finish instead of failing forever on the same item.
    if files.dead:
        baseline.forget_files(files.dead)
    if settings.dead:
        baseline.forget_settings(settings.dead)

    selected_files = list(baseline.files)
    selected_settings = list(baseline.settings)
    stuck = [key for key in selected_files if key not in files.done] + [
        key for key in selected_settings if key not in settings.done
    ]

    if stuck:
        print(
            f"{len(stuck)} thing(s) could not be put back. Nothing was lost — "
            "run this again once the cause is fixed."
        )
        return 1

    # A complete restore consumes the recording. The desktop *is* the way it
    # was now, and a kept record would stop the next change from taking a fresh
    # snapshot — quietly reverting months of the user's own edits the next time
    # they pressed undo.
    baseline.forget_files(list(baseline.files))
    baseline.forget_settings(list(baseline.settings))
    write_ledger({})
    print("Your desktop has been put back the way it was before this app changed anything.")
    return 0
