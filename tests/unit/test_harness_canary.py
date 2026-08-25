"""The sandbox canary's pure logic, tested in the default tier.

The canary is what makes the sandbox tier safe to run on the machine it is
testing, and the sandbox tier is LOCAL ONLY — excluded from a plain ``pytest``
run and from CI entirely. That would leave the one piece of safety-critical
logic in this repository untested everywhere it actually gets run.

So the parts of ``tests/sandbox/canary.py`` that need no shell, no bus and no
desktop are exercised here, in the tier that always runs. Nothing in this file
touches the live session: every assertion is about a throwaway tree under
``tmp_path``, or about pure comparison of two snapshot objects.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

SANDBOX_DIR = Path(__file__).resolve().parents[1] / "sandbox"


def _load_canary() -> ModuleType:
    """Import ``tests/sandbox/canary.py`` without importing the sandbox tier.

    ``tests/sandbox`` is not a package and its directory only lands on
    ``sys.path`` when pytest collects the sandbox tier — which, by design, it
    usually does not. Loading the file directly keeps this test independent of
    collection order and of whether the sandbox marker was selected.
    """
    path = SANDBOX_DIR / "canary.py"
    spec = importlib.util.spec_from_file_location("gtheme_sandbox_canary", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


canary = _load_canary()


def test_the_watched_paths_are_the_ones_the_design_names():
    """DESIGN.md F6 lists five trees. Losing one would be a silent hole."""
    assert canary.LIVE_TREES == (
        ".local/share/gnome-shell/extensions",
        ".local/share/gnome-shell/extension-updates",
        ".local/share/backgrounds",
        ".local/state/gtheme",
        "nightbloom/ghostty",
    )


def test_an_identical_tree_hashes_identically(tmp_path: Path):
    for name in ("a", "b"):
        root = tmp_path / name
        (root / "deep" / "deeper").mkdir(parents=True)
        (root / "deep" / "file.txt").write_text("same", encoding="utf-8")
        (root / "top.bin").write_bytes(b"\x00\x01\x02")
    assert canary.tree_hash(tmp_path / "a") == canary.tree_hash(tmp_path / "b")


def test_a_missing_tree_is_absent_not_empty(tmp_path: Path):
    """An absent directory and an empty one must not hash the same.

    Otherwise deleting ``~/.local/state/gtheme`` — which holds every restore
    point — would look exactly like leaving it alone.
    """
    empty = tmp_path / "empty"
    empty.mkdir()
    assert canary.tree_hash(tmp_path / "gone") == canary.ABSENT
    assert canary.tree_hash(empty) != canary.ABSENT


def test_content_changes_are_caught(tmp_path: Path):
    root = tmp_path / "tree"
    root.mkdir()
    target = root / "f"
    target.write_text("before", encoding="utf-8")
    before = canary.tree_hash(root)
    target.write_text("after!", encoding="utf-8")  # same length, different bytes
    assert canary.tree_hash(root) != before


def test_renames_are_caught(tmp_path: Path):
    """The path is part of the digest, so moving a file is a change."""
    root = tmp_path / "tree"
    root.mkdir()
    (root / "one").write_text("x", encoding="utf-8")
    before = canary.tree_hash(root)
    (root / "one").rename(root / "two")
    assert canary.tree_hash(root) != before


def test_symlinks_are_recorded_but_never_followed(tmp_path: Path):
    """``~/.config/ghostty`` is a symlink into another repository.

    Following it would hash the target tree twice and, worse, would make
    *replacing the link itself* invisible — which is exactly the operation the
    ghostty adapter is allowed to perform only with consent.
    """
    root = tmp_path / "tree"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("original", encoding="utf-8")
    (root / "link").symlink_to(outside)

    before = canary.tree_hash(root)
    (outside / "secret").write_text("changed", encoding="utf-8")
    assert canary.tree_hash(root) == before, "the walk followed the symlink"

    (root / "link").unlink()
    (root / "link").symlink_to(tmp_path / "elsewhere")
    assert canary.tree_hash(root) != before, "a re-pointed symlink went unnoticed"


def test_a_single_file_hashes_as_itself(tmp_path: Path):
    path = tmp_path / "file"
    path.write_text("hello", encoding="utf-8")
    first = canary.tree_hash(path)
    assert first != canary.ABSENT
    path.write_text("world", encoding="utf-8")
    assert canary.tree_hash(path) != first


def test_identical_snapshots_compare_equal():
    snap = canary.Snapshot(
        dconf_mtime_ns=7, dconf_size=3, enabled_extensions="['a']", trees={"t": "hash"}
    )
    assert snap.differences(snap) == []
    canary.assert_unchanged(snap, snap)  # must not raise


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("dconf_mtime_ns", 8, "dconf store was written"),
        ("dconf_size", 4, "live dconf store size"),
        ("enabled_extensions", "['a', 'b']", "enabled-extensions changed"),
    ],
)
def test_each_watched_field_is_reported_by_name(field: str, value: object, expected: str):
    """A failure has to say what leaked; "something changed" is not actionable."""
    before = canary.Snapshot(
        dconf_mtime_ns=7, dconf_size=3, enabled_extensions="['a']", trees={"t": "hash"}
    )
    after = canary.Snapshot(
        **{
            **{
                "dconf_mtime_ns": before.dconf_mtime_ns,
                "dconf_size": before.dconf_size,
                "enabled_extensions": before.enabled_extensions,
                "trees": before.trees,
            },
            field: value,
        }
    )
    with pytest.raises(AssertionError, match=expected):
        canary.assert_unchanged(before, after)


def test_a_tree_appearing_or_vanishing_is_a_difference():
    present = canary.Snapshot(
        dconf_mtime_ns=1, dconf_size=1, enabled_extensions="[]", trees={"t": "abc"}
    )
    gone = canary.Snapshot(
        dconf_mtime_ns=1, dconf_size=1, enabled_extensions="[]", trees={"t": canary.ABSENT}
    )
    assert present.differences(gone)
    assert gone.differences(present)


def test_a_missing_dconf_store_is_not_mistaken_for_an_unchanged_one():
    """``None`` means "no store file". It must not compare equal to a real one."""
    missing = canary.Snapshot(
        dconf_mtime_ns=None, dconf_size=None, enabled_extensions="[]", trees={}
    )
    present = canary.Snapshot(
        dconf_mtime_ns=1, dconf_size=1, enabled_extensions="[]", trees={}
    )
    assert missing.differences(present)


def test_the_live_dconf_path_follows_xdg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert canary.live_dconf_path() == tmp_path / "dconf" / "user"
    monkeypatch.delenv("XDG_CONFIG_HOME")
    assert canary.live_dconf_path() == Path.home() / ".config" / "dconf" / "user"
