"""Two audit findings about the add-on install pipeline, pinned.

* **M4** — the unpacker is a program on disk, and a computer that does not have
  it made the whole batch hang. The exception was raised inside a download
  callback, where the loop that dispatched it prints the traceback and carries
  on, so the batch's "this one landed" callback never fired and the progress
  dialog stayed up for its full three-minute timeout before saying something
  that named nothing. A command that cannot be started is a failed command.

* **H6 (the data half)** — a person was asked to accept third-party code by
  count: "this Look uses 3 add-ons you don't have", with a button next to it.
  Which three is the entire question. The install pipeline now names them —
  title, author, and the one address anything is ever downloaded from — before
  a single byte is fetched, and a lookup that fails costs a title, never a
  name. The dialog that shows this list is a separate change; these tests pin
  the data it will show.
"""

from __future__ import annotations

import json

import pytest
from ego_fakes import FakeRunner, FakeShellProxy, RecordedTransport, network_error

from gtheme.ego.client import EgoClient
from gtheme.ego.install import (
    AddonBrief,
    CommandResult,
    ExtensionInstaller,
    InstallOutcome,
    SubprocessRunner,
    describe_addons,
    readable_name,
)
from gtheme.ego.shelldbus import ShellError, ShellErrorKind, ShellExtensions
from gtheme.ui import jargon

ZIP = b"PK\x03\x04a-real-looking-package"

BLUR = "blur-my-shell@aunetx"


def library_entry(uuid: str, name: str, creator: str) -> bytes:
    """One ``/extension-info/`` answer, as the library sends it."""
    return json.dumps({"uuid": uuid, "name": name, "creator": creator, "pk": 3193}).encode()


def build(extensions=None, *, routes=None, runner=None):
    proxy = FakeShellProxy(extensions or {})
    shell = ShellExtensions(proxy)
    shell.load()
    transport = RecordedTransport(routes or {}) if routes is not None else None
    client = EgoClient(transport, "50.4") if transport is not None else None
    installer = ExtensionInstaller(shell, client, runner=runner or FakeRunner())
    return installer, transport


# -- M4: a missing unpacker ------------------------------------------------


class MissingCommandRunner:
    """The runner a computer without ``gnome-extensions`` really has."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(self, argv):
        self.calls.append(list(argv))
        raise FileNotFoundError(2, "No such file or directory", argv[0])


def test_a_missing_unpacker_is_a_report_and_not_an_exception_nobody_catches():
    """Before the fix this escaped the download callback and hung the batch."""
    runner = MissingCommandRunner()
    installer, _transport = build(routes={"/download-extension/": ZIP}, runner=runner)
    box: list = []

    installer.install_package(BLUR, 69740, box.append)

    assert runner.calls, "the unpacker was attempted"
    assert len(box) == 1, "the caller is told exactly once, so the batch moves on"
    report = box[0]
    assert report.outcome is InstallOutcome.FAILED
    assert report.transaction is None
    assert "gnome-extensions" in str(report.error)


def test_the_real_runner_answers_a_missing_command_instead_of_raising():
    """127 is the shell's own number for it, and `ok` is already False for it."""
    result = SubprocessRunner().run(["gtheme-no-such-command-e3f1a7"])

    assert isinstance(result, CommandResult)
    assert result.returncode == 127
    assert not result.ok
    assert result.stderr, "the reason is carried, for the log"


# -- H6: naming the batch before it is fetched -----------------------------


def test_a_batch_is_named_before_anything_is_downloaded():
    installer, transport = build(
        routes={"/extension-info/": library_entry(BLUR, "Blur my Shell", "aunetx")}
    )
    seen: list = []

    installer.describe_batch([(BLUR, "ego", ())], seen.append)

    assert len(seen) == 1
    briefs = seen[0]
    assert [b.uuid for b in briefs] == [BLUR]
    assert briefs[0].display_title == "Blur my Shell"
    assert briefs[0].creator == "aunetx"
    assert "extensions.gnome.org" in briefs[0].source_line
    assert not any("download-extension" in url for url in transport.requests), (
        "naming the batch must not fetch any of it"
    )


def test_an_add_on_the_library_will_not_describe_is_still_named():
    """A list somebody has to agree to may not depend on a request that fails."""
    installer, _transport = build(routes={"/extension-info/": network_error()})
    seen: list = []

    installer.describe_batch([(BLUR, "ego", ())], seen.append)

    brief = seen[0][0]
    assert brief.display_title == "Blur my shell"
    assert "extensions.gnome.org" in brief.source_line


def test_a_private_add_on_is_named_and_never_looked_up():
    installer, transport = build(routes={})
    seen: list = []

    installer.describe_batch([("intellibar@nightbloom.local", "local-only", ())], seen.append)

    brief = seen[0][0]
    assert brief.display_title == "Intellibar"
    assert transport.requests == [], "a private add-on is not on the website"
    assert "never downloads" in brief.source_line


def test_every_add_on_in_the_batch_comes_back_once_and_in_order():
    installer, _transport = build(
        routes={"/extension-info/": library_entry(BLUR, "Blur my Shell", "aunetx")}
    )
    seen: list = []

    installer.describe_batch(
        [
            (BLUR, "ego", ()),
            ("intellibar@nightbloom.local", "local-only", ()),
            ("just-perfection-desktop@just-perfection", "ego", ()),
        ],
        seen.append,
    )

    assert len(seen) == 1, "one answer for the whole batch, never one per add-on"
    assert [b.uuid for b in seen[0]] == [
        BLUR,
        "intellibar@nightbloom.local",
        "just-perfection-desktop@just-perfection",
    ]


