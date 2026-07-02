# gtheme

A GNOME desktop theme system: **download, apply, switch, and author** full-desktop
themes from a single palette. One declarative manifest per theme; the CLI snapshots
whatever it touches, so every theme is reversible without a hand-written undo script.

```sh
gtheme                      # ← just run it: an interactive arrow-key menu
gtheme list                 # what's available
gtheme apply nsx            # back up current state, apply the NSX theme
gtheme switch jojo          # swap themes (baseline preserved)
gtheme restore              # revert to the pristine pre-gtheme desktop
gtheme new midnight --from nsx   # scaffold a theme from a palette...
gtheme build midnight            # ...and render a whole desktop from ~16 colours
```

### Interactive mode

Run `gtheme` with no arguments (or `gtheme menu`) and you get a full-screen,
arrow-key menu that reaches **every** command — apply/switch, dry-run preview,
restore, browse, author (new/build/capture), and manage (install/update/remove/
export/validate/search). Move with `↑`/`↓` (or `j`/`k`), `enter` to select,
`q`/`esc` to go back. Theme pickers show live palette swatches and mark the
active theme. It's pure stdlib — no `rich`/`curses` — and degrades to a plain
numbered prompt when there's no TTY (pipes/CI). Honours `NO_COLOR`; set
`GTHEME_NO_ANIM=1` to disable the spinner/reveal animations.

It themes the lot: GTK/libadwaita accent, GNOME accent + extensions (dock, blur,
logo-menu, tiling), wallpaper, Ptyxis & Alacritty, starship, fish, btop, micro,
fastfetch — plus an optional sudo step for boot (Plymouth/GDM/Limine).

## Install

gtheme is pure Python (3.11+) and needs only **jinja2** and **pydantic**. On
GNOME it also uses `gsettings` (from **glib2**) and **dconf** to read/write
settings.

> **Note:** no release is tagged yet, so install from a local checkout for now.
> The repo lives at `github.com/blyatiful1/gtheme` (cloning needs access while
> it is private).

```sh
git clone https://github.com/blyatiful1/gtheme ~/gtheme
~/gtheme/install.sh          # symlinks `gtheme` into ~/.local/bin, checks deps
~/gtheme/install.sh --pip    # ...and pip-install jinja2/pydantic if missing
~/gtheme/install.sh --uninstall   # remove the ~/.local/bin/gtheme symlink
```

The installer refuses to continue on Python < 3.11 or with the deps missing
(use `--pip` to install them automatically). On Arch:

```sh
sudo pacman -S python-jinja2 python-pydantic glib2 dconf
```

Or run straight from the checkout: `~/gtheme/bin/gtheme list`.

### Arch package

A `PKGBUILD` is included. Once a release is tagged, pin the tarball checksum
with `updpkgsums`, then `makepkg -si`.

## How a theme works

A theme is a directory with a declarative `theme.toml`:

```toml
[meta]
name = "jojo"
title = "STONE OCEAN"

[palette]                       # or a separate palette.toml
bg = "#0B0E18"
accent = "#7DC75B"
# ...

[[files]]                       # component tag drives --only and per-file backup
component = "gtk"
src  = "files/gtk/gtk.css"
dest = "~/.config/gtk-4.0/gtk.css"

[[settings]]                    # gsettings or dconf; value is GVariant text
component = "desktop"
backend = "gsettings"
key   = "org.gnome.desktop.interface accent-color"
value = "'green'"

[[settings]]                    # {{ runtime }} tokens resolve per-machine
component = "terminal"
backend = "dconf"
key   = "/org/gnome/Ptyxis/Profiles/{{ ptyxis_default_profile }}/palette"
value = "'JoJo'"

[[hooks]]                       # the weird sudo 10% stays as scripts
event = "post"  component = "boot"  sudo = true  optional = true
script  = "hooks/install-boot.sh"
restore = "hooks/restore-boot.sh"
```

Layout:

```
themes/<name>/
  theme.toml        palette.toml
  files/            # sources referenced by [[files]].src
  assets/           # non-installed extras (svg sources, etc.)
  hooks/            # scripts referenced by [[hooks]]
```

### Backup & restore (the safety net)

The first time gtheme touches a file or a settings key, it snapshots the prior
value into a **pristine baseline** under `~/.local/state/gtheme/`. `apply` only
ever adds to that baseline, so no matter how many themes you apply or switch,
`gtheme restore` always returns the system to the state it had *before gtheme
first ran*. Files the theme introduced are removed; keys are reset or restored to
their exact prior value. Boot/sudo hooks ship their own `restore-*.sh`.

