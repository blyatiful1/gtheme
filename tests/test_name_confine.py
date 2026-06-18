"""Wiring tests: the authoring/install entry points reject unsafe theme names.

These complement test_confine's unit tests for ``safe_theme_name`` by proving
the engine functions actually call it before turning a name into a directory.
"""

from __future__ import annotations

import pytest

from gtheme.engine import remote, scaffold
from gtheme.errors import ThemeSecurityError


@pytest.mark.parametrize("name", ["..", "../escape", "a/b"])
def test_new_theme_rejects_traversal(tmp_path, name):
    with pytest.raises(ThemeSecurityError):
        scaffold.new_theme(name, dest_dir=tmp_path)
    # nothing should have been created outside the dest dir
    assert not (tmp_path.parent / "escape").exists()


@pytest.mark.parametrize("name", ["..", "../escape", "a/b"])
def test_copy_theme_rejects_traversal(tmp_path, name):
    src = tmp_path / "theme"
    src.mkdir()
    (src / "theme.toml").write_text('[meta]\nname = "x"\n')
    with pytest.raises(ThemeSecurityError):
        remote._copy_theme(src, name, {"type": "path"})
