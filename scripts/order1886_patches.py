#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Version-checked Order patch recipes, applied only to a derived image copy (#15).

A recipe names the editions it applies to (order1886_editions: every 01.02 release shares
the same code) and the byte edits it makes, each with the original bytes it expects. Nothing
is written until the edition and every expected byte match, a patch always lands in a new
file, and the source image is never modified in place.

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
import order1886_editions as editions
import order1886_frame_rate as timing

# The offsets below address the decoded executable image, which is what the runtime loads:
# the guest executable itself is a SELF container whose image is extracted before use.
IMAGE_KIND = 'decoded-executable'
TIMING = timing.recipe(60)
ASPECT = display.recipe('16:9')

RECIPES = (
    {
        'id': TIMING['id'],
        'title': '60 FPS unlock',
        'description': ('Engine timing unlock from the published 01.02 patch, checked against '
                        'the selected executable\'s instructions. Experimental: the patch warns of '
                        'QTE softlocks in Chapters 6 and 9, so gameplay remains unverified.'),
        'title_ids': editions.TITLE_IDS,
        'guest_executable': 'eboot.bin',
        'image': IMAGE_KIND,
        'edits': ({'offset': timing.INSTRUCTION_RVA,
                   'expected': timing.EXPECTED_INSTRUCTION,
                   'replacement': bytes.fromhex(TIMING['replacement_instruction'])},),
        'experimental': True,
        'warning': timing.WARNING,
    },
    {
        'id': ASPECT['id'],
        'title': '16:9 full-screen framing',
        'description': ('Full-screen 16:9 aspect ratio from the published 01.02 patch, checked '
                        'against the selected executable\'s instructions. Experimental: the patch '
                        'warns of visual issues at native 1080p, so image quality and gameplay '
                        'remain unverified.'),
        'title_ids': editions.TITLE_IDS,
        'guest_executable': 'eboot.bin',
        'image': IMAGE_KIND,
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
    """The editions a recipe applies to."""
    return {'TITLE_IDS': list(recipe['title_ids'])}


def recipe_sha256(recipe):
    """Identity of the edits themselves, independent of description or dict order."""
    canonical = {'id': recipe['id'], 'guest_executable': recipe['guest_executable'],
                 'image': recipe['image'], 'target': target(recipe),
                 'edits': [{'offset': edit['offset'], 'expected': edit['expected'].hex(),
                            'replacement': edit['replacement'].hex()} for edit in recipe['edits']]}
    return hashlib.sha256(json.dumps(canonical, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def identity_error(recipe, metadata):
    """None when the selected game is an edition this recipe applies to."""
    if not isinstance(metadata, dict):
        return f"{recipe['title']} needs the guest build metadata (TITLE_ID)."
    found = metadata.get('TITLE_ID')
    if found not in recipe['title_ids']:
        return (f"{recipe['title']} applies to {', '.join(recipe['title_ids'])}; "
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
    return None


def validate_recipe(recipe, image_bytes, metadata):
    """None when this recipe may be applied to these bytes, or the precise reason it may not.

    The bytes are the guest image the recipe's offsets address. Validation only reads them:
    it checks the edition, the offset bounds and the expected bytes at every edit.
    """
    error = identity_error(recipe, metadata)
    if error:
        return error
    if not isinstance(image_bytes, (bytes, bytearray, memoryview)):
        return f"{recipe['title']} needs the guest image bytes, not text."
    size = len(image_bytes)
    if not size:
        return f"{recipe['title']} received an empty guest image."
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
    """The loaded image a recipe's offsets (RVAs) address, decoded from the guest executable."""
    try:
        elf, _, ph = prepare.parse_self(guest_bytes)[:3]
        loads = [p for p in ph if p['type'] in (1, 0x61000010)]
        image = bytearray(max(p['vaddr'] + p['memsz'] for p in loads))
        for p in loads:
            image[p['vaddr']:p['vaddr'] + p['filesz']] = prepare.span(elf, p['offset'], p['filesz'])
        return bytes(image)
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
    error = validate_recipe(recipe, image_bytes,
                            {'TITLE_ID': recipe['title_ids'][0]} if metadata is None else metadata)
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
    read. `metadata` defaults to the first edition the recipe declares; pass the selected game's own
    metadata to check it here instead of in the caller.
    """
    source, destination = Path(source_path), Path(destination_path)
    if not source.is_file():
        raise ValueError(f'The patch source image is missing: {source}')
    if source.resolve() == destination.resolve():
        raise ValueError('Patch a copy: a derived image is written to a new path, never in place.')
    result = apply_recipe_bytes(recipe, source.read_bytes(), destination, metadata)
    return {**result, 'source': str(source)}

BUILTIN_IDS = tuple(item['id'] for item in RECIPES)


def patch_fingerprint(recipes):
    """The selection, in the form preparation hashes: order-independent, id plus recipe."""
    return sorted({'id': item['id'], 'recipe_sha256': recipe_sha256(item)} for item in recipes)

def validate_selection(identifiers):
    """A saved selection must name catalogued, non-built-in recipes; order is preserved."""
    if not isinstance(identifiers, list) or not all(isinstance(name, str) for name in identifiers):
        raise ValueError('Selected patches must be a list of catalogued ids')
    known = {item['id'] for item in RECIPES}
    for name in identifiers:
        if name not in known:
            raise ValueError(f'Unknown patch id: {name}')
        if name in BUILTIN_IDS:
            raise ValueError(f'{name}: this recipe is configured by the game frame rate or framing '
                             'setting, not by a patch selection.')
    return list(dict.fromkeys(identifiers))

def select(identifiers, metadata):
    """The recipes a preparation asked for, or an error naming the one that cannot apply.

    The two built-in recipes are refused here on purpose: timing and aspect are applied by
    their own preparation profiles, which validate them against the guest executable and
    record them in prepared.json. Accepting the same recipe twice would mean two mechanisms
    editing the same instruction.
    """
    chosen = []
    for identifier in identifiers:
        item = recipe(identifier)
        if item['id'] in BUILTIN_IDS:
            raise ValueError(f"{identifier}: this recipe is applied by its own preparation "
                             "profile (game frame rate or framing), not as a catalogue patch.")
        error = identity_error(item, metadata)
        if error:
            raise ValueError(f'{identifier}: {error}')
        chosen.append(item)
    return tuple(chosen)


def apply_to_prepared(boot_path, recipes, metadata):
    """Apply catalogued recipes inside an already-derived prepared container.

    The prepared image is our own artifact, so editing it in place is allowed — unlike the
    guest executable, which this function never receives. Identity comes from two places:
    the caller's metadata must match each recipe, and every edit's `expected` bytes must be
    present at the offset the recipe names. The container is bound to the guest executable
    by the preparation fingerprint, which already hashes eboot.bin.
    """
    path = Path(boot_path).resolve()
    if not recipes:
        return []
    data = bytearray(path.read_bytes())
    if len(data) < timing.HEADER.size:
        raise ValueError('Truncated PS4BOOT2 header')
    magic, size, entry, ns, nr, ni, flags = timing.HEADER.unpack_from(data)
    if magic != b'PS4BOOT2':
        raise ValueError('Not a derived PS4BOOT2 image')
    start = timing.HEADER.size + ns * 24 + ni * 128 + nr * 32
    if size <= 0 or start + size != len(data):
        raise ValueError('PS4BOOT2 image bounds mismatch')
    applied = []
    for item in recipes:
        error = identity_error(item, metadata)
        if error:
            raise ValueError(f"{item['id']}: {error}")
        edits = []
        for edit in item['edits']:
            offset = edit['offset']
            end = offset + len(edit['expected'])
            if offset < 0 or end > size:
                raise ValueError(f"{item['id']}: edit at {hex(offset)} is outside the prepared image")
            target_offset = start + offset
            current = bytes(data[target_offset:target_offset + len(edit['expected'])])
            if current != edit['expected']:
                raise ValueError(f"{item['id']}: expected bytes are absent at {hex(offset)}; "
                                 "the prepared image is not the build this recipe was verified against")
            if len(edit['replacement']) != len(edit['expected']):
                raise ValueError(f"{item['id']}: an edit must keep the instruction length")
            edits.append({'offset': hex(offset), 'before': current.hex(),
                          'after': bytes(edit['replacement']).hex()})
            data[target_offset:target_offset + len(edit['replacement'])] = edit['replacement']
        applied.append({'id': item['id'], 'recipe_sha256': recipe_sha256(item), 'edits': edits})
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_bytes(bytes(data))
    temporary.replace(path)
    return applied