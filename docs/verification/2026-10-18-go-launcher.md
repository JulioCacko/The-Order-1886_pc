# Windows gold / Go launcher implementation ledger

Baseline: c6d8c74, isolated managed worktree. Original checkout's in-flight save/language work is owned by another chat and is not edited here.
Plan: implement the accepted Windows gold + Wails launcher contract. Linux remains preview. Every open issue remains tracked; implementation, automated checks and gameplay acceptance are separate.

## Tasks
- [x] Reconcile completed language/save batch from the original checkout (54242e0, cherry-picked as 84ea7cb).
- [x] Versioned allowlisted worker with settings validation, capabilities, utilities and session events.
- [x] Wails v2 desktop application, seven-page TypeScript UI, autosave and search (migration preview).
- [x] Worker/native launcher preview packaging and relocated smoke checks; retain the legacy distribution default while broader parity remains open.
- [ ] Runtime correctness, donor readback/HTILE and performance baseline.
- [ ] Controls/display/timing, temporal inputs, upscalers and frame generation.
- [ ] Remaining GitHub acceptance and external qualification.

## Rulings
- Implement inline using executing-plans; fresh whole-change review at the end.
- Use an isolated checkout while the existing chat finishes save/language changes.
- Preserve the legacy launcher and backend as the tested migration boundary; no provider is advertised working until its renderer path and gameplay evidence exist.
- Wails v2.17.0 is the newest stable v2 version returned by the official module proxy.
- UI uses plain TypeScript and semantic HTML/CSS, avoiding an additional component framework.
- Fresh review found and reproduced duplicate-start state loss and worker-death close veto. Starts now reserve ownership atomically, unexpected worker death releases the veto and is reported without claiming descendants stopped.
- Session-result tests distinguish successful verify/prepare, normal completion, stops, native failure and malformed completion. Error cues preserve the exit code and log path.
- The redundant npm install at the Go module root was removed; Wails owns its configured frontend install. README now matches Go1.25 from go.mod.
- A Windows CI workflow was added for worker/save regressions, frontend checks and the Go application build. Hosted execution is unverified until an authorized push/run.

## Evidence
## Current evidence

- The 43-field catalogue exposes the 15 existing working player settings. Requested renderer modes remain visible with explicit reasons and are rejected by settings validation.
- The private Python environment ran 351 tests successfully, 36 skipped for unavailable native fixtures in this isolated checkout. Initial missing xbyak/magic_enum headers were resolved by initializing the pinned submodules. The UTF-16 log is `out/order1886-evidence/go-launcher/python-full.log`.
- Subsequent focused worker tests cover broken-output shutdown and bounded UI log events; full native output stays in the durable session log.
- Go protocol tests/vet pass, TypeScript and Vite production builds pass, npm audit reports zero vulnerabilities. Vite is pinned to 7.3.7.
- Packages `20261018T231334Z` and `20261018T231804Z` passed manifest, both executable names, Unicode relocation, restricted PATH, settings/language persistence and unsupported-setting rejection smoke checks.
- The second package completed real CUSA00076 CPU preparation from a temporary state directory. The original eboot SHA256 remained `a8ce5fe151573dca0b3951e1edfd608b3e027b53cc30761f7805e44c9d9ddec0`; no game runtime was started.
- Native Windows screenshots confirm Home/Graphics rendering, accessible navigation, Ctrl+K search and the repaired persistent launch bar. Artifacts: `native-home.jpg`, `native-graphics.jpg` under the same evidence directory.
- Native resize/DPI/theme, clean-machine missing-WebView2 and live Steam/gameplay checks are not accepted by these captures. Newly written copy still needs translation/native-speaker review.
- User requested continued automated work; the street comparison remains deferred.

Hardware gates: local RTX 3070 only; update 1.02 and external provider hardware remain required. Readback/HTILE, temporal inputs, upscalers/FG and the remaining open-issue acceptance are unfinished. This batch does not establish gold.

## Final migration-preview checks

- Clean code revision: `b9130ac59403d0ad7d9e1e55c99428183610a84d`.
- Final portable package: `out/order1886-go-package/20261019T001510Z/The Order 1886`. Its manifest records `source_dirty=false` and native runtime SHA256 `ca77edaf93ccec956b20263cb3b9a0c36b1b4496e5437e080d5f6d95b850f1e9`.
- **353 Python tests passed, zero skipped.** The final run uses matching existing native CPU fixture binaries from native source revision `54242e0`; these fixtures were not rebuilt in this Go checkout. `native-fixture-provenance.json` records each copied binary's hash and native source identity.
- The former installation-path skip was covered with an exact copy of the real game's read-only `param.sfo`. Only metadata was copied for that native configuration fixture, not an eboot, game content or player saves. `sfo-fixture-provenance.json` records its hash. This is not a playable-installation or gameplay acceptance claim.
- Go protocol/application tests (7), frontend completion-state tests (4), TypeScript/Vite production build, Go vet and npm audit pass. The post-metadata-copy worker subset also passes.
- Fresh review resolved the four lifecycle/build/error-state findings and the subsequent notice-copy issue. The final collector reads compiled dependency modules, deduplicates them, and includes their notices plus Go's standard-library license.
- Portable smoke checks pass for manifest hashes, both executable entry points, Unicode/spaces relocation, restricted PATH, worker protocol, autosave, language persistence and unavailable-setting rejection. Real-data CPU preparation passes from temporary state; the original eboot hash is unchanged.
- Impeccable's mechanical detector returned an empty finding list. The reviewer approved the captured desktop appearance for the opt-in preview; it did not certify locale, minimum-size, DPI/theme or missing-WebView2 behavior.
- The ZIP is `out/order1886-go-package/20261019T001510Z/order1886-go-launcher-preview-windows.zip`, with a sibling SHA256 file. `package-final.json` records archive size/digest and verification of every manifest payload inside the ZIP.

## Publication

Published at the user's request as [Windows Go launcher preview 1](https://github.com/JulioCacko/The-Order-1886_pc/releases/tag/v0.1.0-go-preview.1), explicitly marked prerelease. GitHub's uploaded ZIP digest matches `1896191fc2e5363a037659b9f9989a65a1efc638462da181ca95b5e6011a7662` (137180826 bytes). Preview.4 remains the existing Windows/Linux distribution.

[PR #25](https://github.com/JulioCacko/The-Order-1886_pc/pull/25) merged after both Windows Go workflow runs passed ([push](https://github.com/JulioCacko/The-Order-1886_pc/actions/runs/39181870052), [PR](https://github.com/JulioCacko/The-Order-1886_pc/actions/runs/39181885319)). The tag records `8a8667b733c97fbcbc6cc2d398168d167fd8f53a`; its package retains the exact code/runtime identities above. No feature issue was closed. Manual street/campaign evidence and unfinished renderer/provider/FG/feature work remain open.

