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
