"""Cache OSM fuel and food retail locations from an existing PBF, no network required.

    python earthng/retail_cache.py input.osm.pbf data/retail/ukraine.jsonl.gz

One record per tagged OSM node, way or polygon (not one inferred physical business).
Keeps source tags, geometry and IDs, including unknown/local brands. Re-run skips an
unchanged input; use --force to rescan. OSM polygons may overlap nodes for one site.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import time

import osmium
import retail


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def build(source, output, force=False):
    source, output = Path(source), Path(output)
    metadata = output.with_name(output.name + '.meta.json')
    stat = source.stat()
    fingerprint = {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}
    if not force and output.is_file() and metadata.is_file():
        old = json.loads(metadata.read_text(encoding='utf-8'))
        if old.get('source_stat') == fingerprint and old.get('schema') == 4:
            return old
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name + '.part')
    counts = {'fuel': 0, 'grocery': 0, 'fast_food': 0, 'post': 0, 'service': 0, 'invalid_geometry': 0}
    start = time.monotonic()
    factory = osmium.geom.GeoJSONFactory()
    try:
        with gzip.open(temp, 'wt', encoding='utf-8', compresslevel=5) as stream:
            def emit(osm_type, osm_id, tags, geometry):
                category = retail.kind(tags)
                if not category:
                    return
                record = {'type': 'Feature', 'id': f'{osm_type}/{osm_id}',
                          'geometry': geometry, 'properties': {'kind': category, 'tags': dict(tags)}}
                stream.write(json.dumps(record, ensure_ascii=False, separators=(',', ':')) + '\n')
                counts[category] += 1

            class Reader(osmium.SimpleHandler):
                def node(self, node):
                    if retail.kind(node.tags) and node.location.valid():
                        emit('node', node.id, node.tags,
                             {'type': 'Point', 'coordinates': [node.location.lon, node.location.lat]})

                def way(self, way):
                    # Closed ways are emitted once by area(), with polygon geometry.
                    # Preserve tagged open ways too; they are rare but remain source facts.
                    if not retail.kind(way.tags) or way.is_closed():
                        return
                    try:
                        coordinates = [[node.lon, node.lat] for node in way.nodes]
                    except osmium.InvalidLocationError:
                        counts['invalid_geometry'] += 1
                        return
                    if len(coordinates) < 2:
                        counts['invalid_geometry'] += 1
                        return
                    emit('way', way.id, way.tags, {'type': 'LineString', 'coordinates': coordinates})

                def area(self, area):
                    if not retail.kind(area.tags):
                        return
                    try:
                        geometry = json.loads(factory.create_multipolygon(area))
                    except RuntimeError:
                        counts['invalid_geometry'] += 1
                        return
                    emit('way' if area.from_way() else 'relation', area.orig_id(), area.tags, geometry)

            Reader().apply_file(str(source), locations=True, filters=[
                osmium.filter.KeyFilter(*retail.POINT_KEYS).enable_for(osmium.osm.NODE)])
        info = {'schema': 4, 'source': source.name, 'source_stat': fingerprint,
                'source_sha256': sha256(source),
                'copyright': 'OpenStreetMap contributors, ODbL 1.0',
                'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'seconds': round(time.monotonic() - start, 1), 'counts': counts}
        os.replace(temp, output)
        metadata.write_text(json.dumps(info, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return info
    finally:
        temp.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.output, args.force), ensure_ascii=False, indent=2))
