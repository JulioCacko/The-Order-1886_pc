# First-combat 4K60 milestone

Confirmed by the user on 16 October 2026 after reviewing the gameplay recording.

## Acceptance

- Windows, Ryzen 5 5600X and RTX 3070; Vulkan, 3840x2160 output with upscaling.
- Preserve original scene detail, effects and lighting. User explicitly changed the target to full-screen 16:9 without letterboxing during execution.
- First combat checkpoint anchors a documented repeatable gameplay route.
- FSR and DLSS must each pass two 30-minute warm-cache runs: average >=59 real rendered fps and p99 frame time <=20 ms. Report cold-cache results separately.
- Correct game speed/audio, controller and keyboard/mouse, checkpoint save/load and restart.
- Generated frames, repeated host presents, menus and intros do not establish acceptance. Full-campaign Gold remains open.

## Implementation sequence

1. Preserve baseline executable/receipt, configuration and copied saves; reproduce the recorded slow path and establish raw timing evidence.
2. Use RenderDoc for frame structure, ETW for CPU/wait evidence, Ghidra for verified guest-code questions and WinDbg for concrete failures. Keep instrumented runs separate from acceptance runs.
3. Fix the measured compatibility/performance bottleneck with focused regression coverage and matching real-game comparisons.
4. Implement shared Order-specific color/depth/motion/jitter/history inputs, FSR 3.1.4 through the Vulkan backend in FidelityFX SDK 1.1.4, and DLSS SDK 310.9.16 Super Resolution (model K initially). Validate inputs before enabling providers; preserve FSR1/30 fps recovery.
5. Expose provider selection and actual active status, run the acceptance matrix, and retain runtime/configuration/provider identities with measurements and captures.

## Execution record

- Initial tracked tree clean at 7a3d708. Work branch: codex/order1886-combat-4k60.
- Recorded video: 108.60 seconds; 3838x2154 at 30 recording fps. Sampled overlay 6.0-13.1 fps in opening prison gameplay, not a first-combat benchmark.
- Initial runtime receipt: b6db10c4284d041275820b34f04c3b2748427a37e942e57e86a3d1ba760d0557.
- RenderDoc MCP responds; no capture currently open. Ghidra MCP responds but backend at 127.0.0.1:8080 is offline.
- Implementation and real-game acceptance remain in progress.

### First implementation slice

- Added opt-in raw guest-flip and host-presentation CSV tracing, with draw/dispatch work serials and a timing summarizer. The summarizer reports stalls/repeated serials and never certifies gameplay or unique rendered frames by itself.
- Added opt-in small Windows user-process failure snapshots and native stack addresses; existing dump files are preserved.
- WPR CPU recording was attempted and failed with 0xc5585011 (profiling-policy privilege). ETW MCP responds but has no loaded trace. No completed ETL is claimed.
- Ghidra 12.1.4 was verified through a headless GhidraMCP session against the provenance-bound analysis copy (SHA256 32a3b93c70cfdc48925ab9f3fd47abbae7ae971d9a9b3899c6e18e4a6d405495). Existing project has only one analyzed function; no deep guest-code analysis is claimed.
- WinDbg MCP read the retained older dump. A live owned-target attempt was dominated by page-protection exceptions and was stopped; it is not usable performance evidence.
- Baseline b6db10c4, recovery cache policy, default preparation workers: opening slowed to 7.9 fps and stopped after 246.402 s at an invalid ReadConst pointer in shader abab1f2a.
- Candidate 20261016T213209Z, VSync off/default workers: stopped after 94 s on an image requesting 8029 layers (device limit 2048). Its mixed menu/loading/opening trace is not a gameplay benchmark.
- Candidate 20261016T213943Z, VSync off/preparation workers=0: progressed through visible opening 3D and QTEs, with many warm 30 fps windows and lower cold/transition windows. No descriptor stop observed during the ongoing bounded run. Root cause of the worker-sensitive failures is not yet established.
- Normal launcher and direct-runtime defaults now use zero speculative preparation workers; explicit native overrides remain available for diagnostics. Resource validation remains active.
- Verification: 174 Python tests ran, 28 skipped; focused frame timing tests 7/7; production uniform-guard fixture passed; Windows native build and ten CPU checks passed. Final runtime receipt currently ec9a19cf38edb33e2f3660c99fc2b699dcc2a100ee1f3fc1f769c48a7cf0dddc (later comment-only source edits need a refreshed receipt).
- Outstanding: 4K/60 probe, first combat checkpoint/route, modern FSR and DLSS integration, both-input gameplay acceptance, checkpoint save/load, two 30-minute passes per provider, full-game Gold.

### User-supplied patch and full-screen request

- Copied the supplied TheOrder1886-Orbis.xml unchanged, with SHA256 ff7411479fc32d0075be7e9ad19ef7a68f108e988ec39332227913eb38c2cfb3. Existing guarded 60 FPS recipe records its entry/hash/address; it is not applied twice.
- User subsequently requested removal of letterboxing. Added a separate hash-guarded 16:9 preparation recipe for the exact current SELF/ELF. It changes only the verified aspect float (2.4 to 16/9) in derived output and is independent of 30/60 timing.
- Launcher defaults to the new 16:9 profile and exposes Original as recovery; CLI defaults to Original unless explicitly selected. Cache/receipts include the aspect recipe and applied/source-verified status. All five display guard tests, seven timing tests, 27 backend tests and 11 launcher tests pass before the additional persistence assertion.
- Original 1920-wide scene detail remains the initial test target; 720p/900p resolution entries are not applied automatically. The XML warns of native 1080p visual issues, so full-screen quality remains pending a live render check.
- FSR backend real offscreen test passed two frames on RTX3070 with Khronos and sync validation: zero errors/warnings. DLSS offscreen validation is in progress. These are provider tests, not gameplay acceptance.
