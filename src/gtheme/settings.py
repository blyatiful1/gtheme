"""gsettings / dconf wrappers and runtime placeholder resolution.

Setting values are serialized GVariant text, which both ``gsettings set`` and
``dconf write`` accept verbatim — so reading a value and writing it back later
round-trips cleanly, which is what makes generic restore possible.

Manifests may embed ``{{ placeholder }}`` tokens in a setting's key or value
(e.g. the per-machine Ptyxis profile UUID). They are resolved at apply time
from :func:`runtime_context`.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from functools import lru_cache

from .manifest import Setting
from .paths import DEST_ROOT

_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def _run(args: list[str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8")
    except FileNotFoundError:
        return 127, "", f"{args[0]}: command not found"
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


# Stderr that gsettings prints on a code-0 "success" that did not actually
# persist (no dconf to commit to, e.g. no session bus). Treat it as failure.
_DCONF_COMMIT_FAIL = "failed to commit changes to dconf"


# ---------------------------------------------------------------- gsettings ---
def gsettings_get(schema: str, key: str) -> str | None:
    code, out, _err = _run(["gsettings", "get", schema, key])
    return out if code == 0 else None


def gsettings_set(schema: str, key: str, gvariant: str) -> tuple[bool, str]:
    code, _out, err = _run(["gsettings", "set", schema, key, gvariant])
    # A code-0 result whose stderr says it couldn't commit didn't persist.
    if code == 0 and _DCONF_COMMIT_FAIL in err.lower():
        return False, err
    return code == 0, err


def gsettings_reset(schema: str, key: str) -> tuple[bool, str]:
    code, _out, err = _run(["gsettings", "reset", schema, key])
    return code == 0, err


# --------------------------------------------------------------------- dconf ---
def dconf_read(path: str) -> str | None:
    code, out, _err = _run(["dconf", "read", path])
    if code != 0 or out == "":
        return None
    return out


def dconf_write(path: str, gvariant: str) -> tuple[bool, str]:
    code, _out, err = _run(["dconf", "write", path, gvariant])
    return code == 0, err


def dconf_reset(path: str) -> tuple[bool, str]:
    code, _out, err = _run(["dconf", "reset", path])
    return code == 0, err


def _canon_gvariant(text: str) -> str:
    """Canonicalise GVariant text for comparison; fall back to a trimmed string."""
    try:  # PyGObject may be absent (non-GNOME / minimal venv).
        from gi.repository import GLib

        return GLib.Variant.parse(None, text, None, None).print_(False)
    except Exception:  # noqa: BLE001 — any parse/import failure -> trimmed compare
        return text.strip()


def values_equal(current: str | None, wanted: str) -> bool:
    """True if a setting's current value already equals the wanted value.

    Compares canonical GVariant forms so a non-canonical-but-equivalent manifest
    value (e.g. ``"zoom"`` vs ``'zoom'``, stray spaces) is not reported changed.
    """
    if current is None:
        return False
    if current == wanted:
        return True
    return _canon_gvariant(current) == _canon_gvariant(wanted)


# ---------------------------------------------------------------- placeholders ---
@lru_cache(maxsize=1)
def runtime_context() -> dict[str, str]:
    """Values that can be substituted into setting keys/values at apply time."""
    ctx = {"home": str(DEST_ROOT)}
    uuid = gsettings_get("org.gnome.Ptyxis", "default-profile-uuid")
    if uuid:
        ctx["ptyxis_default_profile"] = uuid.strip().strip("'")
    return ctx


def resolve(text: str, ctx: dict[str, str] | None = None) -> str:
    ctx = ctx if ctx is not None else runtime_context()
    return _PLACEHOLDER.sub(lambda m: ctx.get(m.group(1), m.group(0)), text)


# ---------------------------------------------------- unified setting helpers ---
class ResolvedSetting:
    """A :class:`Setting` with placeholders resolved and key split out."""

    def __init__(self, setting: Setting, ctx: dict[str, str] | None = None):
        self.backend = setting.backend
        self.component = setting.component
        self.key = resolve(setting.key, ctx)
        self.value = resolve(setting.value, ctx)
        self.error = ""  # last backend stderr, set by apply()/restore()
        if self.backend == "gsettings":
            schema, _, gkey = self.key.partition(" ")
            self.schema, self.gkey = schema, gkey.strip()
        else:
            self.schema, self.gkey = "", ""

    @property
    def label(self) -> str:
        return self.key

    def get_current(self) -> str | None:
        if self.backend == "gsettings":
            return gsettings_get(self.schema, self.gkey)
        return dconf_read(self.key)

    def apply(self) -> bool:
        if self.backend == "gsettings":
            ok, err = gsettings_set(self.schema, self.gkey, self.value)
        else:
            ok, err = dconf_write(self.key, self.value)
        self.error = err
        return ok

    def restore(self, saved: str | None) -> bool:
        """Write ``saved`` back, or reset the key if it had no prior value."""
        if saved is None:
            if self.backend == "gsettings":
                ok, err = gsettings_reset(self.schema, self.gkey)
            else:
                ok, err = dconf_reset(self.key)
        elif self.backend == "gsettings":
            ok, err = gsettings_set(self.schema, self.gkey, saved)
        else:
            ok, err = dconf_write(self.key, saved)
        self.error = err
        return ok


def backend_available(backend: str) -> bool:
    return shutil.which(backend) is not None
