"""The generator's lab (lab.lua): knobs for the world and for single tiles, their way into
generator.build through native.lua, and the pause menu's page that sets them.

    .venv/Scripts/python.exe -m unittest discover -s earthng -p "test_lab.py"

docs/PROVING_GROUND.md. Lua checks need lupa.luajit21.
"""
import json
from pathlib import Path
import re
import unittest

from lupa.luajit21 import LuaRuntime

import test_native
from test_options import to_py

ROOT = Path(__file__).resolve().parents[1]
E2R = ROOT / 'mod/lua/ge/extensions/e2r'
PAGE = ROOT / 'mod/ui/ui-vue/mods/earthng'
TUNE = "{roadLift=.12, groundDrop=.25, margin=.12, seat=1, seatDrop=-.04, seatMargin=.05, seatStep=12.5, " \
       "terrainStep=25, crown=.02, ruts=1, wear=1, smooth=1, lanes=1, taper=1, sidewalk=2, curb=.25, " \
       "pullFull=12, pullZero=70, fenceStep=4, wallThick=.2, pressEven=1}"


def lab(look="{block='postsoviet', asphalt='worn'}"):
    lua = LuaRuntime()
    lua.globals().lab = lua.execute((E2R / 'lab.lua').read_text(encoding='utf8'))
    lua.execute(f"quality = {{detail = 50, maxTrees = 1800}}; "
                f"lab.bind{{tune = {TUNE}, look = function() return {look} end, kitStyles = {{'brick', 'panel'}}, "
                f"kitWalls = {{'brick_red'}}, quality = function(key) return quality[key] end}}")
    return lua


