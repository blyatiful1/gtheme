"""What the Looks page shows before a change, and what it admits afterwards.

Six findings, one subject: this page is where the app's promises are made, and
every one of these is a place where it made one and then did not keep it.

* **H2** — an unknown failure was wrapped as ``rolled_back=True``, so the app
  said "Nothing was changed. Your desktop is exactly as it was." about
  precisely the failures that did not unwind, and the honest wording written
  for that case could never be reached. The dialog also offered only "Close",
  with the way back one page away and unnamed.
* **M6** — undo from the toast reported failure whenever the restore *skipped*
  anything, which happens on the success path.
* **M15** — ``Adw.Toast`` renders Pango markup, and a Look's title is written
  by whoever wrote the Look.
* **U4** — the preview showed component counts and nothing else, over a
  ``DiffEntry`` that has carried ``before``/``after`` all along.
* **L8** — ``min_shell`` was compared in the compiler and no caller ever handed
  the compiler a version, so the warning could not fire in the running app.
* **X3** — a restore point that could only be taken in part reported nothing,
  after the dialog had already promised the way back.

Marked ``gtk``: the page module imports libadwaita. Nothing is presented — the
dialogs are captured — and every write goes to an in-memory settings store, a
temporary Looks folder and a temporary state directory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for the Looks page")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from gtheme.core import restorepoints  # noqa: E402
from gtheme.core.backends import use_backend  # noqa: E402
from gtheme.core.settings_backend import MemoryBackend  # noqa: E402
from gtheme.core.transaction import (  # noqa: E402
    Diff,
    DiffEntry,
    ExtensionEnable,
    ExtensionInstall,
    FileRemove,
    FileWrite,
    SettingWrite,
    TransactionError,
)
from gtheme.prefs import Prefs  # noqa: E402
from gtheme.preset.loader import load  # noqa: E402
from gtheme.ui.applyrunner import ApplyRunner  # noqa: E402
from gtheme.ui.pages import looks  # noqa: E402
from gtheme.ui.search import escape_markup  # noqa: E402

pytestmark = pytest.mark.gtk


@pytest.fixture(autouse=True, scope="module")
def _adw():
    if not Gtk.init_check():
        pytest.skip("no display is available for GTK — run under gtk4-broadwayd")
    Adw.init()


class FakeShell:
    """A desktop that answers the one question the preview asks it."""

    def __init__(self, version: str | None = "49") -> None:
        self.proxy = self
        self._version = version

    def shell_version(self) -> str | None:
        return self._version


class FakeWindow:
    """Everything the page asks of the window, and nothing else.

    The runner is deliberately not threaded: an apply that finishes on the
    calling thread is what lets a test read the dialog it produced.
    """

    def __init__(self, prefs: Prefs, *, shell: Any = None) -> None:
        self.prefs = prefs
        self.toasts = Adw.ToastOverlay()
        self.runner = ApplyRunner(None, threaded=False)
        self.shell = shell
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
{extra}

[palette]
bg = "#101010"
accent = "#52E0A4"

[[settings]]
key = "gsettings:org.gnome.desktop.interface icon-theme"
value = "'Papirus-Dark'"
component = "icons"

[[files]]
src = "files/demo.conf"
dest = "~/.config/demo/demo.conf"
"""


def write_look(directory: Path, name="testlook", title="Test Look", extra="") -> Path:
    folder = directory / name
    (folder / "files").mkdir(parents=True)
    (folder / "files" / "demo.conf").write_text("colour = green\n", encoding="utf-8")
    (folder / "theme.toml").write_text(
        THEME_TOML.format(name=name, title=title, extra=extra), encoding="utf-8"
    )
    return folder


def a_tile(themes_dir: Path, **kwargs) -> looks.LookTile:
    return looks.tiles_from_results([load(write_look(themes_dir, **kwargs))])[0]


