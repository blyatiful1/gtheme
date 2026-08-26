"""Installing an add-on: the retry rule, the two paths, and the two sentences.

The rules under test here are the ones that cost somebody a session:

* the state watcher is armed **before** the install request goes out;
* a request that outlives its reply timeout is **never** sent a second time;
* what gtheme promises is decided by asking the desktop what it knows, not by
  assuming the install worked.
"""

from __future__ import annotations

import pytest
from ego_fakes import (
    FakeRunner,
    FakeShellProxy,
    RecordedTransport,
    network_error,
)

from gtheme.core.transaction import ExtensionEnable, Transaction
from gtheme.ego.client import EgoClient
from gtheme.ego.install import (
    COPY,
    CommandResult,
    ExtensionInstaller,
    InstallOutcome,
    enable_transaction,
)
from gtheme.ego.models import ExtensionRecord
from gtheme.ego.shelldbus import ShellError, ShellErrorKind, ShellExtensions
from gtheme.ui import jargon

ZIP = b"PK\x03\x04a-real-looking-package"


def info(uuid: str, **overrides) -> dict:
    payload = {"uuid": uuid, "name": uuid.split("@")[0], "state": 1.0, "type": 2.0}
    payload.update(overrides)
    return payload


def build(extensions=None, *, routes=None, runner=None):
    proxy = FakeShellProxy(extensions or {})
    shell = ShellExtensions(proxy)
    shell.load()
    client = EgoClient(RecordedTransport(routes or {}), "50.4") if routes is not None else None
    installer = ExtensionInstaller(shell, client, runner=runner or FakeRunner())
    return installer, proxy, shell


# -- the live path ---------------------------------------------------------


def test_the_watcher_is_armed_before_the_request_goes_out():
    """A watcher armed after the call misses exactly the case it exists for."""
    installer, proxy, _ = build()
    order: list[str] = []

    class Ordered(FakeShellProxy):
        def connect_state_changed(self, handler):
            order.append("armed")
            return super().connect_state_changed(handler)

        def install_remote(self, uuid, callback):
            order.append("called")
            return super().install_remote(uuid, callback)

    proxy = Ordered({})
    shell = ShellExtensions(proxy)
    shell.load()
    order.clear()  # loading subscribes too; only the install sequence matters
    installer = ExtensionInstaller(shell)
    proxy.install_script = [("successful", None)]
    installer.install_live("new@thing", lambda report: None)
    assert order == ["armed", "called"]


def test_a_confirmed_install_that_the_desktop_now_runs_says_it_is_on():
    installer, proxy, _ = build()

    def scripted(uuid, callback):
        proxy.arrive(uuid)  # the desktop loads it, then answers
        callback("successful", None)

    proxy.install_remote = scripted  # type: ignore[method-assign]
    box: list = []
    installer.install_live("new@thing", box.append)
    report = box[0]
    assert report.outcome is InstallOutcome.ACTIVE
    assert report.message == COPY[InstallOutcome.ACTIVE]
    assert "log out" not in report.message


def test_a_confirmed_install_the_desktop_cannot_see_says_log_out():
    """Files on disk that the running desktop never scanned are not "on now"."""
    installer, proxy, _ = build()
    proxy.install_script = [("successful", None)]
    box: list = []
    installer.install_live("unscanned@thing", box.append)
    report = box[0]
    assert report.outcome is InstallOutcome.NEEDS_RELOGIN
    assert "log out and back in" in report.message


def test_an_add_on_that_is_known_but_stopped_is_simply_switched_on():
    installer, proxy, _ = build({"a@b": info("a@b", state=2.0)})
    proxy.install_script = [("successful", None)]
    box: list = []
    installer.install_live("a@b", box.append)
    assert box[0].outcome is InstallOutcome.ACTIVE
    assert proxy.enable_calls == ["a@b"]


def test_an_add_on_that_is_already_running_is_not_installed_again():
    installer, proxy, _ = build({"a@b": info("a@b")})
    box: list = []
    installer.install_live("a@b", box.append)
    assert box[0].outcome is InstallOutcome.ACTIVE
    assert box[0].message == COPY["already-on"]
    assert proxy.install_calls == []


def test_saying_no_to_the_box_is_a_cancellation_not_a_failure():
    installer, proxy, _ = build()
    proxy.install_script = [("cancelled", None)]
    box: list = []
    installer.install_live("new@thing", box.append)
    assert box[0].outcome is InstallOutcome.CANCELLED
    assert box[0].ok is False


