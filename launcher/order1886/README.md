# Launcher visual assets

The launcher retains its Windows Tkinter stack and native widget semantics. Generated imagery supplies atmosphere and material; the application draws the wordmark, labels, buttons and status indicators separately.

| Asset | Source and use |
| --- | --- |
| `launcher-art.png` | Generated cinematic background for the user-approved launch-bar composition. First choice in the artwork loader. Its adjacent `launcher-art.txt` records provenance. |
| `play-brass.png` | Generated brass material, mirror-tiled behind the semantic native Play button. The triangle and text are added by the application. |
| `background.png` | Unchanged `sce_sys/pic0.png` from the user's locally extracted CUSA00076 copy; bundled final artwork fallback. |
| `logo.png` | Unchanged user-supplied logo, retained as a source asset; the current home wordmark uses Georgia lettering. |
| `order1886.ico` | Format conversion of `sce_sys/icon0.png` with standard Windows icon sizes. |

The artwork loader tries the generated background, the selected game's `sce_sys/pic0.png`, then the bundled `background.png`. It reads player artwork without modifying the game folder. These assets are for this local launcher and contain no game executables or content archives.

Generated PNGs carry their exact prompt in the `impeccable:prompt` metadata field. When inspecting them through Pillow, call `image.load()` before reading `image.info`; lazy PNG loading can omit the text field from an earlier inspection. The Impeccable `embed-prompt --read` helper can also recover it.

The selected concept is `.impeccable/mocks/concept-a.png`; actual native captures are under `.impeccable/review/`, with repository-facing copies under `docs/images/`. Screenshots demonstrate launcher presentation, not gameplay compatibility or measured frame rate. The hero webgate remains open and native measurement limits are recorded separately from the implemented UI.
