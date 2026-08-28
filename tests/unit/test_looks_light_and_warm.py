"""DAYBREAK and HEARTH: the two Looks that need nothing installed first.

The audit's finding (persona-report 2.2) was that the shop window was four
dark rices built out of add-ons and terminal files — so the first thing a new
user could actually *use* depended on downloading between six and eleven GNOME
add-ons and having a fistful of fonts and icon themes already on the machine.
These two exist to be the opposite of that, and everything below pins the part
of them that is a promise rather than a taste:

* the collection is no longer all dark, and it has a warm end to it;
* neither Look turns on an add-on, so there is nothing to fetch;
* neither names a theme, icon set, pointer or font that is not part of GNOME;
* neither writes a file that has to be named in the preview one by one —
  which is the whole reason they are one picture and some settings;
* both carry a full terminal palette, so the Terminal page can *offer* the
  colours even though the Looks themselves touch no terminal.

``tests/unit/test_preset_bundled.py`` already runs the shared checks — they
load, they compile, they ship what they advertise — over every bundled Look
including these two. This file is only what is specific to the pair.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gtheme.core.policy import Tier, file_verdict
from gtheme.preset.loader import load
from gtheme.ui.pages.terminal import palette_from_look

PAIR = ("daybreak", "hearth")

#: Themes, icon sets, pointers and fonts that are part of GNOME itself. A Look
#: aimed at a machine where nothing has been installed may name these and
#: nothing else: naming ``adw-gtk3-dark`` or ``Papirus-Dark`` on a bare desktop
#: is a Look that half-applies and does not say so.
STOCK = frozenset(
    {
        "Adwaita",
        "Adwaita Sans 11",
        "Adwaita Mono 11",
    }
)

#: The interface settings whose value has to name something installed.
NAMES_SOMETHING_INSTALLED = (
    "gsettings:org.gnome.desktop.interface gtk-theme",
    "gsettings:org.gnome.desktop.interface icon-theme",
    "gsettings:org.gnome.desktop.interface cursor-theme",
    "gsettings:org.gnome.desktop.interface font-name",
    "gsettings:org.gnome.desktop.interface document-font-name",
    "gsettings:org.gnome.desktop.interface monospace-font-name",
)

LIGHT = ("'prefer-light'", "'default'")

NIGHT_LIGHT_ON = "gsettings:org.gnome.settings-daemon.plugins.color night-light-enabled"
NIGHT_LIGHT_WARMTH = "gsettings:org.gnome.settings-daemon.plugins.color night-light-temperature"


@pytest.fixture(params=PAIR)
def look(request, repo_root: Path):
    return request.param, repo_root / "themes" / request.param


def _settings(directory: Path) -> dict[str, str]:
    return {s.key: s.value for s in load(directory).preset.settings}


# ── the finding itself ───────────────────────────────────────────────────


def test_the_collection_is_no_longer_all_dark(repo_root: Path):
    """At least one bundled Look leaves the desktop light. This was the audit."""
    light = []
    for folder in sorted((repo_root / "themes").iterdir()):
        if not (folder / "theme.toml").is_file():
            continue
        scheme = _settings(folder).get("gsettings:org.gnome.desktop.interface color-scheme")
        if scheme in LIGHT:
            light.append(folder.name)
    assert light, "every bundled Look still asks for a dark desktop"


def test_the_light_one_is_cool_and_the_warm_one_is_warm(repo_root: Path):
    """Two Looks, not one twice: different highlight, different wallpaper."""
    day = _settings(repo_root / "themes" / "daybreak")
    hearth = _settings(repo_root / "themes" / "hearth")
    accent = "gsettings:org.gnome.desktop.interface accent-color"
    assert day[accent] == "'green'"
    assert hearth[accent] == "'orange'"
    assert day[accent] != hearth[accent]


def test_both_of_them_leave_the_desktop_light(look):
    _name, directory = look
    scheme = _settings(directory)["gsettings:org.gnome.desktop.interface color-scheme"]
    assert scheme in LIGHT, scheme


# ── nothing to install ───────────────────────────────────────────────────


def test_it_turns_on_no_add_ons(look):
    """No download from extensions.gnome.org, no confirmation box, no wait."""
    name, directory = look
    preset = load(directory).preset
    assert preset.extensions.enable == [], name
    assert preset.extensions.install == [], name
    assert preset.extensions.settings == [], name


def test_every_theme_and_font_it_names_ships_with_gnome(look):
    name, directory = look
    settings = _settings(directory)
    for key in NAMES_SOMETHING_INSTALLED:
        assert key in settings, f"{name} does not set {key}"
        value = settings[key].strip("'")
        assert value in STOCK, f"{name}: {key} names {value!r}, which may not be there"


def test_it_copies_exactly_one_file_and_that_file_is_its_wallpaper(look):
    name, directory = look
    files = load(directory).preset.files
    assert len(files) == 1, f"{name} copies {len(files)} files"
    assert files[0].dest.startswith("~/.local/share/backgrounds/"), files[0].dest
    assert files[0].src.endswith(".png"), files[0].src
    assert files[0].template is False, "a picture is not a text file"


def test_it_writes_nothing_the_preview_has_to_name_one_by_one(look, tmp_dest_root: Path):
    """The point of keeping these two to a wallpaper.

    Three of the four older Looks write ``~/.config/starship.toml`` and their
    terminals' own configuration, and those are CONSEQUENTIAL: allowed, but
    listed individually in the plan because their file formats can also name a
    program to run. These two never reach that tier, so their whole plan is
    ordinary decoration.
    """
    name, directory = look
    for entry in load(directory).preset.files:
        verdict = file_verdict(entry.dest, root=tmp_dest_root)
        assert verdict.tier is Tier.ALLOWED, f"{name}: {entry.dest} — {verdict.sentence()}"


# ── the settings they do write ───────────────────────────────────────────


def test_the_wallpaper_setting_points_at_the_file_the_look_copies(look):
    name, directory = look
    preset = load(directory).preset
    copied = preset.files[0].dest.removeprefix("~/")
    expected = "'file://{{ home }}/" + copied + "'"
    pointers = [
        s.value
        for s in preset.settings
        if s.key.endswith("picture-uri") or s.key.endswith("picture-uri-dark")
    ]
    assert pointers, name
    assert set(pointers) == {expected}, name


def test_hearth_turns_night_light_on_because_that_is_what_warm_means(repo_root: Path):
    settings = _settings(repo_root / "themes" / "hearth")
    assert settings[NIGHT_LIGHT_ON] == "true"
    assert settings[NIGHT_LIGHT_WARMTH] == "uint32 3400"


def test_daybreak_sets_the_warmth_without_touching_the_switch(repo_root: Path):
    """Turning somebody's Night Light off is as rude as turning it on."""
    settings = _settings(repo_root / "themes" / "daybreak")
    assert NIGHT_LIGHT_ON not in settings
    assert settings[NIGHT_LIGHT_WARMTH] == "uint32 4200"


