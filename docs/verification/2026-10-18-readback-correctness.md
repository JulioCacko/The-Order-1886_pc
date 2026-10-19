# Protected upload reads: correctness batch

Code revision: `96c26e28d9b013e01fd89609dfc9c7aabab9d416`, following the merged Go launcher preview in PR #25. [PR #26](https://github.com/JulioCacko/The-Order-1886_pc/pull/26) contains this batch.

## Change

Adapted the protected-copy prerequisite from donor `D:/Emulator/theorder1886-port`, commit `3654b06`. Host upload workers and recorder callbacks now copy through the runtime's physical backing view while holding the mapping-table read lock. They no longer read a guest address that can fault into the recorder they are waiting on. Unmapped and reserved spans still return zero; wrapping requests return zero. Existing callers retain responsibility for GPU readback synchronization.

Fresh review reproduced a flexible-mapping split defect: the right fragment retained the first fragment's physical offset. `split_at` now advances physical offsets for every backed mapping. This also preserves the correct backing when the left fragment is removed. Reserved spans remain unbacked.

No adaptive buffer-read watch, HTILE synthesis, timing/provider feature or new launcher option is introduced. Those donor adaptations remain separate work.

## Verification

- RED: the original production upload-copy method faulted on an inaccessible guest source. The first compiled runtime fixture failed because the backing-reader interface did not exist.
- GREEN: two compiled regressions pass against production code. They cover protected guest addresses, sparse gaps, reserved spans, direct/flexible backing offsets, zero-length/wrapping requests, remapping and concurrent mapping changes. The exact upload-copy helper is compiled against the backing interface.
- Review RED/GREEN: right-fragment bytes after a flexible split were wrong before the shared split correction; both direct and flexible split/removal cases now pass. The reviewer reran both compiled tests independently and approved the corrected change.
- Windows: `bash build.sh --test` rebuilt the native runtime and passed **42 native checks**, including the backing-reader fixture. `python -m unittest discover -s tests` passed **355 tests, no skips**, after the split correction. The private environment is the same one used for the Go preview; other previously provenance-recorded fixtures remain in use.
- Linux: the [focused hosted workflow](https://github.com/JulioCacko/The-Order-1886_pc/actions/runs/39183203207) passed both compiled regressions at `96c26e2`. This is a helper/shim check, not a rebuilt Linux portable package or Linux GPU qualification.
- Final native SHA256: `49ccaeab3c3594bd653ae05a2dc0ea6aefdf6b832f393f84d6e6df29d9158b84`. The receipt records `source_dirty=false`, source `96c26e2`, and source-file digest `1e7f102f71d0bf5310d0b8141198475914052fd3169ef4ba363745c88f2be17a`.
- Evidence: `out/order1886-evidence/readback-correctness/{native-full,python-full}.log`, plus `out/runtime-build.json`. Isolated submodule path/line-ending configuration was repaired after initialization; no dependency content or pinned revision was changed. Original checkout, game files and saves were not modified.

## Acceptance boundary

The published Go preview 1 ZIP retains runtime `ca77edaf...` from native source `54242e0`. This batch publishes source separately; it does not replace that tested download with an unqualified native build. No issue is closed by this fix. The manual street comparison remains deferred at the user's request. Actual GPU synchronization under gameplay, readback/HTILE behavior and performance costs still need matched captures; update 1.02, campaigns, temporal providers, frame generation and the remaining gold features/gates are open.
