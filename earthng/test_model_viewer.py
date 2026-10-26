"""The model viewer's pieces that need no pack and no Lua: layers, colours, LiDAR sampling, the page."""
import base64
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

import model_viewer as mv


class LayerTests(unittest.TestCase):
    def test_materials_fall_into_their_layer(self):
        for material, layer in (('e2rf_road_major', 'road'), ('e2rf_mark_white', 'marks'), ('e2rf_curb', 'sidewalk'),
                                ('e2rf_clad_metal', 'rails'), ('e2rf_fence_mesh', 'fences'), ('e2rf_wall_brick', 'buildings'),
                                ('e2rf_roof_tile', 'buildings'), ('e2rf_car', 'cars'), ('e2rf_forest', 'ground')):
            self.assertEqual(mv.group_of(material), layer, material)

    def test_a_road_is_dark_and_an_unknown_material_is_magenta(self):
        self.assertLess(mv.colour('e2rf_road_major').sum(), mv.colour('e2rf_sidewalk').sum())
        self.assertEqual(tuple(mv.colour('e2rf_nothing_known')), (255, 0, 255))


class RasterTests(unittest.TestCase):
    def setUp(self):
        try:
            import rasterio
            from rasterio.transform import from_origin
        except ImportError:
            self.skipTest('rasterio is not installed')
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        # a 10 x 10 m raster of 1 m pixels at (500000, 6500000), height = 2 * east metres, one nodata pixel
        z = np.tile(np.arange(10, dtype='float32') * 2, (10, 1))
        z[0, 0] = -9999
        self.path = Path(self.dir.name) / 'a.tif'
        with rasterio.open(self.path, 'w', driver='GTiff', height=10, width=10, count=1, dtype='float32', crs='EPSG:3301',
                           transform=from_origin(500000, 6500010, 1, 1), nodata=-9999) as dst:
            dst.write(z, 1)

    def test_heights_are_interpolated_between_pixel_centres(self):
        z = mv.sample_raster(self.path, [500005., 500005.5], [6500005., 6500005.])
        self.assertAlmostEqual(z[0], 2 * 4.5 + 0., delta=.01)      # pixel centres are at x + .5: 4.5 m east of the origin
        self.assertAlmostEqual(z[1] - z[0], 1., delta=.01)          # 2 m of height a metre

    def test_outside_and_nodata_are_nan(self):
        z = mv.sample_raster(self.path, [499990., 500000.5, 500005.], [6500005., 6500009.5, 6500005.])
        self.assertTrue(np.isnan(z[0]) and np.isnan(z[1]) and np.isfinite(z[2]))

    def test_the_finest_sheet_that_covers_the_place_is_chosen(self):
        import rasterio
        from rasterio.transform import from_origin
        fine = Path(self.dir.name) / 'fine.tif'
        with rasterio.open(fine, 'w', driver='GTiff', height=20, width=20, count=1, dtype='float32', crs='EPSG:3301',
                           transform=from_origin(500000, 6500010, .5, .5)) as dst:
            dst.write(np.zeros((20, 20), dtype='float32'), 1)
        self.assertEqual(mv.find_sheet(Path(self.dir.name), 500005., 6500005.).name, 'fine.tif')
        self.assertIsNone(mv.find_sheet(Path(self.dir.name), 400000., 6500005.))
        self.assertIsNone(mv.find_sheet(None, 500005., 6500005.))


class PageTests(unittest.TestCase):
    def test_the_data_is_embedded_as_json_and_the_arrays_decode(self):
        pos = np.arange(9, dtype=np.float32).reshape(1, 3, 3)
        data = {'lat': 59.3, 'lon': 24.8, 'radius': 100, 'tris': 1, 'far': True, 'lidar': None, 'dtm': None,
                'groups': [{'name': 'road', 'tris': 1, 'colour': '#585858', 'cols': mv.b64(np.zeros((1, 3)), np.uint8),
                            'pos': mv.b64(pos), 'dev': None}]}
        html = mv.page(data)
        self.assertIn('(far tiles)', html)
        self.assertIn('no LiDAR terrain', html)
        self.assertNotIn('__DATA__', html)
        embedded = html.split('const DATA = ', 1)[1].split(';\n', 1)[0]
        back = json.loads(embedded)
        self.assertEqual(np.frombuffer(base64.b64decode(back['groups'][0]['pos']), dtype=np.float32).tolist(), list(range(9)))


if __name__ == '__main__':
    unittest.main()
