"""Readback policy travels from persisted Go/legacy settings to the native reader."""
import os
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import order1886
from launcher import order1886_launcher as launcher
from launcher import order1886_worker as worker

ROOT = Path(__file__).resolve().parents[1]


class ReadbackPolicyTests(unittest.TestCase):
    def test_catalog_persistence_command_and_environment_agree(self):
        for name, native in (('relaxed','1'),('selective','3'),('precise','2')):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                state=Path(temporary)
                runtime=state/'runtime.exe'
                runtime.write_bytes(b'native fixture')
                runtime.with_name('runtime-build.json').write_text(json.dumps({
                    'runtime_sha256':hashlib.sha256(runtime.read_bytes()).hexdigest(),
                    'game_profile':'order1886','runtime_abi':order1886.RUNTIME_ABI,
                    'readback_policies':['relaxed','precise','selective']}))
                app=worker.Worker(state, ROOT)
                app.dispatch('settings.set', {'values': {'runtime':str(runtime),'readbacks': name}})
                values=launcher.load_launch_settings(state)
                command=launcher.backend_command(values, state=state)
                self.assertEqual(command[command.index('--readbacks')+1], name)
                env=order1886.runtime_environment(runtime,state,values,
                                                {'ORDER1886_READBACKS':'0'})
                self.assertEqual(env['ORDER1886_READBACKS'], native)
        for invalid in ('disabled','unknown',True,3,None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                worker.validate_patch({'readbacks':invalid})
        with self.assertRaises(ValueError):
            order1886.runtime_environment(ROOT/'out/runtime.exe', ROOT/'out/state', {'readbacks':'unknown'})

    def test_default_keeps_existing_relaxed_behavior(self):
        self.assertEqual(launcher.load_launch_settings(ROOT/'out/state',{})['readbacks'],'relaxed')
        env=order1886.runtime_environment(ROOT/'out/runtime.exe',ROOT/'out/state',{}, {})
        self.assertEqual(env['ORDER1886_READBACKS'],'1')

    def test_selective_requires_hash_bound_native_support_and_preserves_saved_value(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            runtime=root/'runtime.exe'
            runtime.write_bytes(b'native fixture')
            receipt=runtime.with_name('runtime-build.json')
            build={'runtime_sha256':hashlib.sha256(runtime.read_bytes()).hexdigest(),
                   'game_profile':'order1886','runtime_abi':order1886.RUNTIME_ABI}
            receipt.write_text(json.dumps(build))
            app=worker.Worker(root/'user',ROOT)
            app.dispatch('settings.set',{'values':{'runtime':str(runtime),'readbacks':'relaxed'}})
            field=next(f for f in app.snapshot()['fields'] if f['key']=='readbacks')
            choice=next(c for c in field['choices'] if c['value']=='selective')
            self.assertFalse(choice['available'])
            self.assertTrue(choice['reason'])
            precise=next(c for c in field['choices'] if c['value']=='precise')
            self.assertFalse(precise['available'])
            with self.assertRaisesRegex(ValueError,'selective|Selective'):
                app.dispatch('settings.set',{'values':{'readbacks':'selective'}})
            self.assertEqual(app.settings()['readbacks'],'relaxed')
            with self.assertRaises(ValueError):
                app.dispatch('settings.set',{'values':{'readbacks':'precise'}})
            with self.assertRaises(ValueError):
                order1886.runtime_environment(runtime,root/'user',{'readbacks':'precise'}, {})
            build['readback_policies']=['relaxed','precise','selective']
            receipt.write_text(json.dumps(build))
            app.dispatch('settings.set',{'values':{'readbacks':'selective'}})
            self.assertEqual(app.settings()['readbacks'],'selective')
            runtime.write_bytes(b'changed binary')
            with self.assertRaises(ValueError):
                order1886.runtime_environment(runtime,root/'user',{'readbacks':'selective'}, {})

    def test_receipt_policy_list_must_be_typed(self):
        from unittest.mock import patch
        with patch.object(order1886,'runtime_identity',return_value={'build':{'readback_policies':'selective'}}):
            with self.assertRaises(ValueError):
                order1886.validate_readback_policy(ROOT/'fixture.exe','selective')

    def test_capabilities_refresh_when_receipt_metadata_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            runtime=root/'runtime.exe'
            runtime.write_bytes(b'native fixture')
            receipt=runtime.with_name('runtime-build.json')
            build={'runtime_sha256':hashlib.sha256(runtime.read_bytes()).hexdigest(),
                   'game_profile':'order1886','runtime_abi':order1886.RUNTIME_ABI,
                   'readback_policies':['relaxed','selective']}
            receipt.write_text(json.dumps(build))
            stamp=receipt.stat()
            app=worker.Worker(root/'user',ROOT)
            values={'runtime':str(runtime)}
            self.assertFalse(app.readback_policy_reason(values,'selective'))
            build['readback_policies']=['relaxed','unclaimed']
            receipt.write_text(json.dumps(build))
            os.utime(receipt,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
            self.assertEqual(receipt.stat().st_size,stamp.st_size)
            self.assertTrue(app.readback_policy_reason(values,'selective'))
            with self.assertRaises(ValueError):
                app.dispatch('settings.set',{'values':{**values,'readbacks':'selective'}})

    def test_default_capabilities_refresh_when_bin_shadows_out(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            name='order1886-runtime.exe' if os.name=='nt' else 'order1886-runtime'
            def native(folder, policies):
                folder.mkdir()
                runtime=folder/name
                runtime.write_bytes(folder.name.encode())
                runtime.with_name('runtime-build.json').write_text(json.dumps({
                    'runtime_sha256':hashlib.sha256(runtime.read_bytes()).hexdigest(),
                    'game_profile':'order1886','runtime_abi':order1886.RUNTIME_ABI,
                    'readback_policies':policies}))
            native(root/'out',[])
            with patch.object(order1886,'ROOT',root), patch.object(order1886,'INSTALL_ROOT',root), \
                 patch.object(launcher,'ROOT',root):
                app=worker.Worker(root/'user',root)
                self.assertTrue(app.readback_policy_reason({},'selective'))
                native(root/'bin',['relaxed','selective','precise'])
                self.assertFalse(app.readback_policy_reason({},'selective'))

    def test_native_page_protection_transitions_in_all_modes(self):
        environment=os.environ.copy()
        compiler=shutil.which(environment.get('CXX','clang++'))
        toolchain=Path(environment.get('MSYS2_ROOT',r'C:\msys64'))/'clang64'
        if not compiler and os.name=='nt':
            compiler=str(toolchain/'bin/clang++.exe')
        self.assertIsNotNone(compiler)
        environment['PATH']=str(Path(compiler).parent)+os.pathsep+environment.get('PATH','')
        with tempfile.TemporaryDirectory(prefix='order-readbacks-') as temporary:
            exe=Path(temporary)/('test.exe' if os.name=='nt' else 'test')
            command=[compiler,'-std=c++23','-O2','-UNDEBUG','-pthread',
                     '-I'+str(ROOT/'gpu/shim'),'-I'+str(ROOT/'gpu/shadps4'),
                     str(ROOT/'tests/test_selective_readbacks.cpp'),'-o',str(exe)]
            if os.name=='nt':
                command+=['-I'+str(toolchain/'include'),'-L'+str(toolchain/'lib'),'-lfmt']
            else:
                command+=['-lfmt']
            result=subprocess.run(command,env=environment,capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            for mode in (0,1,2,3,999):
                with self.subTest(mode=mode):
                    result=subprocess.run([str(exe)],env={**environment,'ORDER1886_READBACKS':str(mode)},
                                          capture_output=True,text=True,timeout=15)
                    self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':
    unittest.main()
