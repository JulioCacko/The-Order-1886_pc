# Synchronous selective buffer readbacks

This source follow-up implements the small-buffer read-watch prerequisite from donor `3654b06`, using the existing synchronous download path. It does not import promoted deferred buffer copies or their stale-data policy.

## Behavior

- The default `relaxed` policy is unchanged. In `selective`, writable GPU buffer bindings up to 64 KiB mark their 4 KiB pages for CPU read tracking. A CPU access downloads the current GPU bytes and waits for completion before releasing protection. `precise` tracks all GPU-written buffer pages.
- Repeated overlapping watches are idempotent. Ordinary downloads keep the watch for later GPU writes. A CPU overwrite flushes first and then clears that page's watch; unmap uses the same invalidation path so remapped pages do not retain the previous watch. No deferred buffer payload survives an unmap.
- GPU-written byte-range mutations and downloads share a mutex. Downloads acquire the region lock before the byte-range mutex; writable bindings release the region lock before acquiring the byte-range mutex.
- The Go Performance page exposes **GPU readback policy**, autosaves valid choices and marks them for next launch. Home reports the requested policy. Shared settings, direct Play and CLI `--readbacks` forward the same policy to `ORDER1886_READBACKS`.
- Selective and precise require a hash-bound native receipt declaring support. Older/custom runtimes remain visible with an availability reason; saving an unsupported choice is rejected. Backend validation also rejects mismatched receipts. Disabled readbacks remain unavailable in the player profile.
- Runtime selection is re-resolved before checking cached capabilities, including a new `bin` runtime shadowing the source `out` runtime. Existing runtime hash/profile/ABI verification remains in force.

## Verification in progress

RED/GREEN checks cover the missing policy mapping, protection transitions in disabled/relaxed/precise/selective modes, invalid native mode fallback, old/mismatched/malformed receipts, saved-value preservation and default-runtime replacement. The fresh reviewer found the default-runtime cache defect; its filesystem regression failed before correction and passes afterward. The reviewer approved the corrected code and independently reran all six focused tests.

The native gate passes **43 checks**, including all readback modes. TypeScript/Vite production build and four frontend state tests pass. Final full-suite/portable evidence and clean code identities are recorded with this batch before publication.

## Limits

These fixtures establish CPU tracking and launch plumbing, not aiming focus, current visual quality, GPU lifecycle stability or an FPS improvement. Synchronous selective/precise modes may add waits. The existing relaxed default is retained pending matched gameplay measurements. HTILE, deferred readbacks, temporal providers, frame generation and the remaining gold features/gates remain open.
