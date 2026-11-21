"""The land's real colour from Sentinel-2: the builder (s2_colour.py), the game's sheets (s2.lua) and the
generator's ground (VEG.real). No network: the source is a stand-in."""
import math
import struct
import sys
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import s2_colour as s2

LUA = HERE.parent / 'mod/lua/ge/extensions/e2r'


FRAME = {'crs': 'EPSG:32636', 'origin': [340000.0, 5590000.0]}


class FlatSource:
    """Reflectance that says where it was read: red rises east, green north, blue is the step."""

    def __init__(self, hole=None):
        self.calls, self.hole = [], hole

    def read(self, crs, x0, y1, step_x, step_y, width, height):
        self.calls.append((crs, x0, y1, step_x, step_y, width, height))
        xs = x0 + (np.arange(width) + .5) * step_x
        ys = y1 - (np.arange(height) + .5) * step_y
        rgb = np.zeros((height, width, 3), np.float32)
        rgb[..., 0] = (xs[None, :] - FRAME['origin'][0] + 10000) / 200000 + .02
        rgb[..., 1] = (ys[:, None] - FRAME['origin'][1] + 10000) / 200000 + .02
        rgb[..., 2] = .03
        mask = np.ones((height, width), bool)
        if self.hole:
            mask &= ~((xs[None, :] > self.hole[0]) & (xs[None, :] < self.hole[2])
                      & (ys[:, None] > self.hole[1]) & (ys[:, None] < self.hole[3]))
            rgb[~mask] = 0
        return rgb, mask


