"""Saving your own desktop has to produce a whole Look (persona-report 2.7, L3).

For a long time "Save my current desktop as a Look" produced a Look that was a
wallpaper and a list of settings. It carried no ``[[files]]`` beyond the picture
and no ``[palette]`` at all, while the four Looks shipped in this repository
carry eighteen to twenty files each. Two things followed, and both were silent:
every file gtheme had written to make that desktop — the terminal's colours, the
prompt's palette — was thrown away, and the Terminal page went permanently blank
under the user's own Look, because it reads its colours from ``[palette]``.

L3 is the same class of defect one layer down. The scan that replaces this
computer's home folder with ``{{ home }}`` matched the literal shape
``/home/<name>`` and nothing else, so on Silverblue (``/var/home/you``), on a
relocated ``$HOME``, or on a home folder living on a mounted volume, every
captured path went out with the login name still in it — and pointed at a
folder the person receiving the Look does not have.

Everything here runs against the in-memory settings backend, a temporary
destination root and a temporary state folder, so the desktop running the suite
is never read and never written.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from gtheme.core import ledger
from gtheme.preset import capture as cap
from gtheme.preset.loader import load

mutating = pytest.mark.mutating

SCHEMA_ID = "org.gtheme.test.carry"
SCHEMA_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<schemalist>
  <schema id="{SCHEMA_ID}" path="/org/gtheme/test/carry/">
    <key name="icon-theme" type="s"><default>'Adwaita'</default></key>
    <key name="picture" type="s"><default>''</default></key>
  </schema>
  <schema id="org.gnome.desktop.background" path="/org/gtheme/test/carry-bg/">
    <key name="picture-uri" type="s"><default>''</default></key>
  </schema>
</schemalist>
"""

ICONS = f"gsettings:{SCHEMA_ID} icon-theme"
PICTURE = f"gsettings:{SCHEMA_ID} picture"
WALLPAPER = "gsettings:org.gnome.desktop.background picture-uri"


@pytest.fixture
def backend(memory_settings, schema_source_factory):
    memory_settings.schema_source = schema_source_factory(SCHEMA_XML)
    return memory_settings


def _wrote(root: Path, relative: str, contents: str = "written by gtheme\n") -> str:
    """Put a file where gtheme would have written one. Returns the claim."""
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(contents, encoding="utf-8")
    return str(target)


def _owned(look: str, *claims: str) -> None:
    """Record that ``look`` owns those destinations, as an apply would."""
    ledger.write_entry(look, list(claims), [])


def _save(backend, out: Path, keys=(ICONS,)) -> cap.CaptureResult:
    return cap.capture_share(list(keys), backend, out_dir=out, name="mine", title="Mine")


# ── the files gtheme wrote travel with the save ──────────────────────────


@mutating
def test_a_saved_desktop_carries_the_files_gtheme_wrote(
    backend, tmp_dest_root: Path, state_dir: Path, tmp_path: Path
):
    """The whole of persona-report 2.7: a saved Look shipped one file, ever.

    The ownership ledger is the record of what this app put on this desktop, so
    it is what the capture reads. Before this fix the assertion below found an
    empty list however much gtheme had written.
    """
    claim = _wrote(tmp_dest_root, ".config/ghostty/config", "background = 1a1b26\n")
    _owned("Some Look", claim)

    out = tmp_path / "look"
    result = _save(backend, out)

    assert [(f.src, f.dest) for f in result.preset.files] == [
        ("files/.config/ghostty/config", "~/.config/ghostty/config")
    ]
    assert (out / "files/.config/ghostty/config").read_text() == "background = 1a1b26\n"


@mutating
def test_two_files_of_the_same_name_do_not_overwrite_each_other(
    backend, tmp_dest_root: Path, state_dir: Path, tmp_path: Path
):
    """Two terminals both call their settings file ``config``.

    Naming what travels after the file alone — which is what the wallpaper
    bundling did, when the wallpaper was the only thing that travelled — would
    have one of them land on the other inside the Look.
    """
    _owned(
        "Some Look",
        _wrote(tmp_dest_root, ".config/ghostty/config", "ghostty\n"),
        _wrote(tmp_dest_root, ".config/kitty/config", "kitty\n"),
    )

    out = tmp_path / "look"
    result = _save(backend, out)

    assert sorted(f.src for f in result.preset.files) == [
        "files/.config/ghostty/config",
        "files/.config/kitty/config",
    ]
    assert (out / "files/.config/kitty/config").read_text() == "kitty\n"


