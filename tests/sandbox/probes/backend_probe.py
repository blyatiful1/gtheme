"""Drive a :class:`SettingsBackend` from *inside* the sandbox, and report JSON.

This runs as a subprocess, never in the pytest process, and that is the whole
point. A backend under test reads ``DBUS_SESSION_BUS_ADDRESS`` and
``XDG_CONFIG_HOME`` from its own environment: run it in-process and a buggy
backend writes to the developer's real dconf, which is precisely the failure
this tier exists to make impossible.

Usage::

    backend_probe.py <BackendName> <<< '[["set", "gsettings:x y", "1"], ...]'

Reads a JSON list of ``[op, key, value?]`` from stdin, applies them in order,
and prints one JSON object to stdout::

    {"backend": "GioBackend", "results": [{"op": ..., "ok": true, "value": "..."}]}

A backend that is not implemented yet reports ``kind: "not-implemented"`` rather
than crashing, so the caller can skip with an honest reason instead of reading a
traceback.
"""

from __future__ import annotations

import json
import sys


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: backend_probe.py <BackendName>", file=sys.stderr)
        return 2
    name = argv[1]

    from gtheme.core import settings_backend as sb

    try:
        backend = getattr(sb, name)()
    except AttributeError:
        print(json.dumps({"error": f"no backend named {name!r}"}))
        return 1

    operations = json.loads(sys.stdin.read())
    results = []
    for entry in operations:
        op, key = entry[0], entry[1]
        value = entry[2] if len(entry) > 2 else None
        record: dict = {"op": op, "key": key}
        try:
            if op == "get":
                record["value"] = backend.get(key)
            elif op == "set":
                backend.set(key, value)
            elif op == "reset":
                backend.reset(key)
            elif op == "roundtrip":
                backend.set(key, value)
                record["value"] = backend.get(key)
            else:
                raise ValueError(f"unknown op {op!r}")
            record["ok"] = True
        except NotImplementedError as exc:
            record["ok"] = False
            record["kind"] = "not-implemented"
            record["message"] = str(exc)
        except sb.BackendError as exc:
            record["ok"] = False
            record["kind"] = exc.kind.value
            record["message"] = str(exc)
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            record["ok"] = False
            record["kind"] = "unexpected:" + type(exc).__name__
            record["message"] = str(exc)
        results.append(record)

    print(json.dumps({"backend": name, "results": results}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
