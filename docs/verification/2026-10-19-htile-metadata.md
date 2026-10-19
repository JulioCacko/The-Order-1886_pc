# Bounded HTILE metadata adaptation

This follow-up adapts the uniform HTILE read idea from donor `3654b0622aaa7648ee07c8dd493d9b0300ef1b6f` without its optional-value dereference or slice-zero assumption. It does not qualify shadow rendering or complete HTILE emulation.

The metadata registry records the owning image UID, type, layer count, stencil format and the byte extent observed at a metadata clear. State changes are locked without holding that lock across GPU operations. Rebinding the same owner preserves state; replacing ownership or geometry resets derived words. An old image cannot erase its replacement's entry. Unmapping metadata bytes removes the entry even if the depth image lives elsewhere. Temporarily disabling metadata in a binding retains the association, as the underlying allocation still exists.

Known, aligned, bounded HTILE reads can synthesize conservative full-range depth words when all tracked slices have the same clear/drawn state. Mixed slices, more than 32 layers, unknown extents and shader-written data retain the normal buffer path. The layer guard also removes undefined shifts. Depth writes update every layer in the attachment view; read-only depth bindings preserve clear state.

Uniform skipped clears and changed draw states materialize through the existing GPU buffer machinery. Uploads preserve neighboring bytes, normal page tracking observes CPU overwrites, selective mode watches small generated buffers, and GPU byte ranges participate in downloads/unmaps. Buffer writes, storage-image bindings, explicit fills/copies and CPU invalidations cancel derived metadata. GPU publication alone does not count as a new shader write. Explicit non-clear HTILE fills keep their real words. Up to eight materializations are logged for bounded runtime evidence.

The permanent CPU model regression checks clear/draw transitions, mixed slices, stencil words, bounded reads, zero/wrapping ranges, overlapping metadata registration, shader writes, image UID reuse, geometry changes, unmap and concurrency. A compiled slice of the production `ObtainBuffer` path additionally checks upload-before-fill, CPU tracking, selective watches, GPU range registration, preserved neighbors and ordinary fallback for written metadata. These are CPU fixtures, not Vulkan or visual evidence.

Initial full checks pass 365 Python tests and 45 native checks. Later boundary/unmap adjustments require final reruns and fresh review before publication. The graph service remains unavailable (`Transport closed`); exact source and caller searches cover this bounded scope.

## Qualification still required

- Mixed-slice HTILE tile layouts are not inferred. The fallback uses real guest/GPU buffer bytes; depth-driven per-tile metadata updates remain incomplete there.
- Conservative uniform min/max and stencil words need matched gameplay/capture acceptance. Synthetic words can introduce buffer fills and synchronization costs; performance must be measured.
- Metadata-clear shader recognition retains the existing heuristic. Its exact game shader inputs and output ranges need runtime evidence.
- No shadow, aiming, FPS, temporal-provider, campaign, update 1.02 or Gold claim follows from these checks. No new player option is introduced by this internal correctness change.
