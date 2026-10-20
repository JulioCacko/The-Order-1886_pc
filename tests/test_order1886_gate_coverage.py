"""The gates the project documents must be the gates CI enforces."""
from pathlib import Path
import json
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/order1886-go-preview.yml'
GO_README = ROOT / 'launcher-go/README.md'


def workflow_text():
    return WORKFLOW.read_text(encoding='utf-8')


class GateCoverageTests(unittest.TestCase):
    def test_the_workflow_enforces_gofmt(self):
        text = workflow_text()
        self.assertIn('gofmt -l .', text, 'gofmt is documented as a gate but not enforced')
        # A formatting failure must fail the job, not merely print.
        self.assertRegex(text, r'if \(\$unformatted\)[^\n]*exit 1')

    def test_the_workflow_runs_the_go_tests_with_the_race_detector(self):
        text = workflow_text()
        self.assertIn('go test ./... -race', text,
                      'the race detector is documented as a gate but never runs in CI')

    def test_the_workflow_still_runs_vet_and_the_go_tests(self):
        text = workflow_text()
        self.assertIn('go vet ./...', text)
        self.assertIn('go test ./...', text)

    def test_the_workflow_triggers_on_the_modules_the_worker_loads(self):
        # The worker imports several scripts/ modules lazily; a change to one must run these
        # checks rather than waiting for the next unrelated push.
        text = workflow_text()
        for trigger in ("- 'scripts/**'", "- 'tests/**'"):
            self.assertIn(trigger, text)

    def test_the_frontend_gates_are_enforced(self):
        text = workflow_text()
        # `npm run build` is `tsc --noEmit && vite build`, so the type check rides along.
        for command in ('npm ci', 'npm test', 'npm run build', 'npm audit --audit-level=high'):
            self.assertIn(command, text)
        package = json.loads((ROOT / 'launcher-go/frontend/package.json').read_text())
        self.assertIn('tsc --noEmit', package['scripts']['build'],
                      'the build script must still type-check before bundling')


if __name__ == '__main__':
    unittest.main()