@mutating
def test_a_saved_desktop_never_carries_a_file_a_look_may_not_write(
    backend, tmp_dest_root: Path, state_dir: Path, tmp_path: Path
):
    """The Wave A policy holds for gtheme's own output, not only for downloads.

    A Look carrying ``~/.config/autostart/x.desktop`` is refused whole, so a
    capture that put one in would produce a saved desktop that could never be
    put back on — and would quietly publish a file that runs at every login.
    """
    _owned(
        "Some Look",
        _wrote(tmp_dest_root, ".config/autostart/rice.desktop", "[Desktop Entry]\n"),
        _wrote(tmp_dest_root, ".config/ghostty/config", "background = 1a1b26\n"),
    )

    result = _save(backend, tmp_path / "look")

    assert [f.dest for f in result.preset.files] == ["~/.config/ghostty/config"]
    refused = [o for o in result.omissions if o.what == "~/.config/autostart/rice.desktop"]
    assert refused, result.omissions
    assert "program entry" in refused[0].reason


@mutating
def test_a_file_the_ledger_claims_that_is_gone_is_named_not_dropped(
    backend, tmp_dest_root: Path, state_dir: Path, tmp_path: Path
):
    """The ledger is written before the change it describes, so it outlives files."""
    _owned("Some Look", str(tmp_dest_root / ".config/ghostty/config"))

    result = _save(backend, tmp_path / "look")

    assert result.preset.files == []
    assert [(o.kind, o.what) for o in result.omissions if o.kind == "file"] == [
        ("file", "~/.config/ghostty/config")
    ]


@mutating
def test_a_saved_desktop_that_carries_files_is_still_a_valid_look(
    backend, tmp_dest_root: Path, state_dir: Path, tmp_path: Path
):
    """Whatever the capture writes has to survive the loader that reads it back."""
    _owned("Some Look", _wrote(tmp_dest_root, ".config/starship.toml", "add_newline = false\n"))

    out = tmp_path / "mine"  # the folder is the Look's name, as the app writes it
    _save(backend, out)

    loaded = load(out)
    assert loaded.errors == []
    assert loaded.warnings == []


@mutating
def test_a_wallpaper_gtheme_already_wrote_is_not_copied_in_twice(
    backend, tmp_dest_root: Path, state_dir: Path, tmp_path: Path
):
    """One picture, one copy: a Look's own wallpaper keeps the place it has."""
    picture = tmp_dest_root / ".local/share/backgrounds/rice/w.png"
    picture.parent.mkdir(parents=True)
    picture.write_bytes(b"pretend png")
    _owned("Some Look", str(picture))
    backend.set(WALLPAPER, f"'file://{picture}'")

    out = tmp_path / "look"
    result = _save(backend, out, keys=[WALLPAPER])

    assert [(f.src, f.dest) for f in result.preset.files] == [
        (
            "files/.local/share/backgrounds/rice/w.png",
            "~/.local/share/backgrounds/rice/w.png",
        )
    ]
    assert result.preset.settings[0].value == (
        "'file://{{ home }}/.local/share/backgrounds/rice/w.png'"
    )
    assert result.preset.meta.screenshots == ["files/.local/share/backgrounds/rice/w.png"]


@mutating
def test_a_home_folder_reached_through_a_link_still_carries_its_files(
    backend, tmp_dest_root: Path, state_dir: Path, tmp_path: Path, monkeypatch
):
    """One place, two spellings.

    An apply records the destination it resolved; the home folder as written
    may be a link to it. Measuring a claim against only one of the two would
    call every file gtheme wrote "outside your home folder" and save a Look
    with nothing in it.
    """
    claim = _wrote(tmp_dest_root, ".config/ghostty/config", "background = 1a1b26\n")
    linked = tmp_path / "linked-home"
    linked.symlink_to(tmp_dest_root)
    monkeypatch.setenv("GTHEME_DEST_ROOT", str(linked))
    _owned("Some Look", claim)

    result = _save(backend, tmp_path / "look")

    assert [f.dest for f in result.preset.files] == ["~/.config/ghostty/config"]