def capture_dialogs(action) -> list[Adw.AlertDialog]:
    """Run something that presents dialogs and hand them back, in order."""
    seen: list[Adw.AlertDialog] = []
    original = Adw.AlertDialog.present

    def spy(self, *_args):
        seen.append(self)

    Adw.AlertDialog.present = spy
    try:
        action()
    finally:
        Adw.AlertDialog.present = original
    return seen


def capture_toasts(action) -> list[Adw.Toast]:
    """Every toast the page put on the overlay, as the widget itself."""
    seen: list[Adw.Toast] = []
    original = Adw.ToastOverlay.add_toast

    def spy(self, toast):
        seen.append(toast)

    Adw.ToastOverlay.add_toast = spy
    try:
        action()
    finally:
        Adw.ToastOverlay.add_toast = original
    return seen


class Boom:
    """A transaction that fails the way the engine's escapes fail: not politely."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error or RuntimeError("the settings store stopped answering")

    def apply(self, _report=None, **_kwargs):
        raise self.error


class Landed:
    """A transaction that works, and reports what it could not do."""

    def __init__(self, **fields: Any) -> None:
        self.restore_point = fields.pop("restore_point", "2026-08-28-120000")
        self.restore_warnings = fields.pop("restore_warnings", [])
        self.cleanup_warnings = fields.pop("cleanup_warnings", [])
        self.cleanup_kept = fields.pop("cleanup_kept", 0)
        self.cleanup_dead = fields.pop("cleanup_dead", 0)

    def apply(self, _report=None, **_kwargs):
        return self


# -- H2: an unknown failure is an unknown desktop --------------------------


def test_an_unknown_failure_never_claims_nothing_was_changed(config_dir, themes_dir, backend):
    """The one sentence a half-applied desktop must never be told."""
    page = looks.build(FakeWindow(Prefs()))
    tile = a_tile(themes_dir)

    dialogs = capture_dialogs(lambda: page._apply(tile, Boom()))

    assert dialogs, "a failure is always said out loud"
    body = dialogs[0].get_body()
    assert dialogs[0].get_heading() == looks.COPY["half-heading"]
    assert looks.COPY["half-body"] in body
    assert looks.COPY["failed-body"] not in body
    assert "the settings store stopped answering" in body


def test_a_failure_offers_the_moment_it_saved_rather_than_only_close(
    config_dir, themes_dir, backend, state_dir
):
    """"Close" is not an answer to "my desktop is half changed".

    The restore point taken for this very apply is the thing that fixes it, so
    the dialog offers it. It is recognised by being *new*: an older moment from
    some earlier session is not what this apply saved, and offering it as if it
    were would put the desktop somewhere nobody asked for.
    """
    page = looks.build(FakeWindow(Prefs()))
    tile = a_tile(themes_dir)
    key = "gsettings:org.gnome.desktop.interface icon-theme"
    backend.set(key, "'Adwaita'")

    class SavesThenFails(Boom):
        def apply(self, _report=None, **_kwargs):
            restorepoints.capture([key], label="Before Test Look", backend=backend)
            raise self.error

    undone: list[str] = []
    page._undo = lambda point_id: undone.append(point_id)  # type: ignore[method-assign]

    dialogs = capture_dialogs(lambda: page._apply(tile, SavesThenFails()))
    dialog = dialogs[0]

    assert dialog.has_response("undo"), "the way back is on the dialog that reports the failure"
    assert dialog.get_response_label("undo") == looks.COPY["failure-undo"]
    dialog.emit("response", "undo")
    assert undone == [restorepoints.list_restore_points()[0].id]


def test_a_failure_with_no_new_moment_behind_it_offers_nothing_it_cannot_do(
    config_dir, themes_dir, backend, state_dir
):
    """No moment was taken, so no moment is offered. Close is the honest answer."""
    page = looks.build(FakeWindow(Prefs()))
    tile = a_tile(themes_dir)

    dialog = capture_dialogs(lambda: page._apply(tile, Boom()))[0]

    assert not dialog.has_response("undo")
    assert dialog.has_response("close")


def test_a_rolled_back_failure_still_reassures(config_dir, themes_dir, backend):
    """The fix must not turn every failure into the frightening one."""
    page = looks.build(FakeWindow(Prefs()))
    tile = a_tile(themes_dir)
    error = TransactionError("no room left on the disk", rolled_back=True)

    dialog = capture_dialogs(lambda: page._apply(tile, Boom(error)))[0]

    assert dialog.get_heading() == looks.COPY["failed-heading"]
    assert looks.COPY["failed-body"] in dialog.get_body()


# -- M6: an undo that worked says it worked --------------------------------


class Restored:
    def __init__(self, *, transaction: Any, warnings: list[str]) -> None:
        self.transaction = transaction
        self.warnings = warnings


def test_an_undo_that_skipped_something_it_no_longer_has_is_not_a_failure(
    config_dir, themes_dir, backend, monkeypatch
):
    """Warnings on the success path are named skips, not a broken restore.

    A key from a previous Look whose add-on has since been removed is skipped
    at undo — the desktop is correctly back, and the app used to answer that
    with "gtheme could not put everything back."
    """
    page = looks.build(FakeWindow(Prefs()))
    monkeypatch.setattr(
        looks.restorepoints,
        "apply_point",
        lambda *_a, **_k: Restored(
            transaction=object(), warnings=["one add-on is no longer on this computer"]
        ),
    )

    toasts = capture_toasts(lambda: page._undo("2026-08-28-120000"))

    assert [t.get_title() for t in toasts] == [escape_markup(looks.COPY["undone"])]


def test_an_undo_that_wrote_nothing_at_all_is_still_reported_as_one(
    config_dir, themes_dir, backend, monkeypatch
):
    """The other half of the same test: a real failure must stay a failure."""
    page = looks.build(FakeWindow(Prefs()))
    monkeypatch.setattr(
        looks.restorepoints,
        "apply_point",
        lambda *_a, **_k: Restored(transaction=None, warnings=["that saved moment is gone"]),
    )

    toasts = capture_toasts(lambda: page._undo("2026-08-28-120000"))

    assert [t.get_title() for t in toasts] == [escape_markup(looks.COPY["undo-failed"])]


# -- M15: a Look's title is not this app's markup --------------------------


def test_a_look_named_with_an_ampersand_still_says_it_is_on(config_dir, themes_dir, backend):
    """"Black & Gold" is invalid markup, and rendered the confirmation empty."""
    page = looks.build(FakeWindow(Prefs()))

    toasts = capture_toasts(lambda: page._toast("Black & Gold is on now."))

    assert toasts[0].get_title() == "Black &amp; Gold is on now."


def test_the_apps_own_sentence_with_an_ampersand_in_it_survives_too(
    config_dir, themes_dir, backend
):
    """Not only a Look's title: this app's own copy names a page with an "&" in it.

    "gtheme could not put everything back. Open Undo & Restore Points." is
    invalid markup, so the toast that says the safety net failed was itself
    rendering as nothing at all.
    """
    page = looks.build(FakeWindow(Prefs()))

    toasts = capture_toasts(lambda: page._toast(looks.COPY["undo-failed"]))

    assert toasts[0].get_title() == escape_markup(looks.COPY["undo-failed"])
    assert "&amp;" in toasts[0].get_title()


def test_a_look_cannot_write_its_own_sentence_into_a_toast(config_dir, themes_dir, backend):
    """The malicious half: a title that is markup must not become one."""
    page = looks.build(FakeWindow(Prefs()))
    hostile = '<span size="xx-large">Nothing was changed.</span> is on now.'

    toasts = capture_toasts(lambda: page._toast(hostile))

    assert "<span" not in toasts[0].get_title()
    assert "&lt;span" in toasts[0].get_title()


# -- U4: show exactly what changes -----------------------------------------


def test_the_detail_layer_names_the_file_the_key_and_the_two_values():
    diff = Diff(
        entries=[
            DiffEntry(
                op=FileWrite(src="/look/x.conf", dest="~/.config/demo/demo.conf"),
                component="terminal",
                summary="Terminal",
                before=None,
                after="digest",
            ),
            DiffEntry(
                op=SettingWrite(key="gsettings:org.gnome.desktop.interface icon-theme", value="'P'"),
                component="icons",
                summary="Icons",
                before="'Adwaita'",
                after="'P'",
            ),
        ]
    )

    lines = looks.detail_lines(diff)

    assert lines[0] == f"~/.config/demo/demo.conf — {looks.COPY['details-file-add']}"
    assert lines[1] == "org.gnome.desktop.interface icon-theme: 'Adwaita' → 'P'"
    assert "gsettings" not in lines[1], "the machinery is not a word this app says"


def test_the_detail_layer_says_which_files_are_replaced_and_which_are_deleted():
    diff = Diff(
        entries=[
            DiffEntry(
                op=FileWrite(src="/look/y.conf", dest="~/.config/demo/kept.conf"),
                component="files",
                summary="1 file",
                before="an older digest",
                after="digest",
            ),
            DiffEntry(
                op=FileRemove(dest="~/.config/demo/gone.conf"),
                component="removed-files",
                summary="Remove gone.conf",
                before="digest",
                after=None,
            ),
        ]
    )

    lines = looks.detail_lines(diff)

    assert lines[0].endswith(looks.COPY["details-file-replace"])
    assert lines[1].endswith(looks.COPY["details-file-remove"])


def test_a_file_that_can_start_programs_is_named_in_both_layers():
    """The consequential tier is named in the headline *and* in the detail.

    ``core.policy`` allows a Look to write a program's own settings file and
    ``to_novice_lines`` names each one rather than counting it. The detail
    layer must not undo that by folding them back in with the wallpaper: the
    destination is the whole point of allowing them at all.
    """
    diff = Diff(
        entries=[
            DiffEntry(
                op=FileWrite(src="/look/starship.toml", dest="~/.config/starship.toml"),
                component="consequential-files",
                summary="starship.toml — sets up your text prompt",
                before="an older digest",
                after="digest",
            )
        ]
    )

    assert diff.to_novice_lines() == ["starship.toml — sets up your text prompt"]
    assert looks.detail_lines(diff) == [
        f"~/.config/starship.toml — {looks.COPY['details-file-replace']}"
    ]


def test_the_detail_layer_names_add_ons_this_computer_already_knows():
    diff = Diff(
        entries=[
            DiffEntry(
                op=ExtensionEnable(uuid="blur-my-shell@aunetx"),
                component="addons",
                summary="1 add-on",
            ),
            DiffEntry(
                op=ExtensionInstall(uuid="stranger@example.com"),
                component="addons",
                summary="1 add-on",
            ),
        ]
    )

    lines = looks.detail_lines(diff, names={"blur-my-shell@aunetx": "Blur my Shell"})

    assert lines[0] == f"Blur my Shell (blur-my-shell@aunetx) — {looks.COPY['details-addon-on']}"
    assert lines[1] == f"stranger@example.com — {looks.COPY['details-addon-get']}"


def test_an_add_ons_own_name_is_read_off_this_computer(tmp_path, monkeypatch):
    """Offline by construction: the name comes from the add-on's own folder."""
    import json

    data_home = tmp_path / "data"
    folder = data_home / "gnome-shell" / "extensions" / "demo@example.com"
    folder.mkdir(parents=True)
    (folder / "metadata.json").write_text(
        json.dumps({"uuid": "demo@example.com", "name": "Demo Add-on"}), encoding="utf-8"
    )
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))

    assert looks.addon_names(["demo@example.com"]) == {"demo@example.com": "Demo Add-on"}
    assert looks.addon_names([]) == {}


