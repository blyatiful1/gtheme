# Changelog

All notable changes to gtheme are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/); versions follow semver.

## v2.0.0 (unreleased) — the rebuild

gtheme was a command-line tool. It is now an app: a GTK4/libadwaita window for
GNOME, written for someone whose first Linux computer is the one in front of
them. v1 is preserved in full on the `legacy-v1` branch and at the `v1-final`
tag; nothing from it is lost, and the state it wrote is never touched.

### The app

- **Fifteen pages in one window**, in four groups: Home and Looks; the eight
  "change one thing" pages (wallpaper, colours, icons and pointer, fonts, top
  bar, windows and desktops, add-ons, terminal); three system pages plus a
  catch-all; and Undo & Restore Points.
- **You can see your current setup.** GNOME's own Appearance panel cannot show
  you which app style, icon set or text style you are actually using. The Home
  page reads all of it back in plain words.
- **Every control carries a sentence** saying what it does, and the words used
  are checked by a test. A list of about ninety terms — the settings machinery,
  the platform vocabulary, the font-rendering physics — may not appear in any
  string the user sees. The app says "add-on", "top bar", "highlight colour",
  "text sharpness".
- **Ctrl+F searches everything**: every setting, its explanation, its synonyms
  in the words a Windows or macOS switcher would use, every Look and every
  add-on. Hits deep-link to the row and flash it.
- **Nothing was left out, and it is machine-checked.** Every setting a GNOME 50
  desktop has is dispositioned in a manifest; anything without a hand-written
  home renders automatically on the More Settings page, from the system's own
  description, labelled as such.
- **A four-slide introduction on first run** that ends in a real action —
  saving your desktop exactly as it is — rather than a "Get Started" button
  that does nothing.

### Safety

- **Restore points, which no other GNOME customisation tool has.** One is taken
  automatically before every change, you can take one whenever you like, and
  "Before gtheme" — how the computer looked before this app ever ran — is kept
  forever.
- **Undo is not a second engine.** Applying a saved moment builds an ordinary
  transaction and goes down the identical path, with the identical preflight,
  recording, ownership tracking and rollback.
- **All-or-nothing applies.** Any failure rolls the whole thing back and says
  what happened in terms of your desktop.
- **`gtheme rescue`** — a headless "put it back" command that imports no GTK
  and needs no graphical session, for the day the desktop itself will not come
  up.
- **Every version 1 defect tag is now a named regression test.** AS4, AS5, AS8,
  R1, R3, R4, R5, R6, F1, L1, X1 and E1 were re-grepped from the legacy source
  and pinned before the new engine was written.

### Breaking changes

- **Looks are declarative only.** Format v2 has no hooks section and the engine
  has no script-execution machinery, so *Looks only change settings; they can't
  run programs on your computer* is a property rather than a policy. **v1
  presets no longer validate** — they are converted, and the converter names
  every hook it dropped and what that hook used to do. Nothing is lost
  silently, but some v1 capabilities (magma's Plymouth theme, nightbloom's
  reseed engines) genuinely do not come across, and each bundled Look's
  `README.md` names its own exclusions.
- **`themes/index.json` is now `version = 2`.** The path and the repository name
  are load-bearing and do not change, and the six fields v1 clients read are
  still there and still mean the same thing — but the top-level version bump is
  a documented break. Four fields are added: `format`, `screenshots`,
  `min_shell` and `provenance`.
- **The interactive text menu is gone.** So are `new`, `build`, `capture` and
  `export` as commands: capturing and sharing a desktop are now buttons in the
  app. The `gtheme` command keeps four subcommands — `gui` (the default),
  `rescue`, `validate <folder>` for Look authors, and `apply <name-or-folder>`
  for using a Look without opening the window.
- **v2 state lives under `~/.local/state/gtheme/v2/`.** v1's files in
  `~/.local/state/gtheme/` are never written to and never deleted, and a
  read-only copy of them is what materialises the "Before gtheme" restore
  point.
- **Requirements moved up**: GNOME 49 or 50 with libadwaita 1.9 or newer. On
  anything older gtheme shows a screen saying so and changes nothing.

### Looks

