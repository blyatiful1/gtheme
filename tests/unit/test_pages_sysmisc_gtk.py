"""The five System-section pages, built for real.

Marked ``gtk`` because these construct libadwaita widgets. Nothing is presented
and no window is ever mapped — the desktop this suite runs on is the desktop it
is customising, and a page that popped up during a test run would be the least
of what that implies. Every value goes to an in-memory settings backend, so no
setting reaches any store; every file location is rerooted under a temporary
directory, so no file reaches the real home.
"""

from __future__ import annotations

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for the page widgets")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from gtheme.core.settings_backend import MemoryBackend  # noqa: E402
from gtheme.panels.schema_probe import SchemaProbe  # noqa: E402
from gtheme.prefs import Prefs  # noqa: E402
from gtheme.ui import search  # noqa: E402
from gtheme.ui.pages import more, nightlight, power, sound, terminal  # noqa: E402
from gtheme.ui.rowindex import RowIndex  # noqa: E402

pytestmark = pytest.mark.gtk


@pytest.fixture(autouse=True, scope="module")
def _adw():
    if not Gtk.init_check():
        pytest.skip("no display is available for GTK — run under gtk4-broadwayd")
    Adw.init()


class FakeWindow:
    """Everything a page asks of its window, and nothing that maps anything."""

    def __init__(self, prefs=None) -> None:
        self.rows = RowIndex()
        self.prefs = prefs
        self.toasts: list[str] = []
        self.opened: list[str] = []

    def toast(self, text: str) -> None:
        self.toasts.append(text)

    def show_page(self, page_id: str) -> None:
        self.opened.append(page_id)


@pytest.fixture
def window() -> FakeWindow:
    return FakeWindow()


@pytest.fixture
def backend() -> MemoryBackend:
    return MemoryBackend()


@pytest.fixture(scope="module")
def probe() -> SchemaProbe:
    return SchemaProbe()


def _widgets(root) -> list:
    """Every widget under ``root``, depth first."""
    found = []
    child = root.get_first_child()
    while child is not None:
        found.append(child)
        found.extend(_widgets(child))
        child = child.get_next_sibling()
    return found


def _titles(root) -> list[str]:
    return [w.get_title() for w in _widgets(root) if isinstance(w, Adw.PreferencesRow)]


# ---------------------------------------------------------------------------
# every page builds, and indexes what it built
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module", [nightlight, sound, power, more])
def test_the_page_builds_and_registers_every_row_it_drew(module, window, backend, probe):
    module.build(window, backend=backend, probe=probe)
    expected = search.page_rows(module.PAGE_ID)
    assert len(window.rows) >= len(expected) > 0
    for row in expected:
        assert row.id in window.rows, f"{row.id} was drawn and not registered"


@pytest.mark.parametrize("module", [nightlight, sound, power, more])
def test_every_registered_row_can_be_refreshed_without_writing(module, window, backend, probe):
    """The live-mirroring contract: a row re-reads itself on demand."""
    module.build(window, backend=backend, probe=probe)
    before = dict(backend._values) if hasattr(backend, "_values") else None
    assert window.rows.refresh_all() > 0
    if before is not None:
        assert backend._values == before, "refreshing a row wrote a value"


@pytest.mark.parametrize("module", [nightlight, sound, power, more])
def test_every_row_carries_an_explanation(module, window, backend, probe):
    """competitor-ux P4: no control ships without a subtitle."""
    page = module.build(window, backend=backend, probe=probe)
    rows = [
        w
        for w in _widgets(page)
        if isinstance(w, Adw.ActionRow | Adw.ExpanderRow) and w.get_title()
    ]
    assert rows
    for row in rows:
        assert row.get_subtitle(), f"{module.PAGE_ID}: {row.get_title()!r} explains nothing"


def test_a_setting_this_computer_does_not_have_is_greyed_and_says_why(window, backend):
    """An honest disabled row beats a control that writes into nothing."""
    from gtheme.panels.descriptor import Row, WidgetKind

    row = Row(
        schema_id="io.github.blyatiful1.NoSuchAddOn",
        key="a-flag",
        title="Something an add-on offers",
        subtitle="Only present when that add-on is installed.",
        kind=WidgetKind.TOGGLE,
    )
    built = search.build_indexed_rows(
        window, "more", [row], backend=backend, probe=SchemaProbe()
    )
    assert len(built) == 1
    widget = built[0][1]
    assert not widget.get_sensitive()
    assert "isn't installed" in widget.get_subtitle()


