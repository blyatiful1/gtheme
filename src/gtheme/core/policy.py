"""What a Look is allowed to change, beyond staying inside your home folder.

``core.confine`` answers *where* a write may land. This module answers a
different question the confinement check cannot: **what does landing there
mean?** ``~/.config/autostart/x.desktop`` is inside the home folder and is a
program that runs at every login; ``~/.config/starship.toml`` is inside the
home folder and holds ``command = "…"`` lines a terminal prompt runs on every
keystroke. Both passed every check gtheme had, while the preview collapsed
them to "23 files" under the sentence "Looks only change settings. They can't
run programs on your computer." (review-report C1/H4.)

So destinations and setting keys are sorted into three tiers.

**REFUSED** — a Look may never write it, and a Look that asks for one does not
apply at all. These are the places where writing a file *is* arranging for a
program to run: the autostart and user-service folders, the folders on your
command path, the shell's own start-up files, the add-on code folder, and
anything named ``.desktop`` or ``.service`` wherever it sits. On the settings
side: the custom-shortcut command and its key combination, the "which program
opens this" keys, the desktop session's own definition, the terminal profile's
own command, and any raw settings location outside the add-on trees a
decorative Look legitimately reaches into. A refusal is deliberately not a
"skip this part": a Look that needs one of these is not a decorative Look, and
applying the rest of it would be applying something the author did not design.

Both halves are judged on the address as the Look *wrote* it as well as on the
address the machine ends up at: a destination whose folder is a symlink into a
dotfiles repository, and a terminal key reachable by two different spellings,
were each a way past a list that only looked at one of the two (C1, H4).

**CONSEQUENTIAL** — allowed, never anonymous. Real Looks legitimately theme a
terminal by writing that terminal's own settings file, and those file formats
can also name a program to run. Three of the four Looks in this repository
write ``~/.config/starship.toml``. Refusing them would refuse the shipped
product; hiding them inside "23 files" is what made C1 possible. So they are
allowed *and* every one of them is named individually in the plan the user is
shown — :meth:`gtheme.core.transaction.Diff.to_novice_lines` never counts
them.

**ALLOWED** — everything else, which is nearly everything: wallpapers, GTK
stylesheets, icon and colour settings, add-on tuning.

Two design notes worth keeping:

* The tiers are *lists*, not cleverness. A guess about what a file format can
  do would be wrong in both directions; a named list with a sentence per entry
  can be read, argued with, and extended by a person.
* The policy is about **Looks** — data somebody downloaded. It is not applied
  to a saved moment being put back, because a restore point describes the
  user's own machine as it was, and refusing to put back a file that was
  already there would break the one promise the app is built around. The
  transaction layer draws that line by asking only when ``look`` is set.
"""

from __future__ import annotations

import enum
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .confine import ConfinementError, expand_dest
from .paths import dest_root
from .settings_backend import BackendError, KeyKind, parse_key

__all__ = [
    "ALLOWED_DCONF_PREFIXES",
    "CONSEQUENTIAL_FILES",
    "PTYXIS_PROFILE_SCHEMA",
    "REFUSED_FILE_NAMES",
    "REFUSED_FOLDERS",
    "REFUSED_PTYXIS_PROFILE_KEYS",
    "REFUSED_SUFFIXES",
    "Tier",
    "Verdict",
    "file_verdict",
    "setting_verdict",
]


class Tier(enum.Enum):
    """How much a Look writing this thing matters."""

    #: Ordinary decoration. Counted in the preview like everything else.
    ALLOWED = "allowed"
    #: Allowed, but named in the preview one by one — never inside a count.
    CONSEQUENTIAL = "consequential"
    #: A Look may not write this, and a Look that asks for it does not apply.
    REFUSED = "refused"


@dataclass(frozen=True)
class Verdict:
    """A tier, and the words to say about it.

    Attributes:
        tier: which of the three.
        what: the short name of the thing, for a line the user reads — a file
            name, or the part of the desktop a setting belongs to. Empty for
            :attr:`Tier.ALLOWED`.
        reason: one clause saying why this is not ordinary decoration, in the
            words of somebody who has never heard of a shell. Empty for
            :attr:`Tier.ALLOWED`.
    """

    tier: Tier
    what: str = ""
    reason: str = ""

    @property
    def refused(self) -> bool:
        return self.tier is Tier.REFUSED

    @property
    def named(self) -> bool:
        """Must this appear in the preview by name rather than in a count?"""
        return self.tier is Tier.CONSEQUENTIAL

    def sentence(self) -> str:
        """The whole refusal, as one sentence a first-time user can act on."""
        return f"{self.what}: {self.reason}" if self.what else self.reason


_ALLOWED = Verdict(Tier.ALLOWED)