@mutating
def test_a_wallpaper_named_like_a_file_gtheme_wrote_gets_a_name_of_its_own(
    backend, tmp_dest_root: Path, state_dir: Path, tmp_path: Path
):
    """Two files inside one Look cannot share a name.

    The second would not fail to copy — it would land on the first, and the
    Look would ship one picture where it lists two.
    """
    _owned("Some Look", _wrote(tmp_dest_root, "w.png", "not really a picture"))
    picture = tmp_path / "elsewhere" / "w.png"
    picture.parent.mkdir(parents=True)
    picture.write_bytes(b"pretend png")
    backend.set(WALLPAPER, f"'file://{picture}'")

    out = tmp_path / "look"
    result = _save(backend, out, keys=[WALLPAPER])

    assert sorted(f.src for f in result.preset.files) == ["files/w-2.png", "files/w.png"]
    assert (out / "files/w-2.png").read_bytes() == b"pretend png"
    assert (out / "files/w.png").read_text() == "not really a picture"


# ── L3 again, one layer down: inside the files themselves ────────────────
#
# The scan that made captured *values* general never looked at the *contents*
# of the files the capture bundles. magma ships a slideshow template that
# renders {{ home }}/.local/share/backgrounds/magma/... nine times, so applying
# it and then saving the desktop copied a file with the login name in it nine
# times into a Look meant to be given away — and pointed the recipient at
# folders they do not have. Same defect as L3, same fix, one layer down.


SLIDESHOW = ".local/share/backgrounds/rice/slideshow.xml"


def _slideshow(root: Path) -> str:
    """A rendered slideshow, exactly as an apply would have left one behind."""
    return (
        "<background>\n"
        f"  <file>{root}/.local/share/backgrounds/rice/day.png</file>\n"
        f"  <file>{root}/.local/share/backgrounds/rice/night.png</file>\n"
        "</background>\n"
    )


@mutating
def test_a_bundled_file_that_names_this_home_folder_is_made_general(
    backend, tmp_dest_root: Path, state_dir: Path, tmp_path: Path
):
    """The file's contents are scanned like a value, and the change is said."""
    _owned("Some Look", _wrote(tmp_dest_root, SLIDESHOW, _slideshow(tmp_dest_root)))

    out = tmp_path / "look"
    result = _save(backend, out)

    entry = result.preset.files[0]
    assert entry.dest == f"~/{SLIDESHOW}"
    assert entry.template, "the recipient's own home folder has to be filled in"
    copied = (out / entry.src).read_text(encoding="utf-8")
    assert str(tmp_dest_root) not in copied
    assert copied.count("{{ home }}") == 2
    assert str(tmp_dest_root) not in (out / "theme.toml").read_text(encoding="utf-8")
    assert any("made general" in warning for warning in result.warnings), result.warnings


@mutating
def test_a_bundled_file_that_is_not_text_is_copied_untouched(
    backend, tmp_dest_root: Path, state_dir: Path, tmp_path: Path
):
    """A picture has nothing to read, and templating one would truncate it."""
    picture = tmp_dest_root / ".local/share/backgrounds/rice/w.png"
    picture.parent.mkdir(parents=True)
    picture.write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe not text")
    _owned("Some Look", str(picture))

    out = tmp_path / "look"
    result = _save(backend, out)

    entry = result.preset.files[0]
    assert not entry.template
    assert (out / entry.src).read_bytes() == b"\x89PNG\r\n\x1a\n\xff\xfe not text"


@mutating
def test_the_generalised_file_lands_on_the_other_computers_home_folder(
    backend, tmp_dest_root: Path, state_dir: Path, tmp_path: Path, monkeypatch
):
    """The whole point, proved end to end: save here, apply as somebody else.

    Rewriting the copy is only half a fix. The entry has to be marked
    ``template`` as well, or the file arrives with ``{{ home }}`` written in it
    literally — which is worse than the login name it replaced.
    """
    from gtheme.core import backends, placeholders
    from gtheme.preset.compile import compile_preset

    _owned("Some Look", _wrote(tmp_dest_root, SLIDESHOW, _slideshow(tmp_dest_root)))
    out = tmp_path / "look"
    _save(backend, out, keys=[])

    theirs = tmp_path / "their-home"
    theirs.mkdir()
    monkeypatch.setenv("GTHEME_DEST_ROOT", str(theirs))
    placeholders.clear_cache()
    try:
        with backends.use_backend(backend):
            compiled = compile_preset(load(out).preset, out, dest_root=str(theirs))
            assert not compiled.refusals, compiled.refusals
            compiled.transaction.apply(restore_point=False)
    finally:
        placeholders.clear_cache()

    landed = (theirs / SLIDESHOW).read_text(encoding="utf-8")
    assert landed == _slideshow(theirs)
    assert "{{" not in landed


