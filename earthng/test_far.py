"""The far view keeps the ground's true shape and bends it with the Earth (far.lua).

An earlier fold put everything past 7.5 km on a rising bowl: the land stood up behind the town
like the inside of a dish. These tests hold the opposite: past the near world the ground only
sinks, as on a sphere, the far plane bounds what is drawn, and a coarser level hangs a skirt from
the rim of its hole so a seam between levels built for different cameras never opens.
"""
from pathlib import Path
import math
import struct
import unittest

from lupa.luajit21 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1] / 'mod/lua/ge/extensions/e2r/far.lua'


def slope_raster(half=2000.0, step=200.0, grade=0.2, base=200.0, cls=2):
    """EGF1 whose height rises with x, so an edge normal is the slope, not half of it."""
    n = int(2 * half / step)
    u0 = v0 = -n // 2
    heights = []
    for _v in range(n + 1):
        for u in range(n + 1):
            heights.append(int((base + grade * (u0 + u) * step + 500) * 4))
    elev = struct.pack(f'<{len(heights)}H', *heights)
    classes = bytes([cls]) * (n * n)
    head = b'EGF1' + bytes([1]) + struct.pack('<iiIIff', u0, v0, n, n, step, float('nan'))
    return head + elev + classes + bytes(n * n) + bytes(n * n) + struct.pack('<I', 0)


def flat_raster(half, step=200.0, height=100.0, cls=2, forest_box=None):
    """An EGF1 blob: a square region of `half` metres round the origin at one height and class."""
    n = int(2 * half / step)
    u0 = v0 = -n // 2
    elev = struct.pack(f'<{(n + 1) * (n + 1)}H', *([int((height + 500) * 4)] * ((n + 1) * (n + 1))))
    classes = bytearray([cls]) * (n * n)
    if forest_box:
        a0, b0, a1, b1 = forest_box
        for v in range(n):
            for u in range(n):
                x, y = (u0 + u + .5) * step, (v0 + v + .5) * step
                if a0 <= x <= a1 and b0 <= y <= b1:
                    classes[v * n + u] = 3
    head = b'EGF1' + bytes([1]) + struct.pack('<iiIIff', u0, v0, n, n, step, float('nan'))
    return head + elev + bytes(classes) + bytes(n * n) + bytes(n * n) + struct.pack('<I', 0)


class FarCurveTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime()
        self.lua.globals().far = self.lua.execute(ROOT.read_text(encoding='utf8'))
        self.far = self.lua.globals().far

    def test_flat_inside_the_near_world_then_a_sphere(self):
        r_eff = float(self.far.FAR.R_EFF)
        self.assertEqual(float(self.far.curve(3000, 5000)), 0)
        self.assertAlmostEqual(float(self.far.curve(10000, 5000)), (1e8 - 2.5e7) / (2 * r_eff), places=6)
        # standard refraction: a 2 m eye sees a plain end ~5.4 km out (geometric 5.0 km)
        horizon = math.sqrt(2 * r_eff * 2)
        self.assertGreater(horizon, 5300)
        self.assertLess(horizon, 5600)

    def test_skirts_cover_the_seam_of_a_late_camera(self):
        far = self.far.FAR
        for level in range(1, int(far.LEVELS)):
            s = float(far.BASE) * 2 ** level
            rim = (float(far.N) / 4 - 2) * s
            # the camera moved up to 2*sqrt(2) steps between the coarse and the fine build
            step = rim * (2 * math.sqrt(2) * s) / float(far.R_EFF)
            self.assertGreater(float(self.far.skirt(level)), step)


class FarLevelTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime()
        self.lua.globals().far = self.lua.execute(ROOT.read_text(encoding='utf8'))
        self.far = self.lua.globals().far
        self.lua.globals().blob = flat_raster(30000, forest_box=(-12000, 6000, -8000, 9000))
        self.lua.execute('R = far.parse(blob)')

    def levels(self, cam=(150.0, -90.0), hole=4600.0, levels=2):
        lua = self.lua
        lua.execute(f'out, P = far.buildLevels(R, {{x = {cam[0]}, y = {cam[1]}, z = 102}}, {hole}, {levels})')
        out = lua.globals().out
        result = {}
        for level in range(levels):
            built = out[level]
            if built is None:
                continue
            px, py = float(built.pos[1]), float(built.pos[2])
            meshes = {}
            for b in range(1, len(built.bands) + 1):
                band = built.bands[b]
                self.assertLess(int(band.faces), 12000, 'a band is one frame of createMesh')
                for k in range(1, len(band.meshes) + 1):
                    m = band.meshes[k]
                    verts = [(float(m.verts[i].x) + px, float(m.verts[i].y) + py, float(m.verts[i].z))
                             for i in range(1, len(m.verts) + 1)]
                    meshes.setdefault(str(m.material), []).extend(verts)
            result[level] = meshes
        return result

    def test_the_ground_only_sinks_with_distance(self):
        cam = (150.0, -90.0)
        built = self.levels(cam)
        far = self.far.FAR
        ground = [v for level in built.values() for v in level.get('e2rfar_meadow', [])]
        self.assertGreater(len(ground), 1000)
        top = 0
        for x, y, z in ground:
            d = math.hypot(x - cam[0], y - cam[1])
            if z > 99:   # skirts hang lower; the ground itself is at 100 minus the curve
                expect = 100 - float(self.far.curve(d, 4600)) - (float(far.DROP) if d < 5600 else 0)
                self.assertAlmostEqual(z, expect, delta=float(far.DROP) + .01)
            if d > 15000:
                top = max(top, z)
        # nothing out there rises over the near ground: no bowl
        self.assertLess(top, 100 - float(self.far.curve(15000, 4600)) + .01)

    def test_a_coarse_level_hangs_a_skirt_from_its_hole(self):
        built = self.levels()
        low = [z for z in (v[2] for v in built[1].get('e2rfar_meadow', []))]
        depth = float(self.far.skirt(1))
        self.assertTrue(any(z < 100 - depth + 1 for z in low), 'no skirt under the hole rim of level 1')

    def test_the_forest_stands_as_a_canopy(self):
        built = self.levels()
        canopy = [v for level in built.values() for v in level.get('e2rfar_canopy', [])]
        self.assertTrue(canopy)
        for x, y, z in canopy:
            self.assertGreater(z, 100 - float(self.far.curve(math.hypot(x, y), 4600)) + 10)

    def test_an_edge_normal_is_the_full_slope(self):
        self.assertAlmostEqual(float(self.far.FAR.FOG), 6e-5)
        self.lua.globals().blob = slope_raster()
        self.lua.execute('R = far.parse(blob)')
        built = self.levels(cam=(0.0, 0.0), hole=400.0, levels=1)
        meadow = built[0]['e2rfar_meadow']
        # west edge of the level: the old clamp made this about half the slope (-0.1)
        west = min(v[0] for v in meadow)
        normals = self.lua.globals().out[0].bands
        steep = []
        for b in range(1, len(normals) + 1):
            band = normals[b]
            px = float(self.lua.globals().out[0].pos[1])
            for k in range(1, len(band.meshes) + 1):
                mesh = band.meshes[k]
                if str(mesh.material) != 'e2rfar_meadow':
                    continue
                for i in range(1, len(mesh.verts) + 1):
                    z = float(mesh.verts[i].z)
                    if abs(float(mesh.verts[i].x) + px - west) < 1 and z > 200 + 0.2 * west - 2:
                        steep.append(float(mesh.normals[i].x))
        self.assertTrue(steep, 'no ground vertex on the west edge')
        self.assertLess(max(steep), -0.15)

    def test_nothing_past_the_far_plane(self):
        self.lua.execute('far.FAR.VIEW = 12000')
        built = self.levels(levels=2)
        for level in built.values():
            for verts in level.values():
                for x, y, _ in verts:
                    self.assertLess(math.hypot(x - 150, y + 90), 12000 + 2 * 400 * 1.5)


