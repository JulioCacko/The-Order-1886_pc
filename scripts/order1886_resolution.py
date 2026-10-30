"""Byte-checked render-size patch, confined to derived preparation output (#3).

The engine already picks its display size from three hard-coded modes (1280x720, 1920x1080,
3840x2160), selected by flag bits that retail never sets. The published 900p/720p patch flips
the 720p test so that branch always runs, then rewrites its immediates; this recipe does the
same with any width. The branch stores the size twice (output size and viewport), and both are
rewritten, so the game sizes every screen target itself. The aspect setting (2.4:1 or 16:9)
still decides how much of that frame the scene covers. One more size is fixed: the renderer's
base scene size (1920x800, stored in the device at +0x738/+0x73c), which sizes scene depth, so
it is set to the scene the aspect leaves: width/2.4 for Original, the full frame for 16:9.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

import order1886_frame_rate as timing

NATIVE_WIDTH = 1920
MIN_WIDTH, MAX_WIDTH = 1280, 4880
BRANCH_RVA = 0x44cef5
EXPECTED_BRANCH = bytes.fromhex('7441')  # je: skip the 720p mode unless its flag bit is set
REPLACEMENT_BRANCH = bytes.fromhex('7541')
# mov dword [rbp-disp], imm32 stores of the 720p mode: output width/height, viewport width/height.
STORES = ((0x44cef7, bytes.fromhex('c78584fcffff00050000')), (0x44cf01, bytes.fromhex('c78588fcffffd0020000')),
          (0x44cf1f, bytes.fromhex('c785d8fbffff00050000')), (0x44cf29, bytes.fromhex('c785dcfbffffd0020000')))
# mov edi, 1920; mov esi, 800 before the renderer device is created.
SCENE = ((0x839c54, bytes.fromhex('bf80070000')), (0x839c59, bytes.fromhex('be20030000')))
# Render targets live in a GPU stack ("GpuStack.RenderTargets", built at 0xca5dc0) with fixed
# partitions sized for 1920x800: A (main, 162 MiB) then B (19 MiB) and C (73 MiB), each shared by
# sub-stacks used at different times. A larger frame overflows A into B and C, so live targets
# overlap. Each partition scales with the scene's pixel count; the GPU heap the stack is carved
# from (allocate, map, record, release) grows by the same amount. Immediates are signed 32-bit,
# which caps the width: 4880 at Original, 4192 at 16:9.
STACK = {'a': 0xa200000, 'b': 0x1300000, 'c': 0x4900000}
STACK_SITES = (  # (rva, original bytes, immediate offset, value)
    (0xca6030, bytes.fromhex('b80000e00f'), 1, 'total'),
    (0xca5e87, bytes.fromhex('488d880000200a'), 3, 'a'),
    (0xca5e92, bytes.fromhex('488d900000500b'), 3, 'a+b'),
    (0xca5ea5, bytes.fromhex('48c743600000200a'), 4, 'a'),
    (0xca5eb5, bytes.fromhex('48c7437800009004'), 4, 'c'),
    *((rva, bytes.fromhex(f'48c783{disp}000000009004'), 7, 'c') for rva, disp in
      ((0xca5ecb, '9000'), (0xca5ee4, 'a800'), (0xca5f7a, '3801'))),
    *((rva, bytes.fromhex(f'48c783{disp}000000003001'), 7, 'b') for rva, disp in
      ((0xca5efd, 'c000'), (0xca5f16, 'd800'), (0xca5f2f, 'f000'), (0xca5f48, '0801'), (0xca5f61, '2001'))))
HEAP_SIZE = 0x28e00000
HEAP_SITES = ((0x298d0b, bytes.fromhex('ba0000e028'), 1), (0x298d33, bytes.fromhex('be0000e028'), 1),
              (0x298d63, bytes.fromhex('48c705c29741010000e028'), 7), (0x2997cc, bytes.fromhex('be0000e028'), 1))
RETAIL_DMEM_MB = 5056
WARNING = ('Render sizes other than the original are experimental: image quality, memory use and '
           'gameplay require verification. Select Original to recover.')


def validate_width(width):
    width = int(width)
    if width == NATIVE_WIDTH:
        return width
    if not MIN_WIDTH <= width <= MAX_WIDTH or width % 16:
        raise ValueError(f'Render width must be {NATIVE_WIDTH} (original) or a multiple of 16 '
                         f'from {MIN_WIDTH} to {MAX_WIDTH}')
    return width


def size(width):
    """The 16:9 frame the game renders into; the aspect setting letterboxes inside it."""
    width = validate_width(width)
    return width, round(width * 9 / 16 / 8) * 8


def scene_size(width, aspect):
    """The scene inside that frame: letterboxed 2.4:1 for Original, the whole frame for 16:9."""
    w, h = size(width)
    return (w, h) if aspect == '16:9' else (w, round(w / 2.4))


def stack(width, aspect='original'):
    """Partition sizes for this scene, in whole MiB like the retail ones."""
    w, h = scene_size(width, aspect)
    ratio = max(1.0, w * h / (1920 * 800))
    size = {key: -(-int(value * ratio) // 0x100000) * 0x100000 for key, value in STACK.items()}
    return {**size, 'a+b': size['a'] + size['b'], 'total': size['a'] + size['b'] + size['c']}


def growth(width, aspect='original'):
    """Bytes the GPU heap, and so guest direct memory, grows by: whole 2 MiB pages."""
    return -(-(stack(width, aspect)['total'] - sum(STACK.values())) // 0x200000) * 0x200000


def dmem_mb(width, aspect='original'):
    return RETAIL_DMEM_MB + -(-growth(width, aspect) // (1 << 20))


def recipe(width, aspect='original'):
    width = validate_width(width)
    if (width != NATIVE_WIDTH and (HEAP_SIZE + growth(width, aspect) >= 1 << 31
                                   or stack(width, aspect)['a+b'] >= 1 << 31)):
        raise ValueError(f'Render width {width} is too large for the {aspect} aspect')
    if width == NATIVE_WIDTH:
        return dict(id='order1886-original-resolution-v1', render_width=width, experimental=False)
    w, h = size(width)
    return dict(id='order1886-resolution-v1', render_width=w, render_height=h, aspect_ratio=aspect,
                scene_size=list(scene_size(width, aspect)), stack_total=hex(stack(width, aspect)['total']),
                heap_size=hex(HEAP_SIZE + growth(width, aspect)), dmem_mb=dmem_mb(width, aspect),
                experimental=True,
                title_ids=list(timing.editions.TITLE_IDS), branch_rva=hex(BRANCH_RVA),
                store_rvas=[hex(rva) for rva, _ in STORES + SCENE],
                public_patch_entry='Resolution Patch', public_patch_app_ver='01.02',
                public_patch_file='patches/TheOrder1886-Orbis.xml',
                public_patch_xml_sha256_lf=timing.PUBLIC_PATCH_XML_SHA256,
                author='illusion; viewport stores and verification by this project', warning=WARNING)


def recipe_sha256(width, aspect='original'):
    return hashlib.sha256(json.dumps(recipe(width, aspect), sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def sites():
    return [(BRANCH_RVA, EXPECTED_BRANCH), *STORES, *SCENE, *((rva, expected) for rva, expected, *_ in STACK_SITES),
            *((rva, expected) for rva, expected, _ in HEAP_SITES)]


def validate_source(eboot, width, metadata, aspect='original'):
    profile = {**recipe(width, aspect), 'recipe_sha256': recipe_sha256(width, aspect), 'applied': False,
               'source_verified': False, 'gameplay_verified': False}
    if profile['render_width'] == NATIVE_WIDTH:
        return profile
    profile.update(timing.verify_source_identity(eboot, metadata, sites(), feature='Render size',
                                                recovery='Select the original render size to recover.'))
    return profile


def apply_prepared(boot, profile):
    width = validate_width(profile['render_width'])
    if width == NATIVE_WIDTH:
        return dict(profile)
    path = Path(boot).resolve()
    if profile.get('source_eboot') and path == Path(profile['source_eboot']).resolve():
        raise ValueError('Resolution patches may only modify a derived prepared image')
    data, start, image_size = timing.prepared_image(path)
    for rva, expected in sites():
        if rva + len(expected) > image_size:
            raise ValueError('PS4BOOT2 image bounds mismatch')
        if bytes(data[start + rva:start + rva + len(expected)]) != expected:
            raise ValueError(f'Render size instruction signature mismatch at RVA {rva:#x}')
    aspect = profile['aspect_ratio']
    if not profile.get('source_verified') or profile.get('recipe_sha256') != recipe_sha256(width, aspect):
        raise ValueError('Render size source/recipe verification is missing or stale')
    before = hashlib.sha256(data).hexdigest()
    data[start + BRANCH_RVA:start + BRANCH_RVA + 2] = REPLACEMENT_BRANCH
    w, h = size(width)
    for (rva, _), value in zip(STORES, (w, h, w, h)):
        data[start + rva + 6:start + rva + 10] = struct.pack('<I', value)
    for (rva, _), value in zip(SCENE, scene_size(width, aspect)):
        data[start + rva + 1:start + rva + 5] = struct.pack('<I', value)
    sizes = stack(width, aspect)
    for rva, _, at, key in STACK_SITES:
        data[start + rva + at:start + rva + at + 4] = struct.pack('<I', sizes[key])
    for rva, _, at in HEAP_SITES:
        data[start + rva + at:start + rva + at + 4] = struct.pack('<I', HEAP_SIZE + growth(width, aspect))
    path.write_bytes(data)
    return {**profile, 'applied': True, 'boot_sha256_before': before,
            'boot_sha256_after': hashlib.sha256(data).hexdigest()}
