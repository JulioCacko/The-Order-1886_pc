#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Version-checked Order patch recipes, applied only to a derived image copy (#15).

A recipe names the exact guest build it was verified against (title id, APP_VER, VERSION),
the SHA256 of the selected game's executable and of the decoded image its offsets address,
and the byte edits it makes. Nothing is written until every guard passes, a patch always
lands in a new file, and the source image is never modified in place.

This module deliberately carries only recipes that were verified against a real
executable, so a Cheats page can list what exists instead of promising what does not.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import sys

if str(Path(__file__).resolve().parent) not in sys.path:  # also importable as scripts.*
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare
import order1886_display as display
import order1886_frame_rate as timing

# The offsets below address the decoded executable image, which is what the runtime loads:
# the guest executable itself is a SELF container whose image is extracted before use.
IMAGE_KIND = 'decoded-executable'
TARGET_FIELDS = ('TITLE_ID', 'APP_VER', 'VERSION')
TIMING = timing.recipe(60)
ASPECT = display.recipe('16:9')

RECIPES = (
    {
        'id': TIMING['id'],
        'title': '60 FPS unlock',
        'description': ('Engine timing unlock verified against the CUSA00076 executable. '
                        'Experimental: the published patch warns of QTE softlocks in Chapters 6 '
                        'and 9, so gameplay remains unverified.'),
        'title_id': timing.EXPECTED_METADATA['TITLE_ID'],
        'app_ver': timing.EXPECTED_METADATA['APP_VER'],
        'version': timing.EXPECTED_METADATA['VERSION'],
        'guest_executable': 'eboot.bin',
        'guest_sha256': timing.EXPECTED_SELF_SHA256,
        'image': IMAGE_KIND,
        'image_sha256': timing.EXPECTED_ELF_SHA256,
        'edits': ({'offset': timing.INSTRUCTION_RVA,
                   'expected': timing.EXPECTED_INSTRUCTION,
                   'replacement': bytes.fromhex(TIMING['replacement_instruction'])},),
        'experimental': True,
        'warning': timing.WARNING,
    },
    {
        'id': ASPECT['id'],
        'title': '16:9 full-screen framing',
        'description': ('Full-screen 16:9 aspect ratio verified against the CUSA00076 executable. '
                        'Experimental: the source patch warns of visual issues at native 1080p, '
                        'so image quality and gameplay remain unverified.'),
        'title_id': timing.EXPECTED_METADATA['TITLE_ID'],
        'app_ver': timing.EXPECTED_METADATA['APP_VER'],
        'version': timing.EXPECTED_METADATA['VERSION'],
        'guest_executable': 'eboot.bin',
        'guest_sha256': timing.EXPECTED_SELF_SHA256,
        'image': IMAGE_KIND,
        'image_sha256': timing.EXPECTED_ELF_SHA256,
        'edits': ({'offset': display.INSTRUCTION_RVA,
                   'expected': display.EXPECTED_INSTRUCTION,
                   'replacement': display.REPLACEMENT_INSTRUCTION},),
        'experimental': True,
        'warning': display.WARNING,
    },
)


def recipe(identifier):
    """The catalogued recipe with this id; an unknown id is an error, not a default."""
    for item in RECIPES:
        if item['id'] == identifier:
            return item
    raise ValueError(f'Unknown patch recipe: {identifier}')


def target(recipe):
    """The guest build metadata a recipe applies to."""
    return dict(zip(TARGET_FIELDS, (recipe['title_id'], recipe['app_ver'], recipe['version'])))


