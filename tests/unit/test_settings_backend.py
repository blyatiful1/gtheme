"""The key grammar and the memory backend. Both are frozen contracts."""

from __future__ import annotations

import pytest

from gtheme.core.settings_backend import (
    BackendError,
    BackendErrorKind,
    GioBackend,
    KeyKind,
    MemoryBackend,
    SubprocessBackend,
    parse_key,
)

SCHEMA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<schemalist>
  <schema id="io.github.blyatiful1.GthemeTest" path="/io/github/blyatiful1/gtheme-test/">
    <key name="a-flag" type="b"><default>false</default></key>
    <key name="a-name" type="s"><default>'Adwaita'</default></key>
    <key name="a-count" type="i"><default>3</default></key>
    <key name="a-list" type="as"><default>[]</default></key>
  </schema>
  <schema id="io.github.blyatiful1.GthemeTestRelocatable">
    <key name="a-flag" type="b"><default>false</default></key>
  </schema>
</schemalist>
"""


# -- grammar ---------------------------------------------------------------


def test_parses_the_plain_gsettings_form():
    key = parse_key("gsettings:org.gnome.desktop.interface color-scheme")
    assert key.kind is KeyKind.GSETTINGS
    assert key.schema == "org.gnome.desktop.interface"
    assert key.key == "color-scheme"
    assert key.path is None


def test_parses_the_dconf_form():
    key = parse_key("dconf:/org/gnome/shell/extensions/blur-my-shell/panel/blur")
    assert key.kind is KeyKind.DCONF
    assert key.path == "/org/gnome/shell/extensions/blur-my-shell/panel/blur"


def test_parses_the_relocatable_form():
    text = (
        "gsettings-path:org.gnome.shell.extensions.burn-my-windows-profile:"
        "/org/gnome/shell/extensions/burn-my-windows/profiles/1/ name"
    )
    key = parse_key(text)
    assert key.kind is KeyKind.GSETTINGS_PATH
    assert key.schema == "org.gnome.shell.extensions.burn-my-windows-profile"
    assert key.path == "/org/gnome/shell/extensions/burn-my-windows/profiles/1/"
    assert key.key == "name"


@pytest.mark.parametrize(
    "text",
    [
        "gsettings:org.gnome.desktop.interface",  # no key
        "gsettings:not-a-schema color-scheme",  # schema needs a dot
        "gsettings:org.gnome.desktop.interface Color-Scheme",  # keys are lowercase
        "dconf:relative/path",  # not absolute
        "dconf:/trailing/slash/",  # that is a directory, not a key
        "gsettings-path:org.a.b:/no/trailing/slash key",
        "gsettings-path:org.a.b /path/ key",  # missing the second colon
        "org.gnome.desktop.interface color-scheme",  # no prefix at all
        "nonsense:whatever",
    ],
)
def test_rejects_malformed_keys(text):
    with pytest.raises(BackendError) as caught:
        parse_key(text)
    assert caught.value.kind is BackendErrorKind.OTHER


@pytest.mark.parametrize(
    "text",
    [
        "gsettings:org.gnome.desktop.interface color-scheme",
        "dconf:/org/gnome/shell/extensions/x/blur",
        "gsettings-path:org.a.b:/org/a/b/1/ name",
    ],
)
def test_key_text_round_trips(text):
    assert parse_key(text).as_text() == text


# -- memory backend --------------------------------------------------------


@pytest.fixture
def backend(schema_source_factory):
    return MemoryBackend(schema_source=schema_source_factory(SCHEMA_XML))


ID = "io.github.blyatiful1.GthemeTest"


def test_reads_the_schema_default(backend):
    assert backend.get(f"gsettings:{ID} a-flag") == "false"
    assert backend.get(f"gsettings:{ID} a-name") == "'Adwaita'"
    assert backend.get(f"gsettings:{ID} a-count") == "3"


def test_writes_and_reads_back(backend):
    backend.set(f"gsettings:{ID} a-name", "'Yaru'")
    assert backend.get(f"gsettings:{ID} a-name") == "'Yaru'"


def test_empty_list_keeps_its_type(backend):
    """``@as []`` is the shape that made generic restore work in v1.

    A value that came back as bare ``[]`` would have lost its type, and writing
    it back later hands GVariant something it cannot parse.
    """
    assert backend.get(f"gsettings:{ID} a-list") == "@as []"
    backend.set(f"gsettings:{ID} a-list", "['one', 'two']")
    assert backend.get(f"gsettings:{ID} a-list") == "['one', 'two']"
    backend.set(f"gsettings:{ID} a-list", "@as []")
    assert backend.get(f"gsettings:{ID} a-list") == "@as []"


def test_reset_returns_the_default(backend):
    backend.set(f"gsettings:{ID} a-count", "42")
    assert backend.get(f"gsettings:{ID} a-count") == "42"
    backend.reset(f"gsettings:{ID} a-count")
    assert backend.get(f"gsettings:{ID} a-count") == "3"


def test_missing_schema_is_typed(backend):
    with pytest.raises(BackendError) as caught:
        backend.get("gsettings:io.github.blyatiful1.NoSuchSchema whatever")
    assert caught.value.kind is BackendErrorKind.NO_SCHEMA


def test_missing_key_is_typed(backend):
    with pytest.raises(BackendError) as caught:
        backend.get(f"gsettings:{ID} no-such-key")
    assert caught.value.kind is BackendErrorKind.NO_KEY


def test_wrong_type_is_rejected_not_coerced(backend):
    with pytest.raises(BackendError) as caught:
        backend.set(f"gsettings:{ID} a-count", "'not a number'")
    assert caught.value.kind is BackendErrorKind.OTHER


def test_relocatable_schema_needs_the_path_form(backend):
    with pytest.raises(BackendError) as caught:
        backend.get("gsettings:io.github.blyatiful1.GthemeTestRelocatable a-flag")
    assert caught.value.kind is BackendErrorKind.NO_SCHEMA
    assert "relocatable" in str(caught.value)


def test_relocatable_schema_works_with_a_path(backend):
    key = "gsettings-path:io.github.blyatiful1.GthemeTestRelocatable:/tmp/gtheme-test/one/ a-flag"
    assert backend.get(key) == "false"
    backend.set(key, "true")
    assert backend.get(key) == "true"


def test_two_relocatable_instances_are_independent(backend):
    one = "gsettings-path:io.github.blyatiful1.GthemeTestRelocatable:/tmp/gtheme-test/one/ a-flag"
    two = "gsettings-path:io.github.blyatiful1.GthemeTestRelocatable:/tmp/gtheme-test/two/ a-flag"
    backend.set(one, "true")
    assert backend.get(two) == "false"


def test_memory_backend_refuses_raw_dconf_paths(backend):
    with pytest.raises(BackendError) as caught:
        backend.get("dconf:/org/gnome/desktop/interface/color-scheme")
    assert caught.value.kind is BackendErrorKind.OTHER


def test_writes_never_reach_a_real_store(backend, schema_source_factory):
    """Two memory backends do not see each other's writes."""
    other = MemoryBackend(schema_source=schema_source_factory(SCHEMA_XML))
    backend.set(f"gsettings:{ID} a-flag", "true")
    assert other.get(f"gsettings:{ID} a-flag") == "false"


# -- the two real backends -------------------------------------------------
#
# Wave 1 landed these bodies; this block used to assert they were stubs. Both
# are exercised properly in tests/unit/core_settings_backend.py, against
# throwaway schemas and never against the machine's own settings. What is left
# here is the shape assertion the frozen contract cares about: whatever goes
# wrong, a caller gets a typed BackendError and never a bare exception.


@pytest.mark.parametrize("cls", [GioBackend, SubprocessBackend])
@pytest.mark.parametrize("method", ["get", "set", "reset"])
def test_both_backends_raise_typed_errors_for_an_unknown_schema(cls, method):
    backend = cls()
    args = ["gsettings:org.gtheme.definitely.not.installed a-key"]
    if method == "set":
        args.append("true")
    with pytest.raises(BackendError) as caught:
        getattr(backend, method)(*args)
    assert caught.value.kind in tuple(BackendErrorKind)
