"""The Add-ons page, driven against a desktop and a library that do not exist.

Every test here builds real widgets and inspects them. Nothing is ever
presented: the page only shows a dialog when it is inside a window, and it
never is here, so running this suite puts nothing on the screen of whoever runs
it. Settings go to an in-memory store, the desktop is a dictionary, and the
online library answers out of the recorded responses in ``tests/fixtures/ego/``
— a test that silently gained a network dependency fails rather than passing on
a good day.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for the page module")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from ego_fakes import (  # noqa: E402
    FakeRunner,
    FakeShellProxy,
    RecordedTransport,
)
from gi.repository import Adw, Gtk  # noqa: E402

from gtheme.core.backends import set_backend, use_backend  # noqa: E402
from gtheme.core.settings_backend import MemoryBackend  # noqa: E402
from gtheme.ego.client import EgoClient  # noqa: E402
from gtheme.ego.install import COPY as INSTALL_COPY  # noqa: E402
from gtheme.ego.install import ExtensionInstaller, InstallOutcome  # noqa: E402
from gtheme.ego.shelldbus import (  # noqa: E402
    ExtensionState,
    ShellError,
    ShellErrorKind,
    ShellExtensions,
)
from gtheme.ego.updates import COPY as UPDATE_COPY  # noqa: E402
from gtheme.ego.updates import UpdateChecker  # noqa: E402
from gtheme.panels.descriptor import PanelDescriptor  # noqa: E402
from gtheme.panels.schema_probe import SchemaProbe  # noqa: E402
from gtheme.prefs import Prefs  # noqa: E402
from gtheme.ui.pages import addons  # noqa: E402

pytestmark = pytest.mark.gtk

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "schemas"

DASH_TO_DOCK = "dash-to-dock@micxgx.gmail.com"
DASH_TO_PANEL = "dash-to-panel@jderose9.github.com"
BLUR = "blur-my-shell@aunetx"
HIDETOPBAR = "hidetopbar@mathieu.bidon.ca"
STRANGER = "some-thing@example.com"
BLUR_PANEL_SCHEMA = "org.gnome.shell.extensions.blur-my-shell.panel"

#: Every request the page can make while a test is running, answered from the
#: recorded captures. Order matters: the fake transport takes the first route
#: that matches, so the catch-all below has to be added last — see
#: :func:`with_pictures`.
ROUTES: dict[str, Any] = {
    "extension-query": "query-downloads-p1.json",
    "extension-info": "info-blur-my-shell.json",
    "/api/v1/": "apiv1-blur-my-shell.json",
    "/comments/all/": "comments-3193.json",
    "/update-info/": "update-info.json",
}

#: Pictures are asked for with something that is not a picture. The page is
#: expected to shrug: an add-on with a broken screenshot is still an add-on.
PICTURES = "https://extensions.gnome.org/"


def with_pictures(routes: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = dict(ROUTES)
    merged.update(routes or {})
    merged.pop(PICTURES, None)
    merged[PICTURES] = b"not-a-picture"
    return merged


def info(uuid: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "uuid": uuid,
        "name": uuid.split("@")[0],
        "state": 1.0,
        "type": 2.0,
        "enabled": True,
        "version": 60.0,
    }
    payload.update(overrides)
    return payload


class FakeWindow:
    """What the page uses the window for: toasts and moving to another page."""

    def __init__(self) -> None:
        self.toasts: list[str] = []
        self.pages: list[str] = []

    def toast(self, text: str) -> None:
        self.toasts.append(text)

    def show_page(self, page_id: str) -> None:
        self.pages.append(page_id)


@pytest.fixture(scope="module")
def probe() -> SchemaProbe:
    """The committed corpus of real add-on settings descriptions."""
    return SchemaProbe([CORPUS], include_default=True)


@pytest.fixture
def window() -> FakeWindow:
    return FakeWindow()


@pytest.fixture
def prefs(config_dir: Path) -> Prefs:
    """App preferences in a throwaway directory, never the user's own."""
    return Prefs()


