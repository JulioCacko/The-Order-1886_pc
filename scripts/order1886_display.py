"""Byte-checked full-screen aspect patch, confined to derived preparation output."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

import order1886_frame_rate as timing

INSTRUCTION_RVA = 0x44ce86
EXPECTED_INSTRUCTION = bytes.fromhex('c78518fcffff9a991940')
REPLACEMENT_INSTRUCTION = bytes.fromhex('c78518fcffff398ee33f')
WARNING = ('Full-screen 16:9 is experimental. The source patch warns of visual issues at native '
           '1080p; image quality and gameplay require verification. Select Original to recover.')


def validate_aspect(value):
    if value not in ('original', '16:9'):
        raise ValueError('Invalid aspect ratio; choose original or 16:9')
    return value


def recipe(aspect):
    aspect = validate_aspect(aspect)
    result = dict(id='order1886-original-aspect-v1' if aspect == 'original' else 'order1886-a8ce-16x9-v1',
                  aspect_ratio=aspect, experimental=aspect != 'original')
    if aspect == '16:9':
        result.update(title_ids=list(timing.editions.TITLE_IDS), instruction_rva=hex(INSTRUCTION_RVA),
                      expected_instruction=EXPECTED_INSTRUCTION.hex(),
                      replacement_instruction=REPLACEMENT_INSTRUCTION.hex(),
                      public_patch_entry='16:9 Aspect Ratio (Full Screen)', public_patch_app_ver='01.02',
                      public_patch_address='0x0084ce8c', public_patch_file='patches/TheOrder1886-Orbis.xml',
                      public_patch_xml_sha256_lf=timing.PUBLIC_PATCH_XML_SHA256,
                      author='illusion; instruction verification by this project',
                      render_size_policy='native; no resolution patch', warning=WARNING)
    return result


def recipe_sha256(aspect):
    return hashlib.sha256(json.dumps(recipe(aspect), sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def validate_source(eboot, aspect, metadata):
    profile = {**recipe(aspect), 'recipe_sha256': recipe_sha256(aspect), 'applied': False,
               'source_verified': False, 'gameplay_verified': False}
    if aspect == 'original':
        return profile
    # Reuse the edition and instruction checks, without applying the independent timing patch.
    profile.update(timing.verify_source_identity(eboot, metadata, [(INSTRUCTION_RVA, EXPECTED_INSTRUCTION)],
                                                feature='Full-screen 16:9',
                                                recovery='Select Original cinematic aspect to recover.'))
    return profile


def apply_prepared(boot, profile):
    aspect = validate_aspect(profile['aspect_ratio'])
    if aspect == 'original':
        return dict(profile)
    path = Path(boot).resolve()
    if profile.get('source_eboot') and path == Path(profile['source_eboot']).resolve():
        raise ValueError('Aspect patches may only modify a derived prepared image')
    data, start, size = timing.prepared_image(path)
    if INSTRUCTION_RVA + len(EXPECTED_INSTRUCTION) > size:
        raise ValueError('PS4BOOT2 image bounds mismatch')
    offset = start + INSTRUCTION_RVA
    instruction = bytes(data[offset:offset + len(EXPECTED_INSTRUCTION)])
    if instruction != EXPECTED_INSTRUCTION:
        raise ValueError(f'Full-screen aspect instruction signature mismatch at RVA {INSTRUCTION_RVA:#x}')
    if not profile.get('source_verified') or profile.get('recipe_sha256') != recipe_sha256('16:9'):
        raise ValueError('Full-screen aspect source/recipe verification is missing or stale')
    before = hashlib.sha256(data).hexdigest()
    data[offset + 6:offset + 10] = REPLACEMENT_INSTRUCTION[6:10]
    after = hashlib.sha256(data).hexdigest()
    path.write_bytes(data)
    return {**profile, 'applied': True, 'changed_bytes': 4, 'boot_file_offset': hex(offset + 6),
            'instruction_before': instruction.hex(), 'instruction_after': REPLACEMENT_INSTRUCTION.hex(),
            'boot_sha256_before': before, 'boot_sha256_after': after}