def test_the_idle_probe_lets_go_of_its_place_in_the_loop(window, backend, probe):
    """A callback that outlives its widgets is a crash on a slow computer."""
    from gi.repository import GLib

    page = nightlight.build(window, backend=backend, probe=probe)
    built = [
        (row, window.rows.lookup(row.id).widget)
        for row in search.page_rows("nightlight")
        if window.rows.lookup(row.id) is not None
    ]
    source = search.probe_built_rows(page, probe, built, backend=backend)
    assert source is not None
    context = GLib.MainContext.default()
    for _ in range(200):
        if context.find_source_by_id(source) is None:
            break
        context.iteration(False)
    assert context.find_source_by_id(source) is None, "the probe never finished"
    page.emit("destroy")  # must not complain about a source that already went


# ---------------------------------------------------------------------------
# night light
# ---------------------------------------------------------------------------


def test_a_schedule_row_says_the_time_it_is_set_to(window, backend, probe):
    """20.25 is a quarter past eight, and the row has to say so."""
    nightlight.build(window, backend=backend, probe=probe)
    entry = window.rows.lookup(
        "org.gnome.settings-daemon.plugins.color:night-light-schedule-from"
    )
    assert entry is not None
    entry.widget.set_value(20.25)
    assert "8:15 pm" in entry.widget.get_subtitle()


def test_the_schedule_rows_keep_the_bounds_the_app_promised(window, backend, probe):
    """GNOME bounds neither; ``KNOWN_CLAMPS`` is what does, and it is not widened."""
    from gtheme.panels.widgets import KNOWN_CLAMPS

    nightlight.build(window, backend=backend, probe=probe)
    for descriptor_id, clamp in KNOWN_CLAMPS.items():
        entry = window.rows.lookup(descriptor_id)
        if entry is None or not hasattr(entry.widget, "get_adjustment"):
            continue
        adjustment = entry.widget.get_adjustment()
        assert adjustment.get_lower() >= clamp.minimum
        if clamp.exclusive_maximum:
            assert adjustment.get_upper() < clamp.maximum
        else:
            assert adjustment.get_upper() <= clamp.maximum


def test_a_uint_slider_shows_the_value_it_actually_holds(window, backend, probe):
    """The regression this page found: ``uint32`` prints as ``"uint32 2700"``.

    Read literally that is not a number, and the slider fell back to its own
    minimum — so the colour-temperature row showed 1700 on every desktop
    whatever the desktop actually held, and nudging it wrote a value the person
    never chose. Twenty settings on a GNOME 50 desktop are ``uint32`` and every
    one of them is on a page of the System section.
    """
    key = "gsettings:org.gnome.settings-daemon.plugins.color night-light-temperature"
    backend.set(key, "3400")
    assert backend.get(key) == "uint32 3400", "the premise of this test changed"
    nightlight.build(window, backend=backend, probe=probe)
    entry = window.rows.lookup(
        "org.gnome.settings-daemon.plugins.color:night-light-temperature"
    )
    assert entry is not None
    assert entry.widget.get_value() == 3400


def test_a_uint_pick_one_row_does_not_call_its_own_value_foreign(window, backend, probe):
    """Same cause, other symptom: "uint32 300" is not one of the offered values."""
    from gtheme.ui.widgets.rows import FOREIGN_CHOICE_SUFFIX

    backend.set("gsettings:org.gnome.desktop.session idle-delay", "300")
    power.build(window, backend=backend, probe=probe)
    entry = window.rows.lookup("org.gnome.desktop.session:idle-delay")
    assert entry is not None
    model = entry.widget.get_model()
    labels = [model.get_string(i) for i in range(model.get_n_items())]
    assert not any(FOREIGN_CHOICE_SUFFIX in label for label in labels), labels
    assert labels[entry.widget.get_selected()] == "After 5 minutes"


