"""Checking for add-on updates, and staging them where the desktop expects.

gtheme does its own update check rather than asking the desktop to do it. Not
out of preference: the desktop's ``CheckForUpdates`` is gated on a hard-coded
list of two application names, neither of which a third-party app can join, and
it is a silent no-op for everybody else. It also reports no progress and no
per-add-on result. So the check here is the same one the desktop would make —
one request that asks about every installed add-on at once — and the answer is
gtheme's to explain.

The other half of this module is where an update goes. **Not** over the running
add-on's folder. The desktop has already imported that code; replacing the
files underneath it leaves a session running the old code with the new files on
disk, and the next attempt to load it produces an error that only logging out
clears. The desktop's own updater stages into a separate folder and moves it
into place at the next start-up, and gtheme does exactly the same thing, for
exactly the same reason. Which is also why the only honest sentence after a
successful staging mentions logging out.
"""

from __future__ import annotations

import enum
import io
import json
import os
import shutil
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .client import EgoClient, EgoError
from .install import CommandRunner, SubprocessRunner
from .shelldbus import ShellExtensions

__all__ = [
    "COPY",
    "UpdateCandidate",
    "UpdateChecker",
    "UpdateVerdict",
    "extension_updates_dir",
    "stage_update",
]

#: The sentences this module contributes.
COPY = {
    "staged": "Update ready. It is applied the next time you log in.",
    "withdrawn": "This add-on is no longer offered for your version of GNOME.",
    "up-to-date": "Everything is up to date.",
    "check-failed": "Could not check for updates. Check your internet connection.",
}


class UpdateVerdict(enum.Enum):
    """What the library says about one installed add-on."""

    #: A different build is available. The library uses two words for this and
    #: means the same thing by both: apply it.
    UPGRADE = "upgrade"
    DOWNGRADE = "downgrade"
    #: Withdrawn for this version of GNOME. Not an update — say so, and offer
    #: removal rather than a download.
    WITHDRAWN = "blacklist"

    @property
    def is_update(self) -> bool:
        return self in (UpdateVerdict.UPGRADE, UpdateVerdict.DOWNGRADE)


@dataclass(frozen=True)
class UpdateCandidate:
    """One add-on the library had something to say about."""

    uuid: str
    installed_version: int
    verdict: UpdateVerdict
    #: Filled in by :meth:`UpdateChecker.resolve`, which is a second request
    #: per add-on — so it happens for the ones a person actually updates, not
    #: for the whole list.
    available_version: int | None = None
    version_tag: int | None = None

    @property
    def ready_to_download(self) -> bool:
        return self.verdict.is_update and self.version_tag is not None


def extension_updates_dir() -> Path:
    """Where a staged update waits. ``GTHEME_EXTENSION_UPDATES_DIR`` overrides.

    The default is the folder the desktop moves into place at the next
    start-up. The override exists so the test suite can watch this code write a
    real folder tree without going anywhere near the real one.
    """
    override = os.environ.get("GTHEME_EXTENSION_UPDATES_DIR")
    if override:
        return Path(override)
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / "gnome-shell" / "extension-updates"


def _safe_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """Entries that stay inside the folder they are unpacked into.

    A package is a file downloaded off the internet. An entry named
    ``../../.bashrc`` unpacks exactly where it says unless somebody checks, and
    this is where somebody checks.
    """
    safe: list[zipfile.ZipInfo] = []
    for member in archive.infolist():
        name = member.filename.replace("\\", "/")
        if name.startswith("/") or ".." in Path(name).parts:
            raise ValueError(f"the add-on package contains an unsafe entry: {member.filename!r}")
        safe.append(member)
    return safe


