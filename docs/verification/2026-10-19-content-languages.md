# Independent game languages: static investigation

Source: installed CUSA00076, APP_VER 01.00 / VERSION 01.03, eboot SELF SHA256
`a8ce5fe151573dca0b3951e1edfd608b3e027b53cc30761f7805e44c9d9ddec0`.
No original file or production language behavior was changed. This does not
qualify independent text/voice selection or close #21.

Headless Ghidra 12.1.4 seeded 27,958 real GNU EH-frame function bounds. The broad
analysis timed out after 180 seconds; targeted decompilation then succeeded.
Addresses below are image-relative and describe static observations.

- Initializer `0xa7f110` defaults SKU to 4. The numeric `-language` option sets
  application `+0x4ec` directly; otherwise PS4 system language is translated by
  table `0xf13370` and filtered by SKU. In SKU 4, Brazilian Portuguese engine ID
  17 falls back to English ID 1. System-language forwarding alone does not prove
  that the requested game language becomes effective.
- `0xa82860` copies application `+0x4ec` to engine configuration `+0xd0`;
  `0x8a10a0` copies this to engine `+0x168`.
- Subtitle/objective setup receives that language and calls the SWF method
  `SetupLanuage` (the executable's spelling). The resource selector `0x7fbf40`
  changes namespace references and stores its selected language at manager `+0x48`.
- Engine initialization also calls `IxCSoundPlayer` virtual `+0x58`. RELA-backed
  vtable `0x16456e0` resolves it to `0x9b51e0`, which stores the numeric language
  at `[global_0x1716388 + 0x6c]`. A read that makes this value control localized
  voice lookup has **not** been proved. Patching this setter could have no effect
  on speech. Trace an actual localized voice-resource lookup before enabling it.

Private asset inspection verified `COMPRESS` containers with two little-endian
64-bit sizes and payload at offset 24. The installed modern Oodle provider
identified legacy LZH but could not decode it. Analysis-only QuickBMS 0.12
successfully decoded the small installed resources. Five small namespaces were
checked; `8e90a600646981c8` contained 21 localized photo-mode resources, including
Brazilian Portuguese. This is positive asset evidence, not proof that all campaign
text or voices for a language are complete. Hashed filenames alone are not a
language inventory.

QuickBMS came from the author's `https://aluigi.altervista.org/papers/quickbms.zip`;
ZIP SHA256 `b9d4f9efb55692994cd42a491cfea11f86e3375a618b9bd771583ce40ddb3828`.
It and the inspected game assets are private analysis inputs, excluded from source
and release packages. No decoder dependency was added to the launcher.

Reproducible manifests, source hashes, decoded-output hashes, focused
decompilations and decoder logs remain in ignored
`out/order1886-evidence/content-languages/`. The initially guessed `00*.c`
decompilations and an uninitialized CRC-table probe are not reliable evidence;
the later exact-FDE outputs supersede them. No game/UI runtime check was performed.
