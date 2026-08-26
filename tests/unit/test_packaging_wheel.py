"""The wheel must carry everything the installed app needs.

This builds a real wheel with the real build backend and looks inside it. The
failure this guards against is silent and total: hatchling's ``force-include``
would happily place a directory called ``share/`` *inside site-packages*, where
the launcher entry and the icons are invisible to the desktop and the settings
descriptions are invisible to the app. Only the wheel's ``.data/data`` tree is
unpacked to the install prefix, and only ``shared-data`` writes there.
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
APP_ID = "io.github.blyatiful1.Gtheme"


@pytest.fixture(scope="module")
def wheel(tmp_path_factory: pytest.TempPathFactory) -> zipfile.ZipFile:
    """A freshly built wheel, or a skip if the build tools are not installed."""
    pytest.importorskip("build", reason="pip install -e '.[dev]' provides it")
    pytest.importorskip("hatchling", reason="pip install -e '.[dev]' provides it")
    out = tmp_path_factory.mktemp("wheel")
    proc = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(out), str(REPO)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"building the wheel failed:\n{proc.stdout}\n{proc.stderr}"
    built = sorted(out.glob("*.whl"))
    assert len(built) == 1, f"expected exactly one wheel, got {built}"
    return zipfile.ZipFile(built[0])


@pytest.fixture(scope="module")
def names(wheel: zipfile.ZipFile) -> list[str]:
    return wheel.namelist()


@pytest.fixture(scope="module")
def data_root(names: list[str]) -> str:
    """The ``gtheme-<version>.data/data/`` prefix inside the wheel."""
    roots = {n.split("/")[0] for n in names if n.split("/")[0].endswith(".data")}
    assert len(roots) == 1, f"expected one .data tree in the wheel, got {sorted(roots)}"
    return f"{roots.pop()}/data/"


def test_no_stray_share_directory_in_site_packages(names: list[str]) -> None:
    tops = {n.split("/")[0] for n in names}
    assert "share" not in tops, (
        "the wheel has a top-level share/ directory, which installs into "
        "site-packages and is never found by anything. Use "
        "[tool.hatch.build.targets.wheel.shared-data], not force-include."
    )


def test_the_code_is_in_the_wheel(names: list[str]) -> None:
    for expected in (
        "gtheme/__init__.py",
        "gtheme/cli.py",
        "gtheme/app.py",
        "gtheme/ui/registry.py",
        "gtheme/panels/loader.py",
    ):
        assert expected in names, f"{expected} is missing from the wheel"


def test_the_console_command_is_declared(wheel: zipfile.ZipFile, names: list[str]) -> None:
    entry_points = [n for n in names if n.endswith(".dist-info/entry_points.txt")]
    assert entry_points, "the wheel declares no commands at all"
    text = wheel.read(entry_points[0]).decode()
    assert "gtheme = gtheme.cli:main" in text


def test_bundled_looks_travel_inside_the_package(names: list[str]) -> None:
    """The Looks the app ships live next to the code that reads them."""
    assert "gtheme/_bundled_themes/index.json" in names
    on_disk = {p.name for p in (REPO / "themes").iterdir() if p.is_dir()}
    in_wheel = {n.split("/")[2] for n in names if n.startswith("gtheme/_bundled_themes/") and n.count("/") > 2}
    assert on_disk <= in_wheel, f"Looks missing from the wheel: {sorted(on_disk - in_wheel)}"


def test_every_desktop_integration_file_lands_under_share(names: list[str], data_root: str) -> None:
    for expected in (
        f"share/applications/{APP_ID}.desktop",
        f"share/metainfo/{APP_ID}.metainfo.xml",
        f"share/icons/hicolor/scalable/apps/{APP_ID}.svg",
        f"share/icons/hicolor/symbolic/apps/{APP_ID}-symbolic.svg",
    ):
        assert data_root + expected in names, f"{expected} is missing from the wheel's .data tree"


@pytest.mark.parametrize("folder", ["domains", "panels"])
def test_every_settings_description_is_installed(
    names: list[str], data_root: str, folder: str
) -> None:
    """gtheme.panels.loader looks for these under <data dir>/gtheme."""
    on_disk = {p.name for p in (REPO / "data" / folder).iterdir() if p.is_file()}
    prefix = f"{data_root}share/gtheme/{folder}/"
    in_wheel = {n[len(prefix):] for n in names if n.startswith(prefix)}
    assert on_disk == in_wheel, (
        f"data/{folder} and the wheel disagree; "
        f"missing: {sorted(on_disk - in_wheel)}, unexpected: {sorted(in_wheel - on_disk)}"
    )


def test_an_installed_copy_is_a_working_corpus(
    wheel: zipfile.ZipFile, names: list[str], data_root: str, tmp_path: Path
) -> None:
    """Unpack the wheel the way `installer` would, and read it back.

    This is the whole point of the layout: `python -m installer` drops the
    `.data/data` tree at the install prefix, so `<prefix>/share/gtheme` is a
    directory `gtheme.panels.loader.data_dir()` searches by way of
    XDG_DATA_DIRS (which contains /usr/share by default).
    """
    from gtheme.panels import loader

    prefix = f"{data_root}share/"
    for name in names:
        if name.startswith(prefix) and not name.endswith("/"):
            target = tmp_path / name[len(prefix):]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(wheel.read(name))

    corpus = loader.load_corpus(tmp_path / "gtheme")
    assert corpus.problems == []
    assert corpus.panels, "no add-on descriptions loaded from the installed copy"
    assert corpus.domains, "no settings descriptions loaded from the installed copy"
