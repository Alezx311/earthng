"""The proving ground's plan (proving_ground.py, proving_zones.py): the island at Point Nemo.

    .venv/Scripts/python.exe -m unittest discover -s earthng -p "test_proving_ground.py"

The pack itself is built by proving_ground.py; these check the plan it is built from.
"""
from collections import defaultdict
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

import proving_ground as ground
import proving_universes as universes
import proving_zones as zones
from fast_sources import DRIVABLE, Frame


class PlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = ground.make_plan()

    def test_frame_is_the_middle_of_the_package(self):
        w, s, e, n = ground.box()
        self.assertAlmostEqual((w + e) / 2, ground.CENTRE[1], places=6)
        self.assertAlmostEqual((s + n) / 2, ground.CENTRE[0], places=6)
        frame = ground.frame()
        x, y = frame.local(ground.CENTRE[1], ground.CENTRE[0])
        self.assertLess(abs(float(x)) + abs(float(y)), 1.)
        # Point Nemo itself is on the island
        x, y = frame.local(ground.POINT_NEMO[1], ground.POINT_NEMO[0])
        self.assertGreater(float(ground.inland(np.float64(x), np.float64(y))), 500.)

    def test_every_tile_has_a_subject_a_start_and_cameras(self):
        tiles = self.plan.tiles
        count = sum((b['tiles'][1] - b['tiles'][0]) * (b['tiles'][3] - b['tiles'][2]) for b in ground.BLOCKS)
        self.assertEqual(len(tiles), count)
        self.assertEqual(len([t for t in tiles.values() if t['block'] == 'main']), len(ground.COLS) * len(ground.ROWS))
        for name in ('A1', 'N10', 'MT-A1', 'MT-P6', 'DS-A1', 'SN-E12', 'MD-A1', 'BR-A1', 'BR-E6'):
            self.assertIn(name, tiles)
        frame = ground.frame()
        for name, tile in tiles.items():
            self.assertNotEqual(tile['zone'], 'free', name)
            self.assertEqual(ground.code(tile['i'], tile['j']), name)
            self.assertEqual(ground.block_of(tile['i'], tile['j'])['id'], tile['block'])
            self.assertTrue(tile['title'], name)
            self.assertGreaterEqual(len(tile['views']), 3, name)
            # the start and the street camera stand in the tile they belong to
            for x, y in (tile['at'][:2], tile['views'][0]['eye'][:2]):
                self.assertEqual((int(x // ground.TILE), int(y // ground.TILE)), (tile['i'], tile['j']), name)
            lon, lat = self.plan.lonlat(*tile['at'][:2])
            self.assertEqual(frame.tile_of(lon, lat), (tile['i'], tile['j']), name)

    def test_tables_fill_their_rows(self):
        columns = len(ground.COLS) - 1          # column H is the junctions
        for table in (zones.CLASSES, zones.PATHS, zones.SURFACES, zones.LANES, zones.TOWN, zones.WORKS,
                      zones.STREET, zones.PLANTS, zones.WATER, zones.RELIEF):
            self.assertEqual(len(table), columns)
        self.assertEqual(len(zones.COVERS), columns * 4)
        self.assertEqual(len(zones.ROWS_PLAN), len(ground.ROWS))

    def test_roads_are_one_net(self):
        """Every tile's avenue is joined to the ring road by ways that share nodes."""
        parent = {}

        def find(a):
            while parent.setdefault(a, a) != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a
        roads = [(ids, tag) for ids, tag in self.plan.ways if tag.get('highway') in DRIVABLE and tag.get('area') != 'yes']
        for ids, _ in roads:
            for n in ids[1:]:
                parent[find(n)] = find(ids[0])
        ring = next(ids for ids, tag in roads if tag.get('name', '').startswith('Кільцева'))
        root = find(ring[0])
        apart = defaultdict(int)
        for ids, tag in roads:
            if find(ids[0]) != root:
                apart[tag.get('name', '?')] += 1
        # the off-road tile's avenue is a track on purpose (not a road of the net), the rest is one net
        self.assertEqual(dict(apart), {})
        named = {tag['name'].split(' ', 1)[0] for _, tag in roads if tag.get('name', '')[:1].isalpha()}
        # every tile with a subject has its avenue in the net (N1 and its copies: the off-road track)
        missing = [name for name, tile in self.plan.tiles.items()
                   if tile['zone'] != 'wild' and name not in named and tile['title'] != 'Бездоріжжя']
        self.assertEqual(missing, [])

    def test_no_road_lies_on_another(self):
        seen = {}
        for ids, tag in self.plan.ways:
            if tag.get('highway') in DRIVABLE and tag.get('area') != 'yes':
                for a, b in zip(ids, ids[1:]):
                    key = (min(a, b), max(a, b), tag.get('layer', '0'))
                    self.assertNotIn(key, seen, f"{tag.get('name')} over {seen.get(key)}")
                    seen[key] = tag.get('name')

    def test_coastline_keeps_the_land_on_its_left(self):
        ids = next(ids for ids, tag in self.plan.ways if tag.get('natural') == 'coastline')
        self.assertEqual(ids[0], ids[-1])
        pts = [self.plan.points[n][:2] for n in ids]
        area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:])) / 2
        self.assertGreater(area, 0)             # counter-clockwise
        self.assertGreater(area, (ground.LAND[2] - ground.LAND[0]) * (ground.LAND[3] - ground.LAND[1]))

    def test_heights(self):
        h = lambda x, y: float(self.plan.height(np.float64(x), np.float64(y)))
        self.assertAlmostEqual(h(-3250, 1250), ground.BASE, places=2)        # a plain tile of the surfaces row
        self.assertLess(h(9000, 0), -20)                                     # open sea
        self.assertLess(h(0, 9000), -20)
        edge = ground.LAND[2] + ground.SHORE
        self.assertLess(h(edge + 30, -2000), 0)
        self.assertGreater(h(edge - 30, -2000), 0)
        # row 1: the ridge of the 10 % tile is 18 m over the land, its foot is level
        grade = self.plan.tiles['B1']
        x0, y0 = grade['i'] * ground.TILE, grade['j'] * ground.TILE
        self.assertAlmostEqual(h(x0 + 250, y0 + 250), ground.BASE + 18, places=1)
        self.assertAlmostEqual(h(x0 + 30, y0 + 250), ground.BASE, places=1)
        self.assertAlmostEqual((h(x0 + 200, y0 + 250) - h(x0 + 100, y0 + 250)) / 100, .10, places=3)
        # row 2: the river runs in a bed under its banks
        river = self.plan.tiles['A2']
        x0, y0 = river['i'] * ground.TILE, river['j'] * ground.TILE
        self.assertLess(h(x0 + 250, y0 + 250), h(x0 + 60, y0 + 250) - 3)
        # no relief of a tile leaks far into the next row
        self.assertAlmostEqual(h(x0 + 60, y0 + 250), ground.BASE, places=1)

    def test_catalogue_is_what_the_game_reads(self):
        catalogue = self.plan.catalogue()
        text = json.dumps(catalogue, ensure_ascii=False)
        self.assertLess(len(text.encode('utf8')), 700_000)
        self.assertEqual([b['id'] for b in catalogue['blocks']], ['main', 'mountains', 'desert', 'snow', 'mud', 'jungle', 'spans', 'thanks'])
        self.assertEqual((catalogue['blocks'][0]['cols'], catalogue['blocks'][0]['rows']),
                         ([ground.COLS[0], ground.COLS[-1]], [ground.ROWS[0], ground.ROWS[-1]]))
        self.assertEqual(catalogue['zones'][0]['id'], 'studio')
        self.assertEqual([z['id'] for z in catalogue['zones']][-7:], ['mountains', 'desert', 'snow', 'mud', 'jungle', 'spans', 'thanks'])
        tile = next(t for t in catalogue['tiles'] if t['code'] == 'D7')
        self.assertEqual((tile['i'], tile['j'], tile['zone'], tile['block']), (-4, 1, 'town', 'main'))
        self.assertNotIn('universe', tile)
        lat, lon = tile['at']
        self.assertLess(abs(lat - ground.CENTRE[0]), .1)
        self.assertLess(abs(lon - ground.CENTRE[1]), .1)
        self.assertEqual([v['id'] for v in tile['views']], ['street', 'over', 'top'])
        self.assertEqual(len(tile['views'][0]['eye']), 3)

    def test_every_tile_has_a_theme_the_page_can_explain(self):
        """The card of the tile under the car says what its theme is there to show."""
        catalogue = self.plan.catalogue()
        themes = catalogue['themes']
        self.assertEqual({t['zone'] for t in catalogue['tiles']} - set(themes), set())
        for zone, theme in themes.items():
            for field in ('title', 'titleEn', 'about', 'aboutEn'):
                self.assertTrue(theme[field].strip(), (zone, field))
            self.assertLess(len(theme['about']), 200, zone)      # a sentence on a card, not a page

    def test_pbf_round_trip(self):
        from osmium_compat import osmium
        with tempfile.TemporaryDirectory() as folder:
            path = self.plan.write_pbf(Path(folder) / 'polygon.osm.pbf')
            counts = defaultdict(int)
            names = set()
            for obj in osmium.FileProcessor(str(path)):
                counts[obj.type_str()] += 1
                if obj.is_way() and 'highway' in obj.tags and 'name' in obj.tags:
                    names.add(obj.tags['name'])
            box = osmium.io.Reader(str(path), osmium.osm.osm_entity_bits.NOTHING).header().box()
        self.assertEqual(counts['n'], len(self.plan.points))
        self.assertEqual(counts['w'], len(self.plan.ways))
        self.assertEqual(counts['r'], len(self.plan.relations))
        self.assertIn('F9 surface=cobblestone', names)
        self.assertAlmostEqual(box.bottom_left.lon, ground.box()[0], places=5)


