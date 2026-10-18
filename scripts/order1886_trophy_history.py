# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only adapter for src/runtime_trophies.c's checksummed local store."""
from pathlib import Path
from scripts.order1886_cache import _check_ancestors

RELATIVE_PATH = Path("trophies/CUSA00076/NPWR06616_00/user-1/unlocks.txt")
HEADER = b"ORDER1886-TROPHIES 1 CUSA00076 NPWR06616_00 1\n"


def read(state):
    path = Path(state).absolute() / RELATIVE_PATH
    _check_ancestors(path)
    try:
        with path.open("rb") as stream:
            data = stream.read(16385)
    except FileNotFoundError:
        return []
    if len(data) > 16384 or not data.startswith(HEADER) or not data.endswith(b"\n"):
        raise ValueError("Local trophy history has an invalid header or size.")
    try:
        lines = data[len(HEADER):].decode("ascii").splitlines()
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

