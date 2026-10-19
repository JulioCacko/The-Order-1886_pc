# The Order: 1886 — Gold continuation handoff

Written 2026-10-19, approximately 17:06 UTC. Revalidate live state before changing code.

## Start here

**Continue in this existing worktree, not the original checkout:**

`C:\Users\julio\.codex\worktrees\order1886-go-launcher\The-Order-1886_pc`

- Branch: `codex/order1886-recoverable-updater`.
- HEAD: `b2778be4ff3d07de2ab94a7182cd476549952ba5`.
- There is important **uncommitted work**, listed below. Do not reset, clean, overwrite or discard it.
- Original checkout `D:\Emulator\The-Order-1886_pc` remains on `order1886-gold`, whose former upstream is gone. Do not accidentally implement there.
- Accepted full plan: `docs/superpowers/plans/2026-10-18-order1886-go-gold.md` in the worktree.
- Persistent, ignored execution ledger: `.superpowers/sdd/2026-10-18-order1886-go-gold/progress.md`.
- Updater evidence/design: `docs/verification/2026-10-19-recoverable-updater.md`.

The user requested this handoff to continue in another chat. No new chat was created or messaged. The full Gold objective remains unfinished; no goal-complete or goal-blocked status was set.

## Important live-state correction

Older summaries and ledger entries describing HTILE as draft are obsolete.

- **PR #35 is MERGED**, not draft: <https://github.com/JulioCacko/The-Order-1886_pc/pull/35>.
  - Head: `b2778be4ff3d07de2ab94a7182cd476549952ba5`.
  - Merge: `4c68f3be26792cda7b0a320dc8e39aca99b2944d`, merged 2026-10-19 16:55:36 UTC.
  - Both Windows runs passed: push `39288707061`, PR `39288826732`; CodeRabbit reports success.
- **PR #32 (HTILE) is also MERGED**, not draft: <https://github.com/JulioCacko/The-Order-1886_pc/pull/32>.
  - Head: `b6d40534af48306234c5bbca79ed03b7afafb6bf`.
  - Merge: `2c00c811d60ca0598171a0e13ecd25b137668694`, merged 2026-10-19 10:01:14 UTC.
- Fetched `origin/main` during handoff preparation. Its SHA is `4c68f3be26792cda7b0a320dc8e39aca99b2944d`.
- Verified that HTILE head `b6d4053...` **is** an ancestor of `origin/main`, but **is not** an ancestor of this worktree's HEAD `b2778be...`.

Preserve WIP before integrating current main. Use a fresh continuation branch for the next PR; #35 is already merged. Inspect the incoming diff before switching/merging. Do not apply the old HTILE stash or revert merged work based on stale notes. Merge state does not prove gameplay, visual or performance qualification.

## User intent and constraints

- Continue the entire Windows Gold plan, integrate reviewed GitHub issues, keep Linux a separately qualified preview.
- User says the game is fully completable; their main reported problem is **8–14 FPS from Chapter 2 onward**, using RTX 3070 / Ryzen 5 5600X.
- User repeatedly requested **continued automated work** instead of loading a manual slow-scene route. Do not repeatedly ask the same question.
- Commit/push/publish verified work and continue. Those actions were already authorized; do not ask permission again without a concrete new reason.
- Preserve completed language/save work: 13 languages, game-language forwarding, Brazilian Portuguese naming, confirmed restore-on-Play, backup-before-replacement, cancellation, session protection, and complete snapshots without merging profiles across snapshots.
- Computer Use was stopped with physical Escape earlier. Do not resume unattended game/UI automation. The later request to open the game was fulfilled by CLI launch only.
- Do not equate host fixtures, successful startup, CI, source merges or user-reported completability with exact campaign/hardware/latency Gold evidence.

## Latest public package and player session

Latest public release, checked live during handoff, remains the prerelease:

<https://github.com/JulioCacko/The-Order-1886_pc/releases/tag/v0.1.0-go-preview.6>

