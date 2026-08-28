# Testing

## The canonical check

```sh
./verify.sh          # lint + the three tiers that run anywhere
./verify.sh --full   # the above, plus the sandbox tier and the honesty gates
```

Exit 0 means green. `--full` is what "done" means; the plain form is what you
run while you work.

Everything runs out of `./.venv` on purpose. PEP 668 marks the system Python
externally-managed, so a bare `python` or `pip` here is either the wrong
interpreter or an error. Create it once:

```sh
uv venv --system-site-packages .venv && uv pip install -e '.[dev]'
```

`--system-site-packages` is not optional. PyGObject, GTK 4 and libadwaita come
from your distribution's packages; the pip wheels either do not exist or shadow
the system typelibs and break.

## Four tiers

| Tier | Size | Needs | When it runs |
|---|---|---|---|
| **unit + regression** | ~1,880 tests | nothing but Python and GLib | always — plain `pytest`, and both CI jobs |
| **dconf** (`-m dconf`) | 42 tests | a private D-Bus session and the dconf-service it activates — no shell | always — plain `pytest`, and both CI jobs |
| **gtk** (`-m gtk`) | ~660 tests | GTK 4 and libadwaita 1.9, offscreen is fine | plain `pytest` locally; in CI only inside an Arch container |
| **sandbox** (`-m sandbox`) | 29 tests | a private D-Bus session **and a real headless GNOME Shell** | `./verify.sh --full` only. **Never in CI.** |

`addopts = -m "not sandbox"` in `pyproject.toml` is what a plain `pytest` obeys:
it deselects those 29 tests rather than trying to boot a desktop, and selects
everything else.

Every tier except `sandbox` is run under `dbus-run-session`, by `verify.sh`, by
both CI jobs and by the Arch package's `check()` (`PKGBUILD` and `PKGBUILD-git`
both wrap the run and both carry `dbus` in `checkdepends`). That is not
decoration: the settings phase decides whether to run from
`DBUS_SESSION_BUS_ADDRESS`, so
without a bus those tests error out (a clean `makepkg` chroot has none), and
with the *live* bus they are one mistake away from the real desktop. A private
bus makes the verdict the same everywhere. The `sandbox` tier is deliberately
**not** wrapped: each session there starts a bus of its own, and the canary
around every test has to read the real desktop to say it did not move.

There is one more marker, `mutating`, which is not a tier. `tests/conftest.py`
**skips** any test carrying it unless an isolation seam is active, so a test
that would write real settings cannot run by accident.

### Tier 1 — unit and regression

The engine tested against a `MemoryBackend` and a temporary destination root.
`use_backend()` in `core/backends.py` is the seam and `tests/conftest.py` is
the only place that uses it, so the whole engine writes nowhere real without
any test having to remember to arrange that.

