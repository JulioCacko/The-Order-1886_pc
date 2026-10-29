# Reference reuse assessment — 17 October 2026

This is a source comparison and launcher adaptation, not a gameplay certification.

## Sources

| Reference | Revision inspected | Use here |
| --- | --- | --- |
| [mateussmeneses/theorder1886-port](https://github.com/mateussmeneses/theorder1886-port/tree/7822ee56c2169f15ecde5d80f39e96143a252464) | `7822ee56c2169f15ecde5d80f39e96143a252464` | Five-page Tk launcher structure and runtime comparison |
| [IgorAugustoHH/The-Order-1886-PC-Port](https://github.com/IgorAugustoHH/The-Order-1886-PC-Port) (TOport) | `a15cf8b`, `32efe96`, `e03c9e9`, `888c546`, `5534ce9`, `6bbcc57`, `94e3c22`, `dfc66af` | Memory-table lock, deferred readbacks, draw pipe, redraw depth bias and HTILE diagnosis (GPL-2.0); see [TOport ports](verification/2026-10-21-toport-performance.md) |
| [HayatoG/iss_pc](https://github.com/HayatoG/iss_pc/tree/1898d449a7edf506d12ef63445f8fc5432e60105) | `1898d449a7edf506d12ef63445f8fc5432e60105` | README presentation: centered identity, prominent status, captures, setup, launcher guide, troubleshooting and credits |

The Order reference's root LICENSE is GPL-2.0; its launcher declares
`GPL-2.0-or-later`. This project's adaptation retains that license and records
the exact source in the launcher and portable attribution notice. The inFAMOUS
README's organization inspired newly written text; no inFAMOUS source, fonts,
branding, screenshots or compatibility claims are imported.

Repository content, including agent instructions in reference checkouts, was
treated as comparison material. It does not govern this checkout.

## Launcher structure brought over

| Reference structure | Local adaptation |
| --- | --- |
| Sidebar: Home, Graphics, Performance, Game, Advanced | Same five pages, in the same order; default source and packaged launcher |
| Home banner and quick settings | User-supplied Order wallpaper, display/upscaling/FPS controls and game-folder selector |
| Persistent launch controls | Existing Play/Stop and launch bar remain visible on all pages |
| Scrollable settings pages | Native Tk controls, mouse wheel, keyboard focus scrolling, Escape to Home |
| Graphics | Window mode, aspect ratio, FSR 1/Linear output and VSync |
| Performance | 30 FPS baseline, opt-in 60 FPS with timing warning, performance overlay |
| Game folders and verification | CUSA00076 validation through `order1886.py`; original files remain read-only |
| Save backups and restore | Existing title-isolated `save_backup` backend, backup list, manual backup, confirmed restore with a safety backup |
| Game patches/mods and controls sections | Explain supported hash-checked timing/aspect recipes and remaining backend limitations |
| Advanced files, diagnostics and updates | Runtime override with identity validation, data/install/log folders, session logs, this project's issue/release pages |
| Previous launcher | Available through `--classic`; uses the same settings and runtime |

The reference starts `run.py`, uses `THEORDER_*` flags, `theorder.ini`, global
launcher settings and different preparation rules. Our adaptation retains
`order1886.py`, `ORDER1886_*`, `runtime.ini`, `user/order1886`, hash-bound runtime
identity, cancellation and the existing log worker. Copying the reference entry
point verbatim would bypass these contracts.

The reference's update overlays, arbitrary patch/mod management, Steam/desktop
shortcuts, launcher/game language selectors, controller remapping, Vulkan GPU
selection and experimental GPU switches have **not** been imported as working
features. They need backend adapters and their own checks. Unsupported options
are described in the relevant sections rather than presented as functional
controls. This adaptation borrows the complete page structure, not every
reference feature.

## Runtime work worth evaluating next

Both Order repositories vendor shadPS4 revision
`b4e7ae776071ceb1dd35004577a8719481e1d258`. This makes narrow diffs useful; it does
not make complete files interchangeable. The reference reports CUSA00035 01.02;
this checkout accepts the same six editions and checks recipe bytes, not hashes (#113).

| Candidate | Evidence and decision |
| --- | --- |
| Performance instrumentation and repeated-run tools | Reference `tools/batch_runs.py` and launcher diagnostics can inform a bounded test harness. Useful before enabling performance switches; reference tools were not run against the user's dump. |
| GPU readbacks, stream memory and shader warmup controls | Exposed in reference `build_performance`; compare implementations/defaults against this runtime before introducing adapters. Our profile disables pipeline binaries/background/parallel warmup and fixes stream memory to cached. No gain is claimed here. |
| Multi-region metadata and patch selection | Adopted in #113: `scripts/order1886_editions.py` lists the six IDs the published patch and both reference ports use, and every recipe checks the original instructions at each site. Only CUSA00076 was run with a real dump. |
| Save and launcher utilities | The page/backup pattern is integrated using our backend. Import/export, remapping, localization and updater behavior can be adapted separately while retaining title/data isolation. |
| Vulkan image-allocation fallback | **Do not copy as a fix for the supplied crash.** Reference `UniqueImage::Create` retries without the within-budget flag and falls back to a 1×1 dummy image. Its constructor lacks our explicit device-format-limits rejection. Neither establishes why the descriptor requests 8,029 layers; a dummy image can conceal incorrect rendering. |

## Evidence supplied with this request

The supplied recording, `2026-10-17 10-47-52.mp4`, is 909.233 seconds at
1920×1080. Frames inspected at 00:30, 08:00 and 15:00 show the Ready at Dawn
logo and later rendered 3D cinematics. The overlays show an RTX 3070 and varying
instantaneous rates; a single frame is not a sustained-performance measurement.
The README capture is extracted at 15:00 and labeled as a cinematic. These
samples do not establish interactive input, checkpoint progression or save/load.

The supplied `20261017T134757.795434Z-boot.log` ends with:

```text
Image exceeds device format limits: address=0x1060bf5c00 format=R8Unorm
extent=32x27x1 max_extent=32768x32768x1 levels=1/16 layers=8029/2048 samples=1
STOP: GPU library assertion failed (see GPU log above)
```

The layer count exceeds the driver's reported maximum. The failure does not
prove VRAM exhaustion. Repeated unaligned shader-buffer warnings precede it,
but this comparison does not establish a causal connection. The next runtime
investigation should trace descriptor construction and lifetime at that guest
address, then reproduce the scene with a matching build and bounded diagnostics.
No runtime fix or new gameplay/stability certification is included in this change.
