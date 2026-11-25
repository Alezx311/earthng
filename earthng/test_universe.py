"""Universes (universe.lua): a tile rebuilt by another world's rules. The rules, a climate that is
given (biome.lua forced), the collector's material swap, the ground's physics, and their way
from the lab through native.lua into generator.build.

    .venv/Scripts/python.exe -m unittest discover -s earthng -p "test_universe.py"

docs/PROVING_GROUND.md. Lua checks need lupa.luajit21.
"""
from pathlib import Path
import unittest

from lupa.luajit21 import LuaRuntime

import fast_style
import test_native
from test_options import to_py

ROOT = Path(__file__).resolve().parents[1]
E2R = ROOT / 'mod/lua/ge/extensions/e2r'
GEO = [0, 0, -123.4, -48.875, 1.36e-5, 0, 0, 9e-6]      # the proving ground's frame, near enough


def module(lua, name):
    return lua.execute((E2R / f'{name}.lua').read_text(encoding='utf8'))


class RuleTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.globals().U = module(self.lua, 'universe')

    def swap(self, universe, kind):
        return self.lua.eval(f"U.swapper(U.get('{universe}'))('{kind}')")

    def test_the_jungle_names_its_climate_and_its_plants(self):
        self.assertEqual(self.lua.eval("U.get('jungle').climate.class"), 1)
        self.assertEqual(self.lua.eval("U.get('jungle').flora"), 'tropics')
        self.assertEqual(self.lua.eval("U.look(U.get('jungle'), nil).block"), 'southeast-asia')
        self.assertEqual(self.swap('jungle', 'edge_grass'), 'edge_dirt')
        self.assertEqual(self.swap('jungle', 'road'), 'road')

    def test_the_universes_with_labels(self):
        self.assertEqual([c[0] for c in to_py(self.lua.eval('U.choices()'))], ['mountains', 'desert', 'snow', 'mud', 'jungle'])
        for choice in to_py(self.lua.eval('U.choices()')):
            self.assertTrue(choice[1] and choice[2])
        self.assertIsNone(self.lua.eval("U.get('none')"))

    def test_a_universe_is_described_for_a_reader(self):
        """The proving ground's page says by which rules the tile under the car is built."""
        import json
        for name in ('mountains', 'desert', 'snow', 'mud', 'jungle'):
            d = to_py(self.lua.eval(f"U.describe('{name}')"))
            json.dumps(d)                                    # plain data: it goes to the page as JSON
            self.assertEqual(d['id'], name)
            self.assertTrue(d['label']['uk'] and d['label']['en'] and d['about']['uk'] and d['about']['en'], name)
            self.assertIs(d['feel'], True)
        snow = to_py(self.lua.eval("U.describe('snow')"))
        self.assertEqual(snow['climate'], {'class': 27, 'name': 'boreal', 'snowline': -3000})
        self.assertEqual(snow['look'], {'block': 'nordic', 'markings': 'none'})
        self.assertEqual((snow['tune'], snow['option']), ({'lanes': 0, 'wear': 0}, {'maxGrass': 0, 'maxRocks': 0}))
        self.assertIn(['sidewalk', 'snow'], snow['swaps'])
        self.assertIn(['mark', False], snow['swaps'])
        self.assertEqual(snow['swaps'], sorted(snow['swaps'], key=lambda s: s[0]))
        self.assertGreater(snow['patterns'], 0)
        mountains = to_py(self.lua.eval("U.describe('mountains')"))
        self.assertEqual(mountains['climate'], {'class': 27, 'name': 'boreal', 'treeline': 420, 'snowline': 900})
        self.assertEqual((to_py(mountains['swaps']), mountains['patterns']), ({}, 0))
        self.assertEqual(to_py(self.lua.eval("U.describe('jungle')"))['flora'], 'tropics')
        self.assertNotIn('climate', to_py(self.lua.eval("U.describe('mud')")))    # the place's own
        self.assertIsNone(self.lua.eval("U.describe('none')"))
        # describing a universe does not change its rules
        self.assertEqual(self.lua.eval("U.get('snow').look.block"), 'nordic')
        self.lua.execute("U.describe('snow').look.block = 'x'")
        self.assertEqual(self.lua.eval("U.get('snow').look.block"), 'nordic')

    def test_snow_covers_roads_roofs_and_fields(self):
        for kind in ('road', 'road_major', 'road_worn', 'road_major_lane', 'road_gravel', 'road_dirt', 'road_track', 'paved'):
            self.assertEqual(self.swap('snow', kind), 'snow_edge', kind)
        for kind in ('roof', 'roof_tile', 'roof_mtile_red', 'sh_roof_slate', 'kw_bitumen', 'sidewalk', 'sidewalk_tile',
                     'farmland', 'farmland_wheat_y', 'wetland'):
            self.assertEqual(self.swap('snow', kind), 'snow', kind)
        for kind in ('mark', 'mark_yellow', 'edge_grass', 'ruts_dirt', 'crack_net'):
            self.assertIs(self.swap('snow', kind), False, kind)
        # walls, kerbs, water and the snow itself are left as they are
        for kind in ('wall_panel', 'curb', 'water', 'snow', 'bare_rock', 'col_ground', 'kw_brick_red'):
            self.assertEqual(self.swap('snow', kind), kind)

    def test_mud_takes_the_land_and_the_unpaved_roads(self):
        for kind in ('ground', 'meadow', 'grass_dry', 'earth', 'fade_dry3', 'cut_grass2', 'bare_ground', 'farmland_rows',
                     'road_dirt', 'road_gravel', 'road_track', 'footway'):
            self.assertEqual(self.swap('mud', kind), 'mud', kind)
        self.assertEqual(self.swap('mud', 'edge_grass'), 'edge_dirt')
        for kind in ('road', 'road_major', 'sidewalk', 'forest', 'park', 'wetland', 'roof_tile'):
            self.assertEqual(self.swap('mud', kind), kind)

    def test_every_swap_names_a_material_there_is(self):
        import house_art
        import kit_art
        import own_art
        import street_art
        kinds = set(fast_style.KINDS)
        # a swap may start from a library's kind (sidewalk_tile is street art): those kinds are
        # defined only where the library's paid sources are in the checkout
        libraries = own_art.ready() and house_art.ready() and kit_art.ready() and street_art.ready()
        for name in ('mountains', 'desert', 'snow', 'mud'):
            u = to_py(self.lua.eval(f"(function() local u = U.get('{name}'); return {{swap = u.swap or {{}}, patterns = u.patterns or {{}}}} end)()"))
            targets = set(v for v in (u['swap'] or {}).values() if v) | set(rule[1] for rule in (u['patterns'] or []) if rule[1])
            self.assertEqual(targets - kinds, set(), name)
            if libraries:
                self.assertEqual(set(u['swap'] or {}) - kinds, set(), name)

    def test_mountains_have_no_swap_and_a_desert_one(self):
        self.assertIsNone(self.lua.eval("U.swapper(U.get('mountains'))"))
        self.assertEqual(self.swap('desert', 'edge_grass'), 'edge_dirt')

    def test_look_is_merged_without_touching_the_packs(self):
        self.lua.execute("pack = {block = 'postsoviet', trees = 'regional'}; mine = U.look(U.get('snow'), pack)")
        self.assertEqual(to_py(self.lua.eval('mine')), {'block': 'nordic', 'trees': 'regional', 'markings': 'none'})
        self.assertEqual(self.lua.eval('pack.block'), 'postsoviet')
        self.assertTrue(self.lua.eval("U.look(U.get('snow'), pack) == mine"))
        self.assertEqual(self.lua.eval("U.look(U.get('desert'), nil).block"), 'middle-east')

    def test_named_climates_are_one_table_each(self):
        self.assertEqual(self.lua.eval("U.climate('desert').class"), 4)
        self.assertTrue(self.lua.eval("U.climate('ice') == U.climate('ice')"))
        self.assertIsNone(self.lua.eval("U.climate('auto')"))

    def test_look_blocks_are_known(self):
        import looks
        for name in ('mountains', 'desert', 'snow', 'mud'):
            look = to_py(self.lua.eval(f"U.get('{name}').look or {{}}")) or {}
            if 'block' in look:
                self.assertIn(look['block'], looks.BLOCK_BY_ID)
            for slot, value in look.items():
                if slot != 'block':
                    self.assertIn(value, looks.SLOTS[slot], f'{name}.{slot}')


class ClimateTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.globals().B = module(self.lua, 'biome')

    def test_a_given_class_makes_its_place(self):
        self.lua.execute('desert = {class = 4}; p = B.forced(desert, -123.4, -48.9)')
        self.assertEqual((self.lua.eval('p.group'), self.lua.eval('p.arid'), self.lua.eval('p.forced')), ('desert', True, True))
        self.assertTrue(self.lua.eval('B.forced(desert, -123.4, -48.9) == p'))
        self.assertTrue(self.lua.eval('B.forcedAt(desert, {0, 0, -123.4, -48.9, 1e-5, 0, 0, 1e-5}, 100, 100) == p'))

    def test_given_lines_are_taken_as_they_are(self):
        self.lua.execute('snow = {class = 27, snowline = -3000}; p = B.forced(snow, 30, 50)')
        self.assertEqual((self.lua.eval('p.group'), self.lua.eval('p.snowline')), ('boreal', -3000))
        self.assertIsNone(self.lua.eval('p.fixedTreeline'))
        self.lua.execute('range = {class = 27, treeline = 420, snowline = 900}; q = B.forced(range, 30, 50)')
        self.assertEqual((self.lua.eval('q.treeline'), self.lua.eval('q.fixedTreeline'), self.lua.eval('q.snowline')), (420, 420, 900))
        # the grid's own place of the same class is not changed by it
        self.assertGreater(self.lua.eval('B.forced({class = 27}, 30, 50).snowline'), 2000)

    def test_without_a_class_the_place_keeps_its_climate(self):
        self.lua.execute('lines = {snowline = 100}; p = B.forced(lines, 30, 50)')
        self.assertEqual((self.lua.eval('p.group'), self.lua.eval('p.snowline')), ('temperate', 100))


