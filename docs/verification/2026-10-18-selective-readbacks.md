# Synchronous selective buffer readbacks

This source follow-up implements the small-buffer read-watch prerequisite from donor `3654b06`, using the existing synchronous download path. It does not import promoted deferred buffer copies or their stale-data policy.

## Behavior

- The default `relaxed` policy is unchanged. In `selective`, writable GPU buffer bindings up to 64 KiB mark their 4 KiB pages for CPU read tracking. A CPU access downloads the current GPU bytes and waits for completion before releasing protection. `precise` tracks all GPU-written buffer pages.
- Repeated overlapping watches are idempotent. Ordinary downloads keep the watch for later GPU writes. A CPU overwrite flushes first and then clears that page's watch; unmap uses the same invalidation path so remapped pages do not retain the previous watch. No deferred buffer payload survives an unmap.
- GPU-written byte-range mutations and downloads share a mutex. Downloads acquire the region lock before the byte-range mutex; writable bindings release the region lock before acquiring the byte-range mutex.
- The Go Performance page exposes **GPU readback policy**, autosaves valid choices and marks them for next launch. Home reports the requested policy. Shared settings, direct Play and CLI `--readbacks` forward the same policy to `ORDER1886_READBACKS`.
- Selective and precise require a hash-bound native receipt declaring support. Older/custom runtimes remain visible with an availability reason; saving an unsupported choice is rejected. Backend validation also rejects mismatched receipts. Disabled readbacks remain unavailable in the player profile.
- Runtime selection is re-resolved before checking cached capabilities, including a new `bin` runtime shadowing the source `out` runtime. Existing runtime hash/profile/ABI verification remains in force.

## Verification

RED/GREEN checks cover the missing policy mapping, protection transitions in disabled/relaxed/precise/selective modes, invalid native mode fallback, old/mismatched/malformed receipts, saved-value preservation and default-runtime replacement. The fresh reviewer found the default-runtime cache defect; its filesystem regression failed before correction and passes afterward. The reviewer approved the corrected code and independently reran all six focused tests.

The final Python suite passes **361 tests with no skips**. The native gate passes **43 checks**, including all readback modes. TypeScript/Vite production build and four frontend state tests pass. The native runtime SHA256 is `d2fa31ee1388c44009f91309ced0bf964dce7eca55b66ed23b30f74e4acb0026`, from clean source `fc3dc29ed114edfdbc88bc722cb370794c2ecf68` (native source-file digest `ef9180fdb22ae1ede034c1197160be1e825681144c4367693aef7c022a24edfd`).

The focused Linux workflow and both Go Windows runs passed at `fc3dc29`: runs `39185512549`, `39185512576` and `39185504180`. Later Go startup corrections receive their own final CI/package checks.

## Packaged desktop startup

The actual native UI check found a stall on Connecting that the worker-only smoke did not detect. Frontend methods could read the worker before asynchronous startup connected it. A delayed-connection regression reproduced both premature status and request results. Connection creation is now serialized and idempotent; frontend calls wait for it. Shutdown waits for a pending connection and refuses creation after close. Transient connection failures are reported from the current attempt rather than retained after recovery; the intentional direct-play setup notice remains.

All **13 Go tests**, Go vet and race detection pass. Fresh review approved the startup correction after a stale-error recovery finding was reproduced and fixed. Temporary diagnostic instrumentation was removed. The probe-free native binary rendered Home, search and Performance with the readback choices. This validates that UI path, not every DPI/locale/accessibility or direct-play recovery scenario. WebView data is scoped to the portable player-state directory.

The internal `20261019T014410Z` package was modified for diagnosis and marked incomplete; it must not be distributed. Final portable evidence is appended from a fresh, clean build.

## Bounded real-game startup checks

Base CUSA00076 startup ran in separate fresh state/cache directories with 30 FPS/original framing, windowed Linear presentation and mouse capture disabled. The receipts record `ORDER1886_READBACKS=3` for selective and `2` for precise. Both reached the configured 90-second watchdog (90.680 and 90.568 seconds), with flip submissions logged; they ended with `exit_code=124`, `timed_out=true`, `forced_stop=true` and `gameplay_verified=false`. This is not a route comparison, graceful-stop acceptance, measured FPS or visual correctness proof. No player saves were copied. The original eboot hash still matches the established baseline. Raw logs/receipts and `startup-summary.json` are under `out/order1886-evidence/selective-readbacks`.

