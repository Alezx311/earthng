"""Tile lookup and the block writer visit set bits only."""
import time
import unittest

import osm_tiles


def _index(xs, ys):
    tiles = {}
    for x in xs:
        for y in ys:
            tiles[f'{x}_{y}'] = {'coverage': osm_tiles.coverage((x, y))}
    return {'cell': osm_tiles.CELL, 'buffer': osm_tiles.BUFFER, 'tiles': tiles}


def _brute(index, bbox):
    w, s, e, n = bbox
    found = None
    for key in sorted(index['tiles']):
        cw, cs, ce, cn = index['tiles'][key]['coverage']
        if cw <= w and cs <= s and e <= ce and n <= cn:
            found = (key, index['tiles'][key])
            break
    return found


class TileLookupTests(unittest.TestCase):
    def test_lookup_matches_a_sorted_scan_including_the_overlap(self):
        index = _index(range(-3, 420), range(0, 6))
        overlap = [10.045, 0.012, 10.055, 0.028]  # inside both tile 200 and 201
        boxes = (overlap, [-0.04, 0.0, -0.02, 0.02], [20.9, 0.24, 20.91, 0.25], [0.0, 0.0, 0.001, 0.001])
        for bbox in boxes:
            self.assertEqual(osm_tiles.tile_for(index, bbox), _brute(index, bbox))
        self.assertEqual(osm_tiles.tile_for(index, overlap)[0], '200_0')
        self.assertIsNone(osm_tiles.tile_for(index, [80, 80, 80.01, 80.01]))

    def test_lookup_of_a_country_sized_index_stays_a_few_cells(self):
        index = _index(range(400, 800), range(60, 260))  # 400 x 200 = 80 000 tiles
        bbox = [31.57, 4.86, 31.58, 4.87]
        started = time.perf_counter()
        for _ in range(50):
            hit = osm_tiles.tile_for(index, bbox)
        self.assertLess(time.perf_counter() - started, 0.05)
        self.assertEqual(hit[0], _brute(index, bbox)[0])


class MaskTests(unittest.TestCase):
    def test_only_set_bits_are_visited_and_high_bits_stay_intact(self):
        order = [(i, i) for i in range(100)]
        mask = (1 << 0) | (1 << 2) | (1 << 80)
        self.assertEqual(list(osm_tiles._mask_keys(mask, order)), [(0, 0), (2, 2), (80, 80)])
        self.assertEqual(list(osm_tiles._mask_keys(0, order)), [])


