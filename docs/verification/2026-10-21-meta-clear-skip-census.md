# Metadata-clear skip: which shaders reach it in The Order: 1886

`Rasterizer::IsComputeMetaClear` (`gpu/shadps4/video_core/renderer_vulkan/vk_rasterizer.cpp`) skips a
compute dispatch and marks the metadata cleared when the shader has no bitwise XOR, reads no
metadata, and writes only registered, aligned, fully mapped metadata ranges. On PR #88, CodeRabbit
pointed out a risk. An ordinary compute write that meets those conditions would be dropped, and its
surface would be wrongly marked cleared.

This census asks whether The Order: 1886 issues such a dispatch. **It does not, in the two scenes
measured.** Exactly one shader reaches the skip. It is the Gnm fill kernel, and it only ever writes
clear values. No stricter predicate was added. The heuristic is upstream shadPS4's, and a narrower
one would risk the PR #88 regression again (flat sky-blue gameplay when depth is never cleared).

## Method

A temporary build of PR #88's head (`3379102`) added two diagnostics. Neither is committed:

- On the skip path, a count per key. The key is the shader hash, the metadata type of each written
  range, and the shader's user-data registers. At each power-of-two count, the build logged the
  hash, dispatch size, written ranges and user data at warning level. `native.log` drops info
  level.
- `PipelineCache::DumpShader` was forced on, so that every compiled shader was written out as
  GCN binary and SPIR-V. The compute SPIR-V was decompiled with `spirv-cross` from MSYS2 CLANG64.

The runs used `tools/order1886_step1_evidence.py` on branch `graphics/step1-cheap-wiring` with
`--keys 45:space 53:space --only baseline`. The runtime was in its own directory under that
worktree, at `out/metaclear-diag/`. ORDER1886_HTILE kept its default value of 0. Evidence is in
`out/order1886-evidence/metaclear/` in that worktree.

| Run | Savedata | Delays (s) | Reached | Rendering |
|---|---|---|---|---|
| `prologue2`, `prologue3` | copy of `savedata-backup-20261020-before-chapter11` | 120, 150, 190 | Prologue cell cutscene | cell floor and walls render; 43 fps |
| `ch11` | copy of the player's Chapter XI `savedata` (read only) | 60, 120, 190, 240 | Chapter XI, Continue | Grayson in a lit alley, full geometry; 17 fps |

## Result

Of the 47 compute shaders compiled in the Prologue, 41 decompile without an XOR. Only one of them ever
reached the skip, in either run:

| Hash | Dispatch | Writes | User data (count, value) | Skips (lower bound) |
|---|---|---|---|---|
| `0x9846aaff` | 512 groups of 64 | HTILE, 0x20000 bytes | `s2=0x8000`, `s4=0xfffffff0` | 16384 Prologue, 8192 Ch. XI |
| `0x9846aaff` | 64 groups of 64 | HTILE, 0x4000 bytes | `s2=0x1000`, `s4=0xfffffff0` | (shares the HTILE count) |
| `0x9846aaff` | 64 groups of 64 | CMASK, 0x4000 bytes | `s2=0x1000`, `s4=0x0` | 16384 Prologue, 8192 Ch. XI |

The counts are the last power of two logged, so each one is a lower bound within a factor of two.

Decompiled, the shader is the standard Gnm buffer fill. Each invocation computes its global index.
If that index is below a user-data count, it stores a second user-data dword at that index. There
are no loads and no lane-dependent data: the stored value is the same for every thread. The count
covers the whole range exactly (0x8000 dwords for 0x20000 bytes, 0x1000 for 0x4000 bytes).

The values are clear values:

- HTILE `0xfffffff0` has ZMask 0, which means a cleared tile (`SurfaceMetadata::Fill` treats a low
  nibble of 0 as cleared).
- CMASK `0x0` is the fast-clear state.

Skipping these dispatches and marking the slices cleared is therefore exactly what the guest asked
for.

## Limits

- The runs cover two scenes, about 215 s and 265 s from boot. They do not cover other chapters,
  combat-heavy sections or menus beyond the title flow. A later level could use another shader.
  The same diagnostic would show it as a new hash.
- The skip still does not check the fill value. A fill of a non-clear value would be marked cleared
  all the same. For example, HTILE `0xfffc000f` is the expanded state. No such fill was seen. If one
  appears, the value is in user data at dispatch time, and the skip could pass it to
  `TextureCache::FillMeta`, which already treats it correctly, instead of `ClearMeta`.
- The native check `test_htile_unsupported_clear_executes_original_shader` covers the recognizer's
  range rules. It does not cover shader content: a fixture shader is a list of buffer descriptors.
