"""The runtime-load verdict, pinned — DESIGN.md A5, F6.

This is the permanent regression port of
``~/gtheme-rebuild/harness/runtime-load-exp/exp2.sh``, run on this box on
2026-08-25. It exists because the whole extension-install design rests on one
empirical fact, and a future GNOME Shell could change it silently:

    On GNOME Shell 50.4, a uuid that was not on disk when the shell ran its
    startup scan NEVER becomes known to the shell. No route reaches it:
    appending to ``enabled-extensions``, ``EnableExtension`` over D-Bus,
    ``gnome-extensions enable``, ``ReloadExtension``, toggling
    ``disable-user-extensions`` off and on, flipping
    ``disable-extension-version-validation`` — every one fails, and the shell
    keeps answering ``GetExtensionInfo`` with an empty dict.

That is why ``InstallRemoteExtension`` (the shell's own downloader, which calls
``loadExtension()`` directly) is the only live install path, and why every other
route has to tell the user honestly that it finishes after they log back in.

The first version of this experiment gated readiness on ``Peer.Ping``, which
answers about 1.5 seconds *before* the extension directory scan runs. It
therefore raced the scan and concluded the opposite. The readiness gate here is
the shell's own "GNOME Shell started at" log line, plus a working
``ListExtensions``, plus a settle — see
:meth:`sandboxlib.SandboxSession.wait_for_startup_complete`.

Three probes, one shell:

``probe-e``  on disk BEFORE the shell starts   — the control: this must load.
``probe-c``  directory created after startup   — must never load.
``probe-d``  ``gnome-extensions install`` after startup — must never load.

If this file ever goes red, do not "fix" it. A green E with a red C or D means
the shell learned to rescan, and DESIGN.md A5 needs rewriting — which is the
whole reason the experiment is in the suite instead of in a report.
"""

from __future__ import annotations

import shutil
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from sandboxlib import (
    DataMode,
    SandboxSession,
    SandboxUnavailable,
    make_probe_extension,
    require_tools,
    zip_extension,
)

pytestmark = pytest.mark.sandbox

UUID_E = "probe-e@gtheme.local"
UUID_C = "probe-c@gtheme.local"
UUID_D = "probe-d@gtheme.local"

#: ExtensionState, from the shell's own enum. D-Bus hands them over as doubles.
STATE_ACTIVE = 1.0
STATE_INITIALIZED = 6.0


@pytest.fixture(scope="module")
def experiment(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict]:
    """Run the whole experiment once; the tests below read its results.

    One shell boot, one ordered sequence of probes, and every observation
    recorded — rather than one shell per assertion, which would take minutes and
    still not be independent, since the ordering *is* the experiment.
    """
    try:
        require_tools()
    except SandboxUnavailable as exc:
        pytest.skip(str(exc))

    root = tmp_path_factory.mktemp("runtime-load-")
    stage = root / "stage"
    for uuid_, marker in ((UUID_E, "E"), (UUID_C, "C"), (UUID_D, "D")):
        make_probe_extension(stage / uuid_, uuid_, marker)
    probe_zip = zip_extension(stage / UUID_D, stage / "probe-d.zip")

    session = SandboxSession(root=root, mode=DataMode.PRIVATE, seed_fixture_extensions=False)

    def stage_e(sess: SandboxSession) -> None:
        """probe-e is on disk before the shell exists, so the scan must see it."""
        shutil.copytree(stage / UUID_E, sess.extensions_dir / UUID_E)

    results: dict = {}
    try:
        session.start(pre_start=stage_e)
        session.wait_for_startup_complete()

        results["known_after_startup"] = session.known_uuids()
        results["e_before_append"] = session.extension_state(UUID_E)

        # --- E: the control. Present at the scan, then enabled. ---------------
        session.gsettings("set", "org.gnome.shell", "enabled-extensions", f"['{UUID_E}']")
        time.sleep(2.0)
        results["e_after_append"] = session.extension_state(UUID_E)
        results["e_markers"] = session.log().count("PROBE_E_ENABLE_MARKER")

        # --- C: directory created after startup-complete ----------------------
        shutil.copytree(stage / UUID_C, session.extensions_dir / UUID_C)
        results["c_dir_exists"] = (session.extensions_dir / UUID_C / "extension.js").is_file()
        results["c_before_append"] = session.extension_state(UUID_C)
        session.gsettings(
            "set", "org.gnome.shell", "enabled-extensions", f"['{UUID_E}', '{UUID_C}']"
        )
        time.sleep(3.0)
        results["c_after_append"] = session.extension_state(UUID_C)
        results["c_markers"] = session.log().count("PROBE_C_ENABLE_MARKER")

        # --- D: gnome-extensions install after startup-complete ---------------
        install = session.run(["gnome-extensions", "install", "--force", str(probe_zip)])
        results["d_install_rc"] = install.returncode
        results["d_dir_exists"] = (session.extensions_dir / UUID_D / "extension.js").is_file()
        results["d_before_append"] = session.extension_state(UUID_D)
        session.gsettings(
            "set",
            "org.gnome.shell",
            "enabled-extensions",
            f"['{UUID_E}', '{UUID_C}', '{UUID_D}']",
        )
        time.sleep(3.0)
        results["d_after_append"] = session.extension_state(UUID_D)
        results["d_markers"] = session.log().count("PROBE_D_ENABLE_MARKER")

        # --- every other route anyone might reach for -------------------------
        results["enable_c"] = session.ext_call("EnableExtension", UUID_C).stdout.strip()
        results["enable_d"] = session.ext_call("EnableExtension", UUID_D).stdout.strip()
        cli = session.run(["gnome-extensions", "enable", UUID_C])
        results["cli_enable_c_rc"] = cli.returncode
        results["cli_enable_c_err"] = (cli.stderr or cli.stdout).strip()
        results["cli_list"] = session.run(["gnome-extensions", "list"]).stdout.split()
        reload_ = session.ext_call("ReloadExtension", UUID_C)
        results["reload_c"] = (reload_.stdout or reload_.stderr).strip()

        # user-extensions toggle: the obvious "make it rescan" gesture
        session.gsettings("set", "org.gnome.shell", "disable-user-extensions", "true")
        time.sleep(1.5)
        session.gsettings("set", "org.gnome.shell", "disable-user-extensions", "false")
        time.sleep(3.0)
        results["c_after_user_toggle"] = session.extension_state(UUID_C)
        results["d_after_user_toggle"] = session.extension_state(UUID_D)
        results["e_after_user_toggle"] = session.extension_state(UUID_E)

        # version-validation flip: reloadExtension() over everything known
        session.gsettings(
            "set", "org.gnome.shell", "disable-extension-version-validation", "true"
        )
        time.sleep(3.0)
        results["c_after_version_flip"] = session.extension_state(UUID_C)
        results["e_after_version_flip"] = session.extension_state(UUID_E)
        session.gsettings(
            "set", "org.gnome.shell", "disable-extension-version-validation", "false"
        )
        time.sleep(1.0)

        # InstallRemoteExtension on a uuid e.g.o has never heard of. Whatever it
        # answers (a download failure offline, "Not Found" online), the uuid on
        # disk must still not become known.
        remote = session.ext_call("InstallRemoteExtension", UUID_C, timeout=60.0)
        results["ire_output"] = (remote.stdout or remote.stderr).strip()[:300]
        time.sleep(1.0)
        results["c_after_ire"] = session.extension_state(UUID_C)

        results["known_at_end"] = session.known_uuids()
        results["log_tail"] = session.log()[-4000:]
        yield results
    finally:
        session.stop()


