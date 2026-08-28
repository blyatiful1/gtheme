# The Look format (version 2)

A **Look** is a folder containing a `theme.toml` and the files it wants to
install. It changes settings and copies files. It cannot contain a program and
gtheme cannot run one — see [SECURITY.md](../SECURITY.md).

Two halves to this document:

- [**Authoring guide**](#authoring-guide) — write one, start to finish, with a
  complete worked example.
- [**Reference**](#reference) — every field, generated from the models that
  define them.

---

## Authoring guide

### The folder

```
my-look/
├── theme.toml                  the only required file; the name is fixed
├── README.md                   optional, and worth writing
├── wallpaper/
│   └── evening.png
└── ghostty/
    └── config
```

The **folder name** is the Look's identifier, and it must match `meta.name`.

Put your Look in `~/.local/share/gtheme/v2/themes/` to have gtheme find it, or
point `gtheme validate` at it wherever it is. Looks you install there win over
bundled ones of the same name.

### Check it as you go

```sh
gtheme validate my-look
```

It either prints `my-look: looks fine.` or one line per problem, naming the
field. Run it after every edit; the format rejects anything it does not
recognise, so a typo in a field name is an error you see rather than a line
that quietly does nothing.

### A worked example

Here is a complete, small, real Look: a warm evening desktop that changes the
background, the colours, the text, one terminal and two add-ons.

```toml
# EVENING — a small worked example for docs/preset-format.md.
format = 2

[meta]
name = "evening"                       # must equal the folder name
title = "EVENING — low amber"
description = "Warm amber on a deep brown desk. Dark, low contrast, no glare."
author = "your-name-here"
version = "1.0.0"
min_shell = "49"                       # built against GNOME 49; not a hard block
screenshots = ["wallpaper/evening.png"]

# Named colours. gtheme does not interpret these; they are here so that
# templated files can use them and so the app can show swatches.
[palette]
bg      = "#1B1512"
surface = "#241C18"
amber   = "#E0A55C"
text    = "#EFE6DA"

# ---------------------------------------------------------------- files
# Copied, in order, BEFORE any setting is written. Sources are relative to
# this folder; destinations are absolute or start with ~/.
[[files]]
src = "wallpaper/evening.png"
dest = "~/.local/share/backgrounds/evening/evening.png"

[[files]]
src = "ghostty/config"
dest = "~/.config/ghostty/config"
template = true                        # fill in {{ }} tokens on the way past

# ------------------------------------------------------------- settings
# Values are GVariant text: a string is quoted INSIDE the TOML string.
[[settings]]
key = "gsettings:org.gnome.desktop.background picture-uri-dark"
value = "'file:///home/you/.local/share/backgrounds/evening/evening.png'"
component = "wallpaper"

[[settings]]
key = "gsettings:org.gnome.desktop.interface color-scheme"
value = "'prefer-dark'"
component = "colors"

[[settings]]
key = "gsettings:org.gnome.desktop.interface gtk-theme"
value = "'adw-gtk3-dark'"
component = "colors"

[[settings]]
key = "gsettings:org.gnome.desktop.interface accent-color"
value = "'orange'"
component = "colors"

[[settings]]
key = "gsettings:org.gnome.desktop.interface font-name"
value = "'Adwaita Sans 11'"
component = "fonts"

# ------------------------------------------------------------ add-ons
[extensions]
enable = [
    "blur-my-shell@aunetx",
    "impatience@gfxmonk.net",
]

[[extensions.install]]
uuid = "blur-my-shell@aunetx"
source = "ego"
ego_pk = 3193                          # its number on extensions.gnome.org

[[extensions.install]]
uuid = "impatience@gfxmonk.net"
source = "ego"
ego_pk = 277

[[extensions.settings]]
uuid = "impatience@gfxmonk.net"
schema_id = "org.gnome.shell.extensions.net.gfxmonk.impatience"
key = "speed-factor"
value = "0.7"
```

Notes on that file, in the order the mistakes usually happen:

**The wallpaper location is written twice**, once as a file destination and
once as the setting that points at it. There is no way around that: the setting
holds a URI, and it is a separate fact from the copy. Write the full path; do
not use `~` inside a setting value, because GNOME will not expand it.

**`value` is GVariant text, not a Python value.** A string setting takes a
quoted string *inside* the TOML string: `value = "'prefer-dark'"`, with both
kinds of quote. A number is bare: `value = "0.7"`. A boolean is `"true"`. An
empty list of strings is `"@as []"` — not `"[]"`, which has no type and cannot
be written at all.

**`component` decides how the change is described, never what is written.** It
is what lets the preview dialog say "Wallpaper, highlight colour, icons, and 3
add-ons" instead of listing setting names at somebody. Pick the closest one
from the [component list](#components); `other` is legal and dull.

**Every add-on named anywhere must appear in `extensions.enable`.** An
`[[extensions.install]]` or `[[extensions.settings]]` block for something not
in that list is a validation error, because it would silently do nothing.

**`ego_pk` is the number in the add-on's address on extensions.gnome.org** —
`https://extensions.gnome.org/extension/277/impatience/` → `277`. Without it
gtheme can still find the add-on by searching, but with it the install offer is
exact.

### The four ways to address a setting

`key` is one string. Four forms, and the third and fourth exist for real add-ons
that needed them:

```
gsettings:org.gnome.desktop.interface color-scheme

dconf:/org/gnome/shell/extensions/blur-my-shell/panel/blur

gsettings-path:org.gnome.shell.extensions.burn-my-windows-profile:/org/gnome/shell/extensions/burn-my-windows/profiles/1/ name

keyfile:/home/you/.config/burn-my-windows/profiles/123.conf:org.gnome.shell.extensions.burn-my-windows-profile:/burn-my-windows/profile/ fire-enable-effect
```

Prefer `gsettings:` whenever the setting has a definition — that is what gives
gtheme the type information that makes an exact undo possible. `dconf:` is the
last resort: with no definition there is no type, so values are handled purely
as text.

### Templates and `{{ }}` tokens

Set `template = true` on a file and gtheme fills in `{{ token }}` before
writing. Two tokens exist today:

| Token | What it becomes |
|---|---|
| `{{ home }}` | your home folder, with no trailing slash |
| `{{ ptyxis_default_profile }}` | the Ptyxis terminal's default profile identifier, which is generated on that machine's first run and cannot be written down in advance |

Tokens work in `key` and `value` too, which is the point of the second one:

```toml
[[settings]]
key = "dconf:/org/gnome/Ptyxis/Profiles/{{ ptyxis_default_profile }}/palette"
value = "'Evening'"
component = "terminal"
```

If a token cannot be resolved on the machine applying the Look, that one
operation is **skipped with a sentence explaining why** — never written
half-resolved, and never a crash. That holds for a token in the `value` just as
much as one in the `key`: a mistyped `{{ hoem }}` in a wallpaper location skips
the setting rather than pointing the desktop at a file with braces in its name.
A path with an empty component (`/Profiles//palette`) is exactly the kind of
damage the check exists to stop.

Templating a file that is not text is an error rather than a mangled write.
Leave `template` off for pictures.

### Merging into a list instead of replacing it

One setting needs it, and it is important:

```toml
[[settings]]
key = "gsettings:org.gnome.shell enabled-extensions"
value = "['blur-my-shell@aunetx']"
merge = "list-union"
component = "addons"
```

Without `merge = "list-union"`, applying that Look switches off every add-on
the user turned on themselves, which they experience as *the app deleted my
dock*. With it, the Look's entries are added and the rest are left alone — and
the record taken before the change still holds the exact previous list, so undo
puts back what was actually there.

In practice you rarely write this by hand: put your add-ons in
`[extensions] enable` and gtheme compiles the union for you.

### Add-ons a Look may want

```toml
[extensions]
enable = ["ding@rastersoft.com", "my-private-thing@example.local"]

[[extensions.install]]
uuid = "ding@rastersoft.com"
source = "ego"
ego_pk = 2087
alternates = ["gtk4-ding@smedius.gitlab.com"]   # same job; whichever is present wins

[[extensions.install]]
uuid = "my-private-thing@example.local"
source = "local-only"        # never offered for download; may not be bundled
```

- `source = "ego"` — gtheme offers to fetch it from extensions.gnome.org
  through the desktop's own installer, with the desktop's own confirmation box.
- `source = "local-only"` — a private add-on. If it is not already installed,
  the Look is applied without it and the user is told, in plain words, which
  part will therefore not work. **A Look must never ship add-on code.** That is
  what keeps the security promise true.
- `alternates` — other identifiers that satisfy the same need. The first one
  present on the machine wins.

For settings that belong to an add-on, use `[[extensions.settings]]` rather
than a raw `dconf:` key. It is addressed by `(schema_id, key)`, because several
add-ons split their settings across child definitions — blur-my-shell has
eight, and `blur` means something different in each.

### Publishing

To be listed in the community index a Look needs **at least one screenshot**.
The check lives in `tools/build_index.py`, not in the model, because the same
model also describes saved moments, which are written by machine from a desktop
that may have no picture to photograph. Publishing is the gate a Look actually
crosses:

```sh
./.venv/bin/python tools/build_index.py           # rewrite themes/index.json
./.venv/bin/python tools/build_index.py --check   # what the test suite runs
```

An unpreviewable Look is exactly what this app exists to spare people, so the
requirement is real.

### Converting a version 1 theme

`src/gtheme/preset/v1_import.py` does it: `convert_dir` reads a version 1 theme
folder, `convert_v1` converts an already-parsed one, and `write_look` writes the
result out as a version 2 folder. All three hand back a `ConversionResult`
carrying the converted Look **and** the list of warnings.

Version 1 files do not stay valid, deliberately. That format had a `[[hooks]]`
section that ran shell scripts, and version 2 has neither the section nor any
machinery to execute one. Conversion is therefore lossy, and every loss is
named: each hook produces its own warning saying what that hook used to do,
folders used as file sources are called out, and required packages, fonts and
third-party tools are listed as things the user must install themselves.
Nothing is dropped silently.

### What a Look cannot do

- Run a program, a script, or a command. There is no field for it.
- Write outside your home folder. Every destination is resolved — through `..`
  and through symbolic links — and refused if it escapes, before anything is
  written.
- Read outside its own folder. Sources are resolved the same way, so a symbolic
  link cannot be used as a siphon — checked when the Look is compiled *and*
  again before the bytes are read.
- Write somewhere that arranging a file *is* arranging for a program to run.
  The list lives in `src/gtheme/core/policy.py` and is refused outright:
  `~/.config/autostart`, `~/.config/systemd`, `~/.config/environment.d`,
  `~/.local/bin`, `~/bin`, `~/.local/share/gnome-shell/extensions`, the shell
  start-up files (`.bashrc`, `.zshrc`, `.profile`, `config.fish`, fish's
  `conf.d`), and anything ending `.desktop` or `.service` anywhere.
- Change a setting that decides what the desktop *runs*: a custom shortcut's
  `command` or `binding`, `org.gnome.desktop.default-applications.*.exec`,
  `org.gnome.desktop.session session-name`, a `keyfile:` key (which would name
  the file to write into), or a `dconf:` location outside the add-on trees —
  `/org/gnome/shell/extensions/`, `/org/gnome/Ptyxis/` and
  `/io/github/jeffshee/hanabi-extension/`.

  A Look asking for any of these does not apply at all — not "minus that
  entry". Each one is named in the preview before anything happens.
- Hide a file that can start a program inside a count. A Look **may** write a
  program's own settings file whose format can also name a command —
  `~/.config/starship.toml` is the shipped example, and three of the four
  bundled Looks write it — but every such destination is listed by name in the
  preview instead of being folded into "23 files".
- Give itself privileges. A `mode` is honoured with the setuid, setgid and
  sticky bits masked off.
- Be applied without a record being taken first, or survive its own failure —
  any error rolls the whole thing back.

---

## Reference

The machine-readable version of everything below is
[`docs/schema/preset-v2.schema.json`](schema/preset-v2.schema.json). It is
**generated** from the models in `src/gtheme/preset/model.py` by
`tools/gen_schema.py`, and a test regenerates it in memory and fails if the
committed file has drifted — so it cannot fall behind the code. Point your
editor at it and get completion and inline errors while you write.

```sh
./.venv/bin/python tools/gen_schema.py            # write
./.venv/bin/python tools/gen_schema.py --check    # exit 1 if stale
```

Every table below is generated from those same models. Unknown fields are
rejected everywhere: the models are strict, so a misspelling is an error you
see rather than a line that is quietly ignored.

### Top level

| Field | Type | Required | Notes |
|---|---|---|---|
| `format` | `2` | yes | Always 2. Version 1 files are converted, not accepted. |
| `meta` | table | yes | See below. |
| `palette` | table of `name = "#RRGGBB"` | no (default empty) | Not interpreted by gtheme; available to templated files and shown as swatches. |
| `files` | array of tables | no (default empty) | Applied **before** settings. |
| `settings` | array of tables | no (default empty) | |
| `extensions` | table | no (default empty) | |

### `[meta]`

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string matching `^[a-z0-9][a-z0-9._-]*$` | yes | Must equal the folder name. |
| `title` | string | yes | What the user sees. |
| `description` | string | yes | One or two sentences; shown on the tile. |
| `author` | string | yes | |
| `version` | string | yes | Your own versioning; gtheme only compares it for updates. |
| `min_shell` | string or absent | no (default absent) | Lowest GNOME major version this was built against, as a string (`"49"`). Compared numerically against the version this desktop reports. It never *blocks*: the Look is compiled with the warning "this Look was made for a newer version of GNOME … parts of it may not apply" alongside its other warnings. On a desktop whose version cannot be read, nothing is claimed either way. |
| `screenshots` | array of strings | no (default empty) | Paths relative to the Look's folder. Empty is allowed here and refused at publish time. |

### `[[files]]`

| Field | Type | Required | Notes |
|---|---|---|---|
| `src` | string | yes | Relative to the Look's folder. One file per entry — a folder is not a source. |
| `dest` | string | yes | Absolute, or starting `~/`. Confined to your home folder. |
| `mode` | string matching `^0[0-7]{3}$` | no (default absent) | Octal, e.g. `"0644"`. setuid/setgid/sticky are masked off. |
| `template` | boolean | no (default `false`) | Fill in `{{ }}` tokens. Text files only. |
| `merge` | `"none"` | no (default `"none"`) | Files are replaced whole. The field exists so that a future merge strategy is an added value rather than a format break. |

### `[[settings]]`

| Field | Type | Required | Notes |
|---|---|---|---|
| `key` | string | yes | One of the [four address forms](#the-four-ways-to-address-a-setting). |
| `value` | string | yes | GVariant text, exactly as GLib prints it. |
| `merge` | `"none"` or `"list-union"` | no (default `"none"`) | `list-union` adds to a list of strings instead of replacing it. |
| `component` | one of the [components](#components) | no (default `"other"`) | How the change is described, never what is written. |

### `[extensions]`

| Field | Type | Required | Notes |
|---|---|---|---|
| `enable` | array of strings | no (default empty) | Every add-on this Look wants switched on. Anything named elsewhere must be in here. |
| `install` | array of tables | no (default empty) | Where an add-on comes from, when it is not already present. |
| `settings` | array of tables | no (default empty) | Settings belonging to those add-ons. |

### `[[extensions.install]]`

| Field | Type | Required | Notes |
|---|---|---|---|
| `uuid` | string | yes | Must appear in `enable`. Never shown to the user. |
| `source` | `"ego"` or `"local-only"` | no (default `"ego"`) | `ego` may be offered for download; `local-only` must already be present, and its absence is a named skip rather than an error. |
| `ego_pk` | integer or absent | no (default absent) | The number in the add-on's extensions.gnome.org address. |
| `alternates` | array of strings | no (default empty) | Other identifiers that do the same job; the first present one wins. |

Two entries for the same `uuid` is an error.

### `[[extensions.settings]]`

| Field | Type | Required | Notes |
|---|---|---|---|
| `uuid` | string | yes | Must appear in `enable`. |
| `schema_id` | string | yes | Which of the add-on's setting groups this key belongs to. |
| `key` | string | yes | |
| `value` | string | yes | GVariant text. |
| `path` | string or absent | no (default absent) | For add-ons whose settings have no fixed location (burn-my-windows profiles). Must start and end with `/`. |

### Components

The closed set `component` may take. It is closed so the preview can be
exhaustive — every change a Look makes has to fall into one of these buckets,
which is what lets the dialog summarise instead of enumerate.

`wallpaper` · `colors` · `icons` · `cursor` · `fonts` · `shell-theme` ·
`topbar` · `windows` · `workspaces` · `animations` · `night-light` · `sound` ·
`power` · `terminal` · `addons` · `privacy` · `accessibility` · `other`

### Order of operations

1. Everything is checked — confinement of every source and destination, before
   the first byte moves.
2. A saved moment is taken.
3. `files` are written, in the order they appear.
4. `settings` are written.
5. Add-ons are switched on (and offered for install if missing).

Files before settings is part of the format, not an implementation detail: a
Look that installs a top bar style and then selects it by name has to write the
file first, or the selection names something that is not there yet.

## See also

- [CONTRIBUTING.md](../CONTRIBUTING.md) — getting your Look into the built-in
  collection.
- [docs/architecture.md](architecture.md) — what happens to a Look after it
  loads.
- The four bundled Looks under [`themes/`](../themes) are the best worked
  examples there are, and each has its own `README.md` naming anything from the
  original that did not survive the conversion.