# ---------------------------------------------------------------------------
# files
# ---------------------------------------------------------------------------

#: Folders (relative to the home folder) a Look may never write into, with the
#: sentence explaining why. Everything here is a place where putting a file is
#: the same act as arranging for a program to run — at login, at start-up, or
#: whenever the user types a name into a command window.
REFUSED_FOLDERS: dict[str, str] = {
    ".config/autostart": "files here are started automatically every time you log in",
    ".config/systemd": "files here are started automatically in the background",
    ".config/environment.d": "files here change how every program on this computer starts",
    ".local/bin": "files here can be run as commands",
    "bin": "files here can be run as commands",
    ".local/share/gnome-shell/extensions": (
        "this is where add-on program code lives, and a Look may not bring its own"
    ),
    ".config/fish/conf.d": "files here are run every time a command window opens",
}

#: Exact files (relative to the home folder) a Look may never write. These are
#: the start-up files of the common command windows: whatever is in them runs
#: on every new window, before the person has typed anything.
REFUSED_FILE_NAMES: dict[str, str] = dict.fromkeys(
    (
        ".bashrc",
        ".bash_profile",
        ".bash_login",
        ".bash_logout",
        ".profile",
        ".zshrc",
        ".zshenv",
        ".zprofile",
        ".zlogin",
        ".config/fish/config.fish",
        ".config/zsh/.zshrc",
        ".config/zsh/.zshenv",
    ),
    "this file is run every time a command window opens",
)

#: Endings a Look may never write, wherever the file sits. A ``.desktop`` file
#: is a program someone can start by clicking it (and, in the autostart folder,
#: without clicking anything); a ``.service`` file is one the machine starts on
#: its own.
REFUSED_SUFFIXES: dict[str, str] = {
    ".desktop": "a file like this is a program entry, not decoration",
    ".service": "a file like this asks the computer to run something in the background",
}

#: Files a Look *may* write and that must never be hidden inside a count. Each
#: is a real program's own settings file, in a format that can also name a
#: command for that program to run. Keys are matched against the destination
#: relative to the home folder: an exact match, or a folder prefix plus a set
#: of endings.
#:
#: Derived from what the four Looks in this repository actually write —
#: ``starship.toml``, ``alacritty/*.toml``, ``ghostty/config`` and
#: ``fastfetch/*.jsonc`` are all in the shipped set — plus the same file for
#: the two other terminals people commonly use. Adding one is a deliberate,
#: reviewable edit, which is the point.
CONSEQUENTIAL_FILES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (
        ".config/starship.toml",
        (),
        "the prompt in your command window can be told to run programs from this file",
    ),
    (
        ".config/alacritty",
        (".toml", ".yml", ".yaml"),
        "a command window can be told which program to start from this file",
    ),
    (
        ".config/ghostty/config",
        (),
        "a command window can be told which program to start from this file",
    ),
    (
        ".config/kitty/kitty.conf",
        (),
        "a command window can be told which program to start from this file",
    ),
    (
        ".config/wezterm/wezterm.lua",
        (),
        "a command window can be told which program to start from this file",
    ),
    (
        ".config/fastfetch",
        (".json", ".jsonc"),
        "this file can list commands for the system-information program to run",
    ),
    (
        ".config/tmux/tmux.conf",
        (),
        "this file can list commands to run",
    ),
    (
        ".tmux.conf",
        (),
        "this file can list commands to run",
    ),
)


def _relative(dest: str, root: str | Path | None, *, resolve: bool) -> PurePosixPath | None:
    """``dest`` as a path below the home folder, or None if it is not below it.

    Uses the same expansion the confinement preflight uses, so ``~/x``,
    ``$HOME/x`` and the fully written-out path are one case rather than three.
    A destination outside the home folder is not this module's business — the
    confinement check refuses it first — but its *ending* still is, which is
    why the caller falls back to the name.

    Args:
        resolve: follow symlinks (``True``) or normalise ``.``/``..``
            lexically and follow nothing (``False``). Both answers are needed
            and neither is sufficient on its own — see :func:`file_verdict`.
    """
    try:
        expanded = expand_dest(dest, root)
        base = Path(root).expanduser() if root is not None else dest_root()
        if resolve:
            return PurePosixPath(expanded.resolve().relative_to(base.resolve()))
        # ``expand_dest`` builds ``~/...`` on the *resolved* root, so the
        # lexical form has to be measured against the resolved root too or a
        # home folder reached through a link would never match.
        lexical = Path(os.path.normpath(expanded))
        return PurePosixPath(lexical.relative_to(base.resolve()))
    except (ConfinementError, OSError, ValueError):
        return None


