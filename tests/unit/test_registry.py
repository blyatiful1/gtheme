"""The page manifest is the app's information architecture. Guard it."""

from __future__ import annotations

import importlib

import pytest

from gtheme.ui import registry

#: The fifteen pages of DESIGN.md A6, and the module each one lives in, kept
#: here independently of the manifest on purpose. If this file and
#: ``ui/registry.py`` ever disagree, one of them is wrong and the test says so
#: — which is what catches a mistyped module name in the manifest, the failure
#: that would otherwise show up as a silently-placeholder page.
EXPECTED: tuple[tuple[str, str, str], ...] = (
    ("home", "Welcome", "home"),
    ("looks", "Welcome", "looks"),
    ("wallpaper", "Change one thing", "wallpaper"),
    ("colors", "Change one thing", "colors"),
    ("icons", "Change one thing", "icons"),
    ("fonts", "Change one thing", "fonts"),
    ("topbar", "Change one thing", "topbar"),
    ("windows", "Change one thing", "windows"),
    ("addons", "Change one thing", "addons"),
    ("terminal", "Change one thing", "terminal"),
    ("nightlight", "System", "nightlight"),
    ("sound", "System", "sound"),
    ("power", "System", "power"),
    ("more", "System", "more"),
    ("restore", "Safety", "restore"),
)


def test_manifest_is_the_fifteen_pages_in_order():
    assert registry.page_ids() == tuple(page_id for page_id, _, _ in EXPECTED)


def test_sections_are_the_four_named_groups():
    assert registry.SECTIONS == ("Welcome", "Change one thing", "System", "Safety")
    registry.check_sections()


def test_every_page_is_in_its_declared_section():
    for page_id, section, _ in EXPECTED:
        assert registry.get(page_id).section == section


def test_page_ids_are_unique():
    ids = registry.page_ids()
    assert len(set(ids)) == len(ids)


def test_every_page_has_a_title_a_subtitle_and_an_icon():
    for page in registry.MANIFEST:
        assert page.title.strip()
        assert page.subtitle and page.subtitle.strip()
        assert page.icon.endswith("-symbolic")


@pytest.mark.parametrize(("page_id", "_section", "module"), EXPECTED)
def test_factory_string_points_at_the_right_module(page_id, _section, module):
    """A typo in a factory string would show as a permanently blank page."""
    assert registry.get(page_id).factory == f"gtheme.ui.pages.{module}:build"


@pytest.mark.parametrize(("page_id", "_section", "module"), EXPECTED)
def test_page_module_if_present_exposes_build(page_id, _section, module):
    """Once a page module exists it must expose ``build``.

    Pages are written after this manifest is frozen, so a module that does not
    exist yet is expected and fine — the window renders a distinct placeholder
    for it. What is never fine is a module that exists and does not have the
    entry point the manifest promises.

    Two absences are tolerated, and only two:

    * the module is not written yet (``ModuleNotFoundError`` naming it, above);
    * the machine has PyGObject but no GTK 4 or libadwaita *typelib*, which is
      the CI unit job (DESIGN.md F10 installs ``python3-gi`` and the GLib
      typelib only, so ``core`` can be imported without a desktop). Every page
      module calls ``gi.require_version("Gtk", "4.0")`` at import time, and
      that raises ``ValueError`` when the typelib is missing. Skipping is
      right — the Adw job in the archlinux container is what proves these
      pages import — but it is skipped by *name*, so a ``ValueError`` from
      anywhere else in the page's own code is still a failure.
    """
    name = f"gtheme.ui.pages.{module}"
    try:
        imported = importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name != name:
            raise  # the page exists and one of ITS imports is broken
        pytest.skip(f"{name} is not written yet")
    except ValueError as exc:
        if not _is_missing_typelib(exc):
            raise  # a real ValueError raised while importing the page
        pytest.skip(f"{name} needs a typelib this machine does not have: {exc}")
    build = getattr(imported, "build", None)
    assert callable(build), f"{name} must expose a callable build()"


