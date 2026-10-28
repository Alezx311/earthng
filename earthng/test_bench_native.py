"""Regression coverage for the ZIP reader used by the offline Lua harness."""
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import bench_native


class BenchZipReaderTest(unittest.TestCase):
    def test_chunked_reads_advance_and_stop_at_eof(self):
        payload = b'a' * 262144 + b'last'
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp) / 'pack.zip'
            with zipfile.ZipFile(pack, 'w') as archive:
                archive.writestr('block.bin', payload)
            with zipfile.ZipFile(pack) as reader:
                with patch.object(bench_native.zipfile, 'ZipFile', return_value=reader):
                    lua, _, _ = bench_native.runtime(pack)
                    sizes = lua.execute('''
                      local f=io.open('/block.bin', 'rb')
                      local first, second, eof=f:read(262144), f:read(262144), f:read(262144)
                      local all=io.open('/block.bin', 'rb'):read('*a')
                      return #first, #second, eof == nil, #all
                    ''')
            self.assertEqual(sizes, (262144, 4, True, len(payload)))


if __name__ == '__main__':
    unittest.main()
