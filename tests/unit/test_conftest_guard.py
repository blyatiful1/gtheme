"""The guard that keeps the suite off the real desktop, testing itself.

The guard is the single most safety-critical thing in ``tests/``: it is what
stands between a ``mutating`` test and the desktop the developer is sitting in
front of. A guard that silently stopped working would look exactly like a suite
that passes.
"""

from __future__ import annotations

import os

import pytest
from _pytest.outcomes import Skipped

from tests.conftest import SEAM_ENV_VARS, SEAM_FIXTURES, _active_seams, enforce_isolation


def test_the_seam_variables_are_the_documented_ones():
    assert set(SEAM_ENV_VARS) == {
        "GTHEME_DEST_ROOT",
        "GTHEME_CONFIG_DIR",
        "GTHEME_STATE_DIR",
    }


def test_every_seam_fixture_exists():
    """A name in SEAM_FIXTURES with no fixture behind it would grant free passes."""
    import tests.conftest as conftest

    for name in SEAM_FIXTURES:
        assert hasattr(conftest, name), f"{name} is listed as a seam but has no fixture"


@pytest.mark.mutating
def test_a_mutating_test_with_a_seam_actually_runs(tmp_dest_root):
    """If the guard were too strict this test would be skipped, not passed."""
    assert os.environ["GTHEME_DEST_ROOT"] == str(tmp_dest_root)
    (tmp_dest_root / "proof").write_text("written inside the seam", encoding="utf-8")
    assert (tmp_dest_root / "proof").is_file()


@pytest.mark.mutating
def test_the_memory_backend_counts_as_a_seam(memory_settings):
    assert memory_settings is not None


class _FakeNode:
    def __init__(self, marker: bool) -> None:
        self._marker = marker

    def get_closest_marker(self, name: str):
        return object() if (name == "mutating" and self._marker) else None


class _FakeRequest:
    def __init__(self, fixturenames: tuple[str, ...], marker: bool = True) -> None:
        self.fixturenames = fixturenames
        self.node = _FakeNode(marker)


def test_no_seam_is_detected_when_nothing_isolates(monkeypatch):
    for name in SEAM_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    assert _active_seams(_FakeRequest(("tmp_path",))) == []


def test_env_seam_is_detected(monkeypatch, tmp_path):
    for name in SEAM_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GTHEME_DEST_ROOT", str(tmp_path))
    assert _active_seams(_FakeRequest(("tmp_path",))) == ["GTHEME_DEST_ROOT"]


@pytest.mark.parametrize("fixture_name", SEAM_FIXTURES)
def test_every_seam_fixture_is_detected_by_name(monkeypatch, fixture_name):
    """Checked by name because the autouse guard can run before the fixture.

    This is not hypothetical: checking only the environment made every
    ``config_dir``-seamed test skip while the summary line reported it as an
    ordinary skip, indistinguishable from a test that had nothing to run.
    """
    for name in SEAM_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    assert _active_seams(_FakeRequest((fixture_name,))) == [fixture_name]


@pytest.mark.mutating
def test_a_mutating_test_seamed_by_config_dir_actually_runs(config_dir):
    """The regression itself: this body must execute, not be skipped."""
    assert os.environ["GTHEME_CONFIG_DIR"] == str(config_dir)
    (config_dir / "proof").write_text("ran", encoding="utf-8")
    assert (config_dir / "proof").is_file()


def test_an_empty_env_var_does_not_count_as_a_seam(monkeypatch):
    """``GTHEME_DEST_ROOT=`` must not be mistaken for isolation."""
    for name in SEAM_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GTHEME_DEST_ROOT", "")
    assert _active_seams(_FakeRequest(("tmp_path",))) == []


def test_the_guard_skips_an_unseamed_mutating_test(monkeypatch):
    """The decisive case: marked, no seam, must not be allowed to run."""
    for name in SEAM_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(Skipped, match="no isolation seam"):
        enforce_isolation(_FakeRequest(("tmp_path",), marker=True))


def test_the_guard_lets_a_seamed_mutating_test_through(monkeypatch, tmp_path):
    for name in SEAM_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GTHEME_DEST_ROOT", str(tmp_path))
    enforce_isolation(_FakeRequest(("tmp_path",), marker=True))  # must not raise


def test_the_guard_ignores_unmarked_tests(monkeypatch):
    for name in SEAM_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    enforce_isolation(_FakeRequest(("tmp_path",), marker=False))  # must not raise
