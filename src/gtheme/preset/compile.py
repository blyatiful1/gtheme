"""Turn a Look into a transaction.

This is the whole bridge between the declarative half of gtheme and the half
that touches the machine. It produces :class:`~gtheme.core.transaction.Op`
objects and nothing else — no writes, no side effects, no execution. That is
what makes the promise on the install surface literally true: there is no code
path from a ``theme.toml`` to a subprocess, because the only thing a Look can
compile into is a file copy, a setting, or an add-on being switched on.

Two things get decided here rather than in the transaction layer, because both
need the Look's own metadata:

* **Which add-ons to offer to install.** A Look names the add-ons it wants; the
  ones already on the machine are simply enabled. A missing ``ego`` add-on
  becomes an install offer. A missing ``local-only`` add-on (DESIGN.md F12 —
  someone's private extension, which a Look may never bundle) becomes a named
  skip warning in the user's words, not an error and not a silent nothing.
* **Which alternate satisfies a requirement.** ding and gtk4-ding do the same
  job; if the Look asks for one and the machine has the other, the other wins.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path

from ..core.transaction import (
    ExtensionEnable,
    ExtensionInstall,
    FileWrite,
    Op,
    SettingWrite,
    Transaction,
)
from .model import Component, ExtensionSetting, Preset

__all__ = ["CompileResult", "compile_preset", "extension_setting_key"]


def extension_setting_key(setting: ExtensionSetting) -> str:
    """Render one add-on setting into the frozen key grammar.

    A relocatable schema — burn-my-windows' per-profile settings are the reason
    the form exists — needs its instance path carried alongside the schema id.
    """
    if setting.path:
        return f"gsettings-path:{setting.schema_id}:{setting.path} {setting.key}"
    return f"gsettings:{setting.schema_id} {setting.key}"


@dataclass
class CompileResult:
    """A Look, ready to apply.

    Attributes:
        transaction: what to do, in the order the engine will do it.
        warnings: things this Look asked for that will not happen, each phrased
            as a sentence a first-time user can act on.
    """

    transaction: Transaction
    warnings: list[str] = field(default_factory=list)

    @property
    def ops(self) -> tuple[Op, ...]:
        return tuple(self.transaction.ops)


def _resolve_uuid(uuid: str, alternates: list[str], installed: Collection[str]) -> str | None:
    """The first of ``uuid`` and its alternates that is actually installed."""
    for candidate in (uuid, *alternates):
        if candidate in installed:
            return candidate
    return None


def compile_preset(
    preset: Preset,
    directory: str | Path,
    *,
    dest_root: str | None = None,
    installed_extensions: Collection[str] | None = None,
) -> CompileResult:
    """Compile a Look into a :class:`~gtheme.core.transaction.Transaction`.

    Args:
        preset: the validated Look.
        directory: its folder — file sources are resolved against this, so the
            transaction carries absolute paths and cannot be confused about
            which Look a relative ``src`` belonged to.
        dest_root: passed through to the transaction; the confinement preflight
            refuses any write that escapes it.
        installed_extensions: the uuids present on this machine. ``None`` means
            "not known" — no install offers are made and no absence is warned
            about, which is the right behaviour for a preview computed before
            the add-on list has been read.

    Returns:
        The transaction and the list of things that will not apply.
    """
    base = Path(directory)
    warnings: list[str] = []
    files: list[Op] = []
    settings: list[Op] = []
    extensions: list[Op] = []

    for entry in preset.files:
        source = base / entry.src
        # A Look that names a file it does not ship still applies, minus that
        # file. The loader has always promised exactly this ("… is missing, so
        # <dest> will not be written"), but compiling the write anyway made the
        # transaction unplannable — one absent source and the Look could
        # neither be previewed nor applied at all, not even the parts that were
        # there. It is a real end state: the downloader keeps a Look whose file
        # failed to fetch. So the entry is dropped here and named as a warning,
        # which is the same sentence the Looks page already shows.
        if not source.is_file():
            reason = (
                "is a folder — a Look copies one file at a time"
                if source.is_dir()
                else "is missing"
            )
            warnings.append(f"{entry.src!r} {reason}, so {entry.dest} will not be written")
            continue
        files.append(
            FileWrite(
                src=str(source),
                dest=entry.dest,
                mode=entry.mode,
                template=entry.template,
                merge=entry.merge,
            )
        )

    for setting in preset.settings:
        settings.append(
            SettingWrite(
                key=setting.key,
                value=setting.value,
                merge=setting.merge,
                component=str(setting.component),
            )
        )

    known_installed = installed_extensions if installed_extensions is not None else None
    enabled_uuids: set[str] = set()

    for uuid in preset.extensions.enable:
        install = preset.extensions.install_for(uuid)
        alternates = tuple(install.alternates)
        if known_installed is None:
            extensions.append(ExtensionEnable(uuid=uuid, alternates=alternates))
            enabled_uuids.add(uuid)
            continue

        present = _resolve_uuid(uuid, install.alternates, known_installed)
        if present is not None:
            extensions.append(ExtensionEnable(uuid=present, alternates=alternates))
            enabled_uuids.add(present)
            if present != uuid:
                enabled_uuids.add(uuid)
            continue

        if install.source == "local-only":
            warnings.append(
                f"this Look uses a private add-on that isn't installed "
                f"({uuid}) — that part of the look won't apply"
            )
            continue

        extensions.append(
            ExtensionInstall(uuid=uuid, ego_pk=install.ego_pk, source=install.source)
        )
        extensions.append(ExtensionEnable(uuid=uuid, alternates=alternates))
        enabled_uuids.add(uuid)

    for setting in preset.extensions.settings:
        if known_installed is not None and setting.uuid not in enabled_uuids:
            continue
        settings.append(
            SettingWrite(
                key=extension_setting_key(setting),
                value=setting.value,
                merge="none",
                component=str(Component.ADDONS),
            )
        )

    transaction = Transaction(
        [*files, *settings, *extensions],
        dest_root=dest_root,
        label=preset.meta.title or preset.meta.name,
        # The label is the title, which is what a person was shown. The name is
        # the folder, which is what a lookup matches on. Both are recorded.
        look=preset.meta.name,
    )
    return CompileResult(transaction=transaction, warnings=warnings)
