import gzip
import json
from collections import OrderedDict
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import shapely
import fast_sources
import fast_style
import retail
import retail_cache

OSM = '''<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="test">
 <node id="1" lat="50.001" lon="30.001"><tag k="amenity" v="fuel"/><tag k="brand" v="ОККО"/></node>
 <node id="2" lat="50.002" lon="30.002"/><node id="3" lat="50.002" lon="30.000"/>
 <node id="4" lat="50.000" lon="30.000"/><node id="5" lat="50.000" lon="30.002"/>
 <node id="6" lat="50.004" lon="30.004"><tag k="shop" v="convenience"/><tag k="name" v="Сільський магазин"/></node>
 <node id="7" lat="50.006" lon="30.006"/><node id="8" lat="50.006" lon="30.005"/>
 <node id="9" lat="50.005" lon="30.005"/><node id="10" lat="50.005" lon="30.006"/>
 <node id="19" lat="50.009" lon="30.009"><tag k="amenity" v="fast_food"/><tag k="brand:wikidata" v="Q38076"/></node>
 <node id="20" lat="50.009" lon="30.008"><tag k="amenity" v="parcel_locker"/><tag k="operator:wikidata" v="Q12133863"/></node>
 <node id="21" lat="50.009" lon="30.007"><tag k="amenity" v="post_office"/><tag k="name" v="Нова Пошта №12"/></node>
 <node id="22" lat="50.009" lon="30.006"><tag k="amenity" v="vending_machine"/><tag k="vending" v="parcel_pickup;parcel_mail_in"/><tag k="operator" v="Nova Poshta"/></node>
 <node id="13" lat="50.008" lon="30.008"/><node id="14" lat="50.008" lon="30.007"/>
 <node id="15" lat="50.007" lon="30.007"/><node id="16" lat="50.007" lon="30.008"/>
 <node id="23" lat="50.0095" lon="30.0075"/><node id="24" lat="50.0095" lon="30.0085"/>
 <node id="25" lat="50.0085" lon="30.0085"/><node id="26" lat="50.0085" lon="30.0075"/>
 <way id="11"><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="5"/><nd ref="2"/>
  <tag k="amenity" v="fuel"/><tag k="brand" v="OKKO"/></way>
 <way id="12"><nd ref="7"/><nd ref="8"/><nd ref="9"/><nd ref="10"/><nd ref="7"/>
  <tag k="shop" v="supermarket"/><tag k="brand" v="Сільпо"/><tag k="building" v="retail"/></way>
 <way id="17"><nd ref="13"/><nd ref="14"/><nd ref="15"/><nd ref="16"/><nd ref="13"/></way>
 <way id="27"><nd ref="23"/><nd ref="24"/><nd ref="25"/><nd ref="26"/><nd ref="23"/>
  <tag k="amenity" v="post_office"/><tag k="brand" v="Нова пошта"/></way>
 <way id="28"><nd ref="23"/><nd ref="24"/>
  <tag k="amenity" v="fast_food"/><tag k="brand" v="McDonald's"/></way>
 <relation id="18"><member type="way" ref="17" role="outer"/><tag k="type" v="multipolygon"/>
  <tag k="shop" v="supermarket"/><tag k="brand" v="Фора"/></relation>
</osm>'''


class RetailTests(unittest.TestCase):
    def test_classes_and_conservative_brand_matching(self):
        self.assertEqual(retail.brand({'amenity': 'fuel', 'brand': 'ОККО'}), 'okko')
        self.assertEqual(retail.brand({'shop': 'supermarket', 'brand': 'Сільпо'}), 'silpo')
        self.assertIsNone(retail.brand({'shop': 'supermarket', 'brand': 'ОККО'}))
        self.assertIsNone(retail.brand({'shop': 'convenience', 'name': 'Магазин ОККО'}))
        self.assertEqual(fast_style.point_kind({'shop': 'convenience'}), 'grocery')
        self.assertEqual(fast_style.point_kind({'amenity': 'fuel'}), 'fuel')
        self.assertEqual(retail.brand({'amenity': 'fast_food', 'brand:wikidata': 'Q38076'}), 'mcdonalds')
        self.assertEqual(retail.enriched({'amenity': 'parcel_locker', 'operator': 'Нова пошта'})['e2r_post_type'], 'locker')
        self.assertEqual(retail.enriched({'amenity': 'vending_machine', 'vending': 'parcel_pickup;parcel_mail_in',
                                          'operator': 'Nova Poshta'})['e2r_post_type'], 'locker')
        self.assertEqual(retail.brand({'amenity': 'post_office', 'name': 'Нова Пошта №12'}), 'nova_poshta')
        self.assertIsNone(retail.kind({'amenity': 'post_office', 'operator': 'Укрпошта'}))

    def test_cache_roundtrip_includes_polygon_and_unknown_and_reuses_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder) / 'input.osm', Path(folder) / 'shops.jsonl.gz'
            source.write_text(OSM, encoding='utf-8')
            info = retail_cache.build(source, output)
            with gzip.open(output, 'rt', encoding='utf-8') as stream:
                records = [json.loads(line) for line in stream]
            self.assertEqual({r['id'] for r in records}, {'node/1', 'node/6', 'way/11', 'way/12', 'relation/18', 'node/19', 'node/20', 'node/21', 'node/22', 'way/27', 'way/28'})
            self.assertEqual(info['counts']['fuel'], 2)
            self.assertEqual(info['counts']['grocery'], 3)
            self.assertEqual(info['counts']['fast_food'], 2)
            self.assertEqual(info['counts']['post'], 4)
            self.assertEqual(next(r for r in records if r['id'] == 'way/28')['geometry']['type'], 'LineString')
            self.assertEqual(next(r for r in records if r['id'] == 'node/6')['properties']['tags']['name'], 'Сільський магазин')
            self.assertEqual(retail_cache.build(source, output), info)

    def test_source_tiles_keep_site_geometry_and_prefer_node(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'tile.osm'
            source.write_text(OSM, encoding='utf-8')
            class IdentityFrame:
                def geo_bbox(self, rect): return rect
                def local(self, x, y): return x, y
            store = object.__new__(fast_sources.Store)
            store.frame, store.scenes = IdentityFrame(), OrderedDict()
            store.meta = {'source': folder}
            store.source_index = {}
            with patch('osm_tiles.tile_for', return_value=('1', {'file': source.name})):
                records = store.scenery([29.99, 49.99, 30.01, 50.01])
            kinds = [record[1] for record in records]
            self.assertEqual(kinds.count('fuel'), 1)
            self.assertEqual(kinds.count('fuel_site'), 1)
            self.assertEqual(kinds.count('grocery'), 3)
            self.assertEqual(kinds.count('grocery_site'), 2)
            self.assertEqual(kinds.count('building'), 1)
            self.assertEqual(kinds.count('fast_food'), 1)
            self.assertEqual(kinds.count('post'), 4)
            self.assertEqual(kinds.count('post_site'), 1)
            fuel = next(r for r in records if r[1] == 'fuel')
            self.assertEqual(fuel[2]['tags']['e2r_brand'], 'okko')
            self.assertEqual(tuple(fuel[3].coords)[0], (30.001, 50.001))
            site = next(r for r in records if r[1] == 'grocery_site')
            self.assertTrue(site[3].covers(site[3].representative_point()))


if __name__ == '__main__':
    unittest.main()
