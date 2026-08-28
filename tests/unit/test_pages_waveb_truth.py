"""Three pages that told the user something that was not so.

Marked ``gtk``: real widgets, never presented. The desktop is a dictionary, the
settings store is in memory, and the descriptor corpus is the shipped one —
handed back through a stand-in loader where a test needs it to be broken.

* **M5** — a switch that the desktop refused stayed reading ON, and nothing was
  ever coming to correct it.
* **M30** — one malformed file in ``data/domains/`` took down two pages that do
  not even render it, while the other thirteen degraded gracefully.
* **L5** — More Settings' filter hid the floor's rows and left its heading and
  three-line explanation sitting over an empty space.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for the page modules")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from ego_fakes import FakeRunner, FakeShellProxy  # noqa: E402
from gi.repository import Adw, Gtk  # noqa: E402

from gtheme.core import backends  # noqa: E402
from gtheme.core.settings_backend import MemoryBackend  # noqa: E402
from gtheme.ego.install import COPY as INSTALL_COPY  # noqa: E402
from gtheme.ego.install import (  # noqa: E402
    ExtensionInstaller,
    InstallOutcome,
    InstallReport,
)
from gtheme.ego.shelldbus import ShellExtensions  # noqa: E402
from gtheme.panels.loader import load_domains  # noqa: E402
from gtheme.panels.schema_probe import SchemaProbe  # noqa: E402
from gtheme.prefs import Prefs  # noqa: E402
from gtheme.ui.pages import addons, more, topbar, windows  # noqa: E402
from gtheme.ui.rowindex import RowIndex  # noqa: E402

pytestmark = pytest.mark.gtk

DASH_TO_DOCK = "dash-to-dock@micxgx.gmail.com"
DASH_TO_PANEL = "dash-to-panel@jderose9.github.com"


@pytest.fixture(autouse=True, scope="module")
def _adw():
    if not Gtk.init_check():
        pytest.skip("no display is available for GTK — run under gtk4-broadwayd")
    Adw.init()


class FakeWindow:
    """Everything these three pages ask of a window, and nothing that maps."""

    def __init__(self, prefs: Prefs | None = None) -> None:
        self.rows = RowIndex()
        self.prefs = prefs
        self.toasts: list[str] = []
        self.pages: list[str] = []

    def toast(self, text: str) -> None:
        self.toasts.append(text)

    def show_page(self, page_id: str) -> None:
        self.pages.append(page_id)


def _info(uuid: str, **overrides: Any) -> dict[str, Any]:
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


def _widgets(root: Gtk.Widget) -> list[Gtk.Widget]:
    found: list[Gtk.Widget] = []
    child = root.get_first_child()
    while child is not None:
        found.append(child)
        found.extend(_widgets(child))
        child = child.get_next_sibling()
    return found


# ---------------------------------------------------------------------------
# M5 — a switch is a statement about the desktop
# ---------------------------------------------------------------------------


class Refusing(FakeShellProxy):
    """A desktop that knows the add-on and will not switch it on."""

    def enable_extension(self, uuid: str) -> bool:
        self.enable_calls.append(uuid)
        return False


@pytest.fixture
def addons_page(config_dir: Path):
    """Build the Add-ons page over a desktop the test controls."""
    built: list[addons.AddonsPage] = []

    def make(proxy: FakeShellProxy):
        shell = ShellExtensions(proxy)
        installer = ExtensionInstaller(shell, None, runner=FakeRunner())
        backends.set_backend(MemoryBackend())
        window = FakeWindow(Prefs())
        page = addons.AddonsPage(
            window,
            shell=shell,
            client=None,
            installer=installer,
            checker=None,
            probe=None,
            prefs=window.prefs,
        )
        built.append(page)
        return page, window

    try:
        yield make
    finally:
        for page in built:
            page.teardown()
        backends.set_backend(None)


def test_a_switch_the_desktop_refused_goes_back_to_off(addons_page):
    """Pins addons.py:757 — ``_turn_on`` toasted and left the switch on.

    ``enable_extension`` returning False produces no ``ExtensionStateChanged``
    signal, so nothing was ever coming to correct the switch: it read ON over
    an add-on that was off, for as long as the page stayed open
    (review-report M5).
    """
    proxy = Refusing({DASH_TO_DOCK: _info(DASH_TO_DOCK, state=2.0, enabled=False)})
    page, window = addons_page(proxy)

    page._installed_rows[DASH_TO_DOCK].set_active(True)

    assert proxy.enable_calls == [DASH_TO_DOCK]
    assert page._installed_rows[DASH_TO_DOCK].get_active() is False
    assert window.toasts == [INSTALL_COPY["would-not-start"]], (
        "the correction must not read as the user switching it off again"
    )
    assert proxy.disable_calls == [], "nothing asked the desktop to disable anything"


def test_an_add_on_that_starts_at_the_next_log_in_keeps_its_switch_on(addons_page):
    """The one outcome where ON is honest: it *is* enabled, from next log-in."""
    proxy = FakeShellProxy({DASH_TO_DOCK: _info(DASH_TO_DOCK, state=2.0, enabled=False)})
    page, window = addons_page(proxy)

    class Waiting:
        def turn_on(self, uuid: str) -> InstallReport:
            return InstallReport(
                uuid,
                InstallOutcome.NEEDS_RELOGIN,
                INSTALL_COPY[InstallOutcome.NEEDS_RELOGIN],
                via="desktop",
            )

    page.installer = Waiting()
    page._installed_rows[DASH_TO_DOCK].set_active(True)

    assert page._installed_rows[DASH_TO_DOCK].get_active() is True
    assert window.toasts == [INSTALL_COPY[InstallOutcome.NEEDS_RELOGIN]]


def test_replacing_an_add_on_that_then_refuses_leaves_the_switch_off(addons_page):
    """The either/or answer goes through the same honest switch move.

    The conflict path used to force the switch back on itself, after
    ``_turn_on``, which would have put the same lie back on screen.
    """
    proxy = Refusing(
        {
            DASH_TO_DOCK: _info(DASH_TO_DOCK, name="Dash to Dock"),
            DASH_TO_PANEL: _info(DASH_TO_PANEL, name="Dash to Panel", state=2.0, enabled=False),
        }
    )
    page, window = addons_page(proxy)

    dialog = page._ask_about_conflict(
        DASH_TO_PANEL, DASH_TO_DOCK, page._installed_rows[DASH_TO_PANEL]
    )
    dialog.emit("response", "replace")

    assert proxy.disable_calls == [DASH_TO_DOCK]
    assert page._installed_rows[DASH_TO_PANEL].get_active() is False
    assert page._installed_rows[DASH_TO_DOCK].get_active() is False
    assert INSTALL_COPY["would-not-start"] in window.toasts
    assert addons.COPY["turned-off"] not in window.toasts, (
        "the page's own switch moves are not the user switching things off"
    )


# ---------------------------------------------------------------------------
# M30 — one broken file, one page's problem
# ---------------------------------------------------------------------------


@pytest.fixture
def page_window(config_dir: Path) -> FakeWindow:
    return FakeWindow(Prefs())


@pytest.fixture
def settings(memory_settings: MemoryBackend) -> MemoryBackend:
    return memory_settings


@pytest.fixture
def corpus() -> list[Any]:
    domains, problems = load_domains()
    assert not problems, f"the shipped corpus itself is broken: {problems}"
    return domains


@pytest.mark.parametrize("module", [topbar, windows])
def test_a_broken_file_this_page_does_not_render_no_longer_takes_it_down(
    module, page_window, settings, corpus, monkeypatch
):
    """Pins topbar.py:107 and windows.py:141 — ``if problems: raise``.

    ``load_domains`` reports a problem for every file in ``data/domains/``, and
    the page's own ``_DOMAIN_IDS`` filter ran *after* the raise. So a
    version-skewed ``peripherals.toml`` — which neither page renders — made
    both of them say "This page could not be opened.", while the other thirteen
    degraded gracefully (review-report M30).
    """
    monkeypatch.setattr(
        module,
        "load_domains",
        lambda *_a, **_k: (corpus, ["peripherals.toml: 3 problem(s): boom"]),
    )
    with backends.use_backend(settings):
        widget = module.build(page_window)
    assert isinstance(widget, Gtk.Widget)
    assert page_window.rows.for_page(module.PAGE_ID), "the page really drew its rows"


@pytest.mark.parametrize("module", [topbar, windows])
def test_a_page_degrades_to_the_parts_that_did_load(
    module, page_window, settings, corpus, monkeypatch
):
    """One of this page's own files is broken; the rest of the page still opens."""
    kept = [domain for domain in corpus if domain.id != module._DOMAIN_IDS[0]]
    monkeypatch.setattr(
        module,
        "load_domains",
        lambda *_a, **_k: (kept, [f"{module._DOMAIN_IDS[0]}.toml: cannot be read (boom)"]),
    )
    with backends.use_backend(settings):
        widget = module.build(page_window)
    assert isinstance(widget, Gtk.Widget)


