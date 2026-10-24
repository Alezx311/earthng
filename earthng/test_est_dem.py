import json
import math
from pathlib import Path
import tempfile
import unittest

import numpy as np

import est_dem

try:
    import rasterio
    from rasterio.transform import from_origin
    from pyproj import Transformer
    from PIL import Image
except ImportError:            # the nature requirements are optional
    rasterio = None


def plane(e, n):
    return 10 + .002 * (e - 540000) - .001 * (n - 6570000)


class CreditTests(unittest.TestCase):
    def test_a_pack_over_burnt_tiles_credits_the_land_board(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder)
            tiles = [cache / 'terrain' / '12' / '2329' / '1185.png', cache / 'terrain' / '12' / '2330' / '1185.png']
            self.assertIsNone(est_dem.credit(tiles, cache))           # nothing burnt
            (cache / 'est' / est_dem.KIND).mkdir(parents=True)
            (cache / 'est' / est_dem.KIND / '6374.tif').write_bytes(b'')
            # a burn outlives the build that made it: the record says which tiles carry the DTM
            (cache / 'est' / 'burnt.json').write_text(json.dumps({'2330/1185': 'stamp'}))
            credit = est_dem.credit(tiles, cache)
            self.assertIn('Maa- ja Ruumiamet', credit['source'])
            self.assertEqual(credit['url'], 'https://geoportaal.maaruum.ee/opendata-licence')
            self.assertRegex(credit['data'], r'extracted 2\d{3}$')
            self.assertIsNone(est_dem.credit(tiles[:1], cache))       # a pack off the burnt tiles


