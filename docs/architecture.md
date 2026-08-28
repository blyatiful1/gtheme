# How gtheme is put together

This document is for contributors, and it uses the precise names of things.
The app's own surface never does — see [the jargon rule](#the-jargon-rule)
below for why that is enforced rather than encouraged.

If you are here to add a Look, a settings row or an add-on panel, you probably
want [CONTRIBUTING.md](../CONTRIBUTING.md) instead; almost all of that work is
data, not code.

---

## The shape

```
                       ui/pages/*.py          fifteen pages, one file each
                            │                 (data-driven rows, no logic)
              ┌─────────────┼─────────────┬──────────────┐
              ▼             ▼             ▼              ▼
         preset/        panels/       system/          ego/
        (Looks, the   (descriptors,  (what is         (extensions.gnome.org
         registry,     the corpus,    installed on     and the desktop's own
         capture)      row building)  this machine)    install service)
              └─────────────┴─────────────┴──────────────┘
                                  │
                                  ▼
                             core/            the engine. No GTK, ever.
                     transaction · baseline · ledger
                     confine · atomic · lock · gvariant
                     placeholders · restorepoints · rescue
                                  │
                                  ▼
                        core/settings_backend.py
                    Gio  ·  subprocess  ·  memory (tests)
```

Two rules hold this apart, and both matter more than they look:

**`core/` never imports GTK or libadwaita.** `tests/unit/test_core_no_gtk.py`
walks the source of every module under `core/` and fails on a `Gtk` or `Adw`
typelib request, then proves at runtime that importing `core` pulls neither in,
and finally imports it with PyGObject removed from `sys.modules` altogether.
That last one is not pedantry: `gtheme rescue` runs on a computer whose
graphical session is dead, and it has to work there.

Gio and GLib *are* allowed in `core/`. The settings backend needs them, and
they have no display dependency.

**Nothing above `core/` constructs a settings backend.** `Transaction` takes no
backend argument; the choice lives in `core/backends.py` behind
`use_backend()`, which is also the test seam. `tests/conftest.py` hands the
whole engine a `MemoryBackend` and every test in the default tier writes
nowhere real. A page that built its own backend would sidestep that, and would
be the one piece of the app that could touch a live desktop from a unit test.

## Module map

### `core/` — the engine

| Module | What it owns |
|---|---|
| `transaction.py` | The only path by which anything changes. Operation types (`FileWrite`, `SettingWrite`, `ExtensionEnable`, `ExtensionInstall`), `plan() -> Diff`, `apply(progress_cb)`. Frozen signatures. |
| `baseline.py` | The pristine baseline: what a file or setting looked like the *first* time gtheme touched it. Never re-recorded, so "before gtheme" stays true forever. |
| `ledger.py` | Who owns what *now*. Answers a different question from the baseline, and confusing the two is how theme managers leave debris. Enables surgical Look-to-Look switching. |
| `confine.py` | The security boundary. `confine_dest` (where a file may land) and `confine_src` (where it may come from), both after resolving `..` and symbolic links. |
| `atomic.py` | Temp file → `fsync` → `os.replace` → `fsync` the directory. Replaces a symlink at the destination rather than writing through it. JSON state keeps a `.bak`. |
| `lock.py` | One gtheme at a time, non-blocking, with an honest message. |
| `gvariant.py` | The wire format. Exact GVariant text in, exact GVariant text out, no normalisation — plus canonicalising comparison, and the list-union that `enabled-extensions` needs. |
| `placeholders.py` | `{{ }}` tokens resolved from a probe registry at apply time, and the gate that refuses to write a half-resolved one. |
| `restorepoints.py` | Saved moments. Includes the read-only importer that turns version 1's baseline store into the "Before gtheme" point. |
| `rescue.py` | The headless "put it back" path. No GTK, no session, no window. |
| `settings_backend.py` | The frozen seam: one key grammar, four address forms, a typed error enum, three implementations. |
| `backends.py` | Which backend is in use, and `use_backend()` — the one supported override. |
| `paths.py` | Every root as a *function*, read from the environment on each call. Version 1 resolved them at import time, and a test that forgot to reload wrote to the real home. |
| `color.py` | Hex colour arithmetic, ported unchanged because the bundled Looks were authored against exactly this maths. |

### `preset/` — Looks

`model.py` is the on-disk format as strict pydantic models (`extra='forbid'`);
`loader.py` reads folders; `compile.py` turns a Look into a `Transaction`;
`capture.py` reads the current desktop back out — the same mechanism serving
both saved moments and "save my desktop as a Look"; `v1_import.py` converts
version 1 files, loudly; `registry.py` is the zero-server community list.

### `panels/` — controls as data

`descriptor.py` holds the frozen models every `.toml` under `data/panels/` and
`data/domains/` parses into. `loader.py` reads that corpus, collecting failures
rather than swallowing them, and is the single reader of `coverage.toml`.
`schema_probe.py` asks GLib whether a setting actually exists on this machine
so a row can grey itself honestly. `widgets.py` builds the row kinds the frozen
base library deliberately left unbuilt.

