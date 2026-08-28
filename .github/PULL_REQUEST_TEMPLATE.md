<!-- Thanks! A short description of what and why is plenty. -->

## Checklist

- [ ] `./verify.sh` passes (ruff, plus the unit, regression and GTK tiers)
- [ ] For theme PRs: `./.venv/bin/python -m gtheme validate themes/<name>` passes,
      `./.venv/bin/python tools/build_index.py` has been re-run and the updated
      `themes/index.json` is committed (CI checks it is fresh), and assets are
      original or license-compatible
