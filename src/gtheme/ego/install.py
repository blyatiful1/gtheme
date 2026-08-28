"""Installing an add-on, and telling the truth about what just happened.

There is exactly one way to install an add-on and have it start working
immediately: ask the desktop to do it, with ``InstallRemoteExtension``. This is
not a preference. The desktop scans its add-on folders once, at start-up, and
has no way to be told to look again — no folder watcher, no rescan call, and a
``ReloadExtension`` method that answers "deprecated and does not work". An
add-on folder that appears afterwards is invisible: switching it on in the
settings is a silent no-op, with no error, no signal and nothing for gtheme to
detect a failure from. That was tested rather than assumed, in a throwaway
desktop inside a private session bus; the write-up is
``research/runtime-load-experiment.md`` and the test that pins it lives in the
sandbox tier, so a future desktop release that changes this fails loudly.

So the module has two paths and two sets of words:

**The live path** — ``InstallRemoteExtension``. The desktop downloads the
add-on itself and starts it, and gtheme can honestly say "it's on now". The
call opens a confirmation box *in the desktop*, in front of gtheme's own
window, and does not answer until somebody clicks it. Two consequences are
handled here and nowhere else:

* the call is made with an effectively infinite timeout, because the default
  25 seconds is a timer on a human being;
* when it times out anyway, gtheme **never calls it again**. The install is
  very likely still running; a second call re-imports an add-on that is already
  loaded and produces an "already initialized" state that only logging out
  clears. Instead the state signal — armed *before* the call — is what says
  whether it worked.

**The package path** — download the zip, hand it to ``gnome-extensions
install``, and merge the add-on into the enabled list through the transaction
layer. This is what a Look with three add-ons uses, and what runs when the
desktop is not reachable. It cannot make anything start running, so it says
"after you log out and back in" and means it.

Which sentence a person sees is decided by asking the desktop whether it knows
the add-on at all, never by assuming. An add-on that was already on disk at the
last log-in *can* be switched on live, and saying "log out" to that person
would be a lie in the other direction.

**Before either path runs**, the batch can be named: :class:`AddonBrief` and
:meth:`ExtensionInstaller.describe_batch` say what each add-on is called, who
wrote it and where it would come from, without downloading anything. A person
being asked to accept third-party code is being asked about particular
add-ons, and "3 add-ons" is not something anyone can accept or refuse. Naming
them costs one lookup each and never fails: an add-on the library will not
describe still comes back with a readable form of its own file name.
"""

from __future__ import annotations

import enum
import subprocess
import tempfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..core.transaction import ExtensionEnable, Transaction
from .client import EgoClient, EgoError
from .models import ExtensionRecord
from .shelldbus import (
    EnableResult,
    ExtensionState,
    ShellError,
    ShellErrorKind,
    ShellExtensions,
    StateWatcher,
)

__all__ = [
    "COPY",
    "COMMAND_NOT_FOUND",
    "AddonBrief",
    "CommandResult",
    "CommandRunner",
    "ExtensionInstaller",
    "InstallOutcome",
    "InstallReport",
    "SubprocessRunner",
    "describe_addons",
    "enable_transaction",
    "readable_name",
    "safe_uuid",
]

#: The characters a GNOME add-on uuid is made of. Same idea as
#: :func:`gtheme.core.confine.safe_name`, widened by exactly one character:
#: every real uuid looks like ``blur-my-shell@aunetx``, so ``@`` has to be
#: allowed where a Look name would not allow it.
_UUID_CHARS = "-_.@"


def safe_uuid(uuid: str) -> str:
    """Validate an add-on uuid that is about to become a path component.

    A uuid arrives from the desktop, from the online library, or from a Look's
    own description file, and then gets used as a folder name and as part of a
    file name. ``..`` as a uuid turns ``<updates>/<uuid>`` into the folder
    *above* the updates folder, which is then deleted and replaced. So it goes
    through the same kind of gate every other name-turned-path in gtheme goes
    through, rather than being trusted because today's callers happen to be
    trustworthy.

    Raises:
        ValueError: the uuid is empty, is ``.`` or ``..``, or holds anything
            outside ``[A-Za-z0-9._@-]``.
    """
    if not uuid or uuid in (".", ".."):
        raise ValueError(f"{uuid!r} is not a usable add-on name")
    for char in uuid:
        if not char.isascii() or not (char.isalnum() or char in _UUID_CHARS):
            raise ValueError(
                f"{uuid!r} is not a usable add-on name: "
                "letters, digits, '-', '_', '.' and '@' only"
            )
    return uuid


