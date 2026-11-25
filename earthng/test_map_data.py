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
        marked = lua.table_from(straight)
        marked.deck = 6.5
        kept = nav.simplify(marked)
        self.assertEqual(kept.deck, 6.5)
        self.assertEqual([v for v in kept.values() if v != 6.5], prefix + [0, 0, 10, 200, 0, 10])

    def runtime(self, files):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.globals().exists = lambda path: path in files
        lua.globals().read = lambda path: lua.table_from(files[path], recursive=True)
        lua.execute('FS={fileExists=function(_, p) return exists(p) end}; jsonReadFile=function(p) return read(p) end')
        lua.globals().catalog = lua.execute((ROOT / 'mod/lua/ge/extensions/e2r/mapCatalog.lua').read_text(encoding='utf8'))
        lua.execute("require=function(n) if n=='ge/extensions/e2r/mapCatalog' then return catalog end return {} end")
        lua.globals().planet = lua.execute((ROOT / 'mod/lua/ge/extensions/e2r/planetMap.lua').read_text(encoding='utf8'))
        return lua

    def test_section_maps_work_without_a_parent_pack_and_unmount_independently(self):
        root = '/earthng/countries/demo/sections/area/map/'
        files = {root + 'index.json': {'version': 1, 'tiles': {}},
                 root + 'places.json': [[50, 30, 9, 'Section town', 'Місто секції', 0, 0]]}
        lua = self.runtime(files)
        lua.execute('''
          local countries={{id='demo',title='Demo',available=true,regions={{id='area',section=true}}}}
          for i=1,3 do planet.update(countries) end
          assert(#catalog.catalogs()==1)
          assert(catalog.catalogs()[1].root=='/earthng/countries/demo/sections/area/map/')
          assert(planet.search('Section town','en',1,'demo')[1].name=='Section town')
          assert(#planet.packPlaces('demo')==1)
          planet.update({{id='demo',title='Demo',available=true,regions={}}})
          assert(#planet.packPlaces('demo')==0)
        ''')

    def test_section_map_subset_keeps_local_data_and_aligned_poi_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source'
            source.mkdir()
            tiles = {'near': {'zoom': 11, 'box': [0, 0, 1, 1], 'file': 'near.json'},
                     'far': {'zoom': 11, 'box': [30, 50, 31, 51], 'file': 'far.json'}}
            for name in ('near.json', 'far.json', 'near.png', 'far.png'):
                (source / name).write_bytes(b'fixture')
            build_map.encode(source / 'index.json', {'version': 1, 'tiles': tiles,
                'raster': {'6/32/31': 'near.png', '6/0/0': 'far.png'}, 'sourceStamp': [3]})
            build_map.encode(source / 'places.json', [[.5, .5, 9, 'Near'], [50, 30, 9, 'Far']])
            (source / 'pois.tsv').write_text('a\t.4\t.4\tcafe\tA\nafar\t50\t30\tcafe\tFar\nz\t.6\t.6\tcafe\tZ\n')
            (source / 'poi_tags.tsv').write_text('{"id":1}\n{"id":2}\n{"id":3}\n')
            result = build_map.subset(source, root / 'cut', [[.1, .1, .9, .9]])
            index = json.loads((result / 'index.json').read_text())
            self.assertEqual(set(index['tiles']), {'near'})
            self.assertEqual(index['raster'], {'6/32/31': 'near.png'})
            self.assertEqual((index['places'], index['pois'], index['poiTags']), (1, 2, 2))
            self.assertEqual((result / 'poi_tags.tsv').read_text(), '{"id":1}\n{"id":3}\n')
            self.assertEqual({p.name for p in result.iterdir()},
                {'index.json', 'places.json', 'pois.tsv', 'poi_tags.tsv', 'near.json', 'near.png'})

    def test_pack_guide_keeps_its_anchor_on_resize_and_unmounts(self):
        guide = json.loads((ROOT / 'earthng/fixtures/map_guide.json').read_text(encoding='utf8'))
        self.assertEqual(len({a['id'] for a in guide}), len(guide))
        lua = self.runtime({'/earthng/countries/demo/guide.json': guide})
        lua.execute('''
          assert(#planet.search('Ломбард', 'uk', 1) == 0)
          planet.update({{id='demo',title='Demo',available=true}})
          local hit = planet.search('Ломбард', 'uk', 1)[1]
          assert(hit.article.id == 'sf-lombard-switchbacks')
          assert(planet.search('Lombard', 'en', 1)[1].article.id == hit.article.id)
          local view = {center = hit, zoom = 16}
          local function merc(lat, lon) return lon * 10000, -lat * 10000 end
          local function unmerc(x, y) return -y / 10000, x / 10000 end
          local vec = function(x, y) return {x=x, y=y} end
          local im = setmetatable({ImVec2=vec, GetFontSize=function() return 14 end,
            CalcTextSize=function() return {x=140} end}, {__index=function() return function() end end})
          local function draw(w, h, ox, oy)
            planet.beginLabels(vec(ox,oy), vec(ox+w,oy+h))
            local mouse = vec(ox+w/2+22, oy+h/2)
            return planet.drawLabels(im, {}, vec(ox,oy), w,h,view,merc,unmerc,function() return 0 end,'uk',mouse)
          end
          for _, size in ipairs({{360,180,0,0}, {920,580,170,37}, {720,430,30,14}, {360,180,39,9}}) do
            local p = draw(unpack(size))
            assert(p and p.article.id == hit.article.id and p.lat == hit.lat and p.lon == hit.lon)
          end
          planet.update({})
          assert(#planet.search('Ломбард', 'uk', 1) == 0)
        ''')

    def test_small_villages_countries_aliases_language_limits_and_unmount(self):
        root = '/earthng/countries/demo/map/'
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

    def test_named_points_for_the_search_and_never_a_military_one(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'sample.osm'
            source.write_text('''<osm version="0.6">
              <node id="1" lat="50.45" lon="30.52"><tag k="railway" v="station"/><tag k="name" v="Київ-Пасажирський"/>
                <tag k="name:en" v="Kyiv-Pasazhyrskyi"/></node>
              <node id="2" lat="50.4" lon="30.5"><tag k="aeroway" v="aerodrome"/><tag k="military" v="airfield"/><tag k="name" v="Base"/></node>
              <node id="3" lat="50.41" lon="30.51"><tag k="advertising" v="billboard"/><tag k="name" v="Board"/></node>
              <node id="4" lat="50.42" lon="30.53"><tag k="shop" v="mall"/></node>
              <node id="5" lat="50.0" lon="30.0"/><node id="6" lat="50.0" lon="30.002"/><node id="7" lat="50.002" lon="30.002"/>
              <node id="8" lat="50.002" lon="30.0"/>
              <way id="10"><nd ref="5"/><nd ref="6"/><nd ref="7"/><nd ref="8"/><nd ref="5"/>
                <tag k="shop" v="mall"/><tag k="building" v="retail"/><tag k="name" v="Ocean Plaza"/></way></osm>''', encoding='utf8')
            output = build_map.build(source, root / 'map', emit=lambda _: None)
            lines = [line.split('\t') for line in (output / 'pois.tsv').read_text(encoding='utf8').splitlines()]
            self.assertEqual([(l[3], l[4]) for l in lines], [('mall', 'Ocean Plaza'), ('station', 'Київ-Пасажирський')])
            self.assertEqual(lines[1][0], 'київ-пасажирський | kyiv-pasazhyrskyi')
            self.assertEqual(lines[1][5], 'Kyiv-Pasazhyrskyi')
            self.assertEqual((lines[0][1], lines[0][2]), ('50.001000', '30.001000'), 'a way at the mean of its nodes')
            self.assertEqual(json.loads((output / 'index.json').read_text())['pois'], 2)
        self.assertEqual(build_map.search_key('  ҐАНОК  Їжак’s  ÉCOLE'), "ґанок їжак's École".replace('É', 'É'))

    def test_the_facts_of_each_point_line_for_line(self):
        """poi_tags.tsv (GENERATION 3): line i holds the OSM id and the facts of pois.tsv line i;
        whitespace collapsed, long values cut, no e-mail, the Ukrainian name only when it differs."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'sample.osm'
            long_text = 'x' * 300
            source.write_text(f'''<osm version="0.6">
              <node id="1" lat="50.45" lon="30.52"><tag k="amenity" v="fuel"/><tag k="name" v="WOG"/>
                <tag k="opening_hours" v="24/7"/><tag k="fuel:diesel" v="yes"/><tag k="email" v="a@b.c"/>
                <tag k="description" v="{long_text}"/><tag k="addr:street" v="Хрещатик   вул."/></node>
              <node id="2" lat="50.46" lon="30.53"><tag k="amenity" v="cafe"/><tag k="name" v="Кава"/><tag k="name:uk" v="Кава"/></node>
              <node id="5" lat="50.0" lon="30.0"/><node id="6" lat="50.0" lon="30.002"/><node id="7" lat="50.002" lon="30.002"/>
              <way id="10"><nd ref="5"/><nd ref="6"/><nd ref="7"/><nd ref="5"/>
                <tag k="tourism" v="museum"/><tag k="name" v="Музей"/><tag k="name:uk" v="Музей історії"/></way></osm>''', encoding='utf8')
            output = build_map.build(source, root / 'map', emit=lambda _: None)
            pois = (output / 'pois.tsv').read_text(encoding='utf8').splitlines()
            tags = (output / 'poi_tags.tsv').read_text(encoding='utf8').splitlines()
            self.assertEqual(len(pois), len(tags))
            facts = {p.split('\t')[4]: dict(kv.split('=', 1) for kv in t.split('\t')) for p, t in zip(pois, tags)}
            self.assertEqual(facts['WOG']['osm'], 'n1')
            self.assertEqual(facts['WOG']['amenity'], 'fuel')
            self.assertEqual(facts['WOG']['opening_hours'], '24/7')
            self.assertEqual(facts['WOG']['fuel:diesel'], 'yes')
            self.assertEqual(facts['WOG']['addr:street'], 'Хрещатик вул.')
            self.assertEqual(len(facts['WOG']['description']), build_map.POI_VALUE)
            self.assertNotIn('email', facts['WOG'])
            self.assertNotIn('name:uk', facts['Кава'], 'the same as the name')
            self.assertEqual(facts['Музей']['osm'], 'w10')
            self.assertEqual(facts['Музей']['name:uk'], 'Музей історії')
            index = json.loads((output / 'index.json').read_text())
            self.assertEqual(index['poiTags'], index['pois'])
            self.assertEqual(index['sourceStamp'][0], 3)

    def test_pack_map_is_authoritative_even_with_a_newer_legacy_planet_sidecar(self):
        country, planet = '/earthng/countries/ua/map/', '/earthng/planet/maps/ua/'
        def roots(country_gen, planet_gen):
            files = {}
            for root, gen in ((country, country_gen), (planet, planet_gen)):
                if gen is not None:
                    files[root + 'index.json'] = {'version': 1, 'tiles': {}, 'sourceStamp': [gen, 'ukraine.osm.pbf', 1, 2]}
                    files[root + 'places.json'] = []
            lua = self.runtime(files)
            lua.execute("catalog.step({{id='ua', title='Україна', available=true}})")
            return [c.root for c in lua.eval('catalog.catalogs()').values()]
        self.assertEqual(roots(1, 3), [country])
        self.assertEqual(roots(3, 3), [country])
        self.assertEqual(roots(3, 1), [country])
        self.assertEqual(roots(None, 1), [])
        self.assertEqual(roots(1, None), [country])

    def test_the_search_finds_points_by_any_name_exact_first(self):
        root = '/earthng/countries/ua/map/'
        pois = ''.join('\t'.join(row) + '\n' for row in sorted([
            ['київ-пасажирський | kyiv-pasazhyrskyi', '50.440000', '30.490000', 'station', 'Київ-Пасажирський', 'Kyiv-Pasazhyrskyi'],
            ['ocean plaza', '50.410000', '30.520000', 'mall', 'Ocean Plaza', ''],
            ['plaza', '50.000000', '30.000000', 'shop_map', 'Plaza', ''],
            ['kyiv food | plaza st', '50.1', '30.1', 'food', 'Kyiv Food', ''],
            ['хрещатик', '48.166780', '23.441110', 'spring', 'Хрещатик', ''],
            ['хрещатик | khreshchatyk', '50.447000', '30.522000', 'metro', 'Хрещатик', 'Khreshchatyk'],
            ['хрещатик парк', '50.451000', '30.528000', 'leisure_map', 'Хрещатик парк', ''],
        ]))
        files = {root + 'index.json': {'version': 1, 'tiles': {}}, root + 'places.json': [], root + 'pois.tsv': pois}
        lua = self.runtime(files)
        lua.globals().readText = lambda path: files[path]
        lua.execute('readFile=function(p) return readText(p) end')
        lua.execute("catalog.step({{id='ua', title='Україна', available=true}})")
        found = list(lua.eval("planet.searchPois('PLAZA', 10)").values())
        self.assertEqual([p.name for p in found], ['Plaza', 'Kyiv Food', 'Ocean Plaza'], 'exact, then the rest by name')
        self.assertEqual((found[2].cat, found[2].lat, found[2].context), ('mall', 50.41, 'Україна'))
        hit = list(lua.eval("planet.searchPois('Київ-Пас', 10)").values())
        self.assertEqual([(p.name, p.en) for p in hit], [('Київ-Пасажирський', 'Kyiv-Pasazhyrskyi')])
        self.assertEqual(len(lua.eval("planet.searchPois('pl', 10)")), 0, 'three letters or more')
        self.assertEqual(len(lua.eval("planet.searchPois('50.4', 10)")), 0, 'only the names are searched')
        # the same name in two places: the one nearer the map's centre first, exact still before prefix
        cats = lambda code: [p.cat for p in lua.eval(code).values()]
        self.assertEqual(cats("planet.searchPois('Хрещатик', 10, {lat = 50.45, lon = 30.52})"),
                         ['metro', 'spring', 'leisure_map'])
        self.assertEqual(cats("planet.searchPois('Хрещатик', 10, {lat = 48.2, lon = 23.5})"),
                         ['spring', 'metro', 'leisure_map'])
        self.assertEqual(cats("planet.searchPois('Хрещатик', 10)"), ['spring', 'metro', 'leisure_map'],
                         'no centre: by name, then south to north')

    def test_pack_and_category_scope_applies_before_the_search_limit(self):
        a, b = '/earthng/countries/one/map/', '/earthng/countries/two/map/'
        files = {}
        for root, en, lat in [(a, 'Hill One', 40), (b, 'Hill Two', 50)]:
            files[root + 'index.json'] = {'version': 1, 'tiles': {}}
            files[root + 'places.json'] = [[lat, 20, 12, en, 'Гірка', 0, 100, 'village']]
        lua = self.runtime(files)
        lua.globals().setOne = 'plaza\t40.000000\t20.000000\tcastle\tPlaza One\t\n'
        lua.globals().setTwo = 'plaza\t50.000000\t20.000000\tshop_map\tPlaza Mart\t\n' \
                               'plaza old\t50.001000\t20.000000\tcastle\tPlaza Old\t\n'
        lua.execute('''
          local old = FS.fileExists
          FS.fileExists = function(self,p) return p:match('/pois.tsv$') or old(self,p) end
          function readFile(p) return p:find('/one/',1,true) and setOne or setTwo end
          local packs = {{id='one',title='One',available=true},{id='two',title='Two',available=true}}
          catalog.step(packs); catalog.step(packs)
          assert(#planet.packPlaces('two') == 1)
          assert(planet.search('hill', 'en', 1, 'two')[1].name == 'Hill Two')
          local hit = planet.searchPois('plaza',1,nil,'two',function(cat) return cat == 'castle' end)[1]
          assert(hit.name == 'Plaza Old' and hit.pack == 'two')
          catalog.step({packs[1]})
          assert(#planet.packPlaces('two') == 0)
          assert(#planet.searchPois('plaza',10,nil,'two') == 0)
        ''')

    def test_native_reader_writes_what_osmium_wrote(self):
        import os
        from unittest.mock import patch
        import osmium
        import native_tool
        if native_tool.tool() is None:
            self.skipTest('native tool not built')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            xml = root / 'sample.osm'
            xml.write_text('''<osm version="0.6">
              <node id="1" lat="50.123456789" lon="30.1"><tag k="place" v="town"/><tag k="name" v="A"/>
                <tag k="name:en" v="Ay"/><tag k="population" v="1 200"/></node>
              <node id="4" lat="50.2" lon="30.2"><tag k="place" v="locality"/><tag k="name" v="Not a place"/></node>
              <node id="2" lat="50.01" lon="30.01"/><node id="3" lat="50.02" lon="30.0201"/>
              <node id="5" lat="50.015" lon="30.5"/>
              <way id="10"><nd ref="2"/><nd ref="5"/><nd ref="3"/><tag k="highway" v="primary"/></way>
              <way id="11"><nd ref="2"/><nd ref="99"/><tag k="highway" v="trunk"/></way>
              <way id="12"><nd ref="3"/><nd ref="5"/><tag k="highway" v="tertiary_link"/></way>
              <way id="13"><nd ref="3"/><nd ref="2"/><tag k="highway" v="residential"/></way></osm>''',
                           encoding='utf8')
            pbf = root / 'sample.osm.pbf'
            writer = osmium.SimpleWriter(str(pbf))
            for obj in osmium.FileProcessor(str(xml)):
                writer.add(obj)
            writer.close()
            outputs = []
            for native in ('0', '1'):
                with patch.dict(os.environ, {'EARTHNG_NATIVE': native}):
                    outputs.append(build_map.build(pbf, root / f'map{native}', emit=lambda _: None))
            names = sorted(p.name for p in outputs[0].iterdir())
            self.assertEqual(names, sorted(p.name for p in outputs[1].iterdir()))
            for name in names:
                self.assertEqual((outputs[0] / name).read_bytes(), (outputs[1] / name).read_bytes(), name)
            self.assertEqual(json.loads((outputs[1] / 'index.json').read_text())['roads'], 2)


if __name__ == '__main__':
    unittest.main()