@pytest.fixture
def make_page(probe: SchemaProbe, window: FakeWindow, prefs: Prefs):
    """Build the page over a desktop and a library the test controls.

    The settings backend is forced for the WHOLE test, not just for the moment
    the page is built. A page opens an add-on's settings long after its
    constructor has returned, and an override that had already been put back by
    then would send those reads and writes to the real desktop — which is
    exactly the thing this suite exists not to do.
    """
    built: list[addons.AddonsPage] = []

    def make(
        extensions: dict[str, dict[str, Any]] | None = None,
        *,
        proxy: FakeShellProxy | None = None,
        routes: dict[str, Any] | None = None,
        backend: MemoryBackend | None = None,
        panels: list[PanelDescriptor] | None = None,
    ):
        proxy = proxy or FakeShellProxy(extensions or {})
        shell = ShellExtensions(proxy)
        client = EgoClient(RecordedTransport(with_pictures(routes)), "50.4")
        installer = ExtensionInstaller(shell, client, runner=FakeRunner())
        checker = UpdateChecker(client, shell)
        checker.runner = FakeRunner()
        set_backend(backend or MemoryBackend())
        page = addons.AddonsPage(
            window,
            shell=shell,
            client=client,
            installer=installer,
            checker=checker,
            probe=probe,
            prefs=prefs,
            panels=panels,
        )
        built.append(page)
        return page, proxy, shell

    try:
        yield make
    finally:
        for page in built:
            page.teardown()
        set_backend(None)


# -- walking the widgets ---------------------------------------------------


def rows_of(widget: Gtk.Widget) -> list[Adw.PreferencesRow]:
    found: list[Adw.PreferencesRow] = []

    def walk(parent: Gtk.Widget) -> None:
        child = parent.get_first_child()
        while child is not None:
            if isinstance(child, Adw.PreferencesRow):
                found.append(child)
            walk(child)
            child = child.get_next_sibling()

    walk(widget)
    return found


def titles_of(widget: Gtk.Widget) -> list[str]:
    return [row.get_title() for row in rows_of(widget)]


def group_titles(widget: Gtk.Widget) -> list[str]:
    found: list[str] = []

    def walk(parent: Gtk.Widget) -> None:
        child = parent.get_first_child()
        while child is not None:
            if isinstance(child, Adw.PreferencesGroup) and child.get_title():
                found.append(child.get_title())
            walk(child)
            child = child.get_next_sibling()

    walk(widget)
    return found


def banners_of(widget: Gtk.Widget) -> list[str]:
    found: list[str] = []

    def walk(parent: Gtk.Widget) -> None:
        child = parent.get_first_child()
        while child is not None:
            if isinstance(child, Adw.Banner):
                found.append(child.get_title())
            walk(child)
            child = child.get_next_sibling()

    walk(widget)
    return found


def buttons_of(widget: Gtk.Widget) -> list[Gtk.Button]:
    found: list[Gtk.Button] = []

    def walk(parent: Gtk.Widget) -> None:
        child = parent.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.Button):
                found.append(child)
            walk(child)
            child = child.get_next_sibling()

    walk(widget)
    return found


# -- installed -------------------------------------------------------------


def test_the_list_is_grouped_by_what_an_add_on_is_for(make_page):
    page, _proxy, _shell = make_page(
        {
            DASH_TO_DOCK: info(DASH_TO_DOCK, name="Dash to Dock"),
            BLUR: info(BLUR, name="Blur my Shell"),
            STRANGER: info(STRANGER, name="Some Thing"),
        }
    )
    groups = group_titles(page.installed_view)
    assert "Looks" in groups
    assert "Layout" in groups
    # An add-on nobody curated is still shown, at the end, under its own group.
    assert groups[-1] == addons.OTHER_CATEGORY_TITLE


