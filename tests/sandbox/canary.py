"""The live-desktop canary — proof, per test, that nothing real was touched.

DESIGN.md F6. The sandbox tier boots a real GNOME Shell on the same machine the
developer is sitting in front of. Isolation is asserted by construction (a
private bus plus a rerooted ``XDG_CONFIG_HOME`` on the ``dbus-run-session``
invocation itself), but "asserted by construction" is exactly the claim that a
one-character mistake makes false while every test still passes.

So every sandbox test is wrapped in a before/after comparison of the live
desktop's actual bytes:

* the live dconf store's modification time — a write that reached the real
  dconf-service would touch it, even if the value written happened to match,
* the live ``enabled-extensions`` value, byte for byte,
* recursive content hashes of the five directories the app can write to:
  installed extensions, staged extension updates, wallpapers, gtheme's own
  state, and the NIGHTBLOOM ghostty config that ``~/.config/ghostty`` is a
  symlink into.

Nothing in this module writes anything. It shells out to ``gsettings`` for the
extension list rather than using ``Gio`` on purpose: the test process must read
the *live* session's value, and a ``Gio.Settings`` object cached by some other
import could be pointed anywhere.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "LIVE_TREES",
    "Snapshot",
    "assert_unchanged",
    "live_dconf_path",
    "live_enabled_extensions",
    "snapshot",
    "tree_hash",
]

#: Everything the app could plausibly write outside dconf. Paths are given
#: relative to the user's home so the list reads as documentation.
LIVE_TREES: tuple[str, ...] = (
    ".local/share/gnome-shell/extensions",
    ".local/share/gnome-shell/extension-updates",
    ".local/share/backgrounds",
    ".local/state/gtheme",
    "nightbloom/ghostty",
    # An add-on that keeps its settings in a file of its own rather than in
    # dconf: the dconf half of this canary cannot see it at all. Added after a
    # unit test wrote into the real one — see the note in
    # tests/unit/test_descriptors_widgets.py.
    ".config/burn-my-windows",
)

#: Marker recorded for a tree that does not exist. Distinct from any hash, so a
#: directory appearing or disappearing during a test is itself a failure.
ABSENT = "absent"

_CHUNK = 1 << 20


def live_dconf_path() -> Path:
    """The live session's dconf store file."""
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "dconf" / "user"


def _hash_file(path: Path, digest: hashlib._Hash) -> None:
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_CHUNK)
            if not chunk:
                break
            digest.update(chunk)


def tree_hash(root: Path) -> str:
    """A content hash of a directory tree, or :data:`ABSENT`.

    Walks in sorted order and feeds the digest, for every entry: its path
    relative to the root, what kind of thing it is, and its content — the file's
    bytes, or a symlink's target text. Symlinks are never followed, which
    matters here because ``~/.config/ghostty`` is a symlink into a separate
    repository and following it would hash the same tree twice while missing a
    replaced link entirely.

    A single file (rather than a directory) hashes as itself.
    """
    if not root.exists() and not root.is_symlink():
        return ABSENT
    digest = hashlib.sha256()
    if root.is_symlink():
        digest.update(b"link\0" + os.readlink(root).encode())
        return digest.hexdigest()
    if root.is_file():
        digest.update(b"file\0")
        _hash_file(root, digest)
        return digest.hexdigest()

    entries: list[Path] = sorted(p for p in root.rglob("*"))
    for path in entries:
        rel = str(path.relative_to(root)).encode()
        if path.is_symlink():
            digest.update(b"link\0" + rel + b"\0" + os.readlink(path).encode())
        elif path.is_dir():
            digest.update(b"dir\0" + rel)
        elif path.is_file():
            digest.update(b"file\0" + rel + b"\0")
            try:
                _hash_file(path, digest)
            except OSError as exc:  # unreadable is still a fact worth pinning
                digest.update(f"unreadable:{exc.errno}".encode())
        else:
            digest.update(b"other\0" + rel)
    return digest.hexdigest()


def live_enabled_extensions() -> str:
    """The live session's ``org.gnome.shell enabled-extensions``, as text.

    ``LC_ALL=C`` for the same reason the subprocess settings backend pins it:
    the value is compared as bytes and must not move under a locale.
    """
    env = dict(os.environ, LC_ALL="C")
    result = subprocess.run(
        ["gsettings", "get", "org.gnome.shell", "enabled-extensions"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        return f"<unavailable rc={result.returncode}>"
    return result.stdout.strip()


@dataclass(frozen=True)
class Snapshot:
    """What the live desktop looked like at one instant."""

    dconf_mtime_ns: int | None
    dconf_size: int | None
    enabled_extensions: str
    trees: dict[str, str] = field(default_factory=dict)

    def differences(self, other: Snapshot) -> list[str]:
        """Human-readable descriptions of every field that moved."""
        out: list[str] = []
        if self.dconf_mtime_ns != other.dconf_mtime_ns:
            out.append(
                "the live dconf store was written: mtime "
                f"{self.dconf_mtime_ns} -> {other.dconf_mtime_ns}"
            )
        if self.dconf_size != other.dconf_size:
            out.append(f"live dconf store size {self.dconf_size} -> {other.dconf_size}")
        if self.enabled_extensions != other.enabled_extensions:
            out.append(
                "live enabled-extensions changed:\n"
                f"  before: {self.enabled_extensions}\n"
                f"  after:  {other.enabled_extensions}"
            )
        for name in sorted(set(self.trees) | set(other.trees)):
            before = self.trees.get(name, ABSENT)
            after = other.trees.get(name, ABSENT)
            if before != after:
                out.append(f"~/{name} changed on disk ({before[:12]} -> {after[:12]})")
        return out


def snapshot(home: Path | None = None) -> Snapshot:
    """Read the live desktop's state. Reads only."""
    root = home or Path.home()
    store = live_dconf_path()
    try:
        stat = store.stat()
        mtime: int | None = stat.st_mtime_ns
        size: int | None = stat.st_size
    except FileNotFoundError:
        mtime = size = None
    return Snapshot(
        dconf_mtime_ns=mtime,
        dconf_size=size,
        enabled_extensions=live_enabled_extensions(),
        trees={name: tree_hash(root / name) for name in LIVE_TREES},
    )


def assert_unchanged(before: Snapshot, after: Snapshot, *, context: str = "") -> None:
    """Raise ``AssertionError`` naming exactly what leaked, or return quietly."""
    differences = before.differences(after)
    if not differences:
        return
    where = f" during {context}" if context else ""
    raise AssertionError(
        "THE LIVE DESKTOP WAS MODIFIED" + where + ". The sandbox leaked:\n  - "
        + "\n  - ".join(differences)
    )
