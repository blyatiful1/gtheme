# Audit-fix campaign ledger (v2 — after plan-critic)

Branch `audit-fixes`, worktree `/home/crocco/gtheme-fixwork`, base `b9e60c9`.
Specs: `.audit/review-report.md` (C/H/M/L IDs) and `.audit/persona-report.md` (§2.1–§2.10 = U1–U10). X-IDs below are §3 items promoted by the plan-critic.
Rule: every ID ends `fixed@<sha>` or `deferred: <reason>`. Agents commit their OWN files (flock `/tmp/gtheme-commit.lock`, `git commit -- <owned files>`, IDs in message). FIXLOG statuses updated + committed by each wave's integrator.

**Verify baseline (update whenever the harness legitimately changes it):** 2591 collected · 2570 passed · 2 skipped · 28 deselected · ruff clean · `verify.sh: OK` (measured by the Wave CD integrator at HEAD `e66183c`, after Waves 0+A+B+infra+port+CD all landed on audit-fixes). Delta from the prior baseline (2390/2360/2/28 at b09ea6e): +201 collected/passed across CD1-CD4 (bc928c9 +39, d7b9f85 +38, 11f28db +45, 13db4d7 +79) plus +8 from CD5's review-fix (e66183c) — reconciles exactly against each agent's self-reported delta. Skipped (2) and deselected (28) unchanged throughout, confirming no test was skipped, deselected, or removed across the wave. Historic: prior baseline 2390/2360/2/28 at b09ea6e; Wave 0 close 1960/1958/2/28 at b2dbf81; pre-campaign 1967/1895/2/70.
Earlier note kept for history: (worktree venv, 2026-08-28, measured at HEAD b2dbf81 after Wave 0 close). Prior baseline 1967/1895/2/70; delta is Wave 0's own (M20 moved 42 dconf tests out of the `sandbox` marker into the default run; +21 new collected items — 20 from tests/unit/test_docs_commands.py, 1 from the L10 dependency guard). Full repo with no marker filter: 1988 items total.
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
- [x] L8 min_shell compared at plan/apply; doc aligned — engine half fixed@4df58e1 (`compile.shell_warning()` + `compile_preset(shell_version=...)`); **UI half closed@835cf28** ("L8-remaining", Wave B2) — `ui/pages/looks.py:build_apply_plan` passes `shell_version=self._shell_version()` (looks.py:1947), so the warning fires in the running app. This closure was already on disk since Wave B but never recorded here; found and closed in FIXLOG bookkeeping by the Wave CD integrator.
- [x] X1 captured-Look add-on settings apply AFTER extension install (phase order/two-pass) — engine half fixed@4df58e1; **UI wiring closed@d7b9f85** (Wave CD2, tracked as X1-wiring) — `LookAddons` is the callable filling `Transaction`'s Wave-A installer seam, constructed only after the "Get them and use this look" press and attached inside `_apply`'s `work()`; a plain apply leaves `transaction.installer` unset. One Apply now both installs and configures an add-on; the old two-change flow (batch, re-preview, second apply) is gone. Advisory carried forward, not re-opened: the reorder still lets an install-only apply satisfy the AS4 "nothing changed" gate and report success — nobody has touched that gate yet.
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

**L8 and X1 are now fully closed** (see notes above — L8's UI half was already on disk since Wave B2/835cf28 and just needed recording; X1's real installer wiring landed at Wave CD2/d7b9f85). Everything in this wave is fully fixed and gate-verified.

**Re-baselined verify numbers (measured this session at HEAD `14247f8`):** `--collect-only`: 2047/2075 collected (28 deselected); `verify.sh`: 2045 passed · 2 skipped · 28 deselected · ruff clean · `verify.sh: OK`. Delta from the prior baseline (1960 collected / 1958 passed): +115 collected total across the wave — A2's bb8de6a (+26), A1's 4df58e1 (+42 net: two new regression files, test_look_write_policy.py=29 + test_apply_contract.py=13), review-fix 14247f8 (+13: 6 C1 symlink cases, 5+4 H4 Ptyxis-key cases, 3 H10 capture-omission cases — some overlap between A1's declared 42 and the review-fix's 13 additive cases, both verified independently against a before/after diff in this session). No skip/deselect count moved (2 skipped, 28 deselected, unchanged from the prior baseline), so no harness/marker change occurred this wave. No existing test was weakened to get green — every changed (not just added) test in this wave is argued in-place by its author and independently spot-checked by the reviewer's before/after diff runs (see `.audit/review-report.md` Wave A section).

## Wave B — UI truth & safety (parallel by file, then serial consolidator) — CLOSED 2026-08-28
Wave commits: `e2d0f30` (B1), `835cf28` (B2), `666b415` (B3), `2d23aa1` (B4), `7fd2fca` (review-fix: M3/H2 post-ops OSError, U8 toast-names-the-moment). Gate green at `7fd2fca`: 2186 passed, 2 skipped, 28 deselected, ruff clean, `verify.sh: OK` (measured this session, worktree venv).

B1 rows.py, panels/widgets.py, colors/icons/fonts/wallpaper write paths, _style_common:
- [x] H3 rows through coalesced recording backend: first-touch Baseline record + MANUAL_OWNER ledger claim + ONE coalesced restore point per edit burst + LockBusy handled; NO per-toggle Transaction (cap-eviction trap) — fixed@e2d0f30 (new `ui/widgets/recording.py`, `RecordingBackend`; every descriptor-row write/reset routes through it). Advisory not re-opened: burst coalescing rewrites the restore-point document once per key (26 small JSON writes for one effect-picker selection — bounded, correct, flagged as the heaviest single interaction in the app); a burst spanning an intervening Look apply can mix vintages in "Before your changes" (sound reasoning, deserves a deliberate policy decision in a later wave, not a defect); `first_touch_value()` re-parses the whole pristine index on every reset-row refresh (perf note for Wave C).
- [x] M3 apply_ops catches OSError — **fixed@e2d0f30, corrected@7fd2fca**. B1's original arm unconditionally claimed "your desktop is exactly as it was", which review's must_fix proved false (reproduced in-process: a late `Baseline.save()` OSError after the op already landed). Review-fix closed both sides: `core/transaction.py` now guards the two post-ops writes (`baseline.save()` and the closing ledger `write_entry`) so a late OSError becomes `TransactionError(rolled_back=False)` instead of escaping bare, and `_style_common.apply_ops`'s OSError arm now states only the reason with no state claim. Residual named, not fixed: `_apply_locked`'s AS4 switch-cleanup branch (`self._restore_ledger(...)`) can still raise a bare OSError after a cleanup already changed the desktop — no longer a lie (nothing downstream claims a state), but not a full narration either; left for Wave C.
- [x] M7 row write BackendError → refresh to truth + reason surfaced — fixed@e2d0f30. One gap found by review and left open rather than silently closed: `panels/widgets.py`'s effect picker (~line 446-466) `continue`s past a per-key `BackendError` with no refresh/message, so a store that refuses writes leaves a stale-looking combo with no toast; review's suggested fix (`is_missing(exc)` discriminator) was not applied this wave — flagged for whoever next touches that file.

