# Image layout and upload bounds

Observed run: `user/order1886/diagnostics/srt-bounded-null-4k-cold/native.log`.

- Line 5460: a BC6H image requests 4096 layers; this device supports 2048.
- Line 5463: upload region 0 accesses 17,179,804,672 bytes in a 1,610,612,736-byte buffer.
- Line 5468: upload region 1 accesses 4,294,935,040 bytes in the same buffer.

The host layout stored each mip size and cumulative offset in `u32`. Region 0's
full pitched mip requires 16 GiB; region 1 requires 4 GiB. Both wrap to zero in
the old multiplication, explaining their repeated buffer offset zero and the
undersized staging allocation. The raw descriptor responsible for this image is
not yet established. The preceding ordinary sharp capture has a related address
but only eight padded cube layers; it does not prove the failing resource's source.

Implemented safeguards:

- Tiling helpers widen their products before evaluating them.
- `ImageInfo` checks each full mip and cumulative size before narrowing into its
  existing `u32` fields. Color and depth attachment layouts use the same check.
- Rejected resource layouts independently retain the raw eight-word sharp and its
  fetch offsets, with a separate 16-record budget. The ordinary 512-record capture
  limit cannot suppress this diagnostic.
- Image creation checks the actual format query result, extent, array layers,
  mip limits, sample mask, and actual host memory requirements before VMA allocates
  memory. Host memory requirements, rather than guest pitch padding, are compared
  with `maxResourceSize`. Maintenance4 supplies a creation-free query; older devices
  use an unbound temporary image which is destroyed before VMA allocation.
- Upload byte spans use checked 64-bit arithmetic, compressed block rounding and
  depth/stencil aspect sizes. Every upload is checked against the actual source
  buffer capacity before changing image state or recording Vulkan commands.

Unsupported layouts fail explicitly. The checks do not clamp dimensions, remap
formats, or replace mapped unknown resources with null descriptors.

CPU reproduction:

```powershell
rtk python -m unittest tests.test_order1886_image_bounds
```

The fixture compiles the production `UpdateSize` and tiling function bodies plus
the shared bounds helpers. It exercises the exact observed 17,179,804,672-byte span,
16 GiB and 4 GiB narrowing failures, cumulative overflow, normal cube/mip layouts,
small compressed copies, arithmetic overflow, depth/stencil aspects, and device
extent/layer/mip limits. Direct syntax checks use the configured build.ninja flags
for `image.cpp`, `image_info.cpp`, and `vk_runtime.cpp`.

The coordinator owns the full build and serialized GPU rerun. These CPU checks do
not establish valid rendering, menu access, gameplay, or 60 distinct frames.

Next executable step: build `out/gpu/order1886-runtime.exe`, record its hash, and
repeat the cold 4K FSR1 validation run. The first rejected layout should provide the
missing raw descriptor context without issuing either invalid Vulkan operation.
