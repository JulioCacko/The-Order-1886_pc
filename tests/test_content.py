from paths import ROOT
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

EXE=ROOT/('out/content-test.exe' if sys.platform=='win32' else 'out/content-test')

def sfo_fixture(entries):
    keys=bytearray(); values=bytearray(); indexes=bytearray()
    for key,value in entries.items():
        key_offset=len(keys); keys.extend(key.encode()+b'\0')
        raw=struct.pack('<I',value) if type(value) is int else value.encode()+b'\0'
        maximum=(len(raw)+3)&~3
        indexes.extend(struct.pack('<HHIII',key_offset,0x404 if type(value) is int else 0x204,len(raw),maximum,len(values)))
        values.extend(raw+b'\0'*(maximum-len(raw)))
    key_start=20+len(indexes); value_start=(key_start+len(keys)+3)&~3
    return struct.pack('<4sIIII',b'\0PSF',0x101,key_start,value_start,len(entries))+indexes+keys+b'\0'*(value_start-key_start-len(keys))+values

@unittest.skipUnless(EXE.exists(),'run bash build.sh --test first')
class ContentTests(unittest.TestCase):
    def run_case(self,*args):
        return subprocess.run([str(EXE.resolve()),*args],capture_output=True,text=True,timeout=5)

    def test_lifecycle_and_output_boundaries(self):
        r=self.run_case();self.assertEqual(r.returncode,0,r.stdout+r.stderr)

    def test_missing_metadata_returns_an_api_error(self):
        r=self.run_case('--missing');self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertIn('absent metadata returns parameter error',r.stdout)

    def test_other_modules_are_counted_independently(self):
        r=self.run_case('--unknown');self.assertEqual(r.returncode,0,r.stdout+r.stderr)

    def test_fatal_metadata_error_flushes_and_skips_cleanup(self):
        r=self.run_case('--late');self.assertEqual(r.returncode,1,r.stdout+r.stderr)
        self.assertIn('invalid or late AppContent metadata',r.stderr)
        self.assertNotIn('unexpected fatal cleanup',r.stderr)

    def run_sfo(self,data):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'param.sfo';path.write_bytes(data)
            return self.run_case('--sfo',str(path))

    def test_sfo_native_metadata_and_missing_defaults(self):
        r=self.run_sfo(sfo_fixture({'TITLE_ID':'CUSA00076','USER_DEFINED_PARAM_1':13,'USER_DEFINED_PARAM_2':0x80000000,'USER_DEFINED_PARAM_4':0xffffffff}))
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        for value in ('parameter 0 = 3','parameter 1 = 13','parameter 2 = -2147483648','parameter 3 = 0','parameter 4 = -1'):
            self.assertIn(value,r.stdout)
        r=self.run_sfo(sfo_fixture({'TITLE_ID':'CUSA00076','USER_DEFINED_PARAM_1':'13'}))
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        for index in range(1,5): self.assertIn(f'parameter {index} = 0',r.stdout)

    def test_native_sfo_bounds_reject_corrupt_tables_and_strings(self):
        good=sfo_fixture({'TITLE_ID':'CUSA00076','USER_DEFINED_PARAM_1':13})
        cases=[good[:19],good+b'\0'*65536]
        for offset,value in ((12,0xfffffff0),(16,0xffffffff),(24,0xffffffff),(48,0xfffffff0)):
            bad=bytearray(good);struct.pack_into('<I',bad,offset,value);cases.append(bad)
        keys,values=struct.unpack_from('<II',good,8)
        bad=bytearray(good);bad[keys:values]=b'x'*(values-keys);cases.append(bad)
        bad=bytearray(good);bad[values:values+12]=b'x'*12;cases.append(bad)
        for index,data in enumerate(cases):
            with self.subTest(case=index):
                r=self.run_sfo(data);self.assertEqual(r.returncode,2,r.stdout+r.stderr)
                self.assertIn('Rejected SFO metadata',r.stderr)

    @unittest.skipUnless((ROOT/'ShadPs4Plus-PkgExtractor-1.1-windows/CUSA00076/sce_sys/param.sfo').exists(),'local Order installation unavailable')
    def test_actual_order_sfo_through_native_configuration(self):
        r=self.run_case('--sfo',str(ROOT/'ShadPs4Plus-PkgExtractor-1.1-windows/CUSA00076/sce_sys/param.sfo'))
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertIn('SFO CUSA00076: SKU=3 (reference compatibility value)',r.stdout)
        for index in range(1,5): self.assertIn(f'parameter {index} = 0',r.stdout)
