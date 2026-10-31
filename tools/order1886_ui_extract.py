"""Extract The Order: 1886 UI movies, bitmaps and layout from the user's own dump (analysis only).

    python tools/order1886_ui_extract.py GAME_DIR --output DIR [--scan-all] [--jobs N]

GAME_DIR holds eboot.bin and _data (CUSA00076 with update 1.02). DIR must be outside the
repository and outside GAME_DIR; nothing is written anywhere else and no game file is changed.

The UI is Flash: Iggy loads SWF movies straight from `_data`. Movies sit inside resources
that are either stored raw or wrapped in a `COMPRESS` container (u64 raw size, u64 size, then
one legacy Oodle LZH/LZHLW stream or a table of independently coded 256 KiB chunks). Legacy
Oodle has no free decoder, so the game's own OodleLZ_Decompress is run from the user's
eboot.bin under Unicorn (`pip install unicorn`); only code bytes verified below are executed.

Per movie the output holds movie.swf (uncompressed, for JPEXS and similar), every bitmap as
PNG, and manifest.json entries with the stage size, every exported/AS3 symbol, the bitmaps
each symbol draws, placement matrices (for re-anchoring UI when the letterbox is removed) and
controller-glyph tags. See docs/order1886-ui-assets.md.
"""
import argparse
import hashlib
import io
import json
import os
import re
import struct
import sys
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

NAMESPACE = '_data/1408209885/ps4'
# Resources the full scan found holding SWF movies (1.02). --scan-all rediscovers them.
KNOWN_UI = ['primary/c2d79afbc68fc86c/v1/e32dc7d7dc8151e2'] + [
    'primary/3861c21fc34b7612/v11345526222/' + name for name in (
        'baceeaafdf99323d', '2fd49d9a5a7d4399', 'abf518b95fd9dd5a', '49aaa19f7cf28a03',
        '0757a7b1def9877f', 'ec5e1979c41e637c', '9e417f9127f39ba6', 'd107aa37d606b0be')]
# Audio and streamed texture mips never hold movies; the full scan skips them.
SKIP = ('primary/3bf280d756aa4f4e', 'primary/4c7002f42ce0da08', 'GPU/')

# OodleLZ_Decompress and the two Oodle allocator entry points in the 1.02 executable.
DECOMPRESS, ALLOC, FREE, MALLOC_POINTER = 0xe81790, 0xe89890, 0xe89920, 0x1679d88
# SHA-256 of the image bytes 0xe80000-0xec0000 (the whole Oodle decoder and allocator).
OODLE_REGION, OODLE_SHA256 = (0xe80000, 0xec0000), '924e68e73d2c8376934ff6a856addced4753d458a0a3ef7d779ab1abbc41ba2e'
CHUNK = 0x40000


# --- containers -------------------------------------------------------------------------

def container_chunks(blob):
    """(raw size, [(offset, size, raw offset, raw size)]) of a COMPRESS container."""
    if blob[:8] != b'COMPRESS' or len(blob) < 24:
        raise ValueError('not a COMPRESS container')
    raw, _ = struct.unpack_from('<QQ', blob, 8)
    if blob[24:32] == bytes(8):  # chunk table: (u64 raw offset, u64 size) before each chunk
        chunks, pos = [], 24
        while pos + 16 <= len(blob):
            offset, size = struct.unpack_from('<QQ', blob, pos)
            if offset != len(chunks) * CHUNK or offset >= raw or pos + 16 + size > len(blob):
                break
            chunks.append((pos + 16, size, offset, min(CHUNK, raw - offset)))
            pos += 16 + size
        else:
            if chunks and chunks[-1][2] + chunks[-1][3] == raw:
                return raw, chunks
    _, size = struct.unpack_from('<QQ', blob, 8)
    if 24 + size > len(blob):
        raise ValueError('truncated COMPRESS container')
    return raw, [(24, size, 0, raw)]


