"""The Looks that ship with gtheme.

These are the app's shop window: if a bundled Look does not load, does not
compile, or promises a file it does not carry, the first thing a new user
clicks is broken. So every one of them is checked end to end here — loaded,
compiled into a transaction, and planned against a throwaway destination root.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from gtheme.core.backends import use_backend
from gtheme.core.settings_backend import parse_key
from gtheme.core.transaction import (
    ExtensionEnable,
    ExtensionInstall,
    FileWrite,
    SettingWrite,
    TransactionError,
)
from gtheme.preset.compile import compile_preset
from gtheme.preset.loader import load
from gtheme.preset.model import Preset

BUNDLED = ("daybreak", "hearth", "hyperclass", "magma", "netrunner", "nightbloom")
#: The v1 tree the bundled Looks were converted from. It is a checkout that
#: may or may not exist on the machine running this, so the conversion tests
#: that need only the v1 *manifests* read them from a frozen copy committed
#: alongside these tests instead — three theme.toml/palette.toml pairs, taken
#: from the legacy-v1 branch, so "did the conversion lose anything" is
#: answered on every machine rather than skipped on most of them.
LEGACY = Path("/home/crocco/gtheme-rebuild/legacy-worktree/themes")
LEGACY_MANIFESTS = Path(__file__).resolve().parents[1] / "fixtures" / "v1"
CONVERTED = ("magma", "netrunner", "hyperclass")


@pytest.fixture(params=BUNDLED)
def look(request, repo_root: Path):
    """Each bundled Look in turn, as ``(name, directory)``."""
    return request.param, repo_root / "themes" / request.param


# ── they load ────────────────────────────────────────────────────────────


def test_it_loads_with_no_errors_and_no_warnings(look):
    name, directory = look
    result = load(directory)
    assert result.errors == [], f"{name}: {result.errors}"
    assert result.warnings == [], f"{name}: {result.warnings}"


def test_it_is_format_2(look):
    _name, directory = look
    assert load(directory).preset.format == 2


def test_it_has_no_hooks_section(look):
    """Belt and braces: the format forbids it, and the files do not have it."""
    _name, directory = look
    raw = tomllib.loads((directory / "theme.toml").read_text(encoding="utf-8"))
    assert "hooks" not in raw


def test_it_ships_the_picture_it_advertises(look):
    _name, directory = look
    preset = load(directory).preset
    for shot in preset.meta.screenshots:
        assert (directory / shot).is_file(), shot


def test_it_ships_every_file_it_references(look):
    _name, directory = look
    for entry in load(directory).preset.files:
        assert (directory / entry.src).is_file(), entry.src


def test_it_explains_itself(look):
    """Every bundled Look carries a README naming what it left behind."""
    _name, directory = look
    readme = (directory / "README.md").read_text(encoding="utf-8")
    assert "does NOT include" in readme or "NOT include" in readme


def test_every_key_it_writes_parses(look):
    name, directory = look
    for setting in load(directory).preset.settings:
        assert parse_key(setting.key), f"{name}: {setting.key}"


def test_every_file_it_writes_stays_under_the_home_folder(look):
    name, directory = look
    for entry in load(directory).preset.files:
        assert entry.dest.startswith("~/"), f"{name}: {entry.dest}"
        assert ".." not in entry.dest, f"{name}: {entry.dest}"


def test_every_add_on_setting_names_an_add_on_the_look_enables(look):
    _name, directory = look
    preset = load(directory).preset
    enabled = set(preset.extensions.enable)
    for setting in preset.extensions.settings:
        assert setting.uuid in enabled


# ── they compile and plan ────────────────────────────────────────────────


def test_it_compiles_into_a_transaction(look, tmp_dest_root: Path):
    _name, directory = look
    preset = load(directory).preset
    result = compile_preset(preset, directory, dest_root=str(tmp_dest_root))
    assert result.ops
    allowed = (FileWrite, SettingWrite, ExtensionEnable, ExtensionInstall)
    assert all(isinstance(op, allowed) for op in result.ops)


def test_its_plan_can_be_computed(look, tmp_dest_root: Path):
    """Runs for real once the engine lands; until then it is a contract check."""
    _name, directory = look
    preset = load(directory).preset
    transaction = compile_preset(
        preset, directory, dest_root=str(tmp_dest_root)
    ).transaction
    try:
        diff = transaction.plan()
    except NotImplementedError:
        pytest.skip("the transaction engine lands with the core port (Wave 1, agent A)")
    except TransactionError as exc:  # pragma: no cover - a real planning failure
        pytest.fail(f"{directory.name} cannot be planned: {exc}")
    assert diff.entries


def test_compiling_it_on_a_bare_machine_offers_the_add_ons(look, tmp_dest_root: Path):
    _name, directory = look
    preset = load(directory).preset
    result = compile_preset(
        preset, directory, dest_root=str(tmp_dest_root), installed_extensions=set()
    )
    offered = {op.uuid for op in result.ops if isinstance(op, ExtensionInstall)}
    private = {
        e.uuid for e in preset.extensions.install if e.source == "local-only"
    }
    assert offered == set(preset.extensions.enable) - private


# ── specific promises ────────────────────────────────────────────────────


def test_nightbloom_marks_its_private_add_on_local_only(repo_root: Path):
    preset = load(repo_root / "themes" / "nightbloom").preset
    entry = preset.extensions.install_for("intellibar@nightbloom.local")
    assert entry.source == "local-only"


def test_applying_nightbloom_without_intellibar_says_what_is_missing(repo_root: Path):
    directory = repo_root / "themes" / "nightbloom"
    preset = load(directory).preset
    installed = set(preset.extensions.enable) - {"intellibar@nightbloom.local"}
    result = compile_preset(preset, directory, installed_extensions=installed)
    assert len(result.warnings) == 1
    assert "intellibar@nightbloom.local" in result.warnings[0]


def test_nightbloom_keeps_panel_blur_off(repo_root: Path):
    """Panel blur plus a hidden panel wedges every kind of screen recording."""
    preset = load(repo_root / "themes" / "nightbloom").preset
    panel_blur = [
        s
        for s in preset.extensions.settings
        if s.schema_id.endswith("blur-my-shell.panel") and s.key == "blur"
    ]
    assert [s.value for s in panel_blur] == ["false"]


def test_nightbloom_does_not_enable_the_banned_add_on(repo_root: Path):
    preset = load(repo_root / "themes" / "nightbloom").preset
    assert "hidetopbar@mathieu.bidon.ca" not in preset.extensions.enable


@pytest.mark.parametrize("name", ["magma", "netrunner", "nightbloom"])
def test_the_video_wallpaper_add_on_is_declared_where_it_is_used(repo_root: Path, name):
    preset = load(repo_root / "themes" / name).preset
    assert "hanabi-extension@jeffshee.github.io" in preset.extensions.enable


@pytest.mark.parametrize("name", ["magma", "netrunner", "nightbloom"])
def test_there_is_a_still_picture_to_fall_back_to(repo_root: Path, name):
    """If the video add-on is absent the desktop must still show something."""
    preset = load(repo_root / "themes" / name).preset
    picture = [
        s
        for s in preset.settings
        if s.key == "gsettings:org.gnome.desktop.background picture-uri"
    ]
    assert len(picture) == 1
    assert picture[0].value.startswith("'file://{{ home }}/")


def test_hyperclass_has_no_video_wallpaper(repo_root: Path):
    preset = load(repo_root / "themes" / "hyperclass").preset
    assert "hanabi-extension@jeffshee.github.io" not in preset.extensions.enable


def test_hyperclass_writes_its_effect_profile_before_pointing_at_it(repo_root: Path):
    """Files run before settings, which is the only reason this Look works."""
    directory = repo_root / "themes" / "hyperclass"
    preset = load(directory).preset
    assert any("burn-my-windows/profiles" in f.dest for f in preset.files)
    pointer = [s for s in preset.settings if "burn-my-windows active-profile" in s.key]
    assert pointer
    ops = compile_preset(preset, directory).ops
    first_setting = next(i for i, op in enumerate(ops) if isinstance(op, SettingWrite))
    last_file = max(i for i, op in enumerate(ops) if isinstance(op, FileWrite))
    assert last_file < first_setting


def test_the_converted_looks_ship_no_executable_payload(repo_root: Path):
    """The bespoke terminal toys are programs; a Look may not carry them."""
    for name in ("magma", "netrunner", "hyperclass"):
        preset = load(repo_root / "themes" / name).preset
        for entry in preset.files:
            assert "/bin" not in entry.dest, f"{name}: {entry.dest}"
            assert entry.mode != "0755", f"{name}: {entry.dest}"
            assert not entry.dest.endswith("config.fish"), f"{name}: {entry.dest}"


# ── the conversion is faithful ───────────────────────────────────────────


@pytest.mark.parametrize("name", CONVERTED)
def test_every_v1_setting_survived_the_conversion(repo_root: Path, name):
    v1 = tomllib.loads((LEGACY_MANIFESTS / name / "theme.toml").read_text(encoding="utf-8"))
    converted = load(repo_root / "themes" / name).preset
    got = {s.key for s in converted.settings}
    for entry in v1["settings"]:
        key = entry["key"]
        if key.strip() == "org.gnome.shell enabled-extensions":
            continue  # became the [extensions] block
        prefix = "dconf:" if entry["backend"] == "dconf" else "gsettings:"
        assert prefix + key in got, f"{name} lost {key}"


@pytest.mark.parametrize("name", CONVERTED)
def test_every_v1_add_on_survived_the_conversion(repo_root: Path, name):
    v1 = tomllib.loads((LEGACY_MANIFESTS / name / "theme.toml").read_text(encoding="utf-8"))
    converted = load(repo_root / "themes" / name).preset
    for uuid in v1.get("requires", {}).get("extensions", []):
        assert uuid in converted.extensions.enable, f"{name} lost {uuid}"


@pytest.mark.parametrize("name", CONVERTED)
def test_the_palette_survived_the_conversion(repo_root: Path, name):
    v1_palette = tomllib.loads(
        (LEGACY_MANIFESTS / name / "palette.toml").read_text(encoding="utf-8")
    )
    converted = load(repo_root / "themes" / name).preset
    flat = {k: v for k, v in v1_palette.items() if isinstance(v, str)}
    for key, value in flat.items():
        assert converted.palette.get(key) == value, f"{name}: {key}"


@pytest.mark.skipif(not LEGACY.is_dir(), reason="the v1 source tree is not on this machine")
def test_reconverting_magma_still_produces_what_is_committed(repo_root: Path, tmp_path):
    """The importer has not drifted from the Look it produced."""
    from gtheme.preset.v1_import import write_look

    fresh = write_look(
        LEGACY / "magma", tmp_path / "magma", skip=frozenset({"files/fish/config.fish"})
    ).preset
    committed = load(repo_root / "themes" / "magma").preset
    assert fresh.files == committed.files
    assert fresh.settings == committed.settings
    assert fresh.extensions == committed.extensions
    assert fresh.palette == committed.palette


# ── the whole set ────────────────────────────────────────────────────────


def test_every_bundled_look_is_present(repo_root: Path):
    found = {
        p.name for p in (repo_root / "themes").iterdir() if (p / "theme.toml").is_file()
    }
    assert found == set(BUNDLED)


def test_their_names_are_unique_and_match_their_folders(repo_root: Path):
    for name in BUNDLED:
        preset = load(repo_root / "themes" / name).preset
        assert preset.meta.name == name


def test_a_bundled_look_is_a_valid_document_on_its_own(look):
    _name, directory = look
    raw = tomllib.loads((directory / "theme.toml").read_text(encoding="utf-8"))
    assert Preset.model_validate(raw)


# ── the preview counts add-ons, not their settings ──────────────────────────
#
# Both of these plan against a MemoryBackend rather than the desktop the suite
# is running on. plan() reports only what would *change*, so on a machine that
# already has these Looks' add-ons switched on the add-ons line is empty and
# the assertions below would pass by describing nothing.
#
# The *store* was seamed; the add-on folders were not. ``plan()`` asks
# :func:`gtheme.core.transaction.installed_extension_uuids` which add-ons are
# on the machine and reports an add-on it cannot find as no change at all — so
# these two tests were quietly measuring the developer's own desktop, and
# passed only because that one desktop happens to have every add-on all six
# bundled Looks ask for. On a machine that has none of them the add-ons line is
# empty and both fail with "declares 6 add-ons and plans 0" (the CI container).
# ``addons_on_this_machine`` plants the folders, so the assertions describe the
# planner rather than the box the suite is running on.


@pytest.fixture
def addons_on_this_machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Put the named add-ons on this machine, wherever this machine is.

    ``installed_extension_uuids`` reads ``$XDG_DATA_HOME/gnome-shell/extensions``
    and ``/usr/share/gnome-shell/extensions``; only the first is redirectable,
    and redirecting it is the seam the engine's own tests already use. Returns
    a callable taking the uuids to install.
    """
    root = tmp_path / "xdg-data" / "gnome-shell" / "extensions"
    root.mkdir(parents=True)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))

    def install(uuids) -> None:
        for uuid in uuids:
            (root / uuid).mkdir(exist_ok=True)

    return install