def test_a_request_that_outlives_its_timeout_is_never_sent_again():
    """A second call re-imports a loaded add-on into a state only a log-out clears."""
    installer, proxy, _ = build()
    proxy.install_script = [
        (None, ShellError(ShellErrorKind.NO_REPLY, "timed out")),
    ]
    box: list = []
    watcher = installer.install_live("slow@thing", box.append)
    assert box[0].outcome is InstallOutcome.WAITING_FOR_CONFIRMATION
    assert proxy.install_calls == ["slow@thing"]

    # …and the follow-up looks, rather than asking again.
    proxy.arrive("slow@thing")
    later = installer.resolve_pending("slow@thing", watcher)
    assert later.outcome is InstallOutcome.ACTIVE
    assert proxy.install_calls == ["slow@thing"]


def test_a_timeout_after_the_add_on_already_started_is_reported_as_success():
    installer, proxy, _ = build()

    def scripted(uuid, callback):
        proxy.arrive(uuid)  # the signal arrives while the call is still open
        callback(None, ShellError(ShellErrorKind.NO_REPLY, "timed out"))

    proxy.install_remote = scripted  # type: ignore[method-assign]
    box: list = []
    installer.install_live("slow@thing", box.append)
    assert box[0].outcome is InstallOutcome.ACTIVE


def test_a_machine_that_forbids_adding_add_ons_says_so_plainly():
    installer, proxy, _ = build()
    proxy.install_script = [(None, ShellError(ShellErrorKind.NOT_ALLOWED, "no"))]
    box: list = []
    installer.install_live("new@thing", box.append)
    assert box[0].outcome is InstallOutcome.NOT_ALLOWED
    assert box[0].message == COPY[InstallOutcome.NOT_ALLOWED]


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (ShellErrorKind.DOWNLOAD_FAILED, COPY["download-failed"]),
        (ShellErrorKind.ENABLE_FAILED, COPY["would-not-start"]),
        (ShellErrorKind.OTHER, COPY[InstallOutcome.FAILED]),
    ],
)
def test_each_failure_gets_its_own_sentence(kind, expected):
    installer, proxy, _ = build()
    proxy.install_script = [(None, ShellError(kind, "boom"))]
    box: list = []
    installer.install_live("new@thing", box.append)
    assert box[0].outcome is InstallOutcome.FAILED
    assert box[0].message == expected


def test_an_incompatible_add_on_is_refused_before_a_box_appears_for_nothing():
    installer, proxy, _ = build()
    record = ExtensionRecord.from_json(
        {"uuid": "old@thing", "name": "Old", "shell_version_map": {"3.36": {"pk": 1, "version": 1}}}
    )
    box: list = []
    installer.install_live("old@thing", box.append, record=record)
    assert box[0].outcome is InstallOutcome.NOT_COMPATIBLE
    assert proxy.install_calls == []


def test_the_user_is_told_where_the_confirmation_box_is():
    installer, proxy, _ = build()
    proxy.install_script = [("cancelled", None)]
    hints: list[str] = []
    installer.install_live("new@thing", lambda r: None, on_dialog=hints.append)
    assert hints == [COPY["confirm-on-screen"]]


# -- the package path ------------------------------------------------------


def test_the_package_path_compiles_the_settings_descriptions():
    """Unpacking the zip by hand leaves an add-on whose own settings window is empty."""
    runner = FakeRunner()
    installer, _proxy, _ = build(routes={"/download-extension/": ZIP}, runner=runner)
    box: list = []
    installer.install_package("new@thing", 69740, box.append)
    assert runner.calls, "the package is handed to the desktop's own installer"
    argv = runner.calls[0]
    assert argv[:3] == ["gnome-extensions", "install", "--force"]
    assert argv[3].endswith("new@thing.shell-extension.zip")


def test_the_package_path_never_claims_the_add_on_is_running():
    installer, _proxy, _ = build(routes={"/download-extension/": ZIP})
    box: list = []
    installer.install_package("new@thing", 69740, box.append)
    report = box[0]
    assert report.outcome is InstallOutcome.NEEDS_RELOGIN
    assert "log out and back in" in report.message
    assert report.via == "package"


