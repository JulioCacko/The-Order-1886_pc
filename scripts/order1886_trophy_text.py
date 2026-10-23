# SPDX-License-Identifier: GPL-2.0-or-later
"""Trophy names and descriptions from the player's own game, decrypted as shadPS4 does.

shadPS4 (src/core/file_format/trp.cpp, src/core/crypto/crypto.cpp, decryptEFSM): the NP
communication ID, zero-padded to 16 bytes, is encrypted with AES-128-CBC under the console's
trophy key and a zero IV; the result is the key for every .ESFM entry of trophy00.trp, each of
which is a 16-byte IV followed by AES-128-CBC ciphertext of an XML document.

The trophy key is the player's, entered in the launcher; nothing Sony-owned ships with this
project, and no trophy text is ever written outside the player's own state.
"""
import re
import xml.etree.ElementTree as ElementTree

NP_COMM_ID = b'NPWR06616_00'
GRADES = {'P': 'platinum', 'G': 'gold', 'S': 'silver', 'B': 'bronze'}


def parse_key(text):
    """The 16-byte trophy key from its 32-hex-digit form, or None when it is not set."""
    text = (text or '').strip()
    if not text:
        return None
    if not re.fullmatch(r'[0-9A-Fa-f]{32}', text):
        raise ValueError('The trophy key must be 32 hexadecimal digits.')
    return bytes.fromhex(text)


def entry_key(trophy_key):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    encryptor = Cipher(algorithms.AES(trophy_key), modes.CBC(bytes(16))).encryptor()
    return encryptor.update(NP_COMM_ID.ljust(16, b'\0')) + encryptor.finalize()


def decrypt_entry(entry, key):
    """One .ESFM entry (IV + ciphertext) to its XML bytes; ValueError when the key is wrong."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    body = entry[16:len(entry) - (len(entry) - 16) % 16]
    if len(entry) < 32 or not body:
        raise ValueError('Trophy text entry is too short.')
    decryptor = Cipher(algorithms.AES(key), modes.CBC(bytes(entry[:16]))).decryptor()
    plain = decryptor.update(bytes(body)) + decryptor.finalize()
    if not plain.lstrip(b'\xef\xbb\xbf').startswith(b'<?xml'):
        raise ValueError("The trophy key does not decrypt this game's trophy text.")
    return plain[:plain.rfind(b'>') + 1]  # block padding follows the closing tag


def trophies(xml):
    """{id: {name, detail, grade, hidden}} from a TROP*.SFM document."""
    root = ElementTree.fromstring(xml)
    rows = {}
    for node in root.iter('trophy'):
        identity = int(node.get('id', '-1'))
        if not 0 <= identity < 128:
            continue
        rows[identity] = {'name': (node.findtext('name') or '').strip(),
                          'detail': (node.findtext('detail') or '').strip(),
                          'grade': GRADES.get(node.get('ttype', ''), ''),
                          'hidden': node.get('hidden') == 'yes'}
    return rows


def text_entry(names, language):
    """The language's TROP_xx.ESFM when the game has it, else its default TROP.ESFM."""
    preferred = f'TROP_{language:02d}.ESFM'.encode() if isinstance(language, int) else None
    if preferred in names:
        return preferred
    return b'TROP.ESFM' if b'TROP.ESFM' in names else None


if __name__ == '__main__':
    # Self-check with a made-up key: encrypt a document the way the game's archive stores it.
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    fake = bytes(range(16))
    document = (b'<?xml version="1.0" encoding="UTF-8"?><trophyconf><trophy id="000" hidden="no" '
                b'ttype="B"><name>First</name><detail>Do it.</detail></trophy><trophy id="001" '
                b'hidden="yes" ttype="P"><name>All</name><detail>Everything.</detail></trophy></trophyconf>')
    padded = document + b'\0' * (-len(document) % 16)
    iv = bytes(16 - n for n in range(16))
    encryptor = Cipher(algorithms.AES(entry_key(fake)), modes.CBC(iv)).encryptor()
    entry = iv + encryptor.update(padded) + encryptor.finalize()
    assert decrypt_entry(entry, entry_key(fake)) == document
    assert trophies(document)[1] == {'name': 'All', 'detail': 'Everything.', 'grade': 'platinum', 'hidden': True}
    try:
        decrypt_entry(entry, entry_key(bytes(16)))
    except ValueError:
        pass
    else:
        raise AssertionError('a wrong key must be rejected')
    assert parse_key('') is None and parse_key('00' * 16) == bytes(16)
    print('ok')
