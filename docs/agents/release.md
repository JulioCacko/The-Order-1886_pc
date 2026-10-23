# Releasing the Go launcher

A release publishes two packages from one commit of `main`: the Windows zip (which the launcher's
own updater installs) and the Linux tarball. Both must come from the same source revision, and
the release must carry a receipt the updater can verify. Preview 9 (`docs/verification/2026-10-21-preview9-release.md`)
is the worked example; every step below exists because skipping it once broke a release.

## Tag and channel

- Stable: `vX.Y.Z`. Preview: `vX.Y.Z-go-preview.N`, published as a GitHub pre-release. The updater
  (`launcher-go/internal/updates/release.go`) ignores any other tag form, and its stable channel
  skips preview tags.
- Set `productVersion` in `launcher-go/wails.json` to `X.Y.Z` in the release branch.

## 1. Release branch

1. Branch `release/<tag>` from the current `origin/main`. Only release documentation, version and
   packaging fixes go on it; land it through a pull request like any other change.
2. `bash build.sh --test` and `python -m unittest discover -s tests` must pass on the branch.

## 2. Windows package

1. Build from an LF clone, not a worktree of the CRLF main checkout:
   `git clone -c core.autocrlf=false <repo> <dir>` and check out the release commit. In a CRLF
   checkout the Wails build rewrites `launcher-go/go.mod`, git reports it modified, the manifest
   says `source_dirty: true`, and the updater refuses the package.
2. In the clone: `bash build.sh`, then from Git Bash (not the MSYS2 shell, whose git sees the tree
   as dirty) `powershell -File packaging/windows/order1886-go-build.ps1 -Runtime out/order1886-runtime.exe`.
3. Run `packaging/windows/order1886-go-smoke.py` on the package.
4. Check `bin/runtime-build.json` in the zip: `source_dirty` is `false` and `source_revision` is the
   release commit.

## 3. Linux package

1. Run the `order1886-go-linux-package` workflow on the release branch
   (`gh workflow run order1886-go-linux-package.yml -R JulioCacko/The-Order-1886_pc --ref <branch>`),
   download its artifact, and note the run id.
2. Its smoke test checks that every bundled library loads from `bin/gpu` without
   `LD_LIBRARY_PATH`. Also extract it on a clean distribution (WSL Ubuntu) and run `ldd` on the
   runtime and the launcher.

## 4. Receipt

```sh
python packaging/order1886_release_receipt.py --tag <tag> \
  --windows <dir>/order1886-go-windows.zip --linux <dir>/order1886-linux-x86_64.tar.gz \
  --workflow-run <run id> --check native_tests="56 pass" --check ... --out <dir>/release-verification.json
```

The script refuses a dirty build, mismatched revisions and a tag the updater would not accept.
Write a `<asset>.sha256` file next to each package.

## 5. Proof

- Play the packaged Windows runtime, not a development build: `tools/order1886_step1_evidence.py
  --runtime <package>/bin/order1886-runtime.exe` with a copied save. Record FPS and p50/p99 frame
  times, and take window shots (game client area only, never the desktop).
- Linux under WSL has only software Vulkan: show that it starts and reaches the title menu, and say
  that gameplay on Linux was not run.
- Write `docs/verification/<date>-<tag>-release.md`: artifacts with sizes and SHA-256, checks,
  proof, fixes made during the release, and what was not covered.

## 6. Publish

1. `gh release create <tag> --target <release commit> --title ... --notes-file ...` with
   `order1886-go-windows.zip`, `order1886-linux-x86_64.tar.gz`, both `.sha256` files,
   `release-verification.json`, `QUICKSTART.txt` and `README-Order1886.txt`. Add `--prerelease`
   only for preview tags.
2. Confirm the updater accepts it:
   `go test -tags live ./internal/updates -run TestPublishedPreviewStages -count=1 -v` in
   `launcher-go` (it stages the newest published package exactly as the launcher does).
3. Update the README's download section and screenshots in the release pull request.
