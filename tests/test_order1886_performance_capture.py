"""Player-requested recording reaches real frame tracing without ambient diagnostic overrides."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import order1886
from launcher import order1886_common as legacy
from launcher import order1886_worker as worker
from launcher.order1886_lang import LANGUAGES, table
import test_order1886_read_backing as native

ROOT = Path(__file__).resolve().parents[1]


class PerformanceCaptureTests(unittest.TestCase):
    def test_recording_copy_is_localized_in_all_thirteen_catalogs(self):
        field = next(f for f in worker.FIELDS if f['key'] == 'performance_capture')
        for locale in LANGUAGES:
            for text in (field['label'], field['description']):
                with self.subTest(locale=locale, text=text):
                    self.assertIn(text, table(locale))
                    if locale != 'en':
                        self.assertNotEqual(table(locale)[text], text)

    def fixture(self, root, capable=True):
        runtime = root / 'runtime.exe'
        runtime.write_bytes(b'native performance fixture')
        receipt = runtime.with_name('runtime-build.json')
        build = {'runtime_sha256': hashlib.sha256(runtime.read_bytes()).hexdigest(),
                 'game_profile': 'order1886', 'runtime_abi': order1886.RUNTIME_ABI,
                 'performance_capture': capable}
        receipt.write_text(json.dumps(build), encoding='utf-8')
        return runtime

    def test_visible_setting_persistence_cli_and_unique_trace_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = self.fixture(root)
            state = root / 'Ordém 日本' / 'user'
            app = worker.Worker(state, ROOT)
            app.dispatch('settings.set', {'values': {'runtime': str(runtime), 'performance_capture': True}})
            values = legacy.load_launch_settings(state)
            self.assertIs(values['performance_capture'], True)
            field = next(f for f in app.snapshot()['fields'] if f['key'] == 'performance_capture')
            self.assertTrue(field['available'])
            self.assertEqual(field['page'], 'system')
            self.assertEqual(field['apply'], 'next_launch')
            command = legacy.backend_command(values, state=state)
            self.assertEqual(command[command.index('--performance-capture') + 1], '1')
            first = order1886.runtime_environment(runtime, state, values, {})
            second = order1886.runtime_environment(runtime, state, values, {})
            self.assertEqual(first['ORDER1886_FRAME_STATS'], '1')
            trace = Path(first['ORDER1886_FRAME_TRACE'])
            self.assertEqual(trace.parent, state.resolve() / 'logs')
            self.assertEqual(trace.suffix, '.csv')
            self.assertNotEqual(trace, Path(second['ORDER1886_FRAME_TRACE']))
            app.dispatch('settings.set', {'values': {'performance_capture': False}})
            self.assertIs(legacy.load_launch_settings(state)['performance_capture'], False)

    def test_unsupported_recording_is_visible_and_cannot_replace_previous_value(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = self.fixture(root, capable=False)
            app = worker.Worker(root / 'user', ROOT)
            app.dispatch('settings.set', {'values': {'runtime': str(runtime)}})
            field = next(f for f in app.snapshot()['fields'] if f['key'] == 'performance_capture')
            self.assertFalse(field['available'])
            self.assertTrue(field['reason'])
            with self.assertRaises(ValueError):
                app.dispatch('settings.set', {'values': {'performance_capture': True}})
            self.assertIs(app.settings()['performance_capture'], False)
            with self.assertRaises(ValueError):
                order1886.runtime_environment(runtime, root / 'user', {'performance_capture': True})
            # A runtime replaced outside the launcher must still allow turning recording off.
            (root / 'user/settings.json').write_text(json.dumps({'runtime': str(runtime), 'performance_capture': True}))
            app.dispatch('settings.set', {'values': {'performance_capture': False}})

    def test_default_off_removes_inherited_recording_and_rejects_invalid_values(self):
        environment = order1886.runtime_environment(ROOT / 'fixture.exe', ROOT / 'out/state', {},
            {'ORDER1886_FRAME_STATS': '1', 'ORDER1886_FRAME_TRACE': 'outside.csv'})
        self.assertNotIn('ORDER1886_FRAME_TRACE', environment)
        self.assertNotIn('ORDER1886_FRAME_STATS', environment)
        for invalid in ('true', 2, None, []):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                order1886.runtime_environment(ROOT / 'fixture.exe', ROOT / 'out/state',
                                              {'performance_capture': invalid})

    def test_runtime_replaced_during_capability_validation_does_not_cache_old_support(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = self.fixture(root)
            receipt = runtime.with_name('runtime-build.json')
            app = worker.Worker(root / 'user', ROOT)
            validate = order1886.validate_performance_capture
            def replace_after_validation(path, enabled):
                validate(path, enabled)
                build = json.loads(receipt.read_text())
                build['performance_capture'] = False
                receipt.write_text(json.dumps(build))
            with patch.object(order1886, 'validate_performance_capture', side_effect=replace_after_validation):
                self.assertTrue(app.native_option_reason({'runtime': str(runtime)}, 'performance_capture'))
            with self.assertRaises(ValueError):
                app.dispatch('settings.set', {'values': {'runtime': str(runtime), 'performance_capture': True}})
            self.assertIs(app.settings()['performance_capture'], False)

    def test_stale_native_options_can_be_repaired_one_at_a_time_in_either_order(self):
        repairs = (('readbacks', 'relaxed'), ('performance_capture', False))
        for sequence in (repairs, repairs[::-1]):
            with self.subTest(sequence=sequence), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                runtime = self.fixture(root)
                receipt = runtime.with_name('runtime-build.json')
                build = json.loads(receipt.read_text())
                build['readback_policies'] = ['relaxed', 'precise']
                receipt.write_text(json.dumps(build))
                app = worker.Worker(root / 'user', ROOT)
                app.dispatch('settings.set', {'values': {'runtime': str(runtime),
                    'readbacks': 'precise', 'performance_capture': True}})
                runtime.write_bytes(b'older native fixture')
                build.update(runtime_sha256=hashlib.sha256(runtime.read_bytes()).hexdigest(),
                             readback_policies=['relaxed'], performance_capture=False)
                receipt.write_text(json.dumps(build))
                with self.assertRaises(ValueError):
                    app.dispatch('settings.set', {'values': {'runtime': str(runtime)}})
                key, value = sequence[0]
                app.dispatch('settings.set', {'values': {key: value}})
                self.assertEqual(app.settings()[key], value)
                with self.assertRaises(ValueError):
                    order1886.runtime_environment(runtime, root / 'user', app.settings())
                key, value = sequence[1]
                app.dispatch('settings.set', {'values': {key: value}})
                environment = order1886.runtime_environment(runtime, root / 'user', app.settings())
                self.assertEqual(environment['ORDER1886_READBACKS'], '1')
                self.assertNotIn('ORDER1886_FRAME_TRACE', environment)

    def test_native_trace_records_unicode_paths_and_preserves_existing_files(self):
        header = (ROOT / 'gpu/shim/ps4_frame_trace.h').as_posix()
        native.ReadBackingTests().compile_and_run('#include "' + header + '"\n' + r'''
#include <cassert>
#include <chrono>
#include <filesystem>
#include <fstream>
int main() {
    namespace fs=std::filesystem;
    const auto directory=fs::temp_directory_path()/("order-trace-"+std::to_string(
        std::chrono::steady_clock::now().time_since_epoch().count()));
    assert(fs::create_directory(directory));
    const auto path=directory/fs::path(u8"Ordém_日本_记录-é.csv");
    const auto encoded=path.u8string();
    {
        Ps4PerfStats::FrameTrace trace(reinterpret_cast<const char*>(encoded.c_str()));
        assert(trace.Enabled());
        trace.Record("host_present",100,1,0,false);
    }
    const auto size=fs::file_size(path);
    {
        Ps4PerfStats::FrameTrace duplicate(reinterpret_cast<const char*>(encoded.c_str()));
        assert(!duplicate.Enabled());
    }
    assert(fs::file_size(path)==size);
    std::ifstream input(path); std::string header,row;
    assert(std::getline(input,header) && std::getline(input,row));
    assert(row=="host_present,100,1,0,0"); input.close();
    assert(fs::remove(path) && fs::remove(directory));
}
''', cxx=True)


if __name__ == '__main__':
    unittest.main()
