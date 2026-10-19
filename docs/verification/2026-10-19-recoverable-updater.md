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

Candidate packages must advertise `order1886-update-2`. The caller carries
`StageArchive`'s returned manifest SHA256 into `Identity.ManifestSHA256` before
preparation; preparation checks that exact manifest again and hashes files during
copying. Editing both a staged file and its manifest cannot replace the originally
verified candidate.

The two Go entry points are replaced before worker/library changes and restored
last during rollback. Deletions run after every replacement and before the
manifest, so a retired entry point never disappears before its replacement
exists.

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

## Helper, startup recovery and the Go-only package

The updater is now wired end to end. `--update-helper` is parsed in `main()` before
Wails and before any worker process, and the launcher copies itself into
`.order1886-update/helper.exe` because Windows cannot replace a running executable
or its loaded Python libraries. The helper waits for the launcher by **process id
and creation time**, then holds the installation lock and the player session lock
(`session.lock`, byte 0, the same lock the Python backend takes) for the whole
apply, recovery or rollback.

Startup order is: parse helper mode → `PendingRecovery` → hand recovery to the
helper and exit → otherwise Wails → `app.connect()`. A journal that appears later
is refused by `App.connect()` as a backstop, so a mixed package never loads. A
completed update is not an interrupted one: rolling it back is an explicit action.
A failed recovery is recorded once in `last-result.json`, never retried
automatically, and surfaced as a blocking state with a single restore action.

The package is now Go only. `order1886-go-build.ps1` no longer copies the previous
Python launcher, writes `update_abi: "order1886-update-2"`, and the relocated
smoke asserts the retired entry point is absent, the ABI is present, and the helper
finds nothing to recover in a clean package. An installed tree that still contains
`The Order 1886 Legacy.exe` loses it during the first update — the updater's first
real deletion in the field.

### Evidence for this batch

- Branch `codex/order1886-update-integration` from `origin/main`
  `4c68f3be26792cda7b0a320dc8e39aca99b2944d`; handed-off WIP preserved byte for byte.
- `go test ./... -count=1`: **118 passed**; `-race`: **117 passed** (before the
  last e2e-only edit); `go vet ./...` passed; `gofmt` clean.
- Full Python suite: **399 tests, OK**. New HTILE-control tests cover the default,
  the declared-runtime path, refusal for a runtime that does not declare it, and
  the catalogue/worker round trip.
- Native: `build.sh --test` passed **46 native checks** and produced runtime
  `0c9537c829bd02403cd96c2afd4f4bd44fa938febd5da47d591fd54a25d9e2e9`, whose receipt
  now declares `htile_control`.
- Frontend: `tsc --noEmit` clean, `vite build` clean, **17 tests** including six new
  update-surface tests (install gating, blocked recovery, progress, failures, busy
  state).
- Go package `out/order1886-go-package/20261019T190040Z/The Order 1886`:
  `source_dirty: false`, revision `9f0ca0a`, `update_abi: order1886-update-2`,
  2349 manifest files; portable smoke passed at a Unicode path with restricted PATH.
- Candidate archive: **137,646,531 bytes**, SHA256
  `f7ff3f3abee1d63b5c779733db63e027b16fee12f8caa485b3cb5c4f0bc6f812`, 2350 entries.
  This is the archive the tagged end-to-end test below actually consumed.
- Packaged end-to-end (`-tags e2e`, `TestPackagedUpdatePreservesPlayerDataAndRollsBack`):
  a full copy of the published preview.6 package plus **46 real player files**
  (savedata, saves backups, trophies, logs, settings, runtime INI) copied read-only
  from the player's own state directory. Apply replaced the launcher files, deleted
  `The Order 1886 Legacy.exe`, left every player byte identical (only the OS session
  lock file appeared), started the updated worker successfully, and rollback
  restored every package file. Run time 43.6 s.
- A live `CheckRelease`/local-extraction check and the earlier transaction checks
  above still stand; this batch adds the packaged binaries and the populated tree.

### Deliberate deviations from the plan text

- A journal from the previous schema is rejected outright instead of being treated
  as "recoverable but not relaunchable": relaunching without the recorded profile
  is exactly the silent profile switch `BindSession` exists to prevent, and no
  released package ever wrote that schema.
- The journal records a validated relaunch mode (`direct_play: bool`), not a list of
  recorded arguments. Arbitrary recorded argv would be an injection surface for no
  benefit, since the only variable part is the state directory, which is recorded
  separately.
- The handed-off work shares one commit with the contract change because
  `recovery.go` depends on the journal field it adds; a session-only commit would
  not build.
- The two native HTILE call sites are gated by one cached environment read. That
  decision has no separate both-directions native test; the C++ read-backing
  fixtures model an opted-in player, and the Python tests cover the launcher
  contract. The gameplay A/B remains the only qualification for the behaviour.
- Removing the legacy launcher EXE was the agreed scope; the legacy Python payload
  it used (`_internal/`, `launcher/`) still ships as dead weight and is a follow-up.

### Still unqualified

Sudden power loss, a player updating their own live installation (this batch used a
copy), WebView2-missing and offline behaviour after an update, the real relaunch
experience in a running session, HTILE gameplay/visual/frame-cost behaviour, and
every Gold gameplay, performance, 4K/FG, Update 1.02 and matching-hardware gate.