`{{ runtime }}` tokens (`ptyxis_default_profile`, `home`) are resolved at apply
time, so manifests committed to the repo are portable across machines.

## Authoring: a palette becomes a desktop

```sh
gtheme new ocean --from jojo     # copies a palette to start from
$EDITOR ~/.local/share/gtheme/themes/ocean/palette.toml
gtheme build ocean               # renders alacritty/ptyxis/btop/micro/gtk from it
gtheme apply ocean --dry-run     # preview every file + setting change
gtheme apply ocean
```

`build` renders the components listed in `[build].managed` from shared Jinja
templates (`src/gtheme/templates/`), using filters like `lighten`, `darken`,
`mix`, `alpha`. Define your structural roles + the 6 ANSI hues; brights and
surfaces are derived if you omit them. Hand-author anything you don't want
regenerated by leaving its component out of `managed`.

Already themed your desktop by hand? Freeze it, then back it up or share it:

```sh
gtheme capture mydesk            # snapshot the FULL live look into a theme
gtheme export mydesk             # bundle it into a shareable mydesk.zip
```

`capture` is comprehensive: it snapshots every file and gsettings/dconf key that
any gtheme theme can manage — GNOME interface (accent, scheme, icon/GTK/cursor
theme, fonts), the wallpaper (bundled, with `{{ home }}` rewritten so it's
portable), terminal/prompt/shell/monitor/editor configs, and every supported
extension (dock, blur, just-perfection, logo-menu, tiling, rounded-corners) —
recording whatever is actually present/set. `export` packs the result into a
single self-contained `.zip` (a clean top-level `<name>/` dir); copy it to
another machine and `gtheme install mydesk.zip` to apply it there (a `.zip`,
an unzipped theme dir, and a git URL all work as install sources).

## Commands

| command | what it does |
|---|---|
| `list` / `search <q>` | browse the collection |
| `install <name\|path\|.zip\|git-url> [--insecure]` | install a theme (bundled, local dir, .zip, or remote) |
| `remove <name>` | uninstall a previously installed theme |
| `update [name] [--insecure]` | refetch installed themes from their origin |
| `diff <name>` / `apply <name> --dry-run` | preview changes |
| `apply <name> [--only c1,c2] [--no-sudo] [--no-hooks] [-y]` | apply |
| `switch <name>` | apply, keeping the pristine baseline |
| `restore [--only c1,c2] [--no-sudo] [--wipe] [-y]` | revert to pre-gtheme state |
| `current` | show the active theme |
| `validate [name]` | check manifest, sources, requires |
| `new <name> [--from base]` / `build <name>` | author from a palette |
| `capture <name>` | freeze the full live config into a theme |
| `export <name> [-o out.zip]` | bundle a theme into a shareable `.zip` |
| `publish <name>` | add to the collection + print contribute steps |

Global flags: `--version` (print the version and exit), `--verbose` (extra
diagnostics), `-y`/`--yes` (assume yes — for non-interactive/CI use).

## Security & consent

Themes can ship `[[hooks]]` (arbitrary shell scripts) and write files outside
their own directory, so gtheme treats anything you downloaded as untrusted:

- **Downloaded-theme hooks require interactive confirmation.** When you `apply`
  a theme installed from a git URL, gtheme prints each hook script and asks
  before running it.
- **`sudo` and untrusted hooks are denied by default.** A hook marked
  `sudo = true`, or any hook from an untrusted theme in a non-interactive run,
  is skipped unless you explicitly consent.
- **File destinations are confined.** Manifest `dest` paths must stay inside
  your home directory; `src` paths must stay inside the theme directory. Path
  escapes (`/etc/...`, `~/../...`, `../`) are refused.
- **`-y`/`--yes`** answers every prompt with "yes" for non-interactive/CI use —
  only point it at themes you trust.
- **`--insecure`** allows non-`https` git origins (e.g. plain `http://`) when
  installing/updating. Off by default.

Locally authored and bundled themes are trusted and run without prompts.

## The collection

- **nsx** — Honda NSX (NA1): Berlina-black cabin, Formula Red, Championship White.
- **jojo** — STONE OCEAN (JoJo Part 6+): Jolyne green, Stand-string blue, the Spin.

Contribute one with `gtheme publish <name>` (copies it into `themes/`, regenerates
`index.json`, and prints the git/PR steps).

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 blyatiful1.
