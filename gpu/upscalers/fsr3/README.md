# Order FSR 3.1.4 Vulkan provider

`order1886_fsr3.dll` exports `order1886_fsr_get_api` for `gpu/shim/order1886_upscale.h`.
The implementation uses the vendored `gpu/third_party/fsr-vulkan` portable
upscaler API, its FidelityFX SDK 1.1.4 host/backend sources and checked FSR 3.1.4
SPIR-V. No vendor sources or shader payloads are modified.

## Caller contract

- Create the Vulkan instance and device at Vulkan 1.2 or newer. No additional
  instance/device extensions are required. Enable core
  `shaderStorageImageWriteWithoutFormat` on the logical device and report that
  actual enablement in `OrderUpscaleDevice`. The chosen queue must support compute.
  Optional float16/subgroup/synchronization2/coherent-memory features are not
  presumed enabled.
- Images must be optimal-tiled, single-sample 2D, one mip and one array layer.
  The ABI cannot inspect those properties; the caller guarantees them. All three
  inputs are sampled images in `SHADER_READ_ONLY_OPTIMAL`: RGBA16F color, R32F
  depth, RG16F motion. Output is RGBA16F storage in `GENERAL`, disjoint from the
  inputs, at the configured output size. Input allocation extents may cover a
  smaller dynamic render size but cannot exceed configured maximum render size.
  Views are required metadata; the SDK creates its own resource views.
- Use active-scene images and real, capture-verified depth, motion, pixel jitter,
  motion scale, camera planes/FOV, exposure and frame time. Negative motion
  scales are valid. Camera planes describe physical near/far distances; pass a
  finite far sentinel (zero is accepted) for infinite depth. The inverted-depth
  flag is separate. Camera units map to meters with factor 1.
- Contexts use auto exposure and dynamic resolution. There are no external
  exposure/reactive/composition masks in this ABI. First dispatch and dispatch
  following a backend failure reset temporal history. Caller requests reset for
  cuts, loads, scene changes, and discontinuities.
- Record into an already-recording caller command buffer outside a render pass.
  Inputs must be made visible to compute sampled reads and output to compute
  storage writes before dispatch. The SDK returns external images to their
  supplied resource states. Caller inserts synchronization before subsequent
  consumers. Dispatch can replace Vulkan compute pipeline/descriptor state;
  caller rebinds its own compute state afterward.
- Serialize each context's create/dispatch/destroy usage and submit recordings
  in record order. Keep images, device, and provider loaded until work completes.
  Wait for relevant frame fences before destroy. The provider never submits or
  waits on a queue. On a dispatch backend error, discard that recording because
  it may contain partially recorded work, then reset/retry or use recovery.

## Build and CPU checks

Standalone: configure this directory with CMake, a C/C++ compiler, Vulkan headers
and loader, then build target `order1886_fsr3`. Set
`ORDER1886_FSR3_BUILD_TESTS=ON` to add `order1886_fsr3_contract` (real provider with
a CPU-only replacement of the GPU SDK boundary) and `order1886_fsr3_load` (loads
the production DLL and checks its ABI/null handling without creating a device).
Run `ctest --test-dir <build-dir> --output-on-failure` with compiler runtime DLLs
on `PATH`. No GPU test is registered with CTest.

For a manually coordinated offscreen run, configure
`ORDER1886_FSR3_BUILD_GPU_SMOKE=ON`, explicitly build
`order1886_fsr3_gpu_smoke`, then run
`order1886_fsr3_gpu_smoke --run-gpu OUTPUT_DIRECTORY`. The executable requires
that opt-in argument and is excluded from the default build. It selects the
RTX 3070 and exercises two 128x72-to-256x144 frames through the real provider DLL:
static gradient/checkerboard color, constant-plane R32F depth, and zero RG16F
motion, with reset followed by history. The harness owns image uploads,
barriers, command submission, fence waits and RGBA16F readback. It rejects
nonfinite, black or nonvarying output, writes both readbacks, and reports
device/driver details plus validation diagnostics. It enables the Khronos layer
if discoverable. For the existing MSYS2 installation, process-local
`VK_LAYER_PATH=C:/msys64/clang64/bin` exposes that layer; request synchronization
validation with `VK_LAYER_VALIDATE_SYNC=1`. Never use this synthetic fixture as
gameplay input or a gameplay/performance benchmark.

For the parent GPU CMake project use `add_subdirectory(upscalers/fsr3)`, arrange a
dependency from the runtime/package target to `order1886_fsr3`, and copy its
`$<TARGET_FILE:order1886_fsr3>` into the emulator's provider search directory.
The provider is loaded through the shared ABI; the emulator need not link the
SDK or provider directly. Package the compiler runtime and Vulkan loader as the
application already does. On MinGW Clang, the subdirectory supplies the SDK's
missing `<mutex>` include using a target-local compiler include option.

FSR4 and SDK 2.3 scaffolds, probes, vendor tests and installs are disabled. The
vendored SDK target bundles some FI/OF source into its static libraries, but this
provider exposes/calls only upscaling and never creates frame-generation state.

CPU checks and the small synthetic GPU smoke do not establish image quality,
Order input correctness, real gameplay integration, or 4K60 acceptance.
