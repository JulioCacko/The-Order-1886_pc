# Order asset mods

Choose the mods folder in Advanced, explicitly enable the desired folders, and
save before starting the game. New folders are disabled. Changes apply on the
next launch. Relative mods paths use the installation directory in both the
launcher and direct play, regardless of the process working directory.

Each mod has its own folder containing paths relative to the original game:

```text
mods/
  My asset mod/
    _data/...
    archivemap.bin
```

Only `_data` assets and the optional `archivemap.bin` asset index are supported.
Executable and system replacements, script injection, directory links, reparse
points, and ambiguous filename case are rejected. Extract archives separately.
An accepted file layout does not establish that an asset is compatible with the
selected game build.

The last selected mod wins when multiple mods replace the same file. The launcher
shows these conflicts; the loader does not merge file contents.

Preparation and executable verification use the original game. The runtime mounts
a separate generation under the selected state's `mod-overlays` directory while
holding the normal session lock. Game files and mod sources are preserved.
Disabling mods restores the original mount. Failed construction preserves the
previous complete generation, and a later successful build removes owned leftovers.
Managed overlay directories cannot themselves be selected as the original game.

Unchanged writable files use hard links where possible. Replacements, read-only
sources, and files on other volumes use copies. Read-only game dumps therefore
require additional disk space and preparation time; cleanup never changes their
attributes.

The implementation adapts the GPL-2.0-or-later overlay approach in
`Jgamrot/bloodborne_pc`, commit `52e4988f54b0626447563874bf8695633b1a4302`,
for Order's asset layout and validation requirements.
