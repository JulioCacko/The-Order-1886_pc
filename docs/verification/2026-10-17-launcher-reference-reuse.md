# Launcher reference reuse verification — 17 October 2026

## Scope

Five-page native Tk launcher adaptation, README presentation, live GitHub
description, the user's supplied wallpaper and official logos/emblem. No native runtime source was
changed and no real-game or GPU session was started for these checks.

References and runtime reuse decisions are recorded in
[the assessment](../order1886-reference-reuse.md). Initial graph generation was
`2026-10-17T14:13:42Z`; coverage reported changed metadata, so current source
was read directly. A later coverage call returned `Transport closed`; no
completeness claim depends on that call.

## Results

| Check | Result |
| --- | --- |
| `python -m unittest discover -s tests -p 'test_order1886*.py'` | 74 passed, rerun after official branding integration |
| Desktop and original launcher regressions after wallpaper integration | 5 + 11 passed |
| Default launcher `--smoke-test` | Passed with supplied wallpaper and official logos |
| Classic launcher `--classic --smoke-test` | Passed with supplied wallpaper and official logo |
| Native window capture | Inspected five-page Home and Game; refreshed Home capture with supplied wallpaper and official horizontal/stacked branding |
| README local file links | All resolved across English, Portuguese, Spanish and reuse assessment |
| `git diff --check` | Passed |
| Live GitHub description | Updated and read back from `JulioCacko/The-Order-1886_pc` |
| Portable package | Built using existing hash-verified native runtime |
| Relocated portable smoke | All 9 checks passed: manifest, preparation closure, artwork, runtime identity, native help/info, GUI, missing game with/without stdio |
| Packaged launcher source | Matches current `launcher/order1886_launcher.py` SHA256 in package manifest |
| Packaged wallpaper | Matches the user-supplied JPEG byte-for-byte |
| Packaged branding PNGs | All three match user-supplied originals byte-for-byte |
| Windows executable icon resources | All 7 ICO image payloads match the official-emblem ICO generated from `app-icon.png` |

The desktop tests cover navigation without writes, settings reaching backend
arguments, launch-bar synchronization, save/settings mutations blocked during a
session, rejecting state inside the game folder, confirmed restore with a real
safety backup, preserving original files, and saving page edits before Play.

The portable verifier's exact preparation closure was updated to include the
already-bundled `order1886_display.py`, and its artwork closure now includes the
new JPEG, all three branding PNGs and `BRANDING.txt`. This retains exact file-set checks.

## Output

- Package directory: `dist/order1886/20261017T151742Z-9f5f7f010bb6/The Order 1886/`
- Archive: `dist/order1886/20261017T151742Z-9f5f7f010bb6/order1886-windows.zip`
- Archive SHA256: `e1c128da02464f5bba8fda3cb372c1d7e4961ceff3335b3c5b56df92f91dd628`
- Runtime SHA256: `9f5f7f010bb68714c8b9c6340ff73e7282b7f551297f7446ae31a97332feec3d`
- Wallpaper SHA256: `5d459c02cb5e3dcfddd0168205d281c6b825441c14e9aa7086edc6f5a079fb46`
- Smoke evidence: `out/order1886-official-branding-evidence/Portable Smoke 1c3d557cca/smoke-report.json`
- Current screenshot: `docs/images/order1886-desktop.png`

The wallpaper's original bytes are retained in
`launcher/order1886/launcher-art.jpg`; scaling/cropping happens only when drawn.
The ZIP excludes player settings and saves. Keep the existing `user` folder when
updating an installation. The earlier packages built at `20261017T144032Z` and
`20261017T144629Z` predate the official-logo update; use the `20261017T151742Z` output above.

The user requested committing these changes and pushing them to `main`, including
the earlier 16:9 support commit required by this launcher. The package is a local
build; no GitHub Release was created and no GitHub Actions success is claimed.
The pre-existing untracked PS4 save-import verification document was left
untouched. The supplied Vulkan image-layer assertion remains unresolved.
