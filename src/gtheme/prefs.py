"""The app's own preferences — a plain JSON file, on purpose.

THE CONTRACT IS FROZEN (DESIGN.md F3). gtheme ships no GSettings schema of its
own. It could, but shipping one means a schema file to install, a
``glib-compile-schemas`` step in every packaging path, and a failure mode
("Settings schema not installed") that crashes the app before its window
appears. waypaper — the closest real precedent for a build-system-less
PyGObject app — stores its preferences itself for exactly this reason.

So: one JSON object at ``~/.config/gtheme/prefs.json``. It holds only things
about the *app* (which page was open, whether an explainer has been dismissed).
Nothing here ever describes the desktop; desktop state lives in the desktop.

Writes are atomic — temp file in the same directory, ``fsync``, then
``os.replace`` — because a preferences file truncated by a crash would take the
onboarding state with it, and re-onboarding someone who has used the app for a
month is a small betrayal.

``GTHEME_CONFIG_DIR`` overrides the location. That is the seam the test suite
uses; it is read on every call rather than cached at import, so a test that
sets it after import still gets an isolated directory.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

__all__ = [
    "PREFS_FILENAME",
    "Prefs",
    "config_dir",
    "default_prefs_path",
]

PREFS_FILENAME = "prefs.json"

#: Banner ids that have a defined meaning. Keeping them here rather than
#: scattered through the pages means the "show all explainers again" action can
#: be exhaustive, and means there is one list to read when asking what this app
#: explains to a first-time user.
#:
#: A test walks ``src/`` and asserts this set is exactly the set of ids the
#: pages actually use — in both directions, so an id that is added here and
#: never shown is as much a failure as one shown and never listed. It was six
#: short when that test was written: every page in the "Change one thing"
#: section had grown a first-visit banner without saying so here.
KNOWN_BANNERS: frozenset[str] = frozenset(
    {
        "onboarding-complete",
        "first-visit-home",
        "first-visit-looks",
        "first-visit-colors",
        "first-visit-icons",
        "first-visit-fonts",
        "first-visit-topbar",
        "first-visit-windows",
        "first-visit-addons",
        "first-visit-terminal",
        "first-visit-more",
        "first-visit-restore",
        "addon-settings-are-the-authors",
    }
)


def config_dir() -> Path:
    """Where preferences live. Honours ``GTHEME_CONFIG_DIR``, then XDG."""
    override = os.environ.get("GTHEME_CONFIG_DIR")
    if override:
        return Path(override)
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "gtheme"


def default_prefs_path() -> Path:
    return config_dir() / PREFS_FILENAME


class Prefs:
    """The preferences file, loaded lazily and written atomically.

    Args:
        path: override the file location outright. Normally omitted, in which
            case :func:`default_prefs_path` decides — which means
            ``GTHEME_CONFIG_DIR`` decides.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._explicit_path = Path(path) if path is not None else None
        self._data: dict[str, Any] | None = None

    @property
    def path(self) -> Path:
        return self._explicit_path if self._explicit_path is not None else default_prefs_path()

    # -- loading and saving ------------------------------------------------

    def _load(self) -> dict[str, Any]:
        if self._data is not None:
            return self._data
        path = self.path
        data: dict[str, Any] = {}
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                # A corrupt or unreadable preferences file must never stop the
                # app from opening. Defaults are always a usable answer, and
                # the file is rewritten on the next set().
                loaded = None
            if isinstance(loaded, dict):
                data = loaded
        self._data = data
        return data

    def reload(self) -> None:
        """Drop the in-memory copy so the next read hits disk again."""
        self._data = None

    def save(self) -> None:
        """Write the current values out atomically."""
        data = self._load()
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(data, indent=2, sort_keys=True) + "\n"
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".prefs-", suffix=".tmp")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    # -- values ------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """One preference, or ``default`` when it has never been set."""
        return self._load().get(key, default)

    def set(self, key: str, value: Any, *, save: bool = True) -> None:
        """Set one preference. Writes immediately unless ``save=False``."""
        self._load()[key] = value
        if save:
            self.save()

    def unset(self, key: str, *, save: bool = True) -> bool:
        """Forget a preference. Returns whether it was there."""
        existed = self._load().pop(key, _MISSING) is not _MISSING
        if existed and save:
            self.save()
        return existed

    def as_dict(self) -> dict[str, Any]:
        """A copy of everything stored."""
        return dict(self._load())

    # -- one-shot banners --------------------------------------------------
    #
    # Every major page shows a dismissible explainer the first time it is
    # visited. "Seen" is sticky: an explainer a person dismissed does not come
    # back, because a banner that reappears reads as a bug.

    @staticmethod
    def _banner_key(banner_id: str) -> str:
        return f"banner-seen/{banner_id}"

    def banner_seen(self, banner_id: str) -> bool:
        """Has this explainer already been shown and dismissed?"""
        return bool(self.get(self._banner_key(banner_id), False))

    def mark_banner_seen(self, banner_id: str, *, save: bool = True) -> None:
        """Record that an explainer was dismissed."""
        self.set(self._banner_key(banner_id), True, save=save)

    def should_show_banner(self, banner_id: str) -> bool:
        """The question a page actually asks. Inverse of :meth:`banner_seen`."""
        return not self.banner_seen(banner_id)

    def reset_banners(self, *, save: bool = True) -> int:
        """Show every explainer again. Backs "Show the introduction again".

        Returns how many were forgotten.
        """
        data = self._load()
        stale = [k for k in data if k.startswith("banner-seen/")]
        for key in stale:
            del data[key]
        if stale and save:
            self.save()
        return len(stale)


class _Missing:
    __slots__ = ()


_MISSING = _Missing()