def _plan_against_nothing(directory: Path, dest_root: Path, backend):
    """The plan for a Look on a machine that has none of it yet."""
    transaction = compile_preset(preset_of(directory), directory, dest_root=str(dest_root)).transaction
    with use_backend(backend):
        return transaction.plan()


def preset_of(directory: Path):
    return load(directory).preset


def test_the_add_ons_line_counts_add_ons_and_nothing_else(
    look, tmp_dest_root: Path, memory_settings, addons_on_this_machine
):
    """HYPERCLASS previewed as "31 add-ons" on a Look that turns on six.

    The other twenty-five were settings belonging to those six -- the dock's
    icon size, the blur radius, where the panel sits -- each one tagged
    ``component = "addons"`` by the v1 conversion and counted as if it were
    another add-on being switched on. A person reading "31 add-ons" reasonably
    expects thirty-one new things on their desktop.

    Driven against the real converted Looks rather than a hand-built Diff,
    because a hand-built one is exactly what missed this: every existing test
    of the add-ons line built its entries out of ExtensionEnable ops, which
    were never the problem.
    """
    _name, directory = look
    preset = preset_of(directory)
    addons_on_this_machine(preset.extensions.enable)
    diff = _plan_against_nothing(directory, tmp_dest_root, memory_settings)

    counted = sum(1 for entry in diff.changes if entry.component == "addons")
    enabling = sum(
        1
        for entry in diff.changes
        if isinstance(entry.op, ExtensionEnable | ExtensionInstall)
    )
    assert counted == enabling, "the add-ons line counted something that is not an add-on"
    assert counted == len(preset.extensions.enable), (
        f"{directory.name} declares {len(preset.extensions.enable)} add-ons "
        f"and plans {counted}"
    )

    settings_line = [entry for entry in diff.changes if entry.component == "addon-settings"]
    assert all(isinstance(entry.op, SettingWrite) for entry in settings_line)


def test_hyperclass_says_six_add_ons_because_it_turns_on_six(
    repo_root, tmp_dest_root: Path, memory_settings, addons_on_this_machine
):
    """The named case, pinned by number so a regression is unmissable."""
    directory = repo_root / "themes" / "hyperclass"
    assert len(preset_of(directory).extensions.enable) == 6, "the premise changed"

    addons_on_this_machine(preset_of(directory).extensions.enable)
    diff = _plan_against_nothing(directory, tmp_dest_root, memory_settings)
    lines = diff.to_novice_lines()

    assert "6 add-ons" in lines, lines

    # The twenty-five that used to be on that line, now on their own.
    theirs = [entry for entry in diff.changes if entry.component == "addon-settings"]
    assert len(theirs) >= 20, "this Look is meant to configure its add-ons heavily"
    assert f"{len(theirs)} add-on settings" in lines, lines
