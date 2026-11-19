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
