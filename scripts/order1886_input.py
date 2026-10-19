# SPDX-License-Identifier: GPL-2.0-or-later
"""Validated digital-button mappings for runtime_pad.c's existing input parser."""
import json
import os
import subprocess

BUTTONS = {'cross': 'Cross', 'circle': 'Circle', 'square': 'Square', 'triangle': 'Triangle',
           'l1': 'L1', 'r1': 'R1', 'l2': 'L2', 'r2': 'R2', 'l3': 'L3', 'r3': 'R3',
           'options': 'Options', 'touchpad_left': 'Touchpad left click',
           'touchpad_right': 'Touchpad right click', 'up': 'D-pad up', 'down': 'D-pad down',
           'left': 'D-pad left', 'right': 'D-pad right'}
UNBOUND = '__unbound__'


def source_reason(name, kind=None):
    if name != name.strip() or any(c in name for c in '\r\n\0') or (kind == 'controller' and ',' in name):
        return 'The native mapping format cannot represent this input name.'
    return ''


def validate(mapping, kind, catalog=None):
    if kind not in ('keyboard', 'controller') or not isinstance(mapping, dict):
        raise ValueError('Input bindings must be a keyboard or controller mapping object.')
    for button, name in mapping.items():
        if (button not in BUTTONS or not isinstance(name, str) or not 0 < len(name) <= 80
                or source_reason(name, kind)):
            raise ValueError('Input binding has an unsupported button or input name.')
        if catalog is not None and name == UNBOUND and catalog.get('unbinding') is not True:
            raise ValueError('The selected native runtime cannot remove a digital binding.')
        if catalog is not None and name != UNBOUND and name not in catalog[kind + '_sources']:
            raise ValueError('Input binding is not supported by the selected native runtime: ' + name)


def encode(mapping, kind, catalog=None):
    validate(mapping, kind, catalog)
    if mapping and catalog is None:
        raise ValueError('Custom input bindings require a verified native input inventory.')
    entries = []
    for button in BUTTONS:
        if button not in mapping:
            continue
        name = mapping[button]
        if name == UNBOUND:
            name = 'none'
        elif kind == 'keyboard':
            code = catalog.get('keyboard_scancodes', {}).get(name)
            if type(code) is not int or not 0 < code < 512:
                raise ValueError('Keyboard input has no verified native scancode: ' + name)
            name = 'scancode:' + str(code)
        elif ',' in name:
            raise ValueError('The native mapping format cannot represent this controller input.')
        entries.append(button + '=' + name)
    spec = ','.join(entries)
    if len(spec.encode()) >= 1024:
        raise ValueError('Input bindings exceed the native mapping size limit.')
    return spec


def read_catalog(runtime, environment):
    try:
        result = subprocess.run([str(runtime), '--input-options'], env=environment,
                                capture_output=True, timeout=10,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError('Cannot read the selected runtime input inventory.') from exc
    if result.returncode or len(result.stdout) > 64 * 1024:
        raise ValueError('The selected runtime did not return a valid input inventory.')
    try:
        catalog = json.loads(result.stdout)
        if (type(catalog.get('version')) is not int or catalog['version'] != 1
                or catalog.get('unbinding') is not True):
            raise ValueError()
        for kind in ('keyboard', 'controller'):
            sources = catalog[kind + '_sources']
            if (not isinstance(sources, list) or not 0 < len(sources) <= 512
                    or any(not isinstance(v, str) or not 0 < len(v) <= 80 for v in sources)
                    or UNBOUND in sources or len(set(sources)) != len(sources)):
                raise ValueError()
        codes = catalog['keyboard_scancodes']
        if (not isinstance(codes, dict) or set(codes) != set(catalog['keyboard_sources'])
                or any(type(code) is not int or not 0 < code < 512 for code in codes.values())
                or len(set(codes.values())) != len(codes)):
            raise ValueError()
        rows = catalog['buttons']
        if not isinstance(rows, list) or len(rows) != len(BUTTONS):
            raise ValueError()
        if {row['id'] for row in rows} != set(BUTTONS):
            raise ValueError()
        for row in rows:
            for kind in ('keyboard', 'controller'):
                defaults = row[kind + '_default']
                if (not isinstance(defaults, list) or len(defaults) > 4
                        or any(v not in catalog[kind + '_sources'] for v in defaults)):
                    raise ValueError()
        return catalog
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError('The selected runtime returned a malformed input inventory.') from exc