`tests/regression/` is the part worth knowing about. Version 1 of gtheme found,
fixed and comment-tagged a set of bugs in its apply engine, and a rewrite's
characteristic failure is reintroducing exactly those. Each tag became a named
test **before** the new transaction layer was written:
`test_AS4_a_transaction_that_applied_nothing_does_not_claim_it_did`,
`test_X1_a_look_unions_into_enabled_addons_instead_of_replacing_them`,
`test_E1_an_unusable_destination_root_refuses_every_write`, and the rest. The
table of what each guards is in
[docs/architecture.md](architecture.md#the-defect-tag-regression-suite), along
with the note recording the two tags that retired with the hooks system.

Also here: the guard that no module under `core/` imports GTK or libadwaita —
checked three ways, ending with an import with PyGObject removed from
`sys.modules` entirely, because `gtheme rescue` runs on a computer whose
graphical session is dead.

### Tier 2 — gtk

Anything that constructs a widget. It needs a real GTK, but not a real screen:
`gtk4-broadwayd` is an offscreen GDK backend, which means no X server, no
compositor and no Xvfb.

This tier is why the CI split exists. Ubuntu runners ship libadwaita 1.5 and
gtheme targets 1.9, so no Adw code may run there at all.

### Tier 3 — dconf

`tests/sandbox/test_dconf_roundtrip.py`, and nothing else. It writes GVariant
text through a **real dconf** and reads it back: `@as []`, maybe types, Pango's
`@wght=460` suffix, an `a{sv}` dictionary — the shapes a type-blind restore
mangles. Then it makes `GioBackend` and `SubprocessBackend` write the same
table and compares them byte for byte, because a value captured under one
backend and restored under the other has to be the same value.

It lives in `tests/sandbox/` and borrows that directory's harness and canary,
but it is not the sandbox tier: `SandboxSession.start_bus_only()` gives it a
private bus and the dconf-service that bus activates, and that is the whole
requirement. No shell, no compositor, no seat, seven seconds.

That distinction is the point. Until it was drawn (review-report M20), the only
assertions that the two backends *write* alike sat behind the `sandbox` marker,
so every check anyone actually ran — plain `pytest`, both CI jobs, the packaged
`check()` — proved they agreed on reads and nothing more.

### Tier 4 — sandbox

This is the one that makes the difference between "the tests pass" and "the app
works".

It boots a **real GNOME Shell** — `gnome-shell --headless --virtual-monitor
1920x1080` — on a private D-Bus session, runs gtheme inside it, walks all
fifteen pages, photographs each one in light and dark, and proves after every
single test that the live desktop was not touched.

A red sandbox is a red check. `verify.sh` never wraps it in `|| true`.

```sh
.venv/bin/python -m pytest -q -m sandbox
```

## Why the sandbox exists at all

The obvious approach — set `XDG_CONFIG_HOME` to a temporary folder and run the
tests — **does nothing**. A settings write goes over D-Bus to the dconf service
that is *already running*, which has the real `XDG_CONFIG_HOME`, and the value
lands in the real store.

Isolation comes from `dbus-run-session`: a fresh bus activates a *fresh* dconf
service, which inherits the sandbox environment. Both halves are required, and
the environment has to be set **on the `dbus-run-session` invocation itself**,
not exported inside it. `SandboxSession` refuses to continue if the bus address
it gets back equals the real one.

### The canary

Around **every** test in that directory, automatically, a fixture records the
live desktop before and after:

| What | Why |
|---|---|
| `~/.config/dconf/user` mtime and size | a write that reached the real dconf service touches it, even if the value written happened to match |
| live `org.gnome.shell enabled-extensions` | byte for byte |
| `~/.local/share/gnome-shell/extensions` | recursive content hash |
| `~/.local/share/gnome-shell/extension-updates` | staged updates |
| `~/.local/share/backgrounds` | wallpapers the app copies into |
| `~/.local/state/gtheme` | restore points and the ownership ledger |
| `~/nightbloom/ghostty` | what `~/.config/ghostty` is a symlink into on the development machine |

Symlinks are recorded and never followed, so *replacing a link* is visible.

A canary that cannot fail is decoration, so two tests exist to prove it can:
`test_isolation.py::test_the_canary_would_actually_notice` deliberately writes,
and `tests/unit/test_harness_canary.py` tests the canary's logic in the tier
that always runs.

### Two data modes

| Fixture | `XDG_DATA_HOME` | Use for |
|---|---|---|
| `sandbox_shared_data` | the user's real one, **read-only** | rendering, page walks, screenshots — seeing the real machine is the point |
| `sandbox_private_data` | private, seeded with the committed fixture corpus | anything that installs, enables, stages or uninstalls an add-on |

If a test could write extension state, it uses the private one. There is no
third option.

### What the sandbox proves that nothing else can

- **Isolation.** The live desktop is byte-for-byte unchanged by a full run.
- **The runtime-load verdict.** GNOME Shell scans its extension directories
  once, at start-up, and an extension installed after that is never discovered
  — proven by experiment, not assumed, and pinned as a permanent regression so
  that a future GNOME which changes it makes the suite fail rather than leaving
  the app quietly pessimistic.
- **That the app actually starts**, maps a window, lists fifteen pages, and can
  be photographed.

Real dconf round-trips used to be on that list. They are not any more, and that
is an improvement: they need a bus, not a shell, so they moved to the `dconf`
tier and now run everywhere.

## The two honesty gates

`verify.sh --full` runs two more things after the sandbox tier, and both exist
because a green test run is not the same as a true one.

### Screenshots (`tools/check_screenshots.py`)

The page walk writes thirty PNGs. This refuses to believe them.

The failure it exists to catch is not "the screenshots are missing" — that one
announces itself. It is the quiet one: the walk ran, every command answered ok,
thirty files were written, and every one of them is a picture of the same
thing. That happens for real reasons. A window that never got keyboard focus
renders every page identically. A page that raised on import shows a stand-in.
A colour scheme that was requested and not applied gives fifteen "dark"
pictures that are the light ones again. Each of those produces a green run and
a README full of lies.

So the checks are about what the pictures *are*:

- every one is newer than the run that claimed to take it (`verify.sh` stamps
  the start time before the walk);
- every one is a real PNG of a plausible size and the right width;
- the fifteen light pictures are all different from each other;
- each page's light and dark pictures differ;
- none is a flat rectangle, which is what a window that never painted produces.

### The live desktop (`tools/check_live_baseline.sh`)

Re-captures the state of the real desktop and diffs it against a stored
baseline. The baseline is personal configuration and deliberately lives outside
this repository, so the gate runs only when `GTHEME_BASELINE_DIR` points at it.

If that variable is set and the script is missing, `verify.sh` **fails** rather
than skipping. A silently skipped safety check is worse than none at all.

## Why CI proves less than the local check

This is stated here, in the CI file, and in the README of the sandbox
directory, because it is the kind of thing people forget.

**CI never runs the sandbox tier.** It has no GNOME Shell to boot, no seat, and
nothing that would make the isolation guarantee meaningful. So CI cannot tell
you that the app starts, that the pages render, that the extension runtime-load
verdict still holds, or that the screenshots in the README are of anything.

It *can* tell you that a settings round-trip survives a real dconf, and does:
the `dconf` tier needs a private bus and no shell, so both jobs run it.

**CI's unit job runs on an older desktop stack than users have.** Ubuntu
runners ship libadwaita 1.5 against gtheme's 1.9 target, so no widget code runs
in that job at all. The Arch container job exists to close that gap for the
`gtk` tier, and it is the only place in CI where a libadwaita widget is
constructed.

**What CI does prove** is worth having and is not nothing: the lint is clean,
the engine is correct against a memory backend, every one of the version 1
defect-tag regressions still holds, the descriptor corpus loads and speaks
plain language, the coverage manifest accounts for every setting, the published
schemas match the models, and the widgets build.

Treat a green CI badge as "nothing obviously broke". Treat `./verify.sh --full`
on a real GNOME machine as the check that decides whether something ships.

## Running one thing

```sh
.venv/bin/python -m pytest tests/regression -q            # the defect-tag suite
.venv/bin/python -m pytest -q -m gtk                      # widgets only
.venv/bin/python -m pytest -q -m dconf                    # the real-dconf tier
.venv/bin/python -m pytest -q -k jargon                   # by name
.venv/bin/python -m pytest -q -m sandbox tests/sandbox/test_isolation.py
```

While building a page, iterate against the broadway variant rather than a full
shell: it starts in about a second instead of sixty to ninety. It cannot tell
you anything about the top bar, add-ons or screenshots, which is exactly the
trade.

## Before you open a pull request

```sh
./verify.sh
```

If you touched anything the app draws, or anything the engine writes, run
`./verify.sh --full` on a real GNOME 49/50 machine and say in the pull request
that you did. If you cannot — no GNOME to hand — say that instead. An honest
"I could not run the sandbox tier" is useful; a silent omission is not.