def test_the_plan_carries_the_detail_layer_and_the_preview_offers_it(
    config_dir, themes_dir, backend, tmp_dest_root
):
    """The headline stays the headline; the detail is one click behind it."""
    page = looks.build(FakeWindow(Prefs()))
    tile = a_tile(themes_dir)
    plan = looks.plan_apply(tile, installed=[])

    assert plan.lines, "the everyday summary is still what the body says"
    assert any("~/.config/demo/demo.conf" in line for line in plan.details)
    assert any("icon-theme" in line for line in plan.details)
    assert not any("icon-theme" in line for line in plan.lines), "the headline stays plain"

    dialog = capture_dialogs(lambda: page._show_preview(tile, plan))[0]
    expander = dialog.get_extra_child()
    assert isinstance(expander, Gtk.Expander)
    assert expander.get_label() == looks.COPY["details-title"]
    assert not expander.get_expanded(), "closed until somebody asks for it"


# -- L8: a Look made for a newer desktop says so ---------------------------


def test_a_look_that_wants_a_newer_desktop_warns_when_the_version_is_known(
    themes_dir, backend, tmp_dest_root
):
    tile = a_tile(themes_dir, extra='min_shell = "99"')

    quiet = looks.plan_apply(tile, installed=[])
    warned = looks.plan_apply(tile, installed=[], shell_version="49")

    assert quiet.warnings == [], "an unmeasured desktop is never accused"
    assert any("newer version of GNOME" in warning for warning in warned.warnings)
    assert warned.warnings[0] in warned.body()