- **Six bundled**: HYPERCLASS (Gilded Void), MAGMA (Obsidian Flow), NETRUNNER,
  NIGHTBLOOM (the glasshouse after dark), DAYBREAK (light) and HEARTH (warm).
  The first three are conversions of their v1 originals; NIGHTBLOOM is new, and
  DAYBREAK and HEARTH were written during the audit pass below, because four
  dark Looks is not a choice. Wallpapers ship in the repository rather than
  being fetched, so applying one needs no internet connection.
- Each Look's folder carries a `README.md` naming what did not survive
  conversion.

### Add-ons

- **Search, install, configure and update from inside the app.** Installing
  goes through GNOME's own confirmation box; gtheme never installs one behind
  it.
- **Twenty-four hand-written settings panels** for popular add-ons, so their
  options are explained in the same voice as the rest of the app. Everything
  else gets a generic panel, honestly labelled.
- **Add-ons that fight each other** are offered as either/or, and combinations
  known to break things carry a warning phrased as what will happen to you.
- **Identifiers are never shown.** Not in a list, not in an error.
- **The log-out question is answered honestly.** GNOME scans for add-ons once,
  at start-up; one installed afterwards is invisible to it, and there is no
  rescan. gtheme asks the desktop what it actually knows and says either "it's
  on" or "it starts working after you log out and back in". That verdict was
  measured by experiment and is pinned as a permanent test.

### Under the hood

- Engine rewritten as `core/`, which imports no GTK at all — checked three
  ways, ending with an import with PyGObject removed entirely.
- Settings go through one seam with three implementations (native, subprocess,
  and an in-memory one that is the test seam), one key grammar with four
  address forms, and typed errors rather than matched error text.
- Controls are data: every row in the app is an entry in a `.toml` file, with a
  mandatory plain-language subtitle and search synonyms next to the setting it
  describes.
- Four test tiers — about 1,880 unit and regression tests, 42 that talk to a
  real dconf over a private session bus, about 660 widget tests, and 29 that
  boot a real headless GNOME Shell on that private bus and prove after every
  one of them that the live desktop was untouched. The thirty screenshots in
  the README are produced by that last tier and then checked for being pictures
  of actually different things.
- Packaging is pure `pyproject.toml` plus a `PKGBUILD` and an `install.sh`; no
  meson, and no `curl | bash` anywhere in the project.

### The audit pass

Before any of the above was called finished, the rebuild was read back against
its own promises — every page, every path that writes to your computer, every
sentence in the documentation — and what did not hold up was fixed. Most of it
is invisible if nothing goes wrong, which is the point. What changed:

- **A Look can only change the way things look, and that is now enforced rather
  than intended.** One written policy decides where a Look may write, checked
  when it is compiled and again before it is applied. Anything that could make
  your computer *run* something is refused outright and by name: autostart
  entries, systemd units, `environment.d`, shell start-up files, `.desktop` and
  `.service` files anywhere, the media-key commands, the default-application
  entries, and any settings tree not on the allow-list. A second, milder tier —
  your shell prompt, your terminal configs, fastfetch — is allowed but listed
  individually before you apply, instead of disappearing into "and 12 files".
  The refusal is decided on the fully resolved path as well as the written one,
  so a symlink cannot be used to step around it, and a Look's own source files
  are confined to its folder at render time rather than trusted from its
  manifest.
- **Rollback covers every way an apply can fail**, not only the ones that were
  anticipated. Any exception during a change now rolls the whole thing back,
  puts the ownership record back as it was, and re-raises something that says
  whether your desktop was restored. The writes that happen *after* the last
  change lands are guarded too — an error there used to escape while the app
  was still saying nothing had happened. Where the app genuinely cannot tell
  whether your desktop was put back, it now says that, instead of guessing in
  its own favour.
- **Changes you make on the individual pages are recorded and undoable.** This
  is the largest single correction. Flipping a switch on Fonts or Top Bar used
  to change your desktop without leaving a trace: only whole Looks were
  recorded, so "Before gtheme", Undo and `gtheme rescue` all had a blind spot
  exactly where a cautious person experiments. Every row in the app now writes
  through a recording layer that saves what was there first, claims the key in
  the ownership record, and takes **one** restore point per burst of edits
  rather than one per switch.
- **Applying a Look shows you exactly what it will change** before it does
  anything: an expander listing every setting as before → after, every file it
  will write by destination, and every add-on by name. It also warns you when
  the Look asks for an icon set, pointer, app style or font this computer does
  not have, when it would turn on two add-ons known to fight each other, and
  when it would write over an accessibility setting you have deliberately
  switched on (high contrast, larger text, reduced motion).