@pytest.mark.parametrize("module", [topbar, windows])
def test_a_page_with_nothing_left_to_draw_still_refuses_and_names_the_file(
    module, page_window, settings, corpus, monkeypatch
):
    """An empty page would be a lie of omission, so this case still refuses."""
    monkeypatch.setattr(
        module,
        "load_domains",
        lambda *_a, **_k: (
            [domain for domain in corpus if domain.id not in module._DOMAIN_IDS],
            [f"{name}.toml: cannot be read (boom)" for name in module._DOMAIN_IDS]
            + ["peripherals.toml: cannot be read (boom)"],
        ),
    )
    with backends.use_backend(settings), pytest.raises(RuntimeError) as raised:
        module.build(page_window)
    said = str(raised.value)
    assert f"{module._DOMAIN_IDS[0]}.toml" in said
    assert "peripherals.toml" not in said, "someone else's broken file is not this page's news"


# ---------------------------------------------------------------------------
# L5 — a heading with nothing under it
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def probe() -> SchemaProbe:
    return SchemaProbe()


def _filter_entry(page: Gtk.Widget) -> Gtk.SearchEntry:
    entries = [
        widget
        for widget in _widgets(page)
        if isinstance(widget, Gtk.SearchEntry)
        and widget.get_placeholder_text() == more.COPY["search-placeholder"]
    ]
    assert len(entries) == 1
    return entries[0]