B2 looks.py, window.py:
- [x] H2(looks) unknown failure defaults rolled_back=False; half-copy reachable; Undo offered — fixed@835cf28
- [x] M6 undo toast requires result.transaction is None — fixed@835cf28
- [x] M15 toasts escape markup — fixed@835cf28 (both Adw.Toast sites; verified by introspection that Adw.Toast:use-markup defaults True and AlertDialog/Label/Expander do not, so those were correctly left alone)
- [x] U4 "Show exactly what changes" expander (before → after; DiffEntry frozen-contract amendment explicit+justified); file destinations + add-on names listed — fixed@835cf28
- [x] U8 undo = Adw.ButtonContent with label, packed from window construction; Ctrl+Z → confirm_apply, editable-focus guard; toast names the moment — **header/shortcut half fixed@835cf28 + 666b415; toast-names-the-moment half was NOT actually done despite both agents ticking it (B3 explicitly skipped it, B2 delivered only the tooltip) — closed by review-fix@7fd2fca**, which added `restore.done_sentence(point)` routed through `point_title()` and wired it into all four success-toast sites (restore.py, home.py, window.py, and a fourth site in looks.py that the must_fix didn't enumerate but fails the same acceptance line). Do not re-open on B2/B3's original claims; the acceptance line is met only as of 7fd2fca.
- [x] L6 header undo independent of Home page — fixed@835cf28. Known trap left in place, not silently dropped: `home.py`'s own "Undo the last change" row (`HomePage.undo_last_change`) still applies the newest moment with no confirmation/preview, while the header button and Ctrl+Z both now confirm via `RestorePage.confirm_undo_last` — same label, two behaviours. `home.header_button` is now dead in production (only tests call it) after `_pack_undo_button` was removed. Flagged for Wave C/F, not required by L6's stated scope.
- [x] X3 _capture_restore_point OSError surfaced (no silent proceed); point.warnings shown — fixed@835cf28 (required touching `core/transaction.py`, outside B2's declared file list — checked clean, no collision). Sibling half named as unowned by review and left unfixed: `core/restorepoints.py::apply_point` still catches only `TransactionError`, so the same OSError class can escape an *undo* (guarded on the threaded path by `RestorePage._failed`'s cautious default, unguarded on `start_apply`'s no-runner branch) — a Wave C/D follow-up, not claimed fixed here.

B3 restore.py, home.py, topbar.py, windows.py, more.py, addons.py:
- [x] H2(restore) on_failed two-branch honest wording — fixed@666b415 (same fix applied to home.py's identical bug, P1 pattern)
- [x] H11 manual moments pass dests (ledger destinations) — fixed@666b415, proven end-to-end by a real-engine regression test
- [x] L1(ui) RestorePage._report branches on rolled_back — fixed@666b415
- [x] M10 restore save via runner (+ onboarding first-point) — fixed@666b415
- [x] M5 addons failed-enable resets switch (not NEEDS_RELOGIN) — fixed@666b415 (uncovered and fixed a real pre-existing suppression bug in the same code path: a switch flipped from inside another notify::active handler was reading its own correction as a user toggle)
- [x] M30 topbar/windows filter corpus problems to own domains — fixed@666b415. Judgment call flagged for a second opinion, not silently resolved: the page still raises when NOTHING it renders loaded at all (an empty page with no message would be a lie of omission) — a two-line deletion if a future gate wants literal never-raise.
- [x] L5 more-page floor group hides when empty — fixed@666b415
- [x] L7 no-runner double report fixed — fixed@666b415

B4 serial consolidator (cross-file):
- [x] M28 one banner helper, nine call sites — fixed@2d23aa1. Audit undercounted the call sites (nine named, eleven found and consolidated: addons.py has two, looks.py is the eleventh). Corrects the audit's `Adw.Banner:use-markup` claim: it defaults FALSE (measured this session, libadwaita 1.9.3), so the two sites the report said were "escaping and therefore wrong" were actually the two rendering correctly, and the fix (route everything through one `set_plain_text` path) is right regardless — recorded as measured truth in the code, not the report's claim.
- [x] M29 one scaffold constant pair + PageShell.group plain-text + Windows wording — fixed@2d23aa1 (a fourth hardcoded site beyond the audit's three found and fixed: wallpaper.py:428)
- [x] L15 accent table single source — fixed@2d23aa1
- [x] L16 shared banner/action-row helpers — fixed@2d23aa1 (`Adw.ActionRow:use-markup` confirmed True by introspection, so this consolidation also closed a live markup hazard, not just a duplication)
- [x] L19 one gvariant quote/unquote pair — fixed@2d23aa1. Audit undercounted here too (five named, eight hand-rolled copies found and removed). Also fixed a real latent bug the audit called "not live": `quote`/`unquote` did not actually round-trip a backslash; `unquote` is now the true inverse via GLib parsing.
- [x] M17 apply_ops success+failure tests — fixed@2d23aa1 (four real Transaction-driven tests, mutation-checked)
- [x] L18(ui) SchemaProbe.source_for_row, Prefs.as_dict, PageShell.built_ids resolved (delete or write the claimed test) — fixed@2d23aa1 (all three deleted after verifying zero callers repo-wide; `built_ids`'s claimed guarantee is proven instead by the existing RowIndex tests, which is the mechanism actually used)

**Review must_fix, both closed at `7fd2fca` (see notes on M3 and U8 above):**
1. `_style_common.apply_ops`'s OSError arm made a state claim (rolled_back=True) it could not know was true for a post-ops OSError — fixed, both UI arm and the `core/transaction.py` source of the escape.
2. U8's toast-names-the-moment half was ticked "fixed" by two agents without actually landing — fixed, four toast sites now route through `point_title()`.

**M21 (Wave 0) dependency now satisfied:** M21's install.sh ledger guard was marked partial pending "Wave B's H3" making per-page edits write the ownership ledger. H3 (`e2d0f30`) does this — every recorded row write claims its key for `MANUAL_OWNER` in the same ledger `install.sh --uninstall` reads. **M21 should be re-verified and closed** by whoever next touches Wave 0/closure bookkeeping; not re-ticked here because M21 lives in the Wave 0 section and is not one of this wave's owned IDs.

**Re-baselined verify numbers (measured this session at HEAD `7fd2fca`):** `--collect-only`: 2188/2216 collected (28 deselected); `verify.sh`: 2186 passed · 2 skipped · 28 deselected · ruff clean · `verify.sh: OK`. Delta from the Wave A baseline (2047/2075 collected): +141 collected across the wave (B2 +37, B3 +34, B1 +28, B4 +37, review-fix +5), independently re-traced commit-by-commit this session by checking out each wave SHA and re-measuring `--collect-only` (chain: b2dbf81=1960 → waveA-close 5024dc7=2047 → B2 835cf28=2084 → B3 666b415=2118 → B1 e2d0f30=2146 → B4 2d23aa1=2183 → reviewfix 7fd2fca=2188). Skipped (2) and deselected (28) unchanged at every commit in the chain — no test hidden or quarantined anywhere in Wave B. No git state left modified; worktree clean at HEAD `7fd2fca`; sibling live checkout `/home/crocco/gtheme` untouched; gtheme app never launched.

**Not fully closed / flagged for later waves (do not re-tick without doing the work):**
- M7's effect-picker `BackendError` gap in `panels/widgets.py` (silent `continue`, no refresh/toast) — Wave C.
- X3's sibling half in `core/restorepoints.py::apply_point` (same OSError class unguarded on undo) — Wave C/D.
- M3's residual AS4 switch-cleanup OSError path in `_apply_locked` — Wave C.
- L6/U8's home-page "Undo the last change" row still applies unconfirmed while the header/Ctrl+Z path confirms (P1 pattern); `home.header_button` now dead in production — Wave C/F.
- `docs/architecture.md:62` ("transaction.py is the only path by which anything changes") still literally false for page edits — one-line doc fix, unowned this wave.
- wallpaper.py's custom-picture file copy sits outside the H3 burst point (undo restores the setting, leaves the copied file) — out of H3's stated scope, flagged not fixed.

## Parallel waves (user-requested), branched from 5024dc7, merged at 05ed1b5 + b09ea6e — CLOSED 2026-08-28
Merged tree verified by the orchestrator: 2360 passed / 2 skipped / 28 deselected, verify.sh: OK at b09ea6e. One merge conflict (cli.py docstring, apply-paragraph vs applog-paragraph) resolved keeping both.
**infra branch** (commits 906b923, ad46328, ace2f3e, a0d0043; own gate green 2103/2/28; review caught + fixed an M25 search-order regression and H6's brief_for reopening the M4 stall class):
- [x] M4 missing gnome-extensions binary fast-fail — fixed@ad46328 (+a0d0043)
- [x] M25 data_dir sys.prefix + XDG_DATA_HOME — fixed@ace2f3e (+a0d0043 ordering fix)
- [x] M27 corpus/dispositions memoised with reload() — fixed@ace2f3e
- [x] M13 blur-my-shell × intellibar hazard entry — fixed@ace2f3e
- [x] U5-infra rotating log + excepthook (applog) — partial@906b923, **closed@11f28db** (Wave CD3): About dialog's libadwaita Troubleshooting/debug_info page + a "Copy details for a bug report" main-menu item (`win.copy-details`) both surface applog's last 40 lines, matching U5-button.
- [x] H6 add-on naming — partial@ad46328, **closed@d7b9f85 + e66183c** (Wave CD2 + CD5 review-fix): `ApplyPlan.addon_lines`/`describe_addons` render every missing add-on's title/author/source offline in the preview dialog, before a single byte downloads; a review must_fix found the dialog had grown a silent online lookup (`name_addons` calling `describe_batch`) that broke the "only goes online when you ask" promise — CD5 dropped that call entirely, so the preview stays fully offline and the offline naming still satisfies H6. SECURITY.md's stale "Get the missing ones" button label also corrected to "Get them and use this look" (H6-label, e66183c), with a new test keeping the two in sync. "First-install via GNOME's own box" was explicitly considered and deliberately skipped by CD2 (would put an interrogation back on the batch path) — that was always the "considered", not required, half of H6.
- [x] U6 conflict table entries (ubuntu-dock, tiling-assistant) — partial@ace2f3e, **closed@d7b9f85** (Wave CD2): `conflict_lines()` runs `active_conflicts` over current-enabled ∪ Look-enabled extensions and renders `replacement_question()` into the apply-confirm dialog for any Look that would introduce ubuntu-dock/tiling-assistant-style conflicts; also delivered plan-time value validation (icon/cursor/gtk/font vs. what's actually installed) and accessibility-write warnings (high-contrast/text-scale/reduced-motion), both originally scoped to Wave D3's U6.
**port branch** (commits dccddf3, fba562e, 5cc1898, 70a371d, 6856845; own gate green 2161/2/28, index fresh with 6 Looks; review caught + fixed: bundled file contents leaking home paths, path traversal via ledger-claimed rel paths, duplicate jargon save-notes, tests reading the real desktop):
- [x] U7-capture whole-desktop capture + omissions list — fixed@5cc1898 (+6856845), **omissions dialog rendering closed@d7b9f85** (Wave CD2, U7-UI): "Save this Look to a file…" exports a `.gtheme.zip` through a hidden-partial-then-rename write (no half-written file survives a failure); the save-notes dialog renders `CaptureResult.omissions` grouped by kind (Files/Settings/Colours/A picture), filtering the prose duplicates out of `warnings`.
- [x] U7-cli gtheme apply <name|path> [--dry-run] — fixed@fba562e
- [x] L3 share scan genericises dest_root() — fixed@5cc1898
- [x] U2 core (honest provenance, browse filter, screenshot fetch seam) — partial@dccddf3, **Looks-page grid closed@d7b9f85** (Wave CD2, U2-UI): the browse grid now uses `registry.browsable()` so an all-bundled library really does reach the "Nobody has published a Look yet" empty state; tiles fetch real community screenshots with the palette card as a loading fallback; "Add a Look from a file…" installs a zip or folder through `look_from_archive()` + `registry.install_look`, the same confinement/staging/replace-question path a download uses. Known wart carried forward, not this wave's to fix: `install_look` hardcodes provenance "community", so a Look imported from your own backup badges as community-sourced (registry.py ownership).
- [x] U2 content (light DAYBREAK + warm HEARTH Looks, index regenerated) — fixed@70a371d
**M21 dependency closed:** Wave B's H3 makes per-page edits write the ownership ledger, so the Wave 0 uninstall guard now sees page-only-changed desktops — M21 is complete as of the merge (verify covers both halves).

## Wave CD (replaces Waves C+D after the parallel split) — terminal, looks/window UI halves, product features — CLOSED 2026-08-28
Wave commits: `bc928c9` (CD1/terminal), `d7b9f85` (CD2/looks+compile), `11f28db` (CD3/window+app infra), `13db4d7` (CD4/a11y+contrast+product), `e66183c` (CD5, review-fix: E5/U3/E2/H6-network/H6-label). Gate green at `e66183c`: 2570 passed, 2 skipped, 28 deselected, ruff clean, `verify.sh: OK` (measured by the wave integrator; see re-baselined numbers below).

C1 terminal/ package + ui/pages/terminal.py (agent CD1):
- [x] H8 adapters return ops; Terminal page applies via one Transaction (snapshot/ledger/lock) — fixed@bc928c9. Adapters gained `plan()` returning `TerminalWrites` (FileChange/SettingChange), replacing `apply()`; `apply_all` builds one `Transaction` from every chosen adapter's ops (Baseline record, MANUAL_OWNER ledger claim, restore point, process lock, rollback all shared with the rest of the app). fish is a named, documented exception (its store is reachable only by running fish; runs after the transaction under the same lock, with `fish_variables` recorded into the pristine Baseline first — NOT covered by the transaction's own restore point, so Undo does not reach it though `gtheme rescue` does). Frozen-contract amendment argued in `terminal/model.py` and pinned by `test_contracts_frozen.py`.
- [x] H12 per-adapter Exception isolation in apply_all; page handler wrapped — fixed@bc928c9. Plan phase and run phase each catch `Exception` per adapter; a transaction failure blames every planned adapter and states whether it rolled back; the page's Apply/Take-over handlers are wrapped in `_guarded` (toast + applog). Trade-off named, not hidden: refusals are still per-adapter (found before any byte is written), but a genuine write failure now fails and rolls back the whole terminal batch — the price of one shared transaction, judged safer than the old half-applied-and-silent behaviour.
- [x] M11 palette built via read_palette fallback (no cached error page) — fixed@bc928c9. `palette_from_look` goes through `read_palette`, so a malformed colour value yields the existing "no colours from this Look" branch instead of raising; `_ansi` drops the whole 16-colour set on one bad entry rather than shipping a partial set.
- [x] L17 detect() once, state passed down — fixed@bc928c9. `installed(backend)` returns `[(adapter, TerminalState)]`; `_adapter_group`/`_foreign_notice` consume the passed state instead of re-scanning. `detect()` now runs exactly once per adapter per page open (was 2-3).
- [x] E1 (Wave F item, delivered here) gnome-terminal + Console adapters — fixed@bc928c9. New `terminal/gnometerminal.py` (relocatable-schema profile writes, per-key probed against the schema on this machine) and `terminal/console.py` (transparency only, states out loud that Console keeps its own colour schemes). Unverified against a real installed `gnome-terminal`/`kgx` (neither is on this machine) — flagged for a real-box check before release, mitigated by per-key probing and 21 tests against compiled-for-the-test schemas.

C2 ego/install.py + looks.py glue (agent CD2, amended by CD5):
- [x] H6 add-ons named (uuid/title/source) before download; docs corrected; first-install via GNOME box considered — fixed@d7b9f85, **amended@e66183c**. `ApplyPlan.addon_lines`/`describe_addons` name every missing add-on (title, author, source) from this computer alone, before a single byte downloads. CD2's first cut also had the dialog upgrade those names to the library's real titles once open (`describe_batch`/`name_addons`) — review's must_fix found that call broke the documented "only goes online when you ask" promise (opening a preview is not asking); CD5 dropped `name_addons` and its call entirely, so the preview is fully offline again and H6's naming guarantee still holds on the offline data alone. SECURITY.md's stale "Get the missing ones" button label corrected to "Get them and use this look" (e66183c), with a new test (`test_security_md_quotes_the_button_that_is_really_on_screen`) keeping the two in sync going forward. "First-install via GNOME's own box" was considered and deliberately not done (would put an interrogation back on the batch path) — recorded, not silently dropped.
- [x] M4 missing gnome-extensions binary → CommandResult(127), no 180s stall — **already fixed@ad46328** (infra branch, parallel waves, before Wave CD started). This Wave-CD line was stale bookkeeping carried over from before the parallel split; no Wave CD agent touched it and none needed to.
- [x] M9 unpack/install off the main loop — fixed@d7b9f85. New `MainLoopClient` marshals only the libsoup legs onto the main loop via `idle_add`; `AddonBatch.run_and_wait(bridged=True)` runs the batch (and its blocking unzip/`gnome-extensions install` subprocess) on the runner's worker thread. Verified with a test driving the batch from a worker thread while the main thread pumps the context.
- [x] M8 look tiles via thumbnail cache — fixed@d7b9f85. `_picture_tile()`/`_texture_for()` use `lookup_cached_thumbnail`/`request_thumbnail_async` with a module-level texture cache keyed by (path, mtime), surviving `reload()`.
- [x] E5 apply progress (per-step feedback) + cancel affordance where safe — fixed@11f28db (Wave CD3), **corrected@e66183c** (Wave CD5, review-fix). `ProgressDialog` (Adw.AlertDialog subclass) shows a step list, a progress bar, and a Stop button offered only once work has actually narrated. Review's must_fix caught a real bug: a Stop pressed during an add-on download was silently swallowed by `except Exception` arms in `LookAddons.__call__`/`Transaction._install_extensions`, so the dialog said "Stopping. Putting back anything that had already changed…" while the apply actually ran to completion and reported success. Fixed by moving `Stopped` into a shared `core/stop.py` and re-raising it ahead of those broad `except Exception` arms at both seam sites, and by no longer having the stop-pressed label claim a rollback that may not be happening. Verified end to end: a Stop during a real `Transaction.apply` run now returns `rolled_back=True` and the file the Look had already written is gone.

C3 window.py, app.py, panels/loader.py, panels/conflicts.py, prefs (agent CD3):
- [x] M26 startup reads ShellVersion without ListExtensions round-trip — fixed@11f28db. `_bare_shell_version()` reads `ShellVersion` off a bare GDBus proxy instead of the lazy `shell` property (whose `_connect_shell()` does a blocking `ListExtensions`); `_offer()` made lazy per-page. Residual named: Home page's own `addon_summary()` still calls `shell.load()` in `__init__`, so opening Home specifically still costs one round trip — that call lives in home.py, not this agent's file, and is the "first real use" the audit's own text points at.
- [x] M27 corpus/dispositions memoised (reload() for tests) — **already fixed@ace2f3e** (infra branch, parallel waves, before Wave CD started). Stale carried-over line; not Wave CD's work.
- [x] M25 data_dir checks sys.prefix + XDG_DATA_HOME — **already fixed@ace2f3e** (infra branch, parallel waves, before Wave CD started). Stale carried-over line; not Wave CD's work.
- [x] L14 sidebar prefs writes batched (save on close/idle) — fixed@11f28db. `show_page()` writes `window/last-page` with `save=False`; the one durable write is the existing `_save_window_state()` on close. Trade-off recorded: a SIGKILLed app loses the last-page memory, matching the existing size/maximised prefs behaviour.
- [x] M13 blur-my-shell × intellibar hazard entry — **already fixed@ace2f3e** (infra branch, parallel waves, before Wave CD started). Stale carried-over line; not Wave CD's work.
- [x] X2 unreadable shell version ≠ permission to proceed (safe gate screen) — fixed@11f28db. `check_desktop(..., adw_version=...)`: libadwaita < 1.9 or GNOME < 49 → "too old" screen; both unreadable → a distinct "could not tell" screen; an unreadable *shell* version with a healthy libadwaita still proceeds (deliberate — the widgets the sidebar needs demonstrably exist), so the decision moved to the thing that actually crashes.
- [x] X4 About: support/help URL + "Copy details" — fixed@11f28db. `about_dialog()` sets `support_url` (metainfo help page) plus `debug_info`/`debug_info_filename` (libadwaita's own Troubleshooting page with its copy button).
- [x] U5-infra rotating log ~/.local/state/gtheme/v2/gtheme.log + excepthook — partial@906b923 (infra branch), **closed@11f28db** (Wave CD3, tracked as U5-button): a main-menu item "Copy details for a bug report" (`win.copy-details`) copies gtheme version + GNOME version + libadwaita/GTK/Python + the last 40 lines of the applog file, and the same content is one click away via About's Troubleshooting page. No setting values in either.
- [x] E10 addons shell connection re-probe affordance (copy no longer lies) — fixed@11f28db. All three unavailable screens (installed/updates/discover) get a real "Ask again" button, wired to a live re-probe through the shared `ApplyRunner` and `Window.adopt_shell()` (closes the old connection, refreshes Home's add-on line, rebuilds the lists) — chosen over the "reopen the app" fallback because the re-probe is fully re-runnable and safe.
- [x] E6 (Wave F item, delivered here) "last change did not finish" launch notice from leftover journal — fixed@11f28db. Detects a leftover `gtheme-rollback-*` journal belonging to this user (none held by another gtheme process) and offers "Put things back" → `undo_last_change()`; answered choices are remembered (capped at 10) and never re-asked.

## Wave D — product features — CLOSED 2026-08-28 (delivered inside Wave CD, see commits above)
D1 preset capture/share/portability (+ L3), agent CD2 unless noted:
- [x] U7 Export Look… / Add a Look from a file… / `gtheme apply <name|path> [--dry-run]` / save toast names folder / capture_share includes gtheme-written files + [palette] (or states omissions) — CLI half fixed@fba562e (port branch), whole-desktop capture fixed@5cc1898+6856845 (port branch), **dialog/UI half closed@d7b9f85** (tracked as U7-UI): "Save this Look to a file…" exports a `.gtheme.zip` through a hidden-partial-then-rename write; save toast names the folder; save-notes dialog renders `CaptureResult.omissions` grouped by kind, filtered against `warnings` so nothing is said twice.
- [x] H13 capture_keys mirrors descriptor_keys (compound incl. color-scheme; floor exclusion explicit) — fixed@d7b9f85. New `panels/keyset.py` derives both `restore.descriptor_keys` (724 keys, byte-identical to the old derivation) and `looks.capture_keys` (558 keys, was 550 — the 8 new compound keys include `color-scheme`) from one source differing by one named argument; floor exclusion is an argued constant (166 keys), not an accident. Reviewer independently re-derived the old function from a `d162f0c` checkout and confirmed the 724/558/166 figures.
- [x] L3 share scan genericises real dest_root() — **already fixed@5cc1898** (port branch, before Wave CD started). Stale carried-over line.
D2 registry/get-more + content:
- [x] U2 provenance filter (honest empty state) + community screenshots fetched + entry_for provenance honest + one light Look authored (index regenerated; screenshot = generated wallpaper for now) — core half fixed@dccddf3 (port branch), content half fixed@70a371d (port branch, DAYBREAK+HEARTH), **grid half closed@d7b9f85** (tracked as U2-UI): browse grid uses `registry.browsable()` so an all-bundled library really reaches "Nobody has published a Look yet"; tiles fetch real screenshots with the palette card as fallback; "Add a Look from a file…" installs through the same confinement/staging path as a download. Known wart, not this wave's to fix: `install_look` hardcodes provenance "community" (registry.py ownership).
D3 first-run + a11y + look-value honesty, agents CD4 (+CD5 for U3's fix):
- [x] U3 real pristine "Before gtheme" captured on first run (kind="pristine", PRISTINE_ID); docs re-worded to match — fixed@13db4d7, **corrected@e66183c**. `onboarding.capture_pristine_point()` runs on first GUI launch over `descriptor_keys()`+`claimed_dests()`, never overwrites an existing point, and defers to the v1 importer on an upgrader's machine. Review's must_fix reproduced a real gap: CLI-applying a Look before ever opening the GUI let a "Before gtheme" point be written over an already-themed desktop, while the docs promised the row unconditionally. Fixed by a fourth guard, `onboarding.already_touched()` (any saved moment, or any ledger entry, under root skips the capture), and by re-qualifying the three doc paragraphs (README:23, README:407-419, GLOSSARY:87) to say the row is left out rather than mislabelled when that happens.
- [x] U6 plan-time value validation via existing scanners (icon/cursor/gtk/font) + conflicts.active_conflicts on Look path + ubuntu-dock/tiling-assistant entries — fixed@d7b9f85 (Wave CD2; see also parallel-waves U6 note above). `compile.Available`/`value_warnings()` cross-check icon/cursor/gtk-theme/font values against `looks.what_is_installed()`'s live scan; `conflict_lines()` runs `active_conflicts` over current ∪ Look-enabled extensions; `accessibility_lines()` reads the plan's own before-values for high-contrast/text-scale/reduced-motion. One narrow known gap, not closed this wave: both mechanisms only recognise the `gsettings:` key spelling, not `dconf:` — the six shipped Looks all use `gsettings:`, so the bundled corpus is covered, but a community/v1-imported Look need not be.
- [x] U10 alternative_text/accessible labels on picture tiles; ShortcutsWindow (Ctrl+?); window clamped to workarea; high-contrast/reduced-motion read before Look writes; contrast check in `gtheme validate` — split across three agents, all closed: window clamp + ShortcutsWindow fixed@11f28db (CD3, U10-window); accessible names/alt-text/captions on wallpaper/icon/pointer/Home tiles fixed@13db4d7 (CD4, U10-pages, looks.py tiles intentionally left to whoever owns that file — noted, not yet done, see concerns below); WCAG contrast_ratio/readable_contrast + `palette_contrast_warnings()` wired into `gtheme validate` fixed@13db4d7 (CD4, U10-contrast); high-contrast/reduced-motion read before a Look writes is U6's `accessibility_lines()` above.

## Wave F — extras + closure
- [x] E1 gnome-terminal + Console adapters (post-H8 ops protocol) — fixed@bc928c9 (delivered inside Wave CD1, see C1 above).
- [x] E2 custom wallpapers join catalogue with readable names; slideshow XML pickable — fixed@13db4d7 (Wave CD4), **doc gap closed@e66183c** (Wave CD5). `wallpaper.record_in_catalogue()` writes `~/.local/share/gnome-background-properties/gtheme.xml` (readable names, de-duplicated, corrupt catalogues rebuilt); custom file filters accept slideshow XML with first-frame validation. Review's must_fix found this new write was undocumented against SECURITY.md's "everything gtheme writes for itself is in one of these" table and README's removal list — CD5 added the row to both and states plainly that, like the picture copies themselves, it is not in the ownership ledger and is left behind by `gtheme rescue`.
- [x] E3 shortcut editor conflict check — fixed@13db4d7. `find_clashes()`/`confirm_replace()` (panels/widgets.py) scan all 175 shortcut keys before a write lands and offer replace/cancel, GNOME-Settings-style, before taking a combination off another shortcut. Known limit, documented: only the first combination of a multi-value key is compared.
- [x] E8 icon-set "only one installed" sentence parity — fixed@13db4d7. `icons.icon_set_description(count)` mirrors `pointer_description(count)`'s three-way wording.
- [x] E9 shortcuts page filter/grouping — fixed@13db4d7. The 175-shortcut page is split into named, collapsed sections per domain with a per-group search filter and a visible "press Ctrl+F" hint; one pre-existing test rewritten to match the new (documented, non-regressive) shape.
- [x] E6 "last change did not finish" launch notice from leftover journal — fixed@11f28db (delivered inside Wave CD3, see C3 above).
- [x] CHANGELOG entry for the whole campaign — fixed in the closure commit below. `## v2.0.0 (unreleased)` gains a `### The audit pass` subsection in the file's own voice, and the three claims elsewhere in that same section that this campaign made false were corrected with it: "exactly three subcommands" → four (`apply` shipped as U7-cli), "Four bundled" Looks → six (DAYBREAK + HEARTH), and the "Three test tiers — 1157 / 381 / 69" line → the four tiers at their measured sizes.
- [x] CLOSURE: per-ID adversarial verification of the full diff; `./verify.sh --full`; final report — done. The closure audit re-checked every ID against the final tree and returned four not fully closed (M7, M26, DOCS §3.4, DOCS-SWEEP); all four were fixed in the gap-fix pass above and re-gated. See the closure stamp at the end of this file.

## Closure gap-fix pass — the four IDs verification found not fully closed

Run after the closure audit re-checked every ID against the final tree. Four
came back open; all four are closed here, each with a test that fails against
the tree as it was.

- [x] **M7** (residual) — `panels/widgets.py` `build_effect_picker`'s per-key
  `except BackendError: continue` swallowed a *refused* write as if it were a
  missing key, so on a locked settings store the picker kept the new selection,
  said nothing, and the desktop played the old animation. Now
  `core.backends.is_missing(exc)` discriminates: an effect this add-on version
  does not have is still skipped quietly; anything else refreshes the row and
  reports the refusal once, exactly like the `WriteRefused` arm beside it. A
  successful run clears a stale refusal (`clear_refusal`). Three tests in
  `tests/unit/test_descriptors_widgets.py`; the two refusal ones fail against
  the old code (`assert 18 == 1`, subtitle unchanged), the "missing key is
  still skipped" one passes both ways on purpose — it guards the fix from
  over-correcting.
- [x] **M26** (residual) — the version half was fixed in Wave CD3, but on a
  fresh machine `Window.__init__` opens **Home**, and building Home read
  `self.shell` (→ `ListExtensions`, GDBus's 25 s default) *and* built a second
  connection of its own. Two blocking round trips inside `Window(...)`, before
  `present()`. Closed in three places: `home.build()` no longer names `shell`,
  so `Window._offer` stops handing it over at construction time; the add-on
  line shows "Counting…" and defers the ask to an idle **after** the window is
  up, doing the listing on a worker thread and borrowing the *window's*
  connection (not a second one) so the two pages cannot disagree;
  `ShellExtensions.loaded` lets `addon_summary` read the map the object already
  keeps live off `ExtensionStateChanged` instead of re-listing. `Window.shell`,
  `adopt_shell` and `teardown` take a lock, because the property now has a
  second caller thread. Six tests across
  `test_window_infra.py`/`test_pages_home_gtk.py`/`test_pages_home_logic.py`;
  all six fail against the old code. Proven on a real desktop as well: the
  regenerated `home-light.png` shows "2 of 27 switched on", i.e. the deferred
  count landed inside a live headless session.
- [x] **DOCS §3.4** — the six MISSING bullets that were still missing are
  written: an accessibility section (README "Getting around without a mouse, or
  without seeing the screen" — honest, including that Orca was never tested), a
  Flatpak/Snap confinement answer that names the boundary and does not pretend
  gtheme can cross it, a "which one wins" answer for gtheme vs GNOME Settings,
  a "Keeping it up to date" section, a "permission denied" answer, and a
  troubleshooting/diagnosis path (Copy details → the log → `GTHEME_LOG_LEVEL` →
  `gtheme validate`). HARD TO FIND closed too: `docs/preset-format.md` is now
  linked from two user-facing sections rather than only from "For people who
  want to help", and `looks.COPY["browse-empty-body"]` — the empty Get-more
  state, which is reachable today — names `theme.toml`, the Looks folder and
  `gtheme validate`. That string passes `ui.jargon.check`.
- [x] **DOCS-SWEEP** — all six false sentences corrected. (1) README:445-449
  and :470 claimed page-by-page edits are not in the first-touch record; H3
  made that false and `install.sh`'s NOTE said the same thing — all three
  rewritten, and the ledger claim in the uninstall guard is now described as
  what it does. (2) "four Looks" → six at all six documented sites, plus seven
  stale code comments saying the same thing (each count re-derived: 3 of 6
  write `starship.toml`, 3 of 6 set a slideshow, `themes/` is 43 MB).
  (3) SECURITY.md's foreign-tool refusal is scoped to the Ghostty card, which
  is the only adapter that computes a `foreign_root`. (4) `architecture.md:62`
  now names all seven op types and states the one deliberate second writer
  (`ui/widgets/recording.py`) instead of a sentence that module's own docstring
  calls false. (5) `:70` credits `onboarding.capture_pristine_point` and
  `:75` separates the ported derivation maths from the WCAG maths added on top.
  (6) `testing.md`'s tier sizes re-measured at HEAD (~1,880 / 42 / ~660 / 28).
- [x] **screenshot blemish** (cosmetic, named in DOCS-SWEEP) — the shipped
  `looks-dark.png` had GNOME's own "Apps now have unrestricted access" banner
  across the app's header bar. It is not incidental: the sandbox harness turns
  on `unsafe_mode` on purpose, and that banner is persistent, so every page
  walk would reproduce it. Fixed at the source —
  `SandboxSession.silence_notifications()` turns off banners and destroys the
  source already up — with a sandbox test asserting the tray is empty during
  the walk, and the thirty pictures regenerated. `tools/check_screenshots.py`:
  "30 fresh screenshots, 15 pages, light and dark, all distinct".

Not done, and why: nothing. The four IDs and the cosmetic note are all closed.

**Known gaps carried forward, named and not silently dropped:**
- U10's picture-only Look tiles (looks.py:1208, :1674) still lack `a11y.name`/`a11y.hide_from_screen_readers` — CD4 flagged this explicitly as a note for whoever owns looks.py; not done by any CD agent.
- `ExtensionInstaller.describe_batch` (ego/install.py) has no production caller left after CD5 dropped `name_addons` — only a test exercises it now; left in place rather than ripped out mid-review-fix, flagged for a maintainer.
- A Stop pressed after the engine's last forward narration but before the final `DONE` report still raises out of a fully-succeeded, fully-recorded apply (pre-existing shape, adjacent to E5, not widened by CD5's fix, not required by any finding).
- fish's `~/.config/fish/fish_variables` remains outside the terminal transaction's own restore point (covered by `gtheme rescue` via the pristine Baseline, not by Undo) — a known, documented asymmetry, not closed this wave.
- The AS4 "nothing changed" gate is now reachable by an install-only apply (X1-wiring made the installer real); nobody has touched the gate itself.
- Ghostty's "Take them over" button still moves a directory and writes its own JSON record outside the transaction/ledger system (H8 named `apply`, not the takeover).
- ~~`docs/architecture.md:62`/`:70`/`:75` are stale by small margins~~ — **closed in the closure gap-fix pass above.**
- ~~README:216/:87 ("Four are built in") is still wrong (six ship)~~ — **closed in the closure gap-fix pass above**, along with the four other doc sites and seven code comments that said the same thing.

## Deferred (user decision required — not silently dropped)
- gettext/i18n adoption (U9 ships the honest minimum)
- Flatpak/AppImage/.deb packaging
- Cutting + pushing the public v2.0.0 tag (M23 ships the -git alternative; namcap not installed → PKGBUILD lint test skips, noted)
- Pushing anything to origin; merging audit-fixes into main (user merges; before merging: run --full and take a restore point — H3/H8/U3 change live behavior)
- Seeding real community Looks / content pipeline (theme-sharing-website branch exists)
- Hardware-presence gating for setting rows (runtime-detection design)
- Offline-mode toggle (design decision)
- Photographing bundled Looks on a live session (sandbox infra could; needs supervised run)

## Campaign closure — 2026-08-28

**Final baseline (the last green full gate, `./verify.sh --full` at HEAD `bf889fc`, worktree venv):**
ruff: all checks passed · pytest default tiers (unit+regression+dconf+gtk): **2579 passed · 2 skipped · 29 deselected** in 49.70s · pytest sandbox tier (headless GNOME Shell on a private bus): **29 passed · 2581 deselected** in 91.57s · screenshots: **30 fresh, 15 pages, light and dark, all distinct** · **`verify.sh: OK`**. Repo-wide collection at that HEAD: **2610** items — re-measured per tier this session: 1878 unit+regression (`-m "not gtk and not dconf and not sandbox"`), 42 dconf, 661 gtk, 29 sandbox.

Against the prior baseline (2591 collected · 2570 passed · 2 skipped · 28 deselected at `e66183c`): +19 collected, all from the closure gap-fix pass (`bf889fc`) — 9 unit tests for M7/M26 plus the doc/copy tests, and **1 new sandbox test** (the page walk asserting the notification tray is empty). That one test is why deselected moved 28 → 29: a declared marker change under the gate rule, not a hidden or quarantined test. Skipped stayed at 2 for the entire campaign. `docs/testing.md`'s "28 tests" / "those 28" were left stale by that same pass and are corrected in this closure commit, along with the three claims in `CHANGELOG.md`'s v2.0.0 body that the campaign itself made false.

**Per-ID closure verdicts.** "closed" = the finding's failure is no longer reproducible against this tree. "gap left" = closed as scoped, with a named residual that is written down rather than dropped; none of them re-open the finding.

Wave 0:

| ID | verdict | gap left |
|---|---|---|
| U1, M22, M16, M20, L9, L11, L12, L13, M24, X5, M21 | closed | — |
| M23 | closed | cutting/pushing the public v2.0.0 tag is deferred (user decision); `PKGBUILD-git` is the shipped alternative |
| L10 | closed | `bin/gtheme:10` still names jinja2 in a comment; not a dependency anywhere |
| U9 | closed | full gettext/i18n of the interface deferred (user decision); U9 ships the honest minimum |
| DOCS §3.4 | closed@`bf889fc` | reopened by the closure audit (6 of 7 MISSING bullets untouched), closed in the gap-fix pass |

Wave A:

| ID | verdict | gap left |
|---|---|---|
| C1, H5, H1(txn), H9, M1, M2, M12, L4, L8, H7, H1(baseline), H10, M14, L1(core), L18(core), M18, M19 | closed | — |
| H4 | closed | `/org/gnome/shell/extensions/` is still a tree-shaped allow-list: an extension that stores its own exec command in dconf is reachable the way Ptyxis was |
| X1 | closed | an install-only apply can still satisfy the AS4 "nothing changed" gate and report success |
| M16-AS5 | closed | `SubprocessBackend`/`GioBackend` used bare in a session-less context hard-fail per key instead of skipping |
| L2 | closed | `SubprocessBackend.reset` deliberately has no read-back verify (no way to tell "no user value" from "effective default") |

Wave B:

| ID | verdict | gap left |
|---|---|---|
| H2(looks), H2(restore), M6, M15, U4, U8, H11, L1(ui), M10, M5, L5, L7, M28, M29, L15, L16, L19, M17, L18(ui) | closed | — |
| H3 | closed | a burst spanning an intervening Look apply can mix vintages in "Before your changes"; wallpaper.py's custom-picture file copy sits outside the burst point (undo restores the setting, leaves the copy) |
| M3 | closed | `_apply_locked`'s AS4 switch-cleanup branch can still raise a bare OSError after a cleanup changed the desktop — no longer a lie, not yet a narration |
| M7 | closed@`bf889fc` | Wave B left the effect-picker's silent `except BackendError: continue`; closed in the gap-fix pass |
| L6 | closed | home.py's own "Undo the last change" row still applies with no confirmation while the header button and Ctrl+Z both confirm; `home.header_button` is dead in production |
| X3 | closed | `core/restorepoints.py::apply_point` still catches only `TransactionError`, so the same OSError class is unguarded on an *undo* |
| M30 | closed | the page still raises when nothing it renders loaded at all — a deliberate call (an empty page with no message would be a lie of omission) |

Parallel waves (infra + port):

| ID | verdict | gap left |
|---|---|---|
| M4, M25, M27, M13, U5-infra, U7-capture, U7-cli, L3 | closed | — |
| H6 | closed | `ExtensionInstaller.describe_batch` has no production caller left after CD5 dropped `name_addons`; only a test exercises it |
| U6 | closed | both mechanisms recognise only the `gsettings:` key spelling, not `dconf:` — the six bundled Looks are covered, a community/v1-imported Look need not be |
| U2 | closed | `registry.install_look` hardcodes provenance "community", so a Look imported from your own backup badges as community-sourced |

Wave CD / D:

| ID | verdict | gap left |
|---|---|---|
| H12, M11, L17, M9, M8, X2, X4, U5-button, E10, E6, U7, H13, U3 | closed | — |
| H8 | closed | fish's `fish_variables` is outside the transaction's own restore point (`gtheme rescue` reaches it, Undo does not); Ghostty's "Take them over" still moves a directory outside the transaction/ledger |
| E1 | closed | never run against a real installed GNOME Terminal or Console (neither exists on this machine); mitigated by per-key schema probing and 21 tests |
| E5 | closed | a Stop pressed after the engine's last forward narration but before the final report still raises out of a fully-succeeded, fully-recorded apply |
| L14 | closed | a SIGKILLed app loses the last-page memory (matches the existing size/maximised prefs behaviour) |
| M26 | closed@`bf889fc` | CD3 fixed the version read; the fresh-machine Home path still made two blocking round trips inside `Window.__init__` — closed in the gap-fix pass |
| U10 | closed | looks.py's picture-only Look tiles (`:1208`, `:1674`) still lack `a11y.name`/`hide_from_screen_readers` |

Wave F + closure:

| ID | verdict | gap left |
|---|---|---|
| E8, E9, CHANGELOG, CLOSURE | closed | — |
| E2 | closed | the background-catalogue XML and the picture copies are not in the ownership ledger and are left behind by `gtheme rescue` — documented in SECURITY.md and README |
| E3 | closed | only the first combination of a multi-value shortcut key is compared |
| DOCS-SWEEP | closed@`bf889fc` | six false doc sentences, two of them made false by this campaign's own fixes |
| screenshot blemish | closed@`bf889fc` | fixed at the source (`SandboxSession.silence_notifications()`), all 30 pictures regenerated |

**Nothing is left open.** Every ID above is closed; every "gap left" is a named residual inside a closed finding, written here and in the wave notes rather than dropped. The Deferred section is unchanged by this pass — those eight items need the user's decision, not an agent's.

**CAMPAIGN CLOSED — 2026-08-28**, at HEAD `bf889fc` plus this closure commit, on branch `audit-fixes` in `/home/crocco/gtheme-fixwork`. Base `b9e60c9`. Nothing was pushed to origin; `audit-fixes` is not merged into main; `/home/crocco/gtheme` (the live tool) was never touched and the gtheme app was never launched outside the test harness. Before merging, read the Deferred section: H3, H8 and U3 change live behaviour, so run `./verify.sh --full` and take a restore point first.
