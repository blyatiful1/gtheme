# The sandbox tier

This directory boots a **real GNOME Shell** — `gnome-shell --headless
--virtual-monitor 1920x1080` — on a **private D-Bus session**, runs gtheme
inside it, and proves after every single test that the live desktop was not
touched.

It is **local only**. `addopts = -m "not sandbox"` keeps it out of a plain
`pytest` run, and it never runs in CI. Run it deliberately:

```
.venv/bin/python -m pytest -q -m sandbox        # this tier
./verify.sh --full                              # everything, this tier included
```

A red sandbox is a red check. `verify.sh` never wraps it in `|| true`.

## One file here is not in that tier

`test_dconf_roundtrip.py` carries the **`dconf`** marker instead, and runs
everywhere a plain `pytest` does — including both CI jobs. It needs the private
bus and the dconf-service that bus activates, and nothing else: no shell, no
compositor, no seat. `SandboxSession.start_bus_only()` is that session.

It lives here because everything it borrows lives here — `sandboxlib`, the
backend probe, and above all the canary, which wraps it exactly as it wraps the
rest of the directory. Keeping the write-parity and round-trip assertions in
the local-only tier meant CI proved the two settings backends agreed on *reads*
and nothing more, while the write halves went unrun for months
(review-report M20).

## Why any of this is safe

`XDG_CONFIG_HOME=<tmp>` on its own does **nothing**. A `gsettings set` goes over
D-Bus to the dconf-service that is *already running* — which has the real
`XDG_CONFIG_HOME` — and the value lands in the real store. Isolation comes from
`dbus-run-session`: a fresh bus activates a *fresh* dconf-service that inherits
the sandbox environment. Both are required, and the environment must be set
**on the `dbus-run-session` invocation itself**, not exported inside it.

`SandboxSession` refuses to continue if the bus address it gets back equals
`DBUS_SESSION_BUS_ADDRESS`.

## The canary (`canary.py`)

Autouse, around **every** test in this directory. Before and after, it records:

| What | Why |
|---|---|
| `~/.config/dconf/user` mtime and size | a write that reached the real dconf-service touches it, even if the value written happened to match |
| live `org.gnome.shell enabled-extensions` | byte for byte |
| `~/.local/share/gnome-shell/extensions` | recursive content hash |
| `~/.local/share/gnome-shell/extension-updates` | staged updates |
| `~/.local/share/backgrounds` | wallpapers the app copies into |
| `~/.local/state/gtheme` | restore points and the ownership ledger |
| `~/nightbloom/ghostty` | what `~/.config/ghostty` is a symlink into |

Symlinks are recorded but never followed, so *replacing a link* is visible.
`test_isolation.py::test_the_canary_would_actually_notice` proves the canary can
fail; `tests/unit/test_harness_canary.py` tests its logic in the tier that
always runs.

## The two data modes (DESIGN.md F6)

| Fixture | `XDG_DATA_HOME` | Use for |
|---|---|---|
| `sandbox_shared_data` | the user's real one, **read-only** | rendering, page-walks, screenshots — seeing the real machine is the point |
| `sandbox_private_data` | private, seeded with `window-calls` + the committed fixture corpus | anything that installs, enables, stages or uninstalls an extension |

If a test could write extension state, it uses `sandbox_private_data`. There is
no third option.

`broadway_session` is the cheap variant: `gtk4-broadwayd` plus
`dbus-run-session`, no shell at all, about a second to start. That is what the
CI `gtk` job uses and what to iterate against while building a page. It cannot
tell you anything about shell chrome, extensions or screenshots.

## What is here

| File | Role |
|---|---|
| `sandboxlib.py` | `SandboxSession` — boot, readiness polling, D-Bus helpers, screenshots, teardown |
| `canary.py` | the live-desktop proof |
| `shot.py` | screenshot helper that acquires an allow-listed bus name first |
| `ext-root/` | the test-only extension that unlocks `Eval`. **Read its README.** |
| `probes/` | scripts run *inside* the sandbox: the sidebar walker, the settings-backend driver |
| `test_isolation.py` | the canary write, and proof the canary can fail |
| `test_runtime_load.py` | the A5 verdict, pinned as a permanent regression |
| `test_dconf_roundtrip.py` | GVariant goldens against a real dconf, plus backend write parity — marked `dconf`, bus only, **runs in CI** |
| `test_boot_smoke.py` | gtheme starts, maps a window, lists fifteen pages, can be photographed |
| `test_broadway.py` | the offscreen variant, marked `gtk` so CI runs it |

`test_app_pages.py` — the full page-walk that screenshots every registered page
in light and dark — lands in Wave 3, once there are pages to walk.

## Non-obvious things that will bite you

Every one of these was measured on GNOME Shell 50.4, not guessed.

* **A headless shell is stuck in the Overview forever.** It has no seat, so
  nothing produces the interaction that dismisses it, and every screenshot shows
  window thumbnails. `window-calls`' `Activate` does **not** fix it. The
  `gtheme-sandbox@gtheme.local` extension turns on `unsafe_mode` so
  `org.gnome.Shell.Eval` works, and `Main.overview.hide()` does.
* **`org.gnome.Shell.Screenshot` is sender-gated.** A plain `gdbus call` owns no
  well-known bus name and gets `AccessDenied`. Owning
  `org.gnome.SettingsDaemon.MediaKeys` (or the portal impl name) passes; owning
  `org.gnome.Screenshot` — the obvious guess — does **not**. After acquiring the
  name, wait ~1.2s for the shell's asynchronous name-watcher, or you race it and
  still get denied. That is what `shot.py` does.
* **`GetFrameRect` returns 0x0** for 4-6 seconds after a window maps. Poll for a
  non-zero width.
* **`Peer.Ping` answers ~1.5s before the extension directory scan runs.** Gating
  readiness on it makes an extension look like it runtime-loaded when it did
  not — that mistake produced the wrong answer once already. Gate on the shell's
  own "GNOME Shell started at" log line.
* **`env` argument order**: `env -u DISPLAY FOO=1 cmd`, never `env FOO=1 -u
  DISPLAY cmd` — GNU `env` stops parsing options at the first non-option
  argument and tries to run a program called `-u`. Building the environment as a
  Python dict is how this port avoids the trap entirely.
* **Teardown kills recorded PIDs.** Never `pkill -f gnome-shell`: on this
  machine that pattern matches the harness's own shell.
* **Timings**: bus 200 ms, `org.gnome.Shell` 0-200 ms, window listed 400 ms,
  frame geometry 4-6 s, a full shell boot 60-90 s.

## Rules

1. Nothing here writes below `~/.local/share/gnome-shell/`. The user's
   extensions directory is a **read-only source**.
2. `gtheme-sandbox@gtheme.local` is never installed, never added to the live
   `enabled-extensions`, never copied anywhere.
3. Every session gets a unique `--wayland-display` and its own temporary root,
   so two test processes cannot collide.
4. A test that writes extension state uses `sandbox_private_data`.
