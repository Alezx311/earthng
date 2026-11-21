"""The flora (mod/lua/ge/extensions/e2r/flora.lua): zones, stands, the trees of a stand and their models."""
from collections import Counter
from pathlib import Path
import unittest

from lupa.luajit21 import LuaRuntime

LUA = Path(__file__).resolve().parents[1] / 'mod/lua/ge/extensions/e2r'


def load():
    lua = LuaRuntime(unpack_returned_tuples=True)
    flora = lua.eval('function(s) return assert(load(s, "@flora.lua"))() end')((LUA / 'flora.lua').read_text(encoding='utf8'))
    return lua, flora


class ZoneTest(unittest.TestCase):
    def setUp(self):
        self.lua, self.flora = load()

    def test_places_fall_in_their_zones(self):
        zone = self.flora.zone
        self.assertEqual(zone(30.36, 50.533, 150), 'polissia')        # Pushcha-Vodytsia
        self.assertEqual(zone(30.73, 50.87, 110), 'polissia')         # the Desna-Dnipro pinewoods
        self.assertEqual(zone(30.508, 50.3835, 170), 'foreststeppe')  # Holosiiv
        self.assertEqual(zone(34.55, 49.59, 150), 'foreststeppe')     # Poltava
        self.assertEqual(zone(32.6, 46.64, 40), 'steppe')             # Kherson
        self.assertEqual(zone(30.72, 46.48, 40), 'steppe')            # Odesa
        self.assertEqual(zone(24.55, 48.45, 620), 'carpathians')      # Yaremche
        self.assertEqual(zone(22.3, 48.62, 120), 'foreststeppe')      # the Transcarpathian lowland
        self.assertEqual(zone(34.17, 44.5, 60), 'crimea')             # Yalta
        self.assertEqual(zone(34.1, 45.6, 30), 'steppe')              # the Crimean steppe
        self.assertIsNone(zone(2.35, 48.85, 40))                      # Paris

    def test_a_border_wanders_but_stays_near_its_line(self):
        # along Kyiv's longitude the Polissia begins at 50.44; +-0.12 degrees of noise
        north = sum(self.flora.zone(30.5, 50.44 + .2, 150, x * 4000, 0) == 'polissia' for x in range(40))
        south = sum(self.flora.zone(30.5, 50.44 - .2, 150, x * 4000, 0) == 'foreststeppe' for x in range(40))
        mixed = Counter(self.flora.zone(30.5, 50.44, 150, x * 4000, x * 1500) for x in range(60))
        self.assertEqual((north, south), (40, 40))
        self.assertGreater(min(mixed['polissia'], mixed['foreststeppe']), 8)

    def test_the_carpathian_belts_follow_the_height(self):
        self.assertEqual(self.flora.belt(400, .5), 'low')
        self.assertEqual(self.flora.belt(800, .5), 'beech')
        self.assertEqual(self.flora.belt(1300, .5), 'spruce')