def test_no_identifier_ever_reaches_the_list(make_page):
    """The desktop returns the identifier as the name when it has no other."""
    page, _proxy, _shell = make_page({DASH_TO_DOCK: info(DASH_TO_DOCK, name=DASH_TO_DOCK)})
    titles = titles_of(page.installed_view)
    assert titles == ["Dash to dock"]
    assert all("@" not in title for title in titles)


def test_with_nothing_installed_the_page_says_where_to_look(make_page):
    page, _proxy, _shell = make_page({})
    statuses = _status_pages(page.installed_view)
    assert any(s.get_title() == addons.COPY["installed-empty-title"] for s in statuses)


def test_with_no_desktop_answering_all_three_views_say_so(probe, window, prefs):
    class Refusing(FakeShellProxy):
        def list_extensions(self):
            raise ShellError(ShellErrorKind.UNAVAILABLE, "no desktop here")

    shell = ShellExtensions(Refusing({}))
    with use_backend(MemoryBackend()):
        page = addons.AddonsPage(
            window, shell=shell, client=None, probe=probe, prefs=prefs, panels=[]
        )
    try:
        assert page.available is False
        titles = [s.get_title() for s in _status_pages(page)]
        assert titles.count(addons.COPY["no-desktop-title"]) >= 2
    finally:
        page.teardown()


def test_with_no_desktop_at_all_the_page_still_builds(probe, window, prefs, monkeypatch):
    """No session to talk to is an ordinary state, not a traceback.

    The two variables below are deleted deliberately: they are what the page
    looks at before it tries to reach a desktop, and without that the page
    under test would find the REAL one — the whole point of this suite is that
    it never does.
    """
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    with use_backend(MemoryBackend()):
        page = addons.AddonsPage(
            window, shell=None, client=None, probe=probe, prefs=prefs, panels=[]
        )
    try:
        assert page.available is False
        titles = [s.get_title() for s in _status_pages(page.installed_view)]
        assert titles == [addons.COPY["no-desktop-title"]]
    finally:
        page.teardown()


def test_turning_an_add_on_off_asks_the_desktop_and_says_what_happened(make_page, window):
    page, proxy, _shell = make_page({DASH_TO_DOCK: info(DASH_TO_DOCK, name="Dash to Dock")})
    page._installed_rows[DASH_TO_DOCK].set_active(False)
    assert proxy.disable_calls == [DASH_TO_DOCK]
    assert window.toasts == [addons.COPY["turned-off"]]


def test_a_desktop_that_refuses_to_switch_something_on_is_reported_honestly(
    make_page, window
):
    """False from the desktop is not an error to swallow; it is a sentence."""

    class Refusing(FakeShellProxy):
        def enable_extension(self, uuid: str) -> bool:
            self.enable_calls.append(uuid)
            return False

    proxy = Refusing(
        {DASH_TO_DOCK: info(DASH_TO_DOCK, name="Dash to Dock", state=2.0, enabled=False)}
    )
    page, proxy, _shell = make_page(proxy=proxy)
    page._installed_rows[DASH_TO_DOCK].set_active(True)
    assert proxy.enable_calls == [DASH_TO_DOCK]
    assert window.toasts == [INSTALL_COPY["would-not-start"]]


def test_the_second_of_two_add_ons_that_do_the_same_job_asks_first(make_page):
    page, proxy, _shell = make_page(
        {
            DASH_TO_DOCK: info(DASH_TO_DOCK, name="Dash to Dock"),
            DASH_TO_PANEL: info(DASH_TO_PANEL, name="Dash to Panel", state=2.0, enabled=False),
        }
    )
    page._installed_rows[DASH_TO_PANEL].set_active(True)

    # Nothing was switched on, and the switch went back: a switch that is
    # already on while a question is on screen would be a lie.
    assert proxy.enable_calls == []
    assert page._installed_rows[DASH_TO_PANEL].get_active() is False