- Source: `43749149095902c245b381373923cca6e1c777c7` (input remapping batch / PR #34).
- Runtime SHA256: `f49ccff3db1ceabbb538ab29633ed3c7cf405d5b4233761171dc5878e8a65c33`.
- ZIP SHA256: `2ecfaa69c7259441e3ec5c9efce3109b6526cc1fd5938f33bb8d60b20a5fee26`.
- ZIP: 137,250,491 bytes; 2,357 entries / 2,356 manifest payload files.
- Package under worktree: `out/order1886-go-package/20261019T073804Z/The Order 1886`.
- That package predates the merged HTILE and updater cores. No new package was published for #35.

When the user requested a test launch, the following was started with `Start-Process -WindowStyle Hidden` (the game creates its own normal window):

```text
<package>/Play The Order 1886.exe
  --state-dir D:\Emulator\The-Order-1886_pc\user\order1886
```

It was confirmed running then (Go PID 41600, runtime PID 15660). **At handoff, a fresh CIM query found no `order1886-runtime.exe` process.** Do not assume those old PIDs remain live or restart the game without user direction. Player packages/settings/saves were not updated by the updater tests.

Historical automated control capture:
`out/order1886-evidence/performance/20261019T032911Z/frame-summary.json`.
It recorded roughly 622.759 s, 59.8466 render-work FPS and p99 20.6479 ms in an unidentified scene. It did **not** reproduce Chapter 2 slowdown and is not a performance gain or 4K/FG acceptance result.

## Committed updater cores

PR #35 contains two reviewed commits:

1. `9e01f76ce342475ccab1e859f39c1969e97e1f44`: release verification, bounded/cancellable downloads and safe private staging.
2. `b2778be4ff3d07de2ab94a7182cd476549952ba5`: verified backups, package-file transaction journal, replacement, rollback and process-interruption recovery.

Core files are in `launcher-go/internal/updates/`.

Properties already implemented/tested:

- Fixed GitHub repository; choose dedicated `order1886-go-windows.zip`, verify GitHub asset SHA256/size and release receipt, then source/runtime/ABI/manifest/file hashes.
- Reject traversal, Windows aliases, links/junctions, duplicate entries, protected/unowned paths and resource-limit violations.
- Stage only into a new directory. Failed/cancelled downloads/stages are removed; existing destinations are refused.
- Prepare validates the current package, refuses modified/unowned collisions, copies verified old/new changed files, and writes a journal before replacement.
- Only manifest-owned files change; never swap/delete the installation directory.
- Main Go EXE first, direct-play Go EXE second, worker/libraries afterward, package manifest last. Rollback restores Go entry points last.
- OS-owned updater lock; unknown edits are never overwritten. Failed apply/cancellation attempts rollback.
- New candidates must advertise `order1886-update-1`; **the package builder does not advertise it yet**, because the actual bootstrap/helper integration is not finished.
- Carry `StageArchive`'s returned manifest SHA256 into `Identity.ManifestSHA256` before preparation. A modified stage plus a rehashed manifest must not replace the originally verified candidate.
- Rollback works without unused new payload. Recovery metadata that exceeds the reader's limits cannot replace the last valid journal.

Committed-source evidence:

- Full Go suite: **97 pass**, race detector: **97 pass**, vet passed.
- Fresh independent review: **84 core tests passed**, no actionable Critical/Important/Minor findings under trusted-directory / stopped-player assumptions.
- Tests include seven replacement interruption boundaries, actual child updater termination and lock reacquisition, cancellation/retry, corrupt stages/backups, Windows library sharing denial, a real Windows junction, and source-checkout refusal.
- One-off isolated check copied **21 real player files / 710,512 bytes** (complete save/backup/trophy trees plus settings/runtime INI) from the retained 014410Z package. Apply/rollback preserved all copied bytes; source files stayed unchanged. Package binaries in that check were deterministic fixtures, not a full real-package update test.
- Live receipt check and local extraction of actual published preview.6 ZIP passed.
- Linux core cross-compilation passed; it was not executed on Linux.

Sudden-power-loss durability, actual packaged helper/bootstrap recovery, native launcher UX and game-visible saves after a packaged update remain unqualified. Old transaction directories are retained; safe retention/cleanup still needs implementation.

## Uncommitted WIP — preserve it

Tracked modifications:

```text
launcher-go/internal/updates/transaction.go
launcher/order1886_worker.py
tests/test_order1886_worker.py
```

New files:

```text
launcher-go/internal/updates/session.go
launcher-go/internal/updates/session_test.go
launcher-go/internal/updates/recovery.go
launcher-go/internal/updates/recovery_test.go
```

What this WIP implements:

- `updates.LockSession(state)` uses the existing backend's `session.lock`: Windows `LockFileEx` byte 0/length 1, Linux `flock`. It creates missing state directories beneath a validated existing ancestor, rejects linked components, and preserves existing lock-file bytes.
- Cross-language tests call the **actual Python `order1886.session_lock`**, proving Go blocks Python, Python blocks Go, and locks can be reacquired after release.
- Worker protocol allowlist adds `updates.preflight`. It calls `require_idle`, verifies state is outside original game content, and briefly acquires the existing session lock without rewriting settings.
  - **This is readiness only**; it releases the lock. The helper must reacquire and retain it through replacement and rollback.
- Recovery journal gains optional `session` metadata (`path`, `portable`).
- `Transaction.BindSession(state)` records the original player profile while prepared, refuses rebinding to a different profile, and stores inside-installation paths relative to the portable root.
- `Transaction.SessionDirectory()` resolves the recorded profile.
- `updates.PendingRecovery(root)` inspects the journal without loading Python, requires original session metadata for pending recovery, and creates no updater files when no journal exists.
- Tests cover portable relocation, external state paths, refusal to guess missing state, and refusal to change recovery profiles.

Latest WIP test results:

- `go test ./internal/updates -count=1`: **93 passing core tests**. This finished successfully; unified exec session `52030` is terminal/closed.
- Three focused new Python worker preflight tests passed after observing the expected failures first.
- Four focused Go/Python lock tests passed after missing-API failures.
- **Full Go suite, race/vet and full Python suite have not been rerun for this WIP.** Do not repeat the committed 97-test result as WIP evidence.
- No fresh independent review, commit, push, package or release for this WIP yet.
- No remaining tool/test process handle is known live at handoff.

## Next implementation steps

1. Read this handoff and the current diff; reconcile with freshly fetched main while preserving WIP. Create a fresh branch for further PR work because #35 is merged. Refresh GitHub issue state/acceptance and inspect merged HTILE source rather than relying on the stale draft notes.
2. Finish the copied static Go helper and **startup recovery before any Python worker/DLL load**. There is currently **no production caller** of the updater/recovery cores; `main.go` / `App.connect` are not wired to them.
3. Bind the actual state directory before handoff. Recovery must use the recorded original profile, not a later launch's default `--state-dir`; preserve relocated portable roots and external state paths.
4. Use a copied Go EXE in the update workspace: Windows cannot replace the running launcher EXE or loaded Python DLLs. Parse helper mode before Wails/worker startup. A headless/no-relaunch mode is needed for isolated tests.
5. Wait only for the initiating Go/worker processes, checking Windows PID **and creation time** to avoid PID-reuse mistakes. Do not kill unrelated applications or the game. `workerClient.Close()` currently only closes stdin; wait for `worker.done` before replacement.
6. Helper reacquires/holds `LockSession` throughout apply/recovery/rollback, together with the updater lock. Preserve normal stop/cancellation semantics. Readiness checks alone are insufficient.
7. Startup must detect pending journals and hand off recovery before `app.connect()` can load a mixed worker. Add a connection backstop. Do not repurpose `startupError` as a blanket blocker: existing direct-play setup recovery uses it while allowing the normal UI/worker to load.
8. Add safe error/progress reporting and restart into the launcher/setup; prevent automatic recovery/relaunch loops. Use allowlisted/versioned actions and argument arrays, not arbitrary commands. Keep diagnostics separate from JSON protocol output.
9. Wire real update status/check/download/cancel/install-and-restart/rollback surfaces into System and Home, with confirmations, busy-state coordination, settings persistence and availability reasons. `automatic_updates` is still unavailable; it can become an opt-in startup **check**, not silently install updates.
10. Only advertise recovery ABI in packaging after the helper/bootstrap is real and tested. Verify actual packaged binaries, both entry points, legacy fallback, Unicode/spaces, restricted PATH, offline/WebView2 handling, repeated updates, failure recovery, rollback and real populated player directories. Retain Linux preview and old launcher parity.
11. Run appropriate full checks and a fresh final source review, then commit/push/open a new PR and publish only qualified preview artifacts. Keep Gold and issue #9 acceptance open until full end-to-end evidence exists.

After updater implementation, continue the remaining full plan: actual Chapter 2 performance diagnosis, merged donor/HTILE gameplay checks, controls/display/timing, validated temporal inputs, DLSS/FSR/XeSS and all FG providers, effects/cheats/mods/utilities/languages/achievements/Steam, then campaign/build/hardware/latency qualification. Update 1.02 and matching hardware evidence remain required.

## Tools and workflow

- Use PowerShell and prefix shell commands with `rtk` per `C:\Users\julio\.codex\RTK.md`.
- Use `rtk proxy` when normal RTK condensation makes source output unusable. Headroom compressed outputs can be recovered through `mcp__headroom__headroom_retrieve` and `.original_content`.
- Always set the current worktree directory explicitly in shell calls.
- Always specify `-R JulioCacko/The-Order-1886_pc` for GitHub commands.
- Existing Python with build/test dependencies:
  `D:/Emulator/The-Order-1886_pc/out/order1886-pyenv/Scripts/python.exe`.
- Go race settings: `CGO_ENABLED=1`, `CC=C:/msys64/clang64/bin/clang.exe`.
- Native checks, when appropriate: `C:/msys64/usr/bin/bash.exe ./build.sh --test` (CLANG64, not MINGW64).
- Use package builders via PowerShell `-File`; redirecting native PyInstaller stderr through Windows PowerShell `*>` previously caused `NativeCommandError`.
- Existing skills: executing-plans + its TDD subskill; PR skill for PR bodies. Follow failure-first tests, concrete evidence and fresh final review. Final review delegation is authorized by executing-plans; do not casually spawn implementers under current delegation restrictions.
- Graph Tier 2 project: `D-Emulator-The-Order-1886_pc`, generation `2026-10-18T23:07:49Z`, root is the original D checkout. `order1886.py` coverage is metadata-changed; Go/worker paths are missing. Use graph first, then exact current-worktree source fallback. Graph `session_lock` is indexed at old lines 337–358; current worktree definition is around 395–416. Some generic call edges are spurious C++ matches; do not rely on them. No `.codegraph` directory was found in this worktree.
- Do not archive/delete the managed worktree: it contains ignored player state, packages, evidence and the ledger. Do not change `.codex` memories without a direct user request.

## Suggested next-chat prompt

> Continue the full Windows Gold task from `D:\Emulator\The-Order-1886_pc\docs\HANDOFF-2026-10-19-GOLD-UPDATER.md`. Work in the existing `C:\Users\julio\.codex\worktrees\order1886-go-launcher\The-Order-1886_pc` checkout, preserve the uncommitted lock/recovery work, reconcile merged PRs #32/#35 with main, and finish updater helper/bootstrap/UI integration before continuing the remaining Gold plan. Continue automated work without restarting the game or resuming unattended UI automation. Do not claim Gold from fixtures or source merges.