class InstallOutcome(enum.Enum):
    """How an install ended. Each one has exactly one sentence in :data:`COPY`."""

    #: Installed and running. "It's on now" is true.
    ACTIVE = "active"
    #: Installed, but the running desktop cannot pick it up until the next
    #: log-in. The only honest thing to say is so.
    NEEDS_RELOGIN = "needs-relogin"
    #: The confirmation box on screen has not been answered yet. Not a failure,
    #: and above all not a reason to try again.
    WAITING_FOR_CONFIRMATION = "waiting-for-confirmation"
    #: The person said no.
    CANCELLED = "cancelled"
    #: Adding add-ons is switched off on this machine.
    NOT_ALLOWED = "not-allowed"
    #: There is no build of this add-on for this version of GNOME.
    NOT_COMPATIBLE = "not-compatible"
    #: A private add-on a Look wants that is not on this machine. Named skip,
    #: never an error — the rest of the Look still applies.
    LOCAL_ONLY_MISSING = "local-only-missing"
    #: Anything else.
    FAILED = "failed"


#: Everything this module says to a person, in one place, so the wording can be
#: reviewed as a whole. Two sentences differ by one clause and that clause is
#: the entire difference between honest and not, so they live side by side.
COPY: dict[InstallOutcome | str, str] = {
    InstallOutcome.ACTIVE: "Added. It's on now.",
    InstallOutcome.NEEDS_RELOGIN: (
        "Added. It starts working after you log out and back in."
    ),
    InstallOutcome.WAITING_FOR_CONFIRMATION: (
        "Waiting for you to confirm the box that appeared on your screen."
    ),
    InstallOutcome.CANCELLED: "Cancelled. Nothing was added.",
    InstallOutcome.NOT_ALLOWED: "This computer does not allow adding new add-ons.",
    InstallOutcome.NOT_COMPATIBLE: (
        "This add-on does not have a version for your version of GNOME yet."
    ),
    InstallOutcome.LOCAL_ONLY_MISSING: (
        "This look uses a private add-on that is not on this computer. "
        "Everything else in the look still applies."
    ),
    InstallOutcome.FAILED: "The add-on could not be added.",
    # -- situational lines, keyed by name
    # What a Look's missing add-on is called before anything has been
    # downloaded. It must NOT be the NEEDS_RELOGIN sentence above: that one
    # begins "Added.", and this add-on has not been added — it is the *plan* to
    # try. If the download then works, the install path builds a fresh report
    # with the real sentence; if it does not, this is what the person is shown,
    # and it says the true thing.
    "not-added-yet": (
        "This add-on is not on this computer, and gtheme could not add it."
    ),
    "confirm-on-screen": (
        "Confirm the download in the box that appeared on your screen. "
        "It is in front of this window."
    ),
    "download-failed": (
        "The add-on could not be downloaded. Check your internet connection."
    ),
    "would-not-start": "The add-on was added but would not start.",
    "already-on": "That add-on is already on.",
    "turned-on": "Turned on.",
    "turn-on-after-login": "Turned on. It takes effect after you log out and back in.",
    # -- where an add-on would come from, said before anything is downloaded.
    # Every download gtheme makes goes to the one address named here, so the
    # sentence can name it rather than hedging.
    "source-ego": "from the GNOME add-on website, extensions.gnome.org",
    "source-local-only": (
        "a private add-on — gtheme never downloads this one"
    ),
}


def readable_name(uuid: str) -> str:
    """A name a person can read, worked out from an add-on's own file name.

    The library knows every add-on's real title, but asking for it takes a
    round trip that can fail, and a list of add-ons about to be added must be
    showable either way. ``blur-my-shell@aunetx`` becomes ``Blur my shell``:
    the author part goes, the dashes and underscores become spaces. Never a
    substitute for the real title when there is one — only for the case where
    the alternative is showing a person something they cannot read.
    """
    head = uuid.split("@", 1)[0]
    words = head.replace("_", " ").replace("-", " ").replace(".", " ").split()
    if not words:
        return uuid
    text = " ".join(words)
    return text[0].upper() + text[1:]


