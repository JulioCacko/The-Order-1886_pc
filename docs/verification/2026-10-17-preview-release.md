# Windows preview release packaging — 17 October 2026

Release: `v0.1.0-preview.1`, Windows x64, marked as a prerelease.
Release notes are in [the release document](../releases/v0.1.0-preview.1.md).

The package builder now includes `QUICKSTART.txt`, an English/Portuguese guide
covering extraction, required CUSA00076 files, first-session settings, all five
pages, save backups, installation updates, logs and current limitations. The
same file is attached separately to the release for reading before download.
The existing portable README points users to it.

## Package evidence

- Release package: `dist/order1886/releases/v0.1.0-preview.1/`
- Verified binary snapshot: `dist/order1886/20261017T154943Z-9f5f7f010bb6/`
- ZIP: `order1886-windows.zip`, 105248335 bytes.
- ZIP SHA256: `51f15e6a7eb2e9204d336a6459b09cc0089a17a7b64840509774d305ddb1fad4`
- Runtime SHA256: `9f5f7f010bb68714c8b9c6340ff73e7282b7f551297f7446ae31a97332feec3d`
- Manual matches `packaging/windows/QUICKSTART-Order1886.txt` byte-for-byte,
  appears in the package manifest, and is present inside the ZIP.
- ZIP CRC check passed; no `The Order 1886/user/` player-state tree is included.
- PowerShell packaging-script syntax and `git diff --check` passed.
- All 9 relocated portable checks passed: manifest, preparation closure,
  artwork, runtime identity, native help/info, GUI, missing-game handling with
  and without stdio.
- Smoke report directory: `out/order1886-public-release-preview1-evidence/`.

All frozen Python source snapshots were compared with committed revision
`25e9d45fb14eeba2d88562ab16a8bdd9ca7b5f16` after normalizing checkout line
endings. The release preserves those validated executable/dependency files;
only the guide, portable README, manifest and ZIP were refreshed. Concurrent
diagnostic changes in the working folder are excluded and remain untouched.

The launcher/backend code is unchanged from the official-branding revision
that passed 74 regressions and both GUI smoke modes. This update adds the
guide and its packaging step; it does not introduce a runtime fix or claim
new gameplay, checkpoint, performance or stability validation. Release notes
retain the known `layers=8029/2048` Vulkan blocker and experimental settings.

The release is published from the source commit containing this guide and
build-script change. GitHub's tag/source archives accompany the binary;
the ZIP retains the GPL license, source attribution and dependency notices.
No game files, player data or portable binary artifacts are committed to Git.