def test_the_either_or_question_names_both_add_ons_in_the_user_s_words(make_page):
    page, _proxy, shell = make_page(
        {
            DASH_TO_DOCK: info(DASH_TO_DOCK, name="Dash to Dock"),
            DASH_TO_PANEL: info(DASH_TO_PANEL, name="Dash to Panel"),
        }
    )
    dialog = page._ask_about_conflict(
        DASH_TO_PANEL, DASH_TO_DOCK, page._installed_rows[DASH_TO_PANEL]
    )
    assert dialog.get_heading() == "Dash to Panel replaces Dash to Dock. Turn Dash to Dock off?"
    assert "two of everything" in dialog.get_body()


def test_both_docks_already_on_is_offered_a_way_out(make_page):
    page, _proxy, _shell = make_page(
        {
            DASH_TO_DOCK: info(DASH_TO_DOCK, name="Dash to Dock"),
            DASH_TO_PANEL: info(DASH_TO_PANEL, name="Dash to Panel"),
        }
    )
    assert any("two of everything" in text for text in banners_of(page.installed_view))


# -- the screen-recording hazard -------------------------------------------


def test_the_recording_hazard_is_named_when_the_blur_really_is_on(make_page, probe):
    backend = MemoryBackend(schema_source=probe.source_for(BLUR_PANEL_SCHEMA))
    page, _proxy, _shell = make_page(
        {BLUR: info(BLUR, name="Blur my Shell"), HIDETOPBAR: info(HIDETOPBAR)},
        backend=backend,
    )
    assert any("screen recording" in text for text in banners_of(page.installed_view))


def test_the_recording_hazard_is_not_named_when_the_blur_is_off(make_page, probe):
    backend = MemoryBackend(schema_source=probe.source_for(BLUR_PANEL_SCHEMA))
    backend.set(f"gsettings:{BLUR_PANEL_SCHEMA} blur", "false")
    page, _proxy, _shell = make_page(
        {BLUR: info(BLUR, name="Blur my Shell"), HIDETOPBAR: info(HIDETOPBAR)},
        backend=backend,
    )
    assert not any("screen recording" in text for text in banners_of(page.installed_view))


def test_a_setting_that_cannot_be_read_still_warns(make_page):
    """Silence would cost somebody the recording they were about to make."""
    page, _proxy, _shell = make_page(
        {BLUR: info(BLUR, name="Blur my Shell"), HIDETOPBAR: info(HIDETOPBAR)},
        backend=MemoryBackend(),  # knows none of the add-on's settings
    )
    assert any("screen recording" in text for text in banners_of(page.installed_view))


# -- the gear panel --------------------------------------------------------


def test_a_curated_add_on_gets_the_curated_rows(make_page, probe):
    backend = MemoryBackend(
        schema_source=probe.source_for("org.gnome.shell.extensions.dash-to-dock")
    )
    page, _proxy, shell = make_page(
        {DASH_TO_DOCK: info(DASH_TO_DOCK, name="Dash to Dock")}, backend=backend
    )
    # The rows are built now, not during the constructor: prove they are still
    # reading and writing the store this test handed in.
    assert page._backend_for("org.gnome.shell.extensions.dash-to-dock") is backend
    dialog = page._open_panel(shell.get(DASH_TO_DOCK))
    titles = titles_of(dialog.get_child())
    assert "Which edge it sits on" in titles
    assert "Icon size" in titles


def test_an_add_on_nobody_curated_gets_its_author_s_words_and_says_so(make_page, probe):
    backend = MemoryBackend(
        schema_source=probe.source_for("org.gnome.shell.extensions.blur-my-shell")
    )
    page, _proxy, shell = make_page(
        {BLUR: info(BLUR, name="Blur my Shell", hasPrefs=True)},
        backend=backend,
        panels=[],  # nothing is curated in this run
    )
    dialog = page._open_panel(shell.get(BLUR))
    assert addons.COPY["author-settings"] in banners_of(dialog.get_child())
    assert titles_of(dialog.get_child()), "the generated panel produced no rows at all"