def stored_container(raw, chunked=True):
    """A COMPRESS container of stored Oodle blocks (header byte 0x00: memcpy) that the game's
    own decoder accepts; no compressor needed. Level/UI packages must stay COMPRESS (a raw
    override of one fails to load), so overrides of them use this."""
    blocks = [b'\x00' + raw[i:i + CHUNK] for i in range(0, len(raw), CHUNK)] or [b'\x00']
    if not chunked:
        body = b''.join(blocks)
        return b'COMPRESS' + struct.pack('<QQ', len(raw), len(body)) + body
    body = b''.join(struct.pack('<QQ', i * CHUNK, len(b)) + b for i, b in enumerate(blocks))
    # Chunked containers record the whole file size, single streams the payload size.
    return b'COMPRESS' + struct.pack('<QQ', len(raw), 24 + len(body)) + body


class Oodle:
    """The executable's own legacy Oodle decoder, emulated. Verified code only."""

    def __init__(self, eboot):
        import prepare
        import link_libc
        try:
            from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE
            from unicorn import x86_const as x
        except ImportError:
            raise SystemExit('Decoding COMPRESS resources needs Unicorn: python -m pip install unicorn')
        self.x = x
        elf, _, ph, _, _ = prepare.parse_self(prepare.read_self(eboot))
        start, end = OODLE_REGION
        if hashlib.sha256(_image(elf, ph, start, end - start)).hexdigest() != OODLE_SHA256:
            raise SystemExit('eboot.bin is not the verified 1.02 build: its Oodle code differs')
        mu = self.mu = Uc(UC_ARCH_X86, UC_MODE_64)
        page = lambda v: (v + 0xfff) & ~0xfff
        for p in ph:
            if p['type'] == 1:
                start = p['vaddr'] & ~0xfff
                mu.mem_map(start, page(p['vaddr'] + p['memsz']) - start)
                mu.mem_write(p['vaddr'], bytes(elf[p['offset']:p['offset'] + p['filesz']]))
        self.stack, tls, self.ret, stub = 0x7000_0000, 0x7100_0000, 0x7200_0000, 0x7300_0000
        self.heap0, self.heap_size = 0x1_0000_0000, 0
        mu.mem_map(self.stack, 0x100000)
        mu.mem_map(tls - 0x10000, 0x20000)  # static TLS sits below the thread pointer
        mu.mem_write(tls, struct.pack('<Q', tls))
        mu.reg_write(x.UC_X86_REG_FS_BASE, tls)
        mu.mem_map(self.ret, 0x1000)
        mu.mem_write(self.ret, b'\xf4')
        mu.mem_map(stub, 0x10000)
        mu.mem_write(stub, b'\xc3' * 0x10000)
        # Imports resolve to `ret` stubs; memcpy/memmove/memset are done here, the rest are
        # Oodle's own logging and return 0. Relative relocations use base 0, as Ghidra does.
        mod = link_libc.module(eboot)
        self.imports = {}
        for target, kind, symbol, addend in mod['relocs']:
            if kind == 8:
                mu.mem_write(target, struct.pack('<Q', addend))
            elif kind in (1, 6, 7):
                address = stub + 16 * len(self.imports)
                self.imports[address] = mod['symbols'][symbol]['name'].split('#')[0]
                mu.mem_write(target, struct.pack('<Q', address))
        self.malloc = stub + 0xff00
        mu.mem_write(MALLOC_POINTER, struct.pack('<Q', self.malloc))
        mu.hook_add(UC_HOOK_CODE, self._import, begin=stub, end=stub + 0xffff)
        for address in (ALLOC, FREE, 0):
            mu.hook_add(UC_HOOK_CODE, self._entry, begin=address, end=address)

    def _alloc(self, size, align=16):
        p = (self.next + max(align, 16) - 1) & ~(max(align, 16) - 1)
        if p + size > self.heap0 + self.heap_size:
            raise MemoryError('Oodle emulator heap exhausted')
        self.next = p + size
        return p

    def _return(self, value):
        x, mu = self.x, self.mu
        sp = mu.reg_read(x.UC_X86_REG_RSP)
        mu.reg_write(x.UC_X86_REG_RAX, value)
        mu.reg_write(x.UC_X86_REG_RIP, struct.unpack('<Q', mu.mem_read(sp, 8))[0])
        mu.reg_write(x.UC_X86_REG_RSP, sp + 8)

    def _entry(self, mu, address, size, _):
        x = self.x
        if address == ALLOC:
            self._return(self._alloc(mu.reg_read(x.UC_X86_REG_RDI), mu.reg_read(x.UC_X86_REG_RSI)))
        elif address == FREE:
            self._return(0)
        else:  # a null callback: Oodle's error log, which the game installs and we do not
            self.failed = True
            mu.emu_stop()

    def _import(self, mu, address, size, _):
        x = self.x
        if address == self.malloc:
            mu.reg_write(x.UC_X86_REG_RAX, self._alloc(mu.reg_read(x.UC_X86_REG_RSI), 64))
            return
        name = self.imports.get(address)
        if name is None:
            return
        di, si, dx = (mu.reg_read(r) for r in (x.UC_X86_REG_RDI, x.UC_X86_REG_RSI, x.UC_X86_REG_RDX))
        if name in ('Q3VBxCXhUHs', '+P6FRGH4LfA') and dx:  # memcpy, memmove
            mu.mem_write(di, bytes(mu.mem_read(si, dx)))
        elif name == '8zTFvBIAIN8' and dx:  # memset
            mu.mem_write(di, bytes([si & 255]) * dx)
        mu.reg_write(x.UC_X86_REG_RAX, di if name in ('Q3VBxCXhUHs', '+P6FRGH4LfA', '8zTFvBIAIN8') else 0)

    def _decode(self, data, raw_size):
        x, mu = self.x, self.mu
        # Inputs, output and Oodle's own decoder state (a few MiB); chunks keep this small.
        need = (len(data) + raw_size + (16 << 20) + 0xfffff) & ~0xfffff
        if need > self.heap_size:
            if self.heap_size:
                mu.mem_unmap(self.heap0, self.heap_size)
            mu.mem_map(self.heap0, need)
            self.heap_size = need
        self.next, self.failed = self.heap0, False
        source = self._alloc(len(data) + 64)
        target = self._alloc(raw_size + 64)
        mu.mem_write(source, data)
        sp = self.stack + 0xF0000
        mu.mem_write(sp, struct.pack('<5Q', self.ret, 0, 0, 0, 0))
        for reg, value in ((x.UC_X86_REG_RSP, sp), (x.UC_X86_REG_RDI, source),
                           (x.UC_X86_REG_RSI, len(data)), (x.UC_X86_REG_RDX, target),
                           (x.UC_X86_REG_RCX, raw_size), (x.UC_X86_REG_R8, 0), (x.UC_X86_REG_R9, 0)):
            mu.reg_write(reg, value)
        mu.emu_start(DECOMPRESS, self.ret)
        if self.failed or mu.reg_read(x.UC_X86_REG_RAX) != raw_size:
            raise ValueError('Oodle stream failed to decode')
        return bytes(mu.mem_read(target, raw_size))

    def decompress(self, blob):
        raw, chunks = container_chunks(blob)
        out = bytearray(raw)
        for p, n, offset, size in chunks:
            out[offset:offset + size] = self._decode(blob[p:p + n], size)
        return bytes(out)


