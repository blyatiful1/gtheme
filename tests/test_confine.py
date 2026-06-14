"""Contract tests for path confinement (gtheme.paths).

``paths.DEST_ROOT`` is resolved from ``GTHEME_DEST_ROOT`` at import time, so we
point it at a throwaway directory *before* importing the module.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Stable, real dest root for the whole module (resolved at paths import time).
_DEST_ROOT = Path(tempfile.mkdtemp(prefix="gtheme-dest-")).resolve()
os.environ["GTHEME_DEST_ROOT"] = str(_DEST_ROOT)

from gtheme import paths  # noqa: E402
from gtheme.errors import ThemeSecurityError  # noqa: E402


def test_dest_root_is_our_tmp():
    assert paths.DEST_ROOT.resolve() == _DEST_ROOT


# --- confine_dest ----------------------------------------------------------


def test_confine_dest_accepts_inside():
    out = paths.confine_dest("~/.config/x")
    assert out.resolve().is_relative_to(_DEST_ROOT)


def test_confine_dest_rejects_absolute_etc():
    with pytest.raises(ThemeSecurityError):
        paths.confine_dest("/etc/x")


def test_confine_dest_rejects_home_escape():
    with pytest.raises(ThemeSecurityError):
        paths.confine_dest("~/../escape")


def test_confine_dest_allow_outside_bypasses():
    # explicit opt-out must not raise
    out = paths.confine_dest("/etc/x", allow_outside=True)
    assert str(out) == "/etc/x"


# --- confine_src -----------------------------------------------------------


def test_confine_src_accepts_inside(tmp_path):
    theme = tmp_path / "theme"
    theme.mkdir()
    out = paths.confine_src("files/gtk.css", theme)
    assert out.resolve().is_relative_to(theme.resolve())


def test_confine_src_rejects_traversal(tmp_path):
    theme = tmp_path / "theme"
    theme.mkdir()
    with pytest.raises(ThemeSecurityError):
        paths.confine_src("../x", theme)


def test_confine_src_rejects_deep_traversal(tmp_path):
    theme = tmp_path / "theme"
    theme.mkdir()
    with pytest.raises(ThemeSecurityError):
        paths.confine_src("files/../../x", theme)
