# Asynchronous pipeline compilation on by default (24 October 2026)

The player reported stutter in gameplay and asked for shaders to compile without stopping the
game. The runtime already had an asynchronous compiler (`vk_async_compiler.h`), but the launcher
and the runtime shipped it off ("Asynchronous shaders (unqualified)"), so every new shader and
pipeline was built on the GPU command thread. This change makes the asynchronous path cheaper for
the GPU thread and turns it on by default.

## Where the GPU thread blocked

`ORDER1886_FRAME_STATS=1` prints every frame over 40 ms with the compile work inside it.

- **Async off (old default):** shader translation, SPIR-V emission, `vkCreateShaderModule` and
  `vkCreateGraphicsPipelines` all run on the GPU thread. The first gameplay frame after loading
  the save compiles about 820 shaders and pipelines in one frame (`818 compiles 5590.3 ms`), and
  every new effect later in gameplay costs one long frame (`14 compiles 163.8 ms`,
  `12 compiles 155.3 ms`).
- **Async on, before this change:** pipelines and SPIR-V emission already ran on workers, and a
  draw whose pipeline was not ready was skipped. The GPU thread still waited for the **whole**
  shader translation (`TranslateProgram`) of every new shader, one at a time, because translation
  reads guest memory that the draw may change once the GPU thread moves on. That wait
  (`GPU capture wait`) was 2.75 s of the first gameplay frame.

## What changed

- `TranslateProgram` takes a callback that runs as soon as translation has read everything it
  needs from guest memory: the fetch shader and the SRT walk in `FlattenExtendedUserdataPass`.
  Every pass after it reads only the `Info`'s own copies (the flattened user data), and the
  fetch shader is captured into the existing `FetchShaderSnapshot` at the same point. The GPU
  thread waits only for that prefix; the rest of the translation, the specialization, the SPIR-V
  emission and the module run on the worker, which drops to low priority once nothing waits.
- The GPU thread never waits behind another shader's translation: a new shader is queued only
  when a translation worker is idle (`AsyncCompiler::HasIdleWorker`), otherwise its draw is
  skipped and the shader is queued on a later draw. The translation pool now has as many
  workers as the pipeline pool (half the available threads, at most 6).
- `async_shaders` defaults to on in the runtime (`Ps4Settings`), the launcher
  (`GRAPHICS_DEFAULTS`) and its option, which is no longer labelled unqualified. It still turns
  off from the launcher, `runtime.ini` or `ORDER1886_ASYNC_SHADERS=0`, from the next launch.
- `tools/order1886_step1_evidence.py` gains a `sync-shaders` variant now that the default is on.

## Which draws are skipped

With async on, a **graphics draw** whose shader or pipeline is still compiling is not recorded
for that frame; the draw is retried every time the game issues it. Nothing else is skipped:

- **Compute dispatches** always compile in place. A dispatch can write buffers that later frames
  or the CPU read back, and no fallback exists for a missing one (see the donor note in
  `docs/order1886-donor-reuse.md`).
- **Tessellated draws** compile in place: their stages read constant buffers at selection time.
- `ORDER1886_SHADER_COLLECT` (shader debugging) keeps everything synchronous.

The risk that remains is a graphics draw the game issues only once whose output later frames
reuse (a one-time bake into a texture). None was seen on the measured route: the gameplay frames
captured 40 and 90 s after loading show the same scene and lighting with async on and off (mean
absolute output difference 1.1 to 1.6 out of 255, from the idle animation). A player who sees a
permanently missing object can turn the option off.

## Persistent cache

Both paths store new shaders, their metadata and the pipeline keys in the GPU cache
(`RegisterShaderBinary`, `RegisterShaderMeta`, `RegisterPipelineData` in
`vk_pipeline_serialization.cpp`; pipeline binaries through `VK_KHR_pipeline_binary` where the
driver has it). The next launch builds them all before the first frame (warm-up: 492 pipelines
in 9.4 to 12 s), and the same scene then compiles nothing on the GPU thread. Worker
`VkPipelineCache`s are merged into the main one at shutdown.

## Measurements

`tools/order1886_step1_evidence.py` with a copy of the player's `user/order1886/savedata`
(Chapter XI), `--continue-save 40 --delays 90 140 --timeout 160 --env ORDER1886_FRAME_STATS=1`,
60 FPS profile, VSync on, a new cold GPU cache per run, RTX 3070. Frame times come from the guest
flip trace (loading flips excluded). The first gameplay frame after loading is listed apart from
the rest of gameplay.

| Build | Async | First gameplay frame | GPU-thread compile work in it | Gameplay frames > 100 ms after it | Latest frame > 100 ms |
| --- | --- | --- | --- | --- | --- |
| `main` 4c9c20f | off | 5681 ms | 818 compiles, 5590 ms | 3 (216, 192, 195 ms) | 14 s after load |
| `main` 4c9c20f | on | 2642 ms | translation wait 2748 ms | 4 (156, 136, 164, 111 ms) | 4.9 s after load |
| this branch | off | 4001 ms | 821 compiles, 3948 ms | 3 (184, 126, 136 ms) | 4.6 s after load |
| this branch | on | **1766 ms** | translation wait **1825 ms** | 3 (160, 107, 118 ms) | **0.7 s after load** |

Whole runs, cold cache: worst frame 5681 → 1766 ms; frames over 100 ms 7 → 5; over 250 ms 2 → 1;
median frame 20.2 → 19.3 ms. With async on, every frame over 100 ms falls within 0.7 s of the
first gameplay frame; after that the GPU thread compiled nothing (`0 shader/pipeline compiles`,
`0 pending draws` in every later 5 s window). With async off, new effects kept stopping the game
for 126 to 216 ms up to 14 s into gameplay.

Run folders (not tracked): `out/evidence/before` (`main` build) and `out/evidence/after1` (this
branch) in the worktree. A warm run seeded from the async cache (`out/evidence/warm`) warmed 492
pipelines before the first frame; its first gameplay frame took 120 ms and the same route had no
compile hitch after it. Its character
then walked into an area the seed run had not reached, which compiled new shaders as expected.

## Not verified

- One run per configuration. A repeat set was started and discarded: manual testing on the same
  machine closed its windows and changed its input.
- The remaining 1.8 s first frame on a cold cache: the loading screen stays up while about 800
  shaders are translated. Overlapping those translations would need every guest-visible signal
  (end-of-pipe, `WRITE_DATA`, `DMA_DATA`, compute queues) to wait for them first.
- Long-session stability with the new translation scheduling, beyond the runs above and the
  native checks (`bash build.sh --test`, 56 passed).