class StandTest(unittest.TestCase):
    def setUp(self):
        self.lua, self.flora = load()
        self.q = self.lua.eval('function(zone, e, needle, mixed, wet, lon) return {zone = zone, e = e, needle = needle, '
                               'mixed = mixed, wet = wet, lon = lon or 30} end')

    def stands(self, q, step=37, n=40):
        return [self.flora.stand(q, x * step + 3.3, y * step * 1.31) for x in range(n) for y in range(n)]

    def test_every_composition_names_species_with_models(self):
        species = set(self.flora.SPECIES.keys())
        stock = set(self.flora.STOCK.keys())

        def lists(zone):
            for key in ('conifer_stand', 'broadleaf', 'broadleaf_east', 'high', 'wet', 'under', 'under_conifer'):
                if zone[key] is not None:
                    yield key, zone[key]
        for name, zone in self.flora.ZONES.items():
            tables = [zone] + [zone[b] for b in ('low', 'beech', 'spruce') if zone[b] is not None]
            for table in tables:
                for key, entries in lists(table):
                    for entry in entries.values():
                        self.assertIn(entry[1], species, (name, key))
                        # Ukraine's own zones stand without the flora pack: every species of
                        # theirs has a stand-in among the game's trees
                        if not zone.world:
                            self.assertIn(entry[1], stock, (name, key))
        for kind, entries in self.flora.SETTLED.items():
            total = sum(entry[2] for entry in entries.values())
            bare = sum(entry[2] for entry in entries.values() if entry[1] not in stock)
            for entry in entries.values():
                self.assertIn(entry[1], species, kind)
            # a town's and a yard's lists name the pack's shrubs and herbs too: a minor share,
            # and never the leading species
            self.assertIn(entries[1][1], stock, kind)
            self.assertLess(bare / total, .4, kind)
        for zone, kinds in self.flora.SETTLED_WORLD.items():
            self.assertEqual(sorted(kinds.keys()), sorted(self.flora.SETTLED.keys()), zone)
            for kind, entries in kinds.items():
                for entry in entries.values():
                    self.assertIn(entry[1], species, (zone, kind))
        for layer, entries in self.flora.LAYERS.items():
            for entry in entries.values():
                self.assertIn(entry[1], species, layer)
                self.assertNotIn(entry[1], stock, layer)

    def test_polissia_is_pinewood_with_stands_of_broadleaves(self):
        stands = self.stands(self.q('polissia', 120))
        conifer = sum(s.conifer for s in stands) / len(stands)
        self.assertAlmostEqual(conifer, .64, delta=.1)
        leaders = Counter(s.leader for s in stands if s.conifer)
        self.assertGreater(leaders['pine'] / sum(leaders.values()), .6)
        broad = Counter(s.leader for s in stands if not s.conifer)
        self.assertGreaterEqual(len(broad), 4)
        self.assertNotIn('pine', broad)

    def test_the_forest_steppe_is_oak_and_the_hornbeam_stays_west_of_the_dnipro(self):
        west = Counter(s.leader for s in self.stands(self.q('foreststeppe', 150, False, None, None, 29.5)))
        east = Counter(s.leader for s in self.stands(self.q('foreststeppe', 150, False, None, None, 34.5)))
        self.assertEqual(west.most_common(1)[0][0], 'oak')
        self.assertGreater(west['hornbeam'], 0)
        self.assertEqual(east['hornbeam'], 0)

    def test_the_maps_leaf_type_decides_where_it_is_known(self):
        self.assertTrue(all(s.conifer for s in self.stands(self.q('foreststeppe', 150, True), n=12)))
        self.assertFalse(any(s.conifer for s in self.stands(self.q('polissia', 150, False), n=12)))
        mixed = self.stands(self.q('foreststeppe', 150, None, True))
        self.assertAlmostEqual(sum(s.conifer for s in mixed) / len(mixed), .5, delta=.1)

    def test_by_the_water_stand_alder_and_willow(self):
        leaders = Counter(s.leader for s in self.stands(self.q('polissia', 100, None, None, True)))
        self.assertEqual(leaders.most_common(1)[0][0], 'alder')
        self.assertNotIn('pine', leaders)

    def test_the_carpathians_change_with_the_height(self):
        low = Counter(s.leader for s in self.stands(self.q('carpathians', 400)))
        mid = Counter(s.leader for s in self.stands(self.q('carpathians', 800)))
        high = Counter(s.leader for s in self.stands(self.q('carpathians', 1350)))
        self.assertIn(low.most_common(1)[0][0], ('oak', 'hornbeam', 'beech'))
        self.assertEqual(mid.most_common(1)[0][0], 'beech')
        self.assertEqual(high.most_common(1)[0][0], 'spruce')

    def test_a_stand_is_mostly_its_leader_and_old_stands_are_taller(self):
        stand = self.flora.stand(self.q('polissia', 120, True), 100, 100)
        trees = Counter(self.flora.tree(stand, k / 500, .5)[0] for k in range(500))
        self.assertGreater(trees[stand.leader] / 500, .6)
        self.assertGreater(len(trees), 2)
        young, old = self.lua.eval('function(s) local a, b = {}, {}; for k, v in pairs(s) do a[k] = v; b[k] = v end; '
                                   'a.age, b.age = .05, .95; return a, b end')(stand)
        _, low = self.flora.tree(young, 0, .5)
        _, high = self.flora.tree(old, 0, .5)
        grown = self.flora.SPECIES[stand.leader].height
        self.assertLess(low, grown * .7)
        self.assertGreater(high, grown * .95)

    def test_neighbouring_points_share_a_stand(self):
        q = self.q('polissia', 120)
        a = self.flora.stand(q, 5000, 5000)
        b = self.flora.stand(q, 5006, 5004)
        self.assertEqual((a.conifer, a.leader), (b.conifer, b.leader))
        self.assertAlmostEqual(a.age, b.age, delta=.08)

    def test_undergrowth_is_shrubs_and_young_trees(self):
        stand = self.flora.stand(self.q('foreststeppe', 150, False), 100, 100)
        seen = Counter()
        for k in range(300):
            species, height = self.flora.undergrowth(stand, k / 300, (k * 7 % 300) / 300)
            seen[species] += 1
            self.assertTrue(self.flora.SPECIES[species].shrub, species)
            self.assertLess(height, 8)
        self.assertEqual(seen.most_common(1)[0][0], 'hazel')

    def test_a_streets_row_is_one_species_a_yard_is_fruit_trees(self):
        row = Counter(self.flora.planted('row', 'foreststeppe', .3, k / 200, .5)[0] for k in range(200))
        self.assertGreater(row.most_common(1)[0][1] / 200, .85)
        garden = Counter(self.flora.planted('garden', 'foreststeppe', k / 200, (k * 13 % 200) / 200, .5)[0] for k in range(200))
        self.assertEqual(garden.most_common(1)[0][0], 'fruit')
        _, height = self.flora.planted('town', 'foreststeppe', .5, .99, .5)
        self.assertLess(height, 22)


