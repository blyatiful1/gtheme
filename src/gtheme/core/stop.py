"""The one exception that means "somebody pressed Stop".

It lives here, in the engine's own layer, rather than beside the button that
raises it, because of who has to *recognise* it. A long change narrates through
a ``report`` callback the caller supplies, and that callback is the only place
the engine ever hands control back between two operations — so it is also the
only place a stop can be raised safely. The engine therefore has to know that
one particular exception coming out of ``report`` is not a failure:

* :meth:`~gtheme.core.transaction.Transaction._install_extensions` wraps its
  installer call in ``except Exception`` on purpose — one add-on failing to
  download must not lose the whole Look — and so does the thing that fills the
  installer seam. A stop raised while an add-on was downloading was caught by
  both, recorded as "this add-on could not be downloaded", and the apply then
  ran to the end: the person was shown a rollback message, an untrue reason
  blaming their internet connection, and then a successful apply of the Look
  they had just asked to stop (review-report E5).
* Making it a ``BaseException`` instead would have kept it out of those arms,
  but it would also have taken it past the arm in
  :meth:`~gtheme.core.transaction.Transaction.apply` that *rolls back* — and a
  stop that leaves the desktop half changed is worse than one that is ignored.

So it stays an ordinary exception, travelling the ordinary failure path that
unwinds, and every ``except Exception`` between the narrator and that path
names it and re-raises it. There are exactly two, and both say why.

Nothing here raises it. :class:`gtheme.ui.applyrunner.ApplyRunner` does, out of
the narrator it hands the work, and re-exports this name so callers have one
place to import it from.
"""

from __future__ import annotations

__all__ = ["Stopped"]


class Stopped(Exception):
    """Raised out of a progress callback when somebody pressed Stop.

    Deliberately an ordinary exception: it travels the engine's existing
    failure path, which is the path that rolls back. A separate cancellation
    channel would need the engine to learn about cancellation, and would then
    need its own rollback.
    """
