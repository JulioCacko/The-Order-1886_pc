#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Hash-bound post-effect switches for derived preparation output only (#16).

Every switch leaves its effect off the way the game itself does when a lens asks for none.
Each frame the engine clamps the blended lens parameters (the sanitizer at RVA 0x834930) and
then copies them into the post-processing constant block (RVA 0x81dc90). The edits below
replace the load or clamp of one effect's strength with a zero, so every consumer sees a
zero strength and takes its own "effect absent" path:

- motion blur: lens+0x14c becomes constant-block+0x380, and the full-screen effects pass
  (RVA 0xca47c0) runs its pass-through motion-blur variant whenever that is not above 0;
- depth of field: lens+0x398 and the alternate-lens amount lens+0x22c gate the depth-of-field
  pass, and constant-block+0x30c/+0x44c carry its blur amount (with the BlurAmountOffset at
  lens+0x39c added), so the pass falls back to the "Depth of Field Disabled" downsample, or
  runs a fog blur alone with no focus blur;
- film grain: the grain strength lens+0x224 (alternate lens+0x360) feeds constant-block
  +0x464/+0x514 next to the per-frame grain noise offsets at +0x470. In Chapter XI the live
  CFilmGrainParams read (0, 0.49, 1.2): the first field is zero, the second is the strength;
- chromatic aberration: the RGB shift (lens+0x3bc, alternate lens+0x36c) feeds
  constant-block+0x320 and the active copy at +0x5c0.

The offsets come from the engine's own reflection: the lens parameter constructor
(RVA 0x8ff3b0) registers CMotionBlurParams, CDOFParams, CAltDOFParams, CFilmGrainParams,
CAltFilmGrainParams, CChromAberParams and CAltChromAberParams at those offsets.
Every edit keeps the instruction length, and nothing is written unless the source SELF, its
decoded ELF, the build metadata and every expected instruction match.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import order1886_frame_rate as timing

VXORPS_XMM0 = 'c5f857c0'
VXORPS_XMM3 = 'c5e057db'
VXORPS_XMM4 = 'c5d857e4'
NOP4, NOP5 = '0f1f4000', '0f1f440000'
# Effect: (label, ((rva, expected instruction, replacement), ...)).
EFFECTS = {
    'motion_blur': ('Motion blur', (
        (0x835086, 'c5fa10864c010000', VXORPS_XMM0 + NOP4),  # vmovss xmm0, [lens+0x14c]
    )),
    'depth_of_field': ('Depth of field', (
        (0x8358af, 'c5fa5d9e98030000', VXORPS_XMM3 + NOP4),  # vminss xmm3, xmm0, [lens+0x398]
        (0x835617, 'c5fa5da62c020000', VXORPS_XMM4 + NOP4),  # vminss xmm4, xmm0, [lens+0x22c]
        (0x81dd89, 'c5fa5d05d3e8c100', VXORPS_XMM0 + NOP4),  # vminss xmm0, xmm0, [1.0]: cb+0x30c
    )),
    'film_grain': ('Film grain', (
        (0x8355df, 'c5fa5d9e24020000', VXORPS_XMM3 + NOP4),  # vminss xmm3, xmm0, [lens+0x224]
        (0x835887, 'c5fa5d9e60030000', VXORPS_XMM3 + NOP4),  # vminss xmm3, xmm0, [lens+0x360]
    )),
    'chromatic_aberration': ('Chromatic aberration', (
        (0x81de57, '8b86c4030000', '31c0' + NOP4),      # mov eax, [lens+0x3c4]
        (0x81de63, '488b86bc030000', '31c0' + NOP5),    # mov rax, [lens+0x3bc]
        (0x81dec1, '8b8e74030000', '31c9' + NOP4),      # mov ecx, [lens+0x374]
        (0x81deca, '488b8e6c030000', '31c9' + NOP5),    # mov rcx, [lens+0x36c]
        (0x81def7, '8b5108', '31d290'),                 # mov edx, [lens+0x3c4]
        (0x81defd, '488b09', '31c990'),                 # mov rcx, [lens+0x3bc]
    )),
}
WARNING = ('Turning a post effect off edits the prepared copy of the executable; it is not '
           'qualified for gameplay. Turn the effect back on to restore the original image.')


