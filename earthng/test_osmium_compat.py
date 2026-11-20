"""A non-ASCII Windows profile must not break PBF readers/writers in a fresh process."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class OsmiumPathTests(unittest.TestCase):
    def test_unicode_paths_in_a_fresh_builder_process(self):
        with tempfile.TemporaryDirectory(prefix='EarthNG_Україна_日本語_') as tmp:
            target = Path(tmp) / 'вхід.osm.pbf'
            script = '''
import locale, sys
sys.path.insert(0, sys.argv[1])
locale.setlocale(locale.LC_CTYPE, 'C')
numeric = locale.setlocale(locale.LC_NUMERIC)
from osmium_compat import osmium
assert locale.setlocale(locale.LC_NUMERIC) == numeric
with osmium.SimpleWriter(sys.argv[2]) as writer:
    writer.add_node(osmium.osm.mutable.Node(id=1, location=(30.5, 50.4), tags={'name':'Town'}))
assert [n.id for n in osmium.FileProcessor(sys.argv[2])] == [1]
with osmium.io.Reader(sys.argv[2]) as reader:
    reader.header()
'''
            result = subprocess.run([sys.executable, '-X', 'utf8', '-c', script,
                str(Path(__file__).parent), str(target)], capture_output=True, text=True, encoding='utf8')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(target.is_file())
