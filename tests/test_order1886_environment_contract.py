"""Every variable the launcher exports must be one the runtime reads.

This is the same class of defect the settings audit found twice: a value exported with care
into a process that never looks at it. The two sides are written in different languages, so
compare them mechanically instead of by memory.

Only one direction is a defect. A variable the runtime reads but the launcher does not set is
usually a hand-set diagnostic knob (`ORDER1886_DUMP_*`, `ORDER1886_VK_*`, `ORDER1886_PIPE_*`)
and deliberately stays out of the launcher; an exported variable nothing reads is dead weight
that looks like a feature.

Note where the reads live: `src/` is the native runtime's C layer, `gpu/` its C++ layers. A
scanner that only looked at `gpu/` (as the first version of this test did) reported five false
positives, all of them read in `src/`.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_SIDE = [ROOT / 'order1886.py', ROOT / 'launcher/order1886_common.py',
                 ROOT / 'launcher/order1886_worker.py']
RUNTIME_ROOTS = [ROOT / 'src', ROOT / 'gpu']
RUNTIME_SUFFIXES = ('.c', '.h', '.cpp', '.hpp', '.cc')

# Exported for a reason other than the runtime reading it.
LAUNCHER_ONLY = {
    'ORDER1886_USER_DIR',      # the child's working directory, not a runtime lookup
    'ORDER1886_MENU_CONFIG',   # read by the settings menu's own file handling
}


def launcher_names():
    names = set()
    for path in LAUNCHER_SIDE:
        names |= set(re.findall(r'ORDER1886_[A-Z0-9_]+', path.read_text(encoding='utf-8')))
    return names


def runtime_names():
    names = set()
    for root in RUNTIME_ROOTS:
        for path in root.rglob('*'):
            if path.suffix in RUNTIME_SUFFIXES:
                names |= set(re.findall(r'ORDER1886_[A-Z0-9_]+',
                                        path.read_text(encoding='utf-8', errors='replace')))
    return names


class EnvironmentContractTests(unittest.TestCase):
    def test_no_exporter_sets_a_variable_the_runtime_ignores(self):
        exported = launcher_names() - LAUNCHER_ONLY
        dead = sorted(name for name in exported if name not in runtime_names())
        self.assertFalse(dead, f'the launcher exports variables nothing reads: {dead}')

    def test_the_scan_reads_both_layers_of_the_runtime(self):
        # A silent miss in one tree is exactly how the first version of this test lied.
        names = runtime_names()
        self.assertIn('ORDER1886_LANGUAGE', names, 'src/ was not scanned')
        self.assertIn('ORDER1886_HTILE', names, 'gpu/ was not scanned')
        self.assertIn('ORDER1886_LANGUAGE', launcher_names())

    def test_the_variables_the_environment_builder_returns_are_all_exported_by_the_launcher(self):
        import order1886
        settings = {'keyboard_bindings': {}, 'controller_bindings': {}}
        env = order1886.runtime_environment(ROOT / 'out' / 'runtime.exe', ROOT / 'out' / 'state',
                                            settings, {})
        produced = {name for name in env if name.startswith('ORDER1886_')}
        self.assertIn('ORDER1886_USER_DIR', produced)
        for name in sorted(produced):
            self.assertIn(name, launcher_names() | {'ORDER1886_MENU_CONFIG'},
                          f'{name} is produced but not named in the launcher sources')


if __name__ == '__main__':
    unittest.main()
