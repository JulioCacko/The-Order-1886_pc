# Preview 9 release verification — 21 October 2026

Tag **v0.1.0-go-preview.9**. Both packages are built from
`b19c604` (branch `release/go-preview-9`, on top of `main` at `6589faa` with #94 and
#95 merged). The tag also carries the release documentation and screenshots added afterwards.

## Artifacts

| Package | Bytes | SHA-256 | Built |
| --- | ---: | --- | --- |
| `order1886-go-windows.zip` | 107,332,965 | `61df772b5177fe52b065fd1cbc870b0d2a501cdb2dc7998c61a9edb79410ce67` | Locally on Windows 11, MSYS2 clang64, from an LF checkout (`core.autocrlf=false`) |
| `order1886-linux-x86_64.tar.gz` | 120,550,075 | `887dea5d34ce94435da423fbb1cfae53c4526594da7c201a918867e5e75b3776` | Workflow run [39697989532](https://github.com/JulioCacko/The-Order-1886_pc/actions/runs/39697989532), Ubuntu 24.04, clang |

| Runtime | SHA-256 |
| --- | --- |
| Windows `order1886-runtime.exe` | `881069e5e37a2c4adee22aaeb4c2d38ae42d7900c7a46508f40cfe92cef40a67` |
| Linux `order1886-runtime` | `b722c6dac817d45b…` (in `package-manifest.json` and `runtime-build.json`) |

Both package manifests report `source_revision` `b19c604` and `source_dirty: false`. The Windows
package holds 218 files and the Linux package 215.

### Why the Windows package is built from an LF checkout

The Wails build rewrites `launcher-go/go.mod` with LF line endings. In a checkout with
`core.autocrlf=true`, git then reports the file as modified, the manifest records
`source_dirty: true`, and the in-launcher updater rejects the package
(`launcher-go/internal/updates/archive.go`). An LF checkout keeps the manifest clean.

### Updater acceptance

`updates.StageArchive`, the function the launcher's updater uses, accepted
`order1886-go-windows.zip` with its size, SHA-256, source revision and runtime hash: 218
files at `b19c604`. `release-verification.json` again carries `archive`, `archive_sha256`,
`archive_bytes` and `runtime_build`. Preview 8's receipt lacked the archive fields, so the
launcher could not update to preview 8.

## Checks

| Check | Result |
| --- | --- |
| Native `build.sh --test` at `6589faa` | 56 checks pass |
| Python `unittest discover -s tests` at `6589faa` | 531 run, 19 skipped, no failures |
| `tests/test_order1886_linux_package.py` | 2 pass |
| Windows portable smoke (`packaging/windows/order1886-go-smoke.py`) | Pass |
| Linux portable smoke, including the new bundled-library check | Pass in run 39697989532 |
| Linux package on a clean Ubuntu 26.04.1 (WSL, glibc 2.43) | `ldd` finds every library of the runtime and the launcher |

## Gameplay proof, Windows

RTX 3070, Windows 11, the packaged runtime from this release, 60 FPS mode, VSync on, a copied
save (`tools/order1886_step1_evidence.py --runtime <package>/bin/order1886-runtime.exe
--continue-save 30 --savedata <copy>`). Screenshots are the game window's client area,
captured only while the window is in front.

| Scene | FPS | p50 ms | p99 ms |
| --- | ---: | ---: | ---: |
| Night courtyard, after 95 s | 53.19 | 18.96 | 22.99 |
| Same, with every overlay item shown | 52.81 | 19.16 | 22.60 |
| Hotel lobby fight, after 95 s | 37.98 | 18.71 | 54.09 |

The overlay in `windows-proof-overlay.jpg` reads 50.6 FPS, GPU 36 %, process CPU 54 %,
VRAM 2.1 / 7.1 GB at that moment.

## Linux proof

Ubuntu 26.04.1 under WSL 2 on the same machine. WSL exposes no GPU-backed Vulkan driver
there, only Mesa's software `lavapipe` (llvmpipe, LLVM 21.1.8). The package was extracted to
`~/o1886-final` and its own runtime was started through the graphics probe:

- The runtime starts and creates its Vulkan device on llvmpipe. It renders the game's intro
  logos and its "PRESS ✕" start screen. With `SDL_VIDEO_DRIVER=x11` and `xdotool` sending Space
  (Cross), it reaches the title menu (`linux-runtime.jpg`, captured from its X11 window with
  `import -window`). That run had no saves, so the menu offers New Game. It runs at 1–2 FPS,
  and the menu's 3D background stays dark on lavapipe.
- The launcher opens under WebKitGTK and shows the light theme (`linux-launcher.jpg`,
  captured from its X11 window inside WSL).

This establishes that the Linux package starts and renders on a system without the build
machine's libraries. It does not establish gameplay or performance on Linux: that needs a
Linux GPU driver.

## Fixed during the release

- Packaging smoke tests on both platforms expected the worker to reject 90 FPS, which became a
  valid choice in #91. They now check that an unoffered 120 FPS is rejected.
- The Linux package now bundles its non-system shared libraries (FFmpeg 6, SDL3, fmt 9,
  Zydis and their dependencies, 108 libraries) into `bin/gpu` with `$ORIGIN` RUNPATHs.
  Before, the runtime stopped on any machine without the CI runner's exact libraries
  (`libavcodec.so.60: cannot open shared object file` on Ubuntu 26.04).
- The launcher's root rule hard-coded the dark theme's text colour, so text without its own
  colour was near-white on the light theme.
- The frame-rate help text still described the 5 FPS scene from before #93.
- Evidence screenshots are cropped to the game window and taken only while it is in front.

## Not covered

- Gameplay on Linux with a GPU driver.
- Long-session stability, full progression, the Chapter 6/9 QTE timing above 30 FPS and 4K/60.
- The Linux launcher's other pages: clicks did not reach the WSLg window.