def _image(elf, ph, rva, size):
    for p in ph:
        if p['type'] == 1 and p['vaddr'] <= rva and rva + size <= p['vaddr'] + p['filesz']:
            return bytes(elf[p['offset'] + rva - p['vaddr']:][:size])
    return b''


def payload(blob, oodle):
    """The resource as the game sees it: COMPRESS decoded, anything else verbatim (fde_c77f60)."""
    if blob[:8] != b'COMPRESS':
        return blob, 'raw'
    if oodle is None:
        raise ValueError('COMPRESS resource needs the Oodle emulator')
    return oodle.decompress(blob), 'chunked' if len(container_chunks(blob)[1]) > 1 else 'compress'


# --- SWF --------------------------------------------------------------------------------

SWF_SIGNATURE = re.compile(rb'(CWS|FWS)[\x06-\x0f]')
TAG_NAMES = {20: 'DefineBitsLossless', 36: 'DefineBitsLossless2', 21: 'DefineBitsJPEG2',
             35: 'DefineBitsJPEG3', 90: 'DefineBitsJPEG4', 6: 'DefineBits'}


class Bits:
    def __init__(self, data, pos):
        self.data, self.pos, self.bit = data, pos, 0

    def u(self, count):
        value = 0
        for _ in range(count):
            value = (value << 1) | (self.data[self.pos] >> (7 - self.bit)) & 1
            self.bit += 1
            if self.bit == 8:
                self.bit, self.pos = 0, self.pos + 1
        return value

    def s(self, count):
        value = self.u(count)
        return value - (1 << count) if count and value >> (count - 1) else value

    def end(self):
        return self.pos + (1 if self.bit else 0)


