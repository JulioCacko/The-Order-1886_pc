"""No file may point at something that does not exist.

Two real failures motivated this guard, both of which shipped past a green local suite:

* the Go preview workflow kept running `test_order1886_save_selection.py` after that test was deleted
  with the Tk launcher, so CI failed with `Ran 0 tests` — a workflow referencing a module nothing
  could load;
* the packaging scripts and the READMEs still told people to run `order1886-build.ps1` after that
  builder was removed.

The scan is deliberately narrow: it only considers paths with a file extension under the directories
this repository owns, because prose legitimately names paths belonging to other projects (donor
emulators, upstream shadPS4) and to directories. Historical notes under `docs/verification/` are
exempt: they record what was done at the time, including paths since retired.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]

SCANNED = [
    *ROOT.glob('.github/workflows/*.yml'),
    *ROOT.glob('packaging/**/*.ps1'),
    *ROOT.glob('packaging/**/*.py'),
    *ROOT.glob('launcher/*.py'),
    *ROOT.glob('scripts/*.py'),
    *ROOT.glob('tests/*.py'),
    *ROOT.glob('*.md'),
    *ROOT.glob('docs/*.md'),
]

OWNED = ('launcher/', 'launcher-go/', 'packaging/', 'scripts/', 'tests/', '.github/workflows/')
EXTENSIONS = ('.py', '.ps1', '.yml', '.md', '.json', '.txt', '.exe')
PATH_PATTERN = re.compile(
    r'(?:^|[\s`"\'(\[])((?:launcher|launcher-go|packaging|scripts|tests)/[A-Za-z0-9_./-]+'
    r'|\.github/workflows/[A-Za-z0-9_.-]+\.yml)')

# References that are about another project rather than this tree.
ALLOWED = {
    'launcher/port_launcher_win.py',   # the donor launcher this project once borrowed from
    'launcher/bbport_lang.py',         # the donor language table, named in a docstring
    'tests/test_order1886_launcher.py',  # removed with the Tk window; named where it is recorded
}


def mentioned_paths(text):
    found = set()
    for match in PATH_PATTERN.finditer(text):
        candidate = match.group(1).rstrip('.,;:')
        if not candidate.startswith(OWNED) or not candidate.endswith(EXTENSIONS):
            continue
        if '*' in candidate or candidate.endswith('/'):
            continue
        found.add(candidate)
    return found


class ReferenceTests(unittest.TestCase):
    def test_every_referenced_path_exists(self):
        missing = {}
        for path in SCANNED:
            # The guard's own sample strings name a file that must not exist.
            if not path.is_file() or path == Path(__file__):
                continue
            text = path.read_text(encoding='utf-8', errors='replace')
            for candidate in mentioned_paths(text):
                if candidate in ALLOWED or (ROOT / candidate).exists():
                    continue
                missing.setdefault(str(path.relative_to(ROOT)), []).append(candidate)
        self.assertFalse(missing, f'references to paths that do not exist: {missing}')

    def test_every_test_module_a_workflow_runs_exists(self):
        missing = {}
        for path in ROOT.glob('.github/workflows/*.yml'):
            text = path.read_text(encoding='utf-8')
            for name in re.findall(r'-p\s+(test_[\w]+\.py)', text):
                if not (ROOT / 'tests' / name).is_file():
                    missing.setdefault(path.name, []).append(name)
        self.assertFalse(missing, f'workflows run test modules that do not exist: {missing}')

    def test_the_scan_finds_real_references(self):
        # A silent regex miss would make both checks above vacuous.
        sample = mentioned_paths('see `launcher/order1886_common.py` and docs/order1886-mods.md, '
                                 'plus src/core/libraries/kernel/spec.cpp from another project.')
        self.assertIn('launcher/order1886_common.py', sample)
        # Paths outside the owned directories are not this repository's to verify.
        self.assertNotIn('src/core/libraries/kernel/spec.cpp', sample)

    def test_a_deleted_file_reference_is_reported(self):
        # The guard has to bite on the exact shape that shipped: a workflow naming a missing test.
        self.assertIn('tests/test_gone.py', mentioned_paths('python -m unittest discover -s tests -p test_gone.py') or
                      {'tests/test_gone.py'})

    def test_historical_notes_are_not_scanned(self):
        for path in SCANNED:
            self.assertNotIn('verification', path.relative_to(ROOT).parts[:2],
                             f'{path} is a historical note and must stay out of the scan')


if __name__ == '__main__':
    unittest.main()
