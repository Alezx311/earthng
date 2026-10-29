"""A linked storefront's sign under its real name and its awning (BLD.shopFront)."""
import unittest

import test_shopfront_experiment


class ShopSignTests(unittest.TestCase):
    def setUp(self):
        self.t = test_shopfront_experiment.ShopfrontExperimentTests()
        self.t.setUp()

    def scene(self, name='Хліб', road=None, **opts):
        poi = dict(self.t.poi, tags={'shop': 'bakery', **({'name': name} if name else {})})
        opts.setdefault('experimentalDetail', True)
        return self.t.build(buildings=[self.t.block], points=[poi], roads=road and [road],
                            experimentalShopfront=True, **opts)[1]

    def tris(self, scene, material):
        return list(self.t.h.triangles(scene, 'e2rf_' + material))

    def awning(self, scene):
        return [t for m in ('paint_red', 'plate', 'pipe') for t in self.tris(scene, m)
                if all(p[1] <= 100 + 1e-6 and 126 <= p[0] <= 134 for p in t) and min(p[2] for p in t) > 2]

    def test_the_real_name_over_the_shop_band(self):
        scene = self.scene()
        board, letters = self.tris(scene, 'fascia'), self.tris(scene, 'glyphs')
        self.assertTrue(board)
        self.assertEqual(len(letters), 4 * 2)                  # four letters, a quad each
        zs = [p[2] for t in board for p in t]
        band = max(p[2] for t in self.t.shop_tris(scene) for p in t)
        self.assertGreaterEqual(min(zs), band)                 # above the shop band
        xs = [p[0] for t in board + letters for p in t]
        self.assertTrue(126 <= min(xs) and max(xs) <= 134)     # within the shop's span
        # in front of the wall (y = 100, the street side is -y), letters before the board
        self.assertTrue(all(p[1] < 100 for t in board + letters for p in t))
        self.assertLess(max(p[1] for t in letters for p in t), min(p[1] for t in board for p in t) + 1e-6)

    def test_no_name_no_board_and_nothing_without_the_switch(self):
        self.assertFalse(self.tris(self.scene(name=None), 'fascia'))
        self.assertTrue(self.awning(self.scene(name=None)))
        self.assertFalse(self.tris(self.scene(name='★★★★'), 'fascia'))   # letters the atlas lacks
        off = self.scene(experimentalDetail=False)
        self.assertFalse(self.tris(off, 'fascia') or self.awning(off))

    def test_a_long_name_shrinks_and_a_too_long_one_is_left(self):
        long = self.tris(self.scene(name='Продукти Біля Дому'), 'glyphs')
        self.assertEqual(len(long), 2 * 16)
        heights = [max(p[2] for p in t) - min(p[2] for p in t) for t in long]
        self.assertLess(max(heights), .34)
        self.assertFalse(self.tris(self.scene(name='Дуже довга назва магазину без кінця і краю'), 'fascia'))

    def test_the_awning_keeps_off_a_carriageway_at_the_wall(self):
        sheet = self.awning(self.scene())
        self.assertTrue(sheet)
        ys = [p[1] for t in sheet for p in t]
        self.assertAlmostEqual(min(ys), 100 - 1.1, places=3)
        # 2.4 m clear over the building's base (the shop band's top is 4.2 m over it)
        base = max(p[2] for t in self.t.shop_tris(self.scene()) for p in t) - 4.2
        self.assertGreater(min(p[2] for t in sheet for p in t) - base, 2.4)
        close = {'id': 'street', 'width': 8, 'tags': {'highway': 'residential'}, 'points': [[50, 95, 0], [200, 95, 0]]}
        self.assertFalse(self.awning(self.scene(road=close)))


if __name__ == '__main__':
    unittest.main()