def validate_disabled(names):
    """The effects to turn off, in catalogue order; an unknown name is an error."""
    if isinstance(names, str) or not all(isinstance(name, str) for name in names):
        raise ValueError('Disabled post effects must be a list of effect names')
    for name in names:
        if name not in EFFECTS:
            raise ValueError(f'Unknown post effect: {name}; choose from {", ".join(EFFECTS)}')
    return tuple(name for name in EFFECTS if name in names)


def recipe(disabled):
    disabled = validate_disabled(disabled)
    result = {'id': 'order1886-post-effects-v1', 'disabled': list(disabled)}
    if disabled:
        result.update(source_self_sha256=timing.EXPECTED_SELF_SHA256,
                      source_elf_sha256=timing.EXPECTED_ELF_SHA256,
                      metadata=dict(timing.EXPECTED_METADATA),
                      edits=[{'effect': name, 'rva': hex(rva), 'expected': expected, 'replacement': replacement}
                             for name in disabled for rva, expected, replacement in EFFECTS[name][1]],
                      author='this project (Ghidra analysis of the CUSA00076 executable)',
                      warning=WARNING)
    return result


def recipe_sha256(disabled):
    return hashlib.sha256(json.dumps(recipe(disabled), sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def validate_source(eboot, disabled, metadata):
    disabled = validate_disabled(disabled)
    profile = {**recipe(disabled), 'recipe_sha256': recipe_sha256(disabled), 'applied': False,
               'source_verified': False, 'gameplay_verified': False}
    if not disabled:
        return profile
    profile.update(timing.verify_source_identity(eboot, metadata, feature='Post-effect switches',
                                                recovery='Turn every post effect back on to recover.'))
    return profile


def apply_prepared(boot, profile):
    """Validate every guard before modifying a single byte in a fresh PS4BOOT2 image."""
    disabled = validate_disabled(profile['disabled'])
    if not disabled:
        return dict(profile)
    path = Path(boot).resolve()
    if profile.get('source_eboot') and path == Path(profile['source_eboot']).resolve():
        raise ValueError('Post-effect patches may only modify a derived prepared image')
    data = bytearray(path.read_bytes())
    if len(data) < timing.HEADER.size:
        raise ValueError('Truncated PS4BOOT2 header')
    magic, size, entry, ns, nr, ni, flags = timing.HEADER.unpack_from(data)
    if magic != b'PS4BOOT2' or size != timing.EXPECTED_IMAGE_SIZE or entry != timing.EXPECTED_ENTRY:
        raise ValueError('Unexpected PS4BOOT2 header for the verified post-effect recipe')
    start = timing.HEADER.size + ns * 24 + ni * 128 + nr * 32
    if start + size != len(data):
        raise ValueError('PS4BOOT2 image bounds mismatch')
    if (not profile.get('source_verified') or profile.get('source_self_sha256') != timing.EXPECTED_SELF_SHA256
            or profile.get('source_elf_sha256') != timing.EXPECTED_ELF_SHA256
            or profile.get('recipe_sha256') != recipe_sha256(disabled)):
        raise ValueError('Post-effect source/recipe verification is missing or stale')
    edits = [(name, rva, bytes.fromhex(expected), bytes.fromhex(replacement))
             for name in disabled for rva, expected, replacement in EFFECTS[name][1]]
    # Check every site first, so a mismatch leaves the image untouched.
    for name, rva, expected, replacement in edits:
        found = bytes(data[start + rva:start + rva + len(expected)])
        if len(replacement) != len(expected) or found != expected:
            raise ValueError(f'{EFFECTS[name][0]} instruction signature mismatch at RVA {rva:#x}')
    before = hashlib.sha256(data).hexdigest()
    for name, rva, expected, replacement in edits:
        data[start + rva:start + rva + len(replacement)] = replacement
    after = hashlib.sha256(data).hexdigest()
    path.write_bytes(data)
    return {**profile, 'applied': True, 'changed_bytes': sum(len(edit[3]) for edit in edits),
            'boot_sha256_before': before, 'boot_sha256_after': after}
