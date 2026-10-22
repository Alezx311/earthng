"""Map data + Lua behavior, including old packs, zoom levels and stock nav refresh."""
import json
from pathlib import Path
import tempfile
import unittest

from lupa.luajit21 import LuaRuntime
import build_map

ROOT = Path(__file__).resolve().parents[1]


class MapDataTests(unittest.TestCase):
    def test_navigation_simplification_keeps_bends_heights_and_junction_ids(self):
        lua = LuaRuntime()
        nav = lua.execute((ROOT / 'mod/lua/ge/extensions/e2r/navigation.lua').read_text(encoding='utf8'))
        prefix = [42, 101, 102, '1-1', 50, 4, 1]
        straight = prefix + [v for x in range(0, 201, 20) for v in (x, 0, 10)]
        reduced = list(nav.simplify(lua.table_from(straight)).values())
        self.assertEqual(reduced, prefix + [0, 0, 10, 200, 0, 10])
        bend = prefix + [0, 0, 0, 50, 0, 0, 100, 0, 5, 100, 50, 5, 100, 100, 5]
        reduced = list(nav.simplify(lua.table_from(bend)).values())
        self.assertEqual(reduced[:7], prefix)
        self.assertIn((100, 0, 5), list(zip(reduced[7::3], reduced[8::3], reduced[9::3])))
        self.assertEqual(reduced[-3:], [100, 100, 5])

    def runtime(self, files):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.globals().exists = lambda path: path in files
        lua.globals().read = lambda path: lua.table_from(files[path], recursive=True)
        lua.execute('FS={fileExists=function(_, p) return exists(p) end}; jsonReadFile=function(p) return read(p) end')
        lua.globals().catalog = lua.execute((ROOT / 'mod/lua/ge/extensions/e2r/mapCatalog.lua').read_text(encoding='utf8'))
        lua.execute("require=function(n) if n=='ge/extensions/e2r/mapCatalog' then return catalog end return {} end")
        lua.globals().planet = lua.execute((ROOT / 'mod/lua/ge/extensions/e2r/planetMap.lua').read_text(encoding='utf8'))
        return lua

    def test_small_villages_countries_aliases_language_limits_and_unmount(self):
        root = '/earthng/planet/maps/demo/'
        places = [build_map.settlement(50.4, 30.2, {'place': 'village', 'name': 'Мала Долина', 'name:en': 'Mala Dolyna', 'alt_name': 'Долинка'}),
                  build_map.settlement(50.5, 30.3, {'place': 'town', 'name': 'Мала Долина Велика', 'population': '100000'})]
        lua = self.runtime({root + 'index.json': {'version': 1, 'tiles': {}}, root + 'places.json': places,
                            '/earthng/planet/basemap/labels.json': {'places': [], 'countries': [[49, 32, 3, 'Ukraine', 'Україна']]}})
        lua.execute("planet.update({{id='demo', title='Ukraine', available=true}})")
        self.assertEqual(lua.eval("planet.search('МАЛА ДОЛИНА', 'uk', 1)[1].name"), 'Мала Долина')
        self.assertEqual(len(lua.eval("planet.search('мала', 'uk', 1)")), 1)
        self.assertEqual(len(lua.eval("planet.search('мала', 'uk', 9)")), 2)
        self.assertEqual(lua.eval("planet.search('мала долина', 'en', 9)[1].name"), 'Mala Dolyna')
        self.assertEqual(lua.eval("planet.search('ДОЛИНКА', 'uk', 9)[1].kind"), 'village')
        self.assertEqual(lua.eval("planet.search('  УКРАЇНА  ', 'uk', 9)[1].kind"), 'country')
        lua.execute('planet.update({})')
        self.assertEqual(len(lua.eval("planet.search('Долинка', 'uk', 9)")), 0)

    def test_overview_levels_and_cache_invalidation(self):
        root = '/earthng/planet/maps/demo/'
        tiles, files = {}, {}
        for key, box, z, line in build_map.road_tiles([(30, 50), (30.3, 50.1)], 1):
            tiles[key] = {'zoom': z, 'box': box, 'file': key + '.json'}
            files[root + key + '.json'] = [line]
        files[root + 'index.json'] = {'version': 1, 'tiles': tiles}
        files[root + 'places.json'] = []
        lua = self.runtime(files)
        lua.execute("catalog.step({{id='demo', title='Demo', available=true}})")
        for zoom in (6, 8, 9, 10, 11, 14):
            self.assertGreater(len(lua.eval(f'catalog.roads({{w=30,s=50,e=30.3,n=50.1}}, {zoom})')), 0)
        self.assertEqual(len(lua.eval('catalog.roads({w=-80,s=-20,e=-79,n=-19}, 6)')), 0)
        lua.execute('catalog.step({})')
        self.assertEqual(len(lua.eval('catalog.roads({w=30,s=50,e=30.3,n=50.1}, 6)')), 0)

    def test_pbf_export_keeps_named_nodes_not_connected_to_roads(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'sample.osm'
            source.write_text('''<osm version="0.6">
              <node id="1" lat="50" lon="30"><tag k="place" v="hamlet"/><tag k="name" v="Hidden hamlet"/></node>
              <node id="2" lat="50.01" lon="30.01"/><node id="3" lat="50.02" lon="30.02"/>
              <way id="10"><nd ref="2"/><nd ref="3"/><tag k="highway" v="primary"/></way></osm>''', encoding='utf8')
            output = build_map.build(source, root / 'map', emit=lambda _: None)
            self.assertEqual(json.loads((output / 'places.json').read_text())[0][3], 'Hidden hamlet')
            index = json.loads((output / 'index.json').read_text())
            self.assertEqual(index['roads'], 1)
            self.assertEqual({x['zoom'] for x in index['tiles'].values()}, {6, 9, 11})
            self.assertEqual({int(k.split('/')[0]) for k in index['raster']}, set(range(5, 11)))
            from PIL import Image
            with Image.open(output / next(iter(index['raster'].values()))) as image:
                self.assertEqual((image.mode, image.size), ('RGBA', (256, 256)))
                self.assertIsNotNone(image.getbbox())
            self.assertEqual(build_map.build(source, output), output)

    def test_overview_reuses_engine_points_and_pans_without_distortion(self):
        root = '/earthng/planet/maps/demo/'
        lua = self.runtime({root + 'index.json': {'version': 1, 'tiles': {
            '6_7_12': {'zoom': 6, 'box': [28, 48, 32, 52], 'file': '6_7_12.json'}}},
            root + 'places.json': [], root + '6_7_12.json': [{'rank': 1, 'box': [50, 30, 50.1, 30.1], 'geo': [50, 30, 50.1, 30.1]}]})
        lua.execute('''
          catalog.step({{id='demo',title='Demo',available=true}})
          allocations=0; strokes={}; offset=0
          im={ImVec2=function(x,y) allocations=allocations+1; return {x=x,y=y} end,
            ImDrawList_AddLine=function(_,a,b) strokes[#strokes+1]={a.x,a.y,b.x,b.y} end}
          bounds={w=30,s=50,e=30.2,n=50.2}
          project=function(lat,lon) return lon*100+offset, lat*100+offset end
          function draw() planet.drawRoads(im,{},bounds,8,project,function() return 1 end) end
          draw(); first=allocations; draw(); assert(allocations==first)
          offset=10; draw(); assert(allocations==first)
          assert(strokes[3][1]-strokes[1][1]==10 and strokes[3][4]-strokes[1][4]==10)
        ''')


if __name__ == '__main__':
    unittest.main()
