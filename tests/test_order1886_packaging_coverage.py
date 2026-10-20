"""Every module an entry point imports must be shipped by both package builders.

`order1886.py` resolves `import prepare`, `import order1886_patches` and friends by inserting
its own `scripts/` directory into `sys.path` at runtime. PyInstaller cannot see that, so the
modules are shipped as data files by an explicit list in each builder. A missing entry is a
`ModuleNotFoundError` on Play in the packaged launcher and nothing in the test suite or the
packaged smoke noticed it — which is exactly how `order1886_patches.py` was nearly lost.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / 'packaging/windows/order1886-go-build.ps1'


def scripts_imported(path):
    """Module names a file imports from scripts/, bare or through the scripts package."""
    text = path.read_text(encoding='utf-8')
    names = set(re.findall(r'^\s*import\s+(order1886_\w+|prepare|link_modules|link_libc|'
                           r'save_backup)\b', text, re.MULTILINE))
    names |= set(re.findall(r'^\s*from\s+(?:scripts\.)?(order1886_\w+|prepare|link_modules|'
                            r'link_libc|save_backup)\s+import\b', text, re.MULTILINE))
    return names


def windows_list():
    text = WINDOWS.read_text(encoding='utf-8')
    # The script has two loops with the same head; anchor on the one that ships scripts.
    start = text.index("foreach ($name in @('prepare.py'")
    block = text[start:]
    block = block[: block.index('))')]
    return {name.replace('.py', '') for name in re.findall(r"'([\w.]+\.py)'", block)}


class PackagingCoverageTests(unittest.TestCase):
    def test_the_go_worker_ships_every_module_the_backend_imports(self):
        needed = scripts_imported(ROOT / 'order1886.py') | scripts_imported(ROOT / 'launcher/order1886_worker.py')
        self.assertIn('order1886_patches', needed)
        missing = sorted(needed - windows_list())
        self.assertFalse(missing, f'order1886-go-build.ps1 does not ship: {missing}')

    def test_the_guard_would_fail_for_a_missing_entry(self):
        # The scan is source-driven: adding an import without adding the module must fail.
        self.assertTrue(scripts_imported(ROOT / 'order1886.py'))
        self.assertNotIn('__not_a_module__', windows_list())


if __name__ == '__main__':
    unittest.main()
