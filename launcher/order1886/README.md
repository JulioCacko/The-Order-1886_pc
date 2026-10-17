# Launcher visual assets

The launcher retains its Windows Tkinter stack and native widget semantics. The background and official logos use images supplied by the user on 17 October 2026; the application draws labels, buttons and status indicators separately. Source PNG/JPEG bytes remain unchanged.

| Asset | Source and use |
| --- | --- |
| `logo-horizontal.png` | Official horizontal game wordmark supplied by the user; Home banner and README header. Transparent margins are omitted only when rendered in the launcher. |
| `logo-stacked.png` | Official stacked game logo supplied by the user; sidebar branding. |
| `app-icon.png` | Official square game emblem supplied by the user; source for launcher/window icons, packaged executable ICO and runtime-window BMP. |
| `BRANDING.txt` | Supplied logo filenames, SHA256 hashes and rights attribution. |
| `launcher-art.jpg` | User-supplied `2354440.jpg`, copied byte-for-byte. First choice in the artwork loader, including portable builds. SHA256 and provenance are in `launcher-art.txt`. |
| `launcher-art.png` | Previous generated cinematic background, retained as a fallback. Its adjacent `launcher-art.txt` records provenance. |
| `play-brass.png` | Generated brass material, mirror-tiled behind the semantic native Play button. The triangle and text are added by the application. |
| `background.png` | Unchanged `sce_sys/pic0.png` from the user's locally extracted CUSA00076 copy; bundled final artwork fallback. |
| `logo.png` | Legacy local source asset; superseded by the supplied horizontal and stacked logos. |
| `native/order1886.ico` | Multi-size Windows format conversion of `app-icon.png`, also generated as `order1886.ico` when packaging. |

The artwork loader tries the supplied JPEG, the previous generated background, the selected game's `sce_sys/pic0.png`, then the bundled `background.png`. It reads player artwork without modifying the game folder. These assets contain no game executables or content archives; the supplied wallpaper retains its respective owners' rights.

Generated PNGs carry their exact prompt in the `impeccable:prompt` metadata field. When inspecting them through Pillow, call `image.load()` before reading `image.info`; lazy PNG loading can omit the text field from an earlier inspection. The Impeccable `embed-prompt --read` helper can also recover it.

The selected concept is `.impeccable/mocks/concept-a.png`; actual native captures are under `.impeccable/review/`, with repository-facing copies under `docs/images/`. Screenshots demonstrate launcher presentation, not gameplay compatibility or measured frame rate. The hero webgate remains open and native measurement limits are recorded separately from the implemented UI.
