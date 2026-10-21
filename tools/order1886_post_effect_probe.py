#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Read the live post-effect strengths out of a running Order runtime (Windows only).

The runtime executes the guest image in its own address space, so the game's globals can be
read with ReadProcessMemory. The image is found by the instruction bytes at a sanitizer site
(either the original or the patched form, see scripts/order1886_post_effects.py). From there
the blended lens parameters (pointer at RVA 0x16da6c0) and the post-processing constant block
(pointer at RVA 0x170db70) give each effect's strength as the game will use it this frame.
Samples are written as JSON lines; nothing in the process is written.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import struct
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import order1886_post_effects as effects  # noqa: E402

LENS_POINTER, CONSTANTS_POINTER = 0x16da6c0, 0x170db70
SITE = 0x81dd89  # the depth-of-field constant clamp, original or patched
SITE_BYTES = {bytes.fromhex(expected) for rva, expected, _ in effects.EFFECTS['depth_of_field'][1] if rva == SITE} | \
             {bytes.fromhex(new) for rva, _, new in effects.EFFECTS['depth_of_field'][1] if rva == SITE}
# Name: (block, offset, count of floats). Lens offsets follow the reflected parameter blocks.
FIELDS = {
    'motion_blur.lens_amount': ('lens', 0x14c, 1), 'motion_blur.constant': ('cb', 0x380, 1),
    'depth_of_field.lens_amount': ('lens', 0x398, 1), 'depth_of_field.lens_offset': ('lens', 0x39c, 1),
    'depth_of_field.alt_amount': ('lens', 0x22c, 1), 'depth_of_field.constant': ('cb', 0x30c, 1),
    'depth_of_field.constant_active': ('cb', 0x44c, 1),
    'film_grain.lens': ('lens', 0x220, 3), 'film_grain.alt': ('lens', 0x35c, 3),
    'film_grain.constant_active': ('cb', 0x510, 3),
    'chromatic_aberration.lens_rgb_shift': ('lens', 0x3bc, 3),
    'chromatic_aberration.lens_strength': ('lens', 0x3c8, 4),
    'chromatic_aberration.constant_active_rgb_shift': ('cb', 0x5c0, 3),
}


class Process:
    def __init__(self, pid):
        self.k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        self.k32.OpenProcess.restype = wintypes.HANDLE
        self.handle = self.k32.OpenProcess(0x0400 | 0x0010, False, pid)  # QUERY_INFORMATION | VM_READ
        if not self.handle:
            raise OSError(ctypes.get_last_error(), 'OpenProcess failed')

    def read(self, address, size):
        buffer, done = ctypes.create_string_buffer(size), ctypes.c_size_t()
        ok = self.k32.ReadProcessMemory(self.handle, ctypes.c_void_p(address), buffer, size, ctypes.byref(done))
        return buffer.raw[:done.value] if ok else b''

    def allocation_bases(self):
        class Info(ctypes.Structure):
            _fields_ = [('base', ctypes.c_void_p), ('alloc_base', ctypes.c_void_p), ('alloc_protect', wintypes.DWORD),
                        ('partition', wintypes.WORD), ('size', ctypes.c_size_t), ('state', wintypes.DWORD),
                        ('protect', wintypes.DWORD), ('type', wintypes.DWORD)]
        info, address, seen = Info(), 0, set()
        while self.k32.VirtualQueryEx(self.handle, ctypes.c_void_p(address), ctypes.byref(info), ctypes.sizeof(info)):
            if info.state == 0x1000 and info.alloc_base and info.alloc_base not in seen:  # MEM_COMMIT
                seen.add(info.alloc_base)
                yield info.alloc_base
            address = (info.base or 0) + info.size
            if address >= 1 << 47:
                break

    def image_base(self):
        """The allocation holding the guest image: its sanitizer site has the known bytes."""
        return next((base for base in self.allocation_bases() if self.read(base + SITE, 8) in SITE_BYTES), None)


def runtime_pids(runtime):
    """Processes running this exact runtime executable: other sessions may run their own."""
    psapi, k32 = ctypes.WinDLL('psapi'), ctypes.WinDLL('kernel32')
    k32.OpenProcess.restype = wintypes.HANDLE
    pids, needed = (wintypes.DWORD * 4096)(), wintypes.DWORD()
    psapi.EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(needed))
    found = set()
    for pid in pids[:needed.value // ctypes.sizeof(wintypes.DWORD)]:
        handle = k32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            continue
        buffer, size = ctypes.create_unicode_buffer(512), wintypes.DWORD(512)
        if k32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)) and                 str(Path(buffer.value)).lower() == runtime:
            found.add(pid)
        k32.CloseHandle(handle)
    return found


def sample(process, base):
    blocks = {}
    for block, pointer in (('lens', LENS_POINTER), ('cb', CONSTANTS_POINTER)):
        raw = process.read(base + pointer, 8)
        address = struct.unpack('<Q', raw)[0] if len(raw) == 8 else 0
        blocks[block] = process.read(address, 0x700) if address else b''
    values = {}
    for name, (block, offset, count) in FIELDS.items():
        data = blocks[block][offset:offset + 4 * count]
        values[name] = list(struct.unpack(f'<{count}f', data)) if len(data) == 4 * count else None
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='JSON lines file to append to')
    parser.add_argument('--at', type=float, nargs='+', required=True, help='seconds after the runtime appears')
    parser.add_argument('--runtime', type=Path, required=True, help='the runtime executable under test')
    parser.add_argument('--wait', type=float, default=120, help='seconds to wait for the runtime to start')
    args = parser.parse_args()
    runtime = str(args.runtime.resolve()).lower()
    already = runtime_pids(runtime)  # a session started before this one is not the one under test
    deadline, pid = time.monotonic() + args.wait, None
    while pid is None and time.monotonic() < deadline:
        pid = next(iter(runtime_pids(runtime) - already), None)
        time.sleep(0.5)
    if pid is None:
        parser.error('the runtime under test did not start')
    start, process, base = time.monotonic(), Process(pid), None
    with args.output.open('a', encoding='utf-8') as out:
        for at in sorted(args.at):
            time.sleep(max(0.0, start + at - time.monotonic()))
            base = base or process.image_base()
            record = {'pid': pid, 'seconds': at, 'image_base': hex(base) if base else None,
                      'values': sample(process, base) if base else None}
            out.write(json.dumps(record) + '\n')
            out.flush()


if __name__ == '__main__':
    main()
