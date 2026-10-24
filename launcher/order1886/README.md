# Launcher visual assets

The Go launcher (`launcher-go/`) copies these assets into its frontend and package. The background and official logos use images supplied by the user on 17 October 2026; the application draws labels, buttons and status indicators separately. Source PNG/JPEG bytes remain unchanged.

| Asset | Source and use |
| --- | --- |
| `logo-horizontal.png` | Official horizontal game wordmark supplied by the user; Home banner and README header. Transparent margins are omitted only when rendered in the launcher. |
| `logo-stacked.png` | Official stacked game logo supplied by the user; sidebar branding. |
| `app-icon.png` | Official square game emblem supplied by the user; source for launcher/window icons, packaged executable ICO and runtime-window BMP. |
| `BRANDING.txt` | Supplied logo filenames, SHA256 hashes and rights attribution. |
| `launcher-art.jpg` | User-supplied `2354440.jpg`, copied byte-for-byte. Home background in the launcher and portable builds. SHA256 and provenance are in `launcher-art.txt`. |
| `native/order1886.ico` | Multi-size Windows format conversion of `app-icon.png`, also generated as `order1886.ico` when packaging. |

These assets contain no game executables or content archives; the supplied wallpaper and logos retain their respective owners' rights.
