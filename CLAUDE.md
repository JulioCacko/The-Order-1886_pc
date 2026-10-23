## Agent skills

### Issue tracker

GitHub Issues on `JulioCacko/The-Order-1886_pc` (`origin`); always pass `-R JulioCacko/The-Order-1886_pc` to `gh`. See `docs/agents/issue-tracker.md`.

### Triage labels

Canonical roles mapped to this repo's labels (`needs-info` -> `question`, `ready-for-agent` -> `ready-to-implement`, others 1:1). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` plus `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## main is protected

Nothing is committed to `main` directly. Land changes through a branch and a pull request; a GitHub
ruleset enforces it on the server, and `scripts/git-hooks/pre-push` refuses it in the checkout once
you enable it:

```sh
git config core.hooksPath scripts/git-hooks
```

That rule is not ceremony: `main` twice took a direct commit here by accident, and each time it was
briefly ahead of anything that had been reviewed.
## Working rules

- One change per branch and pull request against `main`. Commit or push only when the user asks;
  a PR watched by Auto-fix is the standing exception for fixes on that PR's branch.
- Never enable auto-merge; the repository does not allow it. The owner merges.
- Never write to the player's own state under `user/order1886`. Copy what you need (for example
  `savedata`) into a run's own state directory.
- Never publish a screenshot that shows the desktop. Evidence shots are the game window's client
  area, taken only while it is in front (`tools/order1886_step1_evidence.py` enforces this).
- Ask before deleting anything you did not create in the current task.
- Every graphics claim needs evidence from a real run: a screenshot pair (setting on and off, same
  scene) or a frame-time capture, recorded in `docs/verification/<date>-<topic>.md` and linked
  from the PR. "Builds and tests pass" is not evidence that a rendering bug is fixed.

## Build and test (Windows)

- `bash build.sh --test` from the worktree root (it sources the MSYS2 clang64 environment) builds
  `out/order1886-runtime.exe` and runs the native checks; all must pass.
- Python tests: `python -m unittest discover -s tests`. Run them with the Windows Python, not the
  MSYS2 one (`msys2-env.sh` puts a Python without numpy first on `PATH`).
- A new worktree has no submodules. Initialise them from an existing checkout instead of the
  network: point each `submodule.<name>.url` at that checkout's copy, then
  `git -c protocol.file.allow=always submodule update --init`.
- If the build fails with `cannot create regular file 'out/order1886-runtime.exe': Device or
  resource busy`, a stuck runtime still holds the image. Rename it aside
  (`mv out/order1886-runtime.exe out/order1886-runtime.stuck-<time>.exe`) and build again.

## Running the game for evidence

- Use `tools/order1886_graphics_probe.py` (one run) or `tools/order1886_step1_evidence.py`
  (named variants, timed screenshots, frame stats). Both take `--env KEY=VALUE`; the launcher
  environment strips every inherited `ORDER1886_*` variable, so a diagnostic switch set in your
  shell never reaches the runtime.
- A runtime outside this worktree's `out/` gets neither the MSYS2 DLL path nor a verified
  identity: copy it, with its `runtime-build.json`, under `out/`. An older runtime may also crash
  on an image prepared by newer tools; run it with its own tree's tools and a fresh state dir.
- Reproducible scenes: `tools/order1886_scene_driver.py` drives the menus. Continue from a
  playthrough save lands on a different checkpoint over time; chapter select does not. Chapter II
  "Evidence" opens with Council close-ups (faces, skin, the lighting pass).
- Each run starts with a cold shader cache, and the first minutes of a new scene compile shaders
  (a few FPS, sometimes seconds frozen). Do not read that as a hang or a regression, and do not
  compare frame rates across runs while another session's runtime is running
  (`Get-Process order1886-runtime`).
- Disk: `out/` directories are several GB. Check free space on `D:` before a series of runs.

## Debugging rendering

Work from evidence, not guesses: capture the broken frame, find the first pass whose output is
wrong, then the draw, then the state or data that differs.

- RenderDoc: load it as a Vulkan layer through the run's environment
  (`VK_ADD_LAYER_PATH=C:\Program Files\RenderDoc`, `VK_INSTANCE_LAYERS=VK_LAYER_RENDERDOC_Capture`,
  `ENABLE_VULKAN_RENDERDOC_CAPTURE=1`) and press F12 (`key f12` in the scene driver). Captures go
  to `%LOCALAPPDATA%\Temp\RenderDoc`, about 1.7 GB each. Take a window shot next to every capture:
  a capture is only useful if the live frame showed the bug.
- Pixel history and per-sample fragment depth explain "never shaded" pixels; post-VS data shows
  whether two draws agree. The `renderdoc` Python module (for scripts beyond the MCP tools) lives
  in `C:\Users\julio\MCP\renderdoc-module`.
- Built-in one-frame capture: `ORDER1886_CAPTURE_TRIGGER=<file>`, `ORDER1886_CAPTURE_DIR`,
  `ORDER1886_DIAG_DIR`, `ORDER1886_DIAG_IMAGES=1` and `ORDER1886_DRAW_PIPE=0`; touching the file
  captures the next frame (pass census plus every pass target as raw images). The census lists at
  most eight shaders per pass.
- `ORDER1886_TOGGLE_FILE=<file>` switches runtime optimisations live (bits in
  `gpu/shim/ps4_toggles.h`). Flip one bit at a time: switching all of them off at once broke
  geometry.
- Known causes worth checking first: depth-equality redraws (see
  `docs/verification/2026-10-22-redraw-depth-bias.md`), CPU readbacks of GPU-written buffers
  (`ORDER1886_READBACKS`, `ORDER1886_READBACK_LOG=1`), and SRT walker failures in `native.log`
  (`SRT offset failure`).

## Shell pitfalls

- Heredocs in the Bash tool collapse `\` to `\`. Write files containing backslashes (C++ string
  escapes, Windows paths) with the editor tools, not `cat <<EOF` or `python - <<EOF`.
- `rm -rf $VAR` is refused by a safety check; use a literal path or a fresh directory.

## Releases

Follow `docs/agents/release.md`. Build the Windows package from an LF checkout
(`core.autocrlf=false`); in a CRLF checkout the manifest says `source_dirty: true` and the
launcher's updater refuses the package.