class BuilderTests(unittest.TestCase):
    def test_tiers_keep_a_sheet_a_power_of_two_with_whole_gutters(self):
        self.assertEqual([s2.tier(a) for a in (100, 8000, 8001, 80000, 600000)], [12.5, 12.5, 25., 25., 50.])
        for _, step in s2.TIERS:
            px = s2.sheet_px(step)
            self.assertEqual(px & (px - 1), 0, step)
            self.assertEqual(px * step, s2.SHEET_M + 2 * s2.GUTTER_M)
            self.assertEqual(s2.GUTTER_M / step, int(s2.GUTTER_M / step))
        # six tiles of 500 m to a sheet: a tile never straddles two
        self.assertEqual(s2.SHEET_M % 500, 0)

    def test_tile_names_and_overview_levels(self):
        self.assertEqual(s2.tile_name(50, 30), 'N50E030')
        self.assertEqual(s2.tile_name(-1, -74), 'S01W074')
        self.assertTrue(s2.tile_url(50, 30).endswith('/rgbnir/2021/N50/ESA_WorldCover_10m_2021_v200_N50E030_S2RGBNIR.tif'))
        # the largest of the file's own levels not coarser than the step asked for
        self.assertIsNone(s2.overview_level(12.5))
        self.assertEqual(s2.overview_level(25), 0)
        self.assertEqual(s2.overview_level(50), 1)
        # a level a little coarser than the step is still read (the far map's 29 m: the 37 m level)
        self.assertEqual(s2.overview_level(29), 1)
        self.assertEqual(s2.overview_level(20), 0)
        self.assertEqual(s2.overview_level(400), 3)

    def test_albedo_lifts_dark_land_and_eases_bright(self):
        dark = s2.albedo(np.array([[[.035, .06, .03]]], np.float32))[0, 0]
        self.assertAlmostEqual(float(dark @ [.2126, .7152, .0722]), .06 * s2.GAIN * .7152 + .035 * s2.GAIN * .2126 + .03 * s2.GAIN * .0722, places=3)
        self.assertGreater(dark[1], dark[0])
        bright = s2.albedo(np.array([[[.6, .6, .6]]], np.float32))[0, 0]
        self.assertLess(bright[0], .6 * s2.GAIN)
        self.assertLessEqual(bright.max(), 1)
        # grey stays grey, order is kept
        self.assertAlmostEqual(float(bright[0]), float(bright[2]), places=5)
        ramp = s2.albedo(np.linspace(0, 1, 50, dtype=np.float32)[None, :, None].repeat(3, 2))[0, :, 0]
        self.assertTrue((np.diff(ramp) >= 0).all())

    def test_green_land_is_turned_to_summer_and_bare_land_is_not(self):
        # a meadow (bright in the near infrared) and a ploughed field of the same red, green and blue
        meadow = s2.albedo(np.array([[[.05, .065, .04, .30]]], np.float32))[0, 0]
        plain = s2.albedo(np.array([[[.05, .065, .04]]], np.float32))[0, 0]
        field = s2.albedo(np.array([[[.05, .065, .04, .07]]], np.float32))[0, 0]
        self.assertEqual(meadow.shape, (3,))
        # greener and a little darker where it grows; the bare field is the picture's own colour
        self.assertGreater(meadow[1] / meadow[0], plain[1] / plain[0] * 1.2)
        self.assertLess(meadow[2], plain[2])
        self.assertLess(float(meadow @ [.2126, .7152, .0722]), float(plain @ [.2126, .7152, .0722]) * 1.02)
        self.assertTrue(np.allclose(field, plain, atol=1e-6))

    def test_fill_spreads_data_into_holes(self):
        rgb = np.zeros((6, 6, 3), np.float32)
        mask = np.zeros((6, 6), bool)
        rgb[:, :2], mask[:, :2] = .2, True
        out = s2.fill(rgb, mask)
        self.assertTrue(np.allclose(out, .2))
        # nothing known: left as it is
        self.assertTrue((s2.fill(rgb * 0, mask & False) == 0).all())

    def test_sheets_file_round_trip(self):
        entries = {(-2, 3): b'A' * 10, (0, 4): b'B' * 7}
        data = s2.pack_sheets(entries, 25., 128, 4, (-2, 3, 3, 2))
        head, out = s2.read_sheets(data)
        self.assertEqual(head, {'version': 1, 'step': 25., 'px': 128, 'gutter': 4, 'sheet': 3000., 'i0': -2, 'j0': 3, 'ni': 3, 'nj': 2})
        self.assertEqual(out, entries)
        self.assertEqual(data[:4], b'EGS2')
        self.assertEqual(len(data), 4 + 33 + 8 * 6 + 17)

    def test_near_sheets_cut_one_read_into_sheets_with_their_gutters(self):
        source = FlatSource()
        bounds = [-3000., 0., 3000., 3000.]
        data = s2.near_sheets(source, FRAME, bounds, 50.)
        head, sheets = s2.read_sheets(data)
        self.assertEqual((head['i0'], head['j0'], head['ni'], head['nj'], head['px'], head['gutter']), (-1, 0, 2, 1, 64, 2))
        self.assertEqual(sorted(sheets), [(-1, 0), (0, 0)])
        # one read of the block: both sheets and a gutter round them
        self.assertEqual(len(source.calls), 1)
        crs, x0, y1, sx, sy, w, h = source.calls[0]
        self.assertEqual((crs, sx, sy, w, h), ('EPSG:32636', 50., 50., 2 * 60 + 4, 60 + 4))
        self.assertEqual((x0, y1), (FRAME['origin'][0] - 3000 - 100, FRAME['origin'][1] + 3000 + 100))
        # a sheet's texel (c, r) is the land at its own place: the gutter is the neighbour's land
        east = s2.dds_image(sheets[(0, 0)]).astype(np.float32)
        west = s2.dds_image(sheets[(-1, 0)]).astype(np.float32)
        self.assertEqual(east.shape, (64, 64, 3))
        # the east sheet's west gutter shows what the west sheet shows at its east edge
        self.assertLess(np.abs(east[10:50, 0:2] - west[10:50, 60:62]).mean(), 6)
        # red rises to the east across both
        self.assertGreater(east[:, 40, 0].mean(), east[:, 10, 0].mean())
        self.assertGreater(east[:, 10, 0].mean(), west[:, 10, 0].mean())
        # green rises to the north: row 0 is north
        self.assertGreater(east[5, :, 1].mean(), east[58, :, 1].mean())

    def test_near_sheets_skip_what_is_not_wanted_or_has_no_data(self):
        # no data from west of the first sheet to 200 m into the second
        source = FlatSource(hole=(FRAME['origin'][0] - 3300, FRAME['origin'][1] - 200, FRAME['origin'][0] + 200, FRAME['origin'][1] + 3200))
        data = s2.near_sheets(source, FRAME, [-3000., 0., 6000., 3000.], 50.)
        head, sheets = s2.read_sheets(data)
        # the sheet wholly in the hole is left out; its neighbour's gutter is filled from the land
        self.assertNotIn((-1, 0), sheets)
        self.assertIn((0, 0), sheets)
        west_edge = s2.dds_image(sheets[(0, 0)])[20:40, 0:6].astype(np.float32)
        self.assertGreater(west_edge.min(), 20)
        only = s2.near_sheets(FlatSource(), FRAME, [-3000., 0., 6000., 3000.], 50., wanted=lambda i, j: i == 1)
        self.assertEqual(sorted(s2.read_sheets(only)[1]), [(1, 0)])
        self.assertIsNone(s2.near_sheets(FlatSource(), FRAME, [0., 0., 3000., 3000.], 50., wanted=lambda i, j: False))

    def far_bin(self, u0=-10, v0=-20, nu=40, nv=30, step=100.):
        return b'EGF1' + b'\x01' + struct.pack('<iiIIff', u0, v0, nu, nv, step, 20.)

    def test_far_map_covers_the_raster_and_keeps_the_drawn_water(self):
        raster = s2.far_raster(self.far_bin())
        self.assertEqual(raster, (-10, -20, 40, 30, 100.))
        # the drawn map: 64 x 32 texels, red land; its roughness: the west half smooth (water)
        drawn = s2.dds_bytes(Image.new('RGB', (64, 32), (200, 30, 30)))
        rough = Image.new('RGB', (64, 32), (255, 255, 255))
        rough.paste((20, 20, 20), (0, 0, 32, 32))
        source = FlatSource()
        image = s2.far_map(source, FRAME, raster, drawn, s2.dds_bytes(rough, srgb=False))
        self.assertEqual(image.size, (64, 32))
        crs, x0, y1, sx, sy, w, h = source.calls[0]
        self.assertEqual((x0, y1), (FRAME['origin'][0] - 1000, FRAME['origin'][1] - 2000 + 3000))
        self.assertAlmostEqual(sx, 4000 / 64)
        self.assertAlmostEqual(sy, 3000 / 32)
        a = np.asarray(image, np.float32)
        # water keeps the drawn colour, land takes the picture's
        self.assertGreater(a[:, :28, 0].mean(), 150)
        self.assertLess(a[:, 36:, 0].mean(), 120)
        self.assertGreater(a[:, 36:, 1].mean(), a[:, 36:, 2].mean())

    def test_dds_round_trip(self):
        image = Image.new('RGB', (16, 8), (90, 120, 60))
        back = s2.dds_image(s2.dds_bytes(image))
        self.assertEqual(back.shape, (8, 16, 3))
        self.assertLess(np.abs(back.astype(int) - np.array([90, 120, 60])).max(), 6)


