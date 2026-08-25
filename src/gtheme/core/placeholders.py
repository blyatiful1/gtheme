"""``{{ }}`` tokens, and the gate that stops a half-resolved one being written.

Some settings cannot be written down in advance because their address depends
on the machine. The clearest case is Ptyxis, whose per-profile settings live
under a path containing a profile identifier generated on first run:

    dconf:/org/gnome/Ptyxis/Profiles/{{ ptyxis_default_profile }}/palette

A Look writes the token; gtheme resolves it at apply time from a probe.

The gate is the part that took a bug to learn. If the probe finds nothing, the
token either stays as literal ``{{ ... }}`` text, or — worse — collapses to
nothing and leaves ``/Profiles//palette``, a path with an empty component that
dconf rejects. Both cases must be a named skip with a sentence the user can
act on, never a write, and never a crash. :func:`key_ok` is that check, and
apply, preview and the diff all run it, so a preview never promises a write the
apply will refuse.

Probes are a registry rather than the single hardcoded Ptyxis lookup v1 had,
because the terminal adapters land more of them.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING

from .paths import dest_root

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .settings_backend import SettingsBackend

__all__ = [
    "Probe",
    "clear_cache",
    "key_ok",
    "register_probe",
    "resolve",
    "runtime_context",
    "unresolved_tokens",
]

_TOKEN = re.compile(r"\{\{\s*(\w+)\s*\}\}")

#: A probe answers "what is this token worth on this machine?". Returning None
#: means "not applicable here", which becomes a named skip rather than an error.
Probe = Callable[["SettingsBackend | None"], "str | None"]

_PROBES: dict[str, Probe] = {}
_CACHE: dict[str, str] | None = None


def register_probe(name: str, probe: Probe) -> None:
    """Teach the resolver about a token. Replaces any probe of the same name.

    Registering invalidates the cached context, so a terminal adapter that
    registers its probe during start-up is picked up by the next apply.
    """
    _PROBES[name] = probe
    clear_cache()


def clear_cache() -> None:
    """Forget probed values. The next :func:`runtime_context` re-probes."""
    global _CACHE
    _CACHE = None


def _probe_home(_backend: SettingsBackend | None) -> str | None:
    return str(dest_root())


def _probe_ptyxis_default_profile(backend: SettingsBackend | None) -> str | None:
    """The identifier of Ptyxis's default profile, if Ptyxis is installed.

    The schema default is the empty string, which prints as two quote
    characters. Stripping has to happen *before* the emptiness test or an
    unset profile resolves to nothing and produces the ``//`` path
    :func:`key_ok` then has to catch.
    """
    if backend is None:
        return None
    try:
        raw = backend.get("gsettings:org.gnome.Ptyxis default-profile-uuid")
    except Exception:  # noqa: BLE001 - Ptyxis absent is the common case
        return None
    value = raw.strip().strip("'\"").strip()
    return value or None


register_probe("home", _probe_home)
register_probe("ptyxis_default_profile", _probe_ptyxis_default_profile)


def runtime_context(
    backend: SettingsBackend | None = None,
    *,
    refresh: bool = False,
) -> dict[str, str]:
    """Probe every token once and remember the answers.

    Args:
        backend: how to read settings, for probes that need to. Passing None
            means only the probes that need no settings answer.
        refresh: re-probe even if there is a cached answer. An apply that runs
            after an install did something should not use a stale profile id.

    Returns:
        Token name to value, with unanswerable tokens simply absent.
    """
    global _CACHE
    if _CACHE is not None and not refresh:
        return dict(_CACHE)
    context: dict[str, str] = {}
    for name, probe in _PROBES.items():
        try:
            value = probe(backend)
        except Exception:  # noqa: BLE001 - a broken probe must not stop an apply
            value = None
        if value:
            context[name] = value
    _CACHE = context
    return dict(context)


def resolve(text: str, context: dict[str, str] | None = None) -> str:
    """Substitute known tokens. Unknown ones are left exactly as written.

    Leaving them is deliberate: :func:`key_ok` recognises the leftover ``{{``
    and skips the setting with a sentence naming what was missing. Substituting
    an empty string instead would produce a plausible-looking, wrong address.
    """
    values = context if context is not None else runtime_context()
    return _TOKEN.sub(lambda match: values.get(match.group(1), match.group(0)), text)


def unresolved_tokens(text: str) -> list[str]:
    """Token names still standing in ``text``, in order, without duplicates."""
    found: list[str] = []
    for match in _TOKEN.finditer(text):
        if match.group(1) not in found:
            found.append(match.group(1))
    return found


def key_ok(key: str) -> bool:
    """May this key string be written?

    False when a token did not resolve, and false when resolving one to nothing
    left an empty component in a path (``//``). Both are skips with a reason,
    never writes.
    """
    if "{{" in key:
        return False
    prefix, _, rest = key.partition(":")
    if prefix == "dconf":
        return "//" not in rest
    if prefix == "gsettings-path":
        _schema, _, tail = rest.partition(":")
        path, _, _key = tail.partition(" ")
        return "//" not in path
    return True