def test_the_page_hands_the_preview_the_version_the_window_already_knows(
    config_dir, themes_dir, backend, tmp_dest_root
):
    """The half that was missing: the compiler could warn and nobody asked it to."""
    page = looks.build(FakeWindow(Prefs(), shell=FakeShell("49")))
    tile = a_tile(themes_dir, extra='min_shell = "99"')

    dialog = capture_dialogs(lambda: page._on_tile_activated(tile))[0]

    assert "newer version of GNOME" in dialog.get_body()


def test_a_desktop_that_will_not_say_its_version_is_not_guessed_at(
    config_dir, themes_dir, backend
):
    page = looks.build(FakeWindow(Prefs(), shell=FakeShell(None)))
    assert page._shell_version() is None
    assert looks.build(FakeWindow(Prefs()))._shell_version() is None


# -- X3 and M1: what the change could not do, said out loud ----------------


def test_a_moment_saved_only_in_part_is_admitted_after_the_look_lands(
    config_dir, themes_dir, backend
):
    """The promise was "you can put it back with one click". Not all of it."""
    page = looks.build(FakeWindow(Prefs()))
    tile = a_tile(themes_dir)
    outcome = Landed(restore_warnings=["one picture could not be saved"])

    dialogs = capture_dialogs(lambda: page._apply(tile, outcome))

    assert dialogs, "an incomplete moment is never silent"
    body = dialogs[0].get_body()
    assert dialogs[0].get_heading() == looks.COPY["after-heading"]
    assert looks.COPY["snapshot-partial"] in body
    assert "one picture could not be saved" in body


def test_what_the_previous_look_left_behind_is_said_with_what_can_be_done(
    config_dir, themes_dir, backend
):
    page = looks.build(FakeWindow(Prefs()))
    tile = a_tile(themes_dir)
    outcome = Landed(
        cleanup_warnings=["the old background picture could not be put back"],
        cleanup_kept=1,
        cleanup_dead=1,
    )

    body = capture_dialogs(lambda: page._apply(tile, outcome))[0].get_body()

    assert looks.COPY["cleanup-partial"] in body
    assert "the old background picture could not be put back" in body
    assert looks.COPY["cleanup-kept"] in body
    assert looks.COPY["cleanup-dead"] in body


def test_an_apply_with_nothing_to_admit_says_nothing_extra(config_dir, themes_dir, backend):
    """No second dialog on the ordinary path — the toast is the whole report."""
    page = looks.build(FakeWindow(Prefs()))
    tile = a_tile(themes_dir)

    dialogs = capture_dialogs(lambda: page._apply(tile, Landed()))

    assert dialogs == []