### `system/` — what is on this machine

Scanners for themes, icon sets, cursors, fonts, wallpaper catalogues, installed
extensions and thumbnails. All enumeration runs off the main thread with
results posted back through `GLib.idle_add`.

### `ego/` — extensions.gnome.org and the desktop's install service

`client.py` (paginated search, version-map filtering, cached), `install.py`
(the live install path and the fallback), `updates.py`, `shelldbus.py` (one
`ListExtensions` call and then live state changes, never polling).

### `terminal/` — one adapter per program

Ghostty, Ptyxis, Alacritty, fish, starship, btop, cava, fastfetch. Each carries
its own honest sentence about when the change becomes visible, and the page
renders those verbatim.

### `ui/` — the window

`registry.py` is the fifteen-page manifest, frozen, with lazy factory strings.
`rowindex.py` registers every row as it is built, which is what makes search
deep-links and external-change mirroring possible. `search.py`, `jargon.py`,
`onboarding.py`, `preview.py`, `applyrunner.py`, `widgets/rows.py`, and
`pages/`.

`widgets/` is where anything more than one page draws lives, so that there is
one of it rather than nine: `rows.py` (the frozen descriptor-to-widget
library, which also owns `key_for`, `set_plain_text` and the GVariant
`quote`/`unquote` pair), `recording.py` (every write, recorded and honest),
`explainer.py` (the one-shot first-visit banner) and `actions.py` (a sentence
with a button that does it). A page that finds itself writing one of these
again is the drift `review-report` P7 is about.

## The safety model

Seven properties. Each one is a mechanism, not an intention, and each one is
pinned by a named test.

**1. Confinement is checked for every operation before the first byte moves.**
Not per-operation as the transaction runs: a transaction that writes three
files and then discovers the fourth escapes the destination root has already
done damage. The preflight covers the whole plan.

**2. The pristine baseline is captured before the first mutation**, is written
incrementally and atomically as it goes, and is never re-recorded for something
already recorded. There is no "save at the end" call for a `SIGKILL` to skip,
which is what makes the crash-mid-apply guarantee real.

**3. The ownership ledger entry is written *before* the change it describes.**
A crash between the two leaves a ledger that over-claims rather than one that
under-claims. Over-claiming restores something already correct, which is
harmless; under-claiming orphans a change nothing knows how to revert.

**4. Applying is all-or-nothing.** Any failure rolls the whole transaction
back, and the error records whether the rollback succeeded so the UI can say
which of the two things happened.

**5. One code path serves preview and apply.** The dialog that says what will
change renders the same `Diff` object that `apply` consumes. A preview computed
by different code is a lie waiting to happen.

**6. Values round-trip as exact GVariant text.** gtheme does not know the type
of `org.gnome.desktop.interface font-name` and does not need to: it keeps the
string GLib printed and writes that string back. `@as []` stays `@as []`,
`@ms nothing` stays itself, and `'Cantarell 11 @wght=460'` comes back with its
axis intact. Golden round-trip tests run against a real dconf in the sandbox
tier, and the two real backends are asserted to agree.

**7. Undo is not a second engine.** A restore point is a Look. Applying one is
`restorepoints.apply_point`, which builds an ordinary `Transaction` and goes
down the identical path with the identical preflight, baseline, ledger and
rollback. A separate restore implementation would be the least-exercised code
in the application and the code that has to work on the worst day anyone has.

## The defect-tag regression suite

Version 1 of gtheme found, fixed and comment-tagged a set of bugs in its apply
engine. Version 2 is a rewrite, and a rewrite's characteristic failure is
reintroducing exactly those bugs. So before the new transaction layer was
written, each tag became a named test.

The tags were re-grepped from the legacy source rather than copied from a list
(DESIGN.md F9 asks for precisely that). They live in
`legacy-v1`'s `engine/apply.py`, `backup.py`, `paths.py` and `cli.py`, and
every one of them now has a test in
[`tests/regression/test_legacy_defects.py`](../tests/regression/test_legacy_defects.py):

| Tag | The bug it guards against |
|---|---|
| **AS4** | An apply where every operation was skipped recorded itself as applied. The desktop was unchanged and the app said otherwise — the one thing a tool whose whole promise is undo must never do. Two tests: nothing-applied claims nothing, and it does not discard ownership from earlier applies. |
| **AS5** | With no desktop session at all, the settings phase is skipped once, wholesale — not attempted per key and failed per key. |
| **AS8** | A setting this machine does not have is one skip with a reason, not a failed apply. And a skipped setting leaves no baseline record, because a record of something never changed would corrupt the undo. |
| **R1** | A restore that fails keeps its recovery state, so undo is still possible afterwards. |
| **R3** | Switching Looks forgets only what actually reverted. |
| **R4** | Ownership is claimed before the change it describes (property 3 above). |
| **R5** | A record can be *dead* (its stored copy is gone) as opposed to transiently unrestorable. The two are reported differently, because only one of them is worth retrying. |
| **R6** | A complete restore consumes the recording. Keeping it would stop the next apply from re-recording, and months later "undo" would revert a desktop the user had since edited by hand. |
| **F1** | A FIFO, socket or device node at a destination cannot be snapshotted, so it is never written over either. |
| **L1** | Two gthemes cannot mutate at once. Two `Baseline` objects that loaded the same blob counter would both write to slot `0007`, and the second would destroy the only pre-gtheme copy of the first one's file. |
| **X1** | A Look unions into `enabled-extensions` instead of replacing it. Overwriting it switches off every add-on the user turned on themselves, which they experience as "the app deleted my dock". Undo still restores the exact pre-union value. |
| **E1** | A destination root that is empty, relative or a filesystem root is refused outright. Otherwise every path is "inside the root" and confinement silently becomes a no-op. |

