THE ORDER: 1886 - EXPERIMENTAL PC COMPATIBILITY BUILD

The current real-game boot displays an intro title card, then stops during
graphics processing. A working main menu and gameplay have not been established.
This archive is a development preview.

Extract the entire archive to a writable folder. Open The Order 1886.exe,
choose Settings and select your existing extracted CUSA00076 game folder.
Game content is not included. No Python installation or compiler is required.
The backdrop and game window icon are read from your selected game folder.
An original black-and-gold launcher icon is supplied for the portable build.
The bundled runtime is selected automatically. Runtime override is intended
for explicitly selected comparison builds; leave it blank for this package.

Play starts the compatibility runtime. Verify files prepares a separate image
and audits imports; a successful audit does not establish playable gameplay.
View logs records the actual runtime, command, settings and exit details.
Stop session requests runtime shutdown and waits for process cleanup. Do not
interrupt a save operation. Forced shutdown, when needed, is identified in logs.
Exit waits for an active backend to finish stopping before closing the launcher.

Title-specific settings, prepared images, logs, caches and saves belong in
user/order1886 beside the launcher. The original game files are preserved.
Keep the entire user folder when moving or updating this experimental build.
Display settings apply at the next launch; they do not establish performance.

This is emulator-backed compatibility software for The Order: 1886.
It is not an official source-native PC port.
package-manifest.json records shipped file hashes; bin/runtime-build.json
identifies the source build. LICENSE and notices preserve upstream attribution
and dependency licenses. Source attribution is in notices/ATTRIBUTION.txt.
Build script: packaging/windows/order1886-build.ps1.
Corresponding source and complete license obligations must accompany any public
redistribution of this development build. Game assets and trademarks belong to
their respective owners.

Current boot, rendering, gameplay, stability and performance gates are recorded
separately in the project continuation documentation. No claim of full campaign
compatibility is made by this launcher or by a successful package smoke test.
