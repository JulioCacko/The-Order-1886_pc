# Digital input mapping: implementation and qualification

The Go Controls page exposes keyboard and controller source selection for the
runtime's 17 PS4 digital destinations. Each destination has an explicit Default
choice and a No digital source choice. Valid changes autosave and apply at the
next launch. Shared inputs activate every assigned destination; changing one
binding preserves the other overrides. Section reset clears custom mappings.

Physical stick axes, analog triggers, mouse buttons, real touch input and overlay
shortcuts remain active. Their independent remapping remains unavailable and is
identified in the launcher. This is partial progress on #4, not completed input,
QTE, gameplay or Gold qualification.

## Runtime contract

`--input-options` runs before game/SDL initialization and reports JSON v1: the
actual SDL source names, scancode IDs, native default sources and destinations.
The runtime receipt's `input_remapping` flag is bound to its executable hash.
Custom mappings require that matching receipt and a validated inventory; default
maps remain usable with older runtimes. The inventory is checked again before
launch rather than inferred from version text or filenames.

Keyboard names encode as `scancode:<id>` so comma and equals keys are unambiguous.
SDL's distinct Return2 key is labeled with its scancode instead of dropping the
duplicate Return name. `none` removes a digital mapping. Existing textual
environment mappings remain supported by the native parser. Native range and
name checks reject invalid scancodes. The launcher forwards validated mappings
as argument arrays and `ORDER1886_KEY_MAP` / `ORDER1886_PAD_MAP`, replacing inherited
overrides. JSON mapping objects preserve unknown unrelated settings keys.

The shared validator protects CLI, autosave, direct play and restore-on-Play.
Unsupported mappings fail before backup restoration or process launch; failed
autosaves preserve the previous settings file. Invalid keyboard and controller
maps can be cleared independently. Saved invalid mappings have an explanation
and remain visible for repair rather than being silently applied.

Windows legacy/Go and Linux preparation closures include the new standard-library
helper. The legacy launcher preserves and forwards saved mappings; the new editing
surface is in the Go preview. This does not promote Go to the default distribution.

## Evidence boundaries

Observed RED/GREEN checks cover native inventory, punctuation scancodes, digital
unbinding, backend/environment forwarding and validation before autosave/restore.
Actual SDL fixtures verify parser behavior and virtual-controller samples reaching
the guest pad ABI, including unchanged physical trigger behavior. These fixtures
do not establish real-controller, keyboard, combat or QTE acceptance.

Malformed inventory, invalid CLI JSON, older receipts, independent repair, source
aliasing, per-button defaults and frontend state preservation have focused tests.
The dedicated Windows CI job compiles the real SDL fixtures; its result must be
checked separately from local results. Packaged worker, relocated package and
native UI acceptance require separate evidence. UI automation remains stopped
following the user's Escape; no new visual or accessibility acceptance is claimed.

Fresh review found a rapid-edit lost-update risk and a malformed-binding error
that could leave legacy Verify busy. The original concurrent-save behavior failed
the delayed-response regression, and the original Verify path raised an uncaught
validation error. Both pass after serializing settings saves, deriving binding
updates from confirmed state, gating session/actions until saves finish, and
constructing the legacy backend command inside the prelaunch error handler.

Final local checks: 385 Python tests passed with zero skips (79.024 seconds),
45 native checks passed, 13 Go tests plus vet/race passed, and 11 frontend tests
plus TypeScript/Vite build passed. The dependency audit reported no vulnerabilities.
Actual source-worker inventory reports 17 destinations, 247 keyboard choices and
27 controller choices (including No digital source), with no availability error.
These are source checks; they do not prove packaged or real-game acceptance.