def test_the_authors_words_banner_is_shown_once_and_stays_dismissed(make_page, probe, prefs):
    page, _proxy, shell = make_page({BLUR: info(BLUR, name="Blur my Shell")}, panels=[])
    prefs.mark_banner_seen("addon-settings-are-the-authors")
    dialog = page._open_panel(shell.get(BLUR))
    assert addons.COPY["author-settings"] not in banners_of(dialog.get_child())


def test_a_generated_panel_only_draws_what_it_can_draw_correctly(probe):
    """A control that writes the wrong shape of value is worse than no control."""
    rows, skipped = addons.auto_rows(probe, BLUR_PANEL_SCHEMA)
    assert rows and skipped
    kinds = {row.kind.value for row in rows}
    assert kinds <= {"toggle", "slider", "choice", "text"}
    keys = {row.key for row in rows}
    assert "blur" in keys  # an on/off setting
    assert "pipeline" in keys  # plain text
    # The type word an add-on author puts in front of a summary is not shown.
    assert all(not row.title.lower().startswith("boolean") for row in rows)


def test_a_generated_panel_for_an_add_on_with_no_settings_says_so(make_page):
    page, _proxy, shell = make_page({STRANGER: info(STRANGER, name="Some Thing")}, panels=[])
    dialog = page._open_panel(shell.get(STRANGER))
    assert addons.COPY["panel-none"] in titles_of(dialog.get_child())


def test_a_setting_this_version_does_not_have_is_greyed_and_says_why(make_page, probe):
    panel = PanelDescriptor.model_validate(
        {
            "id": "made-up",
            "target": {
                "uuids": [DASH_TO_DOCK],
                "schema_id": "org.gnome.shell.extensions.dash-to-dock",
                "category": "layout",
                "summary": "A dock.",
            },
            "rows": [
                {
                    "schema_id": "org.gnome.shell.extensions.dash-to-dock",
                    "key": "not-a-real-key",
                    "title": "Something that is not there",
                    "subtitle": "A setting this version of the add-on does not have.",
                    "kind": "toggle",
                }
            ],
        }
    )
    backend = MemoryBackend(
        schema_source=probe.source_for("org.gnome.shell.extensions.dash-to-dock")
    )
    page, _proxy, shell = make_page(
        {DASH_TO_DOCK: info(DASH_TO_DOCK, name="Dash to Dock")},
        backend=backend,
        panels=[panel],
    )
    dialog = page._open_panel(shell.get(DASH_TO_DOCK))
    row = next(r for r in rows_of(dialog.get_child()) if r.get_title() == "Something that is not there")
    assert row.get_sensitive() is False
    assert "doesn't have this" in row.get_subtitle()


def test_a_setting_another_page_owns_is_named_rather_than_half_drawn(make_page):
    """The list of top bar styles comes from scanning the computer, not from
    the add-on, so it lives on the page that does the scanning. Saying "open
    the add-on's own window" for it would send somebody to the wrong place.
    """
    panel = PanelDescriptor.model_validate(
        {
            "id": "made-up",
            "target": {
                "uuids": [DASH_TO_DOCK],
                "schema_id": "org.gnome.shell.extensions.dash-to-dock",
                "category": "layout",
                "summary": "A dock.",
            },
            "rows": [
                {
                    "schema_id": "org.gnome.shell.extensions.dash-to-dock",
                    "key": "dock-position",
                    "title": "Which one to use",
                    "subtitle": "Chosen from what is installed on this computer.",
                    "kind": "picker",
                }
            ],
        }
    )
    page, _proxy, shell = make_page(
        {DASH_TO_DOCK: info(DASH_TO_DOCK, name="Dash to Dock")}, panels=[panel]
    )
    dialog = page._open_panel(shell.get(DASH_TO_DOCK))
    titles = titles_of(dialog.get_child())
    assert addons.COPY["panel-elsewhere-one"] in titles
    assert addons.COPY["panel-skipped-one"] not in titles


# -- details ---------------------------------------------------------------


