# Audit-fix campaign ledger (v2 — after plan-critic)

Branch `audit-fixes`, worktree `/home/crocco/gtheme-fixwork`, base `b9e60c9`.
Specs: `.audit/review-report.md` (C/H/M/L IDs) and `.audit/persona-report.md` (§2.1–§2.10 = U1–U10). X-IDs below are §3 items promoted by the plan-critic.
Rule: every ID ends `fixed@<sha>` or `deferred: <reason>`. Agents commit their OWN files (flock `/tmp/gtheme-commit.lock`, `git commit -- <owned files>`, IDs in message). FIXLOG statuses updated + committed by each wave's integrator.

**Verify baseline (update whenever the harness legitimately changes it):** 1960 collected · 1958 passed · 2 skipped · 28 deselected · ruff clean · `verify.sh: OK` (worktree venv, 2026-08-28, measured at HEAD b2dbf81 after Wave 0 close). Prior baseline 1967/1895/2/70; delta is Wave 0's own (M20 moved 42 dconf tests out of the `sandbox` marker into the default run; +21 new collected items — 20 from tests/unit/test_docs_commands.py, 1 from the L10 dependency guard). Full repo with no marker filter: 1988 items total.
Gate rule: `./verify.sh` green AND collected ≥ baseline AND deselected/skipped changes only when a harness change (M16/M20) declares them — then re-baseline here.

