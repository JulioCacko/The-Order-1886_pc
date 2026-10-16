# The Order: 1886 runtime status

Current development: the agreed [4K/60 acceptance and timing profile](order1886-4k60-verification.md) preserve the original scene detail and use FSR1 for 4K output. The 60 FPS recipe is hash-guarded and opt-in; returning to 30 restores the derived native image. Original game files are preserved.

The latest verified source runtime is `e361df5d80edaa477899b7bbab8923831308535d7aeb7841f2418ec8b5f4188b`, with shader binary/meta/key versions 12/9/7. Build and eight native checks pass (`out/order1886-evidence/image-bounds-build-tests.log`). The cold 4K/FSR1/30 run in `user/order1886/diagnostics/image-bounds-4k-cold` exits explicitly with code 23 after 27.636 seconds at `ReadConst pointer outside GPU address space`. Its 149 dumped SPIR-V modules validate; the FSR output-layout callback does not recur. Two integer-filter callbacks remain. The oversized descriptor from the preceding run was not reached, so actual guard intervention remains unverified. Menu, gameplay and the 30-minute performance target remain unverified.

The last packaged launcher/overlay update is documented in [launcher recovery and verification](order1886-launcher-recovery.md), runtime `ca415f6a...`. It fixes invalid-console result reporting and adds the presentation performance panel and F9 toggle. The remaining build/package details below preserve the earlier `917a` historical baseline and do not identify the current source build.

Updated 16 October 2026. This is emulator-backed compatibility software running the original PS4 executable.

## Historical build and gates

- Runtime: `out/order1886-runtime.exe`.
- SHA256: `917a09caa5839844a76295279f6d9cd7d3fdf696d580cd261e2c00c49331bc85`.
- Receipt: `out/runtime-build.json`; revision `1594332d62c1ff1a77603a48ee83349e13b0cbaa`, dirty working tree. Source-file digest: `87408a66b0e8a2f4d915eab67d23b38e7a3b0f472509cdcb29706b759850fa42`.
- ABI `order1886-native-1`; preparation `PS4BOOT5`; renderer/cache `native-ps4` / `native-ps4-v1`.
- Shader binary version 11, metadata version 8, pipeline-key version 6. Older shader binaries are rejected.
- MSYS2 CLANG64, Clang 22.1.8, RelWithDebInfo, LTO off, PGO off.
- Machine: Ryzen 5 5600X, RTX 3070. Vulkan reports NVIDIA driver 617.14.0.0 and Vulkan 1.4.351. Local validation API 1.4.357 is diagnostic-only and is not shipped.

| Gate | Evidence |
| --- | --- |
| BUILD | Passed: integrated runtime, eight native checks, receipt |
| BOOT | Original executable and intro reached; compatibility incomplete |
| MENU / GAMEPLAY | Not reached / not verified |
| STABILITY | Save/load, restart and 30-minute gameplay not verified |
| PERFORMANCE | Not measured; diagnostic durations are not benchmarks |
| DISTRIBUTION | Ten portable CPU checks pass; packaged native runtime reproduces intro and startup failure with restricted PATH |
| CI | Local checks only; GitHub Actions execution unverified |

## Engine separation

Active native code, backend, launcher, build configuration and tests scan clean for `gow3`, `gow_`, full-word `GOW`, and `God of War`. Required attribution, licenses and historical provenance remain. Actual PS4 SDK symbols containing `Kratos` are ABI names and remain intact.

Removed engine injection hooks, executable patch/cheat tables, actor/orb helpers, camera/object reconstruction, optional reconstruction providers, custom shaders, lighting overrides, stale-readback behavior, touchpad photo-mode timing/chords, old launcher artwork and obsolete packaging/tooling. Shared PS4 infrastructure uses `ps4_*` / `Ps4*` names. The backend emits supported Order configuration only; old environment keys have no native consumers.

The Order baseline uses the existing serial Vulkan submission path. The inherited CPU-count rule enabling a two-stage draw pipeline was removed; the presenter's draw scheduler no longer enables its recording worker. A prior threaded run demonstrated simultaneous shared-command-pool writes before a driver fault. Subsequent bounded serial runs have not reproduced those callbacks; this is not a stability claim.

Retirement inventories and recoverable originals:

- `user/order1886/diagnostics/retired-engine-cleanup.json`
- `out/order1886-legacy-tool-cleanup/20261016T052750Z/inventory.json`
- `out/order1886-test-cleanup/20261016T060702Z/inventory.json` and `verification.json`: 15 archived originals, four obsolete suites and one unused foreign-game fixture removed, ten relevant test files updated.