class SourceBoxTests(unittest.TestCase):
    def kept(self, selection, extract=None):
        return set(osm_tiles.region_keys(osm_tiles.region(selection, extract)))

    def test_every_cell_under_a_selection_is_cut(self):
        # Map Builder selection south-east of Tallinn: the raw box kept 3 cells and lost
        # Assaku (59.3726 N) and Kurna (24.8405 E), both inside the selection.
        selection = [24.793289, 59.274507, 25.016449, 59.374695]
        kept = self.kept(selection)
        self.assertEqual(kept, {(x, y) for x in range(495, 501) for y in range(1185, 1188)})
        for lon, lat in [(24.8418, 59.3726), (24.8405, 59.3411), (24.9752, 59.2882)]:
            self.assertIn((int(lon // osm_tiles.CELL), int(lat // osm_tiles.CELL)), kept)
        # the package box (what the tiles cover) is the one these cuts always had
        self.assertEqual(osm_tiles.source_box(selection), [24.74, 59.24, 25.06, 59.41])

    def test_a_cell_the_extract_edge_cuts_through_is_kept(self):
        # cells whose buffered box crossed the extract's edge were dropped with their data:
        # Narva (28.2 E) at the edge of Estonia's extract, 43 % of the Tokyo spot extract
        self.assertIn(496, {x for x, _ in self.kept([24.793, 59.274, 25.016, 59.374], extract=[24.82, 59.0, 26.0, 60.0])})
        # an edge on the cell line takes nothing beyond it
        self.assertNotIn(495, {x for x, _ in self.kept([24.793, 59.274, 25.016, 59.374], extract=[24.8, 59.0, 26.0, 60.0])})
        estonia = [20.85166, 57.49764, 28.21426, 59.99705]
        keys = set(osm_tiles.region_keys(estonia))
        self.assertIn((564, 1187), keys)                    # Narva
        self.assertIn((417, 1149), keys)                    # the south-west corner cell

    def test_no_selection_loses_a_cell_anywhere_on_the_grid(self):
        import random
        rng = random.Random(8)
        for _ in range(4000):
            w = rng.uniform(-179.5, 179.0)
            s = rng.uniform(-85.0, 84.0)
            selection = [w, s, w + rng.choice([1e-6, rng.uniform(0, .4)]), s + rng.choice([1e-6, rng.uniform(0, .4)])]
            if rng.random() < .3:                           # selections on the cell lines
                selection = [round(v / osm_tiles.CELL) * osm_tiles.CELL for v in selection]
                selection[2] += osm_tiles.CELL
                selection[3] += osm_tiles.CELL
            extract = None
            if rng.random() < .5:                           # an extract edge through the selection
                extract = [selection[0] + rng.uniform(-.1, .05), selection[1] + rng.uniform(-.1, .05), 180, 85]
            kept = self.kept(selection, extract)
            w, s, e, n = selection
            if extract:
                w, s = max(w, extract[0]), max(s, extract[1])
            for x in range(int(w // osm_tiles.CELL) - 1, int(e // osm_tiles.CELL) + 2):
                for y in range(int(s // osm_tiles.CELL) - 1, int(n // osm_tiles.CELL) + 2):
                    cw, cs, ce, cn = osm_tiles.cell_box((x, y))
                    if min(e, ce) - max(w, cw) > 1e-9 and min(n, cn) - max(s, cs) > 1e-9:
                        self.assertIn((x, y), kept, (selection, extract))


class SelectTests(unittest.TestCase):
    def test_one_read_for_several_boxes_picks_what_one_read_per_box_picks(self):
        import tempfile
        from pathlib import Path
        import osmium
        import osm_extract_pbf
        with tempfile.TemporaryDirectory() as tmp:
            pbf = str(Path(tmp) / 'grid.osm.pbf')
            with osmium.SimpleWriter(pbf) as w:
                nid = 0
                for y in range(10):
                    for x in range(10):
                        nid += 1
                        tags = {'highway': 'street_lamp'} if (x + y) % 7 == 0 else {}
                        w.add_node(osmium.osm.mutable.Node(id=nid, location=(x * .1, y * .1), tags=tags))
                for y in range(10):        # a street along each row and a short one in each column pair
                    w.add_way(osmium.osm.mutable.Way(id=y + 1, nodes=[y * 10 + x + 1 for x in range(10)],
                                                     tags={'highway': 'residential'}))
                for x in range(0, 10, 2):
                    w.add_way(osmium.osm.mutable.Way(id=100 + x, nodes=[x + 1, x + 11, x + 21], tags={'barrier': 'fence'}))
                w.add_relation(osmium.osm.mutable.Relation(id=1, members=[('w', 104, 'outer'), ('w', 3, 'outer')],
                                                           tags={'type': 'multipolygon', 'landuse': 'forest'}))
            boxes = [[0, 0, .45, .45], [.4, 0, .95, .45], [0, .4, .45, .95], [.4, .4, .95, .95], [.05, .05, .15, .15]]
            together = osm_extract_pbf.select(pbf, boxes)
            for box, pick in zip(boxes, together):
                alone = osm_extract_pbf.select(pbf, [box])[0]
                self.assertEqual(pick, alone)
            self.assertIn(1, together[0]['relations'])         # the forest reaches into the first box
            self.assertTrue(all(pick['ways'] for pick in together))
