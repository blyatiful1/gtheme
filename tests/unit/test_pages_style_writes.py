"""What the "how it looks" pages do when a write does not happen.

The pages hand-build the controls the row library deliberately does not offer —
a picker whose options come from scanning the computer, nine accent dots, a grid
of icon sets, a wall of pictures. Each of those wrote straight to the settings
store and swallowed a refusal whole. Three findings, all of them here:

* **H3** — a hand-built control's write is recorded exactly like a row's.
* **M7** — a refused write puts the control back to what the desktop really
  holds and says why, instead of leaving a picked tile that picked nothing.
* **M3** — the compound writes (dark mode, the window-heading lettering) go
  through one transaction, and a full or read-only state directory raises
  ``OSError`` from *outside* that transaction's own guarded section. It used to
  come straight out of a GTK signal handler: no message, no error, and the
  switch left showing a change that never happened.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for the widget library")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk  # noqa: E402

from gtheme.core import backends as core_backends  # noqa: E402
from gtheme.core import ledger as ledger_store  # noqa: E402
from gtheme.core.baseline import Baseline  # noqa: E402
from gtheme.core.ledger import MANUAL_OWNER  # noqa: E402
from gtheme.core.lock import process_lock  # noqa: E402
from gtheme.core.settings_backend import (  # noqa: E402
    BackendError,
    BackendErrorKind,
    MemoryBackend,
)
from gtheme.core.transaction import SettingWrite  # noqa: E402
from gtheme.panels.descriptor import Row  # noqa: E402
from gtheme.ui.pages import _style_common as common  # noqa: E402
from gtheme.ui.pages import colors, wallpaper  # noqa: E402
from gtheme.ui.widgets import recording  # noqa: E402

pytestmark = pytest.mark.gtk

SCHEMA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<schemalist>
  <schema id="io.github.blyatiful1.GthemeWriteTest"
          path="/io/github/blyatiful1/gtheme-write-test/">
    <key name="a-name" type="s"><default>'Adwaita'</default></key>
  </schema>
</schemalist>
"""

ID = "io.github.blyatiful1.GthemeWriteTest"
NAME = f"gsettings:{ID} a-name"
ACCENT = "gsettings:org.gnome.desktop.interface accent-color"


class FakeWindow:
    """The slice of the window a page speaks through."""

    def __init__(self) -> None:
        self.toasts: list[str] = []

    def toast(self, text: str, **_kwargs: Any) -> None:
        self.toasts.append(text)


class RefusingBackend(MemoryBackend):
    """Reads like any store, refuses every write. A locked-down machine."""

    def set(self, key: str, value: str) -> None:
        raise BackendError(BackendErrorKind.COMMIT_FAILED, f"refused {key}", key=key)


@pytest.fixture(autouse=True)
def _fresh_burst():
    recording.forget_burst()
    yield
    recording.forget_burst()


def _picker_descriptor() -> Row:
    return Row.model_validate(
        {
            "schema_id": ID,
            "key": "a-name",
            "title": "App style",
            "subtitle": "How buttons and menus look.",
            "kind": "picker",
            "reset": True,
        }
    )


# --------------------------------------------------------------------------
# H3 + M7 through a hand-built picker
# --------------------------------------------------------------------------


def test_a_picker_write_is_recorded_like_any_other(schema_source_factory):
    backend = MemoryBackend(schema_source=schema_source_factory(SCHEMA_XML))
    widget, _refresh = common.picker_row(backend, _picker_descriptor(), [("adw-gtk3", "adw-gtk3")])
    widget.set_selected(0)

    assert backend.get(NAME) == "'adw-gtk3'"
    assert Baseline(backend=backend).load().settings[NAME]["saved"] == "'Adwaita'"
    assert NAME in ledger_store.read_ledger().get(MANUAL_OWNER, {}).get("settings", [])


def test_a_refused_picker_says_so_instead_of_showing_a_lie(schema_source_factory):
    backend = RefusingBackend(schema_source=schema_source_factory(SCHEMA_XML))
    widget, _refresh = common.picker_row(backend, _picker_descriptor(), [("adw-gtk3", "adw-gtk3")])
    widget.set_selected(0)

    assert backend.get(NAME) == "'Adwaita'"
    assert widget.get_subtitle().startswith("Not changed.")