def read_rect(data, pos):
    b = Bits(data, pos)
    n = b.u(5)
    xmin, xmax, ymin, ymax = (b.s(n) for _ in range(4))
    return (xmin, xmax, ymin, ymax), b.end()


def read_matrix(data, pos):
    b = Bits(data, pos)
    sx = sy = 1.0
    r0 = r1 = 0.0
    if b.u(1):
        n = b.u(5)
        sx, sy = b.s(n) / 65536, b.s(n) / 65536
    if b.u(1):
        n = b.u(5)
        r0, r1 = b.s(n) / 65536, b.s(n) / 65536
    n = b.u(5)
    tx, ty = b.s(n), b.s(n)
    return dict(a=sx, b=r0, c=r1, d=sy, tx=tx / 20, ty=ty / 20), b.end()


def tags(body, pos):
    while pos + 2 <= len(body):
        header = struct.unpack_from('<H', body, pos)[0]
        pos += 2
        code, size = header >> 6, header & 63
        if size == 63:
            size = struct.unpack_from('<I', body, pos)[0]
            pos += 4
        if pos + size > len(body):
            raise ValueError('truncated SWF tag')
        yield code, body[pos:pos + size]
        pos += size
        if code == 0:
            return


def find_swfs(data):
    """(offset, header bytes length, version) of every complete SWF inside a payload."""
    found = []
    for m in SWF_SIGNATURE.finditer(data):
        offset = m.start()
        length = struct.unpack_from('<I', data, offset + 4)[0] if offset + 8 <= len(data) else 0
        if not 64 < length < 64 << 20:
            continue
        try:
            body = swf_body(data[offset:])
        except (ValueError, zlib.error):
            continue
        if len(body) == length - 8:
            found.append(offset)
    return found


def swf_body(swf):
    length = struct.unpack_from('<I', swf, 4)[0]
    if swf[:3] == b'FWS':
        if len(swf) < length:
            raise ValueError('truncated SWF')
        return swf[8:length]
    if swf[8] != 0x78:
        raise ValueError('not zlib')
    return zlib.decompressobj().decompress(swf[8:], length - 8)


def fill_style(data, pos, version, ids):
    kind = data[pos]
    pos += 1
    if kind == 0:
        return pos + (4 if version >= 3 else 3)
    if kind in (0x10, 0x12, 0x13):
        pos = read_matrix(data, pos)[1]
        return pos + 1 + (data[pos] & 15) * (5 if version >= 3 else 4) + (2 if kind == 0x13 else 0)
    if 0x40 <= kind <= 0x43:
        ids.append(struct.unpack_from('<H', data, pos)[0])
        return read_matrix(data, pos + 2)[1]
    raise ValueError(f'unknown fill style {kind:#x}')


def style_arrays(data, pos, version, ids):
    """Skip a FILLSTYLEARRAY and LINESTYLEARRAY, collecting bitmap fill ids."""
    for lines in (False, True):
        count = data[pos]
        pos += 1
        if count == 0xff and version >= 2:
            count = struct.unpack_from('<H', data, pos)[0]
            pos += 2
        for _ in range(count):
            if not lines:
                pos = fill_style(data, pos, version, ids)
            elif version == 4:  # LINESTYLE2: width, flags, [miter], fill style or RGBA
                flags = data[pos + 2]
                pos += 4 + (2 if (flags >> 4) & 3 == 2 else 0)
                pos = fill_style(data, pos, version, ids) if flags & 0x08 else pos + 4
            else:
                pos += 2 + (4 if version >= 3 else 3)
    return pos


