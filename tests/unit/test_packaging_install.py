"""The two install routes: install.sh from a checkout, and the Arch package.

Neither can be run in the unit tier — one writes into a real home directory and
the other needs makepkg — so what is checked here is the handful of things that
would make them wrong in a way nobody notices until a user is stuck.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
INSTALL = REPO / "install.sh"
PKGBUILD = REPO / "PKGBUILD"
APP_ID = "io.github.blyatiful1.Gtheme"


# --- install.sh -------------------------------------------------------------


def test_install_script_is_runnable() -> None:
    assert INSTALL.is_file()
    assert os.access(INSTALL, os.X_OK), "install.sh is not executable"
    assert INSTALL.read_text().startswith("#!/usr/bin/env bash")


def test_install_script_uses_a_private_folder_not_pip_user() -> None:
    """`pip install --user` is refused by every current distribution (PEP 668)."""
    # Comments are allowed to name the thing they explain we do not do.
    text = "\n".join(
        line for line in INSTALL.read_text().splitlines() if not line.lstrip().startswith("#")
    )
    assert "pip install --user" not in text
    assert "--break-system-packages" not in text
    assert "python3 -m venv --system-site-packages" in text, (
        "the private folder must see the system's PyGObject, or the app cannot start"
    )
    assert not re.search(r"^\s*sudo\b", text, re.M), (
        "install.sh must never run anything as administrator itself — it may "
        "only print the line the reader can choose to run"
    )


def test_install_script_installs_the_desktop_files_too() -> None:
    text = INSTALL.read_text()
    assert f'APP_ID="{APP_ID}"' in text
    # A home-folder install cannot rely on `gtheme` being a known command yet,
    # so the entry it writes names the launcher by its full path.
    assert 's|^Exec=gtheme |Exec=$TARGET |' in text
    for destination in (
        "$DATA_HOME/applications/$APP_ID.desktop",
        "$DATA_HOME/metainfo/$APP_ID.metainfo.xml",
        "$DATA_HOME/icons/hicolor/scalable/apps/$APP_ID.svg",
        "$DATA_HOME/icons/hicolor/symbolic/apps/$APP_ID-symbolic.svg",
    ):
        assert f'"{destination}"' in text, f"install.sh never installs {destination}"
    assert "update-desktop-database" in text
    assert "gtk4-update-icon-cache" in text


def test_install_script_can_be_undone() -> None:
    text = INSTALL.read_text()
    assert "--uninstall" in text
    assert "restore" in text.lower(), "uninstall must not strand a changed desktop"


def test_install_script_is_valid_bash() -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash not installed")
    proc = subprocess.run([bash, "-n", str(INSTALL)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_install_script_help_works_without_touching_anything(tmp_path: Path) -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash not installed")
    env = dict(os.environ, HOME=str(tmp_path), XDG_DATA_HOME=str(tmp_path / "share"))
    proc = subprocess.run(
        [bash, str(INSTALL), "--help"], capture_output=True, text=True, env=env, cwd=str(tmp_path)
    )
    assert proc.returncode == 0
    assert "usage:" in proc.stdout
    assert not (tmp_path / "share").exists(), "--help must not create anything"


def test_install_script_speaks_plainly() -> None:
    """Every line install.sh prints is read by someone new to all of this."""
    from gtheme.ui import jargon

    spoken: list[tuple[str, str]] = []
    for number, line in enumerate(INSTALL.read_text().splitlines(), start=1):
        stripped = line.strip()
        match = re.match(r'^(?:say|step|oops|echo) +"([^"]*)"', stripped)
        if match:
            spoken.append((f"install.sh:{number}", match.group(1)))
    assert spoken, "found no printed lines to check — the test's pattern went stale"
    # Two things are exempt, and only these two:
    #   * $VENV, $REPO and friends — paths, not words said at the reader.
    #   * a literal command line the reader is being handed to copy and paste.
    #     "sudo apt install libadwaita-1-0" is not prose and cannot be
    #     paraphrased; every one of them is introduced by a plain sentence
    #     saying what it is for, which is the part this test polices.
    is_command = re.compile(r"^\s*(?:[A-Za-z/]+: +)?(?:sudo|rm|fish_add_path|echo|\./install\.sh) ")
    texts = [
        (where, re.sub(r"\$\{?[A-Za-z_]+\}?", "", text))
        for where, text in spoken
        if not is_command.match(text)
    ]
    problems = jargon.check_all(texts)
    assert problems == [], "\n".join(problems)


# --- PKGBUILD ---------------------------------------------------------------


def _pkgbuild_array(name: str) -> list[str]:
    text = PKGBUILD.read_text()
    match = re.search(rf"^{name}=\((.*?)\)", text, re.S | re.M)
    assert match, f"PKGBUILD has no {name} array"
    return re.findall(r"'([^']+)'", match.group(1))


def test_pkgbuild_declares_the_system_pieces_the_app_needs() -> None:
    depends = _pkgbuild_array("depends")
    for needed in ("gtk4", "libadwaita", "python-gobject", "python-jinja2", "python-pydantic"):
        assert needed in depends, f"PKGBUILD is missing the dependency {needed}"


def test_pkgbuild_builds_the_wheel_the_way_arch_expects() -> None:
    text = PKGBUILD.read_text()
    assert "python -m build --wheel --no-isolation" in text
    assert 'python -m installer --destdir="$pkgdir" dist/*.whl' in text
    for tool in ("python-build", "python-installer", "python-wheel", "python-hatchling"):
        assert tool in _pkgbuild_array("makedepends"), f"{tool} is not in makedepends"
    assert not re.search(r"^\s*(meson|ninja)\b", text, re.M), (
        "this machine has no meson; the whole packaging design avoids it"
    )


def test_pkgbuild_never_runs_the_local_only_test_tiers() -> None:
    text = PKGBUILD.read_text()
    assert 'pytest -q -m "not gtk and not sandbox"' in text


def test_pkgbuild_installs_the_licence() -> None:
    assert 'install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"' in (
        PKGBUILD.read_text()
    )


def test_namcap_is_happy_if_it_is_here() -> None:
    namcap = shutil.which("namcap")
    if namcap is None:
        pytest.skip("namcap not installed — PKGBUILD linting is a packager-side check")
    proc = subprocess.run([namcap, str(PKGBUILD)], capture_output=True, text=True)
    errors = [line for line in proc.stdout.splitlines() if " E: " in line]
    assert not errors, proc.stdout
