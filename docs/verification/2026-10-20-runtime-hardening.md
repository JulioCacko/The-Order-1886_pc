# Runtime and shader hardening: what changed, what proves it, what does not

Nine rounds of work (12–20 of the current sweep) compared this tree against three references —
upstream `shadps4-emu/shadPS4`, the original `FelipePrado0/SpartanPort` fork, and the installed
game's own executable — and fixed the defects that comparison exposed. This file records them in
one place so a reader does not have to reconstruct the story from twenty pull requests.

**Nothing here is acceptance for anything.** Independent review of these merges (round 22) found one regression — a zero `max_index_size` capping direct draws to a single index — which is fixed and covered, plus several checks that were weaker than claimed; both are recorded below rather than left implied. None of it was exercised against The Order: no frame
was captured, no image compared, no frame rate measured. What each entry can claim is narrower and
checkable: the code no longer aborts, no longer reads outside the buffer it was given, or no longer
computes an address the wrong way. `build.sh --test` runs all of it without a GPU or a guest.

## How the findings were produced

- **Upstream diff.** Every file present in both this tree and upstream shadPS4 was ranked by how
  many lines upstream has that we do not (131 files). Three independent triage passes then judged
  each candidate: a correctness fix, an upstream feature we deliberately lack, or a case where this
  tree is newer. Only the first kind was ported.
- **The game's own import table.** The installed `eboot.bin` was copied out and decoded (SELF → ELF
  → `DT_SCE_SYMTAB`), giving 355 imported NIDs. The NID encoding was validated three ways: all 355
  round-trip byte-exactly, `prepare.py`'s forward function reproduces one of the game's own NIDs, and
  the same encoding matches upstream's registered NIDs for 4439 of 4861 entries.
- **The original fork.** SpartanPort is a God of War port; its patch data does not transfer, but its
  design documents for the temporal/upscaler layer do, and they are mapped file by file in issue #7.

## The fixes

| Round | Defect | Fix | Test |
|---|---|---|---|
| 12 | A guest **cube** image descriptor reached `UNREACHABLE()` in the type conversion and killed the session | `image_type_map.h` maps `Cube` to a 2D image, with the switch as the single source of truth for "is it mapped" | `image-type-map-test` |
| 12 | An image allocation that went over the device budget asserted instead of allocating | Upstream's retry: clear `WITHIN_BUDGET` once, warn with the size, try again | build + the same test |
| 13 | `Thin3DThinPrt` mapped to the **non-PRT** array mode, so `IsPrt()` was false and the bank swizzle wrong | Map it to `ArrayPrt3DTiledThin1` | `upstream-fixes-test` |
| 13 | `sceGnmDrawIndirectMulti` declared a **five-word** packet while writing six, desynchronising the DCB | Declare six | `upstream-fixes-test` |
| 13 | A faulting read always asked for **8 bytes**, so a fault near the end of a mapping could never resolve | Clamp to the page via `PageManager::FaultAccessSize`, which the test calls directly | `upstream-fixes-test` |
| 13 | Eviction floors were fixed defaults, so a **sub-6 GB** budget got a critical threshold above the whole budget | Floors follow the device, as upstream does | `upstream-fixes-test` |
| 13 | The wait-stage-mask array held 2 entries while a submission may carry 4 waits | Size it from `SubmitInfo::wait_semas` | build + `static_assert` |
| 14 | `Sampler::Valid()` returned `true` unconditionally, so a reserved S# field reached the conversion switch (abort) or read a border colour from guest address 0 | Range-check the fields; a custom border colour also needs its table | `sampler-validity-test` |
| 15 | The index buffer was sized from `num_indices` and never clamped to mapped memory; indirect draws read past it | `ResolveIndexRequest` owns the decision (`max_index_size` bounds an indirect draw, and zero means "no cap" because the register is only written by two packet types), clamp through `ClampRangeSize` | `index-buffer-request-test` |
| 16 | The stencil companion was sized `pitch * height` — no layers, tiling or multisampling | Per-slice size from the tile geometry × layers | `stencil-surface-test` |
| 16 | A **stencil-only** target decoded from the depth address with depth geometry | Use the stencil address/size and eight bits per texel | `stencil-surface-test` (primitive only; see limits) |
| 16 | Eight guest imports had no handler in either resolution layer: `sceKernelUtimes`, `Chmod`, `Getdents`, `select`, `pthread_setschedparam`, `scePthreadGetschedparam`, `scePthreadSetschedparam`, `sceAppContentAddcontUnmount` | Ported from upstream with their error codes | `missing-imports-test` |
| 17 | `uses_fp64` was set for 2 of the 38 fp64 opcodes, so an fp64-capable GPU got an **invalid SPIR-V module** instead of the fp32 fallback | The arm lists every fp64 opcode the IR declares | `test_order1886_f64_opcode_coverage.py` |
| 17 | `V_TRUNC_F64` and `V_MIN_F64` were dispatched nowhere; the default arm logged and wrote nothing | Ported both | same |
| 18 | `sceGnmComputeWaitSemaphore` answered `ORBIS_OK` and wrote **nothing** into the guest's buffer | Encode the ten-dword packet | `gnm-decisions-test` |
| 18 | `sceGnmSetGsRingSizes` always succeeded and never published the ring sizes | Sony's 1 MB/4–8 MB contract, then write `vgt_esgs/gsvs_ring_size` | `gnm-decisions-test` |
| 18 | `sceGnmSetupMipStatsReport` returned success over uninitialised memory | Error codes, clear, write the `0x40` sentinel. Only 64-byte alignment is enforced: upstream's address mask would reject any buffer above 16 MB, and failing a call the stub used to accept would be its own regression | `gnm-decisions-test` |
| 19 | `sceGnmDrawIndirectCountMulti` was a stub that called `UNREACHABLE`, with its opcode, struct **and** dispatcher case deleted | Restored all three; the packet fills the `0x10` dwords the guest asserts | `gnm-decisions-test` |
| 20 | The shared-memory barrier pass returned early unless the workgroup was exactly one wave, so wider workgroups got **no barrier at all** | Emit subgroup-scoped memory barriers, as upstream does. Note this also adds barriers where `needs_lds_barriers` is false (non-NVIDIA drivers): that matches upstream, but it is a change from "none" there, not only for wide workgroups | `shared-memory-barriers-test` |