### H2 and R2 retired with the hooks system

Two tags in the legacy source have no test here, deliberately, and this is
where that is recorded.

- **H2** — a failed required pre-hook must block the apply.
- **R2** — a theme's recorded restore hooks must run before it is deleted.

Both are guards on hook machinery: version 1 let a theme name a shell script
and ran it. Version 2 has no hooks section in the format and no code that can
execute anything, which is the only way the sentence *"Looks only change
settings. They can't run programs on your computer."* is true rather than
aspirational.

"We deleted the test" is exactly what a regression suite exists to make
impossible, so the reasoning is worth stating plainly. Take R2: the version 1
bug was that removing a theme orphaned privileged changes its install hook had
made. In version 2 a Look cannot make a privileged change, because a Look
cannot run anything. **The class of bug is gone, rather than the check for
it.** The same argument covers H2 — there is no pre-hook to fail.

If a future version ever reintroduces script execution, these two tags are the
first tests that have to come back, and this section is the note explaining
why they were ever away.

## Data, not code

Three manifests do work that would otherwise be scattered through the UI, and
each of them turns a promise into something a test can check.

**`ui/registry.py`** — the fifteen pages, in order, as a frozen manifest with
lazy factory strings. The sidebar is built by walking it, so a page cannot
exist without appearing in the sidebar and cannot appear without existing. No
page author edits this file, which is why seven page agents could work in
parallel without a merge conflict.

**`data/domains/coverage.toml`** — every key of `data/domains/universe.txt`
(554 settings, read off a live GNOME 50 desktop) carries exactly one disposition
from a closed set: `surfaced(<page>)`, `compound(<op>)`, `floor`,
`excluded(<reason>)` or `delegated(<who>)`. An undispositioned key fails the
test. `excluded` accepts only three reason codes and `delegated` only an
allow-listed set with written justifications, so the app's surface cannot be
quietly narrowed by a contributor who did not want to write a row.

**`data/panels/*.toml` and `data/domains/*.toml`** — every control in the app,
as data. A row is a setting address, a plain-language title, a mandatory
plain-language subtitle, the words a user might search for, a widget kind and
its bounds. Adding a control is adding data.

The More Settings page is the other half of that promise: whatever the coverage
manifest dispositions `floor` renders there automatically, from the system's
own description, clearly labelled as system text. The test proves nothing was
forgotten; the page proves it to the person at the computer.

## The jargon rule

`ui/jargon.py` holds the banned-word list, and it is enforced, not encouraged.
`tests/unit/test_jargon.py` checks every page title, subtitle and section name;
`tests/unit/domains_jargon_test.py` checks every title and subtitle in the
whole descriptor corpus, refuses a row that leaks a setting name into what the
user reads, and refuses a warning phrased as a mechanism rather than as a
consequence.

Search synonyms are deliberately exempt: they exist to catch the words people
actually type, which include the wrong ones.

The list is not there to make the app fold. It is there because the reader has
never used Linux, and every banned word is one they would have to look up —
and looking it up is the failure. A person who has to search the web to
understand a checkbox has already been let down by the checkbox.

## The one platform fact that shapes the Add-ons page

GNOME Shell scans its extension directories **once**, at start-up. An extension
installed to disk after that is never discovered: appending it to
`enabled-extensions`, flipping the user-extensions toggle and relaxing version
validation all fail to load it, and there is no rescan route. This was measured
directly on GNOME Shell 50.4 rather than assumed.

Two consequences run through the code:

1. The only live-install path is asking the desktop to do it —
   `InstallRemoteExtension`, whose own downloader loads the extension directly,
   and whose modal dialog is the consent surface. The fallback path (download,
   unpack, merge into the enabled list) is honest that it finishes after a
   log-out.
2. The experiment is a permanent test, `tests/sandbox/test_runtime_load.py`, so
   that a future GNOME which changes this behaviour makes the suite fail rather
   than leaving the app quietly pessimistic.

## Further reading

- [docs/preset-format.md](preset-format.md) — the Look format, field by field.
- [docs/testing.md](testing.md) — the three tiers, and why CI proves less than
  the local check.
- [SECURITY.md](../SECURITY.md) — the boundaries, stated for users.
- [CONTRIBUTING.md](../CONTRIBUTING.md) — how to add a Look, a panel or a row.
