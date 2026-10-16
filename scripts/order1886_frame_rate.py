#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Hash-bound Order timing recipe for derived preparation output only.

The candidate is derived from illusion's published Order 01.02 patch and verified
against this exact local executable's instruction and timing consumers. Its
metadata is 01.00/01.03; it is not presented as a version match to that patch.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

import prepare

EXPECTED_SELF_SHA256 = 'a8ce5fe151573dca0b3951e1edfd608b3e027b53cc30761f7805e44c9d9ddec0'
EXPECTED_ELF_SHA256 = '65cd8eaf3a724890d63bde7da084b05a8f63e5c36982d8580e71b51fe3557190'
EXPECTED_METADATA = {'TITLE_ID': 'CUSA00076', 'APP_VER': '01.00', 'VERSION': '01.03'}
EXPECTED_IMAGE_SIZE = 24512608
EXPECTED_ENTRY = 0xa0
INSTRUCTION_RVA = 0x4507be
TARGET_GLOBAL_RVA = 0x15c0d54
EXPECTED_INSTRUCTION = bytes.fromhex('c7058c05170102000000')
PUBLIC_PATCH_URL = ('https://github.com/illusionyy/PS-Game-Patch/blob/'
                    '3ad781ad8748139d2ca5e6c3b018d0063b8aa1a3/patches/xml/TheOrder1886-Orbis.xml')
WARNING = ('Experimental 60 FPS is unverified for gameplay stability. The published patch warns of '
           'QTE softlocks in Chapters 6 and 9. To recover, stop the session, select 30 FPS, '
           'and relaunch. Original game files are not patched.')
HEADER = struct.Struct('<8s6Q')


def validate_frame_rate(value):
    if type(value) is not int or value not in (30, 60):
        raise ValueError('Frame rate must be 30 or 60 FPS')
    return value


def recipe(frame_rate):
    rate = validate_frame_rate(frame_rate)
    result = {'id': 'order1886-native-30-v1' if rate == 30 else 'order1886-a8ce-engine-60-v1',
              'engine_fps': rate, 'host_fps_limit': rate, 'vblank_hz': 60,
              'experimental': rate == 60}
    if rate == 60:
        result.update(source_self_sha256=EXPECTED_SELF_SHA256, source_elf_sha256=EXPECTED_ELF_SHA256,
                      metadata=dict(EXPECTED_METADATA), instruction_rva=hex(INSTRUCTION_RVA),
                      expected_instruction=EXPECTED_INSTRUCTION.hex(),
                      replacement_instruction=(EXPECTED_INSTRUCTION[:6] + b'\x01\0\0\0').hex(),
                      target_global_rva=hex(TARGET_GLOBAL_RVA), author='illusion; current-hash verification by this project',
                      public_patch_url=PUBLIC_PATCH_URL, public_patch_app_ver='01.02',
                      warning=WARNING)
    return result


def recipe_sha256(frame_rate):
    return hashlib.sha256(json.dumps(recipe(frame_rate), sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def validate_source(eboot, frame_rate, metadata):
    rate = validate_frame_rate(frame_rate)
    profile = {**recipe(rate), 'recipe_sha256': recipe_sha256(rate), 'applied': False,
               'source_verified': False, 'gameplay_verified': False}
    if rate == 30:
        return profile
    source = Path(eboot).resolve()
    data = source.read_bytes()
    actual_self = hashlib.sha256(data).hexdigest()
    if actual_self != EXPECTED_SELF_SHA256:
        raise ValueError(f'Experimental 60 FPS unsupported SELF SHA256 {actual_self}; '
                         f'expected {EXPECTED_SELF_SHA256}. Select 30 FPS to use the native baseline.')
    elf = prepare.parse_self(data)[0]
    actual_elf = hashlib.sha256(elf).hexdigest()
    if actual_elf != EXPECTED_ELF_SHA256:
        raise ValueError(f'Experimental 60 FPS reconstructed ELF SHA256 mismatch: {actual_elf}')
    for name, expected in EXPECTED_METADATA.items():
        if metadata.get(name) != expected:
            raise ValueError(f'Experimental 60 FPS metadata mismatch for {name}: '
                             f'expected {expected}, found {metadata.get(name)}')
    profile.update(source_verified=True, source_eboot=str(source))
    return profile


def apply_prepared(boot, profile):
    """Validate every guard before modifying a single byte in a fresh PS4BOOT2 image."""
    rate = validate_frame_rate(profile['engine_fps'])
    if rate == 30:
        return dict(profile)
    path = Path(boot).resolve()
    if profile.get('source_eboot') and path == Path(profile['source_eboot']).resolve():
        raise ValueError('Timing patches may only modify a derived prepared image')
    data = bytearray(path.read_bytes())
    if len(data) < HEADER.size:
        raise ValueError('Truncated PS4BOOT2 header')
    magic, size, entry, ns, nr, ni, flags = HEADER.unpack_from(data)
    if magic != b'PS4BOOT2' or size != EXPECTED_IMAGE_SIZE or entry != EXPECTED_ENTRY:
        raise ValueError('Unexpected PS4BOOT2 header for the verified timing recipe')
    image_offset = HEADER.size + ns * 24 + ni * 128 + nr * 32
    if image_offset + size != len(data) or INSTRUCTION_RVA + len(EXPECTED_INSTRUCTION) > size:
        raise ValueError('PS4BOOT2 image bounds mismatch')
    offset = image_offset + INSTRUCTION_RVA
    instruction = bytes(data[offset:offset + len(EXPECTED_INSTRUCTION)])
    if instruction != EXPECTED_INSTRUCTION:
        raise ValueError(f'Experimental 60 FPS instruction signature mismatch at RVA {INSTRUCTION_RVA:#x}')
    target = INSTRUCTION_RVA + len(instruction) + struct.unpack_from('<i', instruction, 2)[0]
    if target != TARGET_GLOBAL_RVA or target + 4 > size:
        raise ValueError('Experimental 60 FPS instruction RIP target mismatch')
    if (not profile.get('source_verified') or profile.get('source_self_sha256') != EXPECTED_SELF_SHA256
            or profile.get('source_elf_sha256') != EXPECTED_ELF_SHA256
            or profile.get('recipe_sha256') != recipe_sha256(60)):
        raise ValueError('Experimental 60 FPS source/recipe verification is missing or stale')
    before = hashlib.sha256(data).hexdigest()
    data[offset + 6] = 1  # Only mov dword [RIP+disp32], 2 -> 1; never force the live global.
    after = hashlib.sha256(data).hexdigest()
    path.write_bytes(data)
    return {**profile, 'applied': True, 'changed_bytes': 1,
            'boot_file_offset': hex(offset + 6), 'instruction_before': instruction.hex(),
            'instruction_after': bytes(data[offset:offset + len(instruction)]).hex(),
            'boot_sha256_before': before, 'boot_sha256_after': after}
