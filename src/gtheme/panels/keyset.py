"""Which settings gtheme captures — derived once, for both things that capture.

Two places in the app write down "how this desktop is set right now": a saved
moment (:mod:`gtheme.ui.pages.restore`) and a Look saved from the current
desktop (:mod:`gtheme.ui.pages.looks`). They were two loops over the same data
written months apart, and they disagreed by 174 keys — every ``compound`` key
among them, ``color-scheme`` first (review-report H13). So a person on a dark
desktop saved it as a Look, applied it on a light one, and got the dark GTK
theme with the light shell: the Look carried ``gtk-theme`` and not the
light-or-dark switch, because one loop read the coverage manifest and the other
did not.

There is one derivation here now, and the two callers differ by **one named
argument** rather than by which loop somebody wrote second:

* a **saved moment** covers everything gtheme can write, floor settings
  included. It goes back onto the same desktop it came from, so a11y and
  screensaver settings the More Settings page can change must be in it or Undo
  puts back less than it promised.
* a **saved Look** covers everything except the ``floor`` tier, deliberately.
  A Look is made to be given away, and the floor is where somebody's
  accessibility settings live — high contrast, large text, the screen reader,
  the screensaver delay. Publishing a desktop must not publish those, and
  applying somebody else's Look must not switch off the magnifier of the person
  who applied it. That exclusion is the one thing H13 asked to be *deliberate*
  rather than an accident of which loop was written second, so it is a named
  constant with this paragraph attached, and :data:`LOOK_DISPOSITIONS` is what
  says it in code.

**Where this lives.** ``panels/`` and not ``core/``: the derivation reads the
descriptor corpus and ``coverage.toml``, which are this package's own data, and
``docs/architecture.md`` has ``panels/`` sitting *above* ``core/`` — the engine
may not import the corpus. It is still off the UI side of the line, has no GTK
import, and can be read from a text console.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ..core.settings_backend import KeyKind, SettingsKey
from .loader import captured_keys, load_corpus, load_dispositions

__all__ = [
    "FLOOR_DISPOSITION",
    "LOOK_DISPOSITIONS",
    "MOMENT_DISPOSITIONS",
    "corpus_keys",
    "floor_keys",
    "look_keys",
    "manifest_keys",
    "moment_keys",
    "row_key",
]

#: The disposition whose keys a shareable Look leaves alone. See the module
#: docstring: this is a decision, not an oversight.
FLOOR_DISPOSITION = "floor"

#: What a saved moment covers: everything gtheme is allowed to write.
MOMENT_DISPOSITIONS: tuple[str, ...] = ("surfaced", "compound", "floor")

#: What a saved Look carries: the same, minus the floor.
LOOK_DISPOSITIONS: tuple[str, ...] = ("surfaced", "compound")


def row_key(row: Any) -> str:
    """The backend key string for one descriptor row.

    The same three forms :func:`gtheme.ui.widgets.rows.key_for` renders, built
    through :class:`~gtheme.core.settings_backend.SettingsKey` so the grammar
    has one owner. ``key_for`` cannot be called from here — it lives in a
    module that imports GTK, and a saved moment has to be derivable with no
    display — so the two are held together by a parity test over the whole
    shipped corpus rather than by hope.
    """
    if row.keyfile:
        return SettingsKey(
            KeyKind.KEYFILE,
            schema=row.schema_id,
            key=row.key,
            path=row.path,
            file=row.keyfile,
        ).as_text()
    if row.path:
        return SettingsKey(
            KeyKind.GSETTINGS_PATH, schema=row.schema_id, key=row.key, path=row.path
        ).as_text()
    return SettingsKey(KeyKind.GSETTINGS, schema=row.schema_id, key=row.key).as_text()


def corpus_keys(corpus: Any | None = None) -> list[str]:
    """Every hand-written descriptor row that holds a value, in corpus order.

    A link row goes somewhere and holds nothing, and a row with no schema
    cannot be addressed, so neither produces a key.
    """
    loaded = corpus if corpus is not None else load_corpus()
    keys: list[str] = []
    seen: set[str] = set()
    for row in loaded.rows:
        if row.schema_id is None or row.key is None:
            continue
        key = row_key(row)
        if key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


def floor_keys(directory: Path | str | None = None) -> set[str]:
    """The keys ``coverage.toml`` disposes as ``floor``.

    The set :func:`look_keys` subtracts. Built in the same shape
    :func:`gtheme.panels.loader.captured_keys` builds its own keys, and a test
    asserts this set is really a subset of that one — if the two spellings ever
    drift apart the subtraction would quietly stop removing anything, which is
    the failure mode a silent filter always has.
    """
    found: set[str] = set()
    for descriptor_id, disposition in load_dispositions(directory).items():
        if str(disposition).partition("(")[0].strip() != FLOOR_DISPOSITION:
            continue
        schema, _, key = str(descriptor_id).partition(":")
        if schema and key:
            found.add(f"gsettings:{schema} {key}")
    return found


def manifest_keys(
    *,
    directory: Path | str | None = None,
    dispositions: Sequence[str] = MOMENT_DISPOSITIONS,
) -> list[str]:
    """The settings named in ``coverage.toml`` under the given dispositions.

    ``coverage.toml`` is read once, by :func:`gtheme.panels.loader.captured_keys`,
    which answers for all three captured tiers. Narrowing to a Look's tiers is
    a subtraction from that answer rather than a second walk of the file.
    """
    keys = captured_keys(directory)
    if FLOOR_DISPOSITION in dispositions:
        return keys
    excluded = floor_keys(directory)
    return [key for key in keys if key not in excluded]


def setting_keys(
    corpus: Any | None = None,
    *,
    directory: Path | str | None = None,
    dispositions: Sequence[str] = MOMENT_DISPOSITIONS,
) -> list[str]:
    """Every setting to write down, from both sources, in one list.

    Two sources, not one, and missing either leaves a hole a person would only
    find by pressing Undo and watching it not work:

    * the **descriptor corpus** — every hand-written row, including the add-on
      panels, whose values may live in a relocatable place or in the add-on's
      own settings file rather than under a plain schema;
    * the **coverage manifest** — the settings that have no row of their own
      but that the app still changes: the ``compound`` keys written two at a
      time by one control (light-or-dark writes two; switching an add-on on
      merges into a list), and the ``floor`` keys the More Settings page
      renders from the system's own descriptions.

    ``excluded`` and ``delegated`` keys are never in the answer, which is
    exactly the set gtheme never writes.

    Args:
        corpus: the descriptor corpus, when it is already loaded.
        directory: where ``coverage.toml`` lives. The tests' seam.
        dispositions: which manifest tiers to include. See
            :data:`MOMENT_DISPOSITIONS` and :data:`LOOK_DISPOSITIONS`.
    """
    keys = corpus_keys(corpus)
    seen = set(keys)
    for key in manifest_keys(directory=directory, dispositions=dispositions):
        if key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


def moment_keys(corpus: Any | None = None, *, directory: Path | str | None = None) -> list[str]:
    """Every setting a saved moment records. What is not here cannot be put back."""
    return setting_keys(corpus, directory=directory, dispositions=MOMENT_DISPOSITIONS)


def look_keys(corpus: Any | None = None, *, directory: Path | str | None = None) -> list[str]:
    """Every setting a saved Look carries — the moment's list minus the floor.

    See the module docstring for why the floor is left out on purpose.
    """
    return setting_keys(corpus, directory=directory, dispositions=LOOK_DISPOSITIONS)