def bitmap_fills(data, pos, version):
    """Bitmap ids a shape fills with, including styles introduced mid-shape (StateNewStyles)."""
    ids = []
    try:
        records(data, style_arrays(data, pos, version, ids), version, ids)
    except (IndexError, struct.error, ValueError):
        pass  # keep the fills found before a truncated or unknown record
    return ids


def records(data, pos, version, ids):
    b = Bits(data, pos)
    fill_bits, line_bits = b.u(4), b.u(4)
    while True:
        if b.u(1):  # edge record
            straight, n = b.u(1), b.u(4) + 2
            if straight:
                if b.u(1):
                    b.u(n), b.u(n)
                else:
                    b.u(1), b.u(n)
            else:
                for _ in range(4):
                    b.u(n)
            continue
        flags = b.u(5)
        if not flags:
            return
        if flags & 1:
            n = b.u(5)
            b.u(n), b.u(n)
        for flag, bits in ((2, fill_bits), (4, fill_bits), (8, line_bits)):
            if flags & flag:
                b.u(bits)
        if flags & 16:
            pos = style_arrays(data, b.end(), version, ids)
            b = Bits(data, pos)
            fill_bits, line_bits = b.u(4), b.u(4)


def placements(data):
    """PlaceObject2/3 records of a timeline: depth, character, name, matrix (first frame wins)."""
    out = []
    for code, tag in data:
        if code not in (26, 70):
            continue
        flags = tag[0]
        pos = 1
        flags2 = 0
        if code == 70:
            flags2 = tag[1]
            pos = 2
        depth = struct.unpack_from('<H', tag, pos)[0]
        pos += 2
        if code == 70 and flags2 & 0x08:
            pos = tag.index(0, pos) + 1
        item = dict(depth=depth)
        if flags & 0x02:
            item['character'] = struct.unpack_from('<H', tag, pos)[0]
            pos += 2
        if flags & 0x04:
            item['matrix'], pos = read_matrix(tag, pos)
        if flags & 0x08:  # colour transform with alpha
            b = Bits(tag, pos)
            add, mult, n = b.u(1), b.u(1), b.u(4)
            for _ in range((4 if mult else 0) + (4 if add else 0)):
                b.s(n)
            pos = b.end()
        if flags & 0x10:
            pos += 2
        if flags & 0x20:
            end = tag.index(0, pos)
            item['name'] = tag[pos:end].decode('utf-8', 'replace')
        if 'character' in item:
            out.append(item)
    return out


def parse_swf(swf):
    body = swf_body(swf)
    stage, pos = read_rect(body, 0)
    rate, frames = body[pos + 1] + body[pos] / 256, struct.unpack_from('<H', body, pos + 2)[0]
    movie = dict(version=swf[3], stage=[v / 20 for v in stage], frame_rate=rate, frames=frames,
                 bitmaps={}, shapes={}, sprites={}, symbols={}, exports={}, root=[])
    top = list(tags(body, pos + 4))
    for code, tag in top:
        if code in TAG_NAMES and code != 6:
            cid = struct.unpack_from('<H', tag)[0]
            bitmap = dict(tag=TAG_NAMES[code], data=tag)
            if code in (20, 36):
                bitmap.update(zip(('format', 'width', 'height'), struct.unpack_from('<BHH', tag, 2)))
            movie['bitmaps'][cid] = bitmap
        elif code in (2, 22, 32, 83):
            cid = struct.unpack_from('<H', tag)[0]
            bounds, q = read_rect(tag, 2)
            if code == 83:
                q = read_rect(tag, q)[1] + 1
            try:
                fills = bitmap_fills(tag, q, {2: 1, 22: 2, 32: 3, 83: 4}[code])
            except (IndexError, struct.error, ValueError):
                fills = []
            movie['shapes'][cid] = dict(bitmaps=fills, bounds=[v / 20 for v in bounds])
        elif code == 39:
            cid = struct.unpack_from('<H', tag)[0]
            movie['sprites'][cid] = placements(list(tags(tag, 4)))
        elif code in (56, 76):
            count, q = struct.unpack_from('<H', tag)[0], 2
            for _ in range(count):
                cid = struct.unpack_from('<H', tag, q)[0]
                end = tag.index(0, q + 2)
                target = movie['symbols'] if code == 76 else movie['exports']
                target[cid] = tag[q + 2:end].decode('utf-8', 'replace')
                q = end + 1
    movie['root'] = placements(top)
    return movie


