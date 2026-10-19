"""Host copies must bypass guest read protection without losing sparse semantics."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReadBackingTests(unittest.TestCase):
    def compile_and_run(self, source, cxx=False):
        environment = os.environ.copy()
        compiler = shutil.which(environment.get('CXX' if cxx else 'CC', 'clang++' if cxx else 'clang'))
        if not compiler and os.name == 'nt':
            compiler = str(Path(environment.get('MSYS2_ROOT', r'C:\msys64')) /
                           'clang64/bin' / ('clang++.exe' if cxx else 'clang.exe'))
        self.assertIsNotNone(compiler)
        environment['PATH'] = str(Path(compiler).parent) + os.pathsep + environment.get('PATH', '')
        with tempfile.TemporaryDirectory(prefix='order-backing-') as temporary:
            directory = Path(temporary)
            exe = directory / ('read.exe' if os.name == 'nt' else 'read')
            if isinstance(source, str):
                source_path = directory / 'shim.cpp'
                source_path.write_text(source, encoding='utf-8')
            else:
                source_path = source
            command = [compiler, '-std=c++23' if cxx else '-std=c11', '-O2', '-UNDEBUG',
                       '-Wall', '-Wextra', '-Werror', '-pthread', '-I' + str(ROOT / 'src'), str(source_path)]
            if os.name == 'nt' and not cxx:
                command += [str(ROOT / 'src/compat_win.c'), '-lonecore', '-lws2_32']
            result = subprocess.run(command + ['-o', str(exe)], env=environment,
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(exe)], env=environment, capture_output=True,
                                    text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_sparse_protected_reads_and_mapping_lifetime(self):
        self.compile_and_run(ROOT / 'tests/test_memory_read_backing.c')

    def test_actual_upload_copy_uses_backing_interface(self):
        text = (ROOT / 'gpu/shim/ps4gpu.cpp').read_text(encoding='utf-8')
        copy = text[text.index('static void CopySparseSerial('):
                    text.index('void MemoryManager::CopySparseMemory(')]
        self.compile_and_run(r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstring>
using VAddr=uintptr_t; using u8=uint8_t; using u64=uint64_t;
static unsigned calls;
[[maybe_unused]] static int runtime_memory_region(uintptr_t address,uintptr_t *start,
                                                uintptr_t *end,int *mapped) {
    *start=address; *end=address+17; *mapped=1; return 1;
}
[[maybe_unused]] static void runtime_memory_read_backing(uintptr_t address,void *out,uint64_t size) {
    assert(address==0x12340000 && size==17);
    ++calls; std::memset(out,0x42,size);
}
''' + copy + r'''
int main() {
    u8 out[17]{};
    CopySparseSerial(0x12340000,out,sizeof(out));
    assert(calls==1);
    for (u8 value:out) assert(value==0x42);
}
''', cxx=True)


if __name__ == '__main__':
    unittest.main()
