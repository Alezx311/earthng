"""Overpass as the first source of a selection: the same tiles as a cut of the country's PBF,
and NeedsPbf (the page asks to download the PBF) when no server gives a complete answer."""
import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

import osmium

import country_fetch
import native_tool
from test_native_tool import fixture, objects

SELECTION = [30.02, 50.02, 30.08, 50.06]        # the fixture's cells (test_native_tool.fixture)
PLACE = {'id': 'land', 'name': 'Land', 'pbf': 'https://download.example/land-latest.osm.pbf'}


class Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def as_xml(pbf, xml):
    """The fixture as Overpass sends it (XML, no header box)."""
    with osmium.SimpleWriter(str(xml)) as out:
        for obj in osmium.FileProcessor(str(pbf)):
            out.add(obj)
    return Path(xml).read_bytes()


class OverpassTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_selection_comes_from_overpass_until_the_pbf_is_allowed_or_on_disk(self):
        source = country_fetch.tile_source(self.root, PLACE, SELECTION)
        self.assertEqual(source.name, 'overpass')
        self.assertEqual(source.tiles, country_fetch.tiles_dir(self.root, 'land', SELECTION))
        self.assertEqual(country_fetch.tile_source(self.root, PLACE, SELECTION, allow_pbf=True).name, 'geofabrik')
        self.assertEqual(country_fetch.tile_source(self.root, PLACE).name, 'geofabrik')     # a whole region
        pbf = country_fetch.pbf_path(self.root, 'land')
        pbf.parent.mkdir(parents=True)
        pbf.write_bytes(b'x')
        self.assertEqual(country_fetch.tile_source(self.root, PLACE, SELECTION).name, 'geofabrik')

    def test_the_query_asks_for_what_the_cut_keeps(self):
        query = country_fetch.overpass_query(country_fetch.overpass_box(SELECTION), 600)
        self.assertIn('[timeout:600]', query)
        self.assertIn('node(49.990000,29.990000,50.110000,30.110000)', query)   # cells 600..601 x 1000..1001 + buffer
        self.assertIn('[type~"^(multipolygon|restriction)$"]', query)
        self.assertIn('["historic"~"^(castle|memorial|monument|ruins)$"]', query)
        self.assertIn('rel(br.r)', query)                                      # landmarks holding a multipolygon
        self.assertIn('.r >>', query)
        self.assertTrue(query.rstrip().endswith('out body;'))

    def test_an_answer_becomes_a_pbf_with_the_fetched_box(self):
        pbf = self.root / 'fixture.osm.pbf'
        fixture(pbf)
        body = as_xml(pbf, self.root / 'reply.osm')
        sent = []

        def urlopen(request, timeout, context):
            sent.append(request)
            return Reply(body)
        source = country_fetch.OverpassSource(self.root, PLACE, SELECTION)
        with patch('urllib.request.urlopen', urlopen):
            source.fetch(emit=lambda _: None)
        self.assertEqual(len(sent), 1)
        self.assertIn(b'data=', sent[0].data)
        header = osmium.io.Reader(osmium.io.File(str(source.pbf), 'pbf'), osmium.osm.osm_entity_bits.NOTHING).header()
        box = header.box()
        self.assertTrue(box.valid())
        got = [box.bottom_left.lon, box.bottom_left.lat, box.top_right.lon, box.top_right.lat]
        for a, b in zip(got, source.fetch_box):
            self.assertAlmostEqual(a, b, places=6)
        self.assertEqual(objects(source.pbf), objects(pbf))
        self.assertFalse(list(source.pbf.parent.glob('*.osm')))          # the XML is not kept
        # a second build reads the kept file
        with patch('urllib.request.urlopen', side_effect=AssertionError('asked again')):
            source.fetch(emit=lambda _: None)

    @unittest.skipUnless(native_tool.tool(), 'native Map Builder not built (cargo build --release in rust/)')
    def test_overpass_tiles_equal_a_cut_of_the_country(self):
        pbf = self.root / 'fixture.osm.pbf'
        fixture(pbf)
        body = as_xml(pbf, self.root / 'reply.osm')
        source = country_fetch.OverpassSource(self.root, PLACE, SELECTION)
        with patch('urllib.request.urlopen', lambda *a, **k: Reply(body)):
            source.fetch(emit=lambda _: None)
        source.cut(None, emit=lambda _: None)
        country_fetch.cut_tiles(pbf, self.root / 'country', SELECTION, emit=lambda _: None)
        a = json.loads((source.tiles / 'index.json').read_text(encoding='utf8'))
        b = json.loads((self.root / 'country' / 'index.json').read_text(encoding='utf8'))
        self.assertTrue(a['tiles'])
        self.assertEqual(sorted(a['tiles']), sorted(b['tiles']))
        self.assertEqual((a['region'], a['package_box']), (b['region'], b['package_box']))
        for key, tile in a['tiles'].items():
            self.assertEqual(objects(source.tiles / tile['file']), objects(self.root / 'country' / b['tiles'][key]['file']), key)
        self.assertTrue(country_fetch.tiles_current(source.tiles, SELECTION))

    def test_busy_servers_and_cut_short_answers_ask_for_the_pbf(self):
        answers = [urllib.error.HTTPError('u', 504, 'Gateway Timeout', {}, None),
                   Reply(b'<?xml version="1.0"?><osm><node id="1" lat="50" lon="30"/>'),
                   Reply(b'<osm><remark> runtime error: Query timed out in "query" </remark></osm>')]

        def urlopen(request, timeout, context):
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        source = country_fetch.OverpassSource(self.root, PLACE, SELECTION)
        lines = []
        with patch('urllib.request.urlopen', urlopen):
            with self.assertRaises(country_fetch.NeedsPbf) as caught:
                source.fetch(emit=lines.append)
        self.assertFalse(answers)                                       # every server was tried
        reason = caught.exception.reason
        self.assertIn('504', reason)
        self.assertIn('ended early', reason)
        self.assertIn('gave up', reason)
        self.assertFalse(source.pbf.exists())
        self.assertFalse(list(source.pbf.parent.glob('*.osm')))

    def test_a_large_area_asks_for_the_pbf_without_asking_overpass(self):
        big = [30.0, 50.0, 30.4, 50.3]
        self.assertGreater(country_fetch.overpass_km2(big), country_fetch.OVERPASS_MAX_KM2)
        with patch('urllib.request.urlopen', side_effect=AssertionError('asked')):
            with self.assertRaises(country_fetch.NeedsPbf) as caught:
                country_fetch.OverpassSource(self.root, PLACE, big).fetch(emit=lambda _: None)
        self.assertIn('km2', caught.exception.reason)

    def test_stop_while_streaming(self):
        import threading
        cancel = threading.Event()
        cancel.set()
        source = country_fetch.OverpassSource(self.root, PLACE, SELECTION)
        with patch('urllib.request.urlopen', lambda *a, **k: Reply(b'<osm></osm>')):
            with self.assertRaises(InterruptedError):
                source.fetch(emit=lambda _: None, cancel=cancel)


if __name__ == '__main__':
    unittest.main()
