# Contributing to gtheme

Most of what gtheme can do is **data**, not code. Adding a control, describing
an add-on's settings, or shipping a whole new desktop appearance are all edits
to text files, and none of them requires you to touch Python.

This document covers the four common contributions, easiest first:

1. [Add a Look](#1-add-a-look)
2. [Add a settings row to an existing page](#2-add-a-settings-row)
3. [Add a curated add-on panel](#3-add-a-curated-add-on-panel)
4. [Change code](#4-change-code)

If you are new to all of this, [docs/start-here.md](docs/start-here.md) covers
terminals and copy-pasting, and [GLOSSARY.md](GLOSSARY.md) covers the words.

---

## Setting up

```sh
git clone https://github.com/blyatiful1/gtheme
cd gtheme
uv venv --system-site-packages .venv
uv pip install -e '.[dev]'
./bin/gtheme                # run it straight out of the checkout
```

`--system-site-packages` is required. PyGObject, GTK 4 and libadwaita come from
your distribution's packages, never from pip.

Before you open a pull request:

```sh
./verify.sh
```

See [docs/testing.md](docs/testing.md) for what that runs and when you need
`--full` instead.

## The house rules

Four, and they apply to every contribution including one-line ones.

**1. Plain language, enforced.** `src/gtheme/ui/jargon.py` holds a list of
words no user-facing string may contain, and tests check every page title,
every row title and every row subtitle against it. `dconf`, `gsettings`,
`schema`, `uuid`, `shell`, `GTK`, `hinting`, `titlebar` and about ninety others
are refused. Say **add-on**, not "extension"; **top bar**, not "shell";
**highlight colour**, not "accent colour". The list is not there to make the
app fold — the reader has never used Linux, and every banned word is one they
would have to look up.

**2. Every row needs a subtitle, and it is a real sentence.** Not a restatement
of the title. If a setting cannot be explained in one sentence to someone who
has never used Linux, it belongs behind `advanced = true` — or it does not
belong.

**3. Warnings say the consequence, not the mechanism.** "Your top bar may
disappear until you log back in", never "conflicts with the panel actor
override". A test checks this.

**4. Never leave a control that visibly moves and does nothing.** If a setting
is inert until another one changes, use `requires_first` so gtheme writes both,
and say so in the explanation.

---

## 1. Add a Look

A Look is a folder with a `theme.toml`. The format, field by field, with a
complete worked example, is in
[docs/preset-format.md](docs/preset-format.md).

The short version:

```sh
mkdir -p themes/my-look
$EDITOR themes/my-look/theme.toml
gtheme validate themes/my-look
```

To have it bundled with gtheme, it also needs:

- **At least one screenshot**, listed in `meta.screenshots`. Enforced at
  publish time by `tools/build_index.py`, not by the format — an unpreviewable
  Look is exactly what this app exists to spare people.
- **A `README.md` in the Look's folder** naming anything from your original
  desktop that did *not* come across, and why. The four bundled Looks all have
  one. This matters more than it sounds: a Look that quietly delivers two
  thirds of what its screenshot shows is how people stop trusting the whole
  collection.
- **Regenerate the index** and commit the result:

  ```sh
  ./.venv/bin/python tools/build_index.py
  ```

  `tools/build_index.py --check` runs in the test suite, so an index that has
  drifted from the Looks beside it fails the canonical check rather than
  shipping.

Two things a Look may never do: bundle add-on code (name the add-on and let
gtheme fetch it from extensions.gnome.org), or contain anything executable.
There is no field for the second one and there never will be.

Wallpapers ship in the repository rather than being fetched at apply time —
one-click Looks beat remote downloads. Keep them to what you need; the four
bundled Looks are about 40 MB between them and that is the budget.

## 2. Add a settings row

Every control in the app is a row in a `.toml` file under `data/domains/` (core
GNOME) or `data/panels/` (one file per add-on). You are adding one entry.

### Find the right file

`data/domains/` is one file per area: `style.toml`, `fonts.toml`,
`wallpaper.toml`, `topbar.toml`, `windows.toml`, `power.toml`, `sound.toml`,
`nightlight.toml`, `privacy.toml`, and so on. The file's `id` is the page its
rows appear on.

### Write the row

```toml
[[rows]]
schema_id = "org.gnome.desktop.interface"
key = "clock-show-weekday"
title = "Show the day of the week"
subtitle = "Puts Monday, Tuesday and so on next to the clock in the bar at the top."
synonyms = ["weekday", "day", "clock", "date"]
kind = "toggle"
```

| Field | |
|---|---|
| `schema_id`, `key` | Which setting this is. Always both — several add-ons reuse a key name across different setting groups, and the name alone is ambiguous. |
| `title` | What the user sees. Plain language, checked by the lint. |
| `subtitle` | **Mandatory.** One sentence saying what it does, to someone who has never used Linux. Also checked by the lint. |
| `synonyms` | The words people actually type into search — including the wrong ones. `taskbar`, `start menu`, `wallpaper`, `dark mode`, `make text bigger`. Deliberately **not** lint-checked, because their whole job is to catch the vocabulary the app refuses to use. |
| `kind` | `toggle`, `slider`, `choice`, `text`, `color`, `picker`, `dict_slider`, `shortcut`, `effect-picker`, `effect-speed`, `link`. |
| `clamp_min`, `clamp_max`, `step` | For sliders. Please set bounds — GNOME's own settings frequently have none, and will happily accept a night-light start hour of forty. |
| `choices` | For `choice`: a list of `{ value, label, subtitle }`. |
| `requires_first` | A list of `{ schema_id, key, value, explain }` written *before* this one. This is how a control that would otherwise be inert becomes honest. |
| `advanced` | `true` folds the row into the collapsed Advanced section. |
| `warn` | A consequence sentence, shown as a banner. |
| `reset` | Defaults to `true` — the row gets a "put this back" button. |
| `path`, `keyfile`, `dict_key`, `link_target` | For the awkward cases; copy an existing example. |

### Then dispose of the key

`data/domains/coverage.toml` accounts for **every** setting a GNOME 50 desktop
has — 554 of them, read off a live machine into `data/domains/universe.txt`.
Each carries exactly one disposition, and a key with none fails the test suite.
If your new row surfaces a key that was previously on the floor page, change
its line:

```toml
"org.gnome.desktop.interface:clock-show-weekday" = "surfaced(topbar)"
```

The five dispositions are `surfaced(<page>)`, `compound(<op>)`, `floor`,
`excluded(<reason>)` and `delegated(<who>)`. The last two are deliberately hard
to use: `excluded` accepts three reason codes and nothing else, and `delegated`
only appears on a committed allowlist, each entry with a written justification.
That is on purpose — the app's surface must not be quietly narrowed by someone
who did not want to write a subtitle.

### Check it

```sh
./.venv/bin/python -m pytest -q -k "domains or jargon or coverage"
./verify.sh
```

## 3. Add a curated add-on panel

Twenty-four popular add-ons have a hand-written settings panel, so their
options are explained in the same voice as everything else in the app. Add-ons
without one still work — they get a generic panel built from their own settings
definitions, labelled "these settings come from the add-on author". A curated
panel is an upgrade, not a requirement.

One file, `data/panels/<add-on>.toml`:

```toml
# Impatience — one slider over the speed of every desktop animation.
id = "impatience"

[target]
uuids = ["impatience@gfxmonk.net"]
ego_pk = 277
schema_id = "org.gnome.shell.extensions.net.gfxmonk.impatience"
category = "looks"
summary = "Speeds up (or slows down) every sliding and fading movement on the desktop with a single slider."

[[rows]]
schema_id = "org.gnome.shell.extensions.net.gfxmonk.impatience"
key = "speed-factor"
title = "Animation speed"
subtitle = "One means normal. Below one everything moves faster; above one everything takes longer."
synonyms = ["animation", "speed", "faster", "snappy", "slow"]
kind = "slider"
clamp_min = 0.1
clamp_max = 4.0
step = 0.05
```

`[target]` fields:

| Field | |
|---|---|
| `uuids` | Every identifier this panel covers. Some add-ons have been renamed; list both. |
| `alternates` | Different add-ons that do the same job and share this panel (ding and gtk4-ding). |
| `ego_pk` | The number in the add-on's extensions.gnome.org address. |
| `schema_id` | Its main settings group. |
| `child_schemas` | Additional groups. blur-my-shell has eight. |
| `schema_by_uuid` | When alternates use different group names. |
| `relocatable_path_template` | For add-ons whose settings have no fixed location — burn-my-windows profiles are why this exists. |
| `conflicts` | Identifiers this add-on fights with. gtheme then offers them as either/or with a "this replaces X — turn X off?" |
| `category` | One of: `looks`, `layout`, `getting things done`, `system`, `system readings`, `phones and devices`. |
| `summary` | One sentence, plain language, saying what the add-on does. This is the line the user reads in the Add-ons list. |
| `warn` | A consequence sentence for known-bad combinations. |

**Get the settings group names from the add-on's own files**, by reading
`schemas/*.gschema.xml` inside it. Do not trust `metadata.json`'s
`settings-schema` field — four of the curated add-ons omit it — and do not
trust filenames: clipboard-history ships its settings file named after a
*different* add-on. There is a committed corpus of these files under
`tests/fixtures/schemas/` and a test that every row in your panel resolves
against it.

If your add-on is not in that corpus yet, `tools/fetch_schema_fixtures.py`
fetches it. Commit what it downloads, including the manifest entry.

Then:

```sh
./.venv/bin/python -m pytest -q -k panels
```

## 4. Change code

Read [docs/architecture.md](docs/architecture.md) first — in particular the two
layering rules, because both are enforced by tests and neither is obvious:

- **Nothing under `core/` may import GTK or libadwaita.** `gtheme rescue` runs
  on a computer with no graphical session at all.
- **Nothing above `core/` constructs a settings backend.** The choice lives in
  `core/backends.py` behind `use_backend()`, which is also the seam that lets
  the whole test suite write nowhere real.

Three more things worth knowing before you start:

**Contracts marked frozen are frozen.** `core/transaction.py`,
`core/settings_backend.py`, `preset/model.py`, `panels/descriptor.py` and
`ui/registry.py` each say so at the top. Field names in those files are the
on-disk format or the interface seven other modules code against. Changing one
is a real change with a real migration, not a rename.

**Undo has exactly one implementation.** Applying a saved moment builds an
ordinary transaction and goes down the identical path. If you find yourself
writing a second restore path, stop: it would be the least-exercised code in
the app and the code that has to work on the worst day anyone has.

**Add the regression test before the fix.** That is how the version 1 defect
tags became `tests/regression/test_legacy_defects.py`, and it is the reason a
full rewrite did not reintroduce a single one of them.

### Pull requests

- One thing per pull request.
- `./verify.sh` green, and say so.
- If you touched anything the app draws or the engine writes, run
  `./verify.sh --full` on a real GNOME 49/50 machine and say that you did. If
  you could not, say that instead — an honest "I could not run the sandbox
  tier" is useful information; a silent omission is not.
- Update [CHANGELOG.md](CHANGELOG.md) for anything a user would notice.
- New user-facing strings: run the lint. It will find you anyway.

## Reporting bugs

Open an issue at <https://github.com/blyatiful1/gtheme/issues> with your distro,
your GNOME version (**Settings → System → About**), what you did, what
happened, and what you expected.

**Security problems go privately first** — see [SECURITY.md](SECURITY.md).

## Licence

MIT. By contributing you agree your contribution is licensed the same way.
