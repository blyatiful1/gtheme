"""The Terminal page under things that used to break it (M11, L17, H12).

Three separate ways this page failed, all of them invisible in a normal run:

* a Look whose palette held one value that is not a colour raised out of the
  page's own builder, and the window **cached** the error placeholder — the
  page was gone for the rest of the session (review-report M11);
* opening it ran every adapter's ``detect()`` two or three times, each a full
  ``PATH`` walk plus a re-parse of that program's config, synchronously between
  the click and the page appearing (review-report L17);
* the Apply handler had no guard anywhere, so anything unexpected ended as a
  traceback on a terminal nobody was looking at and a click that did nothing
  visible at all (review-report H12).
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
from gtheme.terminal import model as terminal_model  # noqa: E402
from gtheme.ui.pages import terminal  # noqa: E402
from gtheme.ui.rowindex import RowIndex  # noqa: E402

pytestmark = pytest.mark.gtk


@pytest.fixture(autouse=True, scope="module")
def _adw():
    if not Gtk.init_check():
        pytest.skip("no display is available for GTK — run under gtk4-broadwayd")
    Adw.init()


class FakeWindow:
    """Everything the page asks of its window, and nothing that maps anything."""

    def __init__(self) -> None:
        self.rows = RowIndex()
        self.prefs = None
        self.toasts: list[str] = []

    def toast(self, text: str) -> None:
        self.toasts.append(text)


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
    found = []
    child = root.get_first_child()
    while child is not None:
        found.append(child)
        found.extend(_widgets(child))
        child = child.get_next_sibling()
    return found


def _descriptions(page) -> str:
    return "\n".join(
        w.get_description() or ""
        for w in _widgets(page)
        if isinstance(w, Adw.PreferencesGroup)
    )


class _Meta:
    name = "handmade"
    title = "Handmade"


class _Preset:
    def __init__(self, palette: dict[str, str]) -> None:
        self.palette = palette
        self.meta = _Meta()


class _Look:
    def __init__(self, palette: dict[str, str]) -> None:
        self.preset = _Preset(palette)
        self.name = "handmade"


class _Counting:
    """An adapter that remembers how often it was asked to look at the machine."""

    id = "counting"
    name = "Counting"
    reload_semantics = terminal_model.ReloadSemantics.RESTART

    def __init__(self) -> None:
        self.detects = 0

    def detect(self) -> terminal_model.TerminalState:
        self.detects += 1
        return terminal_model.TerminalState(
            installed=True, notes=[self.reload_semantics.sentence()]
        )

    def current(self):
        return None

    def plan(self, _palette):
        return terminal_model.TerminalWrites()


# -- M11: a Look whose palette is not all colours --------------------------


def test_a_colour_name_no_terminal_speaks_is_not_a_palette():
    """``Gdk.RGBA().parse`` accepts ``black``; a settings file cannot hold it.

    The Look preview validates with the former and so gives its author no
    signal, which is exactly how such a Look reaches this page.
    """
    assert terminal.palette_from_look(_Preset({"bg": "black", "fg": "#ffffff"})) is None
    assert terminal.palette_from_look(_Preset({"bg": "#000", "fg": "rgb(1,2,3)"})) is None


def test_one_unusable_ansi_colour_does_not_cost_the_look_its_background():
    """A partial ANSI set is already refused; this keeps the refusal that small."""
    palette = {"bg": "#101010", "fg": "#efefef"}
    palette.update({f"ansi_{name}": "#123456" for name in terminal._ANSI_NAMES})
    palette.update({f"ansi_bright_{name}": "#123456" for name in terminal._ANSI_NAMES})
    palette["ansi_bright_white"] = "papayawhip"

    built = terminal.palette_from_look(_Preset(palette))
    assert built is not None
    assert built.ansi == ()
    assert built.background == "#101010"


def test_the_page_still_opens_under_such_a_look(window, backend, probe, monkeypatch):
    """It used to raise, and the window cached the error page it raised into."""
    monkeypatch.setattr(
        terminal, "applied_look", lambda *a, **k: _Look({"bg": "black", "fg": "#ffffff"})
    )

    page = terminal.build(window, backend=backend, probe=probe)

    assert terminal.COPY["colours-none"] in _descriptions(page)
    buttons = [w for w in _widgets(page) if isinstance(w, Adw.ButtonRow)]
    assert buttons and not buttons[0].get_sensitive()


# -- L17: one look at the machine per program ------------------------------


def test_opening_the_page_asks_each_program_about_itself_once(
    window, backend, probe, monkeypatch, tmp_dest_root, state_dir
):
    import gtheme.terminal as terminal_package

    counting = _Counting()
    monkeypatch.setattr(terminal_package, "adapters", lambda _backend=None: [counting])

    terminal.build(window, backend=backend, probe=probe)

    assert counting.detects == 1


def test_what_was_found_travels_with_the_adapter(backend, monkeypatch):
    import gtheme.terminal as terminal_package

    counting = _Counting()
    monkeypatch.setattr(terminal_package, "adapters", lambda _backend=None: [counting])

    found = terminal_package.installed(backend)

    assert [adapter for adapter, _state in found] == [counting]
    assert all(state.installed for _adapter, state in found)
    assert counting.detects == 1


# -- H12: a signal handler that cannot end in silence ----------------------


def test_a_handler_that_fails_says_so_instead_of_printing_a_traceback(window):
    def handler(*_args):
        raise RuntimeError("something nobody predicted")

    terminal._guarded(window, handler)()

    assert window.toasts == [terminal.COPY["crashed"]]
    assert "RuntimeError" not in window.toasts[0]


def test_the_apply_button_reports_a_program_that_misbehaves(
    window, backend, probe, monkeypatch, tmp_dest_root, state_dir
):
    """Not a traceback, not silence, and not "Done" either."""
    import gtheme.terminal as terminal_package

    class _Angry(_Counting):
        id = "angry"
        name = "Angry"

        def plan(self, _palette):
            raise RuntimeError("bytes must be in range(0, 256)")

    monkeypatch.setattr(terminal_package, "adapters", lambda _backend=None: [_Angry()])
    monkeypatch.setattr(
        terminal, "applied_look", lambda *a, **k: _Look({"bg": "#000000", "fg": "#ffffff"})
    )

    page = terminal.build(window, backend=backend, probe=probe)
    button = next(w for w in _widgets(page) if isinstance(w, Adw.ButtonRow))
    button.emit("activated")

    shown = [w.get_title() for w in _widgets(page) if isinstance(w, Adw.ActionRow)]
    assert any(terminal.COPY["failed"].format(why="") .strip() in title for title in shown)
    assert any("0 of 1" in text for text in window.toasts)
    assert not any("range(0, 256)" in text for text in window.toasts + shown)