def test_the_put_this_back_button_is_off_while_the_value_is_the_default(
    window, backend, probe
):
    """The reset button compares stored against default; both stay unbared."""
    nightlight.build(window, backend=backend, probe=probe)
    entry = window.rows.lookup(
        "org.gnome.settings-daemon.plugins.color:night-light-temperature"
    )
    buttons = [w for w in _widgets(entry.widget) if isinstance(w, Gtk.Button)]
    resets = [b for b in buttons if b.get_icon_name() == "edit-undo-symbolic"]
    assert resets, "the row lost its reset button"
    assert not resets[0].get_sensitive()


# ---------------------------------------------------------------------------
# sound
# ---------------------------------------------------------------------------


def test_the_sound_set_row_is_a_pick_one_over_what_is_installed(window, backend, probe):
    """The descriptor calls it a picker, and the base library leaves it unbuilt."""
    sound.build(window, backend=backend, probe=probe)
    entry = window.rows.lookup(sound.SOUND_SET_ROW)
    assert entry is not None
    assert isinstance(entry.widget, Adw.ComboRow)
    assert entry.widget.get_model().get_n_items() >= 1


def test_the_sound_set_list_always_offers_the_one_every_desktop_ships(tmp_path):
    assert sound.installed_sound_sets([tmp_path]) == [sound.DEFAULT_SOUND_SET]


def test_a_directory_without_a_definition_is_not_a_sound_set(tmp_path):
    (tmp_path / "not-a-set").mkdir()
    real = tmp_path / "real-set"
    real.mkdir()
    (real / "index.theme").write_text("[Sound Theme]\n", encoding="utf-8")
    assert sound.installed_sound_sets([tmp_path]) == ["freedesktop", "real-set"]


# ---------------------------------------------------------------------------
# power
# ---------------------------------------------------------------------------


def test_the_nagging_combination_is_warned_about(window, backend, probe):
    backend.set("gsettings:org.gnome.desktop.screensaver lock-enabled", "true")
    backend.set("gsettings:org.gnome.desktop.screensaver lock-delay", "0")
    backend.set("gsettings:org.gnome.desktop.session idle-delay", "60")
    assert power.lock_warning(backend) == power.COPY["lock-warning"]
    page = power.build(window, backend=backend, probe=probe)
    banners = [w for w in _widgets(page) if isinstance(w, Adw.Banner)]
    assert [b.get_title() for b in banners] == [power.COPY["lock-warning"]]


def test_a_sensible_combination_is_not_warned_about(backend):
    backend.set("gsettings:org.gnome.desktop.screensaver lock-enabled", "true")
    backend.set("gsettings:org.gnome.desktop.screensaver lock-delay", "300")
    backend.set("gsettings:org.gnome.desktop.session idle-delay", "600")
    assert power.lock_warning(backend) is None


def test_never_turning_the_screen_off_is_not_a_nagging_combination(backend):
    backend.set("gsettings:org.gnome.desktop.screensaver lock-enabled", "true")
    backend.set("gsettings:org.gnome.desktop.screensaver lock-delay", "0")
    backend.set("gsettings:org.gnome.desktop.session idle-delay", "0")
    assert power.lock_warning(backend) is None


def test_no_lock_means_no_warning(backend):
    backend.set("gsettings:org.gnome.desktop.screensaver lock-enabled", "false")
    backend.set("gsettings:org.gnome.desktop.screensaver lock-delay", "0")
    backend.set("gsettings:org.gnome.desktop.session idle-delay", "60")
    assert power.lock_warning(backend) is None


# ---------------------------------------------------------------------------
# more settings — the floor
# ---------------------------------------------------------------------------


def test_the_floor_draws_every_setting_nobody_described(window, backend, probe):
    more.build(window, backend=backend, probe=probe)
    for descriptor_id in search.floor_ids():
        assert descriptor_id in window.rows, f"{descriptor_id} never reached the page"


def test_the_floor_groups_are_collapsed_and_explained(window, backend, probe):
    page = more.build(window, backend=backend, probe=probe)
    expanders = [
        w
        for w in _widgets(page)
        if isinstance(w, Adw.ExpanderRow) and w.get_title() in more.SCHEMA_TITLES.values()
    ]
    assert len(expanders) >= 20
    for expander in expanders:
        assert not expander.get_expanded(), f"{expander.get_title()!r} opens by default"
        assert len(expander.get_subtitle()) > 40