def bitmaps_under(movie, cid, seen=None):
    seen = set() if seen is None else seen
    if cid in seen:
        return set()
    seen.add(cid)
    if cid in movie['bitmaps']:
        return {cid}
    if cid in movie['shapes']:  # 0xffff and other missing ids mean "no bitmap"
        return {b for b in movie['shapes'][cid]['bitmaps'] if b in movie['bitmaps']}
    found = set()
    for item in movie['sprites'].get(cid, []):
        found |= bitmaps_under(movie, item['character'], seen)
    return found


def decode_bitmap(bitmap):
    """RGBA Pillow image of a SWF bitmap tag (lossless premultiplied ARGB, palette, JPEG+alpha)."""
    from PIL import Image
    tag, data = bitmap['tag'], bitmap['data']
    if tag.startswith('DefineBitsLossless'):
        alpha = tag.endswith('2')
        fmt, width, height = bitmap['format'], bitmap['width'], bitmap['height']
        if fmt == 3:
            colours = data[7] + 1
            pixels = zlib.decompress(data[8:])
            size = 4 if alpha else 3
            stride = (width + 3) & ~3
            palette = [pixels[i * size:i * size + size] + (b'' if alpha else b'\xff')
                       for i in range(colours)]
            base = colours * size
            rgba = b''.join(palette[pixels[base + y * stride + x]]
                            for y in range(height) for x in range(width))
            image = Image.frombytes('RGBa' if alpha else 'RGBA', (width, height), rgba)
        elif fmt == 5:
            pixels = zlib.decompress(data[7:])[:width * height * 4]
            image = Image.frombytes('RGBA', (width, height), pixels, 'raw', 'ARGB')
            if alpha:  # stored premultiplied
                image = Image.frombytes('RGBa', (width, height), image.tobytes())
        else:
            raise ValueError(f'unsupported lossless format {fmt}')
        return image.convert('RGBA')
    if tag == 'DefineBitsJPEG2':
        return Image.open(io.BytesIO(data[2:])).convert('RGBA')
    size = struct.unpack_from('<I', data, 2)[0]
    base = 6 if tag == 'DefineBitsJPEG3' else 8
    image = Image.open(io.BytesIO(data[base:base + size])).convert('RGBA')
    if len(data) > base + size:
        alpha = zlib.decompress(data[base + size:])
        if len(alpha) == image.width * image.height:
            image.putalpha(Image.frombytes('L', image.size, alpha))
    return image


