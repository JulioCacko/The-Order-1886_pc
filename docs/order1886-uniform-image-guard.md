# Uniform guards for optional sampled images

Implemented a bounded, generic guard for resources that the guest shader can only
sample when a flattened unsigned uniform exceeds a constant threshold. This
addresses host descriptor inspection of conditionally unused textures. It does
not establish that the reported New Game/Continue failure is fixed.

The pass runs after SRT flattening and before resource patching. Structured ASL
does not exist at that point, so the analysis uses the existing CFG and explicit
true/false edge polarity. An edge is mandatory only when removing it makes the
use unreachable from entry. This proof supports outer backedges without
evaluating Phi values or induction variables.

Necessary gates propagate through Boolean AND, 64-bit mask AND, Ballot,
InverseBallot, and `Select(condition, unknown, 0)`. Phi, GPU loads, ReadLane, and
other unsupported expressions remain opaque. Shared SSA expressions are memoized
by instruction and polarity; exceeding the 4096-node work budget disables the
whole edge proof. The pass does not hardcode a shader hash, flat slot, threshold,
descriptor address, or malformed-tail pattern.

Before any descriptor fetch, the pass aggregates all uses sharing the descriptor
source prefix. An unguarded use, a different full source/view contract, unresolved
shared tail, depth/R128 use, or non-sampled instruction disables the optimization.
Image-dependent sampler post-ops also disable it for images sharing that sampler.
Ordinary shared samplers retain their existing behavior.

Only ordinary non-depth, non-atomic, non-written, full-width ImageSampleRaw uses
with no descriptor post-op are eligible. Their inactive permutation compiles a
float 2D or 2D-array placeholder with no image backing. When the guard is unknown,
missing, or active, descriptor validation and fetching proceed unchanged.
The existing immutable declared binding count remains authoritative.

Each eligible resource persists a count-fetch recipe, unsigned threshold, and
covered-use count. The current matching Info flat snapshot supplies the value.
Active/inactive state is compared explicitly before specialization's unbound and
wildcard shortcuts. A transition therefore selects a different permutation and
the existing permutation-index-based module hash. FMask dependencies retain the
source guard and its state as well. Cache versions are now shader binary 13,
shader metadata 10, and pipeline key 8; existing raw metadata serialization
includes the new fields in both canonical and effective Info records.

With the existing `ORDER1886_DIAG_RESOURCE_SHARPS=1` diagnostic enabled, at most
32 guard traces report shader/stage, resource and Info identities, derived count
source, current value, threshold, flat size, and proven use count. They are off by
default and perform no extra guest-pointer dereference.

Verification:

```powershell
rtk python -m unittest tests.test_order1886_uniform_guard
```

The portable fixture compiles the production pass and seven real IR source
files. It passed in 48.564 seconds. Cases cover both branch polarities, alternate
entries, outer backedges, opaque Phi AND masks, shared guarded/unguarded and
incompatible uses, unresolved aliases, sampler post-ops, relocated count slots,
the 9/10 boundary, missing count data, inactive placeholder versus active Cube,
binding-count stability, active/inactive specialization in both comparison
directions, metadata-field roundtrip, and an 80-node Fibonacci SSA DAG. Separate
child modes confirm that active and unknown guards retain required-source
failures, exiting through the existing fatal path.

Direct syntax checks passed for resource_patching_pass.cpp, recompiler.cpp,
vk_pipeline_serialization.cpp, and vk_pipeline_cache.cpp using configured build
flags. The production pass also compiled in the CPU fixture. Independent review
found no remaining actionable correctness issue after the DAG memoization fix.

The coordinator owns the full native build and controlled GPU validation. The
next run must confirm actual guard activation with a recipe derived from that
module's current IR, inspect valid rendering and menu/progression behavior, and
check that an active or unknown malformed resource still fails explicitly.
