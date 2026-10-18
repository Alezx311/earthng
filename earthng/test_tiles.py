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