def test_a_heading_with_an_ampersand_survives_the_markup_parser(window, backend, probe):
    """Unescaped, "Mouse, Touchpad & Keyboard" renders as an empty heading."""
    page = more.build(window, backend=backend, probe=probe)
    groups = [w for w in _widgets(page) if isinstance(w, Adw.PreferencesGroup)]
    titles = [g.get_title() for g in groups]
    assert any("&amp;" in title for title in titles), titles


def test_the_first_visit_explainer_shows_once_and_then_never_again(backend, probe, config_dir):
    prefs = Prefs()
    first = FakeWindow(prefs)
    page = more.build(first, backend=backend, probe=probe)
    banners = [w for w in _widgets(page) if isinstance(w, Adw.Banner)]
    assert len(banners) == 1
    banners[0].emit("button-clicked")

    prefs.reload()
    second = FakeWindow(Prefs())
    again = more.build(second, backend=backend, probe=probe)
    assert [w for w in _widgets(again) if isinstance(w, Adw.Banner)] == []


def test_the_local_filter_hides_what_does_not_match(window, backend, probe):
    """Two hundred rows on one page need narrowing without leaving it."""
    page = more.build(window, backend=backend, probe=probe)
    # Every pick-one row carries a search box of its own inside its popover,
    # so the page's own filter is picked out by what it says.
    entries = [
        w
        for w in _widgets(page)
        if isinstance(w, Gtk.SearchEntry)
        and w.get_placeholder_text() == more.COPY["search-placeholder"]
    ]
    assert len(entries) == 1
    rows = [w for w in _widgets(page) if isinstance(w, Adw.PreferencesRow)]
    visible_before = sum(1 for row in rows if row.get_visible())

    entries[0].set_text("magnif")
    entries[0].emit("search-changed")
    visible_after = sum(1 for row in rows if row.get_visible())
    assert 0 < visible_after < visible_before

    entries[0].set_text("")
    entries[0].emit("search-changed")
    assert sum(1 for row in rows if row.get_visible()) == visible_before


# ---------------------------------------------------------------------------
# terminal
# ---------------------------------------------------------------------------


def test_the_terminal_page_shows_a_card_only_for_what_is_installed(
    window, backend, probe, tmp_dest_root, state_dir
):
    from gtheme.terminal import installed

    page = terminal.build(window, backend=backend, probe=probe)
    titles = [
        w.get_title()
        for w in _widgets(page)
        if isinstance(w, Adw.PreferencesGroup) and w.get_title()
    ]
    for adapter, _state in installed(backend):
        assert adapter.name in titles


def test_a_cards_reload_story_is_shown_word_for_word(
    window, backend, probe, tmp_dest_root, state_dir
):
    """The adapter's sentence, verbatim. Rewording it is how honesty is lost."""
    from gtheme.terminal import installed

    page = terminal.build(window, backend=backend, probe=probe)
    descriptions = [
        w.get_description()
        for w in _widgets(page)
        if isinstance(w, Adw.PreferencesGroup) and w.get_description()
    ]
    joined = "\n".join(descriptions)
    for adapter, _state in installed(backend):
        assert adapter.reload_semantics.sentence() in joined


def test_with_no_look_applied_the_button_is_off_and_says_why(
    window, backend, probe, tmp_dest_root, state_dir
):
    page = terminal.build(window, backend=backend, probe=probe)
    buttons = [w for w in _widgets(page) if isinstance(w, Adw.ButtonRow)]
    assert buttons and not buttons[0].get_sensitive()
    descriptions = [
        w.get_description()
        for w in _widgets(page)
        if isinstance(w, Adw.PreferencesGroup) and w.get_description()
    ]
    assert any(terminal.COPY["colours-none"] in text for text in descriptions)


def test_the_page_says_what_it_does_not_manage(
    window, backend, probe, tmp_dest_root, state_dir
):
    page = terminal.build(window, backend=backend, probe=probe)
    assert terminal.COPY["spicetify"] in _titles(page)