def recipe_sha256(recipe):
    """Identity of the edits themselves, independent of description or dict order."""
    canonical = {'id': recipe['id'], 'guest_executable': recipe['guest_executable'],
                 'guest_sha256': recipe['guest_sha256'], 'image': recipe['image'],
                 'image_sha256': recipe['image_sha256'], 'target': target(recipe),
                 'edits': [{'offset': edit['offset'], 'expected': edit['expected'].hex(),
                            'replacement': edit['replacement'].hex()} for edit in recipe['edits']]}
    return hashlib.sha256(json.dumps(canonical, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def identity_error(recipe, metadata):
    """None when the selected game reports the build this recipe was verified against."""
    if not isinstance(metadata, dict):
        return f"{recipe['title']} needs the guest build metadata (TITLE_ID, APP_VER, VERSION)."
    expected = target(recipe)
    for name in TARGET_FIELDS:
        found = metadata.get(name)
        if found != expected[name]:
            return (f"{recipe['title']} applies to {name} {expected[name]}; "
                    f"the selected game reports {found if found else 'nothing'}.")
    return None


def validate_guest(recipe, guest_bytes, metadata):
    """Check the selected executable itself, before its image is decoded."""
    error = identity_error(recipe, metadata)
    if error:
        return error
    if not isinstance(guest_bytes, (bytes, bytearray, memoryview)):
        return f"{recipe['title']} needs the {recipe['guest_executable']} bytes, not text."
    if not len(guest_bytes):
        return f"{recipe['title']} received an empty {recipe['guest_executable']}."
    digest = hashlib.sha256(guest_bytes).hexdigest()
    if digest != recipe['guest_sha256']:
        return (f"{recipe['title']} was verified against {recipe['guest_executable']} SHA256 "
                f"{recipe['guest_sha256']}; the selected game's file is {digest}.")
    return None


def validate_recipe(recipe, image_bytes, metadata):
    """None when this recipe may be applied to these bytes, or the precise reason it may not.

    The bytes are the guest image the recipe's offsets address. Validation only reads them:
    it checks the build identity, the verified image hash, the offset bounds and the expected
    bytes at every edit.
    """
    error = identity_error(recipe, metadata)
    if error:
        return error
    if not isinstance(image_bytes, (bytes, bytearray, memoryview)):
        return f"{recipe['title']} needs the guest image bytes, not text."
    size = len(image_bytes)
    if not size:
        return f"{recipe['title']} received an empty guest image."
    digest = hashlib.sha256(image_bytes).hexdigest()
    if digest != recipe['image_sha256']:
        return (f"{recipe['title']} was verified against guest image SHA256 "
                f"{recipe['image_sha256']}; the supplied image is {digest}.")
    for edit in recipe['edits']:
        offset, expected, replacement = edit['offset'], edit['expected'], edit['replacement']
        if (type(offset) is not int or offset < 0 or not expected
                or len(expected) != len(replacement)):
            return f"{recipe['title']} declares a malformed edit at offset {offset!r}."
        if offset + len(expected) > size:
            return (f"{recipe['title']} edits the image at offset {offset:#x}, past the end of the "
                    f"{size} byte guest image.")
        found = bytes(image_bytes[offset:offset + len(expected)])
        if found != expected:
            return (f"{recipe['title']} expects {expected.hex()} at offset {offset:#x}; the guest "
                    f"image holds {found.hex()}. Restore the original executable.")
    return None


def decode(recipe, guest_bytes):
    """The guest image a recipe's offsets address, decoded from the guest executable."""
    try:
        return bytes(prepare.parse_self(guest_bytes)[0])
    except (ValueError, struct.error) as exc:
        raise ValueError(f"{recipe['title']} cannot address this executable: {exc}") from exc


def applicability(recipe, guest_bytes, metadata):
    """None when the selected game can take this recipe, or the reason it cannot."""
    error = validate_guest(recipe, guest_bytes, metadata)
    if error:
        return error
    try:
        image = decode(recipe, guest_bytes)
    except ValueError as exc:
        return str(exc)
    return validate_recipe(recipe, image, metadata)


def describe(recipe, reason=''):
    """One recipe as the launcher shows it; a reason makes it unavailable."""
    return {'id': recipe['id'], 'title': recipe['title'], 'description': recipe['description'],
            'target': target(recipe), 'guest_executable': recipe['guest_executable'],
            'recipe_sha256': recipe_sha256(recipe),
            'experimental': bool(recipe.get('experimental')), 'warning': recipe.get('warning', ''),
            'applicable': not reason, 'reason': reason}


def catalogue(guest_bytes, metadata):
    """Every catalogued recipe with its applicability for one selected game; writes nothing."""
    return [describe(item, applicability(item, guest_bytes, metadata) or '') for item in RECIPES]


def apply_recipe_bytes(recipe, image_bytes, destination_path, metadata=None):
    """Write a patched copy of these image bytes to a new path, and only after validation."""
    error = validate_recipe(recipe, image_bytes, target(recipe) if metadata is None else metadata)
    if error:
        raise ValueError(error)
    destination = Path(destination_path)
    patched = bytearray(image_bytes)
    edits = []
    for edit in recipe['edits']:
        start, end = edit['offset'], edit['offset'] + len(edit['replacement'])
        edits.append({'offset': hex(start), 'before': bytes(patched[start:end]).hex(),
                      'after': edit['replacement'].hex()})
        patched[start:end] = edit['replacement']
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + '.tmp')
    temporary.write_bytes(bytes(patched))
    temporary.replace(destination)
    return {'applied': True, 'destination': str(destination), 'recipe_id': recipe['id'],
            'recipe_sha256': recipe_sha256(recipe), 'target': target(recipe),
            'source_sha256': hashlib.sha256(image_bytes).hexdigest(),
            'image_sha256': hashlib.sha256(bytes(patched)).hexdigest(),
            'changed_bytes': sum(len(edit['replacement']) for edit in recipe['edits']),
            'edits': edits, 'gameplay_verified': False, 'warning': recipe.get('warning', '')}


def apply_recipe(recipe, source_path, destination_path, metadata=None):
    """Copy an image to a new path and apply the edits to the copy, never in place.

    The source is read once and never written, so an original or prepared image can only be
    read. `metadata` defaults to the build the recipe declares; pass the selected game's own
    metadata to check it here instead of in the caller.
    """
    source, destination = Path(source_path), Path(destination_path)
    if not source.is_file():
        raise ValueError(f'The patch source image is missing: {source}')
    if source.resolve() == destination.resolve():
        raise ValueError('Patch a copy: a derived image is written to a new path, never in place.')
    result = apply_recipe_bytes(recipe, source.read_bytes(), destination, metadata)
    return {**result, 'source': str(source)}
