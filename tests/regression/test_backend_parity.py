"""The three backends must agree, or restore is a lottery.

A value snapshotted through one backend and written back through another has to
be the same value. The primary backend is native ``Gio.Settings``; the fallback
shells out to ``gsettings`` and ``dconf``; the test seam is a real GSettings
stack bound to memory. If any two of them print the same value differently,
then which backend happened to be in use when a restore point was taken decides
whether it can be restored — and nothing in the app would notice.

What this file can prove, and what it cannot:

* **Reads agree, byte for byte.** Both real backends read the live store here,
  which is a read and nothing more. This machine runs a heavily customised
  desktop, so the values are interesting ones rather than schema defaults.
* **Failures classify identically.** All three raise ``BackendError`` with the
  same ``BackendErrorKind`` for a missing schema and for a missing key. That is
  the property callers branch on — the AS8 skip depends on it.
* **Writes are not tested here.** A write through the Gio or subprocess backend
  goes to the machine's own settings store. The write-parity leg lives in
  ``tests/sandbox/test_dconf_roundtrip.py`` and runs against a private dconf
  inside a private bus (DESIGN.md step 10, Agent F), which is the only place it
  can run honestly. That file is marked ``dconf``, not ``sandbox``: it needs no
  shell, so it runs in a plain ``pytest`` and in CI alongside this one — which
  it did not before review-report M20.
"""

from __future__ import annotations

import shutil

import pytest

from gtheme.core.backends import is_missing
from gtheme.core.settings_backend import (
    BackendError,
    BackendErrorKind,
    GioBackend,
    MemoryBackend,
    SubprocessBackend,
    parse_key,
)

pytest.importorskip("gi.repository.Gio", reason="PyGObject is needed for the native backend")

#: Keys that exist on any GNOME machine and are read, never written.
READABLE = [
    "gsettings:org.gnome.desktop.interface color-scheme",
    "gsettings:org.gnome.desktop.interface icon-theme",
    "gsettings:org.gnome.desktop.interface font-name",
    "gsettings:org.gnome.desktop.interface cursor-theme",
    "gsettings:org.gnome.desktop.background picture-uri",
    "gsettings:org.gnome.shell enabled-extensions",
]

#: Neither of these exists anywhere, which is the point.
NO_SCHEMA = "gsettings:org.gtheme.test.absent.schema some-key"
NO_KEY = "gsettings:org.gnome.desktop.interface gtheme-test-absent-key"


def _has(key: str) -> bool:
    try:
        GioBackend().get(key)
    except BackendError:
        return False
    return True


needs_gsettings = pytest.mark.skipif(
    shutil.which("gsettings") is None, reason="the gsettings command is not installed"
)


@needs_gsettings
@pytest.mark.parametrize("key", READABLE)
def test_the_two_real_backends_read_a_value_identically(key):
    """Read-only. Nothing here writes to the machine's settings."""
    if not _has(key):
        pytest.skip(f"{key} is not installed on this machine")
    assert GioBackend().get(key) == SubprocessBackend().get(key)


@needs_gsettings
@pytest.mark.parametrize("key", READABLE)
def test_a_value_read_from_the_machine_is_writable_text(key):
    """Whatever comes out has to be something that can go back in.

    Checked by parsing it as GVariant, which is what a write does — without
    doing the write.
    """
    if not _has(key):
        pytest.skip(f"{key} is not installed on this machine")
    from gi.repository import GLib

    text = GioBackend().get(key)
    assert GLib.Variant.parse(None, text, None, None).print_(True) == text


@pytest.mark.parametrize("cls", [GioBackend, SubprocessBackend, MemoryBackend])
def test_a_missing_schema_is_the_same_failure_in_every_backend(cls):
    with pytest.raises(BackendError) as caught:
        cls().get(NO_SCHEMA)
    assert caught.value.kind is BackendErrorKind.NO_SCHEMA


@needs_gsettings
@pytest.mark.parametrize("cls", [GioBackend, SubprocessBackend, MemoryBackend])
def test_a_missing_key_is_the_same_failure_in_every_backend(cls):
    with pytest.raises(BackendError) as caught:
        cls().get(NO_KEY)
    assert caught.value.kind is BackendErrorKind.NO_KEY


def test_only_the_subprocess_backend_can_address_a_location_with_no_description():
    """The ``dconf:`` form has no schema, so ``Gio.Settings`` cannot open it.

    This is not a gap to close later; it is why the fallback backend is kept,
    and why ``core.backends.AutoBackend`` routes rather than choosing one.
    """
    with pytest.raises(BackendError) as caught:
        GioBackend().get("dconf:/org/gnome/shell/extensions/example/thing")
    assert caught.value.kind is BackendErrorKind.OTHER

    with pytest.raises(BackendError) as caught:
        MemoryBackend().get("dconf:/org/gnome/shell/extensions/example/thing")
    assert caught.value.kind is BackendErrorKind.OTHER


@needs_gsettings
def test_the_router_sends_each_address_to_a_backend_that_can_handle_it():
    from gtheme.core.backends import AutoBackend

    auto = AutoBackend()
    key = "gsettings:org.gnome.desktop.interface color-scheme"
    if _has(key):
        assert auto.get(key) == GioBackend().get(key)
    # A location with no description reaches the subprocess backend, which
    # answers honestly that nothing has ever been written there.
    #
    # That answer is UNSET, not NO_KEY. The assertion here used to read NO_KEY,
    # which is the H7 defect written down as an expectation: NO_KEY means "not
    # on this machine", ``is_missing`` is true of it, and the engine therefore
    # skipped every write to a never-written dconf path — which left the path
    # never-written, so the next apply skipped it again. "Nothing has been
    # written here" and "there is nowhere to write" are different answers and
    # the backend now says which one it means.
    with pytest.raises(BackendError) as caught:
        auto.get("dconf:/org/gtheme/definitely/never/written")
    assert caught.value.kind is BackendErrorKind.UNSET
    assert not is_missing(caught.value)


@pytest.mark.parametrize(
    "key",
    [
        "gsettings:org.gnome.desktop.interface color-scheme",
        "dconf:/org/gnome/shell/extensions/blur-my-shell/panel/blur",
        "gsettings-path:org.gnome.shell.extensions.burn-my-windows-profile:"
        "/org/gnome/shell/extensions/burn-my-windows/profiles/1/ name",
    ],
)
def test_every_address_form_round_trips_through_the_grammar(key):
    """One string in, the same string out. Every backend parses with this."""
    assert parse_key(key).as_text() == key
