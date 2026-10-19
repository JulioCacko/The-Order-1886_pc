# Recoverable Windows updates (#9)

Implementation in progress. This is not updater qualification or a Gold claim.

The Go host will own release checks, downloads, staging and recovery. Its copied
helper can run before Wails and the Python worker load. Existing worker settings
validation and session locking remain authoritative. Use standard Go libraries;
do not copy the donor's unvalidated `extractall` and replacement behavior.

Scope: Go update core and Windows helper/bootstrap; Go bridge; worker idle/lock
handoff; System/Home update controls; settings catalogue; portable manifest and
smoke tests; documentation and issue acceptance. Preserve legacy and Linux entry
points. Source checkouts must never update themselves through the portable updater.

Only manifest-owned package files may change. Saves, settings (including unknown
keys and explicit false), game content, mods and patches must survive byte for
byte. Refuse unexpected existing files, links, modified package files and active
sessions. Stage and verify before replacement. Retain verified previous files and
a write-ahead journal; interrupted replacement must recover before worker startup.
Rollback must refuse unexpected user edits. Download, cancellation, recovery and
rollback tests use isolated installations, never the player's running package.

Archive verification must bind the GitHub asset SHA256 and byte size to the receipt,
source revision, runtime identity and complete manifest. Accept only the dedicated
Go Windows asset from this repository. Reject traversal, Windows path aliases,
links, duplicate entries, unmanifested payloads, protected paths and oversized
archives. Package paths are relative; the installation/staging location may contain
Unicode and spaces. Network, UI, helper and populated-directory evidence remain
required after the core checks.

Donor inspected: `D:/Emulator/theorder1886-port/launcher/port_launcher_win.py`,
`check_update`, `offer_update`, `install_update` (approximately lines 2039–2130).
Its notification/progress flow is useful reference, but it does not establish the
integrity, path validation or recovery contract above. No donor code copied.

## Download and staging evidence

The standard-library Go core now checks the fixed repository's newest dedicated
Go release, validates the GitHub SHA256/size of its receipt and archive, binds
source/runtime identity to the manifest, downloads to a new file, and stages to a
new private directory. Failed/cancelled downloads and stages are removed; existing
destinations are refused. It does not replace installed files or enable updates
in the UI yet.

- `go test ./... -count=1`: 67 passing tests, no skips.
- `CGO_ENABLED=1 CC=C:/msys64/clang64/bin/clang.exe go test -race ./... -count=1`:
  67 passing tests, no races reported.
- `go vet ./...`: passed.
- Real TLS HTTP-server tests exercise release selection, receipts, truncated and
  altered downloads, size limits, cancellation and destination preservation.
- Real ZIP/filesystem tests exercise payload hashes, source/runtime/ABI mismatch,
  missing/extra files, protected paths, Windows path aliases, duplicate entries,
  links marked as directories, expanded-size limits and Unicode staging paths.

A one-off test called the live `CheckRelease` and staged the existing published
preview.6 ZIP into a temporary Unicode path. It passed against GitHub's verified
receipt: 137,250,491 bytes, 2,356 payload files (2,357 ZIP entries), archive SHA256
`2ecfaa69c7259441e3ec5c9efce3109b6526cc1fd5938f33bb8d60b20a5fee26`,
source `43749149095902c245b381373923cca6e1c777c7`, runtime SHA256
`f49ccff3db1ceabbb538ab29633ed3c7cf405d5b4233761171dc5878e8a65c33`.
The temporary machine-specific test was removed after the check; the permanent
suite uses self-contained fixtures. This was local extraction of the published
archive after a live receipt check, not a complete internet ZIP-download test.

Runtime, Python worker and frontend code are unchanged in this batch. No player
package was updated, no game input was automated, and no performance improvement
or Gold acceptance follows from these host checks. Transaction/recovery/helper,
idle handoff, launcher surfaces, packaging ABI and populated-directory update and
rollback evidence remain outstanding under #9.

Fresh source review found no Critical or Important findings and independently
passed all 54 core tests. The reviewer read all four new Go files directly;
graph generation `2026-10-18T23:07:49Z` reports their coverage as missing.
Minor integration boundary: callers must stage beneath a trusted, caller-owned
parent directory. Creating a directory with mode `0700` inherits Windows ACLs;
this API does not grant a separate Windows permission boundary. The helper and
transaction integration must enforce that staging precondition.

## Transaction core (integration still pending)

The Go core now backs up changed manifest-owned files, retains verified new
payloads and writes a recovery journal before changing installed files. Its
installation lock rejects concurrent updaters. It refuses source checkouts,
directory links/junctions, modified package files and unowned path collisions.
Failed replacement and cancellation attempt rollback. Unknown edits are retained
and reported instead of being overwritten. A new transaction may follow a
completed/rolled-back transaction; older transaction directories are retained.
Backup cleanup/retention still needs integration before shipping.

Candidate packages must advertise `order1886-update-1`. This ABI is not yet added
to package builds because the actual launcher bootstrap is still outstanding.
The caller carries `StageArchive`'s returned manifest SHA256 into
`Identity.ManifestSHA256` before preparation; preparation checks that exact
manifest again and hashes files during copying. Editing both a staged file and
its manifest cannot replace the originally verified candidate.

The two Go entry points are replaced before worker/library changes and restored
last during rollback. The helper must hold the player-session lock and wait for
the initiating launcher/worker to close before applying or rolling back. The core
alone does not acquire that player lock or launch a recovery UI. Legacy launcher
startup during replacement and the complete packaged helper/bootstrap flow
remain qualification requirements.

Current checks include interruption at each of seven replacement boundaries,
actual termination of a child updater process followed by lock reacquisition and
recovery, cancellation/retry, unexpected edits, corrupt backups/stages, a Windows
library opened without delete sharing, and rejection of a real Windows junction.
Oversized journals are refused before replacing the previous recovery record.
These are process-interruption checks; sudden-power-loss durability remains
unqualified. They do not establish that the packaged launcher recovers yet.

A one-off isolated check copied complete `savedata`, `savedata_backups` and
`trophies` trees plus settings/runtime INI from the retained 014410Z player
package: **21 files, 710,512 bytes**. Apply and rollback preserved every copied
byte and left the source files unchanged. Current-save and backup directories
were kept separate; no profile data was merged across snapshots. The temporary
machine-specific check was removed after it passed. Package binaries in this
check were the deterministic transaction fixtures, so actual packaged-binary
replacement/locking and runtime visibility of saves remain separate gates.

Final transaction-batch checks: `go test ./... -count=1` and
`go test -race ./... -count=1` each passed **97 tests, no skips**; `go vet ./...`
passed. The Linux core test binary cross-compiled successfully; it was not run on
Linux. A fresh source reviewer independently passed all **84 core tests** and
found no actionable Critical, Important or Minor defects under the documented
trusted-directory and stopped-player assumptions. The earlier staging commit
`9e01f76ce342475ccab1e859f39c1969e97e1f44` also passed hosted Go launcher workflow
`39284967948`; that result does not cover these later transaction changes.

No application entry point calls this module yet. This source batch does not
enable updates, change an installed player package or satisfy #9's full acceptance.