class UniverseTests(unittest.TestCase):
    """Four universes round the main grid, each with the sample and land of its own."""

    @classmethod
    def setUpClass(cls):
        cls.plan = ground.make_plan()
        cls.catalogue = cls.plan.catalogue()

    def tiles(self, block):
        return [t for t in self.plan.tiles.values() if t['block'] == block]

    def test_every_tile_of_a_universe_names_it(self):
        for block in ('mountains', 'desert', 'snow', 'mud', 'jungle'):
            entries = [t for t in self.catalogue['tiles'] if t['block'] == block]
            self.assertTrue(entries)
            self.assertEqual({t.get('universe') for t in entries}, {block})
        self.assertEqual({t.get('universe') for t in self.catalogue['tiles'] if t['block'] == 'main'}, {None})
        # the names the game knows them by
        source = (Path(__file__).resolve().parents[1] / 'mod/lua/ge/extensions/e2r/universe.lua').read_text(encoding='utf8')
        for block in ground.BLOCKS:
            if block['universe']:
                self.assertIn(f"\n  {block['universe']} = {{label", source)

    def test_the_same_sample_in_each(self):
        self.assertEqual(len(universes.SAMPLE), 32)
        self.assertEqual(len(set(universes.SAMPLE)), 32)
        first = [zones.TILES[theme] for theme, _ in universes.SAMPLE]
        self.assertTrue(all(first))
        titles = {}
        for block in ('mountains', 'desert', 'snow', 'mud'):
            titles[block] = {t['title'] for t in self.tiles(block) if t['zone'] not in ('wild', 'junctions')}
        # the sides have room for the first 24, the north and the south for 30 and two junctions
        self.assertEqual(len(titles['snow']), 24)
        self.assertEqual(titles['snow'], titles['mud'])
        self.assertEqual(len(titles['mountains']), 30)
        self.assertEqual(titles['mountains'], titles['desert'])
        self.assertTrue(titles['snow'] <= titles['mountains'])
        for block in ('mountains', 'desert'):
            self.assertEqual(len([t for t in self.tiles(block) if t['zone'] == 'junctions']), 2)
        # and every theme of the main grid is in it
        zones_in = {t['zone'] for t in self.tiles('snow')}
        self.assertTrue({'town', 'works', 'classes', 'surfaces', 'water', 'covers', 'plants', 'street', 'relief', 'lanes'} <= zones_in)

    def test_the_jungle_is_the_places_plants_are_looked_at_in(self):
        self.assertEqual(len(set(universes.JUNGLE)), 10)
        tiles = self.tiles('jungle')
        self.assertEqual(len(tiles), 25)
        subjects = {t['zone'] for t in tiles if t['zone'] != 'wild'}
        self.assertEqual(subjects, {'works', 'plants', 'covers', 'water', 'town', 'street'})
        titles = {t['titleEn'] for t in self.catalogue['tiles'] if t['block'] == 'jungle'}
        # a village, a wood, fields, a park and a town block: the user's list of 21.11
        for title in ('Village homesteads', 'Panel, 9 floors', 'Trees and hedges', 'Jungle village', 'Plantation', 'Rainforest'):
            self.assertIn(title, titles)
        self.assertTrue(any(t.startswith('farmland') for t in titles) and any(t.startswith('park') for t in titles))
        # the corner is not another block's
        i0, i1, j0, j1 = ground.BLOCK['jungle']['tiles']
        for other in ('desert', 'mud'):
            a0, a1, b0, b1 = ground.BLOCK[other]['tiles']
            self.assertFalse(i0 < a1 and a0 < i1 and j0 < b1 and b0 < j1, other)

    def test_each_has_land_of_its_own(self):
        wild = {block: {t['title'] for t in self.tiles(block) if t['zone'] == 'wild'}
                for block in ('mountains', 'desert', 'snow', 'mud', 'jungle')}
        self.assertTrue({'Дощовий ліс', 'Село в джунглях', 'Плантація', 'Мангри', 'Брід у джунглях'} <= wild['jungle'])
        self.assertTrue({'Перевал', 'Гірське село', 'Гора Немо', 'Гірське озеро', 'Лижний курорт'} <= wild['mountains'])
        self.assertTrue({'Оаза', 'Столова гора', 'Шосе крізь дюни', 'Нафтопромисел'} <= wild['desert'])
        self.assertTrue({'Крижане озеро', 'Тайга', 'Полярна станція', 'Північне село'} <= wild['snow'])
        self.assertTrue({'Велике болото', 'Торфовище', 'Лісосіка', 'Село Грузьке', 'Брід'} <= wild['mud'])

    def test_relief(self):
        h = lambda x, y: float(self.plan.height(np.float64(x), np.float64(y)))
        # the range: Mount Nemo over a kilometre, the pass at about 400 m, the sample at its foot level
        self.assertGreater(h(-1300, 5250), 1000)
        self.assertTrue(330 < h(-350, 5180) < 520, h(-350, 5180))
        self.assertAlmostEqual(h(-2750, 3250), ground.BASE, places=1)
        self.assertGreater(h(0, 6000), 100)                 # high land behind the range
        self.assertLess(h(0, 6500), 0)                      # and the sea beyond the north shore
        # dunes of several metres, a mesa of seventy, a level oasis
        dunes = [h(x, -5000) for x in range(-3500, 0, 20)]
        self.assertGreater(max(dunes) - min(dunes), 8)
        self.assertGreater(h(2700, -5200), ground.BASE + 60)
        self.assertLess(abs(h(-1500, -4400) - h(-1460, -4380)), .3)
        # the frozen lake is level, the ski hill stands over the village
        self.assertLess(abs(h(-5800, -300) - h(-5600, -200)), .3)
        self.assertGreater(h(-5950, 2250), h(-5300, 2250) + 80)
        # the lowland lies under the rest of the island and over the sea
        self.assertTrue(2 < h(5600, -850) < ground.BASE - 3, h(5600, -850))

    def test_roads_of_the_universes_join_the_net(self):
        parent = {}

        def find(a):
            while parent.setdefault(a, a) != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a
        roads = [(ids, tag) for ids, tag in self.plan.ways if tag.get('highway') in DRIVABLE and tag.get('area') != 'yes']
        for ids, _ in roads:
            for n in ids[1:]:
                parent[find(n)] = find(ids[0])
        root = find(next(ids for ids, tag in roads if tag.get('name', '').startswith('Кільцева'))[0])
        for wanted in ('Перевальна дорога', 'Пустельне шосе', 'До оази', 'До станції', 'Північна вулиця', 'Грузька вулиця',
                       'Збірна дорога', 'Курортна'):
            ids = next(ids for ids, tag in roads if tag.get('name') == wanted)
            self.assertEqual(find(ids[0]), root, wanted)