class ModelTest(unittest.TestCase):
    def setUp(self):
        self.lua, self.flora = load()

    def test_a_tree_is_the_model_nearest_its_height_scaled_to_it(self):
        shape, scale, materials, own = self.flora.plant('oak', 16, 0)
        self.assertIn('tree_oak_', shape)
        self.assertIsNone(materials)
        self.assertAlmostEqual(own * scale, 16, delta=.01)
        small, scale, _, own = self.flora.plant('oak', 8, 0)
        self.assertIn('sml', small)
        # past what a model stretches to, it stays at its limit
        _, scale, _, own = self.flora.plant('pine', 60, 0)
        self.assertAlmostEqual(scale, 1.1)
        _, scale, _, own = self.flora.plant('pine', 2, 0)
        self.assertAlmostEqual(scale, .6)

    def test_models_of_much_the_same_fit_alternate(self):
        shapes = {self.flora.plant('oak', 15.4, h)[0] for h in range(12)}
        self.assertGreaterEqual(len(shapes), 3)

    def test_the_packs_models_replace_the_stand_ins(self):
        manifest = self.lua.eval('''{species = {pine = {models = {
            {shape = '/art/shapes/earthng/flora/trees/pine/pine_s1_a70.dae', height = 26, materials = '/art/shapes/earthng/flora/trees/pine/main.materials.json'},
            {shape = '/art/shapes/earthng/flora/trees/pine/pine_s2_a45.dae', height = 17, materials = '/art/shapes/earthng/flora/trees/pine/main.materials.json'}}}}}''')
        self.flora.setManifest(manifest)
        shape, scale, materials, own = self.flora.plant('pine', 25, 0)
        self.assertEqual(shape, '/art/shapes/earthng/flora/trees/pine/pine_s1_a70.dae')
        self.assertEqual(materials, '/art/shapes/earthng/flora/trees/pine/main.materials.json')
        self.assertAlmostEqual(scale, 25 / 26)
        self.assertEqual(self.flora.plant('pine', 15, 0)[0], '/art/shapes/earthng/flora/trees/pine/pine_s2_a45.dae')
        # a species the pack lacks keeps the game's own trees
        self.assertIn('/levels/east_coast_usa/', self.flora.plant('oak', 16, 0)[0])
        self.assertTrue(self.flora.used['/art/shapes/earthng/flora/trees/pine/pine_s1_a70.dae'])

    def test_a_zones_shapes_for_the_warm_up_are_sorted_and_whole(self):
        shapes = list(self.flora.shapesOf('polissia').values())
        self.assertEqual(shapes, sorted(set(shapes)))
        self.assertTrue(any('scots_pine' in s for s in shapes))
        self.assertTrue(any('Juniper' in s for s in shapes))
        self.assertGreater(len(shapes), 20)
        self.assertEqual(len(list(self.flora.shapesOf('nowhere').values())), 0)

    def test_the_rank_of_the_noise_is_even(self):
        field = self.flora.field
        values = [field(x * 61.7, y * 47.3, 130, 603) for x in range(60) for y in range(60)]
        for share in (.1, .3, .64, .9):
            self.assertAlmostEqual(sum(v < share for v in values) / len(values), share, delta=.06)


