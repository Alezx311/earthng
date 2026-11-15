"""Count POI-like OSM tags in a PBF (tags only, no geometry): key=value -> nodes, ways, relations.

The numbers behind docs/POI.md. Ukraine (880 MB PBF) takes about 11 minutes and little memory.

Usage: python earthng/poi_census.py <file.osm.pbf> <out.json>
"""
import collections
import json
import sys
import time

import osmium

KEYS = ('amenity', 'shop', 'tourism', 'leisure', 'historic', 'man_made', 'sport', 'office', 'craft',
        'healthcare', 'emergency', 'railway', 'public_transport', 'aeroway', 'natural', 'waterway',
        'landuse', 'building', 'religion', 'memorial', 'attraction', 'club', 'playground', 'vending',
        'barrier', 'advertising', 'highway', 'military', 'power', 'telecom', 'place', 'mountain_pass',
        'information', 'artwork_type', 'bridge:structure', 'ruins', 'castle_type', 'water', 'seamark:type',
        'traffic_calming', 'parking', 'shelter_type', 'tower:type', 'aerodrome:type', 'denomination')


class Census(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.counts = collections.defaultdict(lambda: [0, 0, 0])
        self.named = collections.defaultdict(int)

    def _take(self, tags, slot):
        for key in KEYS:
            value = tags.get(key)
            if value:
                pair = key + '=' + value
                self.counts[pair][slot] += 1
                if 'name' in tags:
                    self.named[pair] += 1

    def node(self, n):
        if len(n.tags):
            self._take(n.tags, 0)

    def way(self, w):
        if len(w.tags):
            self._take(w.tags, 1)

    def relation(self, r):
        if len(r.tags):
            self._take(r.tags, 2)


def main():
    start = time.time()
    census = Census()
    census.apply_file(sys.argv[1])
    out = {pair: {'n': c[0], 'w': c[1], 'r': c[2], 'named': census.named.get(pair, 0)}
           for pair, c in census.counts.items() if sum(c) >= 20}
    with open(sys.argv[2], 'w', encoding='utf-8') as f:
        json.dump({'source': sys.argv[1], 'seconds': round(time.time() - start, 1), 'pairs': out}, f,
                  ensure_ascii=False, indent=0, sort_keys=True)
    print('pairs', len(out), 'seconds', round(time.time() - start, 1))


if __name__ == '__main__':
    main()
