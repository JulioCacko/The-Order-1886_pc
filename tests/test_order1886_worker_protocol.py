"""One bad request must never kill the worker, and the protocol guards must stay in place."""
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from launcher import order1886_worker as worker

ROOT = Path(__file__).resolve().parents[1]


def request(method, params, identifier=1):
    return {'version': 1, 'id': identifier, 'method': method, 'params': params}


def run(requests, fake=None):
    source = StringIO(''.join(json.dumps(item) + '\n' for item in requests))
    output = StringIO()
    served = fake or worker.Worker(Path(tempfile.mkdtemp()), ROOT)
    worker.serve(served, source, output)
    return served, [json.loads(line) for line in output.getvalue().splitlines() if line.strip()]


class UnexpectedFailure:
    """A worker whose method raises outside the caught exception types, as a real bug would."""

    def __init__(self):
        self.emit = None
        self.calls = []

    def dispatch(self, method, params):
        self.calls.append(method)
        if method == 'state.get':
            return {'ok': True}
        raise AttributeError("'NoneType' object has no attribute 'get'")

    def close(self):
        pass


class ProtocolGuardTests(unittest.TestCase):
    def test_params_that_are_not_an_object_are_refused_and_the_worker_keeps_answering(self):
        for bad in ('oops', ['values'], 7, None):
            with self.subTest(params=bad):
                _, replies = run([request('settings.set', bad), request('state.get', {}, 2)])
                self.assertEqual(len(replies), 2, f'{bad!r} ended the request loop')
                self.assertIn('error', replies[0])

    def test_an_unknown_method_is_refused(self):
        _, replies = run([request('does.not.exist', {}), request('state.get', {}, 2)])
        self.assertIn('error', replies[0])
        self.assertIn('method', replies[0]['error']['message'].lower())

    def test_the_real_worker_refuses_a_method_outside_the_allowlist(self):
        with tempfile.TemporaryDirectory() as temporary:
            served = worker.Worker(Path(temporary), ROOT)
            with self.assertRaisesRegex(ValueError, 'Unknown worker method'):
                served.dispatch('does.not.exist', {})

    def test_the_real_worker_refuses_params_that_are_not_an_object(self):
        with tempfile.TemporaryDirectory() as temporary:
            served = worker.Worker(Path(temporary), ROOT)
            for bad in ('oops', ['values'], 7, None):
                with self.subTest(params=bad), self.assertRaisesRegex(ValueError, 'must be an object'):
                    served.dispatch('state.get', bad)


class UnexpectedFailureTests(unittest.TestCase):
    def test_an_unexpected_exception_answers_with_an_error_instead_of_killing_the_worker(self):
        fake = UnexpectedFailure()
        _, replies = run([request('patches.list', {}), request('state.get', {}, 2)], fake=fake)
        self.assertEqual(len(replies), 2, 'one failing method ended the request loop')
        self.assertIn('error', replies[0])
        self.assertEqual(replies[1]['result'], {'ok': True}, 'the worker stopped answering')


class StateWriteLockTests(unittest.TestCase):
    """A state write must hold the OS session lock, which is the only thing that also
    excludes a direct-play game or another launcher — `require_idle` cannot see those."""

    def test_settings_are_refused_while_another_session_holds_the_lock(self):
        import order1886
        with tempfile.TemporaryDirectory() as temporary:
            served = worker.Worker(Path(temporary), ROOT)
            with order1886.session_lock(Path(temporary)):
                with self.assertRaisesRegex(RuntimeError, 'already running or being prepared'):
                    served.dispatch('settings.set', {'values': {'vsync': False}})

    def test_the_lock_is_released_after_the_write(self):
        import order1886
        with tempfile.TemporaryDirectory() as temporary:
            served = worker.Worker(Path(temporary), ROOT)
            served.dispatch('settings.set', {'values': {'vsync': False}})
            # A second writer must be able to take the lock immediately afterwards.
            with order1886.session_lock(Path(temporary)):
                pass

    def test_a_nested_use_does_not_deadlock(self):
        with tempfile.TemporaryDirectory() as temporary:
            served = worker.Worker(Path(temporary), ROOT)
            with served.state_lock():
                self.assertIs(served.settings()['vsync'], True)
                with served.state_lock():
                    pass


if __name__ == '__main__':
    unittest.main()
