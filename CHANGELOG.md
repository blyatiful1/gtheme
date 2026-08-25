# Changelog

All notable changes to gtheme are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/); versions follow semver.

## v2 (in development)

gtheme is being rebuilt from the ground up as a GTK4/libadwaita desktop app.
The v1 command-line tool is preserved in full on the `legacy-v1` branch and at
the `v1-final` tag; nothing from it is lost. Notable v2 changes so far:

- **The app is a window, not a terminal.** v1's CLI is replaced by a native
  GNOME app; a small `gtheme` command remains for the headless rescue path.
- **Looks are declarative only.** Preset format v2 has no hooks section and the
  engine has no script-execution machinery. A Look can change settings and
  write files it owns — it can never run a program on your computer. v1 presets
  are imported by a converter that warns, per hook, about what it dropped.
- **`themes/index.json` stays where it is.** The community registry path and
  the repo name are load-bearing and do not change. The index gains fields
  (`format`, `screenshots`, `min_shell`, provenance) as a superset, so v1
  clients reading it may need updating.

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
