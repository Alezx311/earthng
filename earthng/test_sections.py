"""Country sections: names, lookup and the region size limit."""
import unittest

import sections

HARJU = {'id': 'harju-maakond', 'name': 'Harju County', 'level': 6, 'box': [23.52, 58.99, 26.02, 59.83],
         'geometry': {'type': 'Polygon', 'coordinates': [[[24, 59], [25, 59], [25, 59.5], [24, 59]]]}}
TALLINN = dict(HARJU, id='tallinn', name='Tallinn', level=7, box=[24.55, 59.35, 24.93, 59.59])
TARTU = dict(HARJU, id='tartu-maakond', name='Tartu County', box=[26.05, 58.03, 27.55, 58.79])
TARTU_CITY = dict(HARJU, id='tartu-linn', name='Tartu linn', level=7, box=[26.46, 58.33, 26.8, 58.46])


class SectionTests(unittest.TestCase):
    def test_slug_drops_accents(self):
        self.assertEqual(sections.slug('Lääne-Viru maakond'), 'laane-viru-maakond')
        self.assertEqual(sections.slug('Võru'), 'voru')

    def test_find_by_id_or_unique_prefix(self):
        found = [HARJU, TALLINN, TARTU, TARTU_CITY]
        self.assertIs(sections.find(found, 'Harju'), HARJU)
        self.assertIs(sections.find(found, 'tallinn'), TALLINN)
        self.assertIs(sections.find(found, 'tartu-linn'), TARTU_CITY)
        with self.assertRaisesRegex(ValueError, 'tartu-linn, tartu-maakond'):
            sections.find(found, 'tartu')

    def test_box_grows_by_margin_and_refuses_oversized_areas(self):
        self.assertEqual(sections.box(TALLINN), [24.53, 59.33, 24.95, 59.61])
        self.assertEqual(len(sections.box(HARJU)), 4)       # ~145 km wide: fits one region
        with self.assertRaisesRegex(ValueError, 'smaller parts'):
            sections.box(dict(HARJU, box=[21.0, 57.5, 28.2, 59.9]))

    def test_shape_is_the_grown_outline(self):
        outline = sections.shape(HARJU)
        self.assertTrue(outline.contains(__import__('shapely').Point(24.5, 59.2)))
        self.assertTrue(outline.contains(__import__('shapely').Point(24.5, 58.99)))   # in the margin
        self.assertFalse(outline.contains(__import__('shapely').Point(25.5, 59.2)))


if __name__ == '__main__':
    unittest.main()