@unittest.skipIf(rasterio is None, 'rasterio not installed')
class EstDemTests(unittest.TestCase):
    def test_sheet_numbers(self):
        self.assertEqual(est_dem.sheet_code(545000, 6575000), '6374')
        self.assertEqual(est_dem.sheet_code(655000, 6575000), '6475')
        box = est_dem.sheets((545100, 6570960, 557950, 6582290))
        self.assertEqual(sorted(box), ['6374', '6375', '6384', '6385'])
        self.assertEqual(box['6374'], (540000, 6570000, 550000, 6580000))

    def test_terrarium_round_trip(self):
        h = np.array([-12.3, 0, 41.7, 318.004])
        self.assertLess(np.abs(est_dem.decode(est_dem.encode(h)) - h).max(), 1 / 256)

    def test_feather_falls_to_zero_at_a_missing_sheet(self):
        covered = [(540000, 6570000, 550000, 6580000)]
        e = np.array([545000., 549900., 549500., 550100.])
        n = np.full(4, 6575000.)
        w = est_dem.feather(e, n, covered)
        self.assertEqual(list(np.round(w, 3)), [1, .2, 1, 0])

    def tile_cache(self, root, lat, lon, height=50.):
        x = math.floor((lon + 180) / 360 * 4096)
        y = math.floor((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * 4096)
        path = Path(root) / 'terrain' / '12' / str(x) / f'{y}.png'
        path.parent.mkdir(parents=True)
        Image.fromarray(est_dem.encode(np.full((256, 256), height)), 'RGB').save(path)
        return path

    @staticmethod
    def fake_fetch(have):
        def fetch(code, cache, kind):
            if code not in have:
                return None
            folder = Path(cache) / 'est' / kind
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f'{code}.tif'
            if not path.exists():
                # the sheet's south-west corner, from its number
                w = 1e5 * (int(code[1]) + 2) + 1e4 * int(code[3])
                s = 6e6 + 1e5 * (int(code[0]) - 1) + 1e4 * int(code[2])
                e, n = np.meshgrid(w + 10 + 20 * np.arange(500), s + est_dem.SHEET - 10 - 20 * np.arange(500))
                with rasterio.open(path, 'w', driver='GTiff', width=500, height=500, count=1, dtype='float32',
                                   crs='EPSG:3301', transform=from_origin(w, s + est_dem.SHEET, 20, 20),
                                   nodata=-9999) as out:
                    out.write(plane(e, n).astype('float32'), 1)
            return path
        return fetch

    def test_burn_follows_the_sheets_and_restores(self):
        with tempfile.TemporaryDirectory() as root:
            path = self.tile_cache(root, 59.33, 24.9)
            original = path.read_bytes()
            every = set(est_dem.sheets((500000, 6530000, 600000, 6630000)))
            changed = est_dem.refine([path], root, emit=lambda _m: None, fetch=self.fake_fetch(every))
            self.assertEqual(changed, 1)
            with Image.open(path) as image:
                h = est_dem.decode(np.asarray(image.convert('RGB')))
            x, y = int(path.parent.name), int(path.stem)
            left, _bottom, _right, top = est_dem.tile_bounds(x, y)
            step = est_dem.TILE / 256
            mx, my = np.meshgrid(left + (np.arange(256) + .5) * step, top - (np.arange(256) + .5) * step)
            e, n = Transformer.from_crs(3857, 3301, always_xy=True).transform(mx, my)
            self.assertLess(np.abs(h - plane(e, n))[4:-4, 4:-4].max(), .1)
            # the same sheets again: nothing to do
            self.assertEqual(est_dem.refine([path], root, emit=lambda _m: None, fetch=self.fake_fetch(every)), 0)
            self.assertEqual(est_dem.restore(root), 1)
            self.assertEqual(path.read_bytes(), original)

    def test_fine_tiles_follow_the_sheets_at_ten_metres(self):
        import fast_sources
        with tempfile.TemporaryDirectory() as root:
            centre = self.tile_cache(root, 59.33, 24.9)
            x, y = int(centre.parent.name), int(centre.stem)
            tiles = [centre]
            for dx in (-1, 0, 1):          # the upsampled base reads the neighbours
                for dy in (-1, 0, 1):
                    if dx or dy:
                        path = Path(root) / 'terrain' / '12' / str(x + dx) / f'{y + dy}.png'
                        path.parent.mkdir(parents=True, exist_ok=True)
                        Image.fromarray(est_dem.encode(np.full((256, 256), 50.)), 'RGB').save(path)
                        tiles.append(path)
            every = set(est_dem.sheets((500000, 6530000, 600000, 6630000)))
            est_dem.refine(tiles, root, emit=lambda _m: None, fetch=self.fake_fetch(every))
            children = sorted(Path(root, 'terrain', '13').glob('*/*.png'))
            self.assertIn(Path(root, 'terrain', '13', str(2 * x), f'{2 * y}.png'), children)
            # a z13 pixel X samples the ground at X: ~9.6 m pixels match the plane
            a, b = 2 * x + 1, 2 * y + 1
            with Image.open(Path(root, 'terrain', '13', str(a), f'{b}.png')) as image:
                h = est_dem.decode(np.asarray(image.convert('RGB')))
            size = est_dem.TILE / 2
            mx, my = np.meshgrid(-est_dem.R + a * size + np.arange(256) * size / 256,
                                 est_dem.R - b * size - np.arange(256) * size / 256)
            e, n = Transformer.from_crs(3857, 3301, always_xy=True).transform(mx, my)
            self.assertLess(np.abs(h - plane(e, n))[4:-4, 4:-4].max(), .1)
            # zoom 13 reads the fine tile; where none was burnt, the z12 tile upsampled
            terrain = fast_sources.Terrain(root, zoom=13)
            self.assertTrue(np.allclose(terrain.image(a, b), h, atol=1 / 128))
            self.assertFalse(Path(root, 'terrain', '13', str(2 * x + 2), f'{2 * y}.png').exists())   # its right half needs x + 2
            coarse = fast_sources.Terrain(root).image(x + 1, y)
            self.assertTrue(np.allclose(terrain.image(2 * x + 2, 2 * y)[::2, ::2], coarse[:128, :128], atol=1e-6))
            self.assertEqual(fast_sources.dem_zoom(root, [24.89, 59.32, 24.91, 59.34]), 13)
            self.assertEqual(est_dem.restore(root), 9)
            self.assertFalse(Path(root, 'terrain', '13').exists())

    def test_no_sheet_leaves_terrarium(self):
        with tempfile.TemporaryDirectory() as root:
            path = self.tile_cache(root, 59.33, 24.9)
            original = path.read_bytes()
            self.assertEqual(est_dem.refine([path], root, emit=lambda _m: None, fetch=self.fake_fetch(set())), 0)
            self.assertEqual(path.read_bytes(), original)

    def test_edge_of_the_survey_blends_into_terrarium(self):
        with tempfile.TemporaryDirectory() as root:
            # one sheet only: the tile crosses its edge, outside stays at the Terrarium 50 m
            path = self.tile_cache(root, 59.33, 24.9)
            est = Transformer.from_crs(4326, 3301, always_xy=True).transform(24.9, 59.33)
            code = est_dem.sheet_code(*est)
            est_dem.refine([path], root, emit=lambda _m: None, fetch=self.fake_fetch({code}))
            with Image.open(path) as image:
                h = est_dem.decode(np.asarray(image.convert('RGB')))
            self.assertTrue((np.abs(h - 50) < 1 / 256).any())
            self.assertTrue((np.abs(h - 50) > 1).any())
            # no step anywhere: neighbouring pixels (19.5 m) differ by the plane's slope or the ramp
            self.assertLess(max(np.abs(np.diff(h, axis=0)).max(), np.abs(np.diff(h, axis=1)).max()), 3)


if __name__ == '__main__':
    unittest.main()