- **Add-ons are named before anything is downloaded.** The confirmation lists
  each missing add-on's title, author and source, worked out from data already
  on your computer — opening the preview does not go online. Installing still
  goes through GNOME's own machinery, and the honest answer about logging out
  is unchanged.
- **A long apply shows its progress and can be stopped.** The steps appear as
  they happen, and a Stop button is offered once there is something to stop;
  pressing it rolls back what had already landed.
- **"Before gtheme" is real on a computer that never ran version 1.** It used
  to be materialised only from v1's files, so on a fresh install the row
  promised something it could not deliver. The first time the app opens, it now
  saves your desktop exactly as it is — unless something has already been
  changed on this machine, in which case the row is left out rather than
  labelled with a date that would be a lie.
- **Terminals are themed through the same transaction as everything else** —
  one snapshot, one ownership claim, one restore point, one rollback — instead
  of each terminal writing on its own and half-succeeding in silence. **GNOME
  Terminal and Console are supported** alongside Ptyxis, Alacritty and Ghostty
  (and the prompt and readouts around them: starship, fish, btop, cava,
  fastfetch). Two honest exceptions: fish keeps its variables in a
  store only fish can write, so it is updated after the transaction under the
  same lock with its old values recorded first (`gtheme rescue` reaches it,
  Undo does not); and Ghostty's "take them over" button still moves a folder
  outside the transaction. The GNOME Terminal and Console adapters were written
  on a computer that had neither installed, so each key is probed against your
  computer's own settings description before it is written.
- **`gtheme apply <name-or-folder>`** uses a Look without opening the window,
  takes a restore point first like the app does, and has a `--dry-run` that
  prints what would change and writes nothing.
- **Saving your desktop as a Look captures the whole desktop**, not the subset
  the app happened to know about, and tells you what it could not take —
  grouped by kind — instead of quietly leaving it out. Export writes a
  `.gtheme.zip` through a hidden partial file that is renamed only once it is
  complete, so a failed export never leaves half a file behind.
- **`install.sh` checks before it installs.** It refuses on GNOME older than 49
  or libadwaita older than 1.9 instead of installing an app that cannot run; it
  validates a virtual environment it finds already there (Python version, and a
  real `import gi` probe) rather than reusing it on faith; it prints your
  distribution's own command when the environment cannot be built; and
  `--uninstall` refuses while gtheme still owns settings on this computer,
  including settings changed only on the individual pages. A second
  `PKGBUILD-git` builds from a checkout, for Arch users not waiting on a tag.
- **Keyboard, screen-reader and contrast work.** Ctrl+? opens a shortcuts
  window; picture tiles carry alternative text or are hidden from screen
  readers when they are decoration; the window is clamped to the usable area of
  your screen so it cannot open larger than the display; and `gtheme validate`
  now warns a Look's author when its text-on-background contrast fails WCAG AA.
  The launcher entry is findable in German, Spanish, French and Brazilian
  Portuguese. The interface itself is English only, and Orca has never been
  tested against this app — both are now stated in the README rather than left
  to be discovered.
- **When something goes wrong, you can say what.** A rotating log at
  `~/.local/state/gtheme/v2/gtheme.log`, an uncaught-error hook that writes to
  it, and "Copy details for a bug report" in the main menu — versions plus the
  last forty lines of that log, and no setting values. The same details are one
  click away in About. And if a change was interrupted hard enough to leave its
  rollback journal behind, the next launch says so and offers to put things
  back; the answer is remembered and the question is not asked twice.
- **The documentation was swept against the code**, sentence by sentence, and
  the claims that had drifted were corrected rather than softened — including
  several that this pass itself had made false.

## [Unreleased] (v1)

- **Shared render templates: readable text on accent fills.** The GTK accent
  override now puts the theme's dark `bg` on accent-filled widgets instead of
  `fg_bright` (ivory-on-brass/orange was ~2.2:1; ink is 7–7.6:1), and the
  derived Ptyxis *Light* scheme no longer emits near-invisible white slots
  (`Color7` → `comment`, `Color15` → `ansi_black`, cursor/bell/superuser text
  → `bg`; the Dark superuser badge too). Both bundled themes rebuilt.

