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
# UI fixes, applied to every prepared image whatever the aspect (docs/verification/
# 2026-11-16-ui-band-and-glyph-cache.md). (rva, original bytes, replacement).
#
# 1. The Flash UI (Iggy) is authored for the 2.4:1 band: a 1920x800 stage. The game hands every
#    player the scene size, so with the bars removed the stage is laid out against 1080 rows:
#    menus grow ~5%, subtitles never show and interaction/QTE glyphs vanish. The players now
#    always get the band (width, width*5/12) and GDraw's tile origin centres it in the frame;
#    with the bars on, both are what the game computed anyway (height unchanged, origin 0).
#    The world-to-stage projection of prompts subtracts the same offset, so a glyph stays on
#    the object it marks. The origin needs more room than its site has: it lives in the 4K
#    branch of the display-mode switch, which no retail flag selects and which is fenced off.
# 2. New font-cache glyphs are copied in by a compute shader through a view of the texture
#    with another format. The runtime keeps such a view as a separate aliased image and the
#    sampled texture saw the new glyph late or never ("Eigan." for "Sigan."). Both views keep
#    the texture's own format now, so the copy lands in the image that is sampled.
UI_FIX_VERSION = 1
UI_SITES = tuple((rva, bytes.fromhex(old), bytes.fromhex(new)) for rva, old, new in (
    # IggyPlayerSetDisplaySize callers: height = width * 5 / 12
    (0x838f09, '448ba0c82d01004531ff4989dd662e0f1f840000000000',
               '4569e656d5000041c1ec114531ff4989dd660f1f440000'),
    (0x83944f, '8b90c82d010031ff660f1f840000000000', '4169d456d50000c1ea1131ff0f1f440000'),
    # UI draw: tile origin y = (scene height - band height) / 2, computed in the fenced-off branch
    (0x83a08a, '48c7814007000000000000', 'e8f12ec1ff660f1f440000'),
    (0x44cf7e, '7446', 'eb46'),
    (0x44cf80, 'c78584fcffff000f0000c78588fcffff70080000c785d0fbffff00000000c785d4fbffff00000000c785',
               '488b05c94525016990c02d010056d50000c1ea118b80c82d010029d0d1f848c1e02048898140070000c3'),
    # world-to-stage projection: y relative to the band, normalised by the band height
    (0x7a0873, '488b83c83201004885c97807c4e1fa2ad9eb164889ca48d1ea', '488b83c83201004869d156d5000048c1ea11c4e1fa2ad9eb10'),
    (0x7a08b1, '4885c07807c4e1fa2ae0eb164889c148d1e94883e001', '4829d048d1e8c4e1da2ae0c5fa5cc4c4e1da2ae2eb0c'),
    # font-cache glyph upload: keep the texture's own format on both views
    (0x87e4c7, 'e804f178ff', '0f1f440000'),
    (0x87e5c8, 'e803f078ff', '0f1f440000')))
WARNING = ('Full-screen 16:9 is experimental. The source patch warns of visual issues at native '
           '1080p; image quality and gameplay require verification. Select Original to recover.')


def validate_aspect(value):
    if value not in ('original', '16:9'):
        raise ValueError('Invalid aspect ratio; choose original or 16:9')
    return value


def recipe(aspect):
    aspect = validate_aspect(aspect)
    result = dict(id='order1886-original-aspect-v1' if aspect == 'original' else 'order1886-a8ce-16x9-v1',
                  aspect_ratio=aspect, experimental=aspect != 'original', ui_fix_version=UI_FIX_VERSION)
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
        # A dump with the published 16:9 patch baked in must still show Original framing (#3).
        if timing.source_instruction(eboot, INSTRUCTION_RVA, len(REPLACEMENT_INSTRUCTION)) == REPLACEMENT_INSTRUCTION:
            profile['source_prepatched'] = [hex(INSTRUCTION_RVA)]
        return profile
    # Reuse the edition and instruction checks, without applying the independent timing patch.
    profile.update(timing.verify_source_identity(eboot, metadata, [(INSTRUCTION_RVA, EXPECTED_INSTRUCTION)],
                                                feature='Full-screen 16:9',
                                                recovery='Select Original cinematic aspect to recover.',
                                                prepatched=[(INSTRUCTION_RVA, REPLACEMENT_INSTRUCTION)]))
    return profile


