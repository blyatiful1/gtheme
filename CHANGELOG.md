# Changelog

All notable changes to gtheme are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/); versions follow semver.

## [Unreleased]

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
