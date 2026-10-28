# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only adapter for src/runtime_trophies.c's checksummed local store."""
from pathlib import Path
import base64
import hashlib
import re
import struct
from scripts.order1886_cache import _check_ancestors

from scripts.order1886_editions import VERIFIED_TITLE_ID

# One store per edition, as src/runtime_trophies.c keeps them (RUNTIME_TROPHY_PATH_FORMAT).
RELATIVE_PATH = "trophies/{}/NPWR06616_00/user-1/unlocks.txt"
HEADER = "ORDER1886-TROPHIES 1 {} NPWR06616_00 1\n"


def _archive(game):
    """The installed trophy00.trp, validated: (bytes, {name: (offset, length, flag)}).

    Layout: shadPS4 src/core/file_format/trp.h at 0ebea15c24253b60f514fc37a348dabc8d0bcb90.
    """
    path = Path(game) / 'sce_sys/trophy/trophy00.trp'
    with path.open('rb') as stream:
        data = bytearray(stream.read(8 * 1024 * 1024 + 1))
    if not 96 <= len(data) <= 8 * 1024 * 1024:
        raise ValueError('Installed trophy archive has an invalid size.')
    magic, version, size, count, entry_size = struct.unpack_from('>IIQII', data)
    end_table = 96 + count * 64
    if (magic != 0xdca24d00 or version != 3 or size != len(data) or entry_size != 64
            or not 0 < count <= 512 or end_table > size):
        raise ValueError('Installed trophy archive has an invalid header.')
    digest = bytes(data[28:48])
    data[28:48] = bytes(20)
    if hashlib.sha1(data).digest() != digest:
        raise ValueError('Installed trophy archive checksum does not match.')
    entries, ranges = {}, []
    for index in range(count):
        raw_name, offset, length, flag = struct.unpack_from('>32sQQI', data, 96 + index * 64)
        name = raw_name.split(b'\0', 1)[0]
        if (not re.fullmatch(rb'[A-Z0-9_.]{1,31}', name) or name in entries
                or offset < end_table or not length or offset > size or length > size - offset):
            raise ValueError('Installed trophy archive has an invalid entry.')
        entries[name] = (offset, length, flag)
        ranges.append((offset, offset + length))
    ranges.sort()
    if any(a[1] > b[0] for a, b in zip(ranges, ranges[1:])):
        raise ValueError('Installed trophy archive has overlapping entries.')
    return data, entries


def catalog(game, unlocked=()):
    """Read installed TRP v3 icons in memory; the trophy text is encrypted (see catalog_text)."""
    data, entries = _archive(game)
    rows, encoded_size = [], 0
    for name, (offset, length, flag) in entries.items():
        match = re.fullmatch(rb'TROP([0-9]{3})\.PNG', name)
        if not match:
            continue
        identity = int(match[1])
        if flag != 0 or identity >= 128 or length > 128 * 1024:
            raise ValueError('Installed trophy artwork has an invalid entry.')
        icon = data[offset:offset + length]
        if (len(icon) < 33 or icon[:16] != b'\x89PNG\r\n\x1a\n\0\0\0\rIHDR'
                or not all(0 < n <= 1024 for n in struct.unpack_from('>II', icon, 16))):
            raise ValueError('Installed trophy artwork has invalid image dimensions or format.')
        image = ''
        if identity in unlocked:
            image = 'data:image/png;base64,' + base64.b64encode(icon).decode('ascii')
            encoded_size += len(image)
            if encoded_size > 1024 * 1024:
                raise ValueError('Installed trophy artwork exceeds the launcher response limit.')
        rows.append({'id': identity, 'icon': image})
    if not rows:
        raise ValueError('Installed trophy archive has no achievement artwork.')
    return sorted(rows, key=lambda row: row['id'])


def catalog_text(game, trophy_key, language=None):
    """{id: {name, detail, grade, hidden}} decrypted from the player's own game with the
    player's trophy key, in the game's text for `language` (a PS4 system language id) when it
    has one; {} without a key. ValueError when the key or the archive is wrong."""
    from scripts import order1886_trophy_text as text
    key = text.parse_key(trophy_key)
    if key is None:
        return {}
    data, entries = _archive(game)
    name = text.text_entry(entries, language)
    if name is None:
        raise ValueError('Installed trophy archive has no trophy text.')
    offset, length, _ = entries[name]
    if length > 1024 * 1024:
        raise ValueError('Installed trophy text is too large.')
    return text.trophies(text.decrypt_entry(bytes(data[offset:offset + length]), text.entry_key(key)))


def read(state, title_id=VERIFIED_TITLE_ID):
    path = Path(state).absolute() / RELATIVE_PATH.format(title_id)
    header = HEADER.format(title_id).encode("ascii")
    _check_ancestors(path)
    try:
        with path.open("rb") as stream:
            data = stream.read(16385)
    except FileNotFoundError:
        return []
    if len(data) > 16384 or not data.startswith(header) or not data.endswith(b"\n"):
        raise ValueError("Local trophy history has an invalid header or size.")
    try:
        lines = data[len(header):].decode("ascii").splitlines()
        footer = lines.pop().split(" ")
        if len(footer) != 3 or footer[0] != "END" or len(lines) > 128:
            raise ValueError()
        body = data[:data.rfind(b"END ")]
        checksum = 14695981039346656037
        for value in body:
            checksum = ((checksum ^ value) * 1099511628211) & ((1 << 64) - 1)
        if int(footer[1]) != len(lines) or int(footer[2], 16) != checksum:
            raise ValueError()
        entries = []
        seen = set()
        for line in lines:
            parts = line.split(" ")
            if len(parts) != 2 or not all(part.isascii() and part.isdigit() for part in parts):
                raise ValueError()
            identity, stamp = map(int, parts)
            if not 0 <= identity < 128 or not 0 < stamp < 1 << 63 or identity in seen:
                raise ValueError()
            seen.add(identity)
            entries.append({"id": identity, "unlocked_at": stamp})
        return entries
    except (ValueError, IndexError, UnicodeError) as exc:
        raise ValueError("Local trophy history is corrupt; existing data was not changed.") from exc