- **New bundled theme: `hyperclass`** (HYPERCLASS — Gilded Void), the
  collection's luxury liner: first class aboard a starliner crossing the
  void. Champagne brass (`#C9A24A`, the desaturated "expensive gold" band —
  never slot-machine `#FFD700`) as hairline trim on deep-space ink, warm
  ivory text, one ice vein for anything technical; every contrast ratio
  audited (body text 14:1, all six ANSI hues ≥ 5.9:1 in their canonical hue
  slots). Applied across wallpaper, GTK, GNOME accent/icons, Ptyxis,
  Alacritty, starship, btop, micro, fastfetch, cava, fish, dash-to-dock,
  Tiling Shell, blur-my-shell — and Burn My Windows, whose windows now
  open/close through a champagne hexagon lattice (profile shipped, exactly
  one effect enabled). Three terminal instruments under
  `~/.local/share/gtheme/assets/hyperclass/bin` (fish shortcuts in
  parentheses): a brass ASCII orrery that is a working clock — hours,
  minutes and a smooth seconds moon on engraved orbits (`orrery`), a
  truecolor hyperspace starfield jump (`warp`), and a self-printing
  art-deco boarding pass to a random exoplanet (`boarding`). Three seeded
  procedural wallpapers — an art-deco sunburst marque, first light over a
  ringed gas giant, and the jump itself — rotate on an unhurried GNOME
  crossfade; the numpy generator is included under `assets/`.

- **The collection is now `magma`** (MAGMA — Obsidian Flow), replacing `nsx`,
  `jojo` and `shoji`. A single all-in dark rice: obsidian-glass surfaces with
  molten orange / lava gold accents and one cool teal vein, applied across
  wallpaper, GTK, GNOME accent/icons, Ptyxis, Alacritty, starship, btop,
  micro, fastfetch, fish, dash-to-dock, Tiling Shell and blur-my-shell.
  Ships four terminal animations under `~/.local/share/gtheme/assets/magma/bin`
  (fish shortcuts in parentheses): a live metaball lava-lamp fluid sim in
  24-bit colour half-blocks (`lavalamp`), rising ember drift (`embers`), a
  ~3.5 s eruption (`erupt`) and a deterministic thermal-scan gauge card
  (`thermal`). Three procedural wallpapers — cracked obsidian, the lava lamp
  itself, and an ember updraft — share the animation's exact heat ramp and
  rotate on a slow GNOME slideshow crossfade; the seeded numpy generator is
  included under `assets/`.

- **shoji 1.1.0** — the vermilion Tiling Shell focus border is gone (it read
  as an alert, not a seal; kept `false` in the manifest so re-apply heals
  systems that had it). New procedurally painted `take.png` wallpaper — a
  sumi-e bamboo grove in three ink washes with a single vermilion falling
  leaf — is now the default. Zen panel: the top bar leaves the desktop and
  appears only in the overview (just-perfection `panel=false`,
  `panel-in-overview=true`; revert with `dconf write
  /org/gnome/shell/extensions/just-perfection/panel true`). Fish greets each
  new shell with one random zen line in diluted ink.
- **New bundled theme: `shoji`** (Paper & Ink) — the collection's first light
  theme: washi-paper background, sumi-ink text, a single vermilion hanko
  accent. Procedurally painted wallpapers (brush-stroke enso, ink-wash
  ridgeline, plain washi; generator included under `assets/`), hand-authored
  dual light/dark Ptyxis palette, and a minimal no-powerline starship prompt.

## [0.1.0] — unreleased

Initial public release.

- **Apply / switch / restore** with a pristine baseline: the first time gtheme
  touches a file or settings key it snapshots the prior state, so `gtheme
  restore` always returns the desktop to how it was before gtheme first ran.
- **Interactive TUI** (`gtheme` with no arguments): pure-stdlib arrow-key menu
  with palette swatches, theme-tinted header, breadcrumbs, and a
  screen-reader-friendly plain mode (`--plain` / `GTHEME_PLAIN=1`).
- **Authoring**: `new` scaffolds from a palette, `build` renders terminal /
  monitor / editor / GTK configs from ~16 colours via shared templates,
  `capture` freezes the live desktop into a theme, `export` bundles it into a
  shareable `.zip`.
- **Install sources**: bundled collection, local dirs, `.zip` archives, git
  URLs — with origin tracking, hook-consent prompts for downloaded themes, and
  path confinement.
- **Bundled themes**: `nsx` (Honda NSX NA1) and `jojo` (STONE OCEAN).