def _is_missing_typelib(exc: ValueError) -> bool:
    """Is this the ``gi.require_version`` "no such namespace" ValueError?

    Matched on the message because PyGObject raises a bare ``ValueError`` for
    it and gives us nothing else to go on. Deliberately narrow: a page whose
    own code raises ``ValueError`` while importing must stay a failure, and a
    broad ``except ValueError: skip`` would turn every one of those green.
    """
    text = str(exc)
    return "amespace" in text and ("not available" in text or "available versions" in text)


def test_a_missing_typelib_is_recognised_but_nothing_else_is():
    """The skip above must not swallow a page's own ValueError.

    The messages below are the ones PyGObject actually produces; the first is
    provoked live so a future PyGObject that reworded it turns this test red
    rather than turning every page-import failure into a silent skip. The
    second form (a namespace that exists at another version) is asserted as a
    literal, because provoking it needs a namespace no other test has loaded
    and this suite loads Gtk and Adw.
    """
    import gi

    with pytest.raises(ValueError) as caught:
        gi.require_version("NoSuchTypelibAnywhere", "9.9")
    assert str(caught.value) == "Namespace NoSuchTypelibAnywhere not available"
    assert _is_missing_typelib(caught.value)

    assert _is_missing_typelib(ValueError("Namespace Gtk not available for version 9.9"))

    # Everything else is a failure, including the messages that are nearest to
    # the two above. "already loaded" in particular is what require_version
    # says when a *different* version is in play, which is a real problem.
    for other in (
        "a page said no",
        "Namespace is a fine word",
        "not available anywhere",
        "Namespace Gtk is already loaded with version 4.0",
    ):
        assert not _is_missing_typelib(ValueError(other)), other


def test_floor_page_is_in_the_manifest():
    assert registry.FLOOR_PAGE_ID in registry.page_ids()


def test_get_rejects_an_unknown_page():
    with pytest.raises(KeyError, match="no page 'nope'"):
        registry.get("nope")


def test_resolve_surfaced_buckets_by_page():
    resolved = registry.resolve_surfaced(
        {
            "org.gnome.desktop.background:picture-uri": "surfaced(wallpaper)",
            "org.gnome.desktop.background:picture-uri-dark": "surfaced(wallpaper)",
            "org.gnome.desktop.interface:color-scheme": "compound(dark-mode)",
            "org.gnome.desktop.privacy:remember-recent-files": "floor",
            "org.gnome.desktop.interface:gtk-im-module": "excluded(dead-key-§1.6)",
            "org.gnome.desktop.input-sources:sources": "delegated(gnome-settings)",
        }
    )
    assert resolved["wallpaper"] == [
        "org.gnome.desktop.background:picture-uri",
        "org.gnome.desktop.background:picture-uri-dark",
    ]
    assert resolved[registry.FLOOR_PAGE_ID] == ["org.gnome.desktop.privacy:remember-recent-files"]
    # compound / excluded / delegated produce no rows anywhere.
    assert sum(len(v) for v in resolved.values()) == 3


def test_resolve_surfaced_covers_every_page_even_when_empty():
    resolved = registry.resolve_surfaced({})
    assert set(resolved) == set(registry.page_ids())
    assert all(rows == [] for rows in resolved.values())


def test_resolve_surfaced_rejects_an_unknown_page():
    with pytest.raises(ValueError, match="names no page in the manifest"):
        registry.resolve_surfaced({"a:b": "surfaced(nonexistent)"})


def test_resolve_surfaced_rejects_an_unknown_disposition():
    with pytest.raises(ValueError, match="is not a disposition"):
        registry.resolve_surfaced({"a:b": "probably-fine"})


def test_load_factory_rejects_a_malformed_factory_string():
    bad = registry.PageDescriptor(
        id="x", title="X", subtitle=None, icon="i-symbolic", section="Welcome", factory="no-colon"
    )
    with pytest.raises(ValueError, match="module:function"):
        registry.load_factory(bad)
