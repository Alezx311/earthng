"""The native Map Builder: switched by EARTHNG_NATIVE, and its cut keeps the objects osm_tiles.cut keeps."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import osmium

import native_tool
import osm_tiles


def objects(path):
    nodes, ways, rels = {}, {}, {}
    for o in osmium.FileProcessor(str(path)):
        tags = tuple(sorted((t.k, t.v) for t in o.tags))
        if o.is_node():
            nodes[o.id] = ((o.location.x, o.location.y), tags)
        elif o.is_way():
            ways[o.id] = (tuple(n.ref for n in o.nodes), tags)
        else:
            rels[o.id] = (tuple((m.type, m.ref, m.role) for m in o.members), tags)
    return nodes, ways, rels


def fixture(path):
    """Cells 600..601 x 1000..1001 (lon 30.00-30.10, lat 50.00-50.10) and things round them:
    a way leaving the package, nodes in the buffer, a multipolygon whose outer way lies outside,
    a nested landmark relation, a restriction with a missing member, a node with only meta tags."""
    n = osmium.osm.mutable.Node
    w = osmium.osm.mutable.Way
    r = osmium.osm.mutable.Relation
    with osmium.SimpleWriter(str(path)) as out:
        points = {
            1: (30.02, 50.02, {}), 2: (30.04, 50.03, {}), 3: (30.055, 50.03, {}),     # 3: in both cells' buffers
            4: (30.30, 50.30, {}),                                                     # far outside
            5: (30.03, 50.07, {'highway': 'street_lamp'}),                             # POI
            6: (30.031, 50.071, {'created_by': 'JOSM', 'source': 'survey'}),           # meta only
            7: (30.50, 50.50, {}), 8: (30.51, 50.50, {}), 9: (30.51, 50.51, {}),       # outside ring
            10: (30.075, 50.0099, {'amenity': 'bench', 'name': 'Лавка'}),              # buffer below the package
            11: (-30.0, -50.0, {}),
        }
        for nid, (lon, lat, tags) in points.items():
            out.add_node(n(id=nid, location=(lon, lat), tags=tags))
        out.add_way(w(id=100, nodes=[1, 2, 3], tags={'highway': 'residential', 'name': 'Вулиця'}))
        out.add_way(w(id=101, nodes=[3, 4], tags={'highway': 'primary'}))             # leaves the package
        out.add_way(w(id=102, nodes=[7, 8, 9, 7], tags={}))                            # outer way, far away
        out.add_way(w(id=103, nodes=[11, 7], tags={'highway': 'track'}))               # nowhere near
        out.add_relation(r(id=200, members=[('w', 102, 'outer'), ('w', 100, 'inner')],
                           tags={'type': 'multipolygon', 'landuse': 'forest'}))
        out.add_relation(r(id=201, members=[('r', 200, ''), ('n', 5, 'label')],
                           tags={'type': 'site', 'historic': 'castle'}))
        out.add_relation(r(id=202, members=[('w', 100, 'from'), ('n', 3, 'via'), ('w', 999, 'to')],
                           tags={'type': 'restriction', 'restriction': 'no_left_turn'}))
        out.add_relation(r(id=203, members=[('w', 101, '')], tags={'type': 'route', 'route': 'bus'}))


class NativeToolTests(unittest.TestCase):
    def test_switch_and_command(self):
        with patch.dict(os.environ, {'EARTHNG_NATIVE': '0'}):
            self.assertIsNone(native_tool.tool())
            self.assertIsNone(native_tool.cut_command('a.osm.pbf', 'out'))
        fake = Path('C:/x/earthng-mapbuilder.exe')
        with patch.object(native_tool, 'tool', return_value=fake):
            command = native_tool.cut_command('a.osm.pbf', 'out', [-1.5, 2, 3, 4.25])
        self.assertEqual(command, [str(fake), 'cut', 'a.osm.pbf', '--out', 'out',
                                   '--package-box', '-1.5', '2.0', '3.0', '4.25'])

    @unittest.skipUnless(native_tool.tool(), 'native Map Builder not built (cargo build --release in rust/)')
    def test_native_cut_matches_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            pbf = tmp / 'fixture.osm.pbf'
            fixture(pbf)
            box = [29.99, 49.99, 30.11, 50.11]
            osm_tiles.cut(pbf, tmp / 'python', box)
            subprocess.run(native_tool.cut_command(pbf, tmp / 'native', box), check=True, capture_output=True)
            a = json.loads((tmp / 'python' / 'index.json').read_text(encoding='utf8'))
            b = json.loads((tmp / 'native' / 'index.json').read_text(encoding='utf8'))
            self.assertEqual(sorted(a['tiles']), sorted(b['tiles']))
            self.assertEqual(a['package_box'], b['package_box'])
            self.assertEqual(b['select'], osm_tiles.SELECT)
            self.assertTrue(a['tiles'])
            for key, tile in a['tiles'].items():
                other = b['tiles'][key]
                for field in ('cell', 'coverage', 'nodes', 'ways', 'relations'):
                    self.assertEqual(tile[field], other[field], (key, field))
                self.assertEqual(objects(tmp / 'python' / tile['file']), objects(tmp / 'native' / other['file']), key)


if __name__ == '__main__':
    unittest.main()
