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


def run_rescue(state_dir: str | None = None) -> int:
    """Restore the pristine baseline and undo gtheme's extension changes.

    Args:
        state_dir: override for ``~/.local/state/gtheme/v2``. Test seam.

    Returns:
        Process exit code: 0 when the desktop was restored (or there was
        nothing to restore), non-zero when something could not be put back.
    """
    raise NotImplementedError(
        "gtheme rescue is not built yet. Until it is, undo changes from the "
        "app's Undo & Restore Points page."
    )