class LabUniverseTests(unittest.TestCase):
    def lab(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.globals().lab = module(lua, 'lab')
        lua.globals().U = module(lua, 'universe')
        lua.execute('''
          given = {['polygon:9_0'] = 'mud', ['polygon:-9_0'] = 'snow'}
          lab.bind{tune = {crown = .02, seat = 1, lanes = 1, wear = 1}, universes = U.choices(), climates = U.climates,
            rules = U.get, universeOf = function(scope) return given[scope] end}''')
        return lua

    def test_a_pack_names_a_tiles_universe(self):
        lua = self.lab()
        self.assertEqual(lua.eval("lab.get('universe', 'polygon:9_0')"), ('mud', 'default'))
        self.assertEqual(lua.eval("lab.get('universe', 'polygon:0_0')"), ('none', 'default'))
        self.assertEqual(lua.eval("lab.get('universe', nil)"), ('none', 'default'))
        # nobody set it, and the generator hears of it all the same
        self.assertEqual(to_py(lua.eval("lab.resolve('polygon:9_0')")), {'option': {'universe': 'mud'}})
        self.assertEqual(to_py(lua.eval("lab.resolve('polygon:0_0')")), {})
        knobs = {k['key']: k for g in to_py(lua.eval("lab.payload('polygon:9_0')"))['groups'] for k in g['knobs']}
        self.assertEqual((knobs['universe']['default'], knobs['universe']['value'], knobs['universe']['from']), ('mud', 'mud', 'default'))
        self.assertEqual(to_py(lua.eval("lab.payload('polygon:9_0')"))['groups'][0]['key'], 'universe')

    def test_the_world_wins_over_the_pack_and_a_tile_over_the_world(self):
        lua = self.lab()
        lua.execute("lab.set('universe', 'desert')")
        self.assertEqual(lua.eval("lab.get('universe', 'polygon:9_0')"), ('desert', 'world'))
        self.assertEqual(to_py(lua.eval("lab.resolve('polygon:0_0')")), {'option': {'universe': 'desert'}})
        lua.execute("lab.set('universe', 'snow', 'polygon:9_0')")
        self.assertEqual(to_py(lua.eval("lab.resolve('polygon:9_0')")), {'option': {'universe': 'snow'}})
        # the world's own again: the tile's override is what it was set to, the pack's shows elsewhere
        lua.execute("lab.set('universe', 'none')")
        self.assertEqual(lua.eval("lab.get('universe', 'polygon:-9_0')"), ('snow', 'default'))
        self.assertEqual(lua.eval("lab.get('universe', 'polygon:9_0')"), ('snow', 'tile'))

    def test_a_tile_can_be_taken_out_of_its_universe(self):
        lua = self.lab()
        self.assertEqual(lua.eval("lab.set('universe', 'none', 'polygon:9_0')"), ('none', True))
        self.assertEqual(to_py(lua.eval("lab.resolve('polygon:9_0')")), {'option': {'universe': 'none'}})
        # set back to what the pack names: no override is kept
        self.assertEqual(lua.eval("lab.set('universe', 'mud', 'polygon:9_0')"), ('mud', True))
        self.assertEqual(to_py(lua.eval('lab.scopes()')), {})

    def test_a_universe_gives_its_knobs_their_defaults(self):
        lua = self.lab()
        # snow: no lanes, no wear, nordic walls; elsewhere the knobs' own defaults
        self.assertEqual(lua.eval("lab.get('lanes', 'polygon:-9_0')"), (False, 'default'))
        self.assertEqual(lua.eval("lab.get('look.block', 'polygon:-9_0')"), ('nordic', 'default'))
        self.assertEqual(lua.eval("lab.get('lanes', 'polygon:0_0')"), (True, 'default'))
        # set against the universe, it is an override; set back to the universe's, it is gone
        self.assertEqual(lua.eval("lab.set('lanes', true, 'polygon:-9_0')"), (True, True))
        self.assertEqual(to_py(lua.eval("lab.resolve('polygon:-9_0')")), {'option': {'universe': 'snow'}, 'tune': {'lanes': 1}})
        self.assertEqual(lua.eval("lab.set('lanes', false, 'polygon:-9_0')"), (False, True))
        self.assertEqual(to_py(lua.eval('lab.scopes()')), {})
        # the world's universe rules the world's defaults
        lua.execute("lab.set('universe', 'snow')")
        self.assertEqual(lua.eval("lab.get('lanes', nil)"), (False, 'default'))
        self.assertEqual(lua.eval("lab.get('look.block', 'polygon:0_0')"), ('nordic', 'default'))

    def test_climate_and_feel_knobs(self):
        lua = self.lab()
        lua.execute("lab.set('climate', 'ice', 'polygon:0_0'); lab.set('feel', 'off', 'polygon:0_0')")
        self.assertEqual(to_py(lua.eval("lab.resolve('polygon:0_0')")), {'option': {'climate': 'ice', 'feel': 'off'}})
        self.assertEqual(lua.eval("lab.set('climate', 'venus')"), (None, 'invalid value'))


class NativeUniverseTests(unittest.TestCase):
    """native.lua hands generator.build a universe's rules under the lab's own knobs."""

    def make(self, universe_of="function(scope) return scope == 'sample:3_3' and 'snow' or nil end"):
        lua, mod, cv = test_native.NativeTests('make').make()
        lua.globals().lab = module(lua, 'lab')
        lua.globals().U = module(lua, 'universe')
        lua.execute(f"lab.bind{{tune = {{crown = .02, seat = 1, lanes = 1, wear = 1}}, universes = U.choices(), climates = U.climates, "
                    f"floraZones = {{{{'polissia', 'Полісся', 'Polissia'}}, {{'tropics', 'Тропіки', 'Rainforest'}}}}, "
                    f"rules = U.get, universeOf = {universe_of}}}")
        mod.lab, mod.universes = lua.globals().lab, lua.globals().U
        lua.execute('''
          seen = {}
          local build = stubGenerator.build
          stubGenerator.build = function(cells, i, j, options)
            seen[i .. '_' .. j .. (options.far and ':far' or options.horizon and ':horizon' or '')] = options
            return build(cells, i, j, options)
          end''')
        lat, lon = test_native.geographic(1750, 1750)
        mod.land(cv(dict(seq=1, lat=lat, lon=lon)))
        for _ in range(400):
            mod.update(.016, 2)
            if mod.status().job.state != 'working':
                break
        return lua, mod

    def rebuild(self, mod, key='3_3'):
        mod.rebuild(key)
        for _ in range(300):
            mod.update(.016, 2)

    def test_a_packs_universe_reaches_its_tile_alone(self):
        lua, mod = self.make()
        mine, other = lua.eval("seen['3_3']"), lua.eval("seen['2_3']")
        self.assertEqual(to_py(mine.climate), {'class': 27, 'snowline': -3000})
        self.assertEqual((mine.look.block, mine.look.markings), ('nordic', 'none'))
        self.assertEqual(to_py(mine.tune), {'lanes': 0, 'wear': 0})
        self.assertEqual((mine.swap('road'), mine.swap('roof_tile'), mine.swap('mark')), ('snow_edge', 'snow', False))
        self.assertEqual((mine.feel, mine.maxGrass, mine.maxRocks), (True, 0, 0))
        self.assertIsNone(other.swap)
        self.assertIsNone(other.climate)
        self.assertIsNone(other.feel)
        self.assertGreater(other.maxGrass, 0)

    def test_the_labs_knobs_win_over_the_universes_rules(self):
        lua, mod = self.make()
        lua.execute("lab.set('look.block', 'british', 'sample:3_3'); lab.set('lanes', true, 'sample:3_3')")
        lua.execute("lab.set('climate', 'desert', 'sample:3_3'); lab.set('feel', 'off', 'sample:3_3'); lab.set('maxGrass', 500, 'sample:3_3')")
        self.rebuild(mod)
        mine = lua.eval("seen['3_3']")
        self.assertEqual((mine.look.block, mine.look.markings), ('british', 'none'))
        self.assertEqual(to_py(mine.tune), {'lanes': 1, 'wear': 0})
        self.assertEqual(to_py(mine.climate), {'class': 4})
        self.assertIsNone(mine.feel)
        self.assertEqual(mine.maxGrass, 500)
        self.assertEqual(mine.swap('road'), 'snow_edge')        # the universe is still snow

    def test_the_jungle_names_the_plants_and_the_labs_zone_wins(self):
        lua, mod = self.make("function(scope) return scope == 'sample:3_3' and 'jungle' or nil end")
        mine, other = lua.eval("seen['3_3']"), lua.eval("seen['2_3']")
        self.assertEqual((mine.floraZone, to_py(mine.climate), mine.look.block), ('tropics', {'class': 1}, 'southeast-asia'))
        self.assertIsNone(other.floraZone)
        # a zone given by hand: on the universe's tile and on a tile of no universe
        lua.execute("lab.set('floraZone', 'polissia', 'sample:3_3'); lab.set('floraZone', 'tropics', 'sample:2_3')")
        self.rebuild(mod)
        self.rebuild(mod, '2_3')
        self.assertEqual(lua.eval("seen['3_3'].floraZone"), 'polissia')
        self.assertEqual(lua.eval("seen['2_3'].floraZone"), 'tropics')
        self.assertIsNone(lua.eval("seen['2_3'].climate"))
        self.assertEqual(lua.eval("lab.set('floraZone', 'mars')"), (None, 'invalid value'))

    def test_mud_turns_the_land_system_off(self):
        lua, mod = self.make("function(scope) return scope == 'sample:3_3' and 'mud' or nil end")
        mine = lua.eval("seen['3_3']")
        self.assertIs(mine.land, False)
        self.assertEqual((mine.swap('ground'), mine.feel, mine.maxGrass), ('mud', True, 300))
        self.assertIsNone(mine.climate)
        self.assertIsNone(lua.eval("seen['2_3'].land"))

    def test_no_universe_outside_the_real_pack(self):
        lua, mod = self.make()
        mod.setRealStyle(False)
        for _ in range(400):
            mod.update(.016, 2)
        mine = lua.eval("seen['3_3']")
        self.assertIsNone(mine.swap)
        self.assertIsNone(mine.climate)
        self.assertEqual(mine.look, None)


class GeneratorUniverseTests(unittest.TestCase):
    """generator.lua draws a tile by the rules it is handed."""

    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        # the climate module the generator asks for, with the planet's grid taken as present
        self.lua.execute("B = (function() " + (E2R / 'biome.lua').read_text(encoding='utf8') + " end)(); B.present = true; "
                         "local old = require; require = function(name) if name == 'ge/extensions/e2r/biome' then return B end; "
                         "return old(name) end")
        self.generator = module(self.lua, 'generator')
        self.lua.globals().U = module(self.lua, 'universe')

    def table(self, value):
        if isinstance(value, dict):
            return self.lua.table_from({k: self.table(v) for k, v in value.items()})
        if isinstance(value, list):
            return self.lua.table_from([self.table(v) for v in value])
        return value

    def cell(self, **extra):
        road = {'id': 'r', 'width': 7, 'tags': {'highway': 'residential'}, 'points': [[x, 250, 12] for x in range(0, 501, 20)]}
        track = {'id': 't', 'width': 3.5, 'tags': {'highway': 'unclassified', 'surface': 'dirt'},
                 'points': [[250, y, 12] for y in range(0, 501, 20)]}
        house = {'id': 'b', 'tags': {'building': 'house', 'building:levels': '1', 'roof:shape': 'gabled'}, 'height': 4,
                 'rings': [[[100, 300, 12], [112, 300, 12], [112, 309, 12], [100, 309, 12]]]}
        field = {'id': 'f', 'kind': 'farmland', 'tags': {'landuse': 'farmland'},
                 'rings': [[[300, 300], [480, 300], [480, 480], [300, 480]]]}
        return {'roads': [road, track], 'junctions': [], 'buildings': [house], 'areas': [field], 'lines': [], 'points': [],
                'terrain': {'rect': [0, 0, 1000, 1000], 'nx': 2, 'ny': 2, 'heights': [12] * 4}, **extra}

    def build(self, universe=None, **options):
        options.setdefault('relief', False)
        options.setdefault('geo', GEO)
        options.setdefault('seaLevel', 0)
        opts = self.table({'tileSize': 500, **options})
        if universe:
            self.lua.globals().opts = opts
            self.lua.execute(f"local u = U.get('{universe}'); opts.swap = U.swapper(u); opts.climate = u.climate; "
                             f"opts.feel = u.feel; opts.land = u.option and u.option.land; opts.tune = u.tune")
        road, scene = self.generator.build(self.table([self.cell()]), 0, 0, opts)[:2]
        mats = {}
        for manifest in (road, scene):
            for item in manifest['items'].values():
                for mesh in (item['meshes'] or self.lua.table()).values():
                    mats[mesh.material] = mats.get(mesh.material, 0) + len(mesh.faces) // 3
        return mats

    def test_the_place_as_it_is(self):
        mats = self.build()
        self.assertIn('e2rf_road_lane', mats)
        self.assertIn('e2rf_col_ground', mats)
        for name in ('e2rf_mud', 'e2rf_snow', 'e2rf_desert', 'e2rf_col_mud', 'e2rf_col_snow'):
            self.assertNotIn(name, mats)

    def test_snow(self):
        mats = self.build('snow')
        self.assertIn('e2rf_snow', mats)                # the land, the field and the roof
        self.assertIn('e2rf_snow_edge', mats)           # both roads
        self.assertIn('e2rf_col_snow', mats)            # and the car stands on snow
        for name in ('e2rf_road', 'e2rf_road_lane', 'e2rf_road_dirt', 'e2rf_mark', 'e2rf_ground', 'e2rf_grass', 'e2rf_col_ground'):
            self.assertNotIn(name, mats)
        self.assertFalse([m for m in mats if m.startswith(('e2rf_roof', 'e2rf_farmland', 'e2rf_ruts'))])

    def test_mud(self):
        mats = self.build('mud')
        self.assertIn('e2rf_mud', mats)
        self.assertIn('e2rf_col_mud', mats)
        self.assertIn('e2rf_road_lane', mats)           # the asphalt stays
        for name in ('e2rf_road_dirt', 'e2rf_ground', 'e2rf_col_ground'):
            self.assertNotIn(name, mats)
        self.assertFalse([m for m in mats if m.startswith(('e2rf_farmland', 'e2rf_fade_', 'e2rf_cut_'))])

    def test_desert_is_a_climate(self):
        mats = self.build('desert')
        self.assertIn('e2rf_desert', mats)
        self.assertNotIn('e2rf_ground', mats)
        self.assertIn('e2rf_road_lane', mats)

    def test_a_given_snow_line_alone(self):
        self.lua.execute('lines = {class = 27, snowline = -3000}')
        mats = self.build(climate=self.lua.globals().lines)
        self.assertIn('e2rf_snow', mats)
        self.assertIn('e2rf_road_lane', mats)           # no swap: the road is asphalt
        self.assertIn('e2rf_col_ground', mats)          # and no feel: grass under the wheels


class MaterialTests(unittest.TestCase):
    def test_mud_and_the_felt_grounds(self):
        m = fast_style.MATERIALS
        self.assertEqual(m['e2rf_mud']['groundType'], 'MUD')
        self.assertTrue(m['e2rf_mud']['Stages'][0]['baseColorMap'].startswith('/assets/materials/terrain/mud/'))
        self.assertIn('e2rFallback', m['e2rf_mud'])
        self.assertEqual((m['e2rf_col_snow']['groundType'], m['e2rf_col_sand']['groundType'], m['e2rf_col_mud']['groundType']),
                         ('SNOW', 'SAND', 'MUD'))
        generator = (E2R / 'generator.lua').read_text(encoding='utf8')
        self.assertEqual(m['e2rf_col_dirt']['groundType'], 'DIRT')
        for proxy in ('col_snow', 'col_sand', 'col_mud', 'col_dirt'):
            self.assertIn(f"'{proxy}'", generator)


if __name__ == '__main__':
    unittest.main()
