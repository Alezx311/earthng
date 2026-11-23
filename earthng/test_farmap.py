"""The far view's colour maps as a worker VM reads them (mod/lua/ge/extensions/e2r/farmap.lua).

    .venv\\Scripts\\python.exe -m unittest discover -s earthng -p "test_farmap.py"
"""
import struct
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
LUA = HERE.parent / 'mod' / 'lua' / 'ge' / 'extensions' / 'e2r'

try:
    from lupa import luajit21 as lupa
except ImportError:  # pragma: no cover
    lupa = None

FOREST, NO_DATA = 3, 255


def raster(u0, v0, nu, nv, step, classes):
    """An EGF1 far raster as far.lua parses it: header, elevation nodes, class pixels (the built
    and roof bytes and the marks, which farmap.lua does not read, follow as zeros)."""
    assert len(classes) == nu * nv
    nodes = (nu + 1) * (nv + 1)
    return (b'EGF1' + b'\x01' + struct.pack('<iiIIff', u0, v0, nu, nv, step, 0.0) + bytes(2 * nodes)
            + bytes(classes) + bytes(2 * nu * nv) + struct.pack('<I', 0))


@unittest.skipIf(lupa is None, 'lupa.luajit21 is not installed')
class FarMap(unittest.TestCase):
    def setUp(self):
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute("package.path = %r .. package.path" % (str(LUA.parents[2]).replace('\\', '/') + '/?.lua;'))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        folder = Path(self.tmp.name)
        # the home raster: 4 x 3 pixels of 100 m from (1000, 2000); one forest pixel, one without data
        home = [1] * 12
        home[1 * 4 + 2] = FOREST       # u 2, v 1
        home[2 * 4 + 3] = NO_DATA      # u 3, v 2
        (folder / 'home.bin').write_bytes(raster(10, 20, 4, 3, 100.0, home))
        # a neighbour's raster, its frame 5000 m east of the landing frame, 12.5 m pixels
        (folder / 'other.bin').write_bytes(raster(0, 0, 400, 400, 12.5, [2] * 160000))
        self.make = self.lua.eval('''function(folder)
          local farmap = require('ge/extensions/e2r/farmap')
          return farmap.make({canopy = 16, rasters = {
            {path = folder .. '/home.bin', texKind = 'farmap_home'},
            {path = folder .. '/other.bin', texKind = 'farmap_other', real = true,
              -- landing (1000, 2000) is the neighbour's (-4000, 2000): a shift, no turn
              a = {1000, 2000, -4000, 2000, 1, 0, 0, 1}},
            {path = folder .. '/missing.bin', texKind = 'farmap_gone'}}})
        end''')
        self.map = self.make(self.tmp.name.replace('\\', '/'))

    def kind(self, x, y):
        R = self.map['at'](x, y)
        return R and R['texKind']

    def test_a_point_is_answered_by_the_first_raster_with_data_there(self):
        self.assertEqual(self.kind(1050, 2050), 'farmap_home')
        self.assertEqual(self.kind(1299, 2299), 'farmap_home')
        # the home pixel without data: nobody else covers it either
        self.assertIsNone(self.kind(1350, 2250))
        # past the home raster, inside the neighbour's (its x 0..5000 is the landing frame's 5000..10000)
        self.assertEqual(self.kind(5100, 2100), 'farmap_other')
        self.assertTrue(self.map['at'](5100, 2100)['real'])
        self.assertIsNone(self.kind(999, 2050))
        self.assertIsNone(self.kind(20000, 2050))

    def test_the_same_raster_is_the_same_table(self):
        # the generator groups triangles by the raster they are draped in
        self.assertTrue(self.lua.eval('function(m) return m.at(1050, 2050) == m.at(1250, 2150) end')(self.map))

    def test_uv_runs_over_the_raster_with_v_down(self):
        u, v = self.map['uv'](self.map['at'](1050, 2050), 1100, 2150)
        self.assertAlmostEqual(u, 100 / 400)
        self.assertAlmostEqual(v, 1 - 150 / 300)
        # a neighbour's point goes through its frame
        u, v = self.map['uv'](self.map['at'](5100, 2100), 6250, 4500)
        self.assertAlmostEqual(u, 1250 / 5000)
        self.assertAlmostEqual(v, 1 - 4500 / 5000)

    def test_a_forest_pixel_lifts_the_land_by_the_canopy(self):
        self.assertEqual(self.map['lift'](1250, 2150), 16)
        self.assertEqual(self.map['lift'](1050, 2050), 0)
        self.assertEqual(self.map['lift'](999, 2050), 0)

    def test_no_readable_raster_is_no_map(self):
        none = self.lua.eval('''function()
          return require('ge/extensions/e2r/farmap').make({rasters = {{path = '/nowhere.bin', texKind = 'x'}}})
        end''')()
        self.assertIsNone(none)


if __name__ == '__main__':
    unittest.main()