@dataclass(frozen=True)
class AddonBrief:
    """One add-on, named, *before* anything about it is downloaded.

    A Look's add-ons used to reach the person as a count — "this Look uses 3
    add-ons you don't have" — and the download started from a button next to
    that count. A count is not something anybody can agree to: the add-ons are
    third-party code, and which three they are is the whole question. So the
    install pipeline hands out one of these per add-on it is about to fetch,
    carrying what a person needs in order to say yes or no: what it is called,
    who wrote it, and where it would come from.

    ``uuid`` is in here because the code that acts on the answer needs it. It
    is deliberately *not* part of any sentence this module builds: gtheme does
    not show internal names to people.

    Args:
        uuid: the add-on's identifier. For the code, never for the screen.
        source: ``"ego"`` (may be downloaded from extensions.gnome.org) or
            ``"local-only"`` (a private add-on that is never downloaded).
        title: the real title, once something has been asked. Empty until then.
        creator: who wrote it, when known.
    """

    uuid: str
    source: str = "ego"
    title: str = ""
    creator: str = ""

    @property
    def display_title(self) -> str:
        """What to call it on screen — the real title, or a readable fallback."""
        return self.title or readable_name(self.uuid)

    @property
    def source_line(self) -> str:
        """Where it would come from, in one plain clause."""
        if self.source == "local-only":
            return COPY["source-local-only"]
        return COPY["source-ego"]

    @property
    def line(self) -> str:
        """The whole add-on as one line for a list: name, author, source."""
        who = f", by {self.creator}" if self.creator else ""
        return f"{self.display_title}{who} — {self.source_line}"


def describe_addons(briefs: Iterable[AddonBrief]) -> list[str]:
    """One plain line per add-on, in the order given.

    The phrasing helper the preview dialog uses, so that naming the add-ons is
    a matter of showing this list rather than of every caller inventing its own
    sentence.
    """
    return [brief.line for brief in briefs]


@dataclass(frozen=True)
class CommandResult:
    """What running a command produced."""

    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class CommandRunner(Protocol):
    """Running one command. Injectable, so the tests unpack no real packages."""

    def run(self, argv: Sequence[str]) -> CommandResult: ...


#: What a command that could not be started at all comes back as. The shell's
#: own number for "there is no such command", used here for the same meaning so
#: nothing has to invent a second one.
COMMAND_NOT_FOUND = 127


class SubprocessRunner:
    """The real runner. Pins ``LC_ALL=C`` so nothing ever reads translated text."""

    def run(self, argv: Sequence[str]) -> CommandResult:
        import os

        env = dict(os.environ, LC_ALL="C")
        try:
            completed = subprocess.run(
                list(argv), capture_output=True, text=True, check=False, env=env
            )
        except OSError as exc:
            # A missing `gnome-extensions` raises FileNotFoundError from deep
            # inside a download callback, where the loop that called it prints
            # the traceback and carries on — so the batch's "this one landed"
            # callback never fires and the progress dialog sits there for the
            # full three-minute timeout before saying something that names
            # nothing. A command that cannot be started is a failed command,
            # and the caller already knows how to report one of those.
            return CommandResult(COMMAND_NOT_FOUND, stderr=str(exc))
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


@dataclass(frozen=True)
class InstallReport:
    """What happened, in both machine and human form.

    Args:
        uuid: which add-on. Never shown to a person.
        outcome: the machine-readable result.
        message: the sentence to show. Always set.
        via: ``"desktop"`` for the live path, ``"package"`` for the download
            path, ``"none"`` when nothing was attempted.
        transaction: for the package path, the enable step that still has to be
            applied. Built here, applied by the caller, so that a Look that adds
            three add-ons applies them as one all-or-nothing change rather than
            as three separate ones.
        error: the underlying failure, for the log.
        brief: what this add-on is called and where it comes from, so a caller
            listing several reports can name them instead of counting them.
    """

    uuid: str
    outcome: InstallOutcome
    message: str
    via: str = "none"
    transaction: Transaction | None = None
    error: Exception | None = None
    brief: AddonBrief | None = None

    @property
    def ok(self) -> bool:
        return self.outcome in (InstallOutcome.ACTIVE, InstallOutcome.NEEDS_RELOGIN)

    @property
    def display_title(self) -> str:
        """What to call this add-on on screen. Never its identifier."""
        return (self.brief or AddonBrief(self.uuid)).display_title