# DualShock 4 glyphs by the button token in RAD's class names: ButtonIcon<Size><Style><Token>
# (rad.widgets.buttons.*) and the QTE build-in/out clips Button_<Token>_... (Interact_fla.*).
# In the small ButtonIcon set LS/RS are the sticks ("L"/"R") and LA/RA the clicks ("L3"/"R3"),
# as the bitmaps show; LSF/LSB are left stick forward/back. RAD's names are not consistent
# (large LS/RS icons also carry the L3/R3 text), so the art pack's plan.json is reviewable.
GLYPH_TOKENS = {
    'Cross': 'cross', 'X': 'cross', 'Circle': 'circle', 'Square': 'square', 'Triangle': 'triangle',
    'ShoulderLeft': 'l1', 'ShoulderL1': 'l1', 'L1': 'l1', 'ShoulderRight': 'r1', 'ShoulderR1': 'r1',
    'R1': 'r1', 'TriggerLeft': 'l2', 'TriggerL2': 'l2', 'L2': 'l2', 'TriggerRight': 'r2',
    'TriggerR2': 'r2', 'R2': 'r2', 'LA': 'l3', 'Click_L3': 'l3', 'ClickL3': 'l3', 'RA': 'r3',
    'Click_R3': 'r3', 'ClickR3': 'r3', 'LS': 'left_stick', 'Analog_LS': 'left_stick',
    'AnalogL': 'left_stick', 'LSF': 'left_stick_forward', 'LSB': 'left_stick_back',
    'RS': 'right_stick', 'Analog_RS': 'right_stick', 'Up': 'dpad_up', 'Down': 'dpad_down',
    'Left': 'dpad_left', 'Right': 'dpad_right', 'InvertLeft': 'l1',  # draws "L1"
    'InvertRight': 'r1',  # draws "R1"
    'DPADUD': 'dpad_up_down', 'DPADLR': 'dpad_left_right',
    'Touchpad': 'touchpad', 'Option': 'options', 'Swap': 'cross_circle_swap'}
GLYPH_PATTERNS = [
    re.compile(r'ButtonIcon(?:Small|Large|32)(?:Normal|Invert|Solid)?(?P<t>[A-Za-z0-9]+)$'),
    re.compile(r'(?:^|\.)Button_(?P<t>Analog_[LR]S|Click_[LR]3|[A-Za-z0-9]+?)_'),
    re.compile(r'WorldInteractButtonPress(?P<t>[A-Za-z0-9]+?)_\d+$'),
    re.compile(r'button(?:Face|Analog|Click)(?P<t>Triangle|Circle|Square|X|L3|R3|L)(?:Invert|Normal)'),
    re.compile(r'Face(?:Inverted)?(?P<t>X)Enlarged')]


def glyph_of(names):
    """The controller glyph a symbol (or any owner of a bitmap) shows; 'button' if unnamed."""
    for name in names:
        for pattern in GLYPH_PATTERNS:
            m = pattern.search(name)
            if m:
                token = m.group('t')
                token = {'L': 'AnalogL'}.get(token, token)
                if 'buttonClick' in name:
                    token = 'Click' + token
                return GLYPH_TOKENS.get(token, 'button')
    return None


def extract_movie(swf, folder):
    movie = parse_swf(swf)
    folder.mkdir(parents=True, exist_ok=True)
    body = swf_body(swf)
    (folder / 'movie.swf').write_bytes(b'FWS' + swf[3:4] + struct.pack('<I', len(body) + 8) + body)
    names = {**movie['exports'], **movie['symbols']}
    owners = {}
    for cid, name in names.items():
        for b in bitmaps_under(movie, cid):
            owners.setdefault(b, []).append(name)
    bitmaps = []
    for cid, bitmap in sorted(movie['bitmaps'].items()):
        entry = dict(id=cid, tag=bitmap['tag'], symbols=sorted(owners.get(cid, [])),
                     sha256=hashlib.sha256(bitmap['data']).hexdigest())
        # Build-in/out layers (rings, glows, frames) are shared by several buttons: glyph is
        # set only when every owning button agrees, glyphs lists them all.
        glyphs = sorted({glyph_of([name]) for name in entry['symbols']} - {None})
        entry.update(glyph=glyphs[0] if len(glyphs) == 1 else None, glyphs=glyphs)
        try:
            image = decode_bitmap(bitmap)
            entry.update(width=image.width, height=image.height, png=f'bitmaps/{cid:04d}.png')
            (folder / 'bitmaps').mkdir(exist_ok=True)
            image.save(folder / entry['png'])
        except Exception as error:  # keep going; the manifest names what failed
            entry['error'] = repr(error)
        if 'format' in bitmap:
            entry['lossless_format'] = bitmap['format']
        bitmaps.append(entry)
    symbols = [dict(id=cid, name=name, bitmaps=sorted(bitmaps_under(movie, cid)),
                    placements=movie['sprites'].get(cid, []),
                    glyph=glyph_of([name]))
               for cid, name in sorted(names.items())]
    return dict(version=movie['version'], stage=movie['stage'], frame_rate=movie['frame_rate'],
                frames=movie['frames'], root=movie['root'], symbols=symbols, bitmaps=bitmaps,
                shapes={cid: s for cid, s in movie['shapes'].items() if s['bitmaps']})