class LabTests(unittest.TestCase):
    def test_untouched_lab_gives_the_generator_nothing(self):
        lua = lab()
        self.assertEqual(to_py(lua.eval("lab.resolve('r:0_0')")), {})
        self.assertEqual(to_py(lua.eval('lab.resolve(nil)')), {})
        self.assertTrue(lua.eval("lab.lookOf(nil, 'r:0_0') == nil"))

    def test_a_tile_wins_over_the_world_and_the_world_over_the_default(self):
        lua = lab()
        self.assertEqual(lua.eval("lab.get('crown', 'r:0_0')"), (.02, 'default'))
        self.assertEqual(lua.eval("lab.set('crown', .04)"), (.04, True))
        self.assertEqual(lua.eval("lab.get('crown', 'r:0_0')"), (.04, 'world'))
        self.assertEqual(lua.eval("lab.set('crown', .06, 'r:0_0')"), (.06, True))
        self.assertEqual(lua.eval("lab.get('crown', 'r:0_0')"), (.06, 'tile'))
        self.assertEqual(lua.eval("lab.get('crown', 'r:1_0')"), (.04, 'world'))
        self.assertEqual(to_py(lua.eval("lab.resolve('r:0_0')")), {'tune': {'crown': .06}})
        self.assertEqual(to_py(lua.eval("lab.resolve('r:1_0')")), {'tune': {'crown': .04}})
        # the tile set back to what the world gives has no value of its own
        self.assertEqual(lua.eval("lab.set('crown', .04, 'r:0_0')"), (.04, True))
        self.assertEqual(to_py(lua.eval('lab.scopes()')), {})
        # and the world set back to the default gives nothing again
        lua.execute("lab.set('crown', .02)")
        self.assertEqual(to_py(lua.eval("lab.resolve('r:0_0')")), {})

    def test_values_are_clamped_stepped_and_refused(self):
        lua = lab()
        self.assertEqual(lua.eval("lab.set('crown', 9)"), (.08, True))
        self.assertEqual(lua.eval("lab.set('sidewalk', 1.13)"), (1.25, True))
        self.assertEqual(lua.eval("lab.set('crown', 'x')"), (None, 'invalid value'))
        self.assertEqual(lua.eval("lab.set('look.block', 'atlantis')"), (None, 'invalid value'))
        self.assertEqual(lua.eval("lab.set('nothing', 1)")[0], None)

    def test_switches_reach_the_generator_as_numbers_and_the_look_as_slots(self):
        lua = lab()
        lua.execute("lab.set('wear', false); lab.set('seat', false, 'r:0_0'); lab.set('look.block', 'british', 'r:0_0')")
        lua.execute("lab.set('kit', 'off', 'r:0_0'); lab.set('kitStyle', 'brick'); lab.set('detail', 80, 'r:0_0')")
        got = to_py(lua.eval("lab.resolve('r:0_0')"))
        self.assertEqual(got['tune'], {'wear': 0, 'seat': 0})
        self.assertEqual(got['look'], {'block': 'british'})
        self.assertEqual(got['option'], {'kit': 'off', 'kitStyle': 'brick', 'detail': 80})
        # the pack's look is not changed, the tile's copy has the slot
        lua.execute("pack = {block = 'postsoviet', asphalt = 'worn'}; mine = lab.lookOf(pack, 'r:0_0')")
        self.assertEqual(to_py(lua.eval('mine')), {'block': 'british', 'asphalt': 'worn'})
        self.assertEqual(lua.eval('pack.block'), 'postsoviet')
        self.assertTrue(lua.eval("lab.lookOf(pack, 'r:5_5') == pack"))
        self.assertEqual((lua.eval("lab.switch('on', nil)"), lua.eval("lab.switch('off', true)"), lua.eval("lab.switch('auto', true)")),
                         (True, False, True))

    def test_defaults_follow_the_pack_and_the_quality(self):
        lua = lab()
        self.assertEqual(lua.eval("lab.get('look.block')"), ('postsoviet', 'default'))
        self.assertEqual(lua.eval("lab.get('look.asphalt')"), ('worn', 'default'))
        self.assertEqual(lua.eval("lab.get('look.verge')"), ('grass', 'default'))
        self.assertEqual(lua.eval("lab.get('detail')"), (50, 'default'))
        lua.execute('quality.detail = 70')
        self.assertEqual(lua.eval("lab.get('detail')"), (70, 'default'))
        # the seated ground's own defaults (generator.lua copies seatDrop and seatMargin over them)
        self.assertEqual(lua.eval("lab.get('groundDrop')"), (-.04, 'default'))
        self.assertEqual(lua.eval("lab.get('margin')"), (.05, 'default'))
        self.assertEqual(lua.eval("lab.get('terrainStep')"), (12.5, 'default'))

    def test_every_number_of_tune_is_a_knob(self):
        lua = lab()
        keys = {k['key']: g['key'] for g in to_py(lua.eval('lab.payload(nil)'))['groups'] for k in g['knobs']}
        self.assertEqual(keys['fenceStep'], 'advanced')
        self.assertEqual(keys['wallThick'], 'advanced')
        self.assertEqual(keys['crown'], 'road')
        for hidden in ('seatDrop', 'seatMargin', 'seatStep', 'pressEven'):
            self.assertNotIn(hidden, keys)

    def test_payload_says_where_a_value_comes_from(self):
        lua = lab()
        lua.execute("lab.set('crown', .04); lab.set('sidewalk', 3, 'r:0_0')")
        payload = to_py(lua.eval("lab.payload('r:0_0')"))
        json.dumps(payload)             # plain data: it goes to the page as JSON
        knobs = {k['key']: k for g in payload['groups'] for k in g['knobs']}
        self.assertEqual((knobs['crown']['from'], knobs['crown']['world'], knobs['crown'].get('tile')), ('world', .04, None))
        self.assertEqual((knobs['sidewalk']['from'], knobs['sidewalk']['tile'], knobs['sidewalk']['default']), ('tile', 3, 2))
        self.assertEqual(payload['scopes'], ['r:0_0'])
        self.assertTrue(payload['worldTouched'] and payload['tileTouched'])
        self.assertEqual([g['key'] for g in payload['groups']][:4], ['universe', 'look', 'buildings', 'road'])

    def test_file_round_trip_drops_what_it_does_not_know(self):
        lua = lab()
        lua.execute("saved = nil; lab.storage = {read = function() return saved end, write = function(cfg) saved = cfg end}")
        lua.execute("lab.set('crown', .04); lab.set('look.block', 'nordic', 'r:0_0')")
        saved = to_py(lua.eval('saved'))
        self.assertEqual(saved, {'schema': 'earthng-lab-v1', 'world': {'crown': .04}, 'tiles': {'r:0_0': {'look.block': 'nordic'}}})
        lua.execute("saved.world.gone = 5; saved.tiles['r:0_0'].crown = 'bad'; saved.tiles['r:9_9'] = {nothing = 1}")
        lua.execute('local keep = saved; lab.resetAll(); saved = keep; lab.load()')
        self.assertEqual(to_py(lua.eval("lab.resolve('r:0_0')")), {'tune': {'crown': .04}, 'look': {'block': 'nordic'}})
        self.assertEqual(to_py(lua.eval('lab.scopes()')), ['r:0_0'])
        # another schema is not read at all
        lua.execute("saved = {schema = 'other', world = {crown = .06}}; lab.load()")
        self.assertEqual(to_py(lua.eval('lab.resolve(nil)')), {})

    def test_reset(self):
        lua = lab()
        lua.execute("lab.set('crown', .04); lab.set('crown', .06, 'r:0_0'); lab.set('sidewalk', 3, 'r:0_0')")
        self.assertTrue(lua.eval("lab.reset('crown', 'r:0_0')"))
        self.assertEqual(lua.eval("lab.get('crown', 'r:0_0')"), (.04, 'world'))
        self.assertTrue(lua.eval("lab.reset(nil, 'r:0_0')"))
        self.assertFalse(lua.eval("lab.reset(nil, 'r:0_0')"))
        self.assertTrue(lua.eval('lab.resetAll()'))
        self.assertEqual(to_py(lua.eval("lab.resolve('r:0_0')")), {})


