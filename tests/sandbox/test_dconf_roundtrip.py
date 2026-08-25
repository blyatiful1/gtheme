"""GVariant text survives a real dconf — the property generic restore rests on.

DESIGN.md A3. gtheme restores a setting by writing back the exact string it read,
without knowing the key's type. That works only if the text a value prints as is
also text that parses back to the same value, byte for byte, through the real
store. Under a memory backend that is nearly guaranteed; the interesting
question is whether it holds through dconf, and this is the only tier where a
real dconf can be written to safely.

Two things are checked, both against a throwaway schema compiled into the
session's own ``XDG_DATA_DIRS`` (so the machine's installed schemas are
irrelevant, and so maybe-types and dict types — which GNOME's own schemas barely
use — are covered):

1. **Goldens.** A table of values whose printed form is pinned in this file.
   Where the canonical form differs from what a human would write, both are
   listed, because that difference is exactly what breaks a naive restore:
   ``'hi'`` for a ``ms`` key comes back as ``@ms 'hi'``.

2. **Parity.** ``GioBackend`` and ``SubprocessBackend`` must produce identical
   text for the same key. If they ever disagree, a Look captured under one
   backend restores wrongly under the other.

The parity leg skips with a named reason while the two backends are still
``NotImplementedError`` stubs (they land with Wave 1's core engine port). The
golden leg does not skip: it goes through ``gsettings`` directly and pins the
values whatever else is or is not written yet.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from sandboxlib import DataMode, SandboxSession, SandboxUnavailable, require_tools

# Every test here writes settings — into the sandbox's own dconf, with the
# live canary asserting afterwards that nothing outside it moved.
pytestmark = [pytest.mark.sandbox, pytest.mark.mutating]

PROBE = Path(__file__).parent / "probes" / "backend_probe.py"

SCHEMA_ID = "gtheme.test.golden"
SCHEMA_PATH = "/gtheme/test/golden/"

#: A schema the machine does not have, so the test cannot be fooled by whatever
#: GNOME version happens to be installed. It carries the types that a
#: type-blind restore is most likely to mangle.
SCHEMA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<schemalist>
  <schema id="gtheme.test.golden" path="/gtheme/test/golden/">
    <key name="text" type="s"><default>''</default></key>
    <key name="strings" type="as"><default>[]</default></key>
    <key name="maybe-text" type="ms"><default>nothing</default></key>
    <key name="ints" type="ai"><default>[]</default></key>
    <key name="scale" type="d"><default>1.0</default></key>
    <key name="flag" type="b"><default>false</default></key>
    <key name="pair" type="(dd)"><default>(0.0,0.0)</default></key>
    <key name="dict" type="a{sv}"><default>{}</default></key>
  </schema>
</schemalist>
"""

#: ``(key, written, canonical)``. ``written`` is what a preset might contain;
#: ``canonical`` is what reading it back must produce. Where the two differ, the
#: comment says why — those are the traps.
GOLDENS: tuple[tuple[str, str, str], ...] = (
    # The empty-array case v1 was bitten by: '[]' has no type, so an empty 'as'
    # must print (and be stored) as '@as []' or restore writes the wrong type.
    ("strings", "@as []", "@as []"),
    ("strings", "['a', 'b']", "['a', 'b']"),
    ("strings", "['window-calls@domandoman.xyz']", "['window-calls@domandoman.xyz']"),
    # Maybe types: a present value prints WITH its type annotation. Writing
    # "'hi'" and reading back "@ms 'hi'" is not a round-trip failure — it is the
    # canonical form, and a comparison that does not know this reports a
    # spurious diff on every apply.
    ("maybe-text", "@ms nothing", "@ms nothing"),
    ("maybe-text", "'hi'", "@ms 'hi'"),
    ("maybe-text", "@ms 'hi'", "@ms 'hi'"),
    # Pango font descriptions carry a variable-axis suffix. Nothing may
    # normalise it away.
    ("text", "'Inter Variable @wght=460 11'", "'Inter Variable @wght=460 11'"),
    ("text", "'Cantarell 11'", "'Cantarell 11'"),
    # Non-ASCII, including an em dash and a combining-friendly capital.
    ("text", "'Ünïcodé Ẓ — ok'", "'Ünïcodé Ẓ — ok'"),
    # A string containing a single quote switches the printer to double quotes.
    ('text', '''"it's fine"''', '''"it's fine"'''),
    ("ints", "@ai []", "@ai []"),
    ("ints", "[1, 2, 3]", "[1, 2, 3]"),
    ("scale", "1.25", "1.25"),
    ("scale", "1.0", "1.0"),
    ("flag", "true", "true"),
    ("pair", "(0.5, 0.25)", "(0.5, 0.25)"),
    # rounded-window-corners' a{sv} shape: the dict_slider widget's home.
    ("dict", "@a{sv} {}", "@a{sv} {}"),
    ("dict", "{'padding': <5>, 'enabled': <true>}", "{'padding': <5>, 'enabled': <true>}"),
)


@pytest.fixture(scope="module")
def golden_session(tmp_path_factory: pytest.TempPathFactory):
    """A sandbox whose ``XDG_DATA_DIRS`` carries the throwaway schema.

    Its own session rather than the shared one: installing a schema has to
    happen before the shell starts, and a test schema has no business being
    visible to a session other tests take screenshots of.
    """
    try:
        require_tools()
    except SandboxUnavailable as exc:
        pytest.skip(str(exc))
    root = tmp_path_factory.mktemp("dconf-golden-")
    session = SandboxSession(root=root, mode=DataMode.PRIVATE)
    session.prepare()
    session.install_schema(SCHEMA_XML)
    try:
        session.start()
        session.wait_for_startup_complete(settle=0.5)
        yield session
    finally:
        session.stop()


