"""Selection imagery: georeferencing, bounded downloads, retries and ZIP payloads."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
import zipfile

from PIL import Image
import build_area_photos as photos


class AreaPhotoTests(unittest.TestCase):
    def test_small_places_anywhere_and_large_selections_have_bounded_coverage(self):
        for box in ([30.50, 50.44, 30.52, 50.46], [-80.23, 25.77, -80.21, 25.79],
                    [139.7, 35.6, 139.8, 35.7], [-180, -90, 180, 90]):
            tasks = photos.plan(box)
            self.assertGreater(len(tasks), 0)
            self.assertLessEqual(len(tasks), photos.MAX_SHEETS)
            for lon, lat in [(box[0], box[3]), (box[2] - 1e-9, box[1] + 1e-9)]:
                mx, my = photos.mercator(lon, lat)
                self.assertTrue(any(x / 2**z <= mx <= (x + 1) / 2**z
                                    and y / 2**z <= my <= (y + 1) / 2**z for z, x, y in tasks))
        with self.assertRaises(ValueError):
            photos.plan([0, 0, float('nan'), 1])

    def test_a_selection_is_a_pyramid_the_fine_level_under_the_coarse(self):
        # Ukraine: the finest level the budget allows, coarser ones two zooms apart down to the
        # zoom the planet's own picture ends at
        box = [22.1, 44.3, 40.3, 52.4]
        pyramid = photos.levels(box)
        self.assertEqual([z for z, _ in pyramid], [5, 7, 9])
        self.assertLessEqual(len(pyramid[-1][1]), photos.FINE)
        self.assertGreater(len(pyramid[-1][1]), 8 * len(pyramid[-2][1]), 'a sheet of one level covers 16 of the next')
        self.assertLessEqual(len(photos.plan(box)), photos.MAX_SHEETS)
        # every zoom from FLOOR on has exactly one level, the finest to the end
        shown = photos.zooms(box)
        self.assertEqual(shown, {5: (6, 6), 7: (7, 8), 9: (9, 18)})
        # a town: three levels as well, the finest at the source's own 10 m
        town = [30.3, 50.3, 30.75, 50.6]
        self.assertEqual(photos.levels(town)[-1][0], 13)
        zooms = photos.zooms(town)
        covered = sorted(z for low, high in zooms.values() for z in range(low, high + 1))
        self.assertEqual(covered, list(range(photos.FLOOR, 19)))
        # a place of one sheet is one level from FLOOR to the end
        self.assertEqual(photos.zooms([30.501, 50.451, 30.502, 50.452]), {13: (6, 18)})

    def test_sheets_outside_the_packs_coverage_are_not_fetched(self):
        box = [22, 44, 40, 52]
        corners = [[22, 44, 23, 45], [39, 51, 40, 52]]
        parts = photos.plan(box, corners)
        self.assertLessEqual(len(parts), photos.MAX_SHEETS)
        # the budget goes to what the pack covers: two corners of a country are drawn finer
        self.assertGreater(photos.levels(box, corners)[-1][0], photos.levels(box)[-1][0])
        for z, x, y in parts:
            scale = 2 ** z
            self.assertTrue(any(x / scale <= photos.mercator(c[2], c[1])[0] and (x + 1) / scale >= photos.mercator(c[0], c[3])[0]
                                for c in corners))

    def test_an_installed_pack_gets_its_imagery_as_a_zip_beside_it(self):
        image = Image.new('RGBA', (photos.SIZE, photos.SIZE), (10, 60, 20, 255))
        with tempfile.TemporaryDirectory() as tmp, patch.object(photos, 'fetch', return_value=image):
            root = Path(tmp)
            with zipfile.ZipFile(root / 'earthng_demo.zip', 'w') as archive:
                archive.writestr('earthng/countries/demo/manifest.json',
                                 json.dumps({'id': 'demo', 'coverage': [[30.50, 50.44, 30.51, 50.45], [30.51, 50.44, 30.52, 50.45]]}))
                archive.writestr('earthng/countries/demo/regions/a/manifest.json', json.dumps({'bounds': [0, 0, 1, 1]}))
            self.assertEqual(photos.pack_targets(root / 'earthng_demo.zip'),
                             [('earthng/countries/demo', [30.50, 50.44, 30.52, 50.45],
                               [[30.50, 50.44, 30.51, 50.45], [30.51, 50.44, 30.52, 50.45]])])
            path = photos.addon(root / 'earthng_demo.zip', root / 'out', root / 'cache', emit=lambda _: None)
            self.assertEqual(path.name, 'earthng_demo_photos.zip')
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                self.assertIn('earthng/countries/demo/photos/index.json', names)
                sheets = json.loads(archive.read('earthng/countries/demo/photos/index.json'))
                self.assertEqual(len(names), len(sheets) + 1)
                self.assertTrue(all(s['minZoom'] >= photos.FLOOR and s['maxZoom'] <= 18 for s in sheets))
            # a section pack: its own folder
            with zipfile.ZipFile(root / 'earthng_area.zip', 'w') as archive:
                archive.writestr('earthng/countries/demo/sections/s1/manifest.json', json.dumps({'coverage': [[1, 1, 1.01, 1.01]]}))
            self.assertEqual(photos.pack_targets(root / 'earthng_area.zip')[0][0], 'earthng/countries/demo/sections/s1')

    def test_only_the_finest_level_is_fetched_the_rest_is_put_together(self):
        image = Image.new('RGBA', (photos.SIZE, photos.SIZE), (10, 60, 20, 255))
        box = [30.3, 50.3, 30.75, 50.6]
        pyramid = photos.levels(box)
        self.assertGreater(len(pyramid), 1)
        with tempfile.TemporaryDirectory() as tmp, patch.object(photos, 'fetch', return_value=image) as fetch:
            index = photos.build(box, tmp, emit=lambda _: None)
            self.assertEqual(fetch.call_count, len(pyramid[-1][1]))
            self.assertEqual({call.args[0] for call in fetch.call_args_list}, {pyramid[-1][0]})
            sheets = json.loads(index.read_text())
            self.assertEqual(len(sheets), sum(len(tiles) for _, tiles in pyramid))
            coarse = [s for s in sheets if s['file'].startswith('c')]
            self.assertEqual(len(coarse), sum(len(tiles) for _, tiles in pyramid[:-1]))
            with Image.open(index.parent / coarse[0]['file']) as made:
                self.assertEqual(made.size, (photos.SIZE, photos.SIZE))
                # the sheets are lifted for a map: the dark green of the source is lighter
                self.assertGreater(made.convert('RGB').getpixel((300, 300))[1], 80)

    def test_a_busy_service_is_waited_out_as_long_as_it_asks(self):
        from email.message import Message
        from urllib.error import HTTPError
        png = __import__('io').BytesIO()
        Image.new('RGBA', (photos.SIZE, photos.SIZE), (10, 60, 20, 255)).save(png, 'PNG')
        headers = Message()
        headers['Retry-After'] = '40'
        answers = [HTTPError('u', 429, 'Too Many Requests', headers, None), HTTPError('u', 503, 'busy', Message(), None)]

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self, _):
                return png.getvalue()

        def urlopen(request, timeout):
            if answers:
                raise answers.pop(0)
            return Response()
        slept = []
        with patch.object(photos, 'urlopen', urlopen):
            image = photos.fetch(9, 299, 172, sleep=slept.append)
        self.assertEqual(image.size, (photos.SIZE, photos.SIZE))
        self.assertEqual(slept, [40, 30, photos.PAUSE], 'its Retry-After, then our own longer wait, then the pause')
        # a service that stays busy is given up after RETRIES waits
        answers.extend(HTTPError('u', 429, 'Too Many Requests', Message(), None) for _ in range(photos.RETRIES + 1))
        with patch.object(photos, 'urlopen', urlopen), self.assertRaises(HTTPError):
            photos.fetch(9, 299, 172, sleep=slept.append)
        self.assertEqual(len(slept), 3 + photos.RETRIES)

    def test_wms_uses_mercator_and_correct_axis_order(self):
        p = parse_qs(urlparse(photos.request_url(1, 0, 0)).query)
        self.assertEqual(p['version'], ['1.3.0'])
        self.assertEqual(p['crs'], ['EPSG:3857'])
        bounds = list(map(float, p['bbox'][0].split(',')))
        self.assertEqual(bounds, [-photos.ORIGIN, 0, 0, photos.ORIGIN])
        self.assertEqual(p['layers'], [photos.LAYER])

    def test_cache_retry_and_pack_contains_only_the_selection(self):
        image = Image.new('RGBA', (photos.SIZE, photos.SIZE), (10, 60, 20, 255))
        box = [30.501, 50.451, 30.502, 50.452]
        with tempfile.TemporaryDirectory() as tmp, patch.object(photos, 'fetch', return_value=image) as fetch:
            root = Path(tmp)
            index = photos.build(box, root, emit=lambda _: None)
            count = fetch.call_count
            self.assertGreater(count, 0)
            self.assertEqual(photos.build(box, root, emit=lambda _: None), index)
            self.assertEqual(fetch.call_count, count)
            sheets = json.loads(index.read_text())
            with zipfile.ZipFile(root / 'pack.zip', 'w') as archive:
                photos.write_archive(archive, index, 'earthng/countries/test/sections/area/photos')
            with zipfile.ZipFile(root / 'pack.zip') as archive:
                self.assertEqual(len(archive.namelist()), len(sheets) + 1)
                self.assertTrue(all('/sections/area/photos/' in n for n in archive.namelist()))
            (index.parent / sheets[0]['file']).unlink()
            fetch.side_effect = OSError('offline')
            partial = photos.build(box, root, emit=lambda _: None)
            self.assertLess(len(json.loads(partial.read_text())), len(sheets))
            fetch.side_effect = None
            self.assertEqual(len(json.loads(photos.build(box, root, emit=lambda _: None).read_text())), len(sheets))
            stop = threading.Event()
            stop.set()
            with self.assertRaises(InterruptedError):
                photos.build(box, root, cancel=stop)

    def test_service_failure_is_bounded_and_not_cached_as_success(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(photos, 'fetch', side_effect=OSError('offline')) as fetch:
            index = photos.build([29, 49, 31, 51], tmp, emit=lambda _: None)
            self.assertEqual(fetch.call_count, 3)
            self.assertEqual(json.loads(index.read_text()), [])
