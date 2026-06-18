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


def test_package_installed_finds_a_real_binary():
    # 'sh' is on PATH everywhere these tests run.
    assert package_installed("sh") is True


def test_package_installed_false_for_nonsense():
    assert package_installed("definitely-not-a-real-package-xyz") is False
