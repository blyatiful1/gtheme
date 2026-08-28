"""Ghostty: preserving a hand-written config, and the F7 symlinked directory.

The fixture tree here is the shape of the machine gtheme was built on:
``~/.config/ghostty`` is not a directory, it is a symlink into a separate rice
repository that a person maintains by hand and keeps in git. Every test below
that says "foreign" is asking the same question — *did gtheme write into
somebody else's repository?* — and the answer has to stay no.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from terminal_write_helper import land

from gtheme.terminal.ghostty import FOREIGN_NOTICE, GhosttyAdapter, slugify
from gtheme.terminal.model import Palette, ReloadSemantics

ANSI = tuple(f"#{i:02x}{i:02x}{i:02x}" for i in range(16))

LOOK = Palette(
    name="Nightbloom",
    background="#0A100C",
    foreground="#E8E4D6",
    cursor="#F5C04A",
    ansi=ANSI,
    opacity=0.82,
)

HAND_WRITTEN = """\
# ── NIGHTBLOOM — Ghostty ────────────────────────────────
# The glasshouse after dark.

theme = nightbloom

font-family = Monaspace Argon
font-family = Symbols Nerd Font Mono
font-feature = calt
font-feature = ss01

background-opacity = 0.9
custom-shader = shaders/firefly.glsl
custom-shader = shaders/fog.glsl
keybind = ctrl+shift+r=reload_config
"""


@pytest.fixture
def local_ghostty(tmp_dest_root: Path) -> GhosttyAdapter:
    """A config directory that really is the user's own."""
    directory = tmp_dest_root / ".config" / "ghostty"
    directory.mkdir(parents=True)
    (directory / "config").write_text(HAND_WRITTEN, encoding="utf-8")
    return GhosttyAdapter()


@pytest.fixture
def foreign_ghostty(tmp_dest_root: Path, tmp_path: Path) -> tuple[GhosttyAdapter, Path]:
    """The F7 shape: ~/.config/ghostty is a symlink into another repository."""
    rice = tmp_path / "nightbloom" / "ghostty"
    rice.mkdir(parents=True)
    (rice / "config").write_text(HAND_WRITTEN, encoding="utf-8")
    (rice / "themes").mkdir()
    (rice / "themes" / "nightbloom").write_text("background = #0A100C\n", encoding="utf-8")
    config = tmp_dest_root / ".config"
    config.mkdir(parents=True)
    (config / "ghostty").symlink_to(rice)
    return GhosttyAdapter(), rice


