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

from tests.conftest import (
    _AUTO_STATE_DIR,
    SEAM_ENV_VARS,
    SEAM_FIXTURES,
    _active_seams,
    _fingerprint,
    enforce_isolation,
    live_state_dir,
)


def test_the_seam_variables_are_the_documented_ones():
    assert set(SEAM_ENV_VARS) == {
        "GTHEME_DEST_ROOT",
        "GTHEME_CONFIG_DIR",
        "GTHEME_STATE_DIR",
        "GTHEME_CACHE_DIR",
        "GTHEME_EXTENSION_UPDATES_DIR",
    }


def test_every_seam_fixture_exists():
    """A name in SEAM_FIXTURES with no fixture behind it would grant free passes.

    Seams live in two files: the shared ones here, and the sandbox sessions in
    ``tests/sandbox/conftest.py`` and the modules that build their own. A name
    has to be a real fixture in one of them.
    """
    import ast
    from pathlib import Path

    import tests.conftest as conftest

    tests_dir = Path(conftest.__file__).parent
    defined: set[str] = set()
    for path in [tests_dir / "conftest.py", *sorted((tests_dir / "sandbox").glob("*.py"))]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for deco in node.decorator_list:
                target = deco.func if isinstance(deco, ast.Call) else deco
                if isinstance(target, ast.Attribute) and target.attr == "fixture":
                    defined.add(node.name)

    missing = [name for name in SEAM_FIXTURES if name not in defined]
    assert not missing, f"listed as seams but no fixture defines them: {missing}"


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


# -- the quarantined state directory ---------------------------------------


def test_every_test_gets_a_throwaway_state_root(request):
    """The safety net itself: no test runs with the real v2 state directory."""
    from gtheme.core import paths

    quarantined = getattr(request.node, _AUTO_STATE_DIR)
    assert os.environ["GTHEME_STATE_DIR"] == quarantined
    assert paths.state_dir() != live_state_dir()
    assert not paths.state_dir().is_relative_to(live_state_dir().parent)


def test_the_net_the_harness_hung_is_not_evidence_of_isolation(monkeypatch, tmp_path):
    """A state root nobody asked for must not let a mutating test through.

    Otherwise the quarantine would have quietly disarmed the guard it was
    added to reinforce.
    """
    for name in SEAM_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GTHEME_STATE_DIR", str(tmp_path))
    request = _FakeRequest(("tmp_path",))
    setattr(request.node, _AUTO_STATE_DIR, str(tmp_path))

    assert _active_seams(request) == []
    with pytest.raises(Skipped, match="no isolation seam"):
        enforce_isolation(request)


def test_a_state_root_the_test_chose_is_still_a_seam(monkeypatch, tmp_path):
    for name in SEAM_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GTHEME_STATE_DIR", str(tmp_path / "chosen"))
    request = _FakeRequest(("tmp_path",))
    setattr(request.node, _AUTO_STATE_DIR, str(tmp_path / "automatic"))

    assert _active_seams(request) == ["GTHEME_STATE_DIR"]


def test_the_state_dir_fixture_still_wins_over_the_quarantine(state_dir, request):
    """An explicit seam beats the automatic one, or the seam would be a lie."""
    assert os.environ["GTHEME_STATE_DIR"] == str(state_dir)
    assert os.environ["GTHEME_STATE_DIR"] != getattr(request.node, _AUTO_STATE_DIR)


# -- the end-of-run photograph ----------------------------------------------


def test_the_photograph_notices_a_new_file(tmp_path):
    before = _fingerprint(tmp_path)
    (tmp_path / "restore-point.json").write_text("{}", encoding="utf-8")
    assert _fingerprint(tmp_path) != before


def test_the_photograph_notices_rewritten_contents(tmp_path):
    target = tmp_path / "ownership.json"
    target.write_text("{}", encoding="utf-8")
    before = _fingerprint(tmp_path)
    target.write_text('{"nightbloom": {}}', encoding="utf-8")
    assert _fingerprint(tmp_path) != before


def test_the_photograph_of_an_absent_directory_is_empty_not_an_error(tmp_path):
    """A machine that has never run gtheme is normal, not a failure."""
    assert _fingerprint(tmp_path / "never-existed") == {}


def test_the_photograph_is_stable_when_nothing_happens(tmp_path):
    (tmp_path / "lock").write_text("", encoding="utf-8")
    assert _fingerprint(tmp_path) == _fingerprint(tmp_path)


def test_the_live_state_dir_is_the_real_one_not_the_quarantined_one():
    """It must not read GTHEME_STATE_DIR, or it would photograph the tmpdir."""
    assert live_state_dir().parts[-2:] == ("gtheme", "v2")
    assert str(live_state_dir()) != os.environ["GTHEME_STATE_DIR"]
