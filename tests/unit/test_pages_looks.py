"""The Looks page: what it says, what it plans, and that it builds.

Marked ``gtk``: the page module imports libadwaita, so importing it at all
needs the stack. Nothing is presented and no window is mapped — the page is
constructed against a stand-in window and inspected. Every test that touches
settings runs against an in-memory backend, and every test that writes touches
only a temporary Looks folder.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for the Looks page")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from gtheme.core import restorepoints  # noqa: E402
from gtheme.core.backends import use_backend  # noqa: E402
from gtheme.core.settings_backend import MemoryBackend  # noqa: E402
from gtheme.core.transaction import TransactionError  # noqa: E402
from gtheme.panels.descriptor import Row, WidgetKind  # noqa: E402
from gtheme.panels.loader import Corpus, DomainDescriptor  # noqa: E402
from gtheme.prefs import Prefs  # noqa: E402
from gtheme.preset.loader import load  # noqa: E402
from gtheme.preset.model import Component  # noqa: E402
from gtheme.ui import jargon  # noqa: E402
from gtheme.ui.pages import looks  # noqa: E402

pytestmark = pytest.mark.gtk


@pytest.fixture(autouse=True, scope="module")
def _adw():
    if not Gtk.init_check():
        pytest.skip("no display is available for GTK — run under gtk4-broadwayd")
    Adw.init()


class FakeWindow:
    """Everything the page asks of the window it lives in, and nothing else."""

    def __init__(self, prefs: Prefs) -> None:
        self.prefs = prefs
        self.toasts = Adw.ToastOverlay()
        self.visited: list[str] = []

    def show_page(self, page_id: str) -> None:
        self.visited.append(page_id)


@pytest.fixture
def backend():
    with use_backend(MemoryBackend()) as memory:
        yield memory


@pytest.fixture
def themes_dir(tmp_path, monkeypatch):
    path = tmp_path / "themes"
    path.mkdir()
    monkeypatch.setenv("GTHEME_THEMES_DIR", str(path))
    return path


THEME_TOML = """
format = 2

[meta]
name = "{name}"
title = "{title}"
description = "A Look written by a test."
author = "tests"
version = "1.0.0"

[palette]
bg = "#101010"
accent = "#52E0A4"

[[settings]]
key = "gsettings:org.gnome.desktop.background picture-uri"
value = "'file:///usr/share/backgrounds/one.png'"
component = "wallpaper"

[extensions]
enable = ["nowhere@tests.local"]

