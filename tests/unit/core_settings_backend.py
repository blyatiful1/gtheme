"""The two real backends, exercised without touching the machine's settings.

``MemoryBackend`` is a genuine GSettings stack bound to memory, so a wrongly
typed write fails here exactly as it would against dconf. ``GioBackend`` and
``SubprocessBackend`` write to the real store, so what can be checked at this
tier is their *failure* behaviour and their agreement on reads — the write
leg belongs to the sandbox tier, against a private dconf.

The contract those failures have to keep is narrow and load-bearing: every
failure is a ``BackendError`` carrying one of four kinds, and callers branch on
the kind rather than on the message. The AS8 rule — a missing add-on is a skip,
not a failed apply — is exactly that branch, and it is why the subprocess
backend pins ``LC_ALL=C``: it has no other way to tell the two apart, and a
German locale would classify every missing schema as "something broke".
"""

from __future__ import annotations

import shutil

import pytest

from gtheme.core.backends import AutoBackend, has_session_bus, is_missing
from gtheme.core.settings_backend import (
    BackendError,
    BackendErrorKind,
    GioBackend,
    MemoryBackend,
    SettingsKey,
    SubprocessBackend,
    parse_key,
)

SCHEMA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<schemalist>
  <schema id="org.gtheme.test" path="/org/gtheme/test/">
    <key name="a-word" type="s"><default>'default'</default></key>
    <key name="a-list" type="as"><default>[]</default></key>
    <key name="a-number" type="i"><default>0</default></key>
    <key name="a-maybe" type="ms"><default>nothing</default></key>
  </schema>
  <schema id="org.gtheme.test.profile">
    <key name="name" type="s"><default>'unnamed'</default></key>
  </schema>