def _floor_group(page: Gtk.Widget) -> Adw.PreferencesGroup:
    groups = [
        widget
        for widget in _widgets(page)
        if isinstance(widget, Adw.PreferencesGroup)
        and widget.get_title() == more.COPY["floor-title"]
    ]
    assert len(groups) == 1
    return groups[0]


def test_the_floor_heading_goes_when_nothing_in_it_matches(page_window, settings, probe):
    """Pins more.py:670 — the floor's outer group was never in ``groups``.

    Only its expanders hid, so filtering to something the floor does not have
    left "Described by your desktop" and its three-line explanation standing
    over nothing (review-report L5).
    """
    page = more.build(page_window, backend=settings, probe=probe)
    group = _floor_group(page)
    entry = _filter_entry(page)
    assert group.get_visible()

    entry.set_text("qqzzxx-nothing-matches-this")
    entry.emit("search-changed")
    assert not group.get_visible(), "the heading outlived everything under it"

    entry.set_text("")
    entry.emit("search-changed")
    assert group.get_visible(), "and it comes back when the filter is cleared"


def test_the_floor_heading_stays_while_anything_under_it_matches(
    page_window, settings, probe
):
    page = more.build(page_window, backend=settings, probe=probe)
    group = _floor_group(page)
    entry = _filter_entry(page)

    entry.set_text("magnif")
    entry.emit("search-changed")

    assert group.get_visible()
    assert any(
        isinstance(widget, Adw.ExpanderRow) and widget.get_visible()
        for widget in _widgets(group)
    )
