# Input and direct-play verification, 2026-10-17

Development work after preview.3, based on `e7fa939`. This record does not close
all acceptance criteria in the expanded mouse issue or certify gameplay.

## Issue #4: standard mouse input

The runtime previously never sampled mouse motion. SDL window events now publish
a mouse-to-right-stick sample and left/right button state; guest pad reads do not
call SDL or consume the motion repeatedly. Time-based smoothing keeps the same
constant-speed response across polling rates. Controller and keyboard input remain
available, with the stronger camera-axis component taking precedence.

Game > Controls exposes mouse look, sensitivity and inverted Y. The same values
persist in launcher JSON, backend arguments and runtime INI. Esc releases capture;
F6 toggles it. Focus loss, text entry and host input capture discard pending mouse
movement and neutralize mouse buttons. Recapture starts with a fresh sample.

CPU tests cover motion, button mapping, controller coexistence, capture reset,
NaN rejection, inversion, 30/60/120/240 Hz response, settings persistence and backend
argument/configuration propagation. Mouse aiming has not been accepted in gameplay.
Rebinding UI and a verified direct 1:1 camera hook remain outside this batch.

Independent review found a buffered-event race: SDL flags can already reflect a
queued focus gain while the focus-lost event is being consumed. The window now
latches focus from each event and requires both that latch and the native flags
before capture. A regression covers loss/recapture while native flags already
report focus. The reviewer confirmed the fix and found no remaining blocker in
the reviewed scope; physical hardware focus/aiming acceptance remains outstanding.

## Issue #19: direct play

The portable package contains `Play The Order 1886.exe`. It runs the same backend
command and session worker as the regular GUI's Play action. It reads existing
preferences without rewriting them, resolves relative paths from the installation,
and opens setup for missing/unsupported configuration. Successful direct play does
not construct a Tk window. Runtime failures retain their code and recent error
context, with the complete session log on disk.

Game > Create desktop shortcut uses the Windows Desktop location and updates the
same shortcut. PowerShell is resolved from the OS directory, not PATH. Real WScript
COM tests use temporary Desktop folders, including Unicode and apostrophes; they
do not create a shortcut on the user's actual Desktop.

The frozen-package check caught and fixed a worker-contract bug: the `done` event
contains `(exit_code, mode, cancelled)`, not a bare exit code. A real-worker test
now checks 0, 7 and 130. A second regression prevents direct play from retaining
the entire session event stream: 20,000 unique log lines previously retained
22,247,483 bytes; the bounded recent-context implementation passes the 2 MB test
limit. Separate regressions verify no Tk window on successful quick launch and
shortcut creation with only System32 on PATH.

## Verified results

- `bash build.sh --test`: all 15 native checks passed after the focus-race fix.
  Log: `out/issues4-19-reviewed-native.log`.
- `python -m unittest discover -s tests`: **207 tests**, **28 skipped**, no
  failures, 72.379 seconds. Log: `out/issues4-19-reviewed-full-suite.log`.
- Portable smoke: **15 checks passed**, including both frozen entry points,
  temporary desktop shortcuts, missing-game handling with/without standard handles,
  original/experimental-60 preparation, and saved-settings direct-play cancellation
  from a different working directory. Installation path contains spaces, Unicode
  and an apostrophe. Evidence: `out/issues4-19-reviewed-evidence/`.
- Package audit: **1,316 manifest file hashes**, eight Python-source hashes,
  matching launcher/direct-play EXE bytes and ZIP CRC verified.
- Real direct play from the Unicode/apostrophe installation started the native
  runtime and SDL window, applied the saved mouse preferences, and stopped after
  **5.924 seconds**. Native exit 0; backend/direct-play exit 130; requested stop;
  **no forced termination**. The original `eboot.bin` hash was preserved. Mouse
  capture was disabled for this lifecycle check. `gameplay_verified=false`.

## Local build identity

- Package: `dist/order1886/20261017T213348Z-f383541912a2/`.
- Runtime SHA256:
  `f383541912a29b73d74d03b5fa7f325ea68927558b20633a65f8bebe4ae3f5fb`.
- Launcher/direct-play SHA256:
  `4dc3c09531c94f60cbca8542947894a399998d38f2925152a6265be42eda2bbb`.
- ZIP SHA256:
  `232310e1ae4d24b2bfadb7e1d6483a8a91c6af90e2aef349ef9b49cc2c912dc9`.
- ZIP size: 108,335,912 bytes. Native source digest matches its build receipt.

This is a local development package. The published preview.3 was not changed by
this work. The invalid 8,029-layer crash (#5), gameplay mouse validation, direct
camera hooks, remapping and the other open feature requests remain tracked work.
