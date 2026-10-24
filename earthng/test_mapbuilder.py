"""Map selection, estimates, previews and build lifecycle, without network or a game."""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from shapely.geometry import Polygon, box

import builder_estimate as timing
import builder_map
import country_fetch
import looks
import places


class SelectionTests(unittest.TestCase):
    def test_mercator_roundtrip_and_pole_clamp(self):
        for lon, lat in ((30.52, 50.45), (-73.99, 40.72), (179, -80)):
            result = builder_map.unproject(*builder_map.project(lon, lat))
            self.assertAlmostEqual(result[0], lon)
            self.assertAlmostEqual(result[1], lat)
        self.assertAlmostEqual(builder_map.unproject(*builder_map.project(0, 90))[1], builder_map.MAX_LAT)

    def test_smallest_source_must_cover_whole_rectangle(self):
        boundaries = {'country': box(0, 0, 10, 10), 'city': box(1, 1, 2, 2)}
        self.assertEqual(places.smallest_covering(boundaries, [1.1, 1.1, 1.9, 1.9], boundaries), 'city')
        self.assertEqual(places.smallest_covering(boundaries, [1.1, 1.1, 2.1, 2.1], boundaries), 'country')
        self.assertIsNone(places.smallest_covering(boundaries, [9, 9, 11, 11], boundaries))

    def test_holes_and_unavailable_extracts_are_not_coverage(self):
        hole = Polygon([(0,0), (5,0), (5,5), (0,5)], holes=[[(1,1), (3,1), (3,3), (1,3)]])
        boundaries = {'hole': hole, 'unavailable': box(1, 1, 3, 3)}
        self.assertIsNone(places.smallest_covering(boundaries, [1.5, 1.5, 2, 2], {'hole'}))

    def test_invalid_and_nonfinite_boxes_rejected(self):
        for value in ([1, 2, 1, 3], [2, 3, 1, 4], [0, 0, 181, 1],
                      [0, 0, 1, float('nan')], [0, 0, 1, float('inf')], [False, 0, 1, 1]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                timing.validate_box(value)

    def test_area_reduces_with_latitude(self):
        equator = timing.area_km2([0, 0, 1, 1])
        self.assertAlmostEqual(equator, 12364, delta=20)
        self.assertLess(timing.area_km2([0, 60, 1, 61]), equator * .51)


class OnlineTileTests(unittest.TestCase):
    def test_fresh_cache_served_missing_queued_once_and_offscreen_dropped(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            tiles = builder_map.OnlineTiles(tmp, workers=0)
            cached = tiles.path((5, 1, 2))
            cached.parent.mkdir(parents=True)
            Image.new('RGB', (256, 256), 'red').save(cached)
            self.assertEqual(tiles.get((5, 1, 2)).size, (256, 256))
            self.assertIsNone(tiles.get((5, 1, 3)))
            self.assertIsNone(tiles.get((5, 1, 3)))
            self.assertEqual(tiles.todo.qsize(), 1)
            with patch.object(tiles, 'download', side_effect=AssertionError('fetched off screen')):
                tiles.fetch(tiles.todo.get())
            self.assertFalse(tiles.drain())
            self.assertEqual(tiles.queued, set())

    def test_failure_waits_before_retry_and_error_pages_are_not_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            tiles = builder_map.OnlineTiles(tmp, workers=0)
            key = (5, 1, 3)
            tiles.visible = {key}
            tiles.get(key)

            class Page:
                def __enter__(self): return self
                def __exit__(self, *_): return False
                def read(self): return b'<html>blocked</html>'
            with patch.object(builder_map.urllib.request, 'urlopen', return_value=Page()) as opened:
                tiles.fetch(tiles.todo.get())
            self.assertIn('EarthNG', opened.call_args[0][0].get_header('User-agent'))
            self.assertFalse(tiles.drain())
            self.assertTrue(tiles.error)
            self.assertFalse(tiles.path(key).exists())
            tiles.get(key)
            self.assertEqual(tiles.todo.qsize(), 0)
            with patch.object(builder_map.time, 'time', return_value=time.time() + tiles.RETRY + 1):
                tiles.get(key)
            self.assertEqual(tiles.todo.qsize(), 1)


class EstimateTests(unittest.TestCase):
    def test_estimate_accounts_for_cache_source_scan_and_area(self):
        include = looks.canonical_include({})
        fresh, _ = timing.estimate(2**30, [30, 50, 30.1, 50.1], include)
        cached, _ = timing.estimate(2**30, [30, 50, 30.1, 50.1], include, True, True)
        large, _ = timing.estimate(2**30, [30, 50, 31, 51], include)
        self.assertGreater(sum(fresh), sum(cached))
        self.assertGreater(sum(large), sum(fresh))
        self.assertGreater(fresh[1], 500)  # tiny box still scans full PBF

    def test_unknown_size_and_actual_history(self):
        self.assertIsNone(timing.estimate(None, None, {})[0])
        actual = [1, 2, 3, 4, 5, 6]
        self.assertEqual(timing.estimate(None, None, {}, previous=actual)[0], actual)
        self.assertIsNone(timing.estimate(None, None, {}, previous=[float('nan')]*6)[0])

    def test_history_corruption_and_retention(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'timings.json'
            path.write_text('{broken')
            self.assertEqual(timing.load_history(path), {})
            timing.save_history(path, {str(i): [1]*6 for i in range(110)})
            history = timing.load_history(path)
            self.assertEqual(len(history), 100)
            self.assertNotIn('0', history)


class BuildLifecycleTests(unittest.TestCase):
    def test_cached_tiles_skip_pbf_and_report_ordered_stages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tiles = country_fetch.tiles_dir(root, 'test', None)
            tiles.mkdir(parents=True)
            (tiles / 'index.json').write_text('{}')
            events = []
            commands = []

            def fake_step(command, emit=None, cancel=None):
                commands.append(command)
                if '--job' not in command:
                    return
                job = json.loads(Path(command[command.index('--job') + 1]).read_text(encoding='utf-8'))
                if job['command'] == 'index':
                    Path(job['result']).write_text('[]', encoding='utf-8')
                else:
                    Path(job['result']).write_text(str(root / 'pack.zip'), encoding='utf-8')

            with patch.object(country_fetch, 'download') as download, \
                    patch.object(country_fetch, 'run_step', side_effect=fake_step), \
                    patch.object(country_fetch, 'fetch_dem'), \
                    patch.object(country_fetch, 'install_zip', return_value=root/'installed.zip'):
                country_fetch.build_place({'id':'test', 'name':'Test', 'pbf':'unused'}, root,
                                          root=root, emit=lambda _: None,
                                          progress=lambda name, seconds: events.append((name, seconds)))
            download.assert_not_called()
            self.assertTrue(commands)
            self.assertFalse(any('osm_tiles_country.py' in str(part) for command in commands for part in command))
            self.assertEqual([part for command in commands for part in command if str(part).endswith('--job')],
                             ['--job', '--job'])
            self.assertEqual([name for name, seconds in events if seconds is None], list(timing.STAGES))
            self.assertTrue(all(seconds >= 0 for _, seconds in events if seconds is not None))

    def test_build_job_writes_the_index_then_the_archive_path(self):
        import build_country
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_job = root / 'index-job.json'
            index_result = root / 'regions.json'
            index_job.write_text(json.dumps({
                'command': 'index', 'sources': 'src', 'dem': 'dem', 'work': str(root),
                'result': str(index_result),
            }), encoding='utf-8')
            with patch.object(build_country, 'grid_regions', return_value=[
                    {'dir': root / 'idx', 'core': [1, 2, 3, 4], 'id': 'e0100-n0200'}]):
                build_country.run_job(index_job)
            self.assertEqual(json.loads(index_result.read_text(encoding='utf-8')),
                             [{'dir': str(root / 'idx'), 'core': [1, 2, 3, 4], 'id': 'e0100-n0200'}])
            export_job = root / 'export-job.json'
            export_result = root / 'export-path.txt'
            export_job.write_text(json.dumps({
                'command': 'export', 'id': 'test', 'title': 'Test', 'version': '0.4.0',
                'regions': [], 'out': str(root), 'jobs': 2, 'landing': None, 'look': None,
                'include': None, 'map_data': None, 'work': str(root), 'result': str(export_result),
            }), encoding='utf-8')
            with patch.object(build_country, 'build_country', return_value=root / 'earthng_test.zip') as export:
                build_country.run_job(export_job)
            export.assert_called_once()
            self.assertEqual(export_result.read_text(encoding='utf-8'), str(root / 'earthng_test.zip'))

    def test_cancel_before_sources_never_downloads_or_installs(self):
        cancel = threading.Event()
        cancel.set()
        with patch.object(country_fetch, 'download') as download, patch.object(country_fetch, 'install_zip') as install:
            with self.assertRaises(InterruptedError):
                country_fetch.build_place({'id':'test', 'name':'Test', 'pbf':'unused'}, '.',
                                          cancel=cancel, emit=lambda _: None)
            download.assert_not_called()
            install.assert_not_called()

    def test_cancel_during_dem_retry_does_not_sleep_through_backoff(self):
        import fast_dem
        cancel = threading.Event()

        def failed(_path):
            cancel.set()
            raise OSError('network')
        with patch.object(fast_dem, 'audit', return_value=[Path('missing-test-dem.png')]), \
                patch.object(fast_dem, 'fetch', side_effect=failed), \
                patch.object(country_fetch.time, 'sleep', side_effect=AssertionError('non-cancellable sleep')):
            with self.assertRaises(InterruptedError):
                country_fetch.fetch_dem({}, '.', cancel=cancel, emit=lambda _: None)


class PreviewTests(unittest.TestCase):
    def test_native_srgb_dds_decodes_without_altering_file(self):
        from PIL import Image
        import builder_preview
        import fast_dds
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'sample.color.dds'
            fast_dds.save(Image.new('RGB', (16,16), (200,100,50)), path)
            before = path.read_bytes()
            decoded = builder_preview.decode_image(before)
            self.assertEqual(decoded.size, (16,16))
            self.assertGreater(decoded.getpixel((0,0))[0], 180)
            self.assertEqual(before, path.read_bytes())

    def test_all_choices_render_and_disabled_buildings_change_scene(self):
        import builder_preview
        from PIL import Image
        baseline = looks.canonical({'block':'general'})
        include = looks.canonical_include({})
        with patch.object(builder_preview, 'material', return_value=(Image.new('RGB', (32,32), '#888888'), 'test')):
            full, _ = builder_preview.render(baseline, include, '')
            empty, _ = builder_preview.render(baseline, {k:False for k in include}, '')
            self.assertNotEqual(full.tobytes(), empty.tobytes())
            for slot, choices in looks.SLOTS.items():
                for choice in choices:
                    rendered, _ = builder_preview.render({**baseline, slot:choice}, include, '')
                    self.assertEqual(rendered.size, (440, 230))


class TkTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        import country_ui
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.root.withdraw()
        self.ui = country_ui.Setup(self.root, start_workers=False)
        self.ui.set_places([{'id':'test', 'name':'Test', 'parent':'', 'pbf':'unused'}])
        self.ui.set_boundaries({'test':box(0, 0, 10, 10)})

    def tearDown(self):
        if hasattr(self, 'ui'):
            self.ui.pool.shutdown(wait=False, cancel_futures=True)
            # Cancel scheduled Tk callbacks before destroying the interpreter.
            if self.ui.map.pending:
                self.ui.map.after_cancel(self.ui.map.pending)
            for callback in self.root.tk.call('after', 'info'):
                self.root.after_cancel(callback)
            self.root.destroy()

    def test_map_selection_updates_source_box_and_area(self):
        self.ui.select_box([1, 1, 2, 2])
        self.assertEqual(self.ui.place['id'], 'test')
        self.assertEqual(self.ui.chosen_box(), [1, 1, 2, 2])
        self.assertIn('km²', self.ui.selection_text.get())
        self.ui.clear_box()
        self.assertIsNone(self.ui.map.selection)

    def test_late_size_response_cannot_replace_current_region(self):
        self.ui.select_place(self.ui.by_id['test'])
        before = self.ui.size.get()
        self.ui.show_size(2**30, 'old-place')
        self.assertEqual(self.ui.size.get(), before)
        self.ui.show_size(2**20, 'test')
        self.assertIn('1 MB', self.ui.size.get())

    def test_controls_lock_during_build_and_restore_readonly(self):
        self.ui.select_box([1, 1, 2, 2])
        self.ui.busy(True)
        self.ui.select_box([2, 2, 3, 3])
        self.assertEqual(self.ui.chosen_box(), [1, 1, 2, 2])
        self.assertEqual(str(self.ui.block_box.cget('state')), 'disabled')
        self.ui.busy(False)
        self.assertEqual(str(self.ui.block_box.cget('state')), 'readonly')
        self.assertFalse(self.ui.running)

    def test_worker_completion_records_timings_and_unlocks_controls(self):
        import country_ui
        def target():
            for stage in timing.STAGES:
                self.ui.stage_progress(stage, None)
                self.ui.stage_progress(stage, .1)
        with tempfile.TemporaryDirectory() as tmp, patch.object(country_ui, 'save_settings'), \
                patch.object(country_ui, 'HISTORY', Path(tmp)/'times.json'):
            self.ui.run(target, estimate=[1]*6, history_key='test-run')
            deadline = time.monotonic()+3
            while self.ui.running and time.monotonic() < deadline:
                self.root.update()
                time.sleep(.01)
            self.assertFalse(self.ui.running)
            self.assertIn('Complete', self.ui.progress_text.get())
            self.assertEqual(timing.load_history(country_ui.HISTORY)['test-run'], [.1]*6)

    def test_failed_worker_does_not_save_successful_history(self):
        import country_ui
        def target():
            raise OSError('test failure')
        with patch.object(country_ui, 'save_settings'), patch.object(timing, 'save_history') as save:
            self.ui.run(target, history_key='bad-run')
            deadline = time.monotonic()+3
            while self.ui.running and time.monotonic() < deadline:
                self.root.update()
                time.sleep(.01)
            self.assertIn('Failed', self.ui.progress_text.get())
            self.assertFalse(self.ui.running)
            save.assert_not_called()


if __name__ == '__main__':
    unittest.main()