def stage_update(
    uuid: str,
    zip_bytes: bytes,
    *,
    directory: str | Path | None = None,
    runner: CommandRunner | None = None,
) -> Path:
    """Unpack an update where the desktop picks it up at the next start-up.

    The package is unpacked into a temporary folder beside the destination and
    moved into place in one step, so an interrupted download can never leave
    half an add-on where a whole one is expected.

    Args:
        uuid: which add-on this is. Checked against the package's own
            description — a package that says it is something else is refused,
            because unpacking it would put one add-on's code in another's folder
            and the desktop would then load it under the wrong name.
        zip_bytes: the package.
        directory: where updates are staged. Defaults to
            :func:`extension_updates_dir`.
        runner: how the settings descriptions are compiled.

    Returns:
        The folder the update now sits in.

    Raises:
        ValueError: the package is not a package, is not this add-on, or
            contains an entry that would unpack outside its folder.
    """
    root = Path(directory) if directory is not None else extension_updates_dir()
    destination = root / uuid
    root.mkdir(parents=True, exist_ok=True)

    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise ValueError(f"the download for {uuid} is not an add-on package") from exc

    with archive:
        members = _safe_members(archive)
        names = {member.filename for member in members}
        if "metadata.json" not in names:
            raise ValueError(f"the download for {uuid} has no add-on description in it")
        described = json.loads(archive.read("metadata.json").decode("utf-8"))
        if described.get("uuid") and described["uuid"] != uuid:
            raise ValueError(
                f"the download says it is {described['uuid']!r}, not {uuid!r}"
            )
        staging = Path(tempfile.mkdtemp(prefix=f".{uuid}.", dir=root))
        try:
            archive.extractall(staging, members=members)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    schemas = staging / "schemas"
    if schemas.is_dir():
        # The package ships the settings descriptions but not their compiled
        # form. Without this step the add-on's own settings window opens onto
        # nothing.
        (runner or SubprocessRunner()).run(
            ["glib-compile-schemas", "--strict", str(schemas)]
        )

    if destination.exists():
        shutil.rmtree(destination)
    os.replace(staging, destination)
    return destination


class UpdateChecker:
    """Asks the library about every installed add-on in one request.

    Args:
        client: the online library.
        shell: the running desktop, for what is installed and at which version.
    """

    def __init__(self, client: EgoClient, shell: ShellExtensions) -> None:
        self.client = client
        self.shell = shell
        self.runner: CommandRunner = SubprocessRunner()

    def check(
        self,
        callback: Callable[[list[UpdateCandidate] | None, EgoError | None], None],
    ) -> None:
        """Find out which add-ons have a different build waiting.

        Only add-ons the library itself packaged are asked about. One installed
        from source carries a version number that means something else entirely,
        and comparing the two produces confident nonsense.

        Up-to-date add-ons are simply absent from the answer, so an empty list
        genuinely means "nothing to do".
        """
        installed = self.shell.from_library()
        if not installed:
            callback([], None)
            return

        def _answered(verdicts: dict[str, str] | None, error: EgoError | None) -> None:
            if error is not None or verdicts is None:
                callback(None, error)
                return
            candidates: list[UpdateCandidate] = []
            for uuid, word in verdicts.items():
                try:
                    verdict = UpdateVerdict(word)
                except ValueError:
                    continue
                if uuid not in installed:
                    continue
                candidates.append(
                    UpdateCandidate(
                        uuid=uuid,
                        installed_version=installed[uuid],
                        verdict=verdict,
                    )
                )
            candidates.sort(key=lambda c: c.uuid)
            callback(candidates, None)

        self.client.update_info(installed, _answered)

    def resolve(
        self,
        candidate: UpdateCandidate,
        callback: Callable[[UpdateCandidate | None, EgoError | None], None],
    ) -> None:
        """Look up the exact release to download for one candidate.

        Compatibility is decided from the library's own version map, never from
        the fact that the request succeeded — the detail request answers 200 and
        offers a download for versions of GNOME an add-on has no build for.
        """

        def _got(record, error: EgoError | None) -> None:  # type: ignore[no-untyped-def]
            if error is not None or record is None:
                callback(None, error)
                return
            shell_version = self.shell.proxy.shell_version()
            if not record.supports(shell_version):
                callback(
                    UpdateCandidate(
                        uuid=candidate.uuid,
                        installed_version=candidate.installed_version,
                        verdict=UpdateVerdict.WITHDRAWN,
                    ),
                    None,
                )
                return
            callback(
                UpdateCandidate(
                    uuid=candidate.uuid,
                    installed_version=candidate.installed_version,
                    verdict=candidate.verdict,
                    available_version=record.version_for(shell_version),
                    version_tag=record.version_tag_for(shell_version),
                ),
                None,
            )

        self.client.info(candidate.uuid, _got)

    def download_and_stage(
        self,
        candidate: UpdateCandidate,
        callback: Callable[[Path | None, Exception | None], None],
        *,
        directory: str | Path | None = None,
    ) -> None:
        """Fetch a resolved candidate and put it where the desktop will find it."""
        if candidate.version_tag is None:
            callback(None, ValueError("this update has not been looked up yet"))
            return

        def _downloaded(body: bytes | None, error: EgoError | None) -> None:
            if error is not None or not body:
                callback(None, error)
                return
            try:
                staged = stage_update(
                    candidate.uuid, body, directory=directory, runner=self.runner
                )
            except (OSError, ValueError) as exc:
                callback(None, exc)
                return
            callback(staged, None)

        self.client.download(candidate.uuid, candidate.version_tag, _downloaded)
