"""Climate biomes of the native generator (biome.lua, generator.lua bio): a synthetic climate block
round a flat or high test tile, the real generator through LuaJIT.

Run with: python -m unittest discover -s earthng -p test_biome.py
"""
from collections import Counter
from pathlib import Path
import struct
import tempfile
import unittest

from lupa.luajit21 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
LUA = ROOT / 'mod/lua'
# a region frame at 20.5 E, 45.5 N: one degree is ~78 km east, ~111 km north
GEO = [0, 0, 20.5, 45.5, 1 / 78000, 0, 0, 1 / 111000]


def climate(folder, cls, sea_west=False):
    """The 10 degree block 20-30 E, 40-50 N, every cell of class cls (the west half sea)."""
    w = h = 600
    cells = bytearray([cls]) * (w * h)
    if sea_west:
        for y in range(h):
            cells[y * w:y * w + 30] = bytes(30)       # 20-20.5 E sea
    (folder / '20_13.bin').write_bytes(b'EKG1' + struct.pack('<HH', w, h) + bytes(cells))


class BiomeTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def generator(self, biome=True):
        lua = LuaRuntime(unpack_returned_tuples=True)
        if biome:
            lua.execute(f"package.path = '{LUA.as_posix()}/?.lua;' .. package.path")
        gen = lua.execute((LUA / 'ge/extensions/e2r/generator.lua').read_text(encoding='utf8'))
        if biome:
            module = lua.eval('require')('ge/extensions/e2r/biome')
            module.ROOT = self.root.as_posix() + '/'
            module.present = True
        return lua, gen

    def build(self, lua, gen, height=120, geo=True, **extra):
        def table(v):
            if isinstance(v, dict):
                return lua.table_from({k: table(x) for k, x in v.items()})
            if isinstance(v, list):
                return lua.table_from([table(x) for x in v])
            return v
        n = 41
        # a 25 m DEM, a gentle slope west to east plus the base height
        heights = [height + 20 + 0.02 * (k % n) * 25 for k in range(n * n)]
        cells = [dict(roads=[], junctions=[], buildings=[], areas=[], lines=[], points=[],
                      terrain=dict(rect=[-250, -250, 750, 750], nx=n, ny=n, heights=heights))]
        options = dict(tileSize=500, seaLevel=20, latitude=45.5, maxTrees=2400, maxGrass=4000, maxRocks=120, **extra)
        if geo:
            options['geo'] = GEO
        road, scene = gen.build(table(cells), 0, 0, table(options))[:2]
        ground, plants = Counter(), Counter()
        for manifest in (road, scene):
            for item in manifest['items'].values():
                if item.kind == 'proc':
                    for mesh in item.meshes.values():
                        ground[mesh.material] += len(mesh.faces) // 3
                elif item.kind == 'static':
                    plants[item.shape.split('/')[-1].replace('.dae', '')] += 1
        return ground, plants, scene

    def test_temperate_climate_builds_exactly_what_the_generator_built_before(self):
        climate(self.root, 26)               # Dfb, Kyiv's
        lua, gen = self.generator()
        with_climate = self.build(lua, gen)[:2]
        lua0, gen0 = self.generator(biome=False)
        self.assertEqual(with_climate, self.build(lua0, gen0, geo=False)[:2])

    def test_desert_lays_desert_ground_shrubs_and_stones_and_no_green_grass(self):
        climate(self.root, 4)                # BWh
        lua, gen = self.generator()
        ground, plants, scene = self.build(lua, gen)
        self.assertGreater(ground['e2rf_desert'], ground['e2rf_ground'] * 10)
        self.assertFalse([p for p in plants if p.startswith('s_grass_green')])
        self.assertTrue([p for p in plants if 'grey_bush' in p or 'dry_bush' in p or 'dry_plant' in p])
        self.assertTrue([p for p in plants if 'rocks_desert' in p or 'utah_boulder' in p or 'utah_rock' in p])
        # the level files those shapes need are named for world.lua
        self.assertTrue(any('/johnson_valley/' in m for m in scene['stockMaterials'].values()))

    def test_summit_above_the_snow_line_is_snow_rock_and_scree(self):
        climate(self.root, 29)               # ET of a mid-latitude range: the slopes' climate is searched
        lua, gen = self.generator()
        ground, plants, _ = self.build(lua, gen, height=4200)
        high = ground['e2rf_snow'] + ground['e2rf_snow_edge'] + ground['e2rf_scree'] + ground['e2rf_bare_rock']
        self.assertGreater(high, sum(ground.values()) * .3)
        self.assertEqual(ground['e2rf_ground'], 0)
        self.assertFalse([p for p in plants if p.startswith('tree_oak') or p.startswith('s_grass')])

    def test_ground_under_the_sea_level_far_inland_is_dry_land(self):
        climate(self.root, 4)
        lua, gen = self.generator()
        ground, _, _ = self.build(lua, gen, height=-90)    # Death Valley's floor
        self.assertEqual(ground['e2rf_water'], 0)
        self.assertGreater(ground['e2rf_desert'], 0)
        # by the sea the plane stays: the same depth with the sea 2 km west
        climate(self.root, 4, sea_west=True)
        lua, gen = self.generator()
        ground, _, _ = self.build(lua, gen, height=-90)
        self.assertGreater(ground['e2rf_water'], 0)


if __name__ == '__main__':
    unittest.main()