Original game files and reference installations were preserved. Metadata remains distinct: TITLE_ID `CUSA00076`, APP_VER `01.00`, VERSION `01.03`, INSTALL_DIR_SAVEDATA `CUSA00035`. Prepared images, saves/backups, caches and logs remain outside the game directory.

## Implemented runtime and graphics changes

- POSIX pthread aliases and TLS-key lifecycle; optional IME disconnected-device behavior; event flag masks, ordering, cancellation, deletion and timeouts.
- Dynamic memory-notification queue ordering, reentrancy, concurrency and allocation checks; actual SFO metadata initializes AppContent.
- Descriptor-source bounds checks preserve SGPR0, immediate DWORDs and R128 reads. Unknown sources fail explicitly. Unflattened ReadConst source zero is not mistaken for SGPR0.
- Failed SRT code generation rolls back emitted bytes and saves pointers only after success. Immediate-left dynamic shifts use correct arithmetic. CPU tests exercise the production generator.
- Null/rejected image bindings retain declared sampled/storage type, binding count and following-binding numbering.
- Each compiled permutation owns effective resource metadata. Serialization stores canonical lookup and effective Info; async builders use frozen snapshots and publish stable live owners. Eliminated FMask dependencies retain specialization details and component selectors.
- R16_UINT multisample copies use unsigned host shaders. Float shader binaries are unchanged; other integer copy formats are not generalized.
- Array-layer counts use raw hardware type: ordinary 1D/2D/MSAA/3D resources have one array layer; array/cube counts retain hardware semantics and padding. The captured plain 2D image no longer requests 4,535 layers.
- Image binding checks actual VMA coverage for the base byte before ImageDesc decode. Temporary unmapped-base rejection bypasses texture-set memoization so later mappings can retry. This is not a full-range or sparse-image rejection.
- FMask ImageRead/ImageSampleRaw replacements produce four components using explicit descriptor selectors. R/G and integer Zero/One use the existing two-word identity model. Unestablished B/A payload selection fails before invalid SPIR-V emission. See `docs/order1886-fmask-vector-evidence.md` for the production-body regression and primary Mesa source. The older scalar ImageQueryLod replacement remains a separate finding.

No arbitrary format/tiling remapping, Phi default, blanket return-zero guest stub, global nearest-filter override or higher-frame-rate patch was added. Direct-memory access remains disabled and unproven.

## Current game evidence and blockers

Final runs use SHA `917a09ca...`, original CUSA00076 files, native resolution, 30 FPS presentation cap, 60 Hz vblank and VSync. Shader `0x804aeead` has unresolved Phi/ReadConst SRT offset ancestry. Some other suspect descriptor copies are successfully emitted direct SGPR copies, so dynamic failures do not explain every descriptor.

| Directory under user/order1886/diagnostics | Result |
| --- | --- |
| `graphics-final-fmask-cold` | New isolated cache, validation enabled. Exit 23 after 22.448 s: unsupported FMask selectors R=0 G=0 B=4 A=6. No validation callback before this explicit stop. |
| `graphics-final-fmask-warm` | Actual cold cache reused. Blocking reload restores 129/129 pipelines in 1.53 s. Exit 23 after 15.613 s: R=0 G=2 B=6 A=2. One integer-filter validation callback remains. |
| `graphics-final-fmask-background` | Actual cache reused with six background workers. Log reports 112 preloaded pipelines and 168 shader modules against a 134-entry scan. Exit 23 after 11.558 s: R=1 G=2 B=3 A=7. No validation callback before this stop; not every scanned entry is proven loaded. |
| `graphics-final-917a-package` | Packaged native executable with inherited PATH restricted to Windows System32; package bin prepended, no source dependency injection. Exit 23 after 20.025 s: R=0 G=2 B=6 A=2. |

Each has `run.json` and `native.log`. Cache provenance: `graphics-final-fmask-cold/cache-before-warm.json`. Warm records identify reuse explicitly. `validation-comparison.json` records callback counts across revisions.

The remaining filter error is `VUID-vkCmdDispatchIndirect-magFilter-04553`: UINT images are sampled through a shared linear sampler that also serves float images. UINT shader permutations exist; this is not proven to be another scalar-type mismatch. Establish actual GCN integer-filter semantics and preserve each image/sampler association before choosing a host representation. The supplied reference also copies filters unchanged and does not justify global nearest coercion.

The immediate next step is to capture failing raw FMask words, format, shader identity and fetch origin, then trace required SRT pointer ancestry. Establish selected B/A payload behavior or correct descriptor selection from that evidence. Selector variation across runs is not proof the descriptors are valid; do not guess zero values or discard the assertion.

