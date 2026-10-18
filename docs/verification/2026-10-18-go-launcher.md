# Windows gold / Go launcher implementation ledger

Baseline: c6d8c74, isolated managed worktree. Original checkout's in-flight save/language work is owned by another chat and is not edited here.
Plan: implement the accepted Windows gold + Wails launcher contract. Linux remains preview. Every open issue remains tracked; implementation, automated checks and gameplay acceptance are separate.

## Tasks
- [x] Reconcile completed language/save batch from the original checkout (54242e0, cherry-picked as 84ea7cb).
- [x] Versioned allowlisted worker with settings validation, capabilities, utilities and session events.
- [x] Wails v2 desktop application, seven-page TypeScript UI, autosave and search (migration preview).
- [ ] Worker/native launcher packaging and relocated smoke checks; preserve legacy default until parity passes.
- [ ] Runtime correctness, donor readback/HTILE and performance baseline.
- [ ] Controls/display/timing, temporal inputs, upscalers and frame generation.
- [ ] Remaining GitHub acceptance and external qualification.

## Rulings
- Implement inline using executing-plans; fresh whole-change review at the end.
- Use an isolated checkout while the existing chat finishes save/language changes.
- Preserve the legacy launcher and backend as the tested migration boundary; no provider is advertised working until its renderer path and gameplay evidence exist.
- Wails v2.17.0 is the newest stable v2 version returned by the official module proxy.
- UI uses plain TypeScript and semantic HTML/CSS, avoiding an additional component framework.

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

