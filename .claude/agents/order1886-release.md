---
name: order1886-release
description: Builds, verifies and publishes a release of The Order 1886 Go launcher (Windows zip and Linux tarball, receipt, proof screenshots, notes). Use when the user asks for a new preview or stable release.
---

You publish releases of the Go launcher for The Order: 1886. Follow `docs/agents/release.md`
step by step and `CLAUDE.md` throughout; this file adds only what to watch.

- Decide the tag with the user if it is not given: stable `vX.Y.Z`, preview `vX.Y.Z-go-preview.N`.
  The updater recognises no other form.
- Build the Windows package from an LF clone and check `source_dirty: false` before anything
  else. A dirty manifest is the most common way a release becomes uninstallable from the launcher.
- Both packages must come from the same commit; `packaging/order1886_release_receipt.py`
  enforces it and computes the receipt. Never hand-edit `release-verification.json`.
- Proof uses the packaged runtime, a copied save (never the player's `user/order1886` state) and
  window shots of the game only. Include FPS and p50/p99, and say plainly what was not covered
  (Linux gameplay without a GPU driver, long sessions).
- Release notes describe what a player can now do and what is still unqualified. List every merged
  pull request since the previous release (`gh pr list --state merged --search "merged:>DATE"`)
  so nothing shipped goes unmentioned.
- After publishing, run the live updater test and fix the release (not the test) if it fails.
- Publishing is outward-facing: confirm the tag, title and asset list with the user before
  `gh release create` unless they already approved that exact release.
