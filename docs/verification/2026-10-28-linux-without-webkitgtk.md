# Linux without WebKitGTK: the entry points start and play (#114)

Branch `fix/linux-webkit-free-entry`. Package from
[workflow run 40636406546](https://github.com/JulioCacko/The-Order-1886_pc/actions/runs/40636406546), whose
smoke test passed (it now checks that both entry points link no WebKitGTK and simulates a missing
WebKitGTK). Checked on 28 October 2026.

## Before

On SteamOS, which has no WebKitGTK 4.1, the dynamic linker refused to start both `The Order 1886`
and `Play The Order 1886`. Both were the same Wails binary, which links
`libwebkit2gtk-4.1.so.0` and `libjavascriptcoregtk-4.1.so.0`.

Running this fix in a container exposed a second, older fault. The frozen backend took
`bin/order1886-worker/` as the package folder on Linux, so it looked for
`bin/bin/order1886-runtime` and every play stopped with "Order runtime not found in this
installation". On Windows the worker sits one level higher, so the same code worked there.

## Arch Linux without WebKitGTK

SteamOS is based on Arch, so the test used the `archlinux:latest` container (glibc 2.44) with no
WebKitGTK. For the runtime it had software Vulkan (`vulkan-swrast`), Xvfb and `libbsd`.
`libbsd` is a system library the package expects to find; the reporter's SteamOS 3.9.5 has it. The
CUSA00076 dump was mounted read-only.

| Step | Result |
| --- | --- |
| `ldd` of the entry points | "not a dynamic executable": a static Go build with no GTK or WebKit |
| `ldd bin/order1886-launcher` | `libwebkit2gtk-4.1.so.0`, GTK 3 and the rest not found, as on SteamOS |
| `The Order 1886`, nothing saved | Exit 1. The message names `libwebkit2gtk-4.1.so.0` and gives the `--game-dir` command. The same text is in `user/order1886/logs/launcher-entry.log` |
| `Play The Order 1886 --game-dir /tmp` | Refused: not a game folder. Nothing saved |
| `Play The Order 1886 --game-dir /games/CUSA00076` | Folder saved to `settings.json`. Preparation, link, `Runtime started`. The runtime opens Vulkan on llvmpipe and runs until the test stops it at 240 s |
| `The Order 1886` again | Reports the missing WebKitGTK, then plays the saved folder: `Runtime started` |

## Ubuntu 26.04.1 with WebKitGTK (WSL)

`The Order 1886` starts `bin/order1886-launcher`, which starts its worker. Both were still running
20 s later, and there was no missing-library report and no entry log.

## Not covered

- A real Steam Deck, Steam Game Mode and the zenity/notify-send dialog. The container has neither
  of them, so only stderr and the log were checked.
- The full launcher window on SteamOS: that needs WebKitGTK, through Homebrew (see #114) or a future
  Flatpak/AppImage.
- Gameplay on a Linux GPU driver: the run here used software Vulkan.
