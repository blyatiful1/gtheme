"""Path escapes, ported from v1's ``tests/test_confine.py`` and widened.

A Look is a folder somebody downloaded from the internet. Its ``theme.toml``
says where each of its files goes. Everything below is a way of writing that
down which, taken literally, would put a file somewhere it has no business
being — or read one out of somewhere it has no business reading.

None of them are theoretical. ``~/../../etc`` is what a naive expansion does
with a relative segment; an absolute ``/etc/...`` is what a Look written for a
system-wide install looks like; a symlink pointing out of the Look folder is
how you exfiltrate ``~/.ssh/id_ed25519`` while looking like you are copying a
wallpaper.

The v1 tests are ported roughly one for one, with one deliberate difference
noted at :func:`test_a_name_may_contain_a_dot`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gtheme.core.confine import (
    ConfinementError,
    confine_dest,
    confine_src,
    preflight_dests,
    safe_name,
)
from gtheme.core.transaction import FileWrite, Transaction, TransactionError


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "home"
    target.mkdir()
    monkeypatch.setenv("GTHEME_DEST_ROOT", str(target))
    return target.resolve()


# -- destinations ----------------------------------------------------------


def test_a_destination_inside_the_root_is_fine(root):
    assert confine_dest("~/.config/x").resolve().is_relative_to(root)


def test_an_absolute_system_path_is_refused(root):
    with pytest.raises(ConfinementError):
        confine_dest("/etc/x")


def test_a_relative_escape_is_refused(root):
    with pytest.raises(ConfinementError):
        confine_dest("~/../escape")


def test_a_deep_relative_escape_is_refused(root):
    with pytest.raises(ConfinementError):
        confine_dest("~/.config/../../../etc/passwd")


def test_dollar_home_is_the_same_thing_as_tilde(root):
    assert confine_dest("$HOME/.config/x") == confine_dest("~/.config/x")


def test_a_symlink_pointing_out_of_the_root_is_refused(root, tmp_path):
    """Resolution happens before the containment check, not after.

    A directory inside the root that is really a link to somewhere else is the
    interesting case: the path *looks* contained until you follow it.
    """
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (root / "escape-hatch").symlink_to(outside)
    with pytest.raises(ConfinementError):
        confine_dest("~/escape-hatch/planted")


def test_the_explicit_opt_out_exists_and_is_not_something_a_look_can_ask_for(root):
    """``allow_outside`` is a keyword the engine passes, never data from a file."""
    assert str(confine_dest("/etc/x", allow_outside=True)) == "/etc/x"


# -- the preflight ---------------------------------------------------------


def test_the_preflight_refuses_on_the_first_bad_destination(root):
    with pytest.raises(ConfinementError):
        preflight_dests(["~/.config/a", "~/.config/b", "/etc/shadow"])


def test_a_transaction_with_one_escaping_file_writes_none_of_them(root, tmp_path):
    """The reason the preflight is a separate pass over everything.

    Checking each file as it is written means a Look whose fourth file escapes
    has already replaced three of yours by the time anybody notices.
    """
    look = tmp_path / "look"
    look.mkdir()
    for name in ("a", "b", "c"):
        (look / name).write_text(name, encoding="utf-8")

    tx = Transaction(
        [
            FileWrite(src=str(look / "a"), dest="~/.config/demo/a"),
            FileWrite(src=str(look / "b"), dest="~/.config/demo/b"),
            FileWrite(src=str(look / "c"), dest="~/../../etc/gtheme-escaped"),
        ],
        dest_root=str(root),
        label="ESCAPE",
    )
    with pytest.raises(TransactionError):
        tx.plan()
    with pytest.raises(TransactionError):
        tx.apply(restore_point=False)
    assert not (root / ".config" / "demo" / "a").exists()
    assert not (root / ".config" / "demo" / "b").exists()


# -- sources ---------------------------------------------------------------


def test_a_source_inside_the_look_is_fine(tmp_path):
    look = tmp_path / "look"
    look.mkdir()
    assert confine_src("files/gtk.css", look).resolve().is_relative_to(look.resolve())


def test_a_source_that_climbs_out_is_refused(tmp_path):
    look = tmp_path / "look"
    look.mkdir()
    with pytest.raises(ConfinementError):
        confine_src("../x", look)


def test_a_deeply_climbing_source_is_refused(tmp_path):
    look = tmp_path / "look"
    look.mkdir()
    with pytest.raises(ConfinementError):
        confine_src("files/../../x", look)


def test_a_source_symlink_pointing_out_of_the_look_is_refused(tmp_path):
    """The exfiltration case: a "wallpaper" that is really a link to a key."""
    look = tmp_path / "look"
    look.mkdir()
    secret = tmp_path / "id_ed25519"
    secret.write_text("PRIVATE KEY", encoding="utf-8")
    (look / "wallpaper.jpg").symlink_to(secret)
    with pytest.raises(ConfinementError):
        confine_src("wallpaper.jpg", look)


# -- names -----------------------------------------------------------------


@pytest.mark.parametrize("name", ["nsx", "jojo", "stone-clean", "my_theme", "v2"])
def test_ordinary_names_are_accepted(name):
    assert safe_name(name) == name


@pytest.mark.parametrize(
    "name",
    ["", "..", ".", "../x", "a/b", "/etc/x", "../../etc", "a b", "x\x00y", "~", "a\nb"],
)
def test_names_that_could_walk_out_of_a_folder_are_refused(name):
    with pytest.raises(ConfinementError):
        safe_name(name)


@pytest.mark.parametrize("name", ["ｎｓｘ", "café", "nsx​"])
def test_non_ascii_names_are_refused(name):
    """Python's ``isalnum`` is true for full-width characters.

    A Look named with homographs is one nobody can tell apart from the real
    one, which is the whole point of naming it that way.
    """
    with pytest.raises(ConfinementError):
        safe_name(name)


def test_a_name_may_contain_a_dot():
    """A deliberate difference from v1, which rejected every dot.

    v2's ``preset.model.Meta.name`` is patterned ``^[a-z0-9][a-z0-9._-]*$``, so
    a dot is legal in a Look's name and this has to agree with it. The property
    that matters is unchanged: no separator, and never ``.`` or ``..`` alone.
    """
    assert safe_name("look.v2") == "look.v2"
    with pytest.raises(ConfinementError):
        safe_name("..")