def test_the_control_loads(experiment: dict):
    """probe-e was on disk for the startup scan, so every step must work.

    Without this, a green suite would prove only that the experiment is broken.
    """
    assert UUID_E in experiment["known_after_startup"], (
        "the control extension was not picked up by the startup scan, so this "
        "run says nothing about runtime loading"
    )
    assert experiment["e_before_append"] == STATE_INITIALIZED
    assert experiment["e_after_append"] == STATE_ACTIVE
    assert experiment["e_markers"] >= 1, "probe-e never logged its enable marker"


def test_a_directory_created_after_startup_is_never_seen(experiment: dict):
    """DESIGN.md A5: no disk rescan, no file monitor, no way in."""
    assert experiment["c_dir_exists"], "the test did not actually create probe-c"
    assert experiment["c_before_append"] is None
    assert experiment["c_after_append"] is None, (
        "probe-c became known to the shell after being appended to "
        "enabled-extensions. The shell now rescans; DESIGN.md A5 is out of date."
    )
    assert experiment["c_markers"] == 0


def test_gnome_extensions_install_after_startup_is_never_seen(experiment: dict):
    """The zip fallback path installs correctly and still cannot load live."""
    assert experiment["d_install_rc"] == 0, "gnome-extensions install itself failed"
    assert experiment["d_dir_exists"], "the zip did not unpack into the extensions dir"
    assert experiment["d_before_append"] is None
    assert experiment["d_after_append"] is None
    assert experiment["d_markers"] == 0


def test_no_dbus_or_cli_route_rescues_an_unscanned_uuid(experiment: dict):
    assert experiment["enable_c"] == "(false,)"
    assert experiment["enable_d"] == "(false,)"
    assert experiment["cli_enable_c_rc"] != 0
    assert UUID_C not in experiment["cli_list"]
    assert UUID_D not in experiment["cli_list"]
    assert UUID_E in experiment["cli_list"]
    assert "NotSupported" in experiment["reload_c"] or "deprecated" in experiment["reload_c"]


def test_toggling_user_extensions_does_not_force_a_rescan(experiment: dict):
    assert experiment["c_after_user_toggle"] is None
    assert experiment["d_after_user_toggle"] is None
    assert experiment["e_after_user_toggle"] == STATE_ACTIVE, (
        "the control stopped working across the toggle, so the negative results "
        "above cannot be attributed to the rescan question"
    )


def test_flipping_version_validation_does_not_force_a_rescan(experiment: dict):
    assert experiment["c_after_version_flip"] is None
    assert experiment["e_after_version_flip"] == STATE_ACTIVE


def test_install_remote_extension_does_not_adopt_a_local_directory(experiment: dict):
    """IRE is the live path *because* it downloads and loads; it adopts nothing.

    Asking it about a uuid that only exists on this disk fails — offline with a
    download error, online with "Not Found" — and either way the local directory
    stays invisible. Which is the point: the live path runs through the shell's
    own downloader, never through the filesystem.
    """
    assert experiment["ire_output"], "InstallRemoteExtension answered nothing at all"
    assert experiment["c_after_ire"] is None


def test_the_verdict_holds_at_the_end(experiment: dict):
    known = experiment["known_at_end"]
    assert UUID_E in known
    assert UUID_C not in known
    assert UUID_D not in known


def test_the_experiment_left_no_extension_behind(experiment: dict):
    """Belt and braces on top of the autouse canary."""
    user_dir = Path.home() / ".local/share/gnome-shell/extensions"
    for uuid_ in (UUID_E, UUID_C, UUID_D):
        assert not (user_dir / uuid_).exists(), f"{uuid_} was installed into the REAL session"
