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
