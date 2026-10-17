# The Order patch source

`TheOrder1886-Orbis.xml` is the illusion patch file supplied by the user on
16 October 2026. Its LF-normalized SHA256 is
`ff7411479fc32d0075be7e9ad19ef7a68f108e988ec39332227913eb38c2cfb3`.

The active 60 FPS preparation recipe uses only **60 FPS Unlock**. Its XML byte
address `0x008507c4` equals image base `0x400000` plus the verified instruction RVA
`0x4507be` plus the immediate offset `6`. The prepared receipt now records the
XML hash, entry and address. The unlock is applied once to derived preparation
output; original game files remain unchanged.

The XML targets AppVer 01.02. This installation reports APP_VER 01.00 / VERSION
01.03, so title ID alone is insufficient: the existing exact SELF/ELF hashes,
instruction signature, bounds and RIP-relative timing target remain mandatory.
The user subsequently requested removal of letterboxing. A separate hash-guarded
16:9 aspect recipe now changes only the verified aspect float in derived images;
its applied/source-verified receipt is independent of the timing recipe. The
launcher exposes this experimental profile and Original recovery. The source's
native-1080p visual warning remains pending live verification. The 900p/720p
resolution entries remain unapplied to preserve original scene detail.

The original warning about Chapter 6 and 9 QTE softlocks is retained. Selecting
30 FPS and relaunching restores the native timing preparation. The 60 FPS patch
does not certify game speed, progression, 4K60 performance or full-game Gold.
