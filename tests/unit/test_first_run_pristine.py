"""The "Before gtheme" moment exists on a fresh install (persona-report §2.3).

Before this, the only way that row could exist was
``restorepoints.import_v1_baseline`` — the old command-line gtheme's records —
so on every machine that had never run version 1, which is every new machine,
README's headline safety promise pointed at a row that could never appear.

These tests are about the *first run*, not about the engine: capturing and
restoring a moment are covered in ``tests/unit/core_restorepoints.py``. What is
proved here is that the moment is taken, taken once, taken with the right kind
and id so the Undo page draws it as "Before gtheme", and never taken over the
top of a record that reaches back further.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for the onboarding module")

from gtheme.core.restorepoints import PRISTINE_ID, list_restore_points  # noqa: E402
from gtheme.core.settings_backend import MemoryBackend  # noqa: E402
from gtheme.ui import onboarding  # noqa: E402
from gtheme.ui.applyrunner import ApplyRunner  # noqa: E402

ACCENT = "gsettings:org.gnome.desktop.interface accent-color"
SCHEME = "gsettings:org.gnome.desktop.interface color-scheme"


@pytest.fixture(autouse=True)
def _no_version_one(tmp_path, monkeypatch):
    """No old command-line gtheme on this machine — the fresh-install case.

    Without this the import path reads the *real* ``~/.local/state/
    gtheme.v1-backup``, so what these tests proved would depend on whether the
    developer running them had ever used version 1.
    """
    monkeypatch.setenv("GTHEME_V1_BACKUP_DIR", str(tmp_path / "no-version-one"))


@pytest.fixture
def backend() -> MemoryBackend:
    store = MemoryBackend()
    store.set(ACCENT, "'green'")
    store.set(SCHEME, "'default'")
    return store


def _document(root: Path) -> dict:
    return json.loads((root / PRISTINE_ID / "restore-point.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# the capture itself
# --------------------------------------------------------------------------


def test_a_fresh_install_gets_a_real_pristine_moment(tmp_path, backend):
    point = onboarding.capture_pristine_point(
        backend=backend, root=tmp_path, keys=[ACCENT, SCHEME], dests=[]
    )

    assert point is not None
    assert point.id == PRISTINE_ID
    assert point.kind == "pristine", "the Undo page draws the row by kind, not by id"
    assert point.label == "Before gtheme"
    assert point.settings == {ACCENT: "'green'", SCHEME: "'default'"}
    assert _document(tmp_path)["kind"] == "pristine"


def test_the_undo_page_would_list_it_last_and_never_prune_it(tmp_path, backend):
    onboarding.capture_pristine_point(
        backend=backend, root=tmp_path, keys=[ACCENT], dests=[]
    )
    listed = list_restore_points(tmp_path)
    assert [p.kind for p in listed] == ["pristine"]
    assert [p.label for p in listed] == ["Before gtheme"]


def test_it_is_never_written_over_once_it_exists(tmp_path, backend):
    first = onboarding.capture_pristine_point(
        backend=backend, root=tmp_path, keys=[ACCENT], dests=[]
    )
    assert first is not None

    # The desktop moves on — a Look is applied, the accent changes.
    backend.set(ACCENT, "'purple'")
    again = onboarding.capture_pristine_point(
        backend=backend, root=tmp_path, keys=[ACCENT], dests=[]
    )

    assert again is None, "the moment before gtheme happened once and cannot happen twice"
    assert _document(tmp_path)["settings"] == {ACCENT: "'green'"}


def test_an_upgrade_keeps_version_ones_records_rather_than_todays_desktop(
    tmp_path, backend, monkeypatch
):
    """v1 had already themed this desktop, so today's values are not "before"."""
    v1 = tmp_path / "v1-backup"
    baseline = v1 / "backups" / "baseline"
    baseline.mkdir(parents=True)
    (baseline / "settings.json").write_text(
        json.dumps(
            {
                ACCENT: {
                    "backend": "gsettings",
                    "key": "org.gnome.desktop.interface accent-color",
                    "saved": "'blue'",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GTHEME_V1_BACKUP_DIR", str(v1))
    points = tmp_path / "points"

    point = onboarding.capture_pristine_point(
        backend=backend, root=points, keys=[ACCENT], dests=[]
    )

    assert point is not None
    assert point.settings[ACCENT] == "'blue'", "version 1's record, not the live desktop"
    assert point.kind == "pristine"


# --------------------------------------------------------------------------
# how the first run reaches it
# --------------------------------------------------------------------------


def test_the_work_goes_through_a_runner_and_off_the_main_loop(tmp_path, backend):
    """Five hundred reads and a file copy must not run in the click handler."""
    runner = ApplyRunner(None, threaded=False)

    handed_back = onboarding.ensure_pristine_point(
        object(), backend=backend, root=tmp_path, keys=[ACCENT], dests=[], runner=runner
    )

    assert handed_back is None, "the runner reports, not the caller"
    assert (tmp_path / PRISTINE_ID / "restore-point.json").is_file()


def test_a_failure_costs_the_row_and_nothing_else(tmp_path, backend, monkeypatch):
    def explode(*_args, **_kwargs):
        raise OSError("no room on the disk")

    monkeypatch.setattr(onboarding.restorepoints, "capture", explode)

    assert (
        onboarding.ensure_pristine_point(
            None, backend=backend, root=tmp_path, keys=[ACCENT], dests=[]
        )
        is None
    )


class _Prefs:
    """Just enough of ``Prefs`` for the first-run question."""

    def __init__(self, seen: bool = False) -> None:
        self.seen = seen

    def should_show_banner(self, _banner_id: str) -> bool:
        return not self.seen

    def mark_banner_seen(self, _banner_id: str) -> None:
        self.seen = True


class _Window:
    def __init__(self, prefs: _Prefs) -> None:
        self.prefs = prefs


def test_a_first_run_takes_the_moment_and_a_later_run_does_not(tmp_path, monkeypatch):
    calls: list[object] = []
    monkeypatch.setattr(
        onboarding, "ensure_pristine_point", lambda window, **kw: calls.append(kw)
    )
    monkeypatch.setattr(onboarding, "show_again", lambda window, **kw: "dialog")

    first_run = _Window(_Prefs(seen=False))
    assert onboarding.maybe_present(first_run, root=tmp_path) == "dialog"
    assert calls == [{"backend": None, "root": tmp_path}]

    # Ten launches later the desktop has been changed, and a snapshot of it is
    # not "before gtheme" any more. Nothing is taken.
    seen_it = _Window(_Prefs(seen=True))
    assert onboarding.maybe_present(seen_it, root=tmp_path) is None
    assert len(calls) == 1