class NativeLabTests(unittest.TestCase):
    """native.lua hands each tile its own knobs and builds a tile again on request."""

    def make(self):
        lua, mod, cv = test_native.NativeTests('make').make()
        lua.globals().lab = lua.execute((E2R / 'lab.lua').read_text(encoding='utf8'))
        lua.execute(f"lab.bind{{tune = {TUNE}, kitStyles = {{'brick'}}}}")
        mod.lab = lua.globals().lab
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

    def test_tile_under_the_car(self):
        lua, mod = self.make()
        self.assertEqual(tuple(mod.tileAt()), ('3_3', 'sample:3_3', 3, 3))
        self.assertEqual(tuple(mod.tileAt(10, 510)), ('0_1', 'sample:0_1', 0, 1))

    def test_a_tile_is_built_with_its_own_knobs(self):
        lua, mod = self.make()
        self.assertIsNone(lua.eval("seen['3_3'].tune"))
        self.assertIsNone(lua.eval("seen['3_3'].kit"))
        lua.execute("lab.set('crown', .04); lab.set('sidewalk', 3, 'sample:3_3'); lab.set('look.block', 'british', 'sample:3_3')")
        lua.execute("lab.set('kit', 'off', 'sample:3_3'); lab.set('kitStyle', 'brick', 'sample:3_3'); lab.set('detail', 90, 'sample:3_3')")
        lua.execute("landed = seen['2_3']")
        self.assertEqual(mod.rebuild('3_3'), 1)
        self.assertIsNone(mod.status().stream.ready['3_3'])
        for _ in range(300):
            mod.update(.016, 2)
        self.assertTrue(mod.status().stream.ready['3_3'])
        mine = lua.eval("seen['3_3']")
        self.assertEqual(to_py(mine.tune), {'crown': .04, 'sidewalk': 3})
        self.assertEqual(mine.look.block, 'british')
        self.assertEqual((mine.kit, mine.kitStyle, mine.detail), (False, 'brick', 90))
        # a neighbour was not built again: the very options table of the landing
        self.assertTrue(lua.eval("seen['2_3'] == landed"))
        self.assertIsNone(lua.eval("seen['2_3'].tune"))
        # every tile again: the world's value reaches them all
        self.assertGreater(mod.rebuild(), 1)
        for _ in range(600):
            mod.update(.016, 2)
        self.assertEqual(to_py(lua.eval("seen['2_3'].tune")), {'crown': .04})
        self.assertIsNone(lua.eval("seen['2_3'].look"))

    def test_native_without_the_lab_builds_as_before(self):
        lua, mod, cv = test_native.NativeTests('make').make()
        self.assertIsNone(mod.lab)
        lat, lon = test_native.geographic(1750, 1750)
        mod.land(cv(dict(seq=1, lat=lat, lon=lon)))
        for _ in range(400):
            mod.update(.016, 2)
            if mod.status().job.state != 'working':
                break
        self.assertEqual(mod.status().job.state, 'ready')


