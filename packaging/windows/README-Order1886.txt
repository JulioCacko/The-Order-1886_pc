THE ORDER: 1886 - EXPERIMENTAL PC COMPATIBILITY BUILD

Direct play: configure and save once in The Order 1886.exe, then use
Play The Order 1886.exe. Game > Create desktop shortcut creates or updates
a shortcut to this installation. Keep both EXEs with _internal and bin.

Mouse: Game > Controls has mouse look, sensitivity and inverted Y. Save before
starting. In the game, Esc releases the cursor and F6 captures/releases it.
Left mouse = R2/fire, right mouse = L2/aim, WASD = movement, arrows = camera,
I/J/K/L = d-pad. Alt-Tab and text entry release capture. This uses mouse-to-stick
input; direct 1:1 camera control and gameplay/QTE acceptance remain unverified.

Read QUICKSTART.txt for step-by-step setup, the required game-folder structure,
settings, saves, updates and troubleshooting in English and Portuguese.

The supplied October 17 recording shows logos and later 3D cinematics.
Interactive gameplay, checkpoint progression and sustained performance remain
unverified. The supplied boot log stops on an invalid image-layer count.
This archive is a development preview; it does not fix that runtime failure.

Extract the entire archive to a writable folder. Open The Order 1886.exe,
select your existing extracted CUSA00076 game folder in the launch bar.
Game content is not included. No Python installation or compiler is required.
The launcher uses the user-supplied wallpaper and official horizontal/stacked
game logos. The supplied official emblem is used for the launcher, runtime
window and packaged executable icons. Image rights remain with their owners.
The bundled runtime is selected automatically. Runtime override is intended
for explicitly selected comparison builds; leave it blank for this package.

Play starts the compatibility runtime. Verify files prepares a separate image
and audits imports; a successful audit does not establish playable gameplay.
View logs records the actual runtime, command, settings and exit details.
Stop session requests runtime shutdown and waits for process cleanup. Do not
interrupt a save operation. Forced shutdown, when needed, is identified in logs.
Exit waits for an active backend to finish stopping before closing the launcher.

The sidebar has Home, Graphics, Performance, Game and Advanced pages.
Play/Stop and quick settings remain visible on each page. Use Save settings
after editing; starting from a settings page saves its values before launch.
Game lists save backups and offers backup/restore. Restore asks for confirmation
and backs up the current saves first. Save changes are blocked during a session.
On Game, select a backup and press Play to restore it before launch, then choose
Continue/Load in the game. Older snapshots may lack Profile or progress.
Advanced holds runtime selection, logs, folders and GitHub release/support links.
Its language selection also requests the same game language on the next launch.
Matching game language assets must be installed. Restart the launcher for its UI.
The original launcher remains available with the --classic command-line option.

Title-specific settings, prepared images, logs, caches and saves belong in
user/order1886 beside the launcher. The original game files are preserved.
Keep the entire user folder when moving or updating this experimental build.
Display settings apply at the next launch; they do not establish performance.

This is emulator-backed compatibility software for The Order: 1886.
It is not an official source-native PC port.
package-manifest.json records shipped file hashes; bin/runtime-build.json
identifies the source build. LICENSE and notices preserve upstream attribution
and dependency licenses. Source attribution is in notices/ATTRIBUTION.txt.
Build script: packaging/windows/order1886-go-build.ps1 (the Go launcher is the only launcher).
Corresponding source and complete license obligations must accompany any public
redistribution of this development build. Game assets and trademarks belong to
their respective owners.

Current boot, rendering, gameplay, stability and performance gates are recorded
separately in the project continuation documentation. No claim of full campaign
compatibility is made by this launcher or by a successful package smoke test.