[[extensions.install]]
uuid = "nowhere@tests.local"
source = "{source}"
"""


def write_look(directory, name="testlook", title="Test Look", source="local-only"):
    folder = directory / name
    folder.mkdir(parents=True)
    (folder / "theme.toml").write_text(
        THEME_TOML.format(name=name, title=title, source=source), encoding="utf-8"
    )
    return folder


# -- copy -----------------------------------------------------------------


def test_every_sentence_the_page_says_passes_the_jargon_lint():
    problems: list[str] = []
    for key, text in looks.COPY.items():
        problems.extend(jargon.check(text, where=f"COPY[{key}]"))
    for key, text in looks.BADGES.items():
        problems.extend(jargon.check(text, where=f"BADGES[{key}]"))
    assert problems == []


def test_the_safety_promise_is_the_one_security_makes_verbatim():
    """DESIGN.md A4: this sentence appears on the install surface, unchanged."""
    assert looks.COPY["safety"] == (
        "Looks only change settings. They can't run programs on your computer."
    )


def test_the_three_provenance_badges_are_the_ones_the_research_named():
    assert set(looks.BADGES.values()) == {"Built-in", "Yours", "From the community"}


# -- tiles ----------------------------------------------------------------


def test_a_loaded_look_becomes_a_tile_with_its_badge_and_palette(themes_dir):
    folder = write_look(themes_dir)
    tiles = looks.tiles_from_results([load(folder)])
    assert len(tiles) == 1
    tile = tiles[0]
    assert tile.title == "Test Look"
    assert tile.badge == "Yours"
    assert tile.palette["accent"] == "#52E0A4"
    assert not tile.broken


def test_a_broken_look_is_listed_as_broken_rather_than_hidden(themes_dir):
    """A Look that vanishes reads as a bug in gtheme, not a typo in the Look."""
    folder = themes_dir / "wrong"
    folder.mkdir()
    (folder / "theme.toml").write_text("format = 2\n", encoding="utf-8")
    tiles = looks.tiles_from_results([load(folder)])
    assert len(tiles) == 1
    assert tiles[0].broken
    assert tiles[0].problems


def test_a_looks_own_warnings_travel_with_its_tile(themes_dir):
    folder = write_look(themes_dir)
    result = load(folder)
    result.warnings.append("something will not apply")
    tile = looks.tiles_from_results([result])[0]
    assert tile.notes == ("something will not apply",)


# -- the preview plan ------------------------------------------------------


def test_the_plan_describes_the_change_in_the_users_words(themes_dir, backend):
    tile = looks.tiles_from_results([load(write_look(themes_dir))])[0]
    plan = looks.plan_apply(tile, installed=[])
    assert "Background picture" in plan.lines
    assert plan.transaction is not None


def test_a_private_add_on_that_is_absent_is_a_named_skip_not_an_error(themes_dir, backend):
    tile = looks.tiles_from_results([load(write_look(themes_dir))])[0]
    plan = looks.plan_apply(tile, installed=[])
    assert plan.missing_addons == 0, "a private add-on is never offered for download"
    assert any("private add-on" in warning for warning in plan.warnings)
    assert plan.warnings[0] in plan.body(), "the compiler's own wording, unchanged"


def test_an_add_on_from_the_library_that_is_absent_is_counted(themes_dir, backend):
    folder = write_look(themes_dir, source="ego")
    tile = looks.tiles_from_results([load(folder)])[0]
    plan = looks.plan_apply(tile, installed=[])
    assert plan.missing_addons == 1
    assert looks.COPY["missing-addons-one"] in plan.body()
    assert looks.COPY["missing-addons-note"] in plan.body()


def test_the_body_always_carries_the_safety_promise(themes_dir, backend):
    tile = looks.tiles_from_results([load(write_look(themes_dir))])[0]
    body = looks.plan_apply(tile, installed=[]).body()
    assert looks.COPY["safety"] in body
    assert looks.COPY["apply-safety"] in body


def test_a_look_that_changes_nothing_says_so(themes_dir, backend):
    """The setting is already at the Look's value, so there is nothing to do."""
    tile = looks.tiles_from_results([load(write_look(themes_dir))])[0]
    backend.set(
        "gsettings:org.gnome.desktop.background picture-uri",
        "'file:///usr/share/backgrounds/one.png'",
    )
    plan = looks.plan_apply(tile, installed=[])
    assert plan.nothing_to_do
    assert looks.COPY["nothing-to-do"] in plan.body()


WALLPAPER_KEY = "gsettings:org.gnome.desktop.background picture-uri"


@pytest.mark.mutating
def test_using_a_look_leaves_a_way_back(themes_dir, tmp_dest_root, state_dir, backend):
    """The page's whole promise, end to end: apply, then one click puts it back.

    Every write goes to an in-memory settings backend and a throwaway
    destination root, and the saved moment lands in a throwaway state folder —
    the real desktop is not involved at any point.
    """
    tile = looks.tiles_from_results([load(write_look(themes_dir))])[0]
    plan = looks.plan_apply(tile, installed=[])
    assert plan.transaction is not None

    narration: list[str] = []
    outcome = plan.transaction.apply(lambda _stage, text: narration.append(text))

    assert outcome.restore_point, "applying a Look must save the moment before it"
    assert narration, "applying a Look is narrated, never silent"
    assert backend.get(WALLPAPER_KEY) == "'file:///usr/share/backgrounds/one.png'"

    undone = restorepoints.apply_point(outcome.restore_point)
    assert undone.warnings == []
    assert backend.get(WALLPAPER_KEY) != "'file:///usr/share/backgrounds/one.png'"


