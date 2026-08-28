"""The shortcut editor asks before taking keys off something else.

persona-report §3.2: "The shortcut editor writes whatever you press with **no
conflict check** — GNOME's own Settings stops you here and offers to replace.
gtheme, which exists to be safer, does less." What it left behind was two
settings holding one combination, with nothing on screen to say which one would
win, and no way to find the other one again except by reading 175 rows.

The scan and the sentence are pure and are tested as such. The dialog is real —
built by the page's own :func:`confirm_replace`, never presented (the row is
not in a window, so it has no root to present to) and answered by emitting the
response a button would.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for the row library")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from gtheme.panels import widgets as panel_widgets  # noqa: E402
from gtheme.panels.descriptor import Row, WidgetKind  # noqa: E402
from gtheme.ui import jargon  # noqa: E402

MENU = "gsettings:org.gnome.desktop.wm.keybindings panel-main-menu"
RUN = "gsettings:org.gnome.desktop.wm.keybindings panel-run-dialog"


def _row(key: str, title: str) -> Row:
    return Row(
        title=title,
        subtitle="Does the thing.",
        schema_id="org.gnome.desktop.wm.keybindings",
        key=key,
        kind=WidgetKind.SHORTCUT,
    )


MENU_ROW = _row("panel-main-menu", "Open the main menu")
RUN_ROW = _row("panel-run-dialog", "Open the run box")
CLOSE_ROW = _row("close", "Close the window")
ROWS = [CLOSE_ROW, MENU_ROW, RUN_ROW]


# --------------------------------------------------------------------------
# what counts as the same combination
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("first", "second"),
    [("<Primary>t", "<Control>t"), ("<Control>T", "<Control>t"), ("<Super>m", "<Super>m")],
)
def test_the_same_shortcut_spelled_differently_is_the_same_shortcut(first, second):
    assert panel_widgets.same_keys(first, second)


@pytest.mark.parametrize(
    ("first", "second"),
    [("<Super>m", "<Super>n"), ("<Super>m", "<Shift><Super>m"), ("<Super>m", "")],
)
def test_different_combinations_are_not_confused(first, second):
    assert not panel_widgets.same_keys(first, second)


def test_the_keys_are_named_the_way_a_person_reads_them():
    assert panel_widgets.shortcut_keys_label("<Super>m") == "Super+M"


# --------------------------------------------------------------------------
# the scan
# --------------------------------------------------------------------------


@pytest.mark.mutating
def test_a_combination_already_in_use_is_found(memory_settings):
    memory_settings.set(MENU, "['<Super>m']")

    clashes = panel_widgets.find_clashes(
        memory_settings, "<Super>m", exclude_key=RUN, rows=ROWS
    )

    assert [clash.row.title for clash in clashes] == ["Open the main menu"]


@pytest.mark.mutating
def test_the_shortcut_being_edited_is_not_a_conflict_with_itself(memory_settings):
    memory_settings.set(MENU, "['<Super>m']")

    assert (
        panel_widgets.find_clashes(
            memory_settings, "<Super>m", exclude_key=MENU, rows=ROWS
        )
        == []
    )


@pytest.mark.mutating
def test_clearing_a_shortcut_asks_nobody_anything(memory_settings):
    memory_settings.set(MENU, "['<Super>m']")
    assert (
        panel_widgets.find_clashes(memory_settings, "", exclude_key=RUN, rows=ROWS) == []
    )


def test_the_scan_covers_every_shortcut_in_the_app_not_only_this_page():
    """Two files, one keyboard: the media keys can clash with the window ones."""
    keys = {row.key for row in panel_widgets.shortcut_rows()}
    assert "close" in keys, "the window shortcuts"
    assert "volume-up" in keys, "and the media keys"
    assert len(keys) > 100


# --------------------------------------------------------------------------
# what it says
# --------------------------------------------------------------------------


def test_the_sentence_names_the_other_shortcut_and_the_keys():
    line = panel_widgets.clash_sentence(
        [panel_widgets.ShortcutClash(row=MENU_ROW, accelerator="<Super>m")], "<Super>m"
    )
    assert "Open the main menu" in line
    assert "Super+M" in line
    assert "no keys" in line


def test_two_clashes_are_both_named():
    clashes = [
        panel_widgets.ShortcutClash(row=MENU_ROW, accelerator="<Super>m"),
        panel_widgets.ShortcutClash(row=CLOSE_ROW, accelerator="<Super>m"),
    ]
    line = panel_widgets.clash_sentence(clashes, "<Super>m")
    assert "Open the main menu" in line and "Close the window" in line
    assert "Those shortcuts" in line


def test_the_words_it_uses_are_plain_english():
    problems = jargon.check_all(
        [(f"widgets.CLASH_COPY[{k!r}]", v) for k, v in panel_widgets.CLASH_COPY.items()]
        + [
            (
                "widgets.clash_sentence",
                panel_widgets.clash_sentence(
                    [panel_widgets.ShortcutClash(row=MENU_ROW, accelerator="<Super>m")],
                    "<Super>m",
                ),
            )
        ]
    )
    assert problems == [], "\n".join(problems)


# --------------------------------------------------------------------------
# and what each answer does to the desktop
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="module")
def _adw():
    if not Gtk.init_check():
        pytest.skip("no display is available for GTK — run under gtk4-broadwayd")
    Adw.init()


@pytest.fixture
def clash(memory_settings, monkeypatch):
    """A built "Open the run box" row, mid-capture of Super+M, which is taken.

    Returns ``(press, dialogs)``: ``press(accelerator)`` is the very callback
    the capture dialog hands the key combination to, and ``dialogs`` collects
    every clash dialog the row really built.
    """
    memory_settings.set(MENU, "['<Super>m']")
    memory_settings.set(RUN, "['<Super>r']")
    widget, _refresh = panel_widgets.build_row(memory_settings, RUN_ROW)

    captured: dict[str, Callable[[str], None]] = {}
    monkeypatch.setattr(
        panel_widgets,
        "present_capture_dialog",
        lambda _origin, _row, on_accelerator: captured.setdefault("press", on_accelerator),
    )
    _shortcut_button(widget).emit("clicked")
    assert "press" in captured, "the row's button no longer opens a capture"

    dialogs: list[Adw.AlertDialog] = []
    real = panel_widgets.confirm_replace

    def watch(*args, **kwargs):
        dialog = real(*args, **kwargs)
        dialogs.append(dialog)
        return dialog

    monkeypatch.setattr(panel_widgets, "confirm_replace", watch)
    return captured["press"], dialogs


@pytest.mark.gtk
@pytest.mark.mutating
def test_pressing_keys_that_are_taken_writes_nothing_until_it_is_answered(
    memory_settings, clash
):
    press, dialogs = clash

    press("<Super>m")

    assert len(dialogs) == 1, "no question was asked"
    assert panel_widgets.CLASH_COPY["heading"] == dialogs[0].get_heading()
    assert "Open the main menu" in dialogs[0].get_body()
    assert memory_settings.get(RUN) == "['<Super>r']", "written before it was answered"
    assert memory_settings.get(MENU) == "['<Super>m']"


@pytest.mark.gtk
@pytest.mark.mutating
def test_keeping_it_as_it_was_leaves_both_shortcuts_alone(memory_settings, clash):
    press, dialogs = clash
    press("<Super>m")

    dialogs[0].emit("response", "cancel")

    assert memory_settings.get(RUN) == "['<Super>r']"
    assert memory_settings.get(MENU) == "['<Super>m']"


@pytest.mark.gtk
@pytest.mark.mutating
def test_replacing_takes_the_keys_from_the_other_one(memory_settings, clash):
    press, dialogs = clash
    press("<Super>m")

    dialogs[0].emit("response", "replace")

    assert memory_settings.get(RUN) == "['<Super>m']"
    assert panel_widgets.decode_accelerator(memory_settings.get(MENU)) == "", (
        "the other shortcut must be left with no keys, not sharing them"
    )


@pytest.mark.gtk
@pytest.mark.mutating
def test_a_free_combination_is_written_with_no_question_asked(memory_settings, clash):
    press, dialogs = clash

    # Deliberately a combination nothing on any desktop ships bound: the rest
    # of the corpus answers this scan out of GNOME's own defaults, and a test
    # that picked a plausible shortcut would fail on the first machine whose
    # defaults happened to include it.
    press("<Shift><Control><Alt>F12")

    assert dialogs == []
    assert memory_settings.get(RUN) == "['<Shift><Control><Alt>F12']"
    assert memory_settings.get(MENU) == "['<Super>m']"


def _shortcut_button(widget: Gtk.Widget) -> Gtk.Button:
    found: list[Gtk.Button] = []

    def walk(node: Gtk.Widget) -> None:
        if isinstance(node, Gtk.Button):
            found.append(node)
        child = node.get_first_child()
        while child is not None:
            walk(child)
            child = child.get_next_sibling()

    walk(widget)
    assert found, "the shortcut row has no button to press"
    return found[0]