class WorldTest(unittest.TestCase):
    """The pack's own species: the zones of other climates, the small plants, the blocks."""

    def setUp(self):
        self.lua, self.flora = load()
        self.place = self.lua.eval('function(group) return {group = group} end')
        self.q = self.lua.eval('function(zone, needle) return {zone = zone, e = 30, needle = needle, lon = 100} end')

    def pack(self, *names):
        """A flora pack with one model of each of these species."""
        entries = ', '.join(
            f"{n} = {{models = {{{{shape = '/art/shapes/earthng/flora/trees/{n}/{n}_s1.dae', height = 10}}}}, "
            f"use = {{'forest'}}, layer = 'shrub', region = 'r', latin = 'L'}}" for n in names)
        self.flora.setManifest(self.lua.eval('{species = {' + entries + '}}'))

    def test_without_the_pack_other_climates_keep_their_old_sets(self):
        for group in ('rainforest', 'savanna', 'desert', 'mediterranean', 'temperate', 'boreal', 'steppe'):
            self.assertIsNone(self.flora.worldZone(self.place(group)), group)
        self.assertIsNone(self.flora.worldZone(self.place('ice')))
        self.assertIsNone(self.flora.layer('floor', .3, .5))
        self.assertEqual(len(list(self.flora.cover('bank').values())), 0)
        self.assertEqual(len(list(self.flora.blocks().values())), 0)
        # a yard has what the game's own trees can be: no sunflower without its model
        seen = {self.flora.planted('garden', 'foreststeppe', k / 97, k / 211, .5)[0] for k in range(400)}
        self.assertFalse(seen & {'sunflower', 'corn', 'pumpkin', 'currant', 'garden_rose', 'hydrangea'})

    def test_a_climates_zone_needs_most_of_its_trees(self):
        self.pack('rubber_tree', 'mango')                           # 52 of the canopy's 100 parts
        self.assertFalse(self.flora.zoneOwn('tropics'))
        self.assertIsNone(self.flora.worldZone(self.place('rainforest')))
        self.pack('rubber_tree', 'mango', 'breadfruit')
        self.assertTrue(self.flora.zoneOwn('tropics'))
        self.assertEqual(self.flora.worldZone(self.place('rainforest')), 'tropics')
        # another climate's trees are still not there
        self.assertIsNone(self.flora.worldZone(self.place('desert')))

    def test_a_rainforest_is_its_canopy_with_bananas_and_tree_ferns_under_it(self):
        self.pack('rubber_tree', 'mango', 'breadfruit', 'coconut_palm', 'banana', 'tree_fern', 'bamboo', 'monstera')
        stand = self.flora.stand(self.q('tropics', None), 40, 60)
        self.assertFalse(stand.conifer)
        self.assertEqual(stand.floor, 'jungle_floor')
        trees = Counter(self.flora.tree(stand, k / 300, .5)[0] for k in range(300))
        self.assertTrue(set(trees) <= {'rubber_tree', 'mango', 'breadfruit', 'coconut_palm', 'banana'})
        self.assertGreaterEqual(len(trees), 4)
        under = {self.flora.undergrowth(stand, k / 100, .5)[0] for k in range(100)}
        self.assertEqual(under, {'banana', 'tree_fern', 'bamboo'})
        # the map's needle-leaved wood in a zone without conifers is its broadleaf wood
        self.assertFalse(self.flora.stand(self.q('tropics', True), 40, 60).conifer)
        species, height = self.flora.layer('jungle_floor', .2, .5)
        self.assertEqual(species, 'monstera')
        self.assertAlmostEqual(height, 1, delta=.3)
        # a street there is an avenue of palms
        row = Counter(self.flora.planted('row', 'tropics', .2, k / 200, .5)[0] for k in range(200))
        self.assertEqual(row.most_common(1)[0][0], 'coconut_palm')

    def test_a_desert_wood_has_no_floor_and_a_pinewood_has_heather(self):
        self.pack('saguaro', 'acacia', 'date_palm', 'opuntia', 'agave', 'heather', 'fern')
        self.assertIsNone(self.flora.stand(self.q('desert', None), 10, 10).floor)
        stand = self.flora.stand(self.q('polissia', True), 10, 10)
        self.assertEqual(stand.floor, 'pine_floor')
        self.assertEqual(self.flora.stand(self.q('polissia', False), 10, 10).floor, 'floor')
        plants = Counter(self.flora.layer('pine_floor', k / 100, .5)[0] for k in range(100))
        self.assertEqual(set(plants), {'heather', 'fern'})
        self.assertGreater(plants['heather'], plants['fern'])

    def test_a_village_yard_has_a_kitchen_garden_and_a_town_courtyard_has_not(self):
        self.pack('sunflower', 'corn', 'pumpkin', 'currant', 'garden_rose', 'hydrangea', 'hedge', 'barberry')
        garden = Counter(self.flora.planted('garden', 'foreststeppe', k / 97, k / 400, .5)[0] for k in range(400))
        yard = Counter(self.flora.planted('yard', 'foreststeppe', k / 97, k / 400, .5)[0] for k in range(400))
        self.assertTrue({'sunflower', 'corn', 'currant'} <= set(garden))
        self.assertFalse(set(yard) & {'sunflower', 'corn', 'pumpkin'})
        self.assertEqual(garden.most_common(1)[0][0], 'fruit')
        self.assertEqual(yard.most_common(1)[0][0], 'fruit')
        # a sunflower is a sunflower's height, not a tree's
        heights = [self.flora.planted('garden', 'foreststeppe', k / 97, k / 400, .5)[1] for k in range(400)
                   if self.flora.planted('garden', 'foreststeppe', k / 97, k / 400, .5)[0] == 'sunflower']
        self.assertTrue(heights and max(heights) < 3)

    def test_a_layers_models_are_listed_for_the_ground_cover(self):
        self.pack('reed', 'cattail')
        cover = list(self.flora.cover('bank').values())
        self.assertEqual(sorted(c.species for c in cover), ['cattail', 'reed'])
        self.assertTrue(all(c.shape.endswith('_s1.dae') and c.share > 0 for c in cover))

    def test_the_pack_is_a_list_of_blocks(self):
        self.pack('oak', 'banana')
        blocks = list(self.flora.blocks().values())
        self.assertEqual([b.id for b in blocks], ['banana_s1', 'oak_s1'])
        self.assertEqual((blocks[0].species, blocks[0].layer, blocks[0].region, blocks[0].height), ('banana', 'shrub', 'r', 10))
        self.assertEqual(list(blocks[0].use.values()), ['forest'])

    def test_a_landing_warms_its_own_zones_floor(self):
        self.pack('monstera', 'fern', 'heather', 'reed')

        def has(zone, species):
            return any(f'/{species}/' in shape for shape in self.flora.shapesOf(zone).values())
        self.assertTrue(has('foreststeppe', 'fern') and has('foreststeppe', 'heather') and has('foreststeppe', 'reed'))
        self.assertFalse(has('foreststeppe', 'monstera'))
        self.assertTrue(has('tropics', 'monstera'))
        self.assertFalse(has('tropics', 'heather'))
        self.assertFalse(has('desert', 'fern'))

    def test_every_zone_has_a_name_for_the_lab(self):
        names = {entry[1] for entry in self.flora.zoneChoices().values()}
        self.assertEqual(names, set(self.flora.ZONES.keys()))
        for group, zone in self.flora.WORLD.items():
            self.assertIn(zone, names, group)


if __name__ == '__main__':
    unittest.main()