def _tier_of(relative: PurePosixPath) -> Verdict:
    """The verdict for one already-relative-to-home form of a destination."""
    text = relative.as_posix()

    if text in REFUSED_FILE_NAMES:
        return Verdict(Tier.REFUSED, text, REFUSED_FILE_NAMES[text])
    for folder, reason in REFUSED_FOLDERS.items():
        if text == folder or text.startswith(folder + "/"):
            return Verdict(Tier.REFUSED, text, reason)

    for pattern, suffixes, reason in CONSEQUENTIAL_FILES:
        if not suffixes:
            if text == pattern:
                return Verdict(Tier.CONSEQUENTIAL, relative.name, reason)
            continue
        if text.startswith(pattern + "/") and relative.suffix in suffixes:
            return Verdict(Tier.CONSEQUENTIAL, relative.name, reason)

    return _ALLOWED


def file_verdict(dest: str, *, root: str | Path | None = None) -> Verdict:
    """Which tier this file destination falls in.

    Both the destination *as written* and the destination *with every link
    followed* are judged, and the worst of the two answers wins. Judging only
    the followed one was C1's bypass: ``confine_dest`` returns — and the apply
    writes through — the unresolved path, so on the stow/chezmoi/dotfiles
    machines this app is aimed at, where ``~/.bashrc`` or the whole of
    ``~/.config`` is a link into a repository, every entry in
    :data:`REFUSED_FOLDERS` and :data:`REFUSED_FILE_NAMES` classified the link's
    *target* and let the write through. Judging only the written one would be
    the mirror bug: ``~/decor/../.bashrc`` is not a link and ``~/link-to-bin/x``
    is, and each escapes the other check.

    Args:
        dest: the destination exactly as the Look wrote it.
        root: the destination root, when the caller carries its own (a
            transaction does). Defaults to the process-wide home folder.
    """
    name = PurePosixPath(dest).name
    for suffix, reason in REFUSED_SUFFIXES.items():
        if name.endswith(suffix):
            return Verdict(Tier.REFUSED, name, reason)

    # As-written first, so the name in a CONSEQUENTIAL line is the one the user
    # asked about rather than wherever their dotfiles repository keeps it.
    verdict = _ALLOWED
    for resolve in (False, True):
        relative = _relative(dest, root, resolve=resolve)
        if relative is None:
            # Outside the home folder, or an unusable root. The confinement
            # preflight refuses both; nothing more to say here.
            continue
        candidate = _tier_of(relative)
        if candidate.refused:
            return candidate
        if candidate.named and not verdict.named:
            verdict = candidate

    return verdict


# ---------------------------------------------------------------------------
# settings
# ---------------------------------------------------------------------------

#: Raw settings locations a Look may address. A ``dconf:`` key names a place in
#: the settings store with no description attached, which means nothing can
#: check what is being written there — so the answer is a list of the trees a
#: decorative Look has any business in, and a refusal for everything else.
#:
#: Derived empirically: every ``dconf:`` key in the four Looks in this
#: repository falls under one of these three, and the curated add-on corpus in
#: ``data/panels`` addresses its settings through described schemas rather than
#: raw locations. An add-on that keeps its settings in its own tree (Hanabi is
#: the shipped example) needs its tree added here, deliberately.
ALLOWED_DCONF_PREFIXES: tuple[tuple[str, str], ...] = (
    ("/org/gnome/shell/extensions/", "add-on settings"),
    ("/org/gnome/Ptyxis/", "the terminal's own colours"),
    ("/io/github/jeffshee/hanabi-extension/", "the animated-background add-on's settings"),
)

#: The schema of a Ptyxis terminal profile. It is *relocatable*: one copy of it
#: lives at ``/org/gnome/Ptyxis/Profiles/<uuid>/`` for each profile, which is
#: why the shipped Looks address it as a raw location with the profile's id
#: filled in (``docs/preset-format.md``) rather than by schema name.
PTYXIS_PROFILE_SCHEMA = "org.gnome.Ptyxis.Profile"

_PTYXIS_COMMAND_REASON = (
    "this would make your command window start a program of the Look's choosing "
    "every time you open one"
)

#: The keys under a Ptyxis profile a Look may never write, and why. The tree
#: above is allow-listed for "the terminal's own colours" — but the same tree
#: also holds the profile's *command*, and a Look that sets it has arranged for
#: a program of its choosing to run in every terminal window the user opens
#: afterwards, while the preview says only "Terminal" (review-report H4).
#:
#: A named list rather than an allow-list of colour keys, on purpose: Ptyxis
#: gains keys between releases, and a Look that wants a new colour key should
#: keep working. The three here are the ones that decide what *runs*;
#: everything else in the profile decides how it looks.
REFUSED_PTYXIS_PROFILE_KEYS: dict[str, str] = dict.fromkeys(
    ("custom-command", "use-custom-command", "login-shell"),
    _PTYXIS_COMMAND_REASON,
)