`build.sh --test` went from 47 to **55 native checks** across these rounds; the Python suite grew
from 502 to 559 tests, including guards that read the opcode table and the field catalogue rather
than hand-written lists.

## Limits, stated plainly

- **No game was run.** Every claim above is about code, not behaviour on the title.
- **Some checks are weaker than their row suggests.** `stencil-surface-test` pins the sizing primitive, not the `ImageInfo` branch that uses it; `gnm-decisions-test` checks the indirect-count packet's layout and opcode values, not the producer that writes it; `index-buffer-request-test` does not exercise the caller that passes `is_indirect`. Every one of these is still a real assertion — it is just not the whole path.
- **Issue #5 is still open.** The array-layer abort remains for genuinely unsupported shapes; the
  refusal path added earlier is unverified against the 8029-layer reproduction, which nobody has
  provided.
- **The stencil-only branch has no direct test.** It lives in `ImageInfo`'s constructor, and
  constructing that needs a texture cache; the test covers the sizing primitive it depends on. The
  branch matches upstream line for line and is visible in the diff.
- **The import port is thin in places.** `select` has no sockets here and a `NULL`-timeout `select`
  over nothing ready blocks forever, exactly as POSIX does. `chmod` reduces to one host bit.
  `AddcontUnmount` unmounts nothing because the provider never mounts add-ons.
- **Two upstream candidates were deliberately not ported.** The overlap-resolve subresource drop is
  entangled with the aliasing and readback state machine; the `ClearStrideAndBitshiftDw2WithImm`
  heuristic keys on a shader idiom with no evidence this title produces it, and a wrong match would
  corrupt descriptors.
- **A correction worth keeping.** The audit's first pass said twelve imports had no handler; four of
  them resolve already through `canonical_name()` folding `#libScePosix` onto `#libkernel`. Eight
  were ported, four were verified instead of duplicated.

## Reproducing the audits

The scratch tooling lives outside the repository (in `out/`, which is ignored): the upstream delta
ranking, the NID extraction, and the format-mapping comparison. The method is described above in
enough detail to rebuild them; the numbers in this file are the ones those runs produced on
2026-10-20.