# ── a ledger claim that walks out of the home folder ─────────────────────


@mutating
def test_a_claim_that_walks_upwards_is_refused_and_named(
    backend, tmp_dest_root: Path, state_dir: Path, tmp_path: Path
):
    """The ledger is a file of strings, and a string can say ``..``.

    ``<home>/../../victim.txt`` is lexically under the home folder and names a
    file that is not, so ``files/../../victim.txt`` was written as the place
    inside the Look — and the copy landed beside the Look folder rather than in
    it. Every other source path in the app is confined; this one was not.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "victim.txt").write_text("not gtheme's\n", encoding="utf-8")
    walked = str(tmp_dest_root / ".." / ".." / outside.name / "victim.txt")
    _owned("Some Look", walked)

    out = tmp_path / "looks" / "mine"
    result = _save(backend, out)

    assert result.preset.files == []
    assert [(o.kind, o.what) for o in result.omissions if o.kind == "file"] == [
        ("file", walked)
    ]
    assert not (out.parent / outside.name).exists(), "the copy escaped the Look folder"
    assert list(out.parent.iterdir()) == [out]


@mutating
def test_a_claim_reached_through_a_shortcut_out_of_the_home_folder_is_refused(
    backend, tmp_dest_root: Path, state_dir: Path, tmp_path: Path
):
    """H5's rule, in the direction nobody had asked: a Look must not siphon.

    A claim under the home folder whose path runs through a shortcut pointing
    away from it would read somebody's private file straight into a Look meant
    to be given to a stranger.
    """
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "id_ed25519").write_text("PRIVATE KEY\n", encoding="utf-8")
    (tmp_dest_root / ".secrets").symlink_to(elsewhere)
    _owned("Some Look", str(tmp_dest_root / ".secrets" / "id_ed25519"))

    out = tmp_path / "look"
    result = _save(backend, out)

    assert result.preset.files == []
    assert [o.kind for o in result.omissions if o.kind == "file"] == ["file"]
    assert not (out / "files").exists()
    assert "PRIVATE KEY" not in (out / "theme.toml").read_text(encoding="utf-8")


# ── the colours travel too ───────────────────────────────────────────────


def _a_look_here(themes: Path, name: str, palette: str) -> None:
    folder = themes / name
    folder.mkdir(parents=True)
    (folder / "theme.toml").write_text(
        textwrap.dedent(
            f"""\
            format = 2

            [meta]
            name = "{name}"
            title = "{name.title()}"
            description = "A Look for a test."
            author = "the suite"
            version = "1.0.0"

            [palette]
            {palette}
            """
        ),
        encoding="utf-8",
    )


@mutating
def test_the_colours_of_the_look_in_use_travel_with_the_save(
    backend, tmp_dest_root: Path, state_dir: Path, tmp_path: Path, monkeypatch
):
    """A saved Look had no ``[palette]``, so the Terminal page went blank under it."""
    themes = tmp_path / "themes"
    _a_look_here(themes, "rice", 'bg = "#0d0a0f"\naccent = "#ff7a45"')
    monkeypatch.setenv("GTHEME_THEMES_DIR", str(themes))
    ledger.set_current_look("rice", label="Rice")

    result = _save(backend, tmp_path / "look")

    assert result.preset.palette == {"bg": "#0d0a0f", "accent": "#ff7a45"}
    assert [o for o in result.omissions if o.kind == "palette"] == []


@mutating
def test_the_colours_come_from_the_terminal_when_no_look_is_in_use(
    backend, tmp_dest_root: Path, state_dir: Path, tmp_path: Path
):
    """A desktop nobody applied a Look to still has colours worth saving."""
    config = tmp_dest_root / ".config/ghostty/config"
    config.parent.mkdir(parents=True)
    config.write_text("background = 1a1b26\nforeground = c0caf5\n", encoding="utf-8")

    result = _save(backend, tmp_path / "look")

    assert result.preset.palette == {"bg": "#1a1b26", "fg": "#c0caf5"}


@mutating
def test_a_save_with_no_colours_anywhere_says_so(
    backend, tmp_dest_root: Path, state_dir: Path, tmp_path: Path
):
    """Nothing to read is a real answer; leaving it unsaid is the defect."""
    result = _save(backend, tmp_path / "look")

    assert result.preset.palette == {}
    missing = [o for o in result.omissions if o.kind == "palette"]
    assert missing, result.omissions
    assert any(missing[0].sentence() in warning for warning in result.warnings)


@mutating
def test_the_colours_written_down_are_the_ones_a_look_is_read_for(
    backend, tmp_dest_root: Path, state_dir: Path, tmp_path: Path
):
    """The capture writes the spelling the Terminal page reads back.

    A palette nothing can read is the same as no palette, so this goes through
    the reader the app itself uses rather than asserting on key names.
    """
    ansi = "\n".join(f"palette = {i}=#{i:02x}{i:02x}{i:02x}" for i in range(16))
    config = tmp_dest_root / ".config/ghostty/config"
    config.parent.mkdir(parents=True)
    config.write_text(
        f"background = 1a1b26\nforeground = c0caf5\ncursor-color = ff7a45\n{ansi}\n",
        encoding="utf-8",
    )

    result = _save(backend, tmp_path / "look")

    read_back = _palette_reader()(result.preset)
    assert read_back is not None
    assert read_back.background == "#1a1b26"
    assert read_back.cursor == "#ff7a45"
    assert len(read_back.ansi) == 16


def _palette_reader():
    """``palette_from_look``, skipped rather than failed with no GTK present."""
    pytest.importorskip("gi", reason="the Terminal page needs PyGObject")
    from gtheme.ui.pages.terminal import palette_from_look

    return palette_from_look


# ── L3: a home folder that is not under /home ────────────────────────────


@mutating
def test_a_home_folder_outside_slash_home_is_still_made_general(
    backend, tmp_dest_root: Path, tmp_path: Path, monkeypatch
):
    """L3. Silverblue keeps home folders in ``/var/home``; so do relocated ones.

    The scan matched ``/home/<name>`` and nothing else, so every captured path
    on such a machine was published with the login name in it and pointed at a
    folder the recipient does not have. ``tmp_dest_root`` is requested for the
    isolation guard; the root is then moved somewhere shaped like Silverblue's.
    """
    root = tmp_path / "var" / "home" / "somebody"
    root.mkdir(parents=True)
    monkeypatch.setenv("GTHEME_DEST_ROOT", str(root))
    backend.set(PICTURE, f"'file://{root}/Pictures/w.png'")

    result = _save(backend, tmp_path / "look", keys=[PICTURE])

    assert result.preset.settings[0].value == "'file://{{ home }}/Pictures/w.png'"
    assert "somebody" not in (tmp_path / "look" / "theme.toml").read_text()


@mutating
def test_a_home_folder_under_slash_home_is_replaced_whole(
    backend, tmp_dest_root: Path, tmp_path: Path, monkeypatch
):
    """The real root is tried first, so a nested home folder is not half-matched.

    ``/home/somebody/desktops/one`` matches the ``/home/<name>`` shape at its
    first two components. Replacing that half would leave
    ``{{ home }}/desktops/one/...`` — a path pointing at somewhere the recipient
    has never had — which is worse than not replacing it at all.
    """
    root = tmp_path / "home" / "somebody" / "desktops" / "one"
    root.mkdir(parents=True)
    monkeypatch.setenv("GTHEME_DEST_ROOT", str(root))
    backend.set(PICTURE, f"'file://{root}/Pictures/w.png'")

    result = _save(backend, tmp_path / "look", keys=[PICTURE])

    assert result.preset.settings[0].value == "'file://{{ home }}/Pictures/w.png'"


@mutating
def test_somebody_elses_home_folder_is_still_recognised(
    backend, tmp_dest_root: Path, tmp_path: Path
):
    """The ``/home/<name>`` shape stays as the second half of the scan."""
    backend.set(PICTURE, "'file:///home/someone-else/Pictures/w.png'")

    result = _save(backend, tmp_path / "look", keys=[PICTURE])

    assert result.preset.settings[0].value == "'file://{{ home }}/Pictures/w.png'"
