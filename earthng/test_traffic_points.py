"""Surveyed traffic features survive the source reader and binary cell format."""
from collections import OrderedDict
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lupa.luajit21 import LuaRuntime
import country_format
import fast_sources


class TrafficPointTests(unittest.TestCase):
    def test_source_nodes_and_tags_reach_binary_and_tile_halo(self):
        xml = '''<osm version="0.6">
          <node id="1" lat="50.0" lon="30.0"><tag k="highway" v="traffic_signals"/>
            <tag k="traffic_signals:direction" v="forward"/></node>
          <node id="2" lat="50.001" lon="30.001"><tag k="traffic_sign" v="UA:2.1"/>
            <tag k="direction" v="backward"/></node></osm>'''
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'source.osm'
            path.write_text(xml, encoding='utf8')
            class Frame:
                def geo_bbox(self, rect): return rect
                def local(self, x, y): return x, y
            store = object.__new__(fast_sources.Store)
            store.frame, store.scenes, store.source_index = Frame(), OrderedDict(), {}
            store.meta = {'source': folder}
            with patch('osm_tiles.tile_for', return_value=('tile', {'file': path.name})):
                records = store.scenery([29.9, 49.9, 30.1, 50.1])
            found = {kind: data['tags'] for _, kind, data, _ in records}
            self.assertEqual(found['signal']['traffic_signals:direction'], 'forward')
            self.assertEqual(found['traffic_sign']['traffic_sign'], 'UA:2.1')
            points = [{'id': kind, 'kind': kind, 'tags': tags, 'pos': [510, 250, 0]}
                      for kind, tags in found.items()]
            cell = {'terrain': {'nx': 2, 'ny': 2, 'heights': [0] * 4}, 'points': points}
            blob = country_format.encode_cell(cell, (0, 0))
            decoded = country_format.decode_cell(blob, (0, 0), [0, 0, 1000, 1000])
            self.assertEqual({p['kind'] for p in decoded['points']}, {'signal', 'traffic_sign'})
            lua = LuaRuntime(unpack_returned_tuples=True, encoding=None)
            decoder = lua.execute((Path(__file__).resolve().parents[1] /
                                   'mod/lua/ge/extensions/e2r/cellformat.lua').read_bytes())
            rect = lua.table_from([0, 0, 1000, 1000])
            keep = lua.table_from([0, 0, 500, 500])
            tile = decoder[b'cell'](blob, 1, len(blob), 0, 0, rect, None, keep)
            self.assertEqual({p[b'kind'] for p in tile[b'points'].values()}, {b'signal', b'traffic_sign'})


if __name__ == '__main__':
    unittest.main()