def apply_ui_fix(path):
    """Apply UI_SITES to a derived image when every site holds its original bytes.

    Never fails a preparation: an executable whose bytes differ keeps its own UI code and the
    result says so ('applied': False, 'reason')."""
    data, start, size = timing.prepared_image(path)
    found = []
    for rva, old, new in UI_SITES:
        if rva + len(old) > size:
            return {'version': UI_FIX_VERSION, 'applied': False, 'reason': 'image bounds mismatch'}
        found.append(bytes(data[start + rva:start + rva + len(old)]))
    if all(have[:len(new)] == new for have, (_, _, new) in zip(found, UI_SITES)):
        return {'version': UI_FIX_VERSION, 'applied': True, 'changed_sites': 0}
    mismatch = [hex(rva) for have, (rva, old, _) in zip(found, UI_SITES) if have != old]
    if mismatch:
        return {'version': UI_FIX_VERSION, 'applied': False,
                'reason': 'instruction signature mismatch at RVA ' + ', '.join(mismatch)}
    for rva, _, new in UI_SITES:
        data[start + rva:start + rva + len(new)] = new
    Path(path).write_bytes(data)
    return {'version': UI_FIX_VERSION, 'applied': True, 'changed_sites': len(UI_SITES)}


def apply_prepared(boot, profile):
    aspect = validate_aspect(profile['aspect_ratio'])
    prepatched = hex(INSTRUCTION_RVA) in profile.get('source_prepatched', ())
    path = Path(boot).resolve()
    if profile.get('source_eboot') and path == Path(profile['source_eboot']).resolve():
        raise ValueError('Aspect patches may only modify a derived prepared image')
    profile = {**profile, 'ui_fix': apply_ui_fix(path)}
    if aspect == 'original' and not prepatched:
        return profile
    data, start, size = timing.prepared_image(path)
    if INSTRUCTION_RVA + len(EXPECTED_INSTRUCTION) > size:
        raise ValueError('PS4BOOT2 image bounds mismatch')
    offset = start + INSTRUCTION_RVA
    instruction = bytes(data[offset:offset + len(EXPECTED_INSTRUCTION)])
    if aspect == 'original':
        accepted, wanted = (REPLACEMENT_INSTRUCTION,), EXPECTED_INSTRUCTION
    else:
        accepted = (EXPECTED_INSTRUCTION, REPLACEMENT_INSTRUCTION) if prepatched else (EXPECTED_INSTRUCTION,)
        wanted = REPLACEMENT_INSTRUCTION
    if instruction not in accepted:
        raise ValueError(f'Full-screen aspect instruction signature mismatch at RVA {INSTRUCTION_RVA:#x}')
    if aspect == '16:9' and (not profile.get('source_verified') or profile.get('recipe_sha256') != recipe_sha256('16:9')):
        raise ValueError('Full-screen aspect source/recipe verification is missing or stale')
    before = hashlib.sha256(data).hexdigest()
    changed = sum(a != b for a, b in zip(instruction, wanted))
    data[offset + 6:offset + 10] = wanted[6:10]
    after = hashlib.sha256(data).hexdigest()
    if changed:
        path.write_bytes(data)
    return {**profile, 'applied': True, 'changed_bytes': changed, 'boot_file_offset': hex(offset + 6),
            'instruction_before': instruction.hex(), 'instruction_after': wanted.hex(),
            'boot_sha256_before': before, 'boot_sha256_after': after}