Visually checked final source capture: `graphics-final-fmask-cold/frames/display_000_1920x1080.png`, original Santa Monica Studio External intro. Display/output raw hashes both equal `69e50fda796469e9d98711bf77efcd570c2c31aff10b9ba56e14c2bf3ceb0c19`.

Visually checked final package capture: `graphics-final-917a-package/frames/display_000_1920x1080.png`, same original credit during its fade. Display/output raw hashes both equal `99e5a5e1aca4983db46969dc3b19b01fea1ffed73cd95ac698f1728bc9753481`. These prove specific intro frames, not menu or 3D rendering correctness.

Historical evidence remains intact: `graphics-binding-before-validation` (e21c) has float/R16_UINT and layout VUIDs; `graphics-binding-after-validation` (50b4) lacks those but exposes the layer-count fault; `graphics-final-layer-mapping-validation` (9e0c) exposes invalid FMask SPIR-V and integer filtering. The 9e0c warm attempt in `user/order1886/logs/20261016T055719.148734Z-boot.log` faults in nvoglv64.dll+0xe19da0 after command-pool threading errors. `graphics-serial-submit-cold` (1deea) stops at data format 13/number format 1 without those thread callbacks. Earlier `graphics-final-srt-*` and e21c packaged driver-fault records remain historical. An earlier format-33/sRGB descriptor is BG_RG, not reserved or BC1. These are not final-build compatibility claims.

## Checks and portable preview

- Native build plus eight checks: `out/order1886-evidence/final-integrated-build-tests.log`.
- Final Python suite run alone: 143 tests, 132 passed, 11 skipped; `out/order1886-evidence/final-integrated-python-tests-serial.log`. Skips require absent standalone runtime-test/semaphore-test executables.
- Earlier concurrent suites hit WinError 32 deleting timeout.log or stop.log. Original failures and `out/order1886-evidence/lifecycle-triage/triage-note.md` remain. The isolated final run passes; the transient lock owner remains unresolved. No production/test retry workaround was added.
- Full `git diff --check` passes. CPU overlay and mod-conflict checks are in the test-cleanup evidence.
- Ten portable CPU checks pass from a relocated directory containing spaces with restricted PATH: `out/order1886-evidence/Portable Smoke c52891efe6/smoke-report.json`. They cover manifest, preparation modules, artwork, runtime identity/help/info, frozen GUI settings/navigation and missing/real-game preparation.

Final ZIP: `dist/order1886/20261016T061117Z-917a09caa583/order1886-windows.zip`, 98,113,076 bytes, SHA256 `3d5643163dc69d829d29027db92ee034e5660f1ab53820aca3eebe3558a7d45f`.

Launcher: `dist/order1886/20261016T061117Z-917a09caa583/The Order 1886/The Order 1886.exe`; native executable in bin/ has the final runtime SHA above. Frozen backend SHA `f7ed4459f04e425d70071a4f4d1fd14b92261db1e0686012dadd587c584fe197`. All six frozen Python source hashes match manifest/current sources. ZIP integrity and archived manifest equality pass. Delivery record: `out/order1886-evidence/final-917a-package-delivery.json`.

The package carries launcher, native runtime, dependency closure and notices without game content. This experimental preview reproduces startup and the unsupported-descriptor stop; distribution gameplay acceptance has not passed.

## Reference and reproduction

The supplied `D:/Emulator/PS4/shadPS4` source was verified at revision `5aa7ffa3f4f21bba827d7865ed8f69f98f993542`, version 0.20.1 WIP. No Windows reference executable was found in the audited inventory. This identifies the supplied snapshot, not its status against upstream. It remains implementation evidence, with required attribution/licenses preserved.

~~~powershell
rtk C:/msys64/usr/bin/bash.exe build.sh --test
rtk out/order1886-pyenv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py"
rtk out/order1886-pyenv/Scripts/python.exe tools/order1886_graphics_probe.py --runtime out/order1886-runtime.exe --output-dir user/order1886/diagnostics/NEW-UNIQUE-DIRECTORY --dump-shaders --dump-frame --frame-delay 10 --timeout 60
~~~

The probe requires a new output directory and creates a cold cache. Native command and effective Order environment are in run.json. Validation used a runtime_environment harness override adding ORDER1886_VK_VALIDATION=1 and VK_LAYER_PATH=C:/msys64/clang64/bin; simply exporting Order keys in a parent shell is insufficient because the backend rebuilds them. Warm runs used the recorded cold GPU root plus explicit pipeline-binary/background/parallel overrides. These are diagnostics, not shipped performance settings.

After resolving FMask/SRT and sampler/image constraints, establish MENU and GAMEPLAY, then audio/input/progression, save/load, restart, a recorded 30-minute session and a repeatable cold/warm performance route. No benchmark claim is justified by intro-only evidence.
