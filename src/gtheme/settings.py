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


def _run(args: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8")
    except FileNotFoundError:
        return 127, ""
    return proc.returncode, proc.stdout.strip()


# ---------------------------------------------------------------- gsettings ---
def gsettings_get(schema: str, key: str) -> str | None:
    code, out = _run(["gsettings", "get", schema, key])
    return out if code == 0 else None


def gsettings_set(schema: str, key: str, gvariant: str) -> bool:
    code, _ = _run(["gsettings", "set", schema, key, gvariant])
    return code == 0


def gsettings_reset(schema: str, key: str) -> bool:
    code, _ = _run(["gsettings", "reset", schema, key])
    return code == 0


# --------------------------------------------------------------------- dconf ---
def dconf_read(path: str) -> str | None:
    code, out = _run(["dconf", "read", path])
    if code != 0 or out == "":
        return None
    return out


def dconf_write(path: str, gvariant: str) -> bool:
    code, _ = _run(["dconf", "write", path, gvariant])
    return code == 0


def dconf_reset(path: str) -> bool:
    code, _ = _run(["dconf", "reset", path])
    return code == 0


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
            return gsettings_set(self.schema, self.gkey, self.value)
        return dconf_write(self.key, self.value)

    def restore(self, saved: str | None) -> bool:
        """Write ``saved`` back, or reset the key if it had no prior value."""
        if saved is None:
            if self.backend == "gsettings":
                return gsettings_reset(self.schema, self.gkey)
            return dconf_reset(self.key)
        if self.backend == "gsettings":
            return gsettings_set(self.schema, self.gkey, saved)
        return dconf_write(self.key, saved)


def backend_available(backend: str) -> bool:
    return shutil.which(backend) is not None