# --- driver -----------------------------------------------------------------------------

def archive_map(game):
    data = (game / 'archivemap.bin').read_bytes()
    count = struct.unpack_from('<I', data)[0]
    return {f'{h:016x}': (i, v) for i, (h, v) in
            enumerate(struct.unpack_from('<QI', data, 4 + i * 12) for i in range(count))}


_oodle = None


def _worker_init(eboot):
    global _oodle
    _oodle = Oodle(eboot) if eboot else None


def scan_resource(path):
    """SWF offsets in one resource; used by --scan-all workers."""
    blob = Path(path).read_bytes()
    try:
        data, _ = payload(blob, _oodle)
    except (ValueError, MemoryError) as error:
        return path, None, repr(error)
    return path, find_swfs(data), None


def check_output(output, game):
    output = output.resolve()
    for forbidden in (ROOT, game.resolve()):
        if output == forbidden or forbidden in output.parents:
            raise SystemExit(f'--output must be outside {forbidden}')
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('game_dir', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--scan-all', action='store_true',
                        help='decode every candidate resource to find movies (slow: ~16 GB of payload)')
    parser.add_argument('--jobs', type=int, default=max(1, (os.cpu_count() or 2) - 2))
    parser.add_argument('--resource', action='append', default=[],
                        help=f'resource path relative to {NAMESPACE} (repeatable)')
    args = parser.parse_args(argv)
    game = args.game_dir
    if not (game / 'eboot.bin').is_file() or not (game / NAMESPACE).is_dir():
        raise SystemExit(f'{game} does not hold eboot.bin and {NAMESPACE}')
    output = check_output(args.output, game)
    root = game / NAMESPACE
    eboot = str(game / 'eboot.bin')
    names = args.resource or KNOWN_UI
    if args.scan_all:
        candidates = sorted((p for p in root.rglob('*') if p.is_file() and
                             not any(p.relative_to(root).as_posix().startswith(s) for s in SKIP)),
                            key=lambda p: p.stat().st_size)
        found = []
        with ProcessPoolExecutor(args.jobs, initializer=_worker_init, initargs=(eboot,)) as pool:
            for path, swfs, error in pool.map(scan_resource, map(str, candidates), chunksize=1):
                if error:
                    print(f'skip {path}: {error}', file=sys.stderr)
                elif swfs:
                    found.append(Path(path).relative_to(root).as_posix())
                    print('movie in', found[-1], flush=True)
        names = found
    _worker_init(eboot)
    amap = archive_map(game)
    manifest = dict(game=str(game.resolve()), namespace=NAMESPACE, resources=[])
    output.mkdir(parents=True, exist_ok=True)
    for name in names:
        path = root / name
        blob = path.read_bytes()
        data, container = payload(blob, _oodle)
        entry = dict(path=f'{NAMESPACE}/{name}', size=len(blob),
                     sha256=hashlib.sha256(blob).hexdigest(), container=container,
                     payload_size=len(data), archivemap=amap.get(path.name), movies=[])
        for offset in find_swfs(data):
            folder = output / f'{path.parent.parent.name}_{path.name}_{offset:x}'
            movie = extract_movie(data[offset:], folder)
            movie.update(offset=offset, folder=folder.name)
            entry['movies'].append(movie)
            glyphs = sum(1 for b in movie['bitmaps'] if b['glyphs'])
            print(f'{name} @{offset:#x}: {len(movie["bitmaps"])} bitmaps, {glyphs} glyph bitmaps, '
                  f'{len(movie["symbols"])} symbols -> {folder}')
        manifest['resources'].append(entry)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=1))
    print('manifest', output / 'manifest.json')


if __name__ == '__main__':
    main()
