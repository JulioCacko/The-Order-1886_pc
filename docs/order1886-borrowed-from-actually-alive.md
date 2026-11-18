# Borrowed from "The Order: 1886 — Actually Alive"

Source: [DivinusX/a-port-of-the-order-1886-thats-actually-alive](https://github.com/DivinusX/a-port-of-the-order-1886-thats-actually-alive),
v0.2.33, commit `31b179c` (GPL-2.0-or-later). That project builds on this repository at
`37482884` (`origin/main`), so most of it came back as small, mergeable pieces. This note records
what was taken, how, and what could not be taken. Version numbers of this project are unchanged.

## What was borrowed

| Area | Taken | Where | How |
|---|---|---|---|
| Game language | 21-language selector, SKU-0 language filter recipe, no pt-BR fallback | `launcher/order1886_options.py`, `launcher/order1886_common.py`, `scripts/order1886_patches.py`, `scripts/order1886_editions.py` | Merged into the existing files (his overlays wrap upstream modules; here they are plain edits) |
| In-game menu | F1 menu (R3+L2 on a pad), `game_menu` setting on by default | `gpu/ps4gpu.h`, `vk_presenter.cpp`, `gpu/shim/ps4_overlay.cpp`, `src/probe.c`, launcher files | Patch applied; setting key `game_menu` replaces `in_game_menu` |
| Shader-cache seeds | `scripts/order1886_cache.py` seed import and launch hook | `scripts/order1886_cache.py`, `launcher/order1886_common.py` | Copied and hooked |
| Game preparation | display, frame-rate, mods, glyph and UI-extract updates, prompt script, merge-update helper | `scripts/` | Copied (his version wins) |
| Button prompts | Xbox set retired; keyboard prompts follow live bindings | `scripts/order1886_prompts.py`, `scripts/button_prompts/`, `order1886.py` | A stored `xbox` choice migrates to the original layout |
| Sun shadows | draw-time HTILE expand, staging readback sync | `gpu/shadps4/video_core/...` | Two patches, applied |
| RDNA2 depth | multisampled depth lines on the Windows AMD proprietary driver | `ps4_msaa*.h`, `vk_instance.cpp` | Patch applied, one hunk hand-ported |
| FSR 4 | provider ABI 2, `order_resolve_prep`, Linux provider loop in `build.sh` | `gpu/` | Partly ported (see below) |
| Constant ring | capacity 32 MiB to 256 MiB | `vk_constant_ring.h` | Capacity only |
| Launcher | background music, prebuilt UI, logos | `launcher-go/music.go`, `ui_wails.go`, `launcher-go/frontend-prebuilt/` | Overlay files copied; build uses `wails build -s` |
| Packaging | in-tree Linux engine build, bundle fix/check, package assembler, runtime wrapper, Windows manifest gate | `packaging/` | Added beside the existing packagers (not run on Linux here) |
| Tests | game language, mixed case, prepatched source, shader-cache seed | `tests/` | Added; main's tests updated to the borrowed behaviour |

## Why the engine patches were hand-merged

His five patches (`docs/verification/*.patch` in his repo) are diffs against an unpublished working tree
(`source_dirty: true` in his package manifest), so none of them applied to `37482884`.
Each was applied with `git apply --reject` and the rejected hunks were merged by hand.

## Not borrowed

These exist in his releases but only as prose in his `CHANGES.md` and an unpublished engine
branch (`aot-shader-cache`; commits `6db2288886` and `045ebeac52` are not in any public repository).
They need his engine tree:

- performance overlay (FPS, frame-time graph, GPU/CPU load and temperature, RAM/VRAM)
- graphics presets in the in-game menu and the Unlocked / 90+ FPS change
- ultrawide 21:9 fill screen
- GTX 10 (Pascal) geometry-shader and interpolation fixes
- the retired-frontier allocation in the constant ring (only its size was taken)
- the engine side of shader-cache seed replay
- the FSR 4 provider source (`gpu/upscalers/fsr4/`), which his repository also lacks
- `ffx_1_1_4_portability.hpp` (lives inside the FSR-Vulkan submodule; needs a submodule bump)

## Deviations from his versions

- The Xbox button-prompt set is removed (his choice); main's tests for it were rewritten.
- Mixed-case tests that need a case-sensitive filesystem skip on NTFS.
- New launcher strings have translated labels in all launcher languages; descriptions stay English,
  as the localization policy requires. The translations are machine-assisted and not native-reviewed.
- His launcher art and logos are only included where the prebuilt UI references them; rights stay with
  their owners (see `packaging/windows/ATTRIBUTION-Order1886.txt`).

## Verification status

Checked on Windows 11 only. Nothing here establishes rendering, gameplay or performance; the game itself was not run.

- Engine: `build.sh` builds the runtime, the FSR 3 provider and all 62 native test targets under `-Werror`
  (MSYS2 CLANG64, clang 23.1.5). 60 native test runs pass, including `htile-expand-test`,
  `order-render-baseline-test` and the perf-overlay test. `services-test` and `isa-emulate-test`
  were blocked by Windows Smart App Control (exit 126) and never ran.
- Clang 23 needed `-include` options for the FidelityFX FSR 3 provider (it no longer gets `stdlib.h`,
  `cmath`, `new` and `wchar.h` transitively); that and the Windows `--test` list entry for
  `htile-expand` are separate fix commits.
- Python: `python -m unittest discover -s tests -p "test_order1886*.py"` has no assertion failures.
  Remaining errors are native test executables blocked by Smart App Control (`WinError 4551`) or a
  missing `cryptography` module in the system Python.
- Launcher: `go test ./...` passes except `internal/pkgpath` (its test executable is blocked by the same
  policy); the Wails build (Go 1.27.4, Wails v2.17.0) produces `The Order 1886.exe`, which stays running.
- Not run: Linux (build-engine.sh, bundle/package scripts, FSR 4 provider), the game itself.
