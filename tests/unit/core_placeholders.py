"""``{{ }}`` tokens: resolved, or skipped with a reason. Never guessed at.

A Look cannot write down the address of a Ptyxis profile setting, because the
profile identifier is generated on the machine it is installed on. So it writes
a token and gtheme fills it in.

The failure mode is the interesting part. If the probe finds nothing, there are
two wrong answers and one right one. Leaving the token means writing a key
literally containing ``{{``. Substituting an empty string means writing
``/Profiles//palette`` — a path with an empty component, which dconf rejects,
and which looks plausible enough that v1 shipped it once. The right answer is a
named skip with a sentence saying what was missing.
"""

from __future__ import annotations

import pytest

from gtheme.core import placeholders
from gtheme.core.placeholders import key_ok, register_probe, resolve, unresolved_tokens


@pytest.fixture(autouse=True)
def _clean_cache():
    placeholders.clear_cache()
    yield
    placeholders.clear_cache()


def test_a_known_token_is_substituted():
    assert resolve("{{ home }}/wall.jpg", {"home": "/home/x"}) == "/home/x/wall.jpg"


def test_whitespace_inside_the_braces_does_not_matter():
    context = {"home": "/home/x"}
    assert resolve("{{home}}", context) == resolve("{{  home  }}", context) == "/home/x"


def test_an_unknown_token_is_left_exactly_as_written():
    """Left, not blanked. The leftover braces are what the gate looks for."""
    assert resolve("{{ mystery }}/x", {}) == "{{ mystery }}/x"


def test_the_gate_refuses_a_key_that_still_has_a_token_in_it():
    assert not key_ok("dconf:/org/gnome/Ptyxis/Profiles/{{ ptyxis_default_profile }}/palette")


def test_the_gate_refuses_a_path_with_an_empty_component():
    """What an empty substitution collapses to. dconf rejects it; so do we."""
    assert not key_ok("dconf:/org/gnome/Ptyxis/Profiles//palette")


def test_the_gate_refuses_an_empty_component_in_a_relocatable_address_too():
    assert not key_ok("gsettings-path:org.a.b://profiles// a-key")


def test_the_gate_passes_ordinary_keys():
    assert key_ok("gsettings:org.gnome.desktop.interface color-scheme")
    assert key_ok("dconf:/org/gnome/shell/extensions/blur-my-shell/panel/blur")
    assert key_ok("gsettings-path:org.a.b:/org/a/b/1/ name")


def test_a_double_slash_elsewhere_in_a_gsettings_key_is_not_a_path_problem():
    """The check is about paths, not about the string containing two slashes."""
    assert key_ok("gsettings:org.gnome.desktop.background picture-uri")


def test_the_names_of_what_is_missing_are_reportable():
    """The skip message has to say *what* was missing, or it helps nobody."""
    assert unresolved_tokens("{{ a }}/{{ b }}/{{ a }}") == ["a", "b"]


def test_a_probe_can_be_registered_and_is_used():
    register_probe("test_token", lambda _backend: "answered")
    try:
        assert placeholders.runtime_context()["test_token"] == "answered"
    finally:
        placeholders._PROBES.pop("test_token", None)
        placeholders.clear_cache()


def test_a_probe_that_answers_nothing_leaves_its_token_unresolved():
    register_probe("test_absent", lambda _backend: None)
    try:
        context = placeholders.runtime_context()
        assert "test_absent" not in context
        assert not key_ok(resolve("dconf:/x/{{ test_absent }}/y", context).replace("/x//y", "//"))
    finally:
        placeholders._PROBES.pop("test_absent", None)
        placeholders.clear_cache()


def test_a_probe_that_raises_does_not_stop_an_apply():
    """A broken probe is one setting skipped, not a failed transaction."""

    def broken(_backend):
        raise RuntimeError("the probe exploded")

    register_probe("test_broken", broken)
    try:
        context = placeholders.runtime_context()
        assert "test_broken" not in context
    finally:
        placeholders._PROBES.pop("test_broken", None)
        placeholders.clear_cache()


def test_the_ptyxis_probe_treats_an_unset_profile_as_absent():
    """The v1 bug in miniature.

    The schema default is the empty string, which prints as two quote
    characters. Stripping after the emptiness test leaves a token that resolves
    to nothing and produces ``/Profiles//palette``.
    """

    class UnsetPtyxis:
        def get(self, _key):
            return "''"

        def set(self, _key, _value):  # pragma: no cover - never called
            raise AssertionError

        def reset(self, _key):  # pragma: no cover - never called
            raise AssertionError

    from gtheme.core.placeholders import _probe_ptyxis_default_profile

    assert _probe_ptyxis_default_profile(UnsetPtyxis()) is None


def test_the_ptyxis_probe_unquotes_a_real_profile():
    class RealPtyxis:
        def get(self, _key):
            return "'2f9b1a44'"

        def set(self, _key, _value):  # pragma: no cover
            raise AssertionError

        def reset(self, _key):  # pragma: no cover
            raise AssertionError

    from gtheme.core.placeholders import _probe_ptyxis_default_profile

    assert _probe_ptyxis_default_profile(RealPtyxis()) == "2f9b1a44"


def test_the_home_token_follows_the_destination_root(monkeypatch, tmp_path):
    """So a test's Looks expand into a temporary directory, not a real home."""
    monkeypatch.setenv("GTHEME_DEST_ROOT", str(tmp_path))
    placeholders.clear_cache()
    assert placeholders.runtime_context()["home"] == str(tmp_path)