@pytest.mark.mutating
def test_settings_owned_by_another_tool_are_refused_and_offered_back(
    window, backend, probe, tmp_dest_root, state_dir
):
    """DESIGN.md F7, end to end: refuse, offer, take over, and undo.

    The whole thing happens inside the temporary destination root — the folder
    that is 'somewhere else' is somewhere else *within the sandbox*, and the
    real ``~/.config/ghostty`` on this machine is never looked at, let alone
    written to.
    """
    foreign = tmp_dest_root / "another-tool" / "ghostty"
    foreign.mkdir(parents=True)
    (foreign / "config").write_text("theme = something-else\n", encoding="utf-8")
    config = tmp_dest_root / ".config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "ghostty").symlink_to(foreign)

    from gtheme.terminal.ghostty import GhosttyAdapter

    adapter = GhosttyAdapter()
    assert adapter.foreign_root() is not None and not adapter.taken_over()

    page = terminal.build(window, backend=backend, probe=probe)
    buttons = [
        w
        for w in _widgets(page)
        if isinstance(w, Gtk.Button) and w.get_label() == terminal.COPY["take-over"]
    ]
    assert buttons, "the refusal was shown with no way to answer it"

    # The notice the adapter itself writes reaches the card, unreworded.
    descriptions = "\n".join(
        w.get_description() or ""
        for w in _widgets(page)
        if isinstance(w, Adw.PreferencesGroup)
    )
    assert "another tool" in descriptions

    buttons[0].emit("clicked")
    assert adapter.taken_over()
    assert not (config / "ghostty").is_symlink()
    assert (config / "ghostty" / "config").read_text(encoding="utf-8").startswith("theme =")
    assert buttons[0].get_label() == terminal.COPY["undo-take-over"]

    buttons[0].emit("clicked")
    assert not adapter.taken_over()
    assert (config / "ghostty").is_symlink()


@pytest.mark.mutating
def test_applying_reports_each_program_separately(
    window, backend, probe, tmp_dest_root, state_dir, monkeypatch
):
    """One program refusing must not stop the others, or be called success."""
    from gtheme.terminal.model import FileChange, ReloadSemantics, TerminalState, TerminalWrites

    class _Adapter:
        def __init__(self, ident: str, fails: bool) -> None:
            self.id = ident
            self.name = ident.capitalize()
            self.reload_semantics = ReloadSemantics.RESTART
            self.fails = fails

        def detect(self):
            return TerminalState(installed=True, notes=[self.reload_semantics.sentence()])

        def current(self):
            return None

        def plan(self, _palette):
            if self.fails:
                raise PermissionError("Managed by another tool.")
            return TerminalWrites(
                files=(FileChange(str(tmp_dest_root / f"{self.id}.conf"), b"colours\n"),)
            )

    good, bad = _Adapter("good", False), _Adapter("bad", True)
    monkeypatch.setattr(
        terminal, "installed", lambda _backend: [(good, good.detect()), (bad, bad.detect())]
    )
    monkeypatch.setattr(
        terminal,
        "applied_look",
        lambda *a, **k: type(
            "L",
            (),
            {
                "preset": type(
                    "P",
                    (),
                    {
                        "palette": {"bg": "#000000", "fg": "#ffffff"},
                        "meta": type("M", (), {"name": "x", "title": "X"})(),
                    },
                )()
            },
        )(),
    )

    page = terminal.build(window, backend=backend, probe=probe)
    button = next(w for w in _widgets(page) if isinstance(w, Adw.ButtonRow))
    assert button.get_sensitive()
    button.emit("activated")

    shown = [w.get_title() for w in _widgets(page) if isinstance(w, Adw.ActionRow)]
    assert any(ReloadSemantics.RESTART.sentence() in title for title in shown)
    assert any("Managed by another tool." in title for title in shown)
    assert window.toasts and "1 of 2" in window.toasts[-1]


def test_a_palette_produces_a_visible_swatch(window, backend, probe, tmp_dest_root, state_dir):
    from gtheme.preset import loader

    magma = next(r for r in loader.load_all() if r.name == "magma")
    page = terminal._colours_group(Adw, Gtk, magma, terminal.palette_from_look(magma.preset))
    assert [w for w in _widgets(page) if isinstance(w, Gtk.DrawingArea)]


# ---------------------------------------------------------------------------
# the search overlay
# ---------------------------------------------------------------------------


def test_the_overlay_starts_empty_and_says_what_to_do(window):
    index = search.SearchIndex.build(looks=())
    dialog = search.build_search_dialog(window, index=index)
    assert dialog.gtheme_stack.get_visible_child_name() == "empty"