ReportCallback = Callable[[InstallReport], None]


def enable_transaction(
    uuids: Iterable[str],
    *,
    alternates: dict[str, tuple[str, ...]] | None = None,
    label: str | None = None,
) -> Transaction:
    """Plan switching several add-ons on as one change.

    Goes through the transaction layer rather than writing the enabled list
    directly, for the reason that list is special: it holds add-ons the person
    switched on themselves, so a Look *unions* into it and a restore puts back
    the exact value that was there before — not a value computed by removing
    what the Look added.

    The returned transaction deliberately carries **neither** a Look name nor a
    label. Switching add-ons on is not a Look being applied, and the transaction
    layer treats a named transaction as one: it tidies away everything the
    previous Look owns that the new one does not list, and this transaction
    lists nothing but the enabled-add-ons setting. A label here would therefore
    strip the current Look's wallpaper, icons and fonts off the desktop as the
    side effect of switching one add-on on. Callers that *are* applying a Look
    build the whole thing as one transaction and name that one.

    Args:
        uuids: the add-ons to switch on.
        alternates: per uuid, other uuids that count as the same add-on.
        label: accepted so callers can pass the name of the larger change they
            are part of; it is deliberately not attached to this transaction.
    """
    alternates = alternates or {}
    ops = [ExtensionEnable(uuid=uuid, alternates=alternates.get(uuid, ())) for uuid in uuids]
    return Transaction(ops, look=None)