def test_the_details_show_what_people_wrote_as_words_not_as_markup(make_page):
    page, _proxy, _shell = make_page({})
    record = _first_record(page)
    dialog = page._show_details(record)
    subtitles = [
        row.get_subtitle()
        for row in rows_of(dialog.get_child())
        if isinstance(row, Adw.ActionRow) and row.get_subtitle()
    ]
    assert subtitles, "the reviews never arrived"
    assert all("<p>" not in text for text in subtitles)
    assert any("Compiz" in text for text in subtitles)


def test_the_details_survive_an_add_on_with_no_picture(make_page):
    from gtheme.ego.models import ExtensionRecord

    page, _proxy, _shell = make_page({})
    bare = ExtensionRecord.from_json(
        {"uuid": "bare@example.com", "name": "Bare", "creator": "nobody", "pk": 0}
    )
    dialog = page._show_details(bare)
    assert addons.COPY["no-picture"] in _labels(dialog.get_child())


def test_a_link_row_opens_the_add_ons_own_window(make_page):
    panel = PanelDescriptor.model_validate(
        {
            "id": "made-up",
            "target": {
                "uuids": [DASH_TO_DOCK],
                "schema_id": "org.gnome.shell.extensions.dash-to-dock",
                "category": "layout",
                "summary": "A dock.",
            },
            "rows": [
                {
                    "title": "Open the rest of its settings",
                    "subtitle": "The parts that only fit in the window its author wrote.",
                    "kind": "link",
                    "link_target": f"extension-prefs:{DASH_TO_DOCK}",
                }
            ],
        }
    )
    page, proxy, shell = make_page(
        {DASH_TO_DOCK: info(DASH_TO_DOCK, name="Dash to Dock")}, panels=[panel]
    )
    dialog = page._open_panel(shell.get(DASH_TO_DOCK))
    row = next(
        r for r in rows_of(dialog.get_child()) if r.get_title() == "Open the rest of its settings"
    )
    row.emit("activated")
    assert proxy.prefs_calls == [(DASH_TO_DOCK, "")]


def test_a_link_row_can_also_move_to_another_page(make_page, window):
    panel = PanelDescriptor.model_validate(
        {
            "id": "made-up",
            "target": {
                "uuids": [DASH_TO_DOCK],
                "schema_id": "org.gnome.shell.extensions.dash-to-dock",
                "category": "layout",
                "summary": "A dock.",
            },
            "rows": [
                {
                    "title": "Change the background picture",
                    "subtitle": "The picture behind everything.",
                    "kind": "link",
                    "link_target": "page:wallpaper",
                }
            ],
        }
    )
    page, _proxy, shell = make_page(
        {DASH_TO_DOCK: info(DASH_TO_DOCK, name="Dash to Dock")}, panels=[panel]
    )
    dialog = page._open_panel(shell.get(DASH_TO_DOCK))
    row = next(
        r for r in rows_of(dialog.get_child()) if r.get_title() == "Change the background picture"
    )
    row.emit("activated")
    assert window.pages == ["wallpaper"]


def test_removing_an_add_on_asks_first_and_then_says_what_happened(make_page, window):
    page, proxy, shell = make_page({DASH_TO_DOCK: info(DASH_TO_DOCK, name="Dash to Dock")})
    dialog = page._ask_to_remove(shell.get(DASH_TO_DOCK))
    assert dialog.get_heading() == "Remove Dash to Dock?"
    assert proxy.uninstall_calls == []
    dialog.emit("response", "remove")
    assert proxy.uninstall_calls == [DASH_TO_DOCK]
    assert addons.COPY["removed"] in window.toasts


# -- discover --------------------------------------------------------------


def test_results_are_listed_with_a_rough_count_and_a_way_to_see_more(make_page):
    page, _proxy, _shell = make_page({})
    titles = titles_of(page.results_box)
    assert "Dash to Dock" in titles
    assert addons.COPY["load-more"] in titles  # 44 pages of them
    labels = _labels(page.results_box)
    assert any(text.startswith("About ") for text in labels)