class PageTests(unittest.TestCase):
    """The pause menu's tab: files the game's UI runtime loads from ui/ui-vue/mods/earthng."""

    def test_files(self):
        for name in ('index.js', 'call.js', 'style.js', 'Knob.vue', 'Settings.vue', 'Lab.vue', 'Polygon.vue'):
            self.assertTrue((PAGE / name).is_file(), name)
        index = (PAGE / 'index.js').read_text(encoding='utf8')
        self.assertIn('export async function onLoad', index)
        self.assertIn('export async function onUnload', index)
        for card in ('Settings.vue', 'Lab.vue', 'Polygon.vue'):
            self.assertIn(card, index)
            self.assertTrue((PAGE / card).is_file())

    def test_no_style_blocks(self):
        # the runtime's SCSS subset resolves no imports: the look is style.js, put into the page once
        for path in PAGE.glob('*.vue'):
            source = path.read_text(encoding='utf8')
            self.assertNotIn('<style', source, path.name)
            self.assertEqual(source.count('<template>'), 1, path.name)
            self.assertEqual(source.count('<script setup>'), 1, path.name)
        for card in ('Settings.vue', 'Lab.vue', 'Polygon.vue'):
            self.assertIn('ensureStyle()', (PAGE / card).read_text(encoding='utf8'))

    def test_every_call_is_a_function_of_the_world(self):
        world = (E2R / 'world.lua').read_text(encoding='utf8')
        defined = set(re.findall(r'^function M\.(\w+)\(', world, re.M))
        called = set()
        for path in PAGE.glob('*.vue'):
            called |= set(re.findall(r"world\('(\w+)'", path.read_text(encoding='utf8')))
        self.assertTrue(called)
        self.assertEqual(called - defined, set())
        # and the same registration in Lua as in index.js
        for name in re.findall(r'id: "(earthng-\w+)"', (PAGE / 'index.js').read_text(encoding='utf8')):
            self.assertIn(f"id = '{name}'", world)

    def test_classes_used_are_styled(self):
        style = (PAGE / 'style.js').read_text(encoding='utf8')
        for path in PAGE.glob('*.vue'):
            for name in set(re.findall(r'class="(eng-[\w-]+)', path.read_text(encoding='utf8'))):
                self.assertIn('.' + name, style, f'{path.name}: {name}')

    def test_hooks_have_a_sender(self):
        world = (E2R / 'world.lua').read_text(encoding='utf8')
        for path in PAGE.glob('*.vue'):
            for hook in set(re.findall(r'events\.on\("(\w+)"', path.read_text(encoding='utf8'))):
                self.assertIn(f"guihooks.trigger('{hook}'", world, f'{path.name}: {hook}')


if __name__ == '__main__':
    unittest.main()
