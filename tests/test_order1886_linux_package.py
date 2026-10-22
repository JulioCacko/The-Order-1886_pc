# SPDX-License-Identifier: GPL-2.0-or-later
"""Which libraries the Linux package bundles and which it leaves to the system."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('order1886_go_package', ROOT / 'packaging/linux/order1886-go-package.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class SystemLibraryTests(unittest.TestCase):
    def test_desktop_stack_comes_from_the_system(self):
        for name in ('libc.so.6', 'libstdc++.so.6', 'ld-linux-x86-64.so.2', 'libvulkan.so.1',
                     'libX11.so.6', 'libXext.so.6', 'libxcb.so.1', 'libxkbcommon.so.0',
                     'libwayland-client.so.0', 'libGL.so.1', 'libdrm.so.2', 'libasound.so.2'):
            self.assertTrue(package.SYSTEM_LIBRARY.match(name), name)

    def test_codecs_and_build_host_libraries_are_bundled(self):
        # libx264/libx265/libxml2 once matched an X11 pattern and were left out (Ubuntu 26.04 has none).
        for name in ('libx264.so.164', 'libx265.so.199', 'libxml2.so.2', 'libavcodec.so.60',
                     'libSDL3.so.0', 'libfmt.so.9', 'libZydis.so.4.0', 'libZycore.so.1.4',
                     'libva.so.2', 'libva-drm.so.2', 'libva-x11.so.2', 'libvdpau.so.1'):
            self.assertFalse(package.SYSTEM_LIBRARY.match(name), name)


if __name__ == '__main__':
    unittest.main()
