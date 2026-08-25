#!/usr/bin/env python3
"""Take a PNG screenshot of a GNOME Shell session over D-Bus.

Why this exists instead of a one-line `gdbus call`:
gnome-shell's ScreenshotService guards every method with a SenderChecker. Its
checkInvocation() passes only if the shell is in unsafe mode OR the caller owns
one of a small allow-list of well-known bus names. A plain `gdbus call` owns no
well-known name, so it gets:

    GDBus.Error:org.freedesktop.DBus.Error.AccessDenied: Screenshot is not allowed

The fix: acquire an allow-listed well-known name on the (private) session bus
first, wait for the shell's name-watcher to see it, then call
org.gnome.Shell.Screenshot.Screenshot.

MEASURED on GNOME Shell 50.4 (2026-08-25), against a private headless shell:
    org.gnome.SettingsDaemon.MediaKeys        -> ALLOWED  (PNG written)
    org.freedesktop.impl.portal.desktop.gnome -> ALLOWED  (PNG written)
    org.gnome.Screenshot                      -> DENIED   (dropped from the
                                                 allow-list; gnome-screenshot
                                                 is deprecated)
    org.gnome.Shell.Screenshot                -> cannot be acquired (the shell
                                                 already owns it)

Taking these names is safe HERE only because this always runs against a private
bus where no real gnome-settings-daemon / portal is running. Never point this at
the live session bus.

Usage: shot.py /abs/path/out.png
Reads DBUS_SESSION_BUS_ADDRESS from the environment like any bus client.
"""

import os
import sys

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

# Tried in order; first one we can acquire wins.
ALLOWED_NAMES = [
    "org.gnome.SettingsDaemon.MediaKeys",
    "org.freedesktop.impl.portal.desktop.gnome",
]
# The shell watches these names asynchronously; give its NameOwnerChanged
# handler a beat to register us before we call, or we race and get AccessDenied.
SETTLE_MS = 1200


def attempt(name, path):
    """Own `name`, then screenshot to `path`. Returns (ok, message)."""
    loop = GLib.MainLoop()
    res = {"ok": False, "msg": f"never acquired {name}"}
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    def do_shot():
        try:
            ret = bus.call_sync(
                "org.gnome.Shell",
                "/org/gnome/Shell/Screenshot",
                "org.gnome.Shell.Screenshot",
                "Screenshot",
                GLib.Variant("(bbs)", (False, False, path)),
                GLib.VariantType("(bs)"),
                Gio.DBusCallFlags.NONE,
                25000,
                None,
            )
            ok, used = ret.unpack()
            res["ok"] = bool(ok)
            res["msg"] = used if ok else "shell returned success=false"
        except GLib.Error as e:
            res["ok"] = False
            res["msg"] = e.message
        loop.quit()
        return False

    def on_acquired(_conn, _name):
        GLib.timeout_add(SETTLE_MS, do_shot)

    def on_lost(_conn, _name):
        if not res["ok"]:
            res["msg"] = f"could not acquire {name} (already owned?)"
            loop.quit()

    owner_id = Gio.bus_own_name(
        Gio.BusType.SESSION, name, Gio.BusNameOwnerFlags.REPLACE,
        None, on_acquired, on_lost,
    )
    GLib.timeout_add_seconds(40, lambda: (loop.quit(), False)[1])
    loop.run()
    Gio.bus_unown_name(owner_id)
    return res["ok"], res["msg"]


def main(path):
    for name in ALLOWED_NAMES:
        ok, msg = attempt(name, path)
        print(f"shot.py: via {name}: {'OK ' + msg if ok else 'FAILED ' + msg}",
              file=sys.stdout if ok else sys.stderr, flush=True)
        if ok and os.path.exists(path) and os.path.getsize(path) > 0:
            return 0
    print("shot.py: all allow-listed names failed", file=sys.stderr, flush=True)
    return 1


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].startswith("/"):
        print("usage: shot.py /abs/path/out.png", file=sys.stderr)
        sys.exit(2)
    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        print("shot.py: DBUS_SESSION_BUS_ADDRESS not set", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
