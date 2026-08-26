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


def _descendants(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from _descendants(child)
        child = child.get_next_sibling()


def test_a_tile_asks_for_a_tiles_worth_of_width_not_a_screenshots(
    config_dir, themes_dir, backend
):
    """Why the grid was one tile per row, and the fix for it.

    A bundled Look ships a real screenshot, and ``Gtk.Picture`` reports the
    picture's own width as its natural size — 2561px for a 1440p shot, passed
    straight through by ``Gtk.AspectFrame``. ``Gtk.FlowBox`` lays out lines from
    what its children say they naturally want, so it put one tile per line and
    centred a 320px preview in the middle of it, which is exactly what the
    screenshots showed. Measuring the tile is the property that matters; how
    many end up on a line is then arithmetic the toolkit does.
    """
    page = looks.build(FakeWindow(Prefs()))
    assert page._tiles, "no Looks to measure"

    child = page._grid.get_first_child()
    widest = 0
    while child is not None:
        widest = max(widest, child.measure(Gtk.Orientation.HORIZONTAL, -1).natural)
        child = child.get_next_sibling()

    # The clamp plus the button's own padding; nowhere near a screenshot.
    assert widest <= looks.TILE_WIDTH + 40, widest


def test_a_tiles_description_is_ellipsized_rather_than_cut_mid_word(
    config_dir, themes_dir, backend
):
    page = looks.build(FakeWindow(Prefs()))
    inscriptions = [
        widget for widget in _descendants(page._grid) if isinstance(widget, Gtk.Inscription)
    ]
    assert inscriptions, "no Look on this grid describes itself"
    assert all(
        widget.get_text_overflow() == Gtk.InscriptionOverflow.ELLIPSIZE_END
        for widget in inscriptions
    )


def test_a_community_tile_is_held_to_the_same_width_and_ellipsis(
    config_dir, themes_dir, backend
):
    """The two grids are built by different methods; both had the same bug."""
    page = looks.build(FakeWindow(Prefs()))
    entry = Entry("seaglass")
    entry.description = "A very long sentence about a Look, going on and on and on and on."
    entry.screenshots = ()
    tile = page._community_tile(entry)

    assert tile.measure(Gtk.Orientation.HORIZONTAL, -1).natural <= looks.TILE_WIDTH + 40
    inscriptions = [
        widget for widget in _descendants(tile) if isinstance(widget, Gtk.Inscription)
    ]
    assert inscriptions and all(
        widget.get_text_overflow() == Gtk.InscriptionOverflow.ELLIPSIZE_END
        for widget in inscriptions
    )
    assert entry.description in (tile.get_tooltip_text() or "")


def test_the_second_button_still_just_opens_the_add_ons_page(
    config_dir, themes_dir, backend
):
    """"Get the missing ones" is the offer; "Open Add-ons" is still there."""
    window = FakeWindow(Prefs())
    page = looks.build(window)
    tile = page._tiles[0]
    page._on_preview_response(
        Adw.AlertDialog(),
        "open-addons",
        tile,
        looks.ApplyPlan(title=tile.title, missing_addons=2),
    )
    assert window.visited == ["addons"]


def test_with_no_desktop_to_add_to_it_says_so_and_offers_the_page(
    config_dir, themes_dir, backend
):
    """The honest fallback. No desktop means no add-ons, and saying which."""
    window = FakeWindow(Prefs())
    page = looks.build(window)
    tile = page._tiles[0]
    page._on_preview_response(
        Adw.AlertDialog(), "addons", tile, looks.ApplyPlan(title=tile.title, missing_addons=2)
    )
    assert window.visited == ["addons"]


# -- adding what a Look needs, as one change -------------------------------


class FakeInstaller:
    """An installer that installs nothing and reports what it was asked."""

    def __init__(self, *, present=(), fails=()) -> None:
        self.present = set(present)
        self.fails = set(fails)
        self.asked: list[tuple[str, int]] = []
        self.client = object()

    def plan_for_look(self, wanted, *, label=None):
        from gtheme.core.transaction import ExtensionEnable, Transaction
        from gtheme.ego.install import COPY, InstallOutcome, InstallReport

        ops, missing = [], []
        for uuid, source, alternates in wanted:
            if uuid in self.present:
                ops.append(ExtensionEnable(uuid=uuid, alternates=alternates))
                continue
            outcome = (
                InstallOutcome.LOCAL_ONLY_MISSING
                if source == "local-only"
                else InstallOutcome.NEEDS_RELOGIN
            )
            missing.append(InstallReport(uuid, outcome, COPY[outcome]))
        return Transaction(ops, label=label), missing

    def install_package(self, uuid, version_tag, callback, *, alternates=(), label=None):
        from gtheme.ego.install import COPY, InstallOutcome, InstallReport, enable_transaction

        self.asked.append((uuid, version_tag))
        if uuid in self.fails:
            callback(
                InstallReport(uuid, InstallOutcome.FAILED, COPY["download-failed"], via="package")
            )
            return
        callback(
            InstallReport(
                uuid,
                InstallOutcome.NEEDS_RELOGIN,
                COPY[InstallOutcome.NEEDS_RELOGIN],
                via="package",
                transaction=enable_transaction([uuid], label=label),
            )
        )


class FakeRecord:
    def __init__(self, tag: int | None = 7, supported: bool = True) -> None:
        self.tag = tag
        self.supported = supported

    def supports(self, _version: str) -> bool:
        return self.supported

    def version_tag_for(self, _version: str) -> int | None:
        return self.tag


class FakeLibrary:
    def __init__(self, records: dict) -> None:
        self.records = records

    def info(self, uuid, callback):
        callback(self.records.get(uuid), None)


def test_a_look_that_needs_three_add_ons_is_one_change_not_three():
    """The whole reason this is a batch: one restore point, all or nothing."""
    installer = FakeInstaller(present={"here@x"})
    library = FakeLibrary({"a@x": FakeRecord(), "b@x": FakeRecord()})
    batch = looks.AddonBatch(installer, library, shell_version="50.4", label="MAGMA")

    landed = {}
    batch.run(
        [("here@x", "ego", ()), ("a@x", "ego", ()), ("b@x", "ego", ())],
        lambda transaction, problems: landed.update(t=transaction, p=problems),
    )

    assert [uuid for uuid, _tag in installer.asked] == ["a@x", "b@x"]
    assert landed["p"] == []
    uuids = sorted(op.uuid for op in landed["t"].ops)
    assert uuids == ["a@x", "b@x", "here@x"]
    assert landed["t"].label == "MAGMA"


def test_a_private_add_on_that_is_absent_is_a_named_skip_not_a_failure():
    installer = FakeInstaller()
    batch = looks.AddonBatch(installer, FakeLibrary({}), shell_version="50.4")

    landed = {}
    batch.run([("mine@local", "local-only", ())], lambda t, p: landed.update(t=t, p=p))

    assert installer.asked == [], "a private add-on must never be downloaded"
    assert [report.uuid for report in landed["p"]] == ["mine@local"]
    assert "private add-on" in landed["p"][0].message


def test_an_add_on_with_no_build_for_this_desktop_is_refused_before_it_is_fetched():
    installer = FakeInstaller()
    library = FakeLibrary({"old@x": FakeRecord(supported=False)})
    batch = looks.AddonBatch(installer, library, shell_version="50.4")

    landed = {}
    batch.run([("old@x", "ego", ())], lambda t, p: landed.update(t=t, p=p))

    assert installer.asked == []
    assert landed["p"][0].outcome.value == "not-compatible"


def test_one_add_on_that_will_not_download_does_not_lose_the_others():
    installer = FakeInstaller(fails={"broken@x"})
    library = FakeLibrary({"broken@x": FakeRecord(), "fine@x": FakeRecord()})
    batch = looks.AddonBatch(installer, library, shell_version="50.4")

    landed = {}
    batch.run(
        [("broken@x", "ego", ()), ("fine@x", "ego", ())],
        lambda t, p: landed.update(t=t, p=p),
    )

    assert [report.uuid for report in landed["p"]] == ["broken@x"]
    assert [op.uuid for op in landed["t"].ops] == ["fine@x"]


def test_the_outcome_sentences_are_the_installer_s_own(config_dir, themes_dir, backend):
    """Never re-worded here. "after you log out" is the whole point of it."""
    from gtheme.ego.install import COPY as EGO_COPY
    from gtheme.ego.install import InstallOutcome

    page = looks.build(FakeWindow(Prefs()))
    installer = FakeInstaller()
    batch = looks.AddonBatch(installer, FakeLibrary({}), shell_version="50.4")
    landed = {}
    batch.run([("mine@local", "local-only", ())], lambda t, p: landed.update(t=t, p=p))

    dialog = _capture_dialog(page, lambda: page._report_addons(landed["p"]))
    assert EGO_COPY[InstallOutcome.LOCAL_ONLY_MISSING] in dialog.get_body()


def test_a_plan_names_the_add_ons_it_is_missing_not_just_how_many(
    config_dir, themes_dir, backend, monkeypatch
):
    """The count was all Wave 2 had; the batch needs the list."""
    from gtheme.core.transaction import ExtensionInstall

    page = looks.build(FakeWindow(Prefs()))
    tile = next(tile for tile in page._tiles if not tile.broken)
    plan = looks.plan_apply(tile, installed=[])
    for uuid, source, alternates in plan.missing:
        assert isinstance(uuid, str) and source in {"ego", "local-only"}
        assert alternates == ()
    assert plan.missing_addons == len(plan.missing)
    assert plan.missing_addons == sum(
        1 for op in plan.transaction.ops if isinstance(op, ExtensionInstall)
    )


# -- somebody else's Look wanting a name that is already used --------------


class Entry:
    def __init__(self, name: str) -> None:
        self.name = name
        self.title = name.upper()
        self.description = "a look"


def test_getting_a_look_whose_name_is_free_does_not_ask_anything(
    config_dir, themes_dir, backend, monkeypatch
):
    page = looks.build(FakeWindow(Prefs()))
    started = []
    monkeypatch.setattr(page, "_download", lambda entry, **kw: started.append((entry.name, kw)))
    page._on_community_response(Adw.AlertDialog(), "get", Entry("nobody-has-this"))
    assert started == [("nobody-has-this", {})]


def test_getting_a_look_named_like_one_you_have_asks_first(
    config_dir, themes_dir, backend, monkeypatch
):
    (themes_dir / "seaglass").mkdir()
    (themes_dir / "seaglass" / "theme.toml").write_text(THEME_TOML, encoding="utf-8")

    page = looks.build(FakeWindow(Prefs()))
    started = []
    monkeypatch.setattr(page, "_download", lambda entry, **kw: started.append(entry.name))

    dialog = _capture_dialog(
        page, lambda: page._on_community_response(Adw.AlertDialog(), "get", Entry("seaglass"))
    )
    assert started == [], "it downloaded before asking"
    assert "SEAGLASS" in dialog.get_heading()
    assert looks.COPY["replace-yours"] in dialog.get_body()

    dialog.emit("response", "replace")
    assert started == ["seaglass"]


def test_saying_keep_what_i_have_downloads_nothing(
    config_dir, themes_dir, backend, monkeypatch
):
    (themes_dir / "seaglass").mkdir()
    (themes_dir / "seaglass" / "theme.toml").write_text(THEME_TOML, encoding="utf-8")

    page = looks.build(FakeWindow(Prefs()))
    started = []
    monkeypatch.setattr(page, "_download", lambda entry, **kw: started.append(entry.name))

    dialog = page._confirm_replace(Entry("seaglass"), "yours")
    dialog.emit("response", "keep")
    assert started == []


def test_shadowing_a_built_in_look_says_hidden_rather_than_gone(
    config_dir, themes_dir, backend
):
    """Different consequence, different sentence. One destroys, one hides."""
    page = looks.build(FakeWindow(Prefs()))
    dialog = page._confirm_replace(Entry("magma"), "built-in")
    assert looks.COPY["replace-built-in"] in dialog.get_body()
    assert looks.COPY["replace-yours"] not in dialog.get_body()


def _capture_dialog(page, action):
    """Run something that presents a dialog and hand the dialog back."""
    seen = []
    original = Adw.AlertDialog.present

    def spy(self, *args):
        seen.append(self)

    Adw.AlertDialog.present = spy
    try:
        action()
    finally:
        Adw.AlertDialog.present = original
    assert seen, "nothing was presented"
    return seen[-1]


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
        # The first label under a tile is its title. Found rather than walked
        # to: the tile's boxes are a layout detail and have changed once
        # already, and this test is about which Looks are listed.
        label = next(
            widget for widget in _descendants(child) if isinstance(widget, Gtk.Label)
        )
        titles.append(label.get_label())
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


# -- getting a Look somebody else published ---------------------------------
#
# CONTRACT CHANGED BY RULING (Wave-2 gate, R11): "Downloading a Look from other
# people isn't built yet" is gone, and so is the dialog that said it. No network
# here either — the page is handed a fetcher that answers out of a dict.


COMMUNITY_TOML = """\
format = 2

[meta]
name = "seaglass"
title = "Seaglass"
description = "A quiet green."
author = "somebody"
version = "1.0.0"
screenshots = ["shot.png"]

[[settings]]
key = "gsettings:org.gnome.desktop.interface accent-color"
value = "'green'"
component = "colors"
"""


def _community_entry():
    from gtheme.preset.registry import IndexEntry

    return IndexEntry(
        name="seaglass",
        title="Seaglass",
        description="A quiet green.",
        author="somebody",
        version="1.0.0",
        screenshots=["shot.png"],
        provenance="community",
    )


def _served(monkeypatch, into, routes):
    """Point the page's fetch at a dict of recorded addresses."""
    from gtheme.preset import registry as look_registry

    def fake(url, on_done, _timeout):
        tail = url.rsplit("/main/themes/", 1)[-1]
        if tail in routes:
            on_done(routes[tail].encode() if isinstance(routes[tail], str) else routes[tail], None)
        else:
            on_done(None, "it is not available right now (404)")

    real = look_registry.fetch_look_async  # captured before the patch replaces it

    def fetch_look_async(entry, on_done, **kwargs):
        kwargs.setdefault("into", into)
        kwargs["fetch"] = fake
        return real(entry, on_done, **kwargs)

    monkeypatch.setattr(looks.look_registry, "fetch_look_async", fetch_look_async)


def test_getting_a_community_look_installs_it_and_shows_it(
    config_dir, themes_dir, backend, monkeypatch
):
    _served(
        monkeypatch,
        themes_dir,
        {"seaglass/theme.toml": COMMUNITY_TOML, "seaglass/shot.png": b"pretend png"},
    )
    window = FakeWindow(Prefs())
    page = looks.build(window)
    assert "seaglass" not in [tile.name for tile in page._tiles], "nothing installed yet"

    page._download(_community_entry())

    assert (themes_dir / "seaglass" / "theme.toml").is_file()
    assert "seaglass" in [tile.name for tile in page._tiles], "the grid was not reloaded"
    assert page._stack.get_visible_child_name() == "installed"


def test_a_downloaded_look_is_badged_as_somebody_elses_not_as_yours(
    config_dir, themes_dir, backend, monkeypatch
):
    """It lands in the same folder as a Look the user made themselves."""
    _served(monkeypatch, themes_dir, {"seaglass/theme.toml": COMMUNITY_TOML})
    page = looks.build(FakeWindow(Prefs()))
    page._download(_community_entry())

    tile = next(tile for tile in page._tiles if tile.name == "seaglass")
    assert tile.badge == looks.BADGES["community"]


def test_a_download_that_fails_says_so_and_installs_nothing(
    config_dir, themes_dir, backend, monkeypatch
):
    _served(monkeypatch, themes_dir, {})  # nothing published at that address
    page = looks.build(FakeWindow(Prefs()))
    page._download(_community_entry())

    assert list(themes_dir.iterdir()) == []
    assert "seaglass" not in [tile.name for tile in page._tiles]


def test_a_destroyed_page_does_not_finish_a_download_it_started(
    config_dir, themes_dir, backend, monkeypatch
):
    """The liveness rule every async landing point on this page obeys."""
    _served(monkeypatch, themes_dir, {"seaglass/theme.toml": COMMUNITY_TOML})
    page = looks.build(FakeWindow(Prefs()))
    page._alive = False
    page._download(_community_entry())
    assert "seaglass" not in [tile.name for tile in page._tiles]


def test_every_sentence_about_getting_a_look_passes_the_jargon_lint():
    for key in ("browse-get", "browse-getting", "browse-get-failed", "browse-got"):
        assert jargon.check(looks.COPY[key], where=f"COPY[{key}]") == []


# -- regression: the confirmed review findings on this page ----------------


class DeferredLibrary:
    """A library whose answer arrives on the main loop, like the real one.

    ``EgoClient.info`` and ``EgoClient.download`` both go through
    ``send_and_read_async``, whose callback lands on a later turn of the GLib
    main loop. Every fake in this file answers inline, which is exactly why the
    async bug survived the test suite.
    """

    def __init__(self, records: dict) -> None:
        self.records = records

    def info(self, uuid, callback):
        from gi.repository import GLib

        def later() -> bool:
            callback(self.records.get(uuid), None)
            return GLib.SOURCE_REMOVE

        GLib.idle_add(later)


class DeferredInstaller(FakeInstaller):
    """An installer whose download also finishes on a later main-loop turn."""

    def install_package(self, uuid, version_tag, callback, *, alternates=(), label=None):
        from gi.repository import GLib

        def later() -> bool:
            FakeInstaller.install_package(
                self, uuid, version_tag, callback, alternates=alternates, label=label
            )
            return GLib.SOURCE_REMOVE

        GLib.idle_add(later)


def test_the_batch_waits_for_its_answer_instead_of_reading_an_empty_dict():
    """Pins looks.py:1031/1032 — the async AddonBatch read synchronously.

    ``run`` starts work whose callbacks land on the main loop later. The Looks
    page used to call it and read the result on the next line, so with a real
    client it always saw ``(None, [])``: nothing was enabled, nothing was
    reported, and the download finished into a dictionary nobody read.
    ``run_and_wait`` is the fix, and this drives it against a library and an
    installer that answer the way the real ones do.
    """
    installer = DeferredInstaller(present={"here@x"})
    library = DeferredLibrary({"a@x": FakeRecord(), "b@x": FakeRecord()})
    batch = looks.AddonBatch(installer, library, shell_version="50.4", label="MAGMA")

    transaction, problems = batch.run_and_wait(
        [("here@x", "ego", ()), ("a@x", "ego", ()), ("b@x", "ego", ())], timeout=10
    )

    assert problems == []
    assert transaction is not None, "the enable transaction was thrown away"
    assert sorted(op.uuid for op in transaction.ops) == ["a@x", "b@x", "here@x"]
    assert [uuid for uuid, _tag in installer.asked] == ["a@x", "b@x"]


def test_the_old_read_it_on_the_next_line_pattern_really_would_have_lost_it():
    """The other half of the same finding: the bug is real, not theoretical."""
    installer = DeferredInstaller()
    library = DeferredLibrary({"a@x": FakeRecord()})
    batch = looks.AddonBatch(installer, library, shell_version="50.4")

    landed: dict = {}
    batch.run([("a@x", "ego", ())], lambda t, p: landed.update(t=t, p=p))
    assert landed == {}, "the answer cannot be there yet — that was the bug"


def test_an_add_on_nothing_could_be_fetched_for_is_not_reported_as_added():
    """Pins looks.py:468 — 'Added.' shown for add-ons never added.

    ``plan_for_look`` marks a missing-but-downloadable add-on NEEDS_RELOGIN,
    whose sentence is "Added. It starts working after you log out and back in."
    The batch used to put that untouched report into ``problems`` on both paths
    where nothing is fetched, so the dialog said an add-on had been added when
    the download never started.
    """
    from gtheme.ego.install import COPY as EGO_COPY
    from gtheme.ego.install import InstallOutcome

    added = EGO_COPY[InstallOutcome.NEEDS_RELOGIN]

    # no library at all — EgoClient could not be built
    landed: dict = {}
    looks.AddonBatch(FakeInstaller(), None, shell_version="50.4").run(
        [("a@x", "ego", ())], lambda t, p: landed.update(t=t, p=p)
    )
    assert [report.message for report in landed["p"]] == [EGO_COPY["download-failed"]]
    assert added not in {report.message for report in landed["p"]}

    # the library was asked and answered with nothing
    landed = {}
    looks.AddonBatch(FakeInstaller(), FakeLibrary({}), shell_version="50.4").run(
        [("b@x", "ego", ())], lambda t, p: landed.update(t=t, p=p)
    )
    assert [report.message for report in landed["p"]] == [EGO_COPY["download-failed"]]

    # the library knows it, but has no build for this desktop
    landed = {}
    looks.AddonBatch(
        FakeInstaller(), FakeLibrary({"c@x": FakeRecord(tag=None)}), shell_version="50.4"
    ).run([("c@x", "ego", ())], lambda t, p: landed.update(t=t, p=p))
    assert landed["p"][0].outcome is InstallOutcome.NOT_COMPATIBLE
    assert added not in landed["p"][0].message


def test_saving_over_a_look_of_the_same_name_asks_first(
    config_dir, themes_dir, backend, monkeypatch
):
    """Pins looks.py:1166 — 'Save my desktop as a Look' overwrote in silence.

    A download that lands on a name already taken asks (``_confirm_replace``);
    saving the current desktop under that name wrote straight over the folder.
    """
    write_look(themes_dir, name="seaglass", title="SEAGLASS")

    page = looks.build(FakeWindow(Prefs()))
    saved: list[tuple[str, str]] = []
    monkeypatch.setattr(
        looks.LooksPage, "_save_look", lambda _self, slug, title: saved.append((slug, title))
    )

    class Row:
        def get_text(self) -> str:
            return "Seaglass"

    dialog = _capture_dialog(
        page, lambda: page._on_save_response(Adw.AlertDialog(), "save", Row())
    )
    assert saved == [], "it saved over the Look before asking"
    assert "Seaglass" in dialog.get_heading()
    assert looks.COPY["save-replace-yours"] in dialog.get_body()

    dialog.emit("response", "keep")
    assert saved == [], "'Keep what I have' saved anyway"
    dialog.emit("response", "replace")
    assert saved == [("seaglass", "Seaglass")]


def test_saving_under_a_free_name_still_asks_nothing(config_dir, themes_dir, backend, monkeypatch):
    page = looks.build(FakeWindow(Prefs()))
    saved: list[tuple[str, str]] = []
    monkeypatch.setattr(
        looks.LooksPage, "_save_look", lambda _self, slug, title: saved.append((slug, title))
    )

    class Row:
        def get_text(self) -> str:
            return "Nothing Like This"

    page._on_save_response(Adw.AlertDialog(), "save", Row())
    assert saved == [("nothing-like-this", "Nothing Like This")]


def test_the_batch_waits_from_a_worker_thread_the_way_the_page_runs_it():
    """The production shape of the same fix: worker thread, real main loop.

    ``ApplyRunner`` is threaded in the app, so ``work()`` runs off the main
    loop while the library's callbacks land on it. This drives exactly that.
    """
    import threading

    from gi.repository import GLib

    installer = DeferredInstaller()
    library = DeferredLibrary({"a@x": FakeRecord(), "b@x": FakeRecord()})
    batch = looks.AddonBatch(installer, library, shell_version="50.4", label="MAGMA")

    loop = GLib.MainLoop()
    landed: dict = {}

    def worker() -> None:
        try:
            landed["result"] = batch.run_and_wait(
                [("a@x", "ego", ()), ("b@x", "ego", ())], timeout=15
            )
        except Exception as error:  # noqa: BLE001 - reported through the loop
            landed["error"] = error
        finally:
            GLib.idle_add(loop.quit)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    GLib.timeout_add_seconds(20, loop.quit)
    loop.run()
    thread.join(timeout=5)

    assert "error" not in landed, landed.get("error")
    transaction, problems = landed["result"]
    assert problems == []
    assert sorted(op.uuid for op in transaction.ops) == ["a@x", "b@x"]


def test_a_batch_whose_answer_never_comes_says_so_instead_of_waiting_forever():
    """A parked download must not leave the progress dialog open for ever."""

    class SilentLibrary:
        def info(self, uuid, callback):
            """Asked, and never answers — a request that went nowhere."""

    batch = looks.AddonBatch(FakeInstaller(), SilentLibrary(), shell_version="50.4")
    with pytest.raises(TimeoutError):
        batch.run_and_wait([("a@x", "ego", ())], timeout=0.2)
