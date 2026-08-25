"""Add-ons that must not be on at the same time, and hazards from combinations.

Two different problems live here, and they are kept apart deliberately.

**Either/or pairs.** Four pairs of curated add-ons do the same job in
incompatible ways: two docks, two clipboard histories, two system monitors, two
desktop-icon implementations. Turning the second one on does not produce an
error — it produces a desktop with two docks, or a top bar with everything in
it twice, and a person who has no idea which of the forty things they turned on
did it. So the app never lets both be chosen silently: picking one offers to
turn the other off, in those words.

**Hazardous combinations.** Both add-ons are legitimate, both may be wanted, and
together they break something. This machine has exactly one known case, and it
is a bad one: blurring the top bar while the top bar is set to hide starves
every screen-capture route on the machine — screen recording and screen sharing
stop working, with no error anywhere. That is a sentence the user gets to read
*before* it happens, phrased as what will happen.

Both tables are code rather than data because they are cross-cutting: they are
about pairs, and a panel file describes one add-on. Panels may still declare
their own conflicts, and :func:`from_panels` folds those in, so a new curated
panel can introduce a pair without editing this file.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

__all__ = [
    "CONFLICTS",
    "HAZARDS",
    "Conflict",
    "Hazard",
    "active_conflicts",
    "active_hazards",
    "conflicts_with",
    "from_panels",
    "replacement_question",
]


@dataclass(frozen=True)
class Conflict:
    """One either/or pair.

    Args:
        a: one add-on's directory name.
        b: the other's.
        explain: one sentence saying what having both does, in the user's
            terms. Rendered next to the offer to turn one off.
    """

    a: str
    b: str
    explain: str

    @property
    def pair(self) -> frozenset[str]:
        return frozenset({self.a, self.b})

    def other(self, uuid: str) -> str | None:
        """The one that has to go if ``uuid`` is chosen."""
        if uuid == self.a:
            return self.b
        if uuid == self.b:
            return self.a
        return None


#: The four pairs from the research, plus whatever the panels declare.
CONFLICTS: tuple[Conflict, ...] = (
    Conflict(
        "dash-to-dock@micxgx.gmail.com",
        "dash-to-panel@jderose9.github.com",
        "Both of these rearrange the same part of the screen, and having both on "
        "gives you two of everything.",
    ),
    Conflict(
        "clipboard-indicator@tudmotu.com",
        "clipboard-history@alexsaveau.dev",
        "Both keep a history of what you copied, so having both on gives you two "
        "lists that don't agree.",
    ),
    Conflict(
        "Vitals@CoreCoding.com",
        "tophat@fflewddur.github.io",
        "Both show how busy your computer is in the top bar, and having both on "
        "fills the bar twice over.",
    ),
    Conflict(
        "ding@rastersoft.com",
        "gtk4-ding@smedius.gitlab.com",
        "These are two versions of the same thing — icons on the desktop — and "
        "running both draws them on top of each other.",
    ),
)


@dataclass(frozen=True)
class Hazard:
    """A combination that is allowed and worth a sentence of warning.

    Args:
        uuids: every add-on that must be on for the hazard to apply.
        requires: descriptor ids that must additionally be *true*. Empty means
            having the add-ons on is enough.
        explain: the consequence, phrased as one.
    """

    uuids: tuple[str, ...]
    requires: tuple[str, ...]
    explain: str


#: Known on this machine and reproduced from the notes rather than guessed.
HAZARDS: tuple[Hazard, ...] = (
    Hazard(
        uuids=(
            "blur-my-shell@aunetx",
            "hidetopbar@mathieu.bidon.ca",
        ),
        requires=("org.gnome.shell.extensions.blur-my-shell.panel:blur",),
        explain=(
            "Blurring the bar at the top while the bar is also set to hide can stop "
            "screen recording and screen sharing from working, with no error to tell "
            "you why. Turn the blur off if recording stops working."
        ),
    ),
)


def conflicts_with(uuid: str, extra: Iterable[Conflict] = ()) -> list[str]:
    """Every add-on that cannot be on at the same time as this one."""
    others = []
    for conflict in (*CONFLICTS, *extra):
        other = conflict.other(uuid)
        if other is not None and other not in others:
            others.append(other)
    return others


def active_conflicts(
    enabled: Iterable[str],
    extra: Iterable[Conflict] = (),
) -> list[Conflict]:
    """The pairs where both are currently on. Usually empty, never ignored."""
    on = set(enabled)
    seen: set[frozenset[str]] = set()
    found: list[Conflict] = []
    for conflict in (*CONFLICTS, *extra):
        if conflict.pair <= on and conflict.pair not in seen:
            seen.add(conflict.pair)
            found.append(conflict)
    return found


def replacement_question(chosen_title: str, other_title: str) -> str:
    """The sentence shown when turning one on would collide with another."""
    return f"{chosen_title} replaces {other_title}. Turn {other_title} off?"


def active_hazards(
    enabled: Iterable[str],
    is_true: Callable[[str], bool] | None = None,
) -> list[Hazard]:
    """Hazards that apply right now.

    Args:
        enabled: the add-ons currently on.
        is_true: called with a descriptor id, returns whether that setting is
            on. When not given, a hazard with requirements is reported as
            applying — the honest default is to warn, not to stay quiet
            because nothing could be checked.
    """
    on = set(enabled)
    found: list[Hazard] = []
    for hazard in HAZARDS:
        if not set(hazard.uuids) <= on:
            continue
        if is_true is not None and not all(is_true(need) for need in hazard.requires):
            continue
        found.append(hazard)
    return found


def from_panels(panels: Sequence[object]) -> list[Conflict]:
    """Pairs declared by panel files, as :class:`Conflict` objects.

    A panel's ``target.conflicts`` lists add-ons it must not run beside. Those
    become pairs here with a generic sentence, so a curated panel can introduce
    an either/or without a code change; a pair that deserves better wording gets
    added to :data:`CONFLICTS`, which wins because it is matched first.
    """
    known = {conflict.pair for conflict in CONFLICTS}
    out: list[Conflict] = []
    for panel in panels:
        target = getattr(panel, "target", None)
        if target is None:
            continue
        for uuid in getattr(target, "uuids", ())[:1]:
            for other in getattr(target, "conflicts", ()):
                pair = frozenset({uuid, other})
                if len(pair) != 2 or pair in known:
                    continue
                known.add(pair)
                out.append(
                    Conflict(
                        uuid,
                        other,
                        "These two do the same job in different ways, and having both "
                        "on leaves your desktop showing it twice.",
                    )
                )
    return out
