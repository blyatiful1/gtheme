"""The launcher entry, the store listing and the icons.

These three files are the only part of gtheme a person sees before the app is
even open: the entry in their list of applications, the picture on it, and the
page an app store shows. They are checked here for the things that silently
break them — an icon name that does not match the app id (blank icon), a
window class that does not match (a second, iconless entry in the dock while
the app runs), a screenshot that promises a window nobody will see.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from gtheme.ui import jargon

REPO = Path(__file__).resolve().parents[2]
APP_ID = "io.github.blyatiful1.Gtheme"
DESKTOP = REPO / "data" / f"{APP_ID}.desktop"
METAINFO = REPO / "data" / f"{APP_ID}.metainfo.xml"
ICONS = REPO / "data" / "icons" / "hicolor"
SHOTS = REPO / "docs" / "media" / "screenshots"
RAW_PREFIX = "https://raw.githubusercontent.com/blyatiful1/gtheme/main/docs/media/screenshots/"


def _entry() -> dict[str, str]:
    """The [Desktop Entry] group as a plain dict."""
    values: dict[str, str] = {}
    in_group = False
    for line in DESKTOP.read_text().splitlines():
        line = line.strip()
        if line.startswith("["):
            in_group = line == "[Desktop Entry]"
            continue
        if in_group and "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            values[key] = value
    return values


def _png_size(path: Path) -> tuple[int, int]:
    """Width and height straight out of the PNG header — no image library."""
    header = path.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    width, height = struct.unpack(">II", header[16:24])
    return width, height


# --- the launcher entry -----------------------------------------------------


def test_desktop_entry_has_the_keys_that_make_it_work() -> None:
    entry = _entry()
    assert entry["Type"] == "Application"
    assert entry["Name"] == "Gtheme"
    assert entry["Terminal"] == "false"
    assert entry["StartupNotify"] == "true"
    # A blank icon in the applications list is what a mismatch here looks like.
    assert entry["Icon"] == APP_ID
    # A mismatch here means a running gtheme shows up as a second, nameless
    # window in the dock instead of highlighting its own entry.
    assert entry["StartupWMClass"] == APP_ID
    assert entry["Categories"] == "GNOME;GTK;Settings;DesktopSettings;"
    assert entry["Exec"].split()[0] == "gtheme"
    assert "NoDisplay" not in entry, "the app must appear in the applications list"


def test_desktop_entry_keywords_are_words_a_newcomer_would_type() -> None:
    keywords = {k for k in _entry()["Keywords"].split(";") if k}
    assert {"wallpaper", "dark mode", "appearance"} <= keywords


def test_the_app_id_matches_the_one_the_code_uses() -> None:
    from gtheme import APP_ID as code_app_id

    assert code_app_id == APP_ID


def test_desktop_file_validate_is_happy() -> None:
    tool = shutil.which("desktop-file-validate")
    if tool is None:
        pytest.skip("desktop-file-validate not installed (Arch: desktop-file-utils)")
    proc = subprocess.run([tool, str(DESKTOP)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --- the store listing ------------------------------------------------------


def test_metainfo_agrees_with_the_launcher_entry() -> None:
    root = ET.parse(METAINFO).getroot()
    assert root.get("type") == "desktop-application"
    assert root.findtext("id") == APP_ID
    assert root.findtext("launchable") == f"{APP_ID}.desktop"
    assert root.findtext("project_license") == "MIT"
    assert root.findtext("metadata_license")
    assert root.findtext("summary") == _entry()["Comment"]


def test_every_screenshot_is_a_picture_that_exists() -> None:
    root = ET.parse(METAINFO).getroot()
    shots = root.findall("./screenshots/screenshot")
    assert len(shots) >= 5, "an app store listing with fewer than five pictures is a stub"
    assert [s.get("type") for s in shots].count("default") == 1

    for shot in shots:
        caption = (shot.findtext("caption") or "").strip()
        assert caption, "every screenshot needs a caption"
        image = shot.find("image")
        assert image is not None and image.text
        url = image.text.strip()
        assert url.startswith(RAW_PREFIX), f"{url} does not point into this repository"
        local = SHOTS / url[len(RAW_PREFIX):]
        assert local.is_file(), f"{local.name} is promised in the listing but not committed"
        width, height = _png_size(local)
        assert (int(image.get("width", 0)), int(image.get("height", 0))) == (width, height), (
            f"{local.name} is {width}x{height}, but the listing claims "
            f"{image.get('width')}x{image.get('height')}"
        )


def test_the_listing_speaks_plainly() -> None:
    """The store page is user-facing text and obeys the same word ban."""
    root = ET.parse(METAINFO).getroot()
    texts: list[tuple[str, str]] = [
        ("summary", root.findtext("summary") or ""),
        ("name", root.findtext("name") or ""),
    ]
    for i, para in enumerate(root.findall("./description//p")):
        texts.append((f"description p{i + 1}", "".join(para.itertext())))
    for i, item in enumerate(root.findall("./description//li")):
        texts.append((f"description item {i + 1}", "".join(item.itertext())))
    for i, caption in enumerate(root.findall("./screenshots/screenshot/caption")):
        texts.append((f"caption {i + 1}", "".join(caption.itertext())))
    entry = _entry()
    texts.append(("desktop Name", entry["Name"]))
    texts.append(("desktop Comment", entry["Comment"]))
    texts.append(("desktop GenericName", entry.get("GenericName", "")))

    problems = jargon.check_all(texts)
    assert problems == [], "\n".join(problems)


def test_appstreamcli_is_happy() -> None:
    tool = shutil.which("appstreamcli")
    if tool is None:
        pytest.skip("appstreamcli not installed (Arch: appstream, Debian: appstream)")
    proc = subprocess.run(
        [tool, "validate", "--no-net", str(METAINFO)], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --- the icons --------------------------------------------------------------


def test_both_icons_are_named_after_the_app_id() -> None:
    assert (ICONS / "scalable" / "apps" / f"{APP_ID}.svg").is_file()
    assert (ICONS / "symbolic" / "apps" / f"{APP_ID}-symbolic.svg").is_file()


def test_the_icons_are_real_drawings_and_not_placeholders() -> None:
    app = (ICONS / "scalable" / "apps" / f"{APP_ID}.svg").read_text()
    assert "PLACEHOLDER" not in app.upper()
    assert app.count("<path") + app.count("<rect") + app.count("<circle") >= 6, (
        "the app icon is too simple to be a designed icon"
    )
    assert 'viewBox="0 0 128 128"' in app


def test_the_symbolic_icon_is_one_colour_and_the_right_size() -> None:
    symbolic = (ICONS / "symbolic" / "apps" / f"{APP_ID}-symbolic.svg").read_text()
    assert 'viewBox="0 0 16 16"' in symbolic
    assert "PLACEHOLDER" not in symbolic.upper()
    # A symbolic icon is recoloured by the desktop, so it may carry exactly one
    # colour: the placeholder foreground every symbolic icon uses.
    colours = set(__import__("re").findall(r"#[0-9a-fA-F]{3,8}", symbolic))
    assert colours <= {"#222222"}, f"symbolic icons may not carry colours: {sorted(colours)}"
    assert "<linearGradient" not in symbolic


def test_the_icons_render() -> None:
    tool = shutil.which("rsvg-convert")
    if tool is None:
        pytest.skip("rsvg-convert not installed (Arch: librsvg)")
    for icon, size in (
        (ICONS / "scalable" / "apps" / f"{APP_ID}.svg", "256"),
        (ICONS / "symbolic" / "apps" / f"{APP_ID}-symbolic.svg", "16"),
    ):
        proc = subprocess.run(
            [tool, "-w", size, "-h", size, str(icon)], capture_output=True
        )
        assert proc.returncode == 0, proc.stderr.decode()
        assert proc.stdout[:8] == b"\x89PNG\r\n\x1a\n"