class FarTexturedTests(unittest.TestCase):
    """With a colour map the ground is one textured surface: forests swell, nothing stands as a box."""

    def setUp(self):
        self.lua = LuaRuntime()
        self.lua.globals().far = self.lua.execute(ROOT.read_text(encoding='utf8'))
        self.lua.globals().blob = flat_raster(30000, forest_box=(-12000, 6000, -8000, 9000))
        self.lua.execute("R = far.parse(blob); R.texMat = 'e2rfar_tex_test'")

    def test_one_textured_surface_with_uvs_and_a_forest_dome(self):
        lua = self.lua
        lua.execute('out, P = far.buildLevels(R, {x = 150, y = -90, z = 102}, 4600, 2)')
        out = lua.globals().out
        names, top, uvs = set(), 0, 0
        for level in range(2):
            built = out[level]
            px, py = float(built.pos[1]), float(built.pos[2])
            for b in range(1, len(built.bands) + 1):
                band = built.bands[b]
                for k in range(1, len(band.meshes) + 1):
                    m = band.meshes[k]
                    names.add(str(m.material))
                    self.assertEqual(len(m.uvs), len(m.verts))
                    for i in range(1, len(m.verts) + 1):
                        u, v = float(m.uvs[i].u), float(m.uvs[i].v)
                        x, y = float(m.verts[i].x) + px, float(m.verts[i].y) + py
                        # the raster spans -30..30 km: u runs west to east, v north to south
                        self.assertAlmostEqual(u, (x + 30000) / 60000, places=4)
                        self.assertAlmostEqual(v, 1 - (y + 30000) / 60000, places=4)
                        uvs += 1
                        if -11000 < x < -9000 and 7000 < y < 8000:
                            ground = 100 - float(self.far.curve(math.hypot(x - 150, y + 90), 4600))
                            top = max(top, float(m.verts[i].z) - ground)
        self.assertEqual(names, {'e2rfar_tex_test'})
        self.assertGreater(uvs, 1000)
        self.assertGreater(top, float(self.far.FAR.CANOPY) - 1, 'the wood stands up as a dome')

    @property
    def far(self):
        return self.lua.globals().far


class FarRasterTests(unittest.TestCase):
    def parsed(self, marks):
        lua = LuaRuntime()
        lua.globals().far = lua.execute(ROOT.read_text(encoding='utf8'))
        lua.globals().blob = flat_raster(2000)[:-4] + struct.pack('<I', len(marks)) + b''.join(marks)
        lua.execute('parsed = far.parse(blob)')
        return lua, lua.globals().parsed

    def test_legacy_29_byte_landmarks_decode(self):
        # an earlier writer stored 7 f32 and a u8 kind
        marks = [struct.pack('<7fB', 100 * k, -50, 120, 40 + k, 12, 8, .5, 2) for k in range(3)]
        lua, parsed = self.parsed(marks)
        self.assertEqual(int(parsed.markCount), 3)
        self.assertAlmostEqual(float(lua.eval('parsed.markFloats[8 + 3]')), 41)
        self.assertEqual(float(lua.eval('parsed.markFloats[8 + 7]')), 2)

    def test_32_byte_landmarks_decode(self):
        marks = [struct.pack('<8f', 100 * k, -50, 120, 40 + k, 12, 8, .5, 1) for k in range(2)]
        lua, parsed = self.parsed(marks)
        self.assertEqual(int(parsed.markCount), 2)
        self.assertAlmostEqual(float(lua.eval('parsed.markFloats[8 + 3]')), 41)
        self.assertEqual(float(lua.eval('parsed.markFloats[7]')), 1)

    def glass_faces(self, height):
        mark = struct.pack('<8f', 8000, 0, 100, height, 18, 12, 0, 1)
        blob = flat_raster(20000)[:-4] + struct.pack('<I', 1) + mark
        lua = LuaRuntime()
        lua.globals().far = lua.execute(ROOT.read_text(encoding='utf8'))
        lua.globals().blob = blob
        lua.execute('R = far.parse(blob); marks = far.buildMarks(R, {x=0, y=0, z=100}, 2000)')
        n = int(lua.eval('#marks.meshes'))
        glass = 0
        for i in range(1, n + 1):
            if str(lua.eval(f'marks.meshes[{i}].material')) == 'e2rfar_glass':
                glass = int(lua.eval(f'#marks.meshes[{i}].faces'))
        self.assertEqual(int(lua.eval('marks.count')), 1)
        return glass

    def test_a_tall_tower_carries_more_glass_than_a_short_block(self):
        # one row is 4 walls * 2 triangles * 3 indices; 90 m is three rows, 42 m is one
        self.assertEqual(self.glass_faces(42), 24)
        self.assertEqual(self.glass_faces(90), 72)


if __name__ == '__main__':
    unittest.main()