## Limits

These fixtures establish CPU tracking and launch plumbing, not aiming focus, current visual quality, GPU lifecycle stability or an FPS improvement. Synchronous selective/precise modes may add waits. The existing relaxed default is retained pending matched gameplay measurements. HTILE, deferred readbacks, temporal providers, frame generation and the remaining gold features/gates remain open.

## Mapping ownership correction

A final bounded review reproduced stale GPU ownership after `MAP_FIXED` using the actual VM implementation and a simulated GPU publication callback. Replacement emitted MAP without retiring the old binding; a later unmap could publish old GPU bytes into the new physical allocation while a live alias of the old allocation remained stale. This was an existing mapping-lifetime defect, not proof of a gameplay crash cause.

Mapping changes now serialize across retirement, host replacement and registration. The old binding is retired while its original backing remains present, with the VM table lock released so the GPU publication thread can acquire it. The mapping transaction mutex stays held across the callback. Ordinary unmap, batch unmap and physical release share that ordering. Queued batch MAP notifications drain before retirement, and a recoverable host-map failure restores registration for the surviving mapping.

The permanent production-source regression failed before the correction and passes afterward. It checks live physical aliases, rejected no-overwrite requests, MAP/retire ordering within a batch, physical release, two competing mapping threads and publication on another thread. Linux additionally injects a recoverable host-map failure. The test runs in both the Python gate and the native build gate. The Windows native gate now has 44 checks.

CodeRabbit's preserved-size/timestamp receipt finding also reproduced: the worker could retain unsupported readback choices. The cache signature now includes the small receipt's SHA256; the regression verifies refresh and rejected persistence. This is treated as an availability-contract defect because the launcher must not accept an unsupported setting. No native executable hash check was removed.

The graph service was unavailable (`Transport closed`); exact source and caller searches were used for this bounded change. The previously verified `021337Z` archive (SHA256 `bda49f8bc19cf56cef707b01a95d7f33d48c0f5df00c6ac4f9725f0b1bfb9bb1`, 137197153 bytes) predates this correction and is superseded for publication. Final clean-source identities and hosted checks follow after the corrected build.

After the ownership and receipt corrections, the full Python suite passes **363 tests with no skips** and the rebuilt Windows native gate passes **44 checks**. Linux's injected host-map failure is reserved for its hosted run; Windows host-map failures terminate rather than returning a recoverable error.

## Corrected portable candidate

All hosted checks pass at `212a43ddcf4bf4919b98dd75d4ad0350c013dac2`: Linux `39191008762` (including injected recoverable map failure), Windows `39191008621` and `39191006025`, and CodeRabbit. Native SHA256 is `88416337ff76f31c37f9d33224e29449fdd78b3ce8c87bb482e1ad3202b13382`; the clean receipt records native source-file digest `172a7a9e6f19d0153928e02d6cb7da89ec543bd675c9c16586f4935cbb25c7c7`.

Fresh package `out/order1886-go-package/20261019T024211Z/The Order 1886` passes both entry points, relocated Unicode/spaces paths, restricted PATH, worker protocol, autosave, languages and rejected settings. Its actual WebView2 UI renders Home and Performance. A keyboard selection of Selective shows “Saved — applies on next launch” and persists `readbacks: selective` in this QA package's player settings. Older user-owned preview windows were left untouched.

The archive includes only manifest payloads plus the manifest: **2355 entries**, **137198145 bytes**, SHA256 `94d0b4e3fd9d0671c315212515df77d57a5efd96fb091cda376e7f7190ccf10a`. CRC, exact entry set and every archived payload hash pass. Post-launch player settings/WebView state are excluded. The manifest records clean source `212a43d` and the native hash above.

A fresh selective startup on that native build logs flip submissions and reaches its 90-second watchdog after **90.843 seconds**. Receipt: `exit_code=124`, `runtime_exit_code=1`, `timed_out=true`, `forced_stop=true`; gameplay remains unverified. Evidence is in `out/order1886-evidence/selective-readbacks/startup-ownership` and `package-ownership-final.json`. No feature issue is closed by these checks.
