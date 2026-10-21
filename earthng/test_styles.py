"""Style assets and Lua transitions, including BeamNG's per-frame celestial driver."""
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image
import fast_art as art
import fast_pixel as pixel
import fast_style as style
import fast_packs
import fast_dds

ROOT = Path(__file__).resolve().parents[1]
from lupa.luajit21 import LuaRuntime


class AssetTests(unittest.TestCase):
    def test_road_detail_nodes_have_kinds(self):
        kind = style.point_kind
        self.assertEqual(kind({'highway': 'crossing', 'crossing': 'uncontrolled'}), 'crossing')
        self.assertEqual(kind({'highway': 'crossing', 'crossing:markings': 'zebra', 'crossing': 'unmarked'}), 'crossing')
        self.assertIsNone(kind({'highway': 'crossing', 'crossing': 'unmarked'}))
        self.assertIsNone(kind({'highway': 'crossing', 'crossing:markings': 'no'}))
        self.assertEqual(kind({'highway': 'give_way', 'direction': 'forward'}), 'give_way')
        self.assertEqual(kind({'highway': 'stop'}), 'stop_sign')
        self.assertEqual(kind({'highway': 'turning_loop'}), 'turning_circle')
        self.assertEqual(kind({'highway': 'mini_roundabout'}), 'mini_roundabout')
        self.assertEqual(kind({'highway': 'bus_stop'}), 'stop')

    def test_dark_surfaces_are_not_light_sources(self):
        for pack in ('night', 'rain', 'cyber'):
            fields = art.pack_fields(pack, style.ART)
            for kind in ('road', 'sidewalk', 'ground', 'roof', 'water', 'wall_pnl_grey_end'):
                self.assertEqual(fields['e2rf_' + kind]['emissiveFactor'], '0 0 0', (pack, kind))
                self.assertFalse(fields['e2rf_' + kind]['emissiveMap'], (pack, kind))
        glow = np.asarray(fast_packs.facade_glow('panel', 'night'))
        self.assertTrue((glow[0, 0] == 0).all())
        self.assertGreater(glow.max(), 0)

    def test_pixel_facades_are_palette_limited_and_repeat_at_floor_scale(self):
        for name, n in [('panel', 1), ('pnl_grey', 4), ('lgg_cream', 11)]:
            im = pixel.facade(name)
            self.assertLessEqual(len(im.getcolors(100) or []), len(pixel.PALETTE))
            self.assertIsNotNone(im.getcolors(100))
            # Count cream sills on one vertical scan line: one per 3m floor.
            a = np.asarray(im)
            x = round(im.width * 7 / (32 * n))
            line = (a[:, x] == pixel.CREAM).all(axis=1)
            runs = np.count_nonzero(line[1:] != line[:-1])
            self.assertGreaterEqual(runs, n * 2)
        self.assertNotEqual(pixel.facade('pnl_grey').tobytes(), pixel.facade('pnl_grey_end').tobytes())
        self.assertEqual(pixel.facade('shop_red').tobytes(), pixel.facade('shop_red').tobytes())

    def test_pixel_maps_and_dds_chain(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pixel.build(root)
            fields = pixel.fields(style.ART)
            self.assertTrue(all('e2rf_' + k in fields for k in style.KINDS))
            for kind in style.KINDS:
                with Image.open(root / 'pixel' / f'{kind}.color.png') as im:
                    self.assertGreater(im.width, 0)
                self.assertEqual(fields['e2rf_' + kind]['metallicFactor'], 0)
            image = pixel.facade('panel')
            dest = root / 'panel.color.dds'
            fast_dds.save(image, dest)
            import struct
            data = dest.read_bytes()
            self.assertEqual(struct.unpack_from('<II', data, 12), image.size)
            self.assertEqual(struct.unpack_from('<I', data, 28)[0], 11)
            self.assertEqual(struct.unpack_from('<I', data, 128)[0], fast_dds.BC1_UNORM_SRGB)
            self.assertEqual(len(data), 148 + sum(max(1, (1024 >> i) // 4) ** 2 * 8 for i in range(11)))

    def test_version_paths_agree(self):
        self.assertEqual(style.ART, '/e2r_stream/fast-art/' + art.VERSION)
        source = (ROOT / 'mod/lua/ge/extensions/e2r/native.lua').read_text(encoding='utf8')
        self.assertIn(style.ART + '/packs.json', source)
        self.assertIn('pixel', art.PACKS)
        for name in ('pixel', 'night', 'rain', 'cyber', 'synth'):
            self.assertTrue(art.environment(name)['authoredSun'])
        self.assertFalse(art.environment('real').get('authoredSun', False))


def lua_table(lua, value):
    """Nested dicts and lists as Lua tables (lists 1-based)."""
    if isinstance(value, dict):
        return lua.table_from({k: lua_table(lua, v) for k, v in value.items()})
    if isinstance(value, list):
        return lua.table_from([lua_table(lua, v) for v in value])
    return value


class RoadDecalTests(unittest.TestCase):
    """The game's decal-road and trim maps on roads, and their fallback for an older game."""

    def test_generator_checks_exactly_the_edge_maps(self):
        lua = LuaRuntime()
        generator = lua.execute((ROOT / 'mod/lua/ge/extensions/e2r/generator.lua').read_text(encoding='utf8'))
        checked = {generator.EDGE_MAPS[k] for k in range(1, len(generator.EDGE_MAPS) + 1)}
        maps = {p[:-4] + '.dds' for kind in style.EDGES for p in style.TEXTURES[kind].values()}
        self.assertEqual(checked, maps)

    def test_decal_kinds_fall_back_to_their_old_look(self):
        decal_paths = ('/assets/materials/decalroad/', '/assets/materials/trim/')
        for kind, old in style.DECAL_FALLBACK.items():
            material = style.MATERIALS['e2rf_' + kind]
            stage = material['Stages'][0]
            self.assertTrue(stage['baseColorMap'].startswith(decal_paths), kind)
            fallback = material['e2rFallback']
            self.assertEqual(fallback['name'], 'e2rf_' + kind)
            self.assertNotIn('e2rFallback', fallback)
            values = [v for v in fallback['Stages'][0].values() if isinstance(v, str)]
            self.assertFalse(any(v.startswith(decal_paths) for v in values), kind)
            if old is None:
                self.assertIn('diffuseColor', fallback['Stages'][0])
        for kind in ('mark', 'edge_grass', 'edge_dirt'):
            self.assertTrue(style.MATERIALS['e2rf_' + kind]['alphaTest'])
            self.assertNotIn('translucent', style.MATERIALS['e2rf_' + kind])
            self.assertIn('opacityMap', style.MATERIALS['e2rf_' + kind]['Stages'][0])
        self.assertNotIn('e2rFallback', style.MATERIALS['e2rf_road'])

    def test_flat_packs_hide_the_edges_and_keep_the_line_outline(self):
        base = '/e2r_stream/fast-art/' + art.VERSION
        line = style.TEXTURES['line_worn']['opacityMap']
        for pack in ('toon', 'model', 'synth', 'pixel'):
            fields = art.pack_fields(pack, base)
            for kind in style.EDGES:
                self.assertEqual(fields['e2rf_' + kind]['opacityFactor'], 0, (pack, kind))
            self.assertEqual(fields['e2rf_mark']['opacityMap'], line, pack)
        real = art.pack_fields('real', base)
        self.assertEqual(real['e2rf_mark']['baseColorFactor'], '0.990 0.990 0.990 1')
        self.assertNotIn('opacityFactor', real['e2rf_edge_grass'])
        winter = fast_packs.fields('winter', base, real)
        for kind in style.EDGES:
            self.assertEqual(winter['e2rf_' + kind]['baseColorMap'], f'{base}/winter/ground_ground.color.dds')
            self.assertEqual(winter['e2rf_' + kind]['opacityMap'], style.TEXTURES[kind]['opacityMap'])
        autumn = fast_packs.fields('autumn', base, real)
        self.assertEqual(autumn['e2rf_edge_grass']['opacityFactor'], 0)
        self.assertNotIn('opacityFactor', autumn['e2rf_edge_dirt'])


class BuildingStyleTests(unittest.TestCase):
    def test_lua_post_soviet_countries_match_the_look_block(self):
        import re
        import looks
        source = (ROOT / 'mod/lua/ge/extensions/e2r/generator.lua').read_text(encoding='utf8')
        table = source.split('BLD.postsoviet = {', 1)[1].split('}', 1)[0]
        lua_ids = set(re.findall(r'([a-z]+) = true', table))
        block = next(b for b in looks.BLOCKS if b['id'] == 'postsoviet')
        self.assertEqual(lua_ids, set(block['ids']))

    def test_every_pack_names_only_art_that_ships(self):
        base = '/e2r_stream/fast-art/' + art.VERSION
        shipped = ROOT / 'data/art-distributable' / art.VERSION
        if not shipped.is_dir():
            self.skipTest('no distributable art in this checkout')
        missing = set()
        for pack in art.PACKS:
            for fields in art.pack_fields(pack, base).values():
                for value in fields.values():
                    if isinstance(value, str) and value.startswith(base + '/'):
                        path = shipped / value[len(base) + 1:]
                        if not path.exists() and not path.with_suffix('.dds').exists():
                            missing.add(value)
        self.assertEqual(missing, set())

    def test_factor_is_an_srgb_colour(self):
        # a map's own mean colour needs no tint; half its linear brightness is .73 in sRGB
        self.assertEqual(style._factor((188, 188, 188), .5)[:3], [1.0, 1.0, 1.0])
        half = style._factor((137, 137, 137), .5)[0]
        self.assertAlmostEqual(half, .735, places=2)
        self.assertEqual(style._factor((255, 0, 0), .2), [1.0, 0.0, 0.0, 1])

    def test_building_kinds_fall_back_and_roofs_are_double_sided(self):
        for kind in style.BUILDING_FALLBACK:
            material = style.MATERIALS['e2rf_' + kind]
            self.assertIn('e2rFallback', material)
            old = material['e2rFallback']['Stages'][0]
            self.assertTrue(all(not v.startswith('/assets/materials/tileable/metal/corrugation') for v in old.values()
                                if isinstance(v, str)))
        for kind in style.ROOFS:
            self.assertTrue(style.MATERIALS['e2rf_' + kind]['doubleSided'])
        self.assertFalse(style.MATERIALS['e2rf_roof']['doubleSided'])


class TransitionTests(unittest.TestCase):
    def setUp(self):
        self.lua = lua = LuaRuntime()
        lua.execute('''
          ui_imgui = setmetatable({ArrayChar=function() return {} end}, {__index=function() return function() end end})
          require=function() return {} end
          hptimer=function() return {stop=function() return 1 end, stopAndReset=function() return 1 end} end
          function up(fn, name)
            for i=1,200 do
              local n,v=debug.getupvalue(fn,i)
              if not n then break end
              if n==name then return v end
            end
            error('missing upvalue '..name)
          end
          exposure={autoExposure=true, manualEV=12}
          function object(fields)
            return {fields=fields, getField=function(self,k) return self.fields[k] or '' end,
              setField=function(self,k,_,v) self.fields[k]=tostring(v) end,
              postApply=function() if exposure then exposure.autoExposure=true end end,
              reload=function() end}
          end
          sky=object({elevation='15', azimuth='142', nightColor='0.1 0.1 0.1 1'})
          road=object({roughnessFactor='0.8', emissiveFactor='0 0 0'})
          objects={sunsky=sky, e2rf_road=road}
          scenetree={findObject=function(name)
            if name=='PostEffectLocalExposureObject' then return exposure end
            return objects[name]
          end}
          priorDriver=function(ctx) ctx.sunEl=15; ctx.sunAz=142; ctx.other=true end
          driver=priorDriver
          core_celestial={getDriver=function() return driver end, setDriver=function(fn) driver=fn end}
        ''')
        lua.globals().quality = lua.execute((ROOT / 'mod/lua/ge/extensions/e2r/quality.lua').read_text(encoding='utf8'))
        lua.execute("local old=require; require=function(n) if n=='ge/extensions/e2r/quality' then return quality else return old(n) end end")
        lua.globals().mod = lua.execute((ROOT / 'mod/lua/ge/extensions/e2r/world.lua').read_text(encoding='utf8'))
        lua.execute('''
          S=up(mod.tick,'S'); S.now=10
          apply=up(up(mod.tick,'beginArrival'),'applyPack')
          again=up(mod.tick,'envAgainStep')
          S.packs={night={e2rf_road={roughnessFactor=.2}}, real={e2rf_road={emissiveFactor='0 0 0'}}}
          S.packEnv={night={exposure=5,authoredSun=true,objects={sunsky={elevation='-25',azimuth='142'}}},
            real={objects={sunsky={elevation='48',azimuth='142'}}}}
        ''')

    def test_celestial_driver_holds_authored_sun_and_restores_previous(self):
        self.lua.execute('''
          apply('night')
          local ctx={}; driver(ctx)
          assert(ctx.sunEl==-25 and ctx.other)
          assert(exposure.autoExposure==false and exposure.manualEV==5)
          S.now=11; again()
          assert(exposure.autoExposure==false)
          apply('real')
          assert(driver==priorDriver and exposure.autoExposure==true and exposure.manualEV==12)
          assert(road.fields.roughnessFactor=='0.8')
          S.now=20; again()
          assert(sky.fields.elevation=='48' and exposure.autoExposure==true)
        ''')

    def test_late_exposure_and_unload_restore(self):
        self.lua.execute('''
          exposure=nil; apply('night'); assert(S.exposurePending)
          exposure={autoExposure=true,manualEV=11}; S.now=10.6; again()
          assert(exposure.manualEV==5 and not exposure.autoExposure)
          mod.onExtensionUnloaded()
          assert(exposure.manualEV==11 and exposure.autoExposure)
          assert(driver==priorDriver and S.envAgain==nil and S.exposurePending==nil)
          assert(sky.fields.elevation=='15' and S.packOrig==nil and S.packsWarm==nil)
        ''')

    def test_other_driver_is_not_removed_and_older_engine_works(self):
        self.lua.execute('''
          apply('night'); local other=function() end; driver=other
          apply('real'); assert(driver==other)
          core_celestial=nil; apply('night')
          assert(exposure.manualEV==5)
          mod.onExtensionUnloaded(); assert(exposure.manualEV==12)
        ''')

    def test_missing_game_maps_load_the_fallback_material_and_clear_pack_fields(self):
        self.lua.execute('''
          -- an older game: no decal-road maps; the trim's colour map only as a .dds
          FS = {fileExists = function(_, path)
            return not path:find('/decalroad/', 1, true) and not path:find('_curb_trim_01_b.color.png', 1, true)
          end}
          function findUp(name)
            local seen, queue, i = {}, {}, 1
            for _, f in pairs(mod) do if type(f) == 'function' then queue[#queue + 1] = f end end
            while queue[i] do
              local fn = queue[i]; i = i + 1
              if not seen[fn] then
                seen[fn] = true
                for k = 1, 255 do
                  local n, v = debug.getupvalue(fn, k)
                  if not n then break end
                  if n == name then return v end
                  if type(v) == 'function' then queue[#queue + 1] = v end
                end
              end
            end
            error('no upvalue ' .. name)
          end
          materialFor, dropMissingMaps = findUp('materialFor'), findUp('dropMissingMaps')
        ''')
        lua = self.lua
        for kind in ('mark', 'edge_grass', 'curb'):
            material = lua.table_from(lua_table(lua, style.MATERIALS['e2rf_' + kind]))
            loaded = lua.globals().materialFor(material)
            if kind == 'curb':
                # every trim map is there (the colour map as its .dds): the decal look stays
                self.assertTrue(str(loaded.Stages[1].baseColorMap).endswith('_curb_trim_01_b.color.png'))
            else:
                self.assertIsNotNone(loaded.Stages[1].diffuseColor, kind)
                self.assertIsNone(loaded.Stages[1].baseColorMap, kind)
            self.assertIsNone(loaded.e2rFallback)
        road = lua.globals().materialFor(lua.table_from(lua_table(lua, style.MATERIALS['e2rf_road'])))
        self.assertTrue(str(road.Stages[1].baseColorMap).startswith('/assets/materials/tileable/road/'))
        fields = lua_table(lua, {'e2rf_mark': dict(style.TEXTURES['line_worn'], baseColorFactor='1 1 1 1'),
                                 'e2rf_pk_real_mark': {'Stages': [dict(style.TEXTURES['line_worn'])]}})
        cleared = lua.globals().dropMissingMaps(lua.table_from(fields))
        self.assertEqual(cleared.e2rf_mark.baseColorMap, '')
        self.assertEqual(cleared.e2rf_mark.baseColorFactor, '1 1 1 1')
        self.assertIsNone(cleared.e2rf_pk_real_mark.Stages[1].opacityMap)

    def test_rapid_switch_preserves_pending_material_reloads(self):
        self.lua.execute('''
          S.packs.second={e2rf_road={roughnessFactor=.2}}
          S.packEnv.second=S.packEnv.night
          apply('night'); assert(#S.reloadQueue==1)
          apply('second'); assert(#S.reloadQueue==1)
          apply('real'); assert(#S.reloadQueue==1)
          assert(road.fields.roughnessFactor=='0.8')
          S.now=30; again()
          assert(driver==priorDriver and exposure.autoExposure==true)
        ''')


if __name__ == '__main__':
    unittest.main()
