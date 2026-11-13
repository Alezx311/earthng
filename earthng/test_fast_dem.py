import tempfile
import unittest
from pathlib import Path

import numpy as np

import fast_dem


def sea_tile():
    return np.zeros((256, 256))


class SeamTest(unittest.TestCase):
    def test_the_30e_stripe_of_the_black_sea_is_mended(self):
        # Terrarium z12 tile 2389/1470: columns 82-85 at -4970, -13143, -11452, -3279 m in a sea of 0
        h = sea_tile()
        h[:, 82:86] = [-4970., -13143., -11452., -3279.]
        out, count = fast_dem.mend_seams(h)
        self.assertEqual(count, 4 * 256)
        self.assertEqual(float(np.abs(out).max()), 0.)
        self.assertEqual(float(h[0, 83]), -13143.)        # the input is left as it was

    def test_a_stripe_on_the_tile_edge_is_mended_from_across_the_pixel(self):
        h = sea_tile() + 5.
        h[:, 0:4] = -13143.
        out, count = fast_dem.mend_seams(h)
        self.assertEqual(count, 4 * 256)
        self.assertTrue(np.allclose(out, 5.))

    def test_real_steep_ground_is_left_alone(self):
        # a 1.5 km wall over ten pixels (~300 m) and a 2 km summit ramp: steep, but real
        x = np.arange(256, dtype=float)
        wall = np.clip((x - 120) * 150., 0., 1500.)[None, :].repeat(256, 0)
        out, count = fast_dem.mend_seams(wall)
        self.assertEqual(count, 0)
        self.assertIs(out is wall or np.array_equal(out, wall), True)
        ramp = (x[None, :] + x[:, None]) * 4.
        self.assertEqual(fast_dem.mend_seams(ramp)[1], 0)

    def test_a_noise_tile_is_not_a_seam_and_stays(self):
        # south of Crimea (z12 2424/1488): deep sea with most pixels at 0, not a narrow seam
        rng = np.random.default_rng(1)
        h = np.where(rng.random((256, 256)) < .7, 0., -2250.)
        out, count = fast_dem.mend_seams(h)
        self.assertEqual(count, 0)
        self.assertTrue(np.array_equal(out, h))

    def test_terrarium_encoding_round_trips(self):
        h = np.array([[-13143., -3279.5, 0., 0.00390625], [125.25, 2061.75, -32768., 8848.]])
        self.assertTrue(np.array_equal(fast_dem.terrarium_heights(fast_dem.terrarium_rgb(h)), h))

    def test_mend_file_rewrites_only_a_tile_with_a_seam(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            bad, good = Path(tmp) / 'bad.png', Path(tmp) / 'good.png'
            h = sea_tile(); h[:, 82:86] = -13143.
            Image.fromarray(fast_dem.terrarium_rgb(h), 'RGB').save(bad)
            Image.fromarray(fast_dem.terrarium_rgb(sea_tile() + 12.), 'RGB').save(good)
            before = good.read_bytes()
            self.assertEqual(fast_dem.mend_file(bad), 4 * 256)
            self.assertEqual(fast_dem.mend_file(good), 0)
            self.assertEqual(good.read_bytes(), before)
            with Image.open(bad) as image:
                self.assertEqual(float(fast_dem.terrarium_heights(np.asarray(image.convert('RGB'))).min()), 0.)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ['bad.png', 'good.png'])


if __name__ == '__main__':
    unittest.main()