def test_a_picker_refused_because_something_else_is_applying(schema_source_factory):
    backend = MemoryBackend(schema_source=schema_source_factory(SCHEMA_XML))
    widget, _refresh = common.picker_row(backend, _picker_descriptor(), [("adw-gtk3", "adw-gtk3")])
    with process_lock():
        widget.set_selected(0)

    assert backend.get(NAME) == "'Adwaita'"
    assert "Something else is changing your desktop" in widget.get_subtitle()


# --------------------------------------------------------------------------
# H3 + M7 through the highlight-colour dots
# --------------------------------------------------------------------------


def _accent_row_descriptor() -> Row:
    return Row.model_validate(
        {
            "schema_id": "org.gnome.desktop.interface",
            "key": "accent-color",
            "title": "Highlight colour",
            "subtitle": "The colour used to show what is selected.",
            "kind": "color",
        }
    )


@pytest.mark.mutating
def test_choosing_a_highlight_colour_is_recorded(memory_settings):
    """``accent-color`` is a page row *and* a setting three shipped Looks write.

    That overlap is what made H3 permanent rather than merely annoying: an
    unrecorded edit here poisons what "before gtheme" means for this exact
    setting.
    """
    with core_backends.use_backend(memory_settings):
        widget, _refresh = colors._accent_row(memory_settings, _accent_row_descriptor())
        before = memory_settings.get(ACCENT)
        _press_first_dot(widget)

    assert Baseline(backend=memory_settings).load().settings[ACCENT]["saved"] == before
    assert ACCENT in ledger_store.read_ledger().get(MANUAL_OWNER, {}).get("settings", [])


@pytest.mark.mutating
def test_a_refused_highlight_colour_says_why(memory_settings, schema_source_factory):
    backend = RefusingBackend(schema_source=memory_settings.schema_source)
    with core_backends.use_backend(backend):
        widget, _refresh = colors._accent_row(backend, _accent_row_descriptor())
        _press_first_dot(widget)

    assert widget.get_subtitle().startswith("Not changed.")


def _press_first_dot(widget: Any) -> None:
    for child in _walk(widget):
        if isinstance(child, Gtk.ToggleButton) and not child.get_active():
            child.set_active(True)
            return
    raise AssertionError("the highlight-colour row has no dots to press")


def _walk(widget: Any):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from _walk(child)
        child = child.get_next_sibling()


# --------------------------------------------------------------------------
# M7 through the picture wall
# --------------------------------------------------------------------------


@pytest.mark.mutating
def test_a_refused_background_picture_says_why(memory_settings, tmp_dest_root, tmp_path):
    source = tmp_path / "holiday.png"
    from gi.repository import GdkPixbuf

    GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 4, 4).savev(
        str(source), "png", [], []
    )
    backend = RefusingBackend(schema_source=memory_settings.schema_source)
    window = FakeWindow()
    row = wallpaper._load_domain_rows()["picture-uri"]

    with core_backends.use_backend(backend):
        wallpaper._install_custom_wallpaper(window, backend, row, source, lambda: None)

    assert window.toasts, "a refused picture must not be silent"
    assert window.toasts[-1].startswith("Not changed.")


# --------------------------------------------------------------------------
# M3 — a compound write that cannot even start
# --------------------------------------------------------------------------


class _NoRoom:
    """A transaction that fails the way a full state directory does.

    ``Transaction.apply`` opens the lock file and makes the state directory
    *before* its own guarded section, so this failure is an ``OSError`` and not
    a ``TransactionError`` — which is exactly why the single ``except`` arm
    missed it.
    """

    def __init__(self, ops: Any) -> None:
        self.ops = ops

    def apply(self, *_args: Any, **_kwargs: Any) -> None:
        raise PermissionError(13, "Permission denied")


def test_a_compound_change_that_cannot_start_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(common, "Transaction", _NoRoom)
    window = FakeWindow()

    done = common.apply_ops(
        window, [SettingWrite(NAME, "'adw-gtk3'", component="colours")], done="Changed."
    )

    assert done is False, "the page must know the change did not happen"
    assert window.toasts, "and the person must be told, in a sentence"
    assert "could not be made" in window.toasts[-1]
    assert "Permission denied" in window.toasts[-1]


def test_a_compound_change_that_works_still_says_so(monkeypatch):
    class _Fine(_NoRoom):
        def apply(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    monkeypatch.setattr(common, "Transaction", _Fine)
    window = FakeWindow()

    assert common.apply_ops(window, [SettingWrite(NAME, "'x'")], done="Changed.") is True
    assert window.toasts == ["Changed."]