def test_the_night_light_change_is_described_as_night_light(look):
    """So the preview says "Warmer colours in the evening" rather than "other"."""
    _name, directory = look
    for setting in load(directory).preset.settings:
        if "night-light" in setting.key:
            assert setting.component.value == "night-light", setting.key


# ── the terminal colours they offer but do not write ─────────────────────


def test_it_describes_a_whole_terminal_palette_without_writing_one(look):
    name, directory = look
    preset = load(directory).preset
    assert not [f for f in preset.files if f.dest.endswith(("config", ".toml", ".conf"))], (
        f"{name} writes a terminal file, which these two are meant not to do"
    )
    palette = palette_from_look(preset)
    assert palette is not None, f"{name} offers the Terminal page nothing"
    assert len(palette.ansi) == 16, f"{name}: a partial ANSI set is worse than none"


def test_the_terminal_palette_is_a_light_one(look):
    """A light Look handing a terminal a black background is a broken promise."""
    _name, directory = look
    palette = palette_from_look(load(directory).preset)
    background = tuple(int(palette.background.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    foreground = tuple(int(palette.foreground.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    assert min(background) > 200, palette.background
    assert max(foreground) < 120, palette.foreground


# ── the picture ──────────────────────────────────────────────────────────


def test_the_wallpaper_is_the_size_a_desktop_wants(look):
    name, directory = look
    Image = pytest.importorskip("PIL.Image", reason="Pillow draws and reads the wallpapers")
    with Image.open(directory / load(directory).preset.files[0].src) as picture:
        assert picture.size == (2560, 1440), f"{name}: {picture.size}"
        assert picture.mode == "RGB", picture.mode


def test_the_wallpaper_is_a_picture_rather_than_a_flat_rectangle(look):
    """A gradient that went wrong renders as one colour and still opens fine."""
    name, directory = look
    Image = pytest.importorskip("PIL.Image", reason="Pillow draws and reads the wallpapers")
    with Image.open(directory / load(directory).preset.files[0].src) as picture:
        small = picture.resize((160, 90))
        colours = small.getcolors(maxcolors=160 * 90) or []
    assert colours, f"{name}: too many colours to count, which is not the failure mode"
    commonest = max(count for count, _colour in colours)
    assert commonest / (160 * 90) < 0.5, f"{name} is nearly a single colour"


def test_the_look_advertises_the_wallpaper_as_its_picture(look):
    """Until real photography lands, the tile shows the wallpaper itself."""
    _name, directory = look
    preset = load(directory).preset
    assert preset.meta.screenshots == [preset.files[0].src]
