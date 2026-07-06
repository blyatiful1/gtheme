# Changelog

All notable changes to gtheme are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/); versions follow semver.

## [Unreleased]

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