def test_a_look_s_missing_add_ons_carry_their_names_and_their_source():
    """``plan_for_look`` used to hand back a list that could only be counted."""
    installer, _transport = build()

    _transaction, missing = installer.plan_for_look(
        [(BLUR, "ego", ()), ("intellibar@nightbloom.local", "local-only", ())]
    )

    assert [report.brief.uuid for report in missing] == [
        BLUR,
        "intellibar@nightbloom.local",
    ]
    assert [report.brief.source for report in missing] == ["ego", "local-only"]
    assert [report.display_title for report in missing] == ["Blur my shell", "Intellibar"]


def test_the_name_shown_is_never_the_internal_identifier():
    """gtheme does not put identifiers on screen; the brief carries one anyway."""
    briefs = [
        AddonBrief(uuid=BLUR, source="ego"),
        AddonBrief(uuid="intellibar@nightbloom.local", source="local-only"),
    ]

    for line in describe_addons(briefs):
        assert "@" not in line


def test_the_words_gtheme_supplies_around_the_name_are_plain():
    """Only gtheme's own half is checked.

    An add-on is called what its author called it — "Blur my Shell" contains a
    word the house style bans, and renaming somebody else's add-on to satisfy
    our own rule would be worse than saying it. What gtheme writes is the
    clause after the name, and that is held to the rule.
    """
    for source in ("ego", "local-only"):
        brief = AddonBrief(uuid=BLUR, source=source)
        assert jargon.check(brief.source_line) == []


@pytest.mark.parametrize(
    ("uuid", "expected"),
    [
        (BLUR, "Blur my shell"),
        ("user-theme@gnome-shell-extensions.gcampax.github.com", "User theme"),
        ("dash-to-dock@micxgx.gmail.com", "Dash to dock"),
        ("no-at-sign", "No at sign"),
    ],
)
def test_a_readable_name_is_worked_out_from_the_file_name(uuid, expected):
    assert readable_name(uuid) == expected


# -- H6: the desktop going away must not hang the batch --------------------


class DesktopGoesAway(FakeShellProxy):
    """A desktop that answers, and then is not there any more.

    The shape of the real failure: the Look's add-on list is planned while the
    session bus is up, and by the time the download callback lands the desktop
    has gone (a shell restart, a crash, a bus that stopped answering). Every
    call after :attr:`alive` is cleared raises, exactly as
    ``ShellProxy._call`` does when GLib hands it an error.
    """

    def __init__(self, extensions=None):
        super().__init__(extensions or {})
        self.alive = True

    def _gone(self):
        return ShellError(ShellErrorKind.UNAVAILABLE, "the desktop is not there")

    def get_extension_info(self, uuid):
        if not self.alive:
            raise self._gone()
        return super().get_extension_info(uuid)

    def list_extensions(self):
        if not self.alive:
            raise self._gone()
        return super().list_extensions()

    def enable_extension(self, uuid):
        if not self.alive:
            raise self._gone()
        return super().enable_extension(uuid)


def _installer_on(proxy, *, routes, runner=None):
    shell = ShellExtensions(proxy)
    shell.load()
    transport = RecordedTransport(routes)
    return ExtensionInstaller(shell, EgoClient(transport, "50.4"), runner=runner or FakeRunner())


def test_a_desktop_that_went_away_is_a_report_and_not_a_batch_that_never_ends():
    """The whole install path, with the desktop gone before the download lands.

    An exception here does not reach anybody: it is raised inside the library's
    download callback, which the main loop dispatched and whose traceback the
    main loop prints. The batch's "this one landed" callback never fires and
    the progress dialog waits out its full three-minute timeout before saying
    something that names nothing.
    """
    proxy = DesktopGoesAway()
    installer = _installer_on(proxy, routes={"/download-extension/": ZIP})
    _transaction, missing = installer.plan_for_look([(BLUR, "ego", ())])
    assert [report.uuid for report in missing] == [BLUR], "planned while the desktop was up"

    proxy.alive = False
    box: list = []
    installer.install_package(BLUR, 69740, box.append)

    assert len(box) == 1, "the caller is told exactly once, so the batch moves on"
    report = box[0]
    assert report.outcome is InstallOutcome.NEEDS_RELOGIN
    assert report.transaction is not None, "the enable step is still planned"
    assert report.display_title == "Blur my shell", "named without asking the desktop"


def test_naming_an_add_on_never_raises_when_the_desktop_is_gone():
    """`brief_for` runs inside the library's own callback too, via describe_batch."""
    proxy = DesktopGoesAway()
    entry = library_entry(BLUR, "Blur", "au")
    installer = _installer_on(proxy, routes={"/extension-info/": entry})
    proxy.alive = False

    assert installer.brief_for(BLUR).display_title == "Blur my shell"

    seen: list = []
    installer.describe_batch([(BLUR, "local-only", ())], seen.extend)
    assert [brief.display_title for brief in seen] == ["Blur my shell"]


def test_the_desktop_is_not_asked_to_name_what_it_is_about_to_be_given():
    """The naming lookup is a blocking bus call on the thread that draws.

    An add-on reaching the package path is one the desktop does not have, so
    the round trip buys an empty answer at the price of a UI-thread stall of up
    to the D-Bus default timeout, per add-on, inside a download callback.

    One lookup is still made and has to be: after the unpack, what the desktop
    knows is what decides between "it's on now" and "after you log out". It is
    the *second* one — asking for a title before the download — that is gone.
    """
    proxy = FakeShellProxy({})
    installer = _installer_on(proxy, routes={"/download-extension/": ZIP})
    asked: list = []
    proxy.get_extension_info = lambda uuid: (asked.append(uuid), {})[1]

    box: list = []
    installer.install_package(BLUR, 69740, box.append)

    assert len(box) == 1
    assert asked == [BLUR], "one lookup, the one that decides what to promise"
    assert box[0].display_title == "Blur my shell"