def test_paging_appends_rather_than_replaces(make_page):
    page, _proxy, _shell = make_page({})
    before = len([t for t in titles_of(page.results_box) if t != addons.COPY["load-more"]])
    page._run_query(page=2)
    after = len([t for t in titles_of(page.results_box) if t != addons.COPY["load-more"]])
    assert after == before * 2


def test_an_add_on_that_is_already_here_is_not_offered_again(make_page):
    page, _proxy, _shell = make_page({DASH_TO_DOCK: info(DASH_TO_DOCK, name="Dash to Dock")})
    row = next(r for r in rows_of(page.results_box) if r.get_title() == "Dash to Dock")
    labels = _labels(row)
    assert addons.COPY["added"] in labels
    assert addons.COPY["add"] not in labels


def test_an_add_on_with_no_build_for_this_desktop_is_not_offered(make_page):
    from gtheme.ego.models import ExtensionRecord

    page, _proxy, _shell = make_page({})
    old = ExtensionRecord.from_json(
        {
            "uuid": "ancient@example.com",
            "name": "Ancient",
            "creator": "somebody",
            "pk": 1,
            "description": "Written a long time ago.",
            "shell_version_map": {"3.36": {"pk": 1, "version": 1}},
        }
    )
    row = page._result_row(old)
    labels = _labels(row)
    assert addons.COPY["not-compatible-badge"] in labels
    assert addons.COPY["add"] not in labels


def test_adding_asks_the_desktop_exactly_once(make_page, window):
    """A second request while the first box is unanswered installs it twice."""
    proxy = FakeShellProxy({})
    proxy.install_script = [
        (None, ShellError(ShellErrorKind.NO_REPLY, "still waiting")),
    ]
    page, proxy, _shell = make_page(proxy=proxy)
    record = _first_record(page)
    button = Gtk.Button(label=addons.COPY["add"])

    page._add(record, button)
    assert proxy.install_calls == [record.uuid]
    assert INSTALL_COPY[InstallOutcome.WAITING_FOR_CONFIRMATION] in window.toasts

    page._add(record, button)
    assert proxy.install_calls == [record.uuid], "the request was sent a second time"
    assert addons.COPY["already-adding"] in window.toasts


def test_an_add_on_the_desktop_never_scanned_is_promised_nothing(make_page, window):
    page, proxy, _shell = make_page({})
    proxy.install_script = [("successful", None)]
    record = _first_record(page)
    page._add(record, Gtk.Button())
    assert INSTALL_COPY[InstallOutcome.NEEDS_RELOGIN] in window.toasts


def test_an_add_on_the_desktop_did_pick_up_is_reported_as_on(make_page, window):
    class Arriving(FakeShellProxy):
        def install_remote(self, uuid, callback):
            self.install_calls.append(uuid)
            self.extensions[uuid] = info(uuid, state=1.0)
            callback("successful", None)

    page, proxy, _shell = make_page(proxy=Arriving({}))
    record = _first_record(page)
    page._add(record, Gtk.Button())
    assert INSTALL_COPY[InstallOutcome.ACTIVE] in window.toasts


def test_the_page_follows_the_desktop_when_an_add_on_arrives(make_page):
    page, proxy, _shell = make_page({DASH_TO_DOCK: info(DASH_TO_DOCK, name="Dash to Dock")})
    proxy.arrive(BLUR, name="Blur my Shell")
    page._fill_installed()  # the idle rebuild, run now
    assert set(page._installed_rows) == {DASH_TO_DOCK, BLUR}


def test_a_switch_that_moves_because_the_desktop_said_so_writes_nothing(make_page):
    page, proxy, _shell = make_page(
        {DASH_TO_DOCK: info(DASH_TO_DOCK, name="Dash to Dock", state=2.0, enabled=False)}
    )
    page._on_extension_changed(_installed(DASH_TO_DOCK, state=ExtensionState.ACTIVE))
    assert page._installed_rows[DASH_TO_DOCK].get_active() is True
    assert proxy.enable_calls == []


