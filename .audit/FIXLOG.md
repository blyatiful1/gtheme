# Audit-fix campaign ledger

Branch `audit-fixes`, worktree `/home/crocco/gtheme-fixwork`, base `b9e60c9`.
Specs: `.audit/review-report.md` (code findings C/H/M/L) and `.audit/persona-report.md` (priorities §2.1–§2.10 = U1–U10).
Rule: every ID ends as `fixed@<sha>` or `deferred: <reason>`. Update + commit this file at the end of every wave.

**Resume protocol (if this session died):** read this file, `git -C /home/crocco/gtheme-fixwork log --oneline`, and the two reports; continue with the first wave that has pending IDs. Canonical check: `cd /home/crocco/gtheme-fixwork && ./verify.sh` (worktree has its own .venv). Do NOT touch /home/crocco/gtheme (live tool) until the user merges.

## Wave A — core engine (core/, preset/)
- [ ] C1 look file-destination policy — pending
- [ ] H1 rollback on all exceptions — pending
- [ ] H4 look settings-key policy — pending
- [ ] H5 confine_src on apply path — pending
- [ ] H7 unset dconf path writable — pending
- [ ] H9 switch-cleanup rolled_back truth — pending
- [ ] H10 v1 importer symlink/missing-blob — pending
- [ ] H11 manual moments cover files — pending
- [ ] M1 surface cleanup warnings — pending
- [ ] M2 no-op ledger claims — pending
- [ ] M12 unresolved value tokens skip — pending
- [ ] M14 manual moments union ledger keys — pending
- [ ] L1 RestoreResult rolled_back — pending
- [ ] L2 GioBackend.reset verify — pending
- [ ] L4 add-on skips without bus — pending
- [ ] L8 min_shell enforced — pending
- [ ] L13 SECURITY.md op-count claim — pending
- [ ] L18 dead code (core: Baseline.wipe etc.) — pending
- [ ] M18 restore-failure test rewritten — pending
- [ ] M19 rescue failure-path tests — pending

## Wave B — UI truth & safety (ui/)
- [ ] H2 half-apply honesty (looks/restore) — pending
- [ ] H3 page rows through Transaction — pending
- [ ] M3 apply_ops OSError — pending
- [ ] M5 addons failed-enable switch state — pending
- [ ] M6 undo toast false failure — pending
- [ ] M7 row BackendError handling — pending
- [ ] M10 restore save via runner — pending
- [ ] M11 palette validation on terminal page — pending
- [ ] M15 toast markup escaping — pending
- [ ] M17 apply_ops real tests — pending
- [ ] M28 banner consolidation — pending
- [ ] M29 scaffold constants/markup unification — pending
- [ ] M30 topbar/windows corpus-problem tolerance — pending
- [ ] L5 more-page group hiding — pending
- [ ] L6 header undo always built — pending
- [ ] L7 double report in restore no-runner — pending
- [ ] L15 accent table single source — pending
- [ ] L16 shared banner/action-row helpers — pending
- [ ] L19 gvariant quote/unquote single source — pending
- [ ] U4 show-what-changes diff expander + named destinations/add-ons — pending
- [ ] U8 undo labeled + packed always + Ctrl+Z confirm — pending

## Wave C — terminal, ego, window perf/infra
- [ ] H6 named add-ons in Look install dialog — pending
- [ ] H8 terminal adapters through Transaction — pending
- [ ] H12 apply_all per-adapter exception isolation — pending
- [ ] M4 missing gnome-extensions binary fast-fail — pending
- [ ] M8 looks tiles via thumbnail cache — pending
- [ ] M9 add-on unpack off main loop — pending
- [ ] M13 blur+intellibar hazard entry — pending
- [ ] M26 window startup without ListExtensions — pending
- [ ] M27 corpus/dispositions memoised — pending
- [ ] L14 prefs fsync batching — pending
- [ ] L17 terminal detect() single pass — pending
- [ ] U5-infra rotating log + excepthook + Copy details — pending
- [ ] E5 apply progress + cancel affordance — pending
- [ ] E10 addons shell reconnect affordance — pending

## Wave D — product features (persona priorities)
- [ ] U2 get-more: provenance filter, honest empty state, real screenshots fetch, import affordance, one light Look — pending
- [ ] U3 pristine "Before gtheme" on first run — pending
- [ ] U6 look value validation (icons/fonts scanners) + conflicts on Look path + distro conflict entries — pending
- [ ] U7 export/import Looks, gtheme apply --dry-run, capture files+palette, save toast names folder — pending
- [ ] U10 a11y minimums: alternative_text, ShortcutsWindow, window clamp, protect high-contrast/reduced-motion, contrast check in validate — pending

## Wave E — packaging, install, docs, test infra
- [ ] M16 dbus-run-session hermetic tiers — pending
- [ ] M20 sandbox tier split (write parity in CI) — pending
- [ ] M21 uninstall guard on ledger — pending
- [ ] M22 venv validation on reuse — pending
- [ ] M23 PKGBUILD -git variant / README Arch route — pending
- [ ] M24 README removal instructions + --uninstall — pending
- [ ] M25 data_dir sys.prefix + XDG_DATA_HOME — pending
- [ ] L3 share scan genericise real $HOME — pending
- [ ] L9 PR template index command — pending
- [ ] L10 drop jinja2 dep — pending
- [ ] L11 version single source — pending
- [ ] L12 verify.sh ruff preflight — pending
- [ ] U1 install.sh GNOME/libadwaita gate + README honesty — pending
- [ ] U9 English-only statement + localized .desktop/metainfo keys — pending
- [ ] DOCS §3.4: bug template gtheme restore→rescue, gtheme publish removed, README leftovers/promises (322/303/380/414/425), SECURITY.md locations table, min_shell doc — pending

## Wave F — extras + closure
- [ ] E1 gnome-terminal + Console adapters — pending
- [ ] E2 custom wallpapers join catalogue (+ slideshow XML pick) — pending
- [ ] E3 shortcut conflict check — pending
- [ ] E8 icon-set "only one installed" parity — pending
- [ ] E9 shortcut page filter/sub-headings — pending
- [ ] E6 "last change did not finish" launch notice — pending
- [ ] CLOSURE per-ID adversarial verification + full verify.sh + final report — pending

## Deferred (user decision required — not silently dropped)
- gettext/i18n adoption (U9 does the honest minimum; full adoption is a scope decision)
- Flatpak/AppImage/.deb packaging
- Cutting + pushing the public v2.0.0 tag (release act; M23 ships the -git alternative)
- Pushing branch/anything to origin
- Seeding real community Looks / content pipeline (theme-sharing-website branch exists)
- Hardware-presence gating for setting rows (needs runtime-detection design)
- Offline-mode toggle (design decision)
- Photographing bundled Looks on a live session for real screenshots (sandbox-tier infra exists; needs a supervised run)
