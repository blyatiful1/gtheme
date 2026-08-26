"""Reading the descriptor corpus off disk.

``data/panels/*.toml`` describes one curated add-on each; ``data/domains/*.toml``
describes one area of core GNOME each. Both parse into the frozen models in
:mod:`gtheme.panels.descriptor`, which is what makes a typo in a data file a
loud error at load time rather than a row that quietly does nothing.

The data lives in the repository during development and beside the package once
installed, so the search order is: an explicit argument, then
``GTHEME_DATA_DIR``, then the repository checkout this module was imported
from, then the installed share directories.

Failures are collected, never swallowed: :func:`load_panels` returns what it
could read *and* a list of sentences naming what it could not, so one bad file
does not cost the other twenty-three panels — while still being impossible to
miss, because the caller is handed the problems.

``data/domains/coverage.toml`` is read here too, and the join it feeds — which
rows belong on which page, and which keys a saved moment has to capture — with
it. Three modules had each grown their own reader for that one file, two of
them character-for-character the same and the third subtly different: it kept
the ``compound`` keys the other two drop, because a saved moment that dropped
them would not record light-or-dark or which add-ons were on, which are the two
things people undo most. Three readers of one file is three chances for the
manifest to mean three things, so there is one now and the difference between
those questions is a function name.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from .descriptor import DomainDescriptor, PanelDescriptor, Row

__all__ = [
    "COVERAGE_FILENAME",
    "DATA_DIR_ENV",
    "Corpus",
    "captured_keys",
    "data_dir",
    "floor_ids",
    "load_corpus",
    "load_dispositions",
    "load_domains",
    "load_panels",
    "page_rows",
    "surfaced_ids",
]

#: Override for where the descriptor corpus lives. Set by tests and by anyone
#: running the app from a checkout that is not the one it was imported from.
DATA_DIR_ENV = "GTHEME_DATA_DIR"


def data_dir(explicit: Path | str | None = None) -> Path | None:
    """Where ``panels/`` and ``domains/`` live, or None if nowhere does."""
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(Path(explicit))
    from_env = os.environ.get(DATA_DIR_ENV)
    if from_env:
        candidates.append(Path(from_env))
    # src/gtheme/panels/loader.py -> repository root
    candidates.append(Path(__file__).resolve().parents[3] / "data")
    data_dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    candidates.extend(Path(entry) / "gtheme" for entry in data_dirs.split(os.pathsep) if entry)
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


@dataclass
class Corpus:
    """Everything that loaded, and everything that did not.

    Args:
        panels: the curated add-on panels, in file-name order.
        domains: the core-GNOME areas, in file-name order.
        problems: one sentence per file that could not be read. Empty is the
            only acceptable state for a release; the descriptor tests assert it.
    """

    panels: list[PanelDescriptor] = field(default_factory=list)
    domains: list[DomainDescriptor] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def rows(self) -> list[Row]:
        """Every row of the whole corpus, panels first."""
        return [row for panel in self.panels for row in panel.rows] + [
            row for domain in self.domains for row in domain.rows
        ]

    def descriptor_ids(self) -> list[str]:
        return [row.id for row in self.rows]


def _read(path: Path) -> dict:
    """Parse one descriptor file, accepting either spelling of the row table.

    ``[[rows]]`` is the spelling, because ``rows`` is what the model calls the
    field and one name for one thing is worth more than either name being
    prettier. DESIGN.md writes ``[[row]]`` in places; every committed data file
    uses ``[[rows]]``, and a test keeps it that way.

    ``[[row]]`` is still accepted, because the alternative is a Look or panel
    author hitting "unexpected key 'row'" for a file that is obviously correct.
    A file that uses both spellings is a mistake and says so.
    """
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    if "row" in data:
        if "rows" in data:
            raise ValueError("uses both 'row' and 'rows' — pick one")
        data["rows"] = data.pop("row")
    return data


#: Files that live in ``data/domains/`` but are not descriptors. They are
#: listed by name, never guessed at: a descriptor that fails to load has to
#: stay a loud problem, so the only way a file gets to be silently skipped is
#: by being written down here.
NOT_DESCRIPTORS: frozenset[str] = frozenset(
    {
        # The per-key disposition manifest — same directory, different shape.
        "coverage.toml",
    }
)


def _load_dir(directory: Path, model: type, problems: list[str]) -> Iterator[object]:
    if not directory.is_dir():
        return
    for path in sorted(directory.glob("*.toml")):
        if path.name in NOT_DESCRIPTORS:
            continue
        try:
            yield model.model_validate(_read(path))
        except ValidationError as exc:
            # Checked before ValueError below: pydantic's ValidationError *is*
            # a ValueError, and reporting it as "cannot be read" would hide
            # which field of which row is wrong.
            problems.append(f"{path.name}: {exc.error_count()} problem(s): {exc}")
        except (OSError, tomllib.TOMLDecodeError, ValueError) as exc:
            problems.append(f"{path.name}: cannot be read ({exc})")


def load_panels(directory: Path | str | None = None) -> tuple[list[PanelDescriptor], list[str]]:
    """``(panels, problems)`` from ``data/panels/``."""
    root = Path(directory) if directory is not None else None
    if root is None:
        base = data_dir()
        root = base / "panels" if base is not None else None
    problems: list[str] = []
    if root is None:
        return [], problems
    panels = list(_load_dir(root, PanelDescriptor, problems))
    return panels, problems  # type: ignore[return-value]


def load_domains(directory: Path | str | None = None) -> tuple[list[DomainDescriptor], list[str]]:
    """``(domains, problems)`` from ``data/domains/``."""
    root = Path(directory) if directory is not None else None
    if root is None:
        base = data_dir()
        root = base / "domains" if base is not None else None
    problems: list[str] = []
    if root is None:
        return [], problems
    domains = list(_load_dir(root, DomainDescriptor, problems))
    return domains, problems  # type: ignore[return-value]


def load_corpus(directory: Path | str | None = None) -> Corpus:
    """Both halves of the descriptor corpus in one object."""
    base = data_dir(directory)
    panels, panel_problems = load_panels(base / "panels" if base else None)
    domains, domain_problems = load_domains(base / "domains" if base else None)
    return Corpus(panels=panels, domains=domains, problems=panel_problems + domain_problems)


# ---------------------------------------------------------------------------
# the coverage manifest, and the joins it feeds
# ---------------------------------------------------------------------------

#: The per-key disposition manifest, beside the descriptor corpus.
COVERAGE_FILENAME = "coverage.toml"

#: Dispositions whose keys gtheme can write, and which a saved moment must
#: therefore capture. ``excluded`` and ``delegated`` keys are never written.
CAPTURED_DISPOSITIONS = ("surfaced", "compound", "floor")


def load_dispositions(directory: Path | str | None = None) -> dict[str, str]:
    """``{descriptor_id: disposition}`` from ``data/domains/coverage.toml``.

    Returns an empty mapping when the file is missing or unreadable rather than
    raising. A packaging mistake that loses the manifest must show up as pages
    with no rows on them — visibly wrong, and survivable — not as an app that
    refuses to open.
    """
    base = data_dir(directory)
    if base is None:
        return {}
    path = base / "domains" / COVERAGE_FILENAME
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    given = data.get("dispositions")
    if not isinstance(given, dict):
        return {}
    return {str(key): str(value) for key, value in given.items()}


def surfaced_ids(page_id: str, dispositions: dict[str, str] | None = None) -> list[str]:
    """Every descriptor id that belongs on one page, floor keys included.

    Raises:
        ValueError: the manifest dispositions a key onto a page that does not
            exist. Propagated deliberately — it means the data and
            ``ui.registry`` have drifted, which is a bug to fix rather than a
            condition to survive.
    """
    from ..ui import registry

    given = load_dispositions() if dispositions is None else dispositions
    return registry.resolve_surfaced(given).get(page_id, [])


def page_rows(
    page_id: str,
    *,
    corpus: Corpus | None = None,
    dispositions: dict[str, str] | None = None,
) -> list[Row]:
    """The hand-written rows of one page, in the order they were authored.

    Corpus order is authoring order — the order of the ``[[rows]]`` tables in
    ``data/domains/<area>.toml`` — and that is deliberately what the page shows.
    A person reading down a page is reading the sequence somebody thought about,
    not an alphabetical accident.

    Keys dispositioned ``floor`` have no hand-written row and are therefore not
    returned here; :func:`floor_ids` is the other half.
    """
    wanted = set(surfaced_ids(page_id, dispositions))
    if not wanted:
        return []
    loaded = corpus if corpus is not None else load_corpus()
    return [row for row in loaded.rows if row.id in wanted]


def floor_ids(
    page_id: str | None = None,
    *,
    corpus: Corpus | None = None,
    dispositions: dict[str, str] | None = None,
) -> list[str]:
    """Ids on a page that no descriptor file describes. The floor's own list.

    Sorted, because nobody authored an order for them: they are whatever the
    desktop happens to have that gtheme has not written a control for, and a
    stable alphabetical order is the only honest one.
    """
    from ..ui import registry

    target = registry.FLOOR_PAGE_ID if page_id is None else page_id
    loaded = corpus if corpus is not None else load_corpus()
    authored = {row.id for row in loaded.rows}
    return sorted(d for d in surfaced_ids(target, dispositions) if d not in authored)


def captured_keys(directory: Path | str | None = None) -> list[str]:
    """The settings named in ``coverage.toml`` that gtheme is allowed to write.

    A different question from :func:`surfaced_ids`, which answers "which page
    shows which row" and deliberately drops the ``compound`` keys. A saved
    moment that dropped them would not record light-or-dark or which add-ons
    were on, which are the two things people undo most.
    """
    keys: list[str] = []
    for descriptor_id, disposition in load_dispositions(directory).items():
        verb = str(disposition).partition("(")[0].strip()
        if verb not in CAPTURED_DISPOSITIONS:
            continue
        schema, _, key = str(descriptor_id).partition(":")
        if schema and key:
            keys.append(f"gsettings:{schema} {key}")
    return keys