def test_a_broken_look_cannot_be_planned(themes_dir):
    tile = looks.LookTile(
        name="x", title="X", description="", badge="Yours", directory=themes_dir, result=None
    )
    plan = looks.plan_apply(tile, installed=[])
    assert plan.transaction is None
    assert plan.problem


def test_a_look_whose_planning_fails_reports_it_instead_of_raising(themes_dir, monkeypatch):
    tile = looks.tiles_from_results([load(write_look(themes_dir))])[0]

    def boom(*_args, **_kwargs):
        raise RuntimeError("the store could not be read")

    monkeypatch.setattr(looks.Transaction, "plan", boom)
    plan = looks.plan_apply(tile, installed=[])
    assert plan.transaction is None
    assert "the store could not be read" in (plan.problem or "")


# -- failure wording -------------------------------------------------------


def test_a_rolled_back_failure_reassures():
    heading, body = looks.failure_text(TransactionError("no room left", rolled_back=True))
    assert heading == looks.COPY["failed-heading"]
    assert looks.COPY["failed-body"] in body
    assert "no room left" in body


def test_a_failure_that_could_not_be_undone_never_pretends_otherwise():
    heading, body = looks.failure_text(TransactionError("stopped half way", rolled_back=False))
    assert heading == looks.COPY["half-heading"]
    assert looks.COPY["half-body"] in body


# -- saving the current desktop -------------------------------------------


def test_a_typed_name_becomes_a_folder_name_a_look_can_have():
    assert looks.slugify("My Desktop!! 2") == "my-desktop-2"
    assert looks.slugify("  NIGHTBLOOM  ") == "nightbloom"
    assert looks.slugify("!!!") == ""
    assert looks.slugify("") == ""


def test_capture_covers_every_setting_the_app_can_describe():
    corpus = Corpus(
        domains=[
            DomainDescriptor(
                id="d",
                title="D",
                rows=[
                    Row(
                        schema_id="org.gnome.desktop.background",
                        key="picture-uri",
                        title="Background picture",
                        subtitle="The picture behind everything.",
                        kind=WidgetKind.TEXT,
                    ),
                    Row(
                        title="Open the add-on's own settings",
                        subtitle="Everything this add-on can do.",
                        kind=WidgetKind.LINK,
                        link_target="page:addons",
                    ),
                ],
            )
        ]
    )
    keys = looks.capture_keys(corpus)
    assert keys == ["gsettings:org.gnome.desktop.background picture-uri"]


def test_settings_are_filed_under_the_part_of_the_desktop_they_belong_to():
    assert looks.component_for_key(
        "gsettings:org.gnome.desktop.background picture-uri"
    ) is Component.WALLPAPER
    assert looks.component_for_key(
        "gsettings:org.gnome.desktop.interface font-name"
    ) is Component.FONTS
    assert looks.component_for_key(
        "gsettings:org.gnome.desktop.interface accent-color"
    ) is Component.COLORS
    assert looks.component_for_key(
        "gsettings:org.gnome.shell.extensions.blur-my-shell.panel blur"
    ) is Component.ADDONS
    assert looks.component_for_key("gsettings:com.example.thing key") is Component.OTHER
    assert looks.component_for_key(
        "gsettings-path:org.gnome.desktop.background:/x/ picture-uri"
    ) is Component.WALLPAPER


def test_the_add_ons_that_are_on_now_are_read_through_the_backend(backend):
    backend.set("gsettings:org.gnome.shell enabled-extensions", "['a@b', 'c@d']")
    assert looks.enabled_extension_uuids(backend) == ["a@b", "c@d"]


def test_no_session_means_no_add_ons_named_not_a_crash():
    class Refuses:
        def get(self, _key):
            raise RuntimeError("no session")

    assert looks.enabled_extension_uuids(Refuses()) == []


@pytest.mark.mutating
def test_saving_the_desktop_writes_a_look_that_loads_again(
    themes_dir, config_dir, memory_settings, backend
):
    page = looks.build(FakeWindow(Prefs()))
    result = page.save_current_desktop("my-desktop", "My Desktop")
    assert (themes_dir / "my-desktop" / "theme.toml").is_file()
    assert result.preset.meta.title == "My Desktop"

    page.reload()
    saved = [tile for tile in page._tiles if tile.name == "my-desktop"]
    assert saved and saved[0].badge == "Yours"


