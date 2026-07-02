# Security policy

gtheme applies themes that can ship **arbitrary shell hooks** and write files
into your home directory. The security model (consent prompts, sudo gating,
untrusted-origin tracking, path confinement to `$HOME` and to the theme dir)
is described in the README's *Security & consent* section.

## Reporting a vulnerability

If you find a way for a theme to escape those boundaries — write outside
`$HOME`, run a hook without consent, escape the theme directory via
symlinks/`..`, leak private data into an exported `.zip` — please report it
privately via [GitHub's private vulnerability reporting](../../security/advisories/new)
rather than a public issue.

You can expect an acknowledgement within a week. Fixes for confirmed
boundary escapes take priority over everything else.

## Scope notes

- Themes you author locally are trusted by design; the interesting bugs are
  ones where a theme installed from a **git URL or .zip** can do harm without
  the documented consent prompts.
- `--yes` and `--allow-unsafe` deliberately bypass prompts/validation; issues
  requiring them are usually not vulnerabilities.