class WeldTests(unittest.TestCase):
    def test_crossing_lines_get_a_common_node(self):
        plan = ground.Plan()
        a = plan.way([(0, 0), (100, 0)], {'highway': 'residential'})
        b = plan.way([(50, -50), (50, 50)], {'highway': 'service'})
        c = plan.way([(80, 0), (80, 40)], {'highway': 'footway'})       # ends on the first road
        over = plan.way([(20, -50), (20, 50)], {'highway': 'primary', 'bridge': 'yes', 'layer': '1'})
        rail = plan.way([(70, -50), (70, 50)], {'railway': 'rail'})
        plan.weld()
        shared = set(plan.ways[a][0]) & set(plan.ways[b][0])
        self.assertEqual(len(shared), 1)
        self.assertEqual(plan.points[shared.pop()][:2], [50., 0.])
        self.assertEqual(len(set(plan.ways[a][0]) & set(plan.ways[c][0])), 1)
        self.assertFalse(set(plan.ways[a][0]) & set(plan.ways[over][0]))    # the bridge passes over
        crossing = (set(plan.ways[a][0]) & set(plan.ways[rail][0])).pop()
        self.assertEqual(plan.points[crossing][2], {'railway': 'level_crossing'})
        # the road's nodes stay in order along it
        xs = [plan.points[n][0] for n in plan.ways[a][0]]
        self.assertEqual(xs, sorted(xs))

    def test_a_point_drawn_twice_is_one_node(self):
        plan = ground.Plan()
        a = plan.node(1.001, 2.004)
        self.assertEqual(plan.node(1.0, 2.0, {'highway': 'crossing'}), a)
        self.assertEqual(plan.points[a][2], {'highway': 'crossing'})
        self.assertNotEqual(plan.node(1.02, 2.0), a)


if __name__ == '__main__':
    unittest.main()
