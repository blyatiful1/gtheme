"""Fixtures for the defect-tag regression suite.

Every test in this directory pins a bug v1 already found and fixed once. The
comment tags in the legacy ``engine/apply.py`` — AS4, AS5, AS8, R1, R3, R4, R5,
R6, F1, L1, X1, and E1 over in ``paths.py`` — are the receipts, and this
directory is the net that stops the rewrite quietly reintroducing any of them.

(H2 and R2 were hook-machinery guards: a failed required pre-hook blocking an
apply, and running a theme's recorded restore hooks before deleting it. v2 runs
no scripts at all, so both retire with the hooks rather than becoming tests.
DESIGN.md F9, and ``docs/architecture.md`` records the reasoning.)

The ``engine`` fixture is the isolation seam. Settings go to an in-memory
GSettings backend; files go under a temporary destination root; state goes to a
temporary state directory. Nothing in this directory can reach the desktop the
tests are running on — which matters more than usual here, because this machine
runs a heavily customised desktop and several of these tests are about writing
``enabled-extensions``.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from gtheme.core import backends
from gtheme.core.settings_backend import MemoryBackend

#: A stand-in for the one shared list every Look unions into, plus a couple of
#: ordinary keys. Compiled fresh per test rather than borrowing the machine's
#: own schemas, so the suite behaves the same on a machine with no GNOME.
SHELL_SCHEMA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<schemalist>
  <schema id="org.gnome.shell" path="/org/gnome/shell/">
    <key name="enabled-extensions" type="as">
      <default>[]</default>
    </key>
  </schema>
  <schema id="org.gnome.desktop.interface" path="/org/gnome/desktop/interface/">
    <key name="color-scheme" type="s">
      <default>'default'</default>
    </key>
    <key name="icon-theme" type="s">
      <default>'Adwaita'</default>
    </key>
    <key name="font-name" type="s">
      <default>'Cantarell 11'</default>
    </key>
  </schema>
</schemalist>
"""

#: Keys the tests below use, spelled once.
SCHEME = "gsettings:org.gnome.desktop.interface color-scheme"
ICONS = "gsettings:org.gnome.desktop.interface icon-theme"
ENABLED = "gsettings:org.gnome.shell enabled-extensions"


@dataclass
class Engine:
    """Everything a transaction test needs, already isolated."""

    backend: MemoryBackend
    dest_root: Path
    state: Path
    extensions_dir: Path

    def install_extension(self, uuid: str) -> Path:
        """Pretend an add-on is present, by making the directory one lives in."""
        directory = self.extensions_dir / uuid
        directory.mkdir(parents=True, exist_ok=True)
        return directory


@pytest.fixture
def engine(
    memory_settings: MemoryBackend,
    tmp_dest_root: Path,
    state_dir: Path,
    schema_source_factory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Engine]:
    """An engine that writes nowhere real.

    Requesting ``memory_settings``, ``tmp_dest_root`` and ``state_dir`` is what
    satisfies the ``mutating`` guard in ``tests/conftest.py`` — the guard reads
    the fixture names, including ones pulled in indirectly like these, so a test
    that asks for ``engine`` is properly seamed.
    """
    backend = MemoryBackend(schema_source=schema_source_factory(SHELL_SCHEMA_XML))
    del memory_settings  # requested for the seam; this one has the schemas

    data_home = tmp_path / "data"
    extensions = data_home / "gnome-shell" / "extensions"
    extensions.mkdir(parents=True)
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))

    from gtheme.core import placeholders

    placeholders.clear_cache()
    with backends.use_backend(backend):
        yield Engine(
            backend=backend,
            dest_root=tmp_dest_root,
            state=state_dir,
            extensions_dir=extensions,
        )
    placeholders.clear_cache()


def pytest_collection_modifyitems(items) -> None:
    """Mark every test that uses ``engine`` as ``mutating``.

    The mark and the seam belong together, and remembering to write both on
    every test is exactly the kind of thing that gets forgotten on the one test
    where it matters. Deriving the mark from the fixture makes it impossible to
    have a test that writes settings without the guard in ``tests/conftest.py``
    watching it — and the seam is already satisfied, because ``engine`` pulls
    in ``memory_settings``, ``tmp_dest_root`` and ``state_dir``.
    """
    for item in items:
        if "engine" in getattr(item, "fixturenames", ()):
            item.add_marker(pytest.mark.mutating)
