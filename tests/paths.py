"""Repository paths for the Python tests (run: python3 -m unittest discover -s tests)."""
import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def native_binary(name):
    return ROOT / ('out/gpu/' + name + '.exe' if sys.platform == 'win32' else 'out/' + name)


def native_environment():
    environment = os.environ.copy()
    if sys.platform == 'win32':
        dependencies = Path(environment.get('MSYS2_ROOT', r'C:\msys64')) / 'clang64/bin'
        environment['PATH'] = str(dependencies) + os.pathsep + environment.get('PATH', '')
    return environment

if str(ROOT / 'scripts') not in sys.path:
    sys.path.insert(0, str(ROOT / 'scripts'))


def guest_self(sites):
    """What prepare.parse_self returns for a synthetic eboot.bin holding these (rva, bytes).

    The one load segment starts at file offset 0x4000 with RVA 0, as the real executable's
    does, so a check that reads RVAs straight from the ELF file offsets fails here too."""
    size = max(rva + len(data) for rva, data in sites) + 16
    elf = bytearray(0x4000 + size)
    for rva, data in sites:
        elf[0x4000 + rva:0x4000 + rva + len(data)] = data
    ph = [{'type': 1, 'flags': 5, 'offset': 0x4000, 'vaddr': 0, 'paddr': 0,
           'filesz': size, 'memsz': size, 'align': 0x4000}]
    return elf, None, ph, [], []