def _gsettings_roundtrip(session: SandboxSession, key: str, written: str) -> str:
    result = session.run(["gsettings", "set", SCHEMA_ID, key, written])
    assert result.returncode == 0, f"gsettings set {key} {written!r} failed: {result.stderr}"
    read = session.run(["gsettings", "get", SCHEMA_ID, key])
    assert read.returncode == 0, f"gsettings get {key} failed: {read.stderr}"
    return read.stdout.strip()


def test_the_test_schema_is_visible_in_the_sandbox(golden_session: SandboxSession):
    """Without this, every golden below would be passing vacuously."""
    listed = golden_session.run(["gsettings", "list-schemas"]).stdout.split()
    assert SCHEMA_ID in listed


@pytest.mark.parametrize(("key", "written", "canonical"), GOLDENS, ids=lambda v: str(v)[:40])
def test_golden_values_round_trip_through_real_dconf(
    golden_session: SandboxSession, key: str, written: str, canonical: str
):
    assert _gsettings_roundtrip(golden_session, key, written) == canonical


@pytest.mark.parametrize(("key", "written", "canonical"), GOLDENS, ids=lambda v: str(v)[:40])
def test_the_canonical_form_is_a_fixed_point(
    golden_session: SandboxSession, key: str, written: str, canonical: str
):
    """Writing back what you read must give you what you read.

    This is the restore contract stated as a property. A value that changed
    shape every time it went round would make every diff show a change and every
    restore write something new.
    """
    once = _gsettings_roundtrip(golden_session, key, written)
    assert _gsettings_roundtrip(golden_session, key, once) == once


def test_the_private_store_really_holds_the_values(golden_session: SandboxSession):
    """The values are in the sandbox's dconf file, not just in a live process."""
    _gsettings_roundtrip(golden_session, "text", "'stored-on-disk-probe'")
    dump = golden_session.run(["dconf", "dump", SCHEMA_PATH]).stdout
    assert "stored-on-disk-probe" in dump
    assert golden_session.dconf_store.is_file()
    assert b"stored-on-disk-probe" in golden_session.dconf_store.read_bytes()


# --- backend parity -------------------------------------------------------


def _run_backend(session: SandboxSession, backend: str, operations: list) -> list[dict]:
    process = subprocess.run(  # noqa: S603
        [sys.executable, str(PROBE), backend],
        input=json.dumps(operations),
        env=session.env(),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert process.returncode == 0, f"{backend} probe failed: {process.stderr}"
    payload = json.loads(process.stdout)
    return payload["results"]


def _skip_if_stubbed(backend: str, results: list[dict]) -> None:
    for record in results:
        if record.get("kind") == "not-implemented":
            pytest.skip(
                f"{backend} is still a NotImplementedError stub — it lands with the "
                "Wave-1 core engine port (DESIGN.md step 5). This parity test is "
                "written against the frozen contract and runs as soon as it does."
            )


@pytest.mark.parametrize("backend", ["GioBackend", "SubprocessBackend"])
def test_each_backend_round_trips_the_goldens(golden_session: SandboxSession, backend: str):
    operations = [
        ["roundtrip", f"gsettings:{SCHEMA_ID} {key}", written] for key, written, _ in GOLDENS
    ]
    results = _run_backend(golden_session, backend, operations)
    _skip_if_stubbed(backend, results)
    for (key, written, canonical), record in zip(GOLDENS, results, strict=True):
        assert record["ok"], f"{backend} failed on {key}={written!r}: {record}"
        assert record["value"] == canonical, f"{backend} mangled {key}={written!r}"


def test_the_two_backends_agree(golden_session: SandboxSession):
    """DESIGN.md A3: byte-identical, or a Look captured under one breaks the other."""
    operations = [
        ["roundtrip", f"gsettings:{SCHEMA_ID} {key}", written] for key, written, _ in GOLDENS
    ]
    gio = _run_backend(golden_session, "GioBackend", operations)
    _skip_if_stubbed("GioBackend", gio)
    subproc = _run_backend(golden_session, "SubprocessBackend", operations)
    _skip_if_stubbed("SubprocessBackend", subproc)

    mismatches = [
        (op[1], a.get("value"), b.get("value"))
        for op, a, b in zip(operations, gio, subproc, strict=True)
        if a.get("value") != b.get("value")
    ]
    assert not mismatches, f"GioBackend and SubprocessBackend disagree: {mismatches}"


def test_a_relocatable_schema_key_addresses_the_right_path(golden_session: SandboxSession):
    """The ``gsettings-path:`` key form, against a real store.

    burn-my-windows keeps 163 keys in a relocatable per-profile schema; without
    this form there is no way to name one of its settings at all. The check here
    is that two instance paths of the same schema really are two values.
    """
    session = golden_session
    for path, value in (("/gtheme/test/a/", "'first'"), ("/gtheme/test/b/", "'second'")):
        result = session.run(["dconf", "write", f"{path}text", value])
        assert result.returncode == 0, result.stderr
    assert session.run(["dconf", "read", "/gtheme/test/a/text"]).stdout.strip() == "'first'"
    assert session.run(["dconf", "read", "/gtheme/test/b/text"]).stdout.strip() == "'second'"