#: The whole tree they live under, as a raw settings location. Deliberately the
#: broad ``/org/gnome/Ptyxis/`` rather than ``.../Profiles/``: the key names are
#: what make a location dangerous, not the shape of the path leading to it.
_PTYXIS_PREFIX = "/org/gnome/Ptyxis/"

#: Settings a Look may never write, as ``(schema, keys)``. An empty key set
#: means the whole schema. Each of these decides what the desktop *runs*: the
#: command behind a keyboard shortcut, the program that opens when you ask for
#: a command window or a web page, and the definition of the session itself.
REFUSED_SETTINGS: tuple[tuple[str, frozenset[str], str], ...] = (
    (
        "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding",
        frozenset({"command", "binding"}),
        "this would make a key combination run a program of the Look's choosing",
    ),
    (
        # Not the whole schema, deliberately. ``idle-delay`` lives here too —
        # it is "blank the screen after N minutes", which gtheme's own Power
        # page offers and a saved-as-a-Look desktop legitimately carries, so
        # refusing the schema wholesale would refuse the app's own output.
        # ``session-name`` is the one key that decides which desktop is
        # started, and no decorative Look has any business in it.
        "org.gnome.desktop.session",
        frozenset({"session-name"}),
        "this decides which desktop starts when you log in",
    ),
    (
        # The schema-named half of the Ptyxis profile refusal below. The raw
        # ``dconf:`` form is the one the shipped Looks use, but
        # ``gsettings-path:org.gnome.Ptyxis.Profile:/…/ custom-command``
        # addresses the identical key and has to get the identical answer.
        PTYXIS_PROFILE_SCHEMA,
        frozenset(REFUSED_PTYXIS_PROFILE_KEYS),
        _PTYXIS_COMMAND_REASON,
    ),
)

#: Schema prefix plus keys, for the family of "which program opens this" keys.
_REFUSED_DEFAULT_APPLICATIONS = (
    "org.gnome.desktop.default-applications.",
    frozenset({"exec", "exec-arg"}),
    "this decides which program opens when you ask for one, and a Look may not choose it",
)


def setting_verdict(key: str) -> Verdict:
    """Which tier this settings key falls in.

    Args:
        key: the key string in the grammar frozen in ``core.settings_backend``,
            exactly as the Look wrote it. Unresolved ``{{ }}`` tokens are fine:
            the transaction asks again once they are filled in.
    """
    try:
        parsed = parse_key(key)
    except BackendError:
        if "{{" in key:
            # A token that has not been filled in yet. The apply path checks
            # again with the real value, and refuses to write a half-resolved
            # location at all (``core.placeholders.key_ok``).
            return _ALLOWED
        return Verdict(
            Tier.REFUSED,
            key,
            "gtheme cannot make sense of where this setting lives, so it will not write it",
        )

    if parsed.kind is KeyKind.DCONF:
        path = parsed.path or ""
        if path.startswith(_PTYXIS_PREFIX):
            # The allow-list below opens this tree for "the terminal's own
            # colours". The profile's command lives in the same tree, and the
            # preview for it says "Terminal" (review-report H4).
            last = path.rsplit("/", 1)[-1]
            if last in REFUSED_PTYXIS_PROFILE_KEYS:
                return Verdict(Tier.REFUSED, path, REFUSED_PTYXIS_PROFILE_KEYS[last])
        if any(path.startswith(prefix) for prefix, _what in ALLOWED_DCONF_PREFIXES):
            return _ALLOWED
        return Verdict(
            Tier.REFUSED,
            path,
            "a Look may only change add-on settings this way, and this is somewhere else",
        )

    if parsed.kind is KeyKind.KEYFILE:
        # The keyfile form names the file the values live in, which would let a
        # Look write into any file it liked without going near the destination
        # rules above. gtheme's own pages use it; a Look has no need of it.
        return Verdict(
            Tier.REFUSED,
            parsed.file or key,
            "a Look may not write settings straight into a file of its own choosing",
        )

    schema = parsed.schema or ""
    name = parsed.key or ""
    for refused_schema, keys, reason in REFUSED_SETTINGS:
        if schema == refused_schema and (not keys or name in keys):
            return Verdict(Tier.REFUSED, f"{schema} {name}".strip(), reason)
    prefix, keys, reason = _REFUSED_DEFAULT_APPLICATIONS
    if schema.startswith(prefix) and name in keys:
        return Verdict(Tier.REFUSED, f"{schema} {name}", reason)
    return _ALLOWED