try:
    from lupa.luajit21 import LuaRuntime
except ImportError:      # the builder's tests above still run
    LuaRuntime = None


@unittest.skipIf(LuaRuntime is None, 'needs lupa.luajit21')
class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute('''
          WRITTEN, LOADED, JSON = {}, {}, {}
          FS = {fileExists = function(_, p) return FILES[p] ~= nil end, directoryExists = function() return true end,
                directoryCreate = function() end}
          FILES = {}
          local realOpen = io.open
          io.open = function(path, mode)
            if mode == 'rb' then
              local data = FILES[path]
              if not data then return nil end
              return {read = function() return data end, close = function() end}
            end
            local parts = {}
            return {write = function(_, s) parts[#parts + 1] = s end, close = function() WRITTEN[path] = table.concat(parts) end}
          end
          jsonWriteFile = function(file, defs) JSON[file] = defs end
          loadJsonMaterialsFile = function(file) LOADED[#LOADED + 1] = file end
          log = function() end
          function HEX(s) return s and (s:gsub('.', function(c) return string.format('%02x', c:byte()) end)) end
        ''')
        self.s2 = self.lua.execute((LUA / 's2.lua').read_text(encoding='utf8'))
        self.hex = self.lua.globals().HEX

    def region(self, entries, step=25., px=128, gutter=4, grid=(-2, 3, 3, 2)):
        data = s2.pack_sheets(entries, step, px, gutter, grid)
        self.lua.globals().FILES['/earthng/countries/x/far/r1.s2.bin'] = data
        return self.lua.table_from({'descriptor': self.lua.table_from(
            {'manifest': '/earthng/countries/x/regions/r1/manifest.json', 'id': 'r1'})})

    def test_the_file_the_builder_writes_is_the_file_the_game_reads(self):
        entries = {(-2, 3): bytes(range(256)) * 2, (0, 4): b'\x00\x0d\x0a\x1a' * 5}
        R = self.s2.parse(s2.pack_sheets(entries, 25., 128, 4, (-2, 3, 3, 2)))
        self.assertEqual((R.step, R.px, R.gutter, R.sheet, R.i0, R.j0, R.ni, R.nj, R.span), (25., 128, 4, 3000., -2, 3, 3, 2, 3200.))
        read = self.lua.eval('function(s2, R, I, J) return HEX(s2.bytes(R, I, J)) end')
        self.assertEqual(read(self.s2, R, -2, 3), entries[(-2, 3)].hex())
        self.assertEqual(read(self.s2, R, 0, 4), entries[(0, 4)].hex())
        for miss in ((-1, 3), (5, 5), (-3, 3), (0, 9)):
            self.assertIsNone(read(self.s2, R, *miss))
        self.assertIsNone(self.s2.parse(b'nope'))

    def test_a_sheet_is_written_once_and_gets_a_material_for_each_land(self):
        sheet = bytes(range(256))
        options = self.s2.options(self.region({(-2, 3): sheet}))
        self.assertEqual((options.sheet, options.step, options.px, options.gutter), (3000., 25., 128, 4))
        grass = options.kind(-2, 3, 'grass')
        self.assertEqual(grass, 's2g_r1_m2_3')
        self.assertEqual(options.kind(-2, 3, 'earth'), 's2e_r1_m2_3')
        g = self.lua.globals()
        # binary safe, written once
        self.assertEqual(self.lua.eval("HEX(WRITTEN['e2r_stream/s2/r1/m2_3.color.dds'])"), sheet.hex())
        self.assertEqual(len(list(g.LOADED.values())), 1)
        defs = g.JSON['e2r_world/s2_r1_m2_3.json']
        stage = defs['e2rf_s2g_r1_m2_3'].Stages[1]
        self.assertEqual(stage.baseColorMap, '/e2r_stream/s2/r1/m2_3.color.dds')
        # the detail repeats every 2 m of a 3.2 km sheet
        self.assertEqual(stage.detailScale[1], 1600)
        self.assertIn('t_grass_01', stage.detailMap)
        self.assertIn('dirt_crumbly', defs['e2rf_s2e_r1_m2_3'].Stages[1].detailMap)
        self.assertEqual(defs['e2rf_s2e_r1_m2_3'].groundType, 'DIRT')
        # a sheet the region does not have: no kind, asked once
        self.assertIsNone(options.kind(0, 3, 'grass'))
        self.assertIsNone(options.kind(0, 3, 'grass'))
        self.assertEqual(self.s2.stats.sheets, 1)

    def test_a_pack_without_sheets_has_no_options(self):
        r = self.lua.table_from({'descriptor': self.lua.table_from(
            {'manifest': '/earthng/countries/y/regions/r9/manifest.json', 'id': 'r9'})})
        self.assertIsNone(self.s2.options(r))
        self.s2.enabled = False
        self.assertIsNone(self.s2.options(self.region({(0, 0): b'x'})))