def test_typing_produces_results_that_deep_link(window):
    index = search.SearchIndex.build(looks=())
    chosen: list[tuple[str, str | None]] = []
    dialog = search.build_search_dialog(
        window, index=index, on_activate=lambda p, d: chosen.append((p, d))
    )
    dialog.gtheme_entry.set_text("night light")
    dialog.gtheme_entry.emit("search-changed")
    assert dialog.gtheme_stack.get_visible_child_name() == "results"
    first = dialog.gtheme_results.get_first_child()
    assert first is not None
    first.emit("activated")
    assert chosen and chosen[0][0] == "nightlight"


def test_a_query_that_matches_nothing_says_so(window):
    dialog = search.build_search_dialog(window, index=search.SearchIndex.build(looks=()))
    dialog.gtheme_entry.set_text("zzzzzzzz-no-such-thing")
    dialog.gtheme_entry.emit("search-changed")
    assert dialog.gtheme_stack.get_visible_child_name() == "empty"


def test_without_a_navigator_the_window_is_the_navigator(window, backend, probe):
    nightlight.build(window, backend=backend, probe=probe)
    dialog = search.build_search_dialog(window, index=search.SearchIndex.build(looks=()))
    dialog.gtheme_entry.set_text("how warm")
    dialog.gtheme_entry.emit("search-changed")
    first = dialog.gtheme_results.get_first_child()
    assert first is not None
    first.emit("activated")
    assert window.opened == ["nightlight"]


def test_a_deep_link_flashes_the_row_it_landed_on(window, backend, probe):
    nightlight.build(window, backend=backend, probe=probe)
    descriptor_id = "org.gnome.settings-daemon.plugins.color:night-light-temperature"
    assert search.flash(window, descriptor_id)
    widget = window.rows.lookup(descriptor_id).widget
    assert widget.has_css_class(search.FLASH_CSS_CLASS)


def test_flashing_a_row_that_is_not_on_screen_is_a_no_op(window):
    assert search.flash(window, "org.gnome.nothing:here") is False


def test_ctrl_f_is_wired_to_a_real_window():
    window = Gtk.Window()
    controller = search.install_search(window, index=search.SearchIndex(hits=[]))
    assert isinstance(controller, Gtk.ShortcutController)
    assert window.observe_controllers().get_n_items() >= 1


# -- regression: the confirmed review findings on the probe seam ------------


class _RecordingProbe(SchemaProbe):
    """A real probe that also writes down what backend it was probed with."""

    def __init__(self) -> None:
        super().__init__()
        self.backends: list[object] = []

    def probe(self, rows, backend=None):
        self.backends.append(backend)
        return super().probe(rows, backend)


def _one_row():
    from gtheme.panels.descriptor import Row, WidgetKind

    return Row(
        schema_id="org.gnome.shell.extensions.burn-my-windows-profile",
        key="fire-enable",
        title="A setting an add-on keeps in a file of its own",
        subtitle="The kind of row the backend exists for.",
        kind=WidgetKind.TOGGLE,
    )


def test_probe_built_rows_hands_the_backend_on_instead_of_dropping_it(window, backend):
    """Pins search.py:435 — the backend parameter was accepted and swallowed.

    ``probe_rows_idle`` needs the backend to answer for an add-on that keeps
    its settings in a file of its own; without one it returns the pessimistic
    "cannot be read" and greys a row that works. ``probe_built_rows`` declared
    the parameter, three pages passed it, and the call never forwarded it.
    """
    row = _one_row()
    probe = _RecordingProbe()
    widget = Adw.SwitchRow(title=row.title, subtitle=row.subtitle)

    search.probe_built_rows(Gtk.Box(), probe, [(row, widget)], backend=backend)

    assert probe.backends == [backend]


def test_the_page_shell_probes_with_its_own_backend(window, backend):
    """The same omission, in ``PageShell.start_probe``."""
    from gtheme.ui.pages import _style_common as common

    shell = common.PageShell(window, "more")
    shell.backend = backend
    probe = _RecordingProbe()
    shell.probe = probe
    shell._probe_targets = [(_one_row(), Adw.SwitchRow(title="x"))]

    shell.start_probe()

    assert probe.backends == [backend]
