# Installed achievement artwork

The Go preview now lists the selected installation's achievement IDs, locked and
earned state, local progress, artwork for earned entries, and localized first-unlock
dates. Unknown earned IDs remain visible when an archive is missing or different.
Artwork is read from the user's installation and is not distributed. Locked images
stay hidden to avoid revealing artwork before an unlock.

The read-only worker adapter validates the TRP v3 header, declared size, SHA1,
entry bounds, duplicate/unsafe names, overlap, PNG dimensions and response budget.
It never extracts archive paths to disk. Archive errors preserve the independent
checksummed unlock history; history errors are shown instead of asserting that
every trophy is locked. The previous worker schema remains readable by the frontend.

The layout was checked against shadPS4's GPL-2.0-or-later
`src/core/file_format/trp.h` at `0ebea15c24253b60f514fc37a348dabc8d0bcb90`.
No decryption implementation or dependency was added. Official names and
descriptions in this installation are encrypted ESFM entries and remain unavailable.
This is partial progress on #22, not achievement or Gold qualification.

Read-only inspection of the installed base game's `sce_sys/trophy/trophy00.trp`
found 22 icons, IDs 0 through 21, and verified the file was unchanged. Archive SHA256:
`cd8978bb801504f041de5de9510341af5f82353d919bcddee3944f0a4a70435b`.
Isolated test unlocks were supplied to the reader; this is not a claim that the
player earned any particular trophy.

The parser, worker response and frontend-list tests were observed failing before
their corresponding implementation and then passing. Corrupt archives, unsafe
entries, excessive dimensions, response limits, unknown earned IDs and date
formatting for all 13 launcher locales have automated coverage.

Fresh review found that the three-second polling refresh recreated the scroll
container, returning readers to the top of the now-populated list. The original
replacement behavior failed the regression (`0` instead of `760` scroll pixels).
The shared replacement now restores scroll and stable keyboard focus; explicit
page navigation still starts at the top. The regression passes with the fix.

Local checks: 376 Python tests passed with zero skips (77.842 seconds), 45 native
checks passed, 13 Go tests plus vet/race passed, seven frontend tests and the
TypeScript/Vite build passed. Dependency audit reported zero vulnerabilities.
The first Python run had 17 skips for an absent decoder in the packaging
environment; the final run used the already-equipped original private environment
against this worktree's source. These are local checks, not hosted CI evidence.

Packaged UI, accessibility, actual game unlock capture, encrypted names, complete
localization of new copy and the remaining native trophy APIs still require
qualification. Native UI automation remains stopped following the user's Escape.
