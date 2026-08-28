# Audit-fix campaign ledger (v2 — after plan-critic)

Branch `audit-fixes`, worktree `/home/crocco/gtheme-fixwork`, base `b9e60c9`.
Specs: `.audit/review-report.md` (C/H/M/L IDs) and `.audit/persona-report.md` (§2.1–§2.10 = U1–U10). X-IDs below are §3 items promoted by the plan-critic.
Rule: every ID ends `fixed@<sha>` or `deferred: <reason>`. Agents commit their OWN files (flock `/tmp/gtheme-commit.lock`, `git commit -- <owned files>`, IDs in message). FIXLOG statuses updated + committed by each wave's integrator.

**Verify baseline (update whenever the harness legitimately changes it):** 1967 collected · 1895 passed · 2 skipped · 70 deselected · ruff clean · `verify.sh: OK` (worktree venv, 2026-08-28).
Gate rule: `./verify.sh` green AND collected ≥ baseline AND deselected/skipped changes only when a harness change (M16/M20) declares them — then re-baseline here.

**Resume protocol (if a session died):** read this file + `git -C /home/crocco/gtheme-fixwork log --oneline` + `git status`. If the tree is DIRTY: diff it against the pending IDs, run `./verify.sh`, commit what is sound before continuing — do not redo work already on disk. Continue at the first wave with pending IDs. Never push to origin; never touch `/home/crocco/gtheme` (live tool); never launch the gtheme app (tests only — conftest's live-state canary fails the suite if live state changes).
Budget gate: the orchestrator checks remaining session tokens between waves; below ~2M it commits, updates this file, and hands off instead of starting another wave.

## Wave 0 — docs, install, packaging, test harness (text/shell/infra; cheapest criticals first)
- [ ] U1 install.sh GNOME/libadwaita ≥1.9 gate + README "no command line" honesty + start-here contradiction — pending
- [ ] M22 install.sh validates pre-existing venv (python version + import gi probe in venv) — pending
- [ ] M23 PKGBUILD-git variant for checkout builds; README Arch route corrected (tag cut = deferred) — pending
- [ ] M21 uninstall guard reads ownership ledger too (note: complete only with H3 in Wave B) — pending
- [ ] M16 verify.sh/CI/PKGBUILD check() wrapped in dbus-run-session (AS5 backend-ask half → Wave A) — pending
- [ ] M20 sandbox tier split: write-parity + dconf round-trip runnable in CI under private dbus — pending
- [ ] L9 PR template index command corrected — pending
- [ ] L10 jinja2 dep dropped (pyproject + PKGBUILD + packaging test) — pending
- [ ] L11 version single-source (__init__ ↔ PKGBUILD ↔ metainfo) — pending
- [ ] L12 verify.sh preflight checks ruff too — pending
- [ ] L13 SECURITY.md op-count claim corrected to the stronger true claim — pending
- [ ] M24 README removal instructions name --uninstall + full leftover list — pending
- [ ] U9 English-only stated honestly + localized .desktop Name/Comment/Keywords + xml:lang metainfo (full gettext = deferred) — pending
- [ ] X5 install.sh venv failure branch gives per-distro commands — pending
- [ ] DOCS §3.4: bug_report.yml `gtheme restore`→`rescue`; theme_submission.yml `gtheme publish` removed; README:303/322 overclaims; README:380/414 + GLOSSARY:86 "Before gtheme" promise made conditional-truthful (re-worded again by U3); SECURITY.md locations table completed — pending

## Wave A — core engine (core/, preset/ only; UI halves of these IDs live in Wave B)
Agent A1 owns transaction.py, preset/compile.py, preset/model.py, preset/placeholders glue:
- [ ] C1 file-destination policy (autostart/systemd/rc/starship/.desktop/.service refusal) — pending
- [ ] H4 settings-key policy (media-keys command, default-applications exec, dconf: scope) — pending
- [ ] H5 confine_src called in compile_preset + re-checked in _rendered + regression test through apply — pending
- [ ] H1(txn) rollback on Exception, ledger restored, real rolled_back re-raised as TransactionError — pending
- [ ] H9 rolled_back &= not cleanup_changed; no re-point at stripped Look; tidy-up narrated — pending
- [ ] M1 cleanup warnings/kept/dead surfaced on TransactionResult — pending
- [ ] M2 no-op ops not claimed (or orphan-without-baseline = satisfied) — pending
- [ ] M12 unresolved value tokens skip the op — pending
- [ ] L4 add-on install skips reported without session bus — pending
- [ ] L8 min_shell compared at plan/apply; doc aligned — pending
- [ ] X1 captured-Look add-on settings apply AFTER extension install (phase order/two-pass) — pending
- [ ] M16-AS5 settings phase gate asks the backend, not the env — pending
Agent A2 owns settings_backend.py, gvariant.py, baseline.py, restorepoints.py, core tests:
- [ ] H7 never-written dconf path = writable unset, not missing — pending
- [ ] L2 GioBackend.reset read-back verify — pending
- [ ] H1(baseline) record_file/record_setting I/O failures → TransactionError — pending
- [ ] H10 v1 importer: symlink → {"link": target}; missing blob → omit dest (synthetic v1 fixture test) — pending
- [ ] M14 manual capture unions ledger-claimed keys — pending
- [ ] L1(core) RestoreResult carries rolled_back — pending
- [ ] L18(core) Baseline.wipe deleted — pending
- [ ] M18 restore-failure test made real (fail after something landed; no tautology) — pending
- [ ] M19 rescue failure-path tests (exit 1 preserves records; LockBusy) — pending

## Wave B — UI truth & safety (parallel by file, then serial consolidator)
B1 rows.py, panels/widgets.py, colors/icons/fonts/wallpaper write paths, _style_common:
- [ ] H3 rows through coalesced recording backend: first-touch Baseline record + MANUAL_OWNER ledger claim + ONE coalesced restore point per edit burst + LockBusy handled; NO per-toggle Transaction (cap-eviction trap) — pending
- [ ] M3 apply_ops catches OSError — pending
- [ ] M7 row write BackendError → refresh to truth + reason surfaced — pending
B2 looks.py, window.py:
- [ ] H2(looks) unknown failure defaults rolled_back=False; half-copy reachable; Undo offered — pending
- [ ] M6 undo toast requires result.transaction is None — pending
- [ ] M15 toasts escape markup — pending
- [ ] U4 "Show exactly what changes" expander (before → after; DiffEntry frozen-contract amendment explicit+justified); file destinations + add-on names listed — pending
- [ ] U8 undo = Adw.ButtonContent with label, packed from window construction; Ctrl+Z → confirm_apply, editable-focus guard; toast names the moment — pending
- [ ] L6 header undo independent of Home page — pending
- [ ] X3 _capture_restore_point OSError surfaced (no silent proceed); point.warnings shown — pending
B3 restore.py, home.py, topbar.py, windows.py, more.py, addons.py:
- [ ] H2(restore) on_failed two-branch honest wording — pending
- [ ] H11 manual moments pass dests (ledger destinations) — pending
- [ ] L1(ui) RestorePage._report branches on rolled_back — pending
- [ ] M10 restore save via runner (+ onboarding first-point) — pending
- [ ] M5 addons failed-enable resets switch (not NEEDS_RELOGIN) — pending
- [ ] M30 topbar/windows filter corpus problems to own domains — pending
- [ ] L5 more-page floor group hides when empty — pending
- [ ] L7 no-runner double report fixed — pending
B4 serial consolidator (cross-file):
- [ ] M28 one banner helper, nine call sites — pending
- [ ] M29 one scaffold constant pair + PageShell.group plain-text + Windows wording — pending
- [ ] L15 accent table single source — pending
- [ ] L16 shared banner/action-row helpers — pending
- [ ] L19 one gvariant quote/unquote pair — pending
- [ ] M17 apply_ops success+failure tests — pending
- [ ] L18(ui) SchemaProbe.source_for_row, Prefs.as_dict, PageShell.built_ids resolved (delete or write the claimed test) — pending

## Wave C — terminal, ego, window infra/perf
C1 terminal/ package + ui/pages/terminal.py:
- [ ] H8 adapters return ops; Terminal page applies via one Transaction (snapshot/ledger/lock) — pending
- [ ] H12 per-adapter Exception isolation in apply_all; page handler wrapped — pending
- [ ] M11 palette built via read_palette fallback (no cached error page) — pending
- [ ] L17 detect() once, state passed down — pending
C2 ego/install.py + looks.py glue:
- [ ] H6 add-ons named (uuid/title/source) before download; docs corrected; first-install via GNOME box considered — pending
- [ ] M4 missing gnome-extensions binary → CommandResult(127), no 180s stall — pending
- [ ] M9 unpack/install off the main loop — pending
- [ ] M8 look tiles via thumbnail cache — pending
- [ ] E5 apply progress (per-step feedback) + cancel affordance where safe — pending
C3 window.py, app.py, panels/loader.py, panels/conflicts.py, prefs:
- [ ] M26 startup reads ShellVersion without ListExtensions round-trip — pending
- [ ] M27 corpus/dispositions memoised (reload() for tests) — pending
- [ ] M25 data_dir checks sys.prefix + XDG_DATA_HOME — pending
- [ ] L14 sidebar prefs writes batched (save on close/idle) — pending
- [ ] M13 blur-my-shell × intellibar hazard entry — pending
- [ ] X2 unreadable shell version ≠ permission to proceed (safe gate screen) — pending
- [ ] X4 About: support/help URL + "Copy details" — pending
- [ ] U5-infra rotating log ~/.local/state/gtheme/v2/gtheme.log + excepthook — pending
- [ ] E10 addons shell connection re-probe affordance (copy no longer lies) — pending

## Wave D — product features
D1 preset capture/share/portability (+ L3):
- [ ] U7 Export Look… / Add a Look from a file… / `gtheme apply <name|path> [--dry-run]` / save toast names folder / capture_share includes gtheme-written files + [palette] (or states omissions) — pending
- [ ] H13 capture_keys mirrors descriptor_keys (compound incl. color-scheme; floor exclusion explicit) — pending
- [ ] L3 share scan genericises real dest_root() — pending
D2 registry/get-more + content:
- [ ] U2 provenance filter (honest empty state) + community screenshots fetched + entry_for provenance honest + one light Look authored (index regenerated; screenshot = generated wallpaper for now) — pending
D3 first-run + a11y + look-value honesty:
- [ ] U3 real pristine "Before gtheme" captured on first run (kind="pristine", PRISTINE_ID); docs re-worded to match — pending
- [ ] U6 plan-time value validation via existing scanners (icon/cursor/gtk/font) + conflicts.active_conflicts on Look path + ubuntu-dock/tiling-assistant entries — pending
- [ ] U10 alternative_text/accessible labels on picture tiles; ShortcutsWindow (Ctrl+?); window clamped to workarea; high-contrast/reduced-motion read before Look writes; contrast check in `gtheme validate` — pending

## Wave F — extras + closure
- [ ] E1 gnome-terminal + Console adapters (post-H8 ops protocol) — pending
- [ ] E2 custom wallpapers join catalogue with readable names; slideshow XML pickable — pending
- [ ] E3 shortcut editor conflict check — pending
- [ ] E8 icon-set "only one installed" sentence parity — pending
- [ ] E9 shortcuts page filter/grouping — pending
- [ ] E6 "last change did not finish" launch notice from leftover journal — pending
- [ ] CHANGELOG entry for the whole campaign — pending
- [ ] CLOSURE: per-ID adversarial verification of the full diff; ./verify.sh AND ./verify.sh --full (sandbox tier, page walk, screenshot regeneration committed, live-desktop-unchanged canary); final report — pending

## Deferred (user decision required — not silently dropped)
- gettext/i18n adoption (U9 ships the honest minimum)
- Flatpak/AppImage/.deb packaging
- Cutting + pushing the public v2.0.0 tag (M23 ships the -git alternative; namcap not installed → PKGBUILD lint test skips, noted)
- Pushing anything to origin; merging audit-fixes into main (user merges; before merging: run --full and take a restore point — H3/H8/U3 change live behavior)
- Seeding real community Looks / content pipeline (theme-sharing-website branch exists)
- Hardware-presence gating for setting rows (runtime-detection design)
- Offline-mode toggle (design decision)
- Photographing bundled Looks on a live session (sandbox infra could; needs supervised run)
