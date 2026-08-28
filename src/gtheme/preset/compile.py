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

Two boundaries are also checked here, because this is the first place that sees
a Look's own folder and its declared destinations together: where each file may
come from (``core.confine.confine_src``) and what a Look is allowed to write at
all (``core.policy``). Neither is enforced *only* here — the transaction refuses
the same things on its own, and has to, because a hand-built transaction never
passes through this module. What this module adds is the sentence: a person
sees "this Look asked to write ~/.config/autostart/x.desktop" before anything
happens, rather than a refusal with no story attached.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path

from ..core.confine import ConfinementError, confine_src
from ..core.gvariant import unquote
from ..core.policy import file_verdict, setting_verdict
from ..core.transaction import (
    ExtensionEnable,
    ExtensionInstall,
    FileWrite,
    Op,
    SettingWrite,
    Transaction,
)

# The only thing this module borrows from ``system``: the parser that splits a
# font description into a family and a size. A Look asks for "Adwaita Sans 11";
# whether that font is here is a question about "Adwaita Sans", and re-writing
# that split here would be the second copy of a parser that already has tests.
from ..system.fontscan import parse_font_description
from .model import Component, ExtensionSetting, Meta, Preset

__all__ = [
    "PACKAGE_HINTS",
    "Available",
    "CompileResult",
    "compile_preset",
    "extension_setting_key",
    "shell_warning",
    "value_warnings",
]


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
        refusals: things this Look asked for that gtheme will not let any Look
            do (``core.policy``'s refused tier). Every one of these is also in
            :attr:`warnings`, named, because they are the most important
            sentences the dialog can show — but they are carried separately as
            well, because their consequence is different from a missing file's:
            a Look with one of these does not apply at all, and the transaction
            refuses it whether or not anything read this list.
    """

    transaction: Transaction
    warnings: list[str] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)

    @property
    def ops(self) -> tuple[Op, ...]:
        return tuple(self.transaction.ops)

    @property
    def refused(self) -> bool:
        """Will this Look be refused rather than applied?"""
        return bool(self.refusals)


def shell_warning(meta: Meta, shell_version: str | None) -> str | None:
    """The ``min_shell`` sentence, or None when there is nothing to say.

    ``docs/preset-format.md`` has always said this field produces a warning and
    never blocks. Nothing read it (review-report L8): a Look declaring
    ``min_shell = "50"`` applied in complete silence on GNOME 49, and
    ``index.json`` publishes the field, so it looks live from outside.

    It never blocks, and it never guesses. If the desktop's version cannot be
    read — which happens exactly when the desktop is not answering — this says
    nothing rather than accusing a Look of being too new for a version nobody
    measured.
    """
    if not meta.min_shell or not shell_version:
        return None
    wanted = re.match(r"\d+", str(meta.min_shell).strip())
    have = re.match(r"\d+", str(shell_version).strip())
    if not wanted or not have or int(have.group()) >= int(wanted.group()):
        return None
    return (
        f"this Look was made for a newer version of GNOME ({wanted.group()}; this "
        f"computer has {have.group()}) — parts of it may not apply"
    )


#: What each setting a Look can get *wrong* is called in the user's words, and
#: what stays as it is when the value names something this computer does not
#: have. Keyed by the schema-and-key half of a setting key, so both the plain
#: and the relocatable spellings of the same setting land on one entry.
_CHECKED_VALUES: dict[str, tuple[str, str]] = {
    "org.gnome.desktop.interface icon-theme": ("an icon set", "your icons will stay as they are"),
    "org.gnome.desktop.interface cursor-theme": (
        "a mouse pointer style",
        "your mouse pointer will stay as it is",
    ),
    "org.gnome.desktop.interface gtk-theme": (
        "an app style",
        "your apps will look the way they do now",
    ),
    "org.gnome.desktop.interface font-name": ("a text style", "your text will stay as it is"),
    "org.gnome.desktop.interface document-font-name": (
        "a text style for documents",
        "the text in your documents will stay as it is",
    ),
    "org.gnome.desktop.interface monospace-font-name": (
        "a text style for the terminal",
        "the text in your terminal will stay as it is",
    ),
}

#: Which list on :class:`Available` answers for each checked setting.
_CHECKED_AGAINST: dict[str, str] = {
    "org.gnome.desktop.interface icon-theme": "icon_themes",
    "org.gnome.desktop.interface cursor-theme": "cursor_themes",
    "org.gnome.desktop.interface gtk-theme": "app_styles",
    "org.gnome.desktop.interface font-name": "fonts",
    "org.gnome.desktop.interface document-font-name": "fonts",
    "org.gnome.desktop.interface monospace-font-name": "fonts",
}

#: What to install to get the things the Looks in this repository ask for.
#:
#: Deliberately short and deliberately named after the thing rather than after
#: a distribution: every entry here is something one of gtheme's own Looks
#: wants, so "this Look needs Papirus" is answered with the name a person can
#: type into their software manager instead of with a shrug. A name that is not
#: in this table is still *reported* — it is only the last clause of the
#: sentence that goes missing, and inventing a package name for a font nobody
#: here has heard of would be worse than leaving it out.
PACKAGE_HINTS: dict[str, str] = {
    "papirus": "papirus-icon-theme",
    "papirus-dark": "papirus-icon-theme",
    "papirus-light": "papirus-icon-theme",
    "adw-gtk3": "adw-gtk-theme",
    "adw-gtk3-dark": "adw-gtk-theme",
    "meslolgs nerd font": "ttf-meslo-nerd",
    "meslolgs nerd font mono": "ttf-meslo-nerd",
    "iosevka nerd font": "ttf-iosevka-nerd",
    "iosevka nerd font mono": "ttf-iosevka-nerd",
    "monaspace neon": "ttf-monaspace",
    "rajdhani": "ttf-rajdhani",
}


@dataclass(frozen=True)
class Available:
    """What this computer actually has, for a Look's values to be checked against.

    Every one of the four Looks gtheme shipped first asks for ``Papirus-Dark``
    icons and none of them ships an icon set; three ask for ``adw-gtk3-dark``.
    The write always succeeds — the setting exists, the *value* is simply a
    name of something that is not installed — so the desktop falls back, the
    Home page reads the name back cheerfully, and nobody is ever told that the
    icons they were promised are not there (persona-report §2.6).

    This is deliberately **data, not a scan**. The compiler judges; the caller
    measures. That keeps this module free of the filesystem and of Pango, and
    it is the same rule ``installed_extensions`` follows: an empty
    :class:`Available` means "nothing was measured", and nothing is claimed.

    Args:
        icon_themes: the folder names of the icon sets on this computer.
        cursor_themes: the same, for the ones that hold a mouse pointer.
        app_styles: the names of the installed app styles.
        fonts: the installed font family names.
    """

    icon_themes: frozenset[str] = frozenset()
    cursor_themes: frozenset[str] = frozenset()
    app_styles: frozenset[str] = frozenset()
    fonts: frozenset[str] = frozenset()

    @property
    def measured(self) -> bool:
        """True when anything at all was read off this computer."""
        return bool(self.icon_themes or self.cursor_themes or self.app_styles or self.fonts)


def _package_clause(wanted: str) -> str:
    """" — the X package adds it", when there is a package worth naming."""
    package = PACKAGE_HINTS.get(wanted.strip().casefold())
    return f" — the {package} package adds it" if package else ""


def _font_is_here(wanted: str, families: Collection[str]) -> bool:
    """Is a font description's family one of the families installed here?

    A description carries style words the family name does not — "Rajdhani
    Medium" is the family "Rajdhani" — and Pango needs a weight/style/stretch
    table to split those correctly. So the test is the other way round: a
    family that is installed and that the description *starts with* is a match.
    Erring towards silence is the point. Telling somebody a font is missing
    when it is there is worse than saying nothing, because the sentence is
    supposed to be the reason their text will look wrong.
    """
    spec = parse_font_description(wanted).family_and_style.casefold()
    if not spec:
        return True
    return any(
        spec == family.casefold() or spec.startswith(family.casefold() + " ")
        for family in families
    )


def value_warnings(preset: Preset, available: Available | None) -> list[str]:
    """The sentences for everything this Look asks for that is not installed.

    A Look names an icon set, a mouse pointer, an app style and a text style
    by name, and every one of those names is a thing that has to *be* on the
    computer for the setting to mean anything. Nothing checked them: the
    transaction's skip fires on a missing settings group, and
    ``org.gnome.desktop.interface`` is always there, so the write succeeded and
    the desktop quietly fell back to what it had (persona-report §2.6).

    Args:
        preset: the Look.
        available: what this computer has. ``None``, or an empty one, means
            nothing was measured and nothing is said — a preview that accuses
            a Look of asking for a missing font on a machine where no font was
            ever counted would be a guess.

    Returns:
        One sentence per value that names something absent, in the order the
        Look wrote them, naming the package to install where one is known.
    """
    if available is None or not available.measured:
        return []
    said: set[tuple[str, str]] = set()
    warnings: list[str] = []
    for setting in preset.settings:
        body = setting.key.split(":", 1)[-1]
        checked = _CHECKED_VALUES.get(body)
        if checked is None:
            continue
        against = getattr(available, _CHECKED_AGAINST[body])
        if not against:
            continue  # that kind of thing was not counted on this computer
        wanted = unquote(setting.value).strip()
        if not wanted:
            continue
        if _CHECKED_AGAINST[body] == "fonts":
            # The size is part of the value and no part of the question: what
            # has to be installed is the family, so that is what is checked and
            # what the sentence names.
            named = parse_font_description(wanted).family_and_style or wanted
            here = _font_is_here(wanted, against)
        else:
            named = wanted
            here = wanted in against
        if here or (body, named) in said:
            continue
        said.add((body, named))
        kind, stays = checked
        warnings.append(
            f"this Look asks for {kind} that is not on this computer ({named}), so "
            f"{stays}{_package_clause(named)}"
        )
    return warnings


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
    shell_version: str | None = None,
    available: Available | None = None,
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
        shell_version: the GNOME version this desktop is running, when the
            caller knows it. Used for the ``min_shell`` warning and nothing
            else; ``None`` means "not measured", and nothing is claimed.
        available: the icon sets, mouse pointers, app styles and fonts this
            computer has, for :func:`value_warnings`. ``None`` means "not
            measured", and no value is accused of being missing.

    Returns:
        The transaction, the list of things that will not apply, and the list
        of things gtheme refuses to let a Look do at all.
    """
    base = Path(directory)
    warnings: list[str] = []
    refusals: list[str] = []
    files: list[Op] = []
    settings: list[Op] = []
    extensions: list[Op] = []

    too_new = shell_warning(preset.meta, shell_version)
    if too_new:
        warnings.append(too_new)
    # Said before the file and add-on notes because it is the one class of
    # warning about something the Look will *appear* to have done: the write
    # lands, the desktop falls back, and the only sign is that the icons never
    # changed (persona-report §2.6).
    warnings.extend(value_warnings(preset, available))

    for entry in preset.files:
        # Where the file may come from. ``confine_src`` has implemented this
        # rule since the beginning and had exactly one caller — the download
        # staging path — so the apply path never asked (review-report H5): a
        # Look could ship ``files/wallpaper.png`` as a shortcut to a private
        # key and have its contents copied out at a readable permission. A
        # refusal reads like the missing-source case because it has the same
        # consequence for the person: that part of the Look does not happen.
        # The *resolved* location is what the op carries, so the transaction
        # reads a real file inside the Look's folder and never a shortcut to
        # somewhere else.
        try:
            source = confine_src(entry.src, base)
        except ConfinementError:
            warnings.append(
                f"{entry.src!r} comes from outside this Look's own folder, so "
                f"{entry.dest} will not be written"
            )
            continue
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
        # Where the file may go, beyond staying inside the home folder. A
        # refused destination is *not* dropped: the op stays, so the engine's
        # own preflight refuses the whole Look with the same verdict, and this
        # sentence is what says why in words (review-report C1).
        verdict = file_verdict(entry.dest, root=dest_root)
        if verdict.refused:
            refusals.append(
                f"this Look asked to write {entry.dest} — {verdict.reason}, so gtheme "
                "will not apply it"
            )
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
        # The same two-tier question for settings: a Look may change how the
        # desktop looks, and may not change what it *runs* (review-report H4).
        verdict = setting_verdict(setting.key)
        if verdict.refused:
            refusals.append(
                f"this Look asked to change a setting gtheme will not let a Look change "
                f"— {verdict.reason}"
            )
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
        key = extension_setting_key(setting)
        verdict = setting_verdict(key)
        if verdict.refused:
            refusals.append(
                f"this Look asked to change a setting gtheme will not let a Look change "
                f"— {verdict.reason}"
            )
        settings.append(
            SettingWrite(
                key=key,
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
    return CompileResult(
        transaction=transaction,
        # The refusals are said out loud in the ordinary warning list too: they
        # are the sentences that matter most, and a caller that only renders
        # warnings must not be the reason a person never sees them.
        warnings=[*warnings, *refusals],
        refusals=refusals,
    )
