#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Byte-checked Order timing recipes for derived preparation output only.

The 60 FPS recipe is illusion's published Order 01.02 patch. Every edition in
order1886_editions runs the same 01.02 code, so a recipe binds to the instruction bytes at
its sites, not to one executable's hash: the eboot.bin first verified here (SELF SHA256
a8ce5fe1..., the CUSA00076 01.02 executable) is one of several builds with that code (#113).

The 90 FPS and unlocked recipes come from this executable alone
(docs/verification/2026-10-21-graphics-step8-frame-rate.md). The engine clock
(RVA 0x90eab0) steps by measured wall time, clamped at 66.7 ms, so no simulation
constant assumes 30 FPS. The rate comes from the vblank interval global at 0x15c0d54:
the main loop's `-frontend -syncinterval 2` argument sets it at boot, three writes
reset it to 2 and two set it to 1 for a scripted sequence. A CPU pacer (RVA 0x835a60)
sleeps until interval * 16666 us minus 2 ms has passed, and the flip (RVA 0x877cf0)
calls sceVideoOutSetFlipRate(interval - 1). At interval 0 the pacer never sleeps and
the flip is immediate: the engine's own uncapped mode.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

import order1886_editions as editions
import prepare

INSTRUCTION_RVA = 0x4507be
TARGET_GLOBAL_RVA = 0x15c0d54
EXPECTED_INSTRUCTION = bytes.fromhex('c7058c05170102000000')
PUBLIC_PATCH_URL = ('https://github.com/illusionyy/PS-Game-Patch/blob/'
                    '3ad781ad8748139d2ca5e6c3b018d0063b8aa1a3/patches/xml/TheOrder1886-Orbis.xml')
PUBLIC_PATCH_XML_SHA256 = 'ff7411479fc32d0075be7e9ad19ef7a68f108e988ec39332227913eb38c2cfb3'
PUBLIC_IMAGE_BASE = 0x400000
WARNING = ('Experimental 60 FPS is unverified for gameplay stability. The published patch warns of '
           'QTE softlocks in Chapters 6 and 9. To recover, stop the session, select 30 FPS, '
           'and relaunch. Original game files are not patched.')
HEADER = struct.Struct('<8s6Q')
UNLOCKED = 0  # engine_fps of the unlocked recipe: only the presentation cap paces it
RATES = (30, 60, 90, UNLOCKED)
SYNC_ARGUMENTS_RVA = 0x1482726
SYNC_ARGUMENTS = b'-frontend -syncinterval 2\0'
PACER_RVA = 0x835b9c
PACER_MICROSECONDS = 16666
# RVA -> the interval each `mov dword [RIP+disp32], imm32` there writes to TARGET_GLOBAL_RVA.
INTERVAL_WRITES = {0x4507be: 2, 0x7658dd: 2, 0x765b6e: 2, 0x76590a: 1, 0x3f193a: 1}
FEATURES = {60: 'Experimental 60 FPS', 90: 'Experimental 90 FPS', UNLOCKED: 'Experimental unlocked frame rate'}
HIGH_RATE_WARNING = ('{feature} is experimental. The game clock follows measured time, but '
                     'Chapter 6 and 9 QTE behaviour at this rate has not been accepted. To recover, '
                     'stop the session, select 30 FPS, and relaunch. Original game files are not patched.')


def validate_frame_rate(value):
    if type(value) is not int or value not in RATES:
        raise ValueError('Frame rate must be 30, 60 or 90 FPS, or 0 for unlocked')
    return value


def interval_write(rva, interval):
    return b'\xc7\x05' + struct.pack('<iI', TARGET_GLOBAL_RVA - rva - 10, interval)


def pacer_instruction(microseconds):
    """imul r14d, dword [RIP+disp32], imm32: the pacer's frame budget is interval * imm32."""
    return b'\x44\x69\x35' + struct.pack('<iI', TARGET_GLOBAL_RVA - PACER_RVA - 11, microseconds)


def edits(frame_rate):
    """(rva, expected, replacement) of the 90 or unlocked recipe; each encodes the RIP target."""
    interval = 1 if frame_rate == 90 else 0
    result = [(SYNC_ARGUMENTS_RVA, SYNC_ARGUMENTS, SYNC_ARGUMENTS[:-2] + b'%d\0' % interval)]
    result += [(rva, interval_write(rva, value), interval_write(rva, interval))
               for rva, value in INTERVAL_WRITES.items() if value != interval]
    if frame_rate == 90:
        # At interval 1 the stock pacer holds every frame to at least 14.7 ms (68 FPS).
        result.append((PACER_RVA, pacer_instruction(PACER_MICROSECONDS),
                       pacer_instruction(1000000 // 90)))
    return result


def recipe(frame_rate):
    rate = validate_frame_rate(frame_rate)
    if rate in (90, UNLOCKED):
        return {'id': f'order1886-a8ce-engine-{rate or "unlocked"}-v1', 'engine_fps': rate,
                'host_fps_limit': rate, 'vblank_hz': 60, 'experimental': True,
                'title_ids': list(editions.TITLE_IDS), 'target_global_rva': hex(TARGET_GLOBAL_RVA),
                'edits': [{'rva': hex(rva), 'expected': old.hex(), 'replacement': new.hex()}
                          for rva, old, new in edits(rate)],
                'author': 'this project; reverse-engineered from the verified executable',
                'warning': HIGH_RATE_WARNING.format(feature=FEATURES[rate])}
    result = {'id': 'order1886-native-30-v1' if rate == 30 else 'order1886-a8ce-engine-60-v1',
              'engine_fps': rate, 'host_fps_limit': rate, 'vblank_hz': 60,
              'experimental': rate == 60}
    if rate == 60:
        result.update(title_ids=list(editions.TITLE_IDS), instruction_rva=hex(INSTRUCTION_RVA),
                      expected_instruction=EXPECTED_INSTRUCTION.hex(),
                      replacement_instruction=(EXPECTED_INSTRUCTION[:6] + b'\x01\0\0\0').hex(),
                      target_global_rva=hex(TARGET_GLOBAL_RVA), author='illusion; instruction verification by this project',
                      public_patch_url=PUBLIC_PATCH_URL, public_patch_app_ver='01.02',
                      public_patch_file='patches/TheOrder1886-Orbis.xml',
                      public_patch_xml_sha256_lf=PUBLIC_PATCH_XML_SHA256,
                      public_patch_entry='60 FPS Unlock',
                      public_patch_address=f'0x{PUBLIC_IMAGE_BASE + INSTRUCTION_RVA + 6:08x}',
                      warning=WARNING)
    return result


def recipe_sha256(frame_rate):
    return hashlib.sha256(json.dumps(recipe(frame_rate), sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def image_bytes(elf, ph, rva, size):
    """The bytes the loaded image holds at rva, read from the decoded ELF; None if unmapped."""
    for p in ph:
        if p['type'] in (1, 0x61000010) and p['vaddr'] <= rva and rva + size <= p['vaddr'] + p['filesz']:
            start = p['offset'] + rva - p['vaddr']
            return bytes(elf[start:start + size])
    return None


def verify_source_identity(eboot, metadata, sites, *, feature, recovery):
    """An accepted edition whose executable holds the expected bytes at every recipe site.

    No hash or APP_VER is required: the bytes are what the edits depend on, and a build whose
    code differs at any site is refused before preparation."""
    title_id = metadata.get('TITLE_ID')
    if not editions.supported(title_id):
        raise ValueError(f'{feature} supports {", ".join(editions.TITLE_IDS)}; '
                         f'the selected game is {title_id or "unknown"}. {recovery}')
    source = Path(eboot).resolve()
    data = prepare.read_self(source)
    elf, _, ph = prepare.parse_self(data)[:3]
    for rva, expected in sites:
        found = image_bytes(elf, ph, rva, len(expected))
        if found != expected:
            raise ValueError(f'{feature} does not match this executable at RVA {rva:#x}: expected '
                             f'{expected.hex()}, found {found.hex() if found else "unmapped"} '
                             f'(APP_VER {metadata.get("APP_VER", "unknown")}). {recovery}')
    return dict(source_verified=True, source_eboot=str(source), title_id=title_id,
                source_self_sha256=hashlib.sha256(data).hexdigest(),
                source_elf_sha256=hashlib.sha256(elf).hexdigest())


def source_sites(frame_rate):
    """(rva, expected) of every instruction a non-native rate edits."""
    if frame_rate == 60:
        return [(INSTRUCTION_RVA, EXPECTED_INSTRUCTION)]
    return [(rva, expected) for rva, expected, _ in edits(frame_rate)]


def prepared_image(path):
    """(bytes, image offset, image size) of a derived PS4BOOT2 container, bounds-checked."""
    data = bytearray(Path(path).read_bytes())
    if len(data) < HEADER.size:
        raise ValueError('Truncated PS4BOOT2 header')
    magic, size, entry, ns, nr, ni, flags = HEADER.unpack_from(data)
    if magic != b'PS4BOOT2':
        raise ValueError('Not a derived PS4BOOT2 image')
    start = HEADER.size + ns * 24 + ni * 128 + nr * 32
    if size <= 0 or start + size != len(data):
        raise ValueError('PS4BOOT2 image bounds mismatch')
    return data, start, size


def validate_source(eboot, frame_rate, metadata):
    rate = validate_frame_rate(frame_rate)
    profile = {**recipe(rate), 'recipe_sha256': recipe_sha256(rate), 'applied': False,
               'source_verified': False, 'gameplay_verified': False}
    if rate == 30:
        return profile
    profile.update(verify_source_identity(eboot, metadata, source_sites(rate), feature=FEATURES[rate],
                                         recovery='Select 30 FPS to use the native baseline.'))
    return profile


def apply_prepared(boot, profile):
    """Validate every guard before modifying a single byte in a fresh PS4BOOT2 image."""
    rate = validate_frame_rate(profile['engine_fps'])
    if rate == 30:
        return dict(profile)
    path = Path(boot).resolve()
    if profile.get('source_eboot') and path == Path(profile['source_eboot']).resolve():
        raise ValueError('Timing patches may only modify a derived prepared image')
    data, image_offset, size = prepared_image(path)
    if rate != 60:
        return apply_edits(path, data, image_offset, size, profile)
    if INSTRUCTION_RVA + len(EXPECTED_INSTRUCTION) > size:
        raise ValueError('PS4BOOT2 image bounds mismatch')
    offset = image_offset + INSTRUCTION_RVA
    instruction = bytes(data[offset:offset + len(EXPECTED_INSTRUCTION)])
    if instruction != EXPECTED_INSTRUCTION:
        raise ValueError(f'Experimental 60 FPS instruction signature mismatch at RVA {INSTRUCTION_RVA:#x}')
    target = INSTRUCTION_RVA + len(instruction) + struct.unpack_from('<i', instruction, 2)[0]
    if target != TARGET_GLOBAL_RVA or target + 4 > size:
        raise ValueError('Experimental 60 FPS instruction RIP target mismatch')
    if not profile.get('source_verified') or profile.get('recipe_sha256') != recipe_sha256(60):
        raise ValueError('Experimental 60 FPS source/recipe verification is missing or stale')
    before = hashlib.sha256(data).hexdigest()
    data[offset + 6] = 1  # Only mov dword [RIP+disp32], 2 -> 1; never force the live global.
    after = hashlib.sha256(data).hexdigest()
    path.write_bytes(data)
    return {**profile, 'applied': True, 'changed_bytes': 1,
            'boot_file_offset': hex(offset + 6), 'instruction_before': instruction.hex(),
            'instruction_after': bytes(data[offset:offset + len(instruction)]).hex(),
            'boot_sha256_before': before, 'boot_sha256_after': after}


def apply_edits(path, data, image_offset, size, profile):
    """Every site of the 90 or unlocked recipe must match before any byte changes."""
    rate = profile['engine_fps']
    feature = FEATURES[rate]
    if not profile.get('source_verified') or profile.get('recipe_sha256') != recipe_sha256(rate):
        raise ValueError(f'{feature} source/recipe verification is missing or stale')
    sites = edits(rate)
    for rva, expected, _ in sites:
        if rva + len(expected) > size or bytes(data[image_offset + rva:image_offset + rva + len(expected)]) != expected:
            raise ValueError(f'{feature} instruction signature mismatch at RVA {rva:#x}')
    before = hashlib.sha256(data).hexdigest()
    for rva, _, replacement in sites:
        data[image_offset + rva:image_offset + rva + len(replacement)] = replacement
    path.write_bytes(data)
    return {**profile, 'applied': True,
            'changed_bytes': sum(a != b for _, old, new in sites for a, b in zip(old, new)),
            'boot_sha256_before': before, 'boot_sha256_after': hashlib.sha256(data).hexdigest()}