def _fingerprint(directory: Path) -> dict[str, str]:
    return {
        str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


# -- the ordinary case -----------------------------------------------------


def test_reload_semantics_are_honest():
    assert GhosttyAdapter.reload_semantics is ReloadSemantics.MANUAL_RELOAD
    assert "reload" in ReloadSemantics.MANUAL_RELOAD.sentence()


@pytest.mark.mutating
def test_apply_writes_a_theme_file_and_selects_it(local_ghostty: GhosttyAdapter):
    land(local_ghostty, LOOK)
    theme = local_ghostty.themes_dir / "nightbloom"
    assert theme.is_file()
    assert "palette = 0=#000000" in theme.read_text()
    assert "background = #0A100C" in theme.read_text()
    config = local_ghostty.config_path.read_text()
    assert "theme = nightbloom" in config
    assert "background-opacity = 0.82" in config


@pytest.mark.mutating
def test_apply_preserves_comments_and_keys_gtheme_never_heard_of(
    local_ghostty: GhosttyAdapter,
):
    land(local_ghostty, LOOK)
    config = local_ghostty.config_path.read_text()
    for line in (
        "# ── NIGHTBLOOM — Ghostty ────────────────────────────────",
        "font-family = Monaspace Argon",
        "font-family = Symbols Nerd Font Mono",
        "custom-shader = shaders/firefly.glsl",
        "custom-shader = shaders/fog.glsl",
        "keybind = ctrl+shift+r=reload_config",
    ):
        assert line in config
    # And the repeated keys stayed repeated rather than collapsing to one.
    assert config.count("font-feature = ") == 2


@pytest.mark.mutating
def test_apply_replaces_rather_than_appends_a_known_key(local_ghostty: GhosttyAdapter):
    land(local_ghostty, LOOK)
    config = local_ghostty.config_path.read_text()
    assert config.count("background-opacity") == 1
    assert "background-opacity = 0.9" not in config


@pytest.mark.mutating
def test_current_round_trips_what_apply_wrote(local_ghostty: GhosttyAdapter):
    land(local_ghostty, LOOK)
    read_back = local_ghostty.current()
    assert read_back is not None
    assert (read_back.background, read_back.foreground) == (LOOK.background, LOOK.foreground)
    assert read_back.ansi == ANSI
    assert read_back.opacity == pytest.approx(0.82)


@pytest.mark.mutating
def test_a_partial_palette_reads_as_no_palette(local_ghostty: GhosttyAdapter):
    """Sixteen or nothing — Palette refuses a half-filled ANSI set."""
    local_ghostty.themes_dir.mkdir(parents=True)
    (local_ghostty.themes_dir / "half").write_text(
        "palette = 0=#000000\nbackground = #111111\nforeground = #eeeeee\n", encoding="utf-8"
    )
    local_ghostty.config_path.write_text("theme = half\n", encoding="utf-8")
    palette = local_ghostty.current()
    assert palette is not None
    assert palette.ansi == ()


def test_slugify_cannot_climb_out_of_the_themes_folder():
    assert slugify("../../etc/passwd") == "etc-passwd"
    assert slugify("  ") == "gtheme"


# -- F7: the config directory belongs to someone else ----------------------


@pytest.mark.mutating
def test_a_symlinked_directory_is_detected_as_foreign(
    foreign_ghostty: tuple[GhosttyAdapter, Path],
):
    adapter, rice = foreign_ghostty
    state = adapter.detect()
    assert state.foreign_root == rice.resolve()
    assert any("managed by another tool" in note for note in state.notes)
    assert "nightbloom" in state.notes[-1]


@pytest.mark.mutating
def test_apply_refuses_a_foreign_directory_and_changes_nothing(
    foreign_ghostty: tuple[GhosttyAdapter, Path],
):
    adapter, rice = foreign_ghostty
    before = _fingerprint(rice)
    with pytest.raises(PermissionError, match="managed by another tool"):
        land(adapter, LOOK)
    assert _fingerprint(rice) == before
    # Not even a stray temp file: an atomic write's tmp lands beside its target.
    assert not list(rice.glob(".gtheme-*"))


@pytest.mark.mutating
def test_reading_a_foreign_directory_is_still_allowed(
    foreign_ghostty: tuple[GhosttyAdapter, Path],
):
    """Showing someone what they already have changes nothing."""
    adapter, _rice = foreign_ghostty
    state = adapter.detect()
    assert state.installed
    assert state.config_path is not None


@pytest.mark.mutating
def test_take_over_snapshots_the_link_then_materialises_a_real_directory(
    foreign_ghostty: tuple[GhosttyAdapter, Path],
):
    adapter, rice = foreign_ghostty
    before = _fingerprint(rice)

    assert adapter.take_over() is True

    directory = adapter.config_dir
    assert directory.is_dir() and not directory.is_symlink()
    assert (directory / "config").read_text() == HAND_WRITTEN
    assert (directory / "themes" / "nightbloom").is_file()
    assert adapter.foreign_root() is None
    assert _fingerprint(rice) == before, "the original repository must be untouched"

    record = adapter.takeover_record
    assert record.is_file()
    assert str(rice) in record.read_text()


@pytest.mark.mutating
def test_after_take_over_apply_works_and_the_original_repo_stays_untouched(
    foreign_ghostty: tuple[GhosttyAdapter, Path],
):
    adapter, rice = foreign_ghostty
    before = _fingerprint(rice)
    adapter.take_over()
    land(adapter, LOOK)
    assert "theme = nightbloom" in adapter.config_path.read_text()
    assert _fingerprint(rice) == before


@pytest.mark.mutating
def test_undo_takeover_puts_the_link_back(foreign_ghostty: tuple[GhosttyAdapter, Path]):
    adapter, rice = foreign_ghostty
    adapter.take_over()
    land(adapter, LOOK)

    assert adapter.undo_takeover() is True
    assert adapter.config_dir.is_symlink()
    assert adapter.config_dir.resolve() == rice.resolve()
    assert not adapter.takeover_record.exists()
    # gtheme's copy is kept aside rather than deleted.
    kept = list(adapter.config_dir.parent.glob("ghostty.gtheme-*"))
    assert len(kept) == 1
    assert "theme = nightbloom" in (kept[0] / "config").read_text()


@pytest.mark.mutating
def test_take_over_is_a_no_op_on_a_directory_that_was_never_foreign(
    local_ghostty: GhosttyAdapter,
):
    assert local_ghostty.take_over() is False
    assert local_ghostty.undo_takeover() is False


def test_the_refusal_names_the_tool_that_owns_the_directory():
    assert FOREIGN_NOTICE.format(owner="NIGHTBLOOM").startswith(
        "Your terminal's settings are managed by another tool (NIGHTBLOOM)"
    )
