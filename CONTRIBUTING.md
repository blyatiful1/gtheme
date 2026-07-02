# Contributing to gtheme

Thanks for wanting to make GNOME desktops prettier. Two kinds of
contributions are especially welcome: **themes** and **fixes**.

## Dev setup

```sh
git clone https://github.com/blyatiful1/gtheme
cd gtheme
python -m pip install -e .[dev]      # or: ./install.sh --pip
python -m pytest -q                  # 170+ tests, should all pass
python -m gtheme validate all
```

Runtime dependencies are deliberately just **jinja2 + pydantic** and the TUI
is pure stdlib — PRs that add dependencies need a very good reason.

## Contributing a theme

Author it (see the README's *Authoring* section), then:

```sh
gtheme validate mytheme        # must pass (warnings are OK if explained)
gtheme publish mytheme         # copies it into themes/, regenerates index.json,
                               # and prints the exact git/PR steps
```

The submission checklist reviewers use:

- [ ] `gtheme validate <name>` passes; `gtheme apply <name> --dry-run` output looks sane
- [ ] **Assets are original or license-compatible**, attribution preserved
      (ASCII art keeps its artist initials; no ripped wallpapers, screenshots
      of copyrighted material, or official logos — fan themes are palette and
      geometry tributes, not asset dumps)
- [ ] No hard-coded usernames or machine paths — use `{{ home }}` /
      `{{ ptyxis_default_profile }}` runtime tokens
- [ ] No distro-only assumptions (guard optional `source` lines in shell
      configs with `test -f …; and source …`)
- [ ] Dark palette → set `org.gnome.desktop.interface color-scheme` to
      `'prefer-dark'` so light-mode desktops don't look half-applied
- [ ] Hooks: only if genuinely needed, `optional = true` for anything sudo,
      and always ship the matching restore script
- [ ] Ran `gtheme index` (CI fails on a stale `themes/index.json`)

A desktop screenshot in the PR sells the theme better than any description.

## Code changes

- Match the existing style: terse, comment the *why* and the invariants
  (grep for `R2:` / `AS4:`-style rule tags in the engine).
- Every behavior change comes with a test. The engine's apply/restore state
  machine is fully hermetic in tests — see `tests/test_baseline.py` for the
  fixtures (env-redirected `GTHEME_DEST_ROOT` / `XDG_*`, faked
  gsettings/dconf backends). Never make a test touch the real desktop.
- `schema/theme.schema.json` must stay in sync with `manifest.py`
  (`tests/test_schema.py` enforces it against the bundled themes).

## Security

Theme installs are a trust boundary (hooks, path confinement, consent
prompts). If your change touches `paths.py`, `remote.py`, `export.py`, or the
hook gate, expect extra review. Found a boundary escape? See
[SECURITY.md](SECURITY.md) — please report privately.
