"""``gtheme.core`` must never depend on GTK. Two reasons, both load-bearing.

``gtheme rescue`` runs when the graphical session is broken, from a text
console, on a machine where importing GTK may itself fail. And CI's Ubuntu
runner has libadwaita 1.5 while gtheme targets 1.9, so no Adw code may run
there — but the core engine tests must.

Gio and GLib are allowed: they are the settings machinery, they have no display
dependency, and CI installs them.
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
import subprocess
import sys
from pathlib import Path

import pytest

import gtheme.core

FORBIDDEN = ("Gtk", "Adw", "Gdk", "Gsk", "GnomeDesktop")


def _core_modules() -> list[str]:
    return sorted(
        name
        for _, name, _ in pkgutil.walk_packages(gtheme.core.__path__, "gtheme.core.")
    )


def test_there_are_core_modules_to_check():
    """Guard the guard: an empty list would make every test below vacuous."""
    assert _core_modules(), "no modules found under gtheme.core"


@pytest.mark.parametrize("module_name", _core_modules())
def test_no_core_module_names_a_gtk_typelib(module_name):
    module = importlib.import_module(module_name)
    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "gi.repository":
            imported = {alias.name for alias in node.names}
            assert not imported & set(FORBIDDEN), (
                f"{module_name} imports {imported & set(FORBIDDEN)} from gi.repository"
            )
        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "require_version"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                assert node.args[0].value not in FORBIDDEN, (
                    f"{module_name} calls gi.require_version({node.args[0].value!r})"
                )


def test_importing_core_pulls_in_no_gtk_at_runtime():
    """The decisive check: a fresh interpreter, importing only core."""
    code = (
        "import sys\n"
        "import gtheme.core.settings_backend, gtheme.core.transaction, gtheme.core.rescue\n"
        "loaded = [m for m in sys.modules if m.startswith('gi.repository.')]\n"
        "bad = [m for m in loaded if m.rsplit('.', 1)[-1] in "
        f"{FORBIDDEN!r}]\n"
        "print(','.join(bad))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "", f"core pulled in {result.stdout.strip()}"


def test_core_imports_without_pygobject_at_all():
    """A machine with no PyGObject must still be able to run the rescue path."""
    code = (
        "import sys\n"
        "class Blocker:\n"
        "    def find_module(self, name, path=None):\n"
        "        if name == 'gi' or name.startswith('gi.'):\n"
        "            raise ImportError('PyGObject is not installed')\n"
        "        return None\n"
        "sys.meta_path.insert(0, Blocker())\n"
        "import gtheme.core.settings_backend, gtheme.core.transaction, gtheme.core.rescue\n"
        "import gtheme.cli\n"
        "print('ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
