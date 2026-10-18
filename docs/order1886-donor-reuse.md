# The Order donor reuse, 2026-10-17

## Additional authorized donor: Bloodborne PC

The user requested extensive reuse from `D:\Emulator\bloodborne_pc`,
[Jgamrot/bloodborne_pc](https://github.com/Jgamrot/bloodborne_pc), pinned at
`52e4988f54b0626447563874bf8695633b1a4302`. Its checkout was clean and its root
license is GPLv2. Preserve per-file notices and third-party SDK licenses when
adapting code. Keep that checkout unchanged.

Reuse is being evaluated by subsystem: renderer scheduling/resource handling,
temporal-provider plumbing, input/settings, localization, updates, mods and
achievements. The Order's executable guards, user-data isolation and branding
remain the integration contracts. Bloodborne engine addresses, shader matches,
camera conventions, asset formats and gameplay mechanics require separate Order
evidence. Donor feature availability does not certify those features here.

The donor's latest history includes a rollback of two texture-budget changes that
crashed an 8 GB GPU; newer renderer code is not accepted without regression and
RTX 3070 evidence. Findings and imported changes will be tracked against the
pinned revision rather than treating a whole-tree replacement as verified.

The integrated Bloodborne-derived batch includes recording-chunk reentry fixes,
arena-wide SRT fault registration, attributed launcher translations, reversible
asset overlays, and local trophy persistence. Order-specific validation and
failure handling were retained or strengthened. See the
[local integration record](verification/2026-10-18-gold-work.md) for tests, runtime
identities, Chapter 2 evidence, and remaining acceptance gates.

## Earlier Order-specific donor batch

This is the first compatibility batch from `D:\Emulator\theorder1886-port`,
[mateussmeneses/theorder1886-port](https://github.com/mateussmeneses/theorder1886-port),
inspected at `74500b7`. Both projects distribute their code under GPLv2; imported
shadPS4 code retains its existing GPL-2.0-or-later notices. The donor checkout was
read only. Existing launcher, save-import and graphics-probe work in this checkout
was retained.

## Imported fixes

| Donor commit | Change here | Regression evidence |
| --- | --- | --- |
| `91aa3ac` | Resource-free shader variants compare the user-data push-constant offset when the shader reads user data. Prevents a fullscreen clear from reading another stage's descriptor pointer. | `srt-descriptor-validation-test`: different offsets reject in both directions; shaders with no user-data reads can still share. Failed before the fix. |
| `d5ee454` | `V_MAC_LEGACY_F32` and `V_MAD_LEGACY_F32` use legacy multiplication, including zero times infinity/NaN; clamped log, reciprocal and reciprocal-square-root instructions clamp infinities to signed maximum float and preserve NaNs. | `order-shader-math-test`: executes the production translator, evaluates its emitted scalar IR, and checks legacy and ordinary instruction behavior. Zero times infinity failed before the fix. |
| `944c0ad` | Intel defaults to static vertex input to avoid the donor's reported black-character driver issue. `ORDER1886_VERTEX_INPUT_DYNAMIC_STATE=0/1` permits diagnosis on any vendor, subject to actual extension support. | `amd-paths-test`: Intel, NVIDIA, AMD, empty override and explicit override cases. Hardware rendering still needs Intel validation. |
| `6108e95` | Compute pipelines now use the same driver-keyed binary store as graphics pipelines. Unsupported, corrupt or rejected binaries keep the existing compile fallback and handle cleanup. | `pipeline-binary-cache-test`: compute miss, hit, rejected binary handles, rejected restored pipeline and disabled-extension fallback, plus existing graphics cache cases. |

Shader binary version advances from 13 to 14. Earlier compiled shader artifacts
are rejected automatically, including artifacts created with the incorrect math
or specialization rules. The native build's `--test` gate runs the new translator,
compute cache and vendor policy regressions on Windows and Linux. This batch was
validated on Windows; Linux execution remains unverified.

The [verification record](verification/2026-10-17-donor-reuse.md) contains build
hashes, red/green results and the passing RTX 3070 graphics/compute cache smoke.

## Relation to open issues

Issue numbers below belong to
[JulioCacko/The-Order-1886_pc](https://github.com/JulioCacko/The-Order-1886_pc/issues),
not to the donor's separate tracker.

| Issues | What this batch establishes / next work |
| --- | --- |
| #3, #14: performance and timing | Compute binary caching reduces repeated driver compilation when supported. No sustained 4K/60 or timing benchmark is claimed. Capture cold/warm results at the same checkpoint before accepting performance targets. |
| #5: invalid 8,029-layer image | Preserve this checkout's descriptor diagnostics, bounds validation, dynamic ReadConst lowering, walker rollback and mapped-range checks. Neither the donor nor this batch establishes the cause of the reported layer count. Reproduce with descriptor/shader provenance before changing image interpretation. |
| #4: mouse camera | Donor pad changes also weaken lifecycle, handle and user validation. Do not copy `runtime_pad.c` wholesale. Port mouse capture/remapping independently and test focus transitions. |
| #7, #10–#13: temporal upscalers | Donor camera, motion and temporal paths differ substantially from this checkout's native baseline. Import only after establishing valid Order motion vectors, depth, jitter and per-provider capability checks. Upscaler labels are not evidence of a working provider. |
| #8, #21: UI and game languages | Donor exposes 30 PS4 system-language IDs, but that does not implement independently selectable text and voice or guarantee installed localization assets. Adapt its language table after defining the runtime language contract. |
| #9, #18–#20, #22: updates, Steam, packaging, utilities, achievements | Donor includes reusable launcher/helper implementations. Its launcher is structurally different; adapt individual modules with persistence and packaging tests instead of replacing this checkout's five-page launcher or overwriting user settings. |
| #15–#17: cheats, effect settings, mods | Reuse only Order-specific, version/signature-checked patches. Existing mod overlay and content-validation contracts take precedence over donor shortcuts. |

## Already present or deliberately deferred

- Empty add-on enumeration already accepts nonzero service labels here. Keep the
  current SFO-backed metadata and explicit unavailable add-on behavior.
- The current loader already enters the main executable without separately
  running its fixed-offset initializer; the donor's double-initialization patch
  is unnecessary here.
- SRT walker sharing, speculative-fault isolation and mapped-range snapshots
  already have newer local hardening. Retain them.
- Donor async compute skips selected dispatches while compilation runs. Recurrence
  alone does not prove a dispatch has no persistent buffer side effects. Keep
  dispatch execution intact in this batch.
- Donor's synchronous pipeline restore budget depends on its newer asynchronous
  publication/permutation state. Port that state together with cache-pairing
  regressions before enabling the budget here.

No GitHub issue is closed by this document. Compiler/CPU fixtures establish the
listed semantics; gameplay rendering, Intel visuals, the #5 crash sequence and
long-session performance need separate measured runs.
