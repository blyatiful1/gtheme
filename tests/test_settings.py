"""Tests for settings helpers hardened by the audit (AS2/AS5/AS7, P3)."""

from __future__ import annotations

from gtheme import settings
from gtheme.validate import package_installed


def test_values_equal_identical():
    assert settings.values_equal("'zoom'", "'zoom'") is True


def test_values_equal_none_current():
    assert settings.values_equal(None, "'zoom'") is False


def test_values_equal_trims_surrounding_whitespace():
    # Fallback (no PyGObject) still trims leading/trailing whitespace so a stray
    # newline/space in the read-back value isn't reported as "changed".
    assert settings.values_equal("'zoom'\n", "'zoom'") is True
    assert settings.values_equal("  'zoom'  ", "'zoom'") is True


def test_values_equal_canonicalises_with_glib_if_available():
    # Internal-whitespace/quote-style canonicalisation needs GLib (present on a
    # real GNOME box). Skip cleanly where PyGObject isn't installed.
    import pytest

    try:
        from gi.repository import GLib  # noqa: F401
    except Exception:  # noqa: BLE001
        pytest.skip("PyGObject not available")
    assert settings.values_equal("[ 'a', 'b' ]", "['a', 'b']") is True


def test_values_equal_real_difference():
    assert settings.values_equal("'zoom'", "'centered'") is False


def test_run_forces_c_locale(monkeypatch):
    # apply/restore classify "No such schema/key" by English substring; gettext
    # localizes gsettings errors, so _run must pin the C locale (merged env).
    seen = {}

    class _P:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(settings.subprocess, "run",
                        lambda args, **kw: seen.update(kw) or _P())
    monkeypatch.setenv("LC_ALL", "de_DE.UTF-8")
    monkeypatch.setenv("LANGUAGE", "de")
    code, _out, _err = settings._run(["gsettings", "get", "a", "b"])
    assert code == 0
    env = seen["env"]
    assert env["LC_ALL"] == "C" and env["LC_MESSAGES"] == "C" and env["LANGUAGE"] == "C"
    assert "PATH" in env  # os.environ merged, not replaced


def _ptyxis_ctx(monkeypatch, raw):
    """runtime_context() with gsettings_get faked to return ``raw`` for Ptyxis."""
    monkeypatch.setattr(settings, "gsettings_get", lambda schema, key: raw)
    settings.runtime_context.cache_clear()
    try:
        return settings.runtime_context()
    finally:
        settings.runtime_context.cache_clear()


def test_runtime_context_empty_ptyxis_uuid_is_dropped(monkeypatch):
    # live-probe-0: the schema default is '' (raw "''") — must NOT yield an
    # empty ptyxis_default_profile (which templates into a '//' dconf path).
    ctx = _ptyxis_ctx(monkeypatch, "''")
    assert "ptyxis_default_profile" not in ctx


def test_runtime_context_unset_ptyxis_uuid_is_dropped(monkeypatch):
    ctx = _ptyxis_ctx(monkeypatch, None)
    assert "ptyxis_default_profile" not in ctx


def test_runtime_context_real_ptyxis_uuid_is_stripped(monkeypatch):
    ctx = _ptyxis_ctx(monkeypatch, "'abc-123'\n")
    assert ctx["ptyxis_default_profile"] == "abc-123"


def test_package_installed_finds_a_real_binary():
    # 'sh' is on PATH everywhere these tests run.
    assert package_installed("sh") is True


def test_package_installed_false_for_nonsense():
    assert package_installed("definitely-not-a-real-package-xyz") is False
