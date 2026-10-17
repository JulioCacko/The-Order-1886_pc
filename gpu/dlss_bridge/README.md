# Optional Order Vulkan DLSS Super Resolution provider

Build separately from the MinGW host with x64 MSVC 2022:

```powershell
rtk proxy pwsh -NoProfile -File gpu/dlss_bridge/build.ps1
```

The script finds existing Vulkan headers from `out/gpu/CMakeCache.txt`, or accepts
`-VulkanInclude`. It obtains the pinned official NVIDIA SDK **310.9.16** only when
missing, under ignored `out/deps`, verifies the release runtime hash, and builds
`out/dlss-bridge/Release/order1886_dlss.dll`. The adjacent release
`nvngx_dlss.dll` is **310.9.16.0**. No proprietary source or binary belongs in Git.
`out/dlss-bridge/provenance.json` records source and binary/license hashes.
The bridge's MIT license and NVIDIA's separate SDK license both apply; shipping
NVIDIA code requires satisfying its redistribution and notification conditions.

## Host integration

- Load the DLL by absolute path; resolve C export `order1886_dlss_get_api` with
  `ORDER1886_UPSCALE_ABI`. An MSVC import library must never be linked into the
  MinGW host. Keep both DLLs available for the complete provider/device lifetime.
- Before instance/device creation query both extension callbacks, copy/deduplicate
  the returned names with the renderer's extension lists, check support, and
  enable them. The provider uses official NGX feature-specific discovery queries.
  Device probing/NGX errors mean unavailable, never silent success.
- Supply the real Vulkan instance, physical/logical device, queue/family and proc
  loaders to `create`. Vulkan 1.1+, an NVIDIA adapter, DLSS SR capability and a
  suitable driver are required. Only one context is supported at a time; this
  keeps the NGX global API serialized without cross-device shutdown hazards.
- `create` initializes NGX and checks capability. Because this ABI has no creation
  command buffer, the first `dispatch` creates the SR feature on the **caller's
  recording command buffer**, outside a render pass/dynamic rendering. It can
  fail at this point even after a successful context create. Treat that as an
  unavailable/failed provider; discard the failed command buffer before recovery.
- Supply active-scene color/output RGBA16F, depth R32F and motion RG16F, with
  separate output, sampled inputs, STORAGE|TRANSFER_DST output and single-mip/layer views.
  Inputs may be GENERAL or SHADER_READ_ONLY_OPTIMAL; output must be GENERAL.
  NGX performs transfer clears on the output, so TRANSFER_DST is required even
  when the caller only plans to sample it. The provider records producer/consumer
  barriers covering transfer and compute operations, temporarily uses read-only
  input layouts, then restores declared layouts and makes output writes visible.
  All images must be owned by the supplied graphics queue; no ownership transfer
  is performed. The caller must rebind pipeline/descriptors/dynamic state after
  NGX evaluation and retain resources until its submission completes.
- Jitter is in render pixels. Motion is current-to-previous; scale values convert
  motion texture values to render pixels. These conventions, depth inversion,
  HDR/pre-exposure, real frame interval and Order history resets must be proven
  by the renderer adapter. The plugin does not fabricate motion/camera inputs.
  First evaluation forces a history reset; later resets follow the supplied flag.
- Configured render/output ratio chooses quality/performance mode; **preset K**
  is requested in every mode. No frame generation, sharpening or scene detail
  changes are added. Runtime/driver overrides can still affect actual model use;
  verify the effective model and image quality during capture validation.
- There are **no private command submissions or GPU waits**. After a dispatch
  failure, discard the recording and destroy/recreate the context after previous
  GPU work completes. Before destroy, output resize, provider switch or DLL
  unload, the caller must finish all work using that context. Failed recording
  poisons the context: later dispatch calls reject it without recording work,
  since feature initialization may have been discarded with the failed buffer.
  Destroy also frees
  NGX resources; it does not wait for the GPU. Never unload with a live context.

## Validation boundary

CTest verifies frame/config rejection and DLL C ABI negotiation, null handling,
failure output clearing and invalid-context handling without initializing Vulkan
or NGX. A separate fake-NGX/Vulkan lifecycle test exercises failed creation and
failed evaluation, rejects retry of the poisoned context, and verifies fresh
creation/history reset and successful evaluation after destroy/recreate.
It establishes CPU contracts only. A parent-controlled GPU test and real
Order captures must establish resource synchronization, effective preset, visual
correctness, memory behavior and performance before the provider is enabled.