class ExtensionInstaller:
    """Adds add-ons, by whichever path can honestly be described.

    Args:
        shell: the running desktop's add-on service.
        client: the online library, for the package path. Optional — the live
            path needs no client at all, since the desktop does its own
            downloading.
        runner: how ``gnome-extensions install`` is run.
    """

    def __init__(
        self,
        shell: ShellExtensions,
        client: EgoClient | None = None,
        runner: CommandRunner | None = None,
    ) -> None:
        self.shell = shell
        self.client = client
        self.runner = runner or SubprocessRunner()

    # -- the live path -------------------------------------------------

    def install_live(
        self,
        uuid: str,
        callback: ReportCallback,
        *,
        record: ExtensionRecord | None = None,
        on_dialog: Callable[[str], None] | None = None,
    ) -> StateWatcher | None:
        """Ask the desktop to fetch and start an add-on.

        Args:
            uuid: the add-on to add.
            callback: called once with the report.
            record: its library entry, when the caller already has one. Used to
                refuse an incompatible add-on before a confirmation box appears
                for something that cannot work.
            on_dialog: called with the "confirm on screen" line as soon as the
                request is out, so the UI can say what the person is waiting
                for instead of showing a spinner that looks stuck.

        Returns:
            The armed state watcher, so a caller that gets
            ``WAITING_FOR_CONFIRMATION`` can keep listening. None when nothing
            was attempted.
        """
        if record is not None and not record.supports(self.shell.proxy.shell_version()):
            callback(
                InstallReport(
                    uuid,
                    InstallOutcome.NOT_COMPATIBLE,
                    COPY[InstallOutcome.NOT_COMPATIBLE],
                )
            )
            return None

        existing = self.shell.get(uuid)
        if existing is not None and existing.state is ExtensionState.ACTIVE:
            callback(
                InstallReport(uuid, InstallOutcome.ACTIVE, COPY["already-on"], via="desktop")
            )
            return None

        # Armed BEFORE the call. The desktop can finish and emit the signal
        # while the call itself is still unanswered; a watcher armed after the
        # call would miss exactly the case it exists for.
        watcher = StateWatcher(uuid=uuid, shell=self.shell)
        watcher.arm()

        def _replied(result: str | None, error: ShellError | None) -> None:
            callback(self._interpret_live(uuid, result, error, watcher))

        self.shell.proxy.install_remote(uuid, _replied)
        if on_dialog is not None:
            on_dialog(COPY["confirm-on-screen"])
        return watcher

    def _interpret_live(
        self,
        uuid: str,
        result: str | None,
        error: ShellError | None,
        watcher: StateWatcher,
    ) -> InstallReport:
        """Turn one D-Bus answer into one sentence. The retry rule lives here."""
        if error is not None:
            if error.kind is ShellErrorKind.NO_REPLY:
                # The call outlived its timeout. The install is very likely
                # still going, so this is a report about waiting, not a
                # failure — and under no circumstances a second call.
                if watcher.became_active or self._is_active(uuid):
                    watcher.disarm()
                    return InstallReport(
                        uuid, InstallOutcome.ACTIVE, COPY[InstallOutcome.ACTIVE], via="desktop"
                    )
                return InstallReport(
                    uuid,
                    InstallOutcome.WAITING_FOR_CONFIRMATION,
                    COPY[InstallOutcome.WAITING_FOR_CONFIRMATION],
                    via="desktop",
                    error=error,
                )
            watcher.disarm()
            if error.kind is ShellErrorKind.NOT_ALLOWED:
                outcome = InstallOutcome.NOT_ALLOWED
                message = COPY[InstallOutcome.NOT_ALLOWED]
            elif error.kind is ShellErrorKind.DOWNLOAD_FAILED:
                outcome = InstallOutcome.FAILED
                message = COPY["download-failed"]
            elif error.kind is ShellErrorKind.ENABLE_FAILED:
                outcome = InstallOutcome.FAILED
                message = COPY["would-not-start"]
            else:
                outcome = InstallOutcome.FAILED
                message = COPY[InstallOutcome.FAILED]
            return InstallReport(uuid, outcome, message, via="desktop", error=error)

        watcher.disarm()
        if result == "cancelled":
            return InstallReport(
                uuid, InstallOutcome.CANCELLED, COPY[InstallOutcome.CANCELLED], via="desktop"
            )
        if result == "successful":
            return self._gate_on_desktop(uuid, via="desktop")
        return InstallReport(
            uuid, InstallOutcome.FAILED, COPY[InstallOutcome.FAILED], via="desktop"
        )

    def _is_active(self, uuid: str) -> bool:
        found = self.shell.get(uuid)
        return found is not None and found.state is ExtensionState.ACTIVE

    def _gate_on_desktop(self, uuid: str, *, via: str) -> InstallReport:
        """Decide what to promise by asking the desktop what it knows.

        Three answers, three different sentences:

        * running already — "it's on now";
        * known but not running — switching it on works, so do that and say so;
        * unknown — the desktop never scanned it, and nothing in this session
          will change that. The next log-in will.
        """
        found = self.shell.get(uuid)
        if found is None:
            return InstallReport(
                uuid, InstallOutcome.NEEDS_RELOGIN, COPY[InstallOutcome.NEEDS_RELOGIN], via=via
            )
        if found.state is ExtensionState.ACTIVE:
            return InstallReport(uuid, InstallOutcome.ACTIVE, COPY[InstallOutcome.ACTIVE], via=via)
        enabled = self.shell.enable(uuid)
        if enabled is EnableResult.ENABLED_NOW:
            return InstallReport(uuid, InstallOutcome.ACTIVE, COPY[InstallOutcome.ACTIVE], via=via)
        if enabled is EnableResult.NEEDS_RELOGIN:
            return InstallReport(
                uuid, InstallOutcome.NEEDS_RELOGIN, COPY[InstallOutcome.NEEDS_RELOGIN], via=via
            )
        return InstallReport(uuid, InstallOutcome.FAILED, COPY["would-not-start"], via=via)

    def resolve_pending(self, uuid: str, watcher: StateWatcher) -> InstallReport:
        """Ask again, later, what became of a call that never answered.

        Called by the UI on a timer, or when the state signal fires. Still no
        second install call — this only looks.
        """
        if watcher.became_active or self._is_active(uuid):
            watcher.disarm()
            return InstallReport(
                uuid, InstallOutcome.ACTIVE, COPY[InstallOutcome.ACTIVE], via="desktop"
            )
        return InstallReport(
            uuid,
            InstallOutcome.WAITING_FOR_CONFIRMATION,
            COPY[InstallOutcome.WAITING_FOR_CONFIRMATION],
            via="desktop",
        )

    # -- the package path ----------------------------------------------

    def install_package(
        self,
        uuid: str,
        version_tag: int,
        callback: ReportCallback,
        *,
        alternates: tuple[str, ...] = (),
        label: str | None = None,
        brief: AddonBrief | None = None,
    ) -> None:
        """Download the add-on and unpack it, for when the live path is out.

        Used when the desktop is not answering, and for a Look that adds
        several add-ons at once — one confirmation box per add-on would be an
        interrogation.

        The zip carries the settings descriptions but not their compiled form,
        so unpacking it by hand leaves an add-on whose own settings window
        cannot find them. ``gnome-extensions install`` compiles them; that is
        the whole reason gtheme shells out here instead of unzipping.

        Nothing this path does can make an add-on start running, so it never
        says otherwise. The returned report carries the enable step as a
        planned transaction for the caller to apply.

        Args:
            brief: what this add-on is called, worked out before the download
                started. Carried through onto every report so a caller can name
                what failed rather than counting failures.
        """
        described = brief or self.brief_for(uuid)
        if self.client is None:
            callback(
                InstallReport(
                    uuid,
                    InstallOutcome.FAILED,
                    COPY[InstallOutcome.FAILED],
                    brief=described,
                )
            )
            return

        def _downloaded(body: bytes | None, error: EgoError | None) -> None:
            if error is not None or not body:
                callback(
                    InstallReport(
                        uuid,
                        InstallOutcome.FAILED,
                        COPY["download-failed"],
                        via="package",
                        error=error,
                        brief=described,
                    )
                )
                return
            callback(
                self._unpack_and_plan(
                    uuid, body, alternates=alternates, label=label, brief=described
                )
            )

        self.client.download(uuid, version_tag, _downloaded)

    def _unpack_and_plan(
        self,
        uuid: str,
        zip_bytes: bytes,
        *,
        alternates: tuple[str, ...] = (),
        label: str | None = None,
        brief: AddonBrief | None = None,
    ) -> InstallReport:
        try:
            component = safe_uuid(uuid)
        except ValueError as exc:
            # A callback is no place for an exception nobody catches; the
            # honest answer to "this name cannot be a file" is a failed report.
            return InstallReport(
                uuid,
                InstallOutcome.FAILED,
                COPY[InstallOutcome.FAILED],
                via="package",
                error=exc,
                brief=brief,
            )
        with tempfile.TemporaryDirectory(prefix="gtheme-addon-") as tmp:
            package = Path(tmp) / f"{component}.shell-extension.zip"
            package.write_bytes(zip_bytes)
            try:
                result = self.runner.run(
                    ["gnome-extensions", "install", "--force", str(package)]
                )
            except OSError as exc:
                # Belt and braces with SubprocessRunner's own guard: this
                # method runs inside a download callback, and an exception
                # escaping here is swallowed by the loop that dispatched it —
                # the batch then waits out its whole timeout for a callback
                # that will never come. Every other failure in this module is
                # an InstallReport, so this one is too.
                result = CommandResult(COMMAND_NOT_FOUND, stderr=str(exc))
        if not result.ok:
            return InstallReport(
                uuid,
                InstallOutcome.FAILED,
                COPY[InstallOutcome.FAILED],
                via="package",
                error=RuntimeError(result.stderr.strip() or "unpacking failed"),
                brief=brief,
            )

        transaction = enable_transaction(
            [uuid], alternates={uuid: alternates}, label=label
        )
        report = self._gate_on_desktop(uuid, via="package")
        return InstallReport(
            uuid,
            report.outcome,
            report.message,
            via="package",
            transaction=transaction,
            brief=brief,
        )

    # -- naming a batch before it is fetched ---------------------------

    def brief_for(self, uuid: str, source: str = "ego") -> AddonBrief:
        """Name one add-on without asking anything over the network.

        Uses the desktop's own title when the add-on is already here, and a
        readable form of its file name when it is not. Always returns
        something showable, because a list of add-ons a person is being asked
        to approve may not depend on a request that can fail.
        """
        known = self.shell.get(uuid) if self.shell is not None else None
        title = known.name if known is not None else ""
        return AddonBrief(uuid=uuid, source=source, title=title)

    def describe_batch(
        self,
        wanted: Sequence[tuple[str, str, tuple[str, ...]]],
        callback: Callable[[list[AddonBrief]], None],
    ) -> None:
        """Name every add-on in a batch *before* a single byte is downloaded.

        This is what turns "this Look uses 3 add-ons you don't have" into three
        add-ons with names, authors and one address they come from. It asks the
        library for the real titles, one after another, and never lets a failed
        lookup cost a name: an add-on the library will not describe still comes
        back with the readable form of its own file name and the same source
        clause. Downloading is a separate step and happens only if somebody
        says yes to this list.

        Args:
            wanted: ``(uuid, source, alternates)`` per add-on, the same shape
                :meth:`plan_for_look` takes.
            callback: called once, with one brief per entry, in the order
                given.
        """
        briefs: list[AddonBrief] = []
        queue = [(entry[0], entry[1]) for entry in wanted]

        def step() -> None:
            while queue:
                uuid, source = queue.pop(0)
                if source != "ego" or self.client is None:
                    briefs.append(self.brief_for(uuid, source))
                    continue

                def described(
                    record: ExtensionRecord | None,
                    error: EgoError | None,
                    uuid: str = uuid,
                    source: str = source,
                ) -> None:
                    if record is None or error is not None:
                        briefs.append(self.brief_for(uuid, source))
                    else:
                        briefs.append(
                            AddonBrief(
                                uuid=uuid,
                                source=source,
                                title=record.name,
                                creator=record.creator,
                            )
                        )
                    step()

                self.client.info(uuid, described)
                return
            callback(briefs)

        step()

    # -- a Look's whole add-on list ------------------------------------

    def plan_for_look(
        self,
        wanted: Sequence[tuple[str, str, tuple[str, ...]]],
        *,
        label: str | None = None,
    ) -> tuple[Transaction, list[InstallReport]]:
        """Work out what a Look's add-on list means for this machine.

        Args:
            wanted: ``(uuid, source, alternates)`` per add-on, where source is
                ``"ego"`` (may be offered for download) or ``"local-only"`` (a
                private add-on that must already be here).
            label: what to call the resulting change.

        Returns:
            The transaction that switches on everything already present, and a
            report per add-on that is missing — a private one that is absent is
            a named skip and never an error, because the rest of the Look is
            still perfectly applicable.
        """
        present: list[str] = []
        alternates_by_uuid: dict[str, tuple[str, ...]] = {}
        missing: list[InstallReport] = []

        for uuid, source, alternates in wanted:
            here = uuid if self.shell.knows(uuid) else _first_known(self.shell, alternates)
            if here is not None:
                present.append(here)
                alternates_by_uuid[here] = alternates
                continue
            if source == "local-only":
                missing.append(
                    InstallReport(
                        uuid,
                        InstallOutcome.LOCAL_ONLY_MISSING,
                        COPY[InstallOutcome.LOCAL_ONLY_MISSING],
                        brief=AddonBrief(uuid=uuid, source=source),
                    )
                )
            else:
                # NEEDS_RELOGIN is what the caller queues a download on, so the
                # outcome stays. The *sentence* may not: nothing has been
                # downloaded yet, and this report is shown verbatim when the
                # download never happens.
                missing.append(
                    InstallReport(
                        uuid,
                        InstallOutcome.NEEDS_RELOGIN,
                        COPY["not-added-yet"],
                        brief=AddonBrief(uuid=uuid, source=source),
                    )
                )
        return (
            enable_transaction(present, alternates=alternates_by_uuid, label=label),
            missing,
        )

    # -- switching on and off ------------------------------------------

    def turn_on(self, uuid: str) -> InstallReport:
        """Switch an already-installed add-on on, honestly."""
        outcome = self.shell.enable(uuid)
        if outcome is EnableResult.ENABLED_NOW:
            return InstallReport(uuid, InstallOutcome.ACTIVE, COPY["turned-on"], via="desktop")
        if outcome is EnableResult.NEEDS_RELOGIN:
            return InstallReport(
                uuid,
                InstallOutcome.NEEDS_RELOGIN,
                COPY["turn-on-after-login"],
                via="desktop",
            )
        return InstallReport(
            uuid, InstallOutcome.FAILED, COPY["would-not-start"], via="desktop"
        )


def _first_known(shell: ShellExtensions, uuids: Iterable[str]) -> str | None:
    """The first of several equivalent add-ons that is actually here."""
    for uuid in uuids:
        if shell.knows(uuid):
            return uuid
    return None