</schemalist>
"""

WORD = "gsettings:org.gtheme.test a-word"
LIST = "gsettings:org.gtheme.test a-list"
NUMBER = "gsettings:org.gtheme.test a-number"
MAYBE = "gsettings:org.gtheme.test a-maybe"
PROFILE = "gsettings-path:org.gtheme.test.profile:/org/gtheme/profiles/1/ name"


@pytest.fixture
def memory(schema_source_factory) -> MemoryBackend:
    return MemoryBackend(schema_source=schema_source_factory(SCHEMA_XML))


# -- the memory backend as the reference implementation --------------------


def test_a_value_round_trips_exactly(memory):
    memory.set(WORD, "'Cantarell 11 @wght=460'")
    assert memory.get(WORD) == "'Cantarell 11 @wght=460'"


def test_an_empty_list_comes_back_with_its_type(memory):
    assert memory.get(LIST) == "@as []"
    memory.set(LIST, "['a']")
    memory.set(LIST, "@as []")
    assert memory.get(LIST) == "@as []"


def test_a_maybe_type_comes_back_with_its_annotation(memory):
    assert memory.get(MAYBE) == "@ms nothing"
    memory.set(MAYBE, "@ms 'here'")
    assert memory.get(MAYBE) == "@ms 'here'"


def test_a_wrongly_typed_write_is_refused_rather_than_coerced(memory):
    with pytest.raises(BackendError) as caught:
        memory.set(NUMBER, "'not a number'")
    assert caught.value.kind is BackendErrorKind.OTHER


def test_a_reset_returns_the_schema_default(memory):
    memory.set(WORD, "'changed'")
    memory.reset(WORD)
    assert memory.get(WORD) == "'default'"


def test_a_relocatable_setting_needs_its_location(memory):
    """burn-my-windows keeps 163 keys per profile in a schema with no fixed
    location. Addressing it without one is a mistake worth naming."""
    assert memory.get(PROFILE) == "'unnamed'"
    with pytest.raises(BackendError) as caught:
        memory.get("gsettings:org.gtheme.test.profile name")
    assert caught.value.kind is BackendErrorKind.NO_SCHEMA
    assert "needs a path" in str(caught.value)


def test_two_locations_of_the_same_relocatable_schema_are_separate(memory):
    one = "gsettings-path:org.gtheme.test.profile:/org/gtheme/profiles/1/ name"
    two = "gsettings-path:org.gtheme.test.profile:/org/gtheme/profiles/2/ name"
    memory.set(one, "'first'")
    assert memory.get(two) == "'unnamed'"


# -- typed failures --------------------------------------------------------


def test_a_missing_schema_is_named_as_such(memory):
    with pytest.raises(BackendError) as caught:
        memory.get("gsettings:org.gtheme.absent a-key")
    assert caught.value.kind is BackendErrorKind.NO_SCHEMA
    assert is_missing(caught.value)


def test_a_missing_key_is_named_as_such(memory):
    with pytest.raises(BackendError) as caught:
        memory.get("gsettings:org.gtheme.test not-a-key")
    assert caught.value.kind is BackendErrorKind.NO_KEY
    assert is_missing(caught.value)


def test_a_bad_value_is_not_mistaken_for_a_missing_thing(memory):
    """The AS8 branch depends on this: "not here" skips, "broke" fails."""
    with pytest.raises(BackendError) as caught:
        memory.set(NUMBER, "'nope'")
    assert not is_missing(caught.value)


def test_the_failure_carries_the_key_it_was_about(memory):
    with pytest.raises(BackendError) as caught:
        memory.get("gsettings:org.gtheme.absent a-key")
    assert caught.value.key == "gsettings:org.gtheme.absent a-key"


# -- the key grammar -------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "kind", "schema", "key", "path"),
    [
        (
            "gsettings:org.gnome.desktop.interface color-scheme",
            "gsettings",
            "org.gnome.desktop.interface",
            "color-scheme",
            None,
        ),
        (
            "dconf:/org/gnome/shell/extensions/blur-my-shell/panel/blur",
            "dconf",
            None,
            None,
            "/org/gnome/shell/extensions/blur-my-shell/panel/blur",
        ),
        (
            "gsettings-path:org.a.b:/org/a/b/1/ name",
            "gsettings-path",
            "org.a.b",
            "name",
            "/org/a/b/1/",
        ),
    ],
)
def test_the_three_address_forms_parse_and_render_back(text, kind, schema, key, path):
    parsed = parse_key(text)
    assert parsed.kind.value == kind
    assert (parsed.schema, parsed.key, parsed.path) == (schema, key, path)
    assert parsed.as_text() == text


@pytest.mark.parametrize(
    "text",
    [
        "",
        "no-prefix",
        "gsettings:missing-the-key",
        "gsettings:not a schema id",
        "dconf:relative/path",
        "dconf:/trailing/slash/",
        "gsettings-path:org.a.b/no/colon name",
        "gsettings-path:org.a.b:no-leading-slash/ name",
        "gsettings-path:org.a.b:/no/trailing/slash name",
        "elsewhere:org.a.b c",
    ],
)
def test_a_malformed_address_fails_loudly(text):
    """A malformed address is a mistake in a Look or a descriptor, and a
    silently skipped setting is how that mistake ships."""
    with pytest.raises(BackendError) as caught:
        parse_key(text)
    assert caught.value.kind is BackendErrorKind.OTHER


def test_rendering_a_parsed_address_is_stable():
    key = SettingsKey(parse_key("gsettings:org.a.b c").kind, schema="org.a.b", key="c")
    assert parse_key(key.as_text()).as_text() == key.as_text()


# -- the router ------------------------------------------------------------


def test_the_router_refuses_the_same_malformed_addresses():
    with pytest.raises(BackendError):
        AutoBackend().get("nonsense")


def test_the_memory_backend_cannot_address_a_location_with_no_description(memory):
    """No schema means no type, and no type means nothing to validate against."""
    with pytest.raises(BackendError) as caught:
        memory.get("dconf:/org/gnome/shell/extensions/x/y")
    assert caught.value.kind is BackendErrorKind.OTHER


def test_two_memory_backends_do_not_see_each_others_writes(schema_source_factory):
    """The property that makes this the test seam."""
    source = schema_source_factory(SCHEMA_XML)
    first, second = MemoryBackend(source), MemoryBackend(source)
    first.set(WORD, "'only mine'")
    assert second.get(WORD) == "'default'"


# -- the subprocess backend's own rules ------------------------------------


@pytest.mark.skipif(shutil.which("gsettings") is None, reason="gsettings is not installed")
def test_the_subprocess_backend_classifies_a_missing_schema_under_a_pinned_locale():
    """It reads an error message, which is why the locale is pinned.

    This is the only place in gtheme that looks at text to decide what
    happened. Under a translated locale "No such schema" would classify as
    "something broke" and a Look built for a machine with one more add-on
    would fail to apply instead of skipping one line.
    """
    with pytest.raises(BackendError) as caught:
        SubprocessBackend().get("gsettings:org.gtheme.absent.schema a-key")
    assert caught.value.kind is BackendErrorKind.NO_SCHEMA


def test_the_subprocess_backend_says_so_when_the_command_is_missing(monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises(BackendError) as caught:
        SubprocessBackend().get("dconf:/org/gtheme/test/thing")
    assert caught.value.kind is BackendErrorKind.OTHER
    assert "not installed" in str(caught.value)


def test_a_commit_that_did_not_stick_is_its_own_kind():
    """v1's trap: ``gsettings set`` exiting 0 while printing that it failed."""
    error = SubprocessBackend._classify("failed to commit changes to dconf", "gsettings:a.b c")
    assert error.kind is BackendErrorKind.COMMIT_FAILED


def test_error_classification_covers_every_kind_it_can_produce():
    cases = {
        "No such schema “org.a.b”": BackendErrorKind.NO_SCHEMA,
        "No such key “c”": BackendErrorKind.NO_KEY,
        "failed to commit changes to dconf": BackendErrorKind.COMMIT_FAILED,
        "something else entirely": BackendErrorKind.OTHER,
        "": BackendErrorKind.OTHER,
    }
    for text, kind in cases.items():
        assert SubprocessBackend._classify(text, "gsettings:a.b c").kind is kind


@pytest.mark.skipif(shutil.which("gsettings") is None, reason="gsettings is not installed")
def test_the_native_backend_reads_a_relocatable_location_the_same_way():
    """Both real backends address relocatable schemas identically or neither
    can restore burn-my-windows."""
    key = (
        "gsettings-path:org.gtheme.absent.profile:"
        "/org/gtheme/absent/profiles/1/ name"
    )
    for backend in (GioBackend(), SubprocessBackend()):
        with pytest.raises(BackendError) as caught:
            backend.get(key)
        assert caught.value.kind is BackendErrorKind.NO_SCHEMA


# -- the session check -----------------------------------------------------


def test_a_missing_session_is_detected_rather_than_discovered_forty_times(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "empty"))
    assert has_session_bus() is False

    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    assert has_session_bus() is True