def test_the_package_path_plans_the_enable_step_through_the_transaction_layer():
    installer, _proxy, _ = build(routes={"/download-extension/": ZIP})
    box: list = []
    installer.install_package("new@thing", 69740, box.append, alternates=("alt@thing",))
    transaction = box[0].transaction
    assert isinstance(transaction, Transaction)
    assert transaction.ops == (ExtensionEnable(uuid="new@thing", alternates=("alt@thing",)),)


def test_a_download_that_fails_does_not_run_anything():
    runner = FakeRunner()
    installer, _proxy, _ = build(
        routes={"/download-extension/": network_error()}, runner=runner
    )
    box: list = []
    installer.install_package("new@thing", 1, box.append)
    assert box[0].outcome is InstallOutcome.FAILED
    assert box[0].message == COPY["download-failed"]
    assert runner.calls == []


def test_a_refusal_from_the_unpacker_is_reported_and_nothing_is_promised():
    runner = FakeRunner(CommandResult(2, stderr="not a valid extension"))
    installer, _proxy, _ = build(routes={"/download-extension/": ZIP}, runner=runner)
    box: list = []
    installer.install_package("new@thing", 1, box.append)
    assert box[0].outcome is InstallOutcome.FAILED
    assert box[0].transaction is None


def test_an_add_on_that_was_on_disk_at_the_last_login_can_be_switched_on_live():
    """The one case where the package path may honestly say "on now"."""
    installer, proxy, _ = build(
        {"was-here@x": info("was-here@x", state=6.0)}, routes={"/download-extension/": ZIP}
    )
    box: list = []
    installer.install_package("was-here@x", 1, box.append)
    assert box[0].outcome is InstallOutcome.ACTIVE
    assert proxy.enable_calls == ["was-here@x"]


# -- a whole Look's add-on list -------------------------------------------


def test_a_look_switches_on_what_is_present_as_one_change():
    """The label assertion here used to require the bug in finding install.py:217.

    It asserted ``transaction.label == "NIGHTBLOOM"``, i.e. that an
    add-ons-only transaction wears the Look's name — which is precisely what
    makes the transaction layer treat it as a Look switch and tidy the real
    Look's files and settings off the desktop. The expectation was wrong, so it
    is inverted here; the ops it plans are unchanged.
    """
    installer, _proxy, _ = build({"a@b": info("a@b"), "c@d": info("c@d", state=2.0)})
    transaction, missing = installer.plan_for_look(
        [("a@b", "ego", ()), ("c@d", "ego", ())], label="NIGHTBLOOM"
    )
    assert [op.uuid for op in transaction.ops] == ["a@b", "c@d"]
    assert transaction.label is None
    assert transaction.look is None
    assert missing == []


def test_a_missing_private_add_on_is_a_named_skip_and_never_an_error():
    installer, _proxy, _ = build({"a@b": info("a@b")})
    transaction, missing = installer.plan_for_look(
        [("a@b", "ego", ()), ("intellibar@nightbloom.local", "local-only", ())]
    )
    assert [op.uuid for op in transaction.ops] == ["a@b"]
    assert len(missing) == 1
    assert missing[0].outcome is InstallOutcome.LOCAL_ONLY_MISSING
    assert "still applies" in missing[0].message


def test_the_first_present_alternative_is_the_one_that_is_used():
    installer, _proxy, _ = build({"gtk4-ding@smedius.gitlab.com": info("gtk4-ding@smedius.gitlab.com")})
    transaction, missing = installer.plan_for_look(
        [("ding@rastersoft.com", "ego", ("gtk4-ding@smedius.gitlab.com",))]
    )
    assert [op.uuid for op in transaction.ops] == ["gtk4-ding@smedius.gitlab.com"]
    assert missing == []


# -- switching on ----------------------------------------------------------


def test_turning_on_says_which_of_the_two_things_happened():
    installer, _proxy, _ = build({"a@b": info("a@b", state=2.0)})
    assert installer.turn_on("a@b").message == COPY["turned-on"]
    assert installer.turn_on("ghost@nowhere").message == COPY["turn-on-after-login"]


def test_the_enable_transaction_unions_rather_than_replacing():
    """Replacing the list would switch off every add-on the person chose themselves."""
    transaction = enable_transaction(["a@b"], label="x")
    assert transaction.ops == (ExtensionEnable(uuid="a@b", alternates=()),)


# -- the words themselves --------------------------------------------------


def test_nothing_this_module_says_uses_a_word_the_reader_would_have_to_look_up():
    for key, sentence in COPY.items():
        complaints = jargon.check(sentence, where=str(key))
        assert complaints == [], complaints
