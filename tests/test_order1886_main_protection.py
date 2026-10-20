"""main is protected by a pull request, on the server and in the checkout.

Twice this repository took a direct commit on main by accident, once with a documentation change and
once with a feature branch, and both times main was briefly ahead of what anyone had reviewed. The
GitHub ruleset is the real guard; this test keeps the local half from being deleted or weakened, and
records how to enable it in a fresh checkout.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / 'scripts/git-hooks/pre-push'


class MainProtectionTests(unittest.TestCase):
    def test_the_hook_exists_and_is_a_shell_script(self):
        self.assertTrue(HOOK.is_file(), 'the pre-push hook is missing')
        text = HOOK.read_text(encoding='utf-8')
        self.assertTrue(text.startswith('#!/bin/sh'), 'the hook must stay a POSIX shell script')

    def test_the_hook_refuses_a_push_to_main(self):
        text = HOOK.read_text(encoding='utf-8')
        self.assertIn('protected=main', text)
        self.assertIn('refs/heads/"$protected"', text)
        self.assertRegex(text, r'exit 1', 'the hook must fail the push, not warn about it')
        self.assertIn('refusing a direct push', text)

    def test_the_hook_has_one_documented_escape_hatch(self):
        text = HOOK.read_text(encoding='utf-8')
        self.assertIn('ALLOW_MAIN_PUSH', text)
        # The override is read from the environment, never from a file, so it cannot be left on.
        self.assertIn('allow=${ALLOW_MAIN_PUSH:-}', text)
        self.assertIsNone(re.search(r'ORDER1886_.*MAIN', text))

    def test_the_hook_explains_how_to_enable_it(self):
        text = HOOK.read_text(encoding='utf-8')
        self.assertIn('git config core.hooksPath scripts/git-hooks', text)


if __name__ == '__main__':
    unittest.main()