# -- the page itself -------------------------------------------------------


def test_the_page_builds_and_lists_the_bundled_looks(config_dir, themes_dir, backend):
    page = looks.build(FakeWindow(Prefs()))
    assert isinstance(page, Gtk.Widget)
    names = {tile.name for tile in page._tiles}
    assert {"magma", "netrunner", "nightbloom", "hyperclass"} <= names
    assert all(tile.badge == "Built-in" for tile in page._tiles)


def test_the_first_visit_explainer_shows_once_and_stays_dismissed(config_dir, themes_dir, backend):
    prefs = Prefs()
    window = FakeWindow(prefs)
    page = looks.build(window)
    assert page._banner.get_revealed()

    page._on_banner_dismissed(page._banner)
    assert not page._banner.get_revealed()
    assert prefs.banner_seen(looks.BANNER_ID)

    again = looks.build(FakeWindow(prefs))
    assert not again._banner.get_revealed()


def test_the_grid_holds_one_tile_per_look(config_dir, themes_dir, backend):
    page = looks.build(FakeWindow(Prefs()))
    children = []
    child = page._grid.get_first_child()
    while child is not None:
        children.append(child)
        child = child.get_next_sibling()
    assert len(children) == len(page._tiles)


def test_asking_for_the_missing_add_ons_goes_to_the_add_ons_page(
    config_dir, themes_dir, backend
):
    window = FakeWindow(Prefs())
    page = looks.build(window)
    tile = page._tiles[0]
    page._on_preview_response(
        Adw.AlertDialog(), "addons", tile, looks.ApplyPlan(title=tile.title, missing_addons=2)
    )
    assert window.visited == ["addons"]


def test_a_community_entry_with_no_picture_is_never_listed(config_dir, themes_dir, backend):
    """The publish rule: no screenshot, no listing."""
    page = looks.build(FakeWindow(Prefs()))
    document = json.dumps(
        {
            "version": 2,
            "themes": [
                {
                    "name": "seen",
                    "title": "Seen",
                    "description": "has a picture",
                    "author": "a",
                    "version": "1",
                    "screenshots": ["shot.png"],
                },
                {
                    "name": "unseen",
                    "title": "Unseen",
                    "description": "has none",
                    "author": "a",
                    "version": "1",
                    "screenshots": [],
                },
            ],
        }
    )
    from gtheme.preset.registry import parse_index

    page._on_index(parse_index(document), None)
    assert page._browse_stack.get_visible_child_name() == "results"
    titles = []
    child = page._browse_grid.get_first_child()
    while child is not None:
        # FlowBoxChild → Button → Box → [preview, title label, badge, …]
        column = child.get_child().get_child()
        titles.append(column.get_first_child().get_next_sibling().get_label())
        child = child.get_next_sibling()
    assert titles == ["Seen"]


def test_an_unreachable_community_list_says_so_and_offers_another_try(
    config_dir, themes_dir, backend
):
    page = looks.build(FakeWindow(Prefs()))
    page._on_index(None, "the list could not be downloaded")
    assert page._browse_stack.get_visible_child_name() == "error"
    assert page._browse_error.get_description() == "the list could not be downloaded"


def test_an_empty_community_list_teaches_instead_of_showing_nothing(
    config_dir, themes_dir, backend
):
    page = looks.build(FakeWindow(Prefs()))
    page._on_index([], None)
    assert page._browse_stack.get_visible_child_name() == "empty"


def test_a_destroyed_page_stops_answering_its_own_callbacks(config_dir, themes_dir, backend):
    """A worker thread landing after the page is gone must touch nothing."""
    page = looks.build(FakeWindow(Prefs()))
    page._on_destroy(page)
    assert page._alive is False
    page._on_index(None, "arrives too late")
    assert page._browse_stack.get_visible_child_name() != "error"
