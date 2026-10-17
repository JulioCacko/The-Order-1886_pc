# Donor reuse verification, 2026-10-17

Scope and source attribution: [donor reuse report](../order1886-donor-reuse.md).

## Build identity

- Windows CLANG64, clang 22.1.8, `RelWithDebInfo`, LTO off.
- Source base: `519d54aba69f72d8a39d3d29b380e3a85e74a2b8`, with local changes.
- Runtime: `out/order1886-runtime.exe`.
- Runtime SHA256: `b4e9fdd14faae1a6719d3e4e383601fbeadc3026c8b8da3741dae1fb7511a041`.
- Source-files SHA256 from build receipt:
  `9a225de4908e87eaefdfd1b1ae26c093763e9e49603240b8a4180d50f6ec8ab1`.
- Receipt: `out/runtime-build.json`, generated at `2026-10-17T20:37:57.162291+00:00`.
- `--runtime-info` reports `order1886-native-1`, `PS4BOOT5`, `native-ps4`.

The runtime is a source-build output. Existing distributable ZIPs are separate
artifacts and do not acquire these changes automatically.

## Regressions demonstrated before the fixes

- The descriptor fixture rejected the old implementation with:
  `resource-free shader must keep its user-data push-constant offset`.
- The production-translator math fixture failed on
  `Translate(opcode, 0, exceptional, 7) == 7`: legacy multiply-add propagated NaN
  for a zero operand paired with infinity/NaN.
- The compute binary-cache fixture could not compile against the old API because
  `CreateCachedComputePipeline` did not exist.
- The vendor policy fixture could not compile before the extracted policy was
  added. Its completed assertions cover Intel static defaults and vendor overrides;
  this is CPU policy coverage, not Intel hardware rendering evidence.

Local red logs: `out/donor-math-red-run.log`, `out/donor-compute-red-build.log`,
`out/donor-vendor-red-build.log`.

## Passing checks

1. `bash build.sh --test`: passed after all changes, including all 13 Windows CPU
   executables in the build gate. Covers runtime keys, event flags, memory hooks,
   services, content, native rendering baseline, descriptor validation, pad,
   frame trace, overlay, shader math, graphics/compute binary cache and vendor policy.
   Log: `out/donor-final-native-verification.log`.
2. `python -m unittest discover -s tests`: 192 tests, 28 skipped, no failures,
   60.660 seconds. Log: `out/donor-python-retest.log`.
3. RTX 3070 Vulkan initialization with binary caching disabled and requested:
   passed; global key sizes were 0 and 8 respectively. Both executions also passed
   missing-entrypoint, invalid-key and disabled-extension fallback fixtures.
   Logs: `out/donor-vulkan-disabled.log`, `out/donor-vulkan-enabled.log`.
4. `pipeline-binary-cache-test --gpu out/donor-pipeline-gpu-verified`: passed on
   NVIDIA GeForce RTX 3070. Real graphics and compute shader modules and pipelines
   were created successfully. Cache summary: **4 hits, 2 compiled, 0 rejected,
   2 saved, 0 cache errors**. Log: `out/donor-vulkan-cache-gpu-verified.log`.

The first Python run, concurrent with the native rebuild, failed
`test_watchdog_kills_and_reaps_child`: its 150 ms watchdog expired before the
fixture child printed its PID. The isolated 28-test backend rerun passed, followed
by the complete passing 192-test rerun above. No production timeout was changed.

The first real graphics cache smoke failed an existing `files == 2` assertion.
The driver assigned the same binary key to triangle/line variants with rasterizer
discard enabled, producing one valid file. The test now compares stored files
against the keys actually returned by the driver, and also checks cold/warm
compute pipeline creation. Binary restoration checks and fallback tests remain.

## Limits

No game-content or save files were changed. No gameplay acceptance is asserted:
Intel character rendering, the invalid 8,029-layer crash (#5), sustained 4K/60,
QTE/timing correctness and long-session stability require further runs. The real
Vulkan smoke creates pipelines and exercises binary caching; it does not render
or benchmark The Order gameplay. Skipped Python tests are not passing evidence.
