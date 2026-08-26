"""App preferences: round-trip, isolation seam, and the one-shot banners."""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path

import pytest

from gtheme.prefs import KNOWN_BANNERS, Prefs, default_prefs_path
from gtheme.prefs import config_dir as prefs_config_dir


def test_env_override_wins(config_dir):
    """``GTHEME_CONFIG_DIR`` is the seam every other test in this file rests on."""
    assert prefs_config_dir() == config_dir


def test_default_path_is_under_the_config_dir(config_dir):
    assert default_prefs_path() == config_dir / "prefs.json"


def test_xdg_config_home_is_used_when_there_is_no_override(tmp_path, monkeypatch):
    monkeypatch.delenv("GTHEME_CONFIG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert prefs_config_dir() == tmp_path / "gtheme"


@pytest.mark.mutating
def test_round_trip(config_dir):
    prefs = Prefs()
    prefs.set("last-page", "wallpaper")
    prefs.set("window-width", 1234)

    reloaded = Prefs()
    assert reloaded.get("last-page") == "wallpaper"
    assert reloaded.get("window-width") == 1234


@pytest.mark.mutating
def test_writes_land_in_the_seam_directory_not_the_real_home(config_dir):
    Prefs().set("last-page", "home")
    assert (config_dir / "prefs.json").is_file()
    assert os.environ["GTHEME_CONFIG_DIR"] == str(config_dir)


@pytest.mark.mutating
def test_the_file_is_readable_json(config_dir):
    Prefs().set("a", {"nested": [1, 2]})
    data = json.loads((config_dir / "prefs.json").read_text(encoding="utf-8"))
    assert data == {"a": {"nested": [1, 2]}}


def test_missing_file_yields_defaults(config_dir):
    assert Prefs().get("never-set", "fallback") == "fallback"


@pytest.mark.mutating
def test_a_corrupt_file_does_not_stop_the_app(config_dir):
    (config_dir / "prefs.json").write_text("{not json at all", encoding="utf-8")
    prefs = Prefs()
    assert prefs.get("anything") is None
    prefs.set("recovered", True)
    assert Prefs().get("recovered") is True


@pytest.mark.mutating
def test_unset_forgets(config_dir):
    prefs = Prefs()
    prefs.set("temp", 1)
    assert prefs.unset("temp") is True
    assert prefs.unset("temp") is False
    assert Prefs().get("temp") is None


@pytest.mark.mutating
def test_no_temp_files_are_left_behind(config_dir):
    prefs = Prefs()
    for i in range(5):
        prefs.set(f"k{i}", i)
    leftovers = [p.name for p in config_dir.iterdir() if p.name != "prefs.json"]
    assert leftovers == []


# -- one-shot banners ------------------------------------------------------


@pytest.mark.mutating
def test_a_banner_is_shown_once(config_dir):
    prefs = Prefs()
    assert prefs.should_show_banner("first-visit-looks") is True
    prefs.mark_banner_seen("first-visit-looks")
    assert prefs.should_show_banner("first-visit-looks") is False
    assert Prefs().banner_seen("first-visit-looks") is True


@pytest.mark.mutating
def test_banners_are_independent(config_dir):
    prefs = Prefs()
    prefs.mark_banner_seen("first-visit-looks")
    assert prefs.should_show_banner("first-visit-addons") is True


@pytest.mark.mutating
def test_reset_banners_shows_them_all_again(config_dir):
    prefs = Prefs()
    prefs.mark_banner_seen("first-visit-looks")
    prefs.mark_banner_seen("first-visit-addons")
    prefs.set("last-page", "home")

    assert prefs.reset_banners() == 2
    assert prefs.should_show_banner("first-visit-looks") is True
    # Resetting explainers must not forget everything else.
    assert prefs.get("last-page") == "home"


def test_explicit_path_beats_the_env_seam(tmp_path, config_dir):
    elsewhere = tmp_path / "elsewhere.json"
    prefs = Prefs(elsewhere)
    prefs.set("k", "v")
    assert elsewhere.is_file()
    assert not (config_dir / "prefs.json").exists()


# -- the banner registry ----------------------------------------------------


def _banner_ids_used_in_source(src: Path) -> dict[str, str]:
    """Every banner id the app actually shows, to the file that shows it.

    Read out of the syntax tree rather than by grepping, so a string that
    merely looks like a banner id ("first-visit" in a copy table, say) is not
    mistaken for one. An id counts when it is:

    * assigned to a name ending in ``BANNER_ID``,
    * passed as a ``banner_id=`` keyword, or
    * the first argument to one of the three banner methods.
    """
    calls = {"should_show_banner", "mark_banner_seen", "banner_seen"}
    found: dict[str, str] = {}

    def record(node: ast.AST, where: str) -> None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.setdefault(node.value, where)

    for path in sorted(src.rglob("*.py")):
        if path.name == "prefs.py":
            continue  # the registry itself is the other side of the comparison
        where = str(path.relative_to(src))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.upper().endswith("BANNER_ID"):
                        record(node.value, where)
            elif isinstance(node, ast.Call):
                for keyword in node.keywords:
                    if keyword.arg == "banner_id":
                        record(keyword.value, where)
                function = node.func
                if isinstance(function, ast.Attribute) and function.attr in calls and node.args:
                    record(node.args[0], where)
    return found


def test_known_banners_is_exactly_what_the_pages_show(repo_root):
    """Both directions, because both are real failures.

    An id a page shows and this list does not name is an explainer that "show
    all explainers again" would not bring back — the user asks for their
    explanations and gets some of them. An id this list names and no page shows
    is a promise about a banner that does not exist.
    """
    used = _banner_ids_used_in_source(repo_root / "src" / "gtheme")

    missing = sorted(set(used) - KNOWN_BANNERS)
    assert missing == [], (
        "these banner ids are shown but not listed in prefs.KNOWN_BANNERS: "
        + ", ".join(f"{name} ({used[name]})" for name in missing)
    )
    unused = sorted(KNOWN_BANNERS - set(used))
    assert unused == [], f"prefs.KNOWN_BANNERS names banners nothing shows: {unused}"


def test_every_page_that_can_show_a_banner_is_covered(repo_root):
    """A sanity floor under the test above: it must be finding things at all.

    A collector that silently matched nothing would make the equality assertion
    pass by being vacuous on both sides.
    """
    used = _banner_ids_used_in_source(repo_root / "src" / "gtheme")
    assert len(used) >= 13, sorted(used)
    assert "first-visit-home" in used
    assert "onboarding-complete" in used