@unittest.skipIf(LuaRuntime is None, 'needs lupa.luajit21')
class GroundTests(unittest.TestCase):
    """The generator's open land in a sheet's material (generator.lua VEG.real)."""

    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.generator = self.lua.execute((LUA / 'generator.lua').read_text(encoding='utf8'))
        self.asked = []

    def table(self, value):
        if isinstance(value, dict):
            return self.lua.table_from({k: self.table(v) for k, v in value.items()})
        if isinstance(value, list):
            return self.lua.table_from([self.table(v) for v in value])
        return value

    def options(self, have=True):
        def kind(I, J, land):
            self.asked.append((I, J, land))
            return f's2{land[0]}_{I}_{J}' if have else None
        wrap = self.lua.eval('function(f) return function(I, J, land) return f(I, J, land) end end')
        return self.lua.table_from({'sheet': 3000., 'step': 25., 'px': 128, 'gutter': 4, 'kind': wrap(kind)})

    def build(self, cells, i=0, j=0, **options):
        options.setdefault('relief', False)
        table = self.table(options)
        if 's2' in options:
            table['s2'] = options['s2']
        return self.generator.build(self.table(cells), i, j, table)

    def corners(self, manifest, prefix):
        out = []
        for item in (manifest['items'] or self.lua.table()).values():
            for mesh in (item['meshes'] or self.lua.table()).values():
                if mesh.material.startswith(prefix):
                    for k in range(1, len(mesh.faces) + 1):
                        face = mesh.faces[k]
                        p, uv = mesh.verts[face.v + 1], mesh.uvs[face.u + 1]
                        out.append((mesh.material, p.x + item.pos[1], p.y + item.pos[2], p.z + item.pos[3], uv.u, uv.v))
        return out

    CELL = {'roads': [{'id': 'r', 'width': 7, 'nodes': [1, 2], 'tags': {'highway': 'tertiary', 'sidewalk': 'no'},
                       'points': [[-50 + 20 * k, 250, 20] for k in range(31)]}],
            'terrain': {'rect': [-500, -500, 1500, 1500], 'nx': 5, 'ny': 5, 'heights': [20.0] * 25}}

    def test_open_land_takes_the_sheets_material_and_its_uvs(self):
        # tile (7, 2): x 3500..4000, y 1000..1500, in sheet (1, 0)
        cell = {'terrain': {'rect': [3000, 500, 4500, 2000], 'nx': 4, 'ny': 4, 'heights': [20.0] * 16}}
        road = self.build([cell], i=7, j=2, s2=self.options())[0]
        self.assertEqual(set(self.asked), {(1, 0, 'grass'), (1, 0, 'earth')})
        land = self.corners(road, 'e2rf_s2g_1_0')
        self.assertTrue(land)
        # no land by relief, no plain ground left
        self.assertFalse(self.corners(road, 'e2rf_cut_'))
        self.assertFalse(self.corners(road, 'e2rf_ground'))
        span, west, north = 3200., 3000. - 100, 3000. + 100
        for _, x, y, z, u, v in land:
            self.assertAlmostEqual(u, (x - west) / span, places=6)
            self.assertAlmostEqual(v, (north - y) / span, places=6)
            self.assertTrue(0 < u < 1 and 0 < v < 1)
        # the whole tile is covered once
        area = 0
        for k in range(0, len(land), 3):
            (_, ax, ay, *_), (_, bx, by, *_), (_, cx, cy, *_) = land[k:k + 3]
            area += abs((bx - ax) * (cy - ay) - (cx - ax) * (by - ay)) / 2
        self.assertAlmostEqual(area, 500 * 500, delta=1)

    def test_the_verge_beside_a_road_is_the_same_land(self):
        road = self.build([self.CELL], s2=self.options())[0]
        self.assertTrue(self.corners(road, 'e2rf_s2g_0_0'))
        self.assertFalse(self.corners(road, 'e2rf_ground'))
        self.assertFalse(self.corners(road, 'e2rf_cut_'))
        self.assertFalse(self.corners(road, 'e2rf_fade_'))
        # the verge's own triangles lie within 3 m of the asphalt's edge
        beside = [c for c in self.corners(road, 'e2rf_s2g_0_0') if 3.5 < abs(c[2] - 250) < 6.6 and 100 < c[1] < 400]
        self.assertTrue(beside)

    def test_fields_take_the_soil_detail_and_other_covers_keep_their_own(self):
        field = {'id': 'f', 'kind': 'farmland', 'tags': {'landuse': 'farmland'},
                 'rings': [[[0, 0, 0], [500, 0, 0], [500, 240, 0], [0, 240, 0]]]}
        paved = {'id': 'p', 'kind': 'paved', 'tags': {'landuse': 'industrial'},
                 'rings': [[[0, 300, 0], [500, 300, 0], [500, 500, 0], [0, 500, 0]]]}
        cell = {'areas': [field, paved], 'terrain': {'rect': [-500, -500, 1500, 1500], 'nx': 5, 'ny': 5, 'heights': [20.0] * 25}}
        road, scene = self.build([cell], s2=self.options())[:2]
        earth = self.corners(road, 'e2rf_s2e_0_0')
        self.assertTrue(earth)
        self.assertLess(max(c[2] for c in earth), 250.01)
        # no drawn crop over it, in either layer
        self.assertFalse(self.corners(road, 'e2rf_farmland'))
        self.assertFalse(self.corners(scene, 'e2rf_farmland'))
        self.assertTrue(self.corners(road, 'e2rf_paved') or self.corners(scene, 'e2rf_paved'))

    def test_without_sheets_other_packs_and_distant_tiles_draw_as_before(self):
        cases = ({}, {'s2': self.options(have=False)}, {'s2': self.options(), 'realStyle': False})
        for extra in cases:
            road = self.build([self.CELL], **extra)[0]
            self.assertFalse(self.corners(road, 'e2rf_s2'), extra.keys())
            self.assertTrue(self.corners(road, 'e2rf_ground') or self.corners(road, 'e2rf_cut_'))
        far = self.build([self.CELL], far=True, s2=self.options())
        for manifest in far[:3]:
            if manifest is not None:
                self.assertFalse(self.corners(manifest, 'e2rf_s2'))

    def test_a_far_tile_under_a_real_far_map_is_draped_in_it(self):
        R = self.lua.table_from({'texKind': 'farmap_r1', 'real': True})
        far_map = self.lua.table_from({'at': lambda x, y: R, 'uv': lambda r, x, y: (x / 10000, 1 - y / 10000)})
        options = self.table({'far': True, 'relief': False})
        options['farMap'] = far_map
        out = self.generator.build(self.table([self.CELL]), 0, 0, options)
        draped = [c for manifest in out[:3] if manifest is not None for c in self.corners(manifest, 'e2rf_farmap_r1')]
        self.assertTrue(draped)
        for _, x, y, z, u, v in draped:
            self.assertAlmostEqual(u, x / 10000, places=6)
            self.assertAlmostEqual(v, 1 - y / 10000, places=6)
        # a drawn far map (no real colour) leaves the far tile's land as it was
        R['real'] = None
        out = self.generator.build(self.table([self.CELL]), 0, 0, options)
        plain = [c for manifest in out[:3] if manifest is not None for c in self.corners(manifest, 'e2rf_farmap_r1')]
        self.assertFalse(plain)


if __name__ == '__main__':
    unittest.main()
