"""Ghostty — a plain text config that does not reload itself.

Two things make ghostty the awkward one, and both are handled here rather than
in the UI.

**It does not watch its own file.** Ghostty's own help says so outright: editing
the config does not reload it. Whatever gtheme writes is invisible until the
user triggers a reload from the menu or a keybind, and a couple of settings need
a full restart even then. So the adapter reports
:attr:`~gtheme.terminal.model.ReloadSemantics.MANUAL_RELOAD` and the page says
it out loud. An app that claims a change happened when the window in front of
you has not changed teaches people not to believe it.

**Its config directory may not be its config directory.** On the machine this
was written on, ``~/.config/ghostty`` is a symlink to ``~/nightbloom/ghostty`` —
a rice repository the user maintains by hand, in git. Writing "into
``~/.config``" would in fact have edited that working tree. So the adapter
resolves the *directory* (DESIGN.md F7), and when it lands somewhere else it
refuses and says why. Taking it over is a deliberate, reversible act: the
dir-level symlink is recorded first, then replaced by a real directory seeded
with a copy of what the symlink pointed at, so nothing is lost and the link can
be put back.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from .fsio import atomic_write_text, config_root, confine, state_root
from .kv import KeyValueFile
from .model import (
    FileChange,
    Palette,
    ReloadSemantics,
    TerminalState,
    TerminalWrites,
    one_line,
    read_palette,
)

__all__ = ["GhosttyAdapter", "slugify"]

#: What the user is asked when the config directory belongs to something else.
FOREIGN_NOTICE = (
    "Your terminal's settings are managed by another tool ({owner}). "
    "gtheme has not changed anything. Take them over?"
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """A safe file name for a look. ASCII, lowercase, no separators.

    Palette names come from presets, and a preset is a file someone else wrote:
    a name containing ``../`` must not become part of a path.
    """
    slug = _SLUG_RE.sub("-", name.strip().lower()).strip("-")
    return slug or "gtheme"


class GhosttyAdapter:
    """Restyle Ghostty by writing a theme file and pointing the config at it.

    Args:
        config_dir: override the settings directory. Normally omitted, in which
            case it is ``<config root>/ghostty`` — and the config root already
            honours the test destination root.
    """

    id = "ghostty"
    name = "Ghostty"
    reload_semantics = ReloadSemantics.MANUAL_RELOAD

    def __init__(self, config_dir: Path | None = None) -> None:
        self._config_dir = Path(config_dir) if config_dir is not None else None

    # -- where things are --------------------------------------------------

    @property
    def config_dir(self) -> Path:
        return self._config_dir if self._config_dir is not None else config_root() / "ghostty"

    @property
    def config_path(self) -> Path:
        return self.config_dir / "config"

    @property
    def themes_dir(self) -> Path:
        return self.config_dir / "themes"

    @property
    def takeover_record(self) -> Path:
        return state_root() / "terminal" / "ghostty-takeover.json"

    # -- the F7 check ------------------------------------------------------

    def foreign_root(self) -> Path | None:
        """Where the config directory really is, when that is somewhere else.

        Returns None when the directory is absent (nothing to be foreign) or
        genuinely lives under the user's own settings folder.
        """
        directory = self.config_dir
        if not directory.exists():
            return None
        resolved = directory.resolve()
        root = config_root().resolve()
        if resolved.is_relative_to(root):
            return None
        return resolved

    def taken_over(self) -> bool:
        """Has the user explicitly handed this directory to gtheme?"""
        return self.takeover_record.is_file()

    def _owner_name(self, foreign: Path) -> str:
        """A name for whatever owns the directory, in the user's words."""
        for part in reversed(foreign.parts):
            if part not in {"config", ".config", "ghostty", "/"}:
                return part
        return str(foreign)

    def _guard(self) -> None:
        foreign = self.foreign_root()
        if foreign is not None and not self.taken_over():
            raise PermissionError(FOREIGN_NOTICE.format(owner=self._owner_name(foreign)))

    # -- the protocol ------------------------------------------------------

    def detect(self) -> TerminalState:
        installed = shutil.which("ghostty") is not None or self.config_dir.exists()
        foreign = self.foreign_root()
        notes = [self.reload_semantics.sentence()]
        if foreign is not None and not self.taken_over():
            notes.append(FOREIGN_NOTICE.format(owner=self._owner_name(foreign)))
        elif foreign is not None:
            notes.append(
                "You told gtheme to take these settings over; the original folder "
                "link was saved and can be put back."
            )
        return TerminalState(
            installed=installed,
            config_path=self.config_path if installed else None,
            foreign_root=foreign,
            current=self.current() if installed else None,
            notes=notes,
        )

    def current(self) -> Palette | None:
        """The look in effect, read back from the theme file the config names.

        Reading is always allowed, even from a foreign directory — showing
        someone what they already have changes nothing.
        """
        config = self._read(self.config_path)
        if config is None:
            return None
        opacity = _float_or(config.value("background-opacity"), 1.0)
        theme = config.value("theme")
        if theme:
            palette = self._read_theme_file(theme, opacity)
            if palette is not None:
                return palette
        background = config.value("background")
        foreground = config.value("foreground")
        if background and foreground:
            return read_palette(
                name=theme or "Ghostty",
                background=_hash(background),
                foreground=_hash(foreground),
                cursor=_hash_or_none(config.value("cursor-color")),
                ansi=_ansi_from(config),
                opacity=opacity,
            )
        return None

    def plan(self, palette: Palette) -> TerminalWrites:
        """A theme file, and the config line that points at it.

        Everything gtheme does not understand — every comment, every
        ``custom-shader``, every keybind — comes back out of the config
        untouched, because the config is edited line by line rather than
        regenerated.

        The theme file is listed first and the transaction keeps that order:
        pointing the config at a theme that is not on disk yet would leave the
        terminal briefly asking for something that does not exist.

        Raises:
            PermissionError: the config directory belongs to another tool and
                :meth:`take_over` has not been called (DESIGN.md F7). The
                refusal happens here, before the batch writes anything at all.
        """
        self._guard()
        confine(self.config_dir)

        slug = slugify(palette.name)
        theme_file = confine(self.themes_dir / slug)
        config = self._read(self.config_path) or KeyValueFile.parse("")
        config.set("theme", slug)
        config.set("background-opacity", _fmt_float(palette.opacity))
        return TerminalWrites(
            files=(
                FileChange(str(theme_file), self._render_theme(palette).encode("utf-8")),
                FileChange(str(confine(self.config_path)), config.render().encode("utf-8")),
            )
        )

    # -- taking the directory over ----------------------------------------

    def take_over(self) -> bool:
        """Replace a foreign config directory with a real one gtheme may write.

        The dir-level symlink is recorded first — its own target, not the
        contents — so :meth:`undo_takeover` can put the link back exactly as it
        was. The replacement directory is seeded with a copy of what the link
        pointed at, so nothing the user had disappears, and it is built in a
        temporary directory *beside* the config directory so no byte is ever
        written inside the foreign tree.

        Returns:
            Whether anything was done. False means the directory was already
            gtheme's to write.
        """
        foreign = self.foreign_root()
        if foreign is None:
            return False
        directory = self.config_dir
        link_target = os.readlink(directory) if directory.is_symlink() else None

        parent = confine(directory.parent)
        parent.mkdir(parents=True, exist_ok=True)
        record = {
            "config_dir": str(directory),
            "was_symlink": link_target is not None,
            "link_target": link_target,
            "resolved": str(foreign),
            "taken_over_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        # The snapshot is written BEFORE anything moves. If this machine loses
        # power one line further down, the record of what the link used to be
        # is already on disk and the takeover can be undone; the other order
        # would lose the link target and with it the way back.
        #
        # Not confined: this is gtheme's own state directory, not a destination
        # from a manifest, and under test it deliberately lives outside the
        # destination root.
        atomic_write_text(
            self.takeover_record, json.dumps(record, indent=2, sort_keys=True) + "\n"
        )

        staging = Path(tempfile.mkdtemp(dir=str(parent), prefix=".gtheme-ghostty-"))
        try:
            shutil.copytree(foreign, staging / "config-dir", symlinks=True)
            # os.replace cannot rename a directory over a symlink, so the link
            # is removed first. The copy already exists and the snapshot is
            # already recorded, so the gap is recoverable from either side.
            if link_target is not None:
                directory.unlink()
            os.replace(staging / "config-dir", directory)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return True

    def undo_takeover(self) -> bool:
        """Put the original folder link back, keeping gtheme's copy aside.

        The materialised directory is moved next to itself rather than deleted:
        it may hold changes made since the takeover, and deleting a directory
        the user might want is not an undo.
        """
        record_path = self.takeover_record
        if not record_path.is_file():
            return False
        record = json.loads(record_path.read_text(encoding="utf-8"))
        directory = self.config_dir
        if record.get("was_symlink") and record.get("link_target"):
            if directory.exists() and not directory.is_symlink():
                stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
                shutil.move(str(directory), str(confine(f"{directory}.gtheme-{stamp}")))
            directory.symlink_to(record["link_target"])
        record_path.unlink()
        return True

    # -- file shapes -------------------------------------------------------

    def _read(self, path: Path) -> KeyValueFile | None:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        return KeyValueFile.parse(text)

    def _read_theme_file(self, theme: str, opacity: float) -> Palette | None:
        path = self.themes_dir / theme
        parsed = self._read(path)
        if parsed is None:
            return None
        background = parsed.value("background")
        foreground = parsed.value("foreground")
        if not background or not foreground:
            return None
        return read_palette(
            name=theme,
            background=_hash(background),
            foreground=_hash(foreground),
            cursor=_hash_or_none(parsed.value("cursor-color")),
            ansi=_ansi_from(parsed),
            opacity=opacity,
        )

    def _render_theme(self, palette: Palette) -> str:
        """The theme file, with every value refused if it could start a line.

        Ghostty's config is one setting per line and has no escaping at all, so
        a value carrying a newline would not be a broken colour — it would be a
        second setting, and ghostty's settings include ones that name a
        program. :class:`~gtheme.terminal.model.Palette` has already refused
        anything of the sort; this is the second lock on the same door.
        """
        name = one_line(palette.name, what="the look name")
        background = one_line(palette.background, what="the background")
        foreground = one_line(palette.foreground, what="the text colour")
        cursor = one_line(palette.cursor or palette.foreground, what="the cursor colour")
        lines = [f"# {name} — written by gtheme"]
        for index, colour in enumerate(palette.ansi):
            lines.append(f"palette = {index}={one_line(colour, what=f'colour {index}')}")
        lines.append(f"background = {background}")
        lines.append(f"foreground = {foreground}")
        lines.append(f"cursor-color = {cursor}")
        lines.append(f"cursor-text = {background}")
        return "\n".join(lines) + "\n"


def _ansi_from(parsed: KeyValueFile) -> tuple[str, ...]:
    """The sixteen ``palette = N=#rrggbb`` lines, in index order.

    A partial palette is not a palette: ``Palette`` refuses anything that is not
    empty or exactly sixteen, so an incomplete file reads as "no ANSI colours"
    rather than blowing up the page that asked.
    """
    found: dict[int, str] = {}
    for value in parsed.values("palette"):
        index, sep, colour = value.partition("=")
        if not sep:
            continue
        try:
            found[int(index.strip())] = _hash(colour.strip())
        except ValueError:
            continue
    if len(found) != 16 or set(found) != set(range(16)):
        return ()
    return tuple(found[i] for i in range(16))


def _hash(colour: str) -> str:
    """Ghostty accepts ``#rrggbb`` and bare ``rrggbb``; gtheme speaks the first."""
    colour = colour.strip()
    return colour if colour.startswith("#") else f"#{colour}"


def _hash_or_none(colour: str | None) -> str | None:
    return _hash(colour) if colour else None


def _float_or(text: str | None, fallback: float) -> float:
    try:
        return float(text) if text is not None else fallback
    except ValueError:
        return fallback


def _fmt_float(value: float) -> str:
    return f"{value:g}"