**Resume protocol (if a session died):** read this file + `git -C /home/crocco/gtheme-fixwork log --oneline` + `git status`. If the tree is DIRTY: diff it against the pending IDs, run `./verify.sh`, commit what is sound before continuing — do not redo work already on disk. Continue at the first wave with pending IDs. Never push to origin; never touch `/home/crocco/gtheme` (live tool); never launch the gtheme app (tests only — conftest's live-state canary fails the suite if live state changes).
Budget gate: the orchestrator checks remaining session tokens between waves; below ~2M it commits, updates this file, and hands off instead of starting another wave.

## Wave 0 — docs, install, packaging, test harness (text/shell/infra; cheapest criticals first)  — CLOSED 2026-08-28
Wave commits: `465cdcd` (packaging), `4f9f9d0` (docs), `ca88c0e` + `f6486ff` (harness), `b2dbf81` (review-fix, all agents). Gate green at `b2dbf81`: see baseline line above.
- [x] U1 install.sh GNOME/libadwaita ≥1.9 gate + README "no command line" honesty + start-here contradiction — fixed@465cdcd (install.sh gate),4f9f9d0 (README/start-here/GLOSSARY)
- [x] M22 install.sh validates pre-existing venv (python version + import gi probe in venv) — fixed@465cdcd
- [x] M23 PKGBUILD-git variant for checkout builds; README Arch route corrected (tag cut = deferred) — fixed@465cdcd (PKGBUILD-git); README Arch route text is 4f9f9d0 but packaging flagged it may be stale — re-check `makepkg -p PKGBUILD-git -si` / `pacman -R gtheme-git` wording against README before merge
- [x] M21 uninstall guard reads ownership ledger too (note: complete only with H3 in Wave B) — partial: fixed@465cdcd for install.sh (guard now also refuses on a non-empty ownership.json ledger, with a NOTE comment saying so); remains incomplete until Wave B's H3 makes per-page edits actually write that ledger — today a desktop changed only via the per-thing pages still reads as clean to this guard
- [x] M16 verify.sh/CI/PKGBUILD check() wrapped in dbus-run-session (AS5 backend-ask half → Wave A) — fixed@ca88c0e,f6486ff (verify.sh + both CI jobs + release.yml), fixed@b2dbf81 (PKGBUILD + PKGBUILD-git check() wrapped, checkdepends+=dbus — this closed a must-fix from review that found both packaged checks still ran pytest bare against the new dconf tier). AS5 (settings phase asks the backend, not the env) is out of Wave 0 scope by design, deferred to Wave A.
- [x] M20 sandbox tier split: write-parity + dconf round-trip runnable in CI under private dbus — fixed@ca88c0e (new `dconf` marker, `SandboxSession.start_bus_only()`; 42 tests moved out of `sandbox` into the default/CI run; 28 headless-gnome-shell tests remain `sandbox`-only)
- [x] L9 PR template index command corrected — fixed@4f9f9d0
- [x] L10 jinja2 dep dropped (pyproject + PKGBUILD + packaging test) — fixed@465cdcd (PKGBUILD depends),ca88c0e (pyproject + stronger dependency-guard test); bin/gtheme:10 still names jinja2 in a comment only, not a dependency — left as-is, noted by harness agent
- [x] L11 version single-source (__init__ ↔ PKGBUILD ↔ metainfo) — fixed@465cdcd (all three now 2.0.0, each with a comment naming the other two pending the v2.0.0 tag)
- [x] L12 verify.sh preflight checks ruff too — fixed@ca88c0e
- [x] L13 SECURITY.md op-count claim corrected to the stronger true claim — fixed@4f9f9d0
- [x] M24 README removal instructions name --uninstall + full leftover list — fixed@4f9f9d0
- [x] U9 English-only stated honestly + localized .desktop Name/Comment/Keywords + xml:lang metainfo (full gettext = deferred) — fixed@465cdcd (data files: de/pt_BR/es/fr GenericName/Comment/Keywords + xml:lang metainfo entries; Name[xx] deliberately omitted, "Gtheme" is a proper noun, noted in a .desktop comment), fixed@b2dbf81 (README's English-only row corrected after review found it contradicted the localized search words the same wave shipped — now scoped to interface text only, launcher/store listing named as already searchable in 4 languages). Full gettext/i18n of the app UI remains deferred per the original scope and the Deferred section below.
- [x] X5 install.sh venv failure branch gives per-distro commands — fixed@465cdcd
- [x] DOCS §3.4: bug_report.yml `gtheme restore`→`rescue`; theme_submission.yml `gtheme publish` removed; README:303/322 overclaims; README:380/414 + GLOSSARY:86 "Before gtheme" promise made conditional-truthful (re-worded again by U3); SECURITY.md locations table completed — fixed@4f9f9d0, with one instance corrected again at b2dbf81 (see H6 note below)

Review found one item that had drifted worse than "pending" during Wave 0 itself and is tracked under its real ID, not a Wave-0 one: **H6** (Wave C, add-on install overclaim) — the docs pass's SECURITY.md rewrite at 4f9f9d0 introduced a *new* instance of the H6 overclaim ("Add-ons are installed there by GNOME's own installer, never by gtheme directly" — false, `gnome-extensions install` is called directly from the Look path). Fixed for SECURITY.md at `b2dbf81`. H6 is **not** closed: SECURITY.md:64-66, README:323-324 and docs/preset-format.md:249 still carry the original instances and remain Wave C's to fix — do not re-check H6's box in Wave C from this note alone.

## Wave A — core engine (core/, preset/ only; UI halves of these IDs live in Wave B) — CLOSED 2026-08-28
Wave commits: `bb8de6a` (A2), `4df58e1` (A1), `14247f8` (review-fix, C1/H4/H10). Gate green at `14247f8`: 2045 passed, 2 skipped, 28 deselected, ruff clean, `verify.sh: OK` (measured this session).

**Policy-design note (C1/H4):** C1 and H4 did not ship as two separate ad-hoc refusal lists. A1 introduced a single two-tier write policy (`src/gtheme/core/policy.py`): REFUSED destinations/keys (autostart, systemd, environment.d, shell rc files, `.desktop`/`.service` suffixes anywhere, media-keys commands, default-applications exec, keyfile: keys, non-allow-listed dconf trees) are blocked outright at compile+apply time; a CONSEQUENTIAL tier (starship.toml, alacritty/ghostty/kitty/wezterm/tmux/fastfetch config) is allowed but named individually in the preview instead of collapsing into an anonymous file count. The review-fix pass closed a symlink-classification bypass in this same policy module (C1) and a Ptyxis-profile `custom-command`/`use-custom-command`/`login-shell` gap in the dconf allow-list (H4) rather than reopening the two-tier design.

Agent A1 owns transaction.py, preset/compile.py, preset/model.py, preset/placeholders glue:
- [x] C1 file-destination policy (autostart/systemd/rc/starship/.desktop/.service refusal) — fixed@4df58e1 (two-tier policy.py + preflight), fixed@14247f8 (review-fix: symlink-bypass closed — `file_verdict` now takes the worse of the as-written and fully-resolved destination, both directions)
- [x] H4 settings-key policy (media-keys command, default-applications exec, dconf: scope) — fixed@4df58e1 (policy.setting_verdict + dconf allow-list), fixed@14247f8 (review-fix: `/org/gnome/Ptyxis/` tree allow-list gap closed — `custom-command`/`use-custom-command`/`login-shell` explicitly refused for both dconf: and gsettings-path:/gsettings: spellings). Advisory left open (not re-opening the box): `/org/gnome/shell/extensions/` is still a tree-shaped allow-list, so a shell-extension that stores its own exec command in dconf (Executor, Command Menu, Argos) is reachable the same way Ptyxis was — named in review as an inherent limit of a tree allow-list, not fixed this wave.
- [x] H5 confine_src called in compile_preset + re-checked in _rendered + regression test through apply — fixed@4df58e1
- [x] H1(txn) rollback on Exception, ledger restored, real rolled_back re-raised as TransactionError — fixed@4df58e1 (BaseException-only-flush behavior deliberately unchanged — verified against 3 crash-survival tests that require it, see commit for reasoning)
- [x] H9 rolled_back &= not cleanup_changed; no re-point at stripped Look; tidy-up narrated — fixed@4df58e1
- [x] M1 cleanup warnings/kept/dead surfaced on TransactionResult — fixed@4df58e1
- [x] M2 no-op ops not claimed (or orphan-without-baseline = satisfied) — fixed@4df58e1
- [x] M12 unresolved value tokens skip the op — fixed@4df58e1
- [~] L4 add-on install skips reported without session bus — fixed@4df58e1
- [~] L8 min_shell compared at plan/apply; doc aligned — **partial**: engine half fixed@4df58e1 (`compile.shell_warning()` + `compile_preset(shell_version=...)`); UI half NOT done — `ui/pages/looks.py:build_apply_plan` never passes `shell_version`, so the warning cannot fire in the running app. ~2-line follow-up, explicitly deferred to whoever picks up Wave B's looks.py (B2/U4 territory per A1's own concern list). Do not tick fully closed until that lands.
- [~] X1 captured-Look add-on settings apply AFTER extension install (phase order/two-pass) — **partial**: engine half fixed@4df58e1 (install phase hoisted above settings + above the no-session guard, `installer` seam added to Transaction). Real installer wiring (so one Apply both installs and configures an add-on) is explicitly deferred to Wave C / C2 (`ego/install.py` + `looks.py`); until then the user-visible symptom (install, then a second Apply) persists. Also carries an advisory from review: the reorder lets an install-only apply satisfy the AS4 "nothing changed" gate and report success — only reachable once Wave C wires a real installer; note for whoever does.
- [x] M16-AS5 settings phase gate asks the backend, not the env — fixed@4df58e1 (`core.backends.can_write_settings`, AutoBackend implements it; advisory: SubprocessBackend/GioBackend used bare in a session-less context now hard-fail per-key instead of skipping gracefully — ~4-line follow-up noted, not required for this wave's scope)
Agent A2 owns settings_backend.py, gvariant.py, baseline.py, restorepoints.py, core tests:
- [x] H7 never-written dconf path = writable unset, not missing — fixed@bb8de6a (new `BackendErrorKind.UNSET`; backend + baseline + restorepoints sides), confirmed by A1's transaction-side mapping in 4df58e1 (shared contract, both halves verified together)
- [x] L2 GioBackend.reset read-back verify — fixed@bb8de6a (SubprocessBackend.reset deliberately left without read-back — no reliable way to distinguish "no user value" from "effective default" for that backend; noted as a known parity gap, not a miss)
- [x] H1(baseline) record_file/record_setting I/O failures → TransactionError — fixed@bb8de6a (new `BaselineError`, deliberately not an `OSError` subclass — flagged to Wave B: `except OSError` in apply_ops (M3) will NOT catch it, must reach A1's rollback handler)
- [x] H10 v1 importer: symlink → {"link": target}; missing blob → omit dest (synthetic v1 fixture test) — fixed@bb8de6a (importer half), fixed@14247f8 (review-fix: sibling bug in `restorepoints.capture()` closed — copy2/readlink failure on a file that DOES exist was still recording `None` → `FileRemove`, i.e. Undo would delete a file that failed to copy rather than leaving it alone; same warn-and-omit shape now used on both sides)
- [x] M14 manual capture unions ledger-claimed keys — fixed@bb8de6a
- [x] L1(core) RestoreResult carries rolled_back — fixed@bb8de6a (UI branch is Wave B3's L1(ui), unaffected)
- [x] L18(core) Baseline.wipe deleted — fixed@bb8de6a (verified zero callers repo-wide before deleting; UI half L18(ui) remains Wave B4's)
- [x] M18 restore-failure test made real (fail after something landed; no tautology) — fixed@bb8de6a (mutation-checked: reverting `_roll_back`'s settings leg to a no-op turns the rewritten test red)
- [x] M19 rescue failure-path tests (exit 1 preserves records; LockBusy) — fixed@bb8de6a (mutation-checked: hoisting `write_ledger({})` above the `if stuck:` guard in rescue.py turns the new test red)

**Not fully closed — do not re-tick without doing the remaining work:** L8 (UI half, looks.py), X1 (Wave C real installer wiring). Everything else above is fully fixed and gate-verified.

**Re-baselined verify numbers (measured this session at HEAD `14247f8`):** `--collect-only`: 2047/2075 collected (28 deselected); `verify.sh`: 2045 passed · 2 skipped · 28 deselected · ruff clean · `verify.sh: OK`. Delta from the prior baseline (1960 collected / 1958 passed): +115 collected total across the wave — A2's bb8de6a (+26), A1's 4df58e1 (+42 net: two new regression files, test_look_write_policy.py=29 + test_apply_contract.py=13), review-fix 14247f8 (+13: 6 C1 symlink cases, 5+4 H4 Ptyxis-key cases, 3 H10 capture-omission cases — some overlap between A1's declared 42 and the review-fix's 13 additive cases, both verified independently against a before/after diff in this session). No skip/deselect count moved (2 skipped, 28 deselected, unchanged from the prior baseline), so no harness/marker change occurred this wave. No existing test was weakened to get green — every changed (not just added) test in this wave is argued in-place by its author and independently spot-checked by the reviewer's before/after diff runs (see `.audit/review-report.md` Wave A section).

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