# -- updates ---------------------------------------------------------------


def test_the_update_list_shows_names_and_never_identifiers(make_page):
    page, _proxy, _shell = make_page(
        {
            BLUR: info(BLUR, name="Blur my Shell", _generated="by the library"),
        },
    )
    page._check_updates()
    titles = titles_of(page.updates_view)
    assert "Blur my Shell" in titles
    assert all("@" not in title for title in titles)


def test_with_nothing_to_do_the_updates_view_says_so(make_page):
    page, _proxy, _shell = make_page({DASH_TO_DOCK: info(DASH_TO_DOCK)})
    page._check_updates()
    statuses = _status_pages(page.updates_view)
    assert any(s.get_description() == UPDATE_COPY["up-to-date"] for s in statuses)
    # And there is still a way to look again afterwards.
    assert addons.COPY["check"] in titles_of(page.updates_view)


@pytest.mark.mutating
def test_an_update_is_staged_and_the_page_says_when_it_applies(
    make_page, window, tmp_path, monkeypatch
):
    """Nothing is put over a running add-on: it waits for the next log-in."""
    staging = tmp_path / "extension-updates"
    monkeypatch.setenv("GTHEME_EXTENSION_UPDATES_DIR", str(staging))
    routes = {"download-extension": _package(BLUR)}
    page, _proxy, _shell = make_page(
        {BLUR: info(BLUR, name="Blur my Shell", _generated="by the library")}, routes=routes
    )
    page._check_updates()
    button = next(
        b for b in buttons_of(page.updates_view) if b.get_label() == addons.COPY["update"]
    )
    button.emit("clicked")

    assert (staging / BLUR / "metadata.json").is_file()
    assert UPDATE_COPY["staged"] in window.toasts


# -- teardown --------------------------------------------------------------


def test_teardown_stops_listening_to_everything(make_page, capfd):
    from gi.repository import GLib

    page, proxy, _shell = make_page({DASH_TO_DOCK: info(DASH_TO_DOCK)})
    assert proxy.handlers, "the page never subscribed in the first place"
    # Let whatever the page put on idle time actually run, so teardown meets
    # both kinds of source: the ones still pending and the ones already gone.
    context = GLib.MainContext.default()
    for _ in range(50):
        if not context.iteration(False):
            break
    page.teardown()
    assert proxy.handlers == {}
    assert page._sources == []
    _out, err = capfd.readouterr()
    assert "CRITICAL" not in err, err


def test_teardown_is_safe_to_run_twice(make_page):
    page, _proxy, _shell = make_page({})
    page.teardown()
    page.teardown()


# -- helpers ---------------------------------------------------------------


def _status_pages(widget: Gtk.Widget) -> list[Adw.StatusPage]:
    found: list[Adw.StatusPage] = []

    def walk(parent: Gtk.Widget) -> None:
        child = parent.get_first_child()
        while child is not None:
            if isinstance(child, Adw.StatusPage):
                found.append(child)
            walk(child)
            child = child.get_next_sibling()

    walk(widget)
    return found


def _labels(widget: Gtk.Widget) -> list[str]:
    found: list[str] = []

    def walk(parent: Gtk.Widget) -> None:
        child = parent.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.Label):
                found.append(child.get_label() or "")
            walk(child)
            child = child.get_next_sibling()

    walk(widget)
    return found


def _first_record(page: addons.AddonsPage):
    assert page._query is not None and page._query.extensions
    return page._query.extensions[0]


def _installed(uuid: str, *, state: ExtensionState):
    from gtheme.ego.shelldbus import InstalledExtension

    return InstalledExtension(uuid=uuid, name=uuid.split("@")[0], state=state, enabled=True)


def _package(uuid: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("metadata.json", json.dumps({"uuid": uuid, "version": 73}))
        archive.writestr("extension.js", "// hello")
    return buffer.getvalue()
