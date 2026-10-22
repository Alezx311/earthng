"""Build sections of a country: its administrative areas (counties, cities) from the OSM extract.

A section is the unit we rebuild while improving a country: one region of the country pack in
its own zip (earthng_<country>_<section>.zip). The game joins every mounted section of a
country into that one country (countries.lua).
"""
import hashlib
import json
import re
import unicodedata
from pathlib import Path

VERSION = 'sections-1'
LEVELS = ('4', '5', '6', '7')     # states/provinces, counties, cities; not villages
SIMPLIFY = 0.001                  # degrees (~100 m) of the stored outline
MARGIN = 0.02                     # degrees round the outline: neighbours share a little edge
MAX_SPAN_KM = 160.                # a region's frame keeps the car within ~80 km of its centre


def slug(name):
    """'Lääne-Viru maakond' -> 'laane-viru-maakond'."""
    text = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '-', text).strip('-')


def scan(pbf, levels=LEVELS):
    """Every boundary=administrative area of the levels in the extract: [{id, name, level, box,
    geometry (GeoJSON, lon/lat)}], sorted by id."""
    import osmium
    import osmium.geom
    import shapely
    from shapely import wkb

    factory = osmium.geom.WKBFactory()
    found = []

    class Areas(osmium.SimpleHandler):
        def area(self, a):
            tags = a.tags
            if (a.from_way() or tags.get('boundary') != 'administrative'
                    or tags.get('admin_level') not in levels or not tags.get('name')):
                return
            try:
                shape = wkb.loads(factory.create_multipolygon(a), hex=True)
            except RuntimeError:            # an unclosed ring at the extract edge
                return
            shape = shapely.simplify(shape, SIMPLIFY, preserve_topology=True)
            name = tags.get('name:en') or tags.get('name')
            found.append({'id': slug(tags.get('name')), 'name': name, 'level': int(tags.get('admin_level')),
                          'osm': a.orig_id(), 'box': [round(v, 5) for v in shape.bounds],
                          'geometry': shapely.geometry.mapping(shape)})

    Areas().apply_file(str(pbf), locations=True, idx='flex_mem')
    seen, out = {}, []
    for entry in sorted(found, key=lambda e: (e['id'], e['level'], e['osm'])):
        if entry['id'] in seen:         # the same name twice (a city and its county): add the level
            entry['id'] = f"{entry['id']}-{entry['level']}"
            if entry['id'] in seen:
                continue
        seen[entry['id']] = entry
        out.append(entry)
    return out


def load(pbf, cache):
    """scan() of the extract, cached next to it by the extract's size and time."""
    pbf = Path(pbf)
    stat = pbf.stat()
    key = hashlib.sha256(f'{VERSION}:{pbf.name}:{stat.st_size}:{int(stat.st_mtime)}'.encode()).hexdigest()[:10]
    path = Path(cache) / f'{pbf.name.split(".")[0]}-{key}.json'
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    found = scan(pbf)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix('.part')
    part.write_text(json.dumps(found), encoding='utf-8')
    part.replace(path)
    return found


def find(found, name):
    """The section called name: its id, its slug, or the one id starting with it ('harju')."""
    key = slug(name)
    exact = [s for s in found if s['id'] == key]
    if exact:
        return exact[0]
    near = [s for s in found if s['id'].startswith(key + '-')]
    if len(near) == 1:
        return near[0]
    choices = ', '.join(sorted(s['id'] for s in (near or found)))
    raise ValueError(f'no single section {name!r}; choose one of: {choices}')


def box(section, margin=MARGIN):
    """The section's lon/lat box grown by margin, checked against the region size limit."""
    import math
    w, s, e, n = section['box']
    w, s, e, n = w - margin, s - margin, e + margin, n + margin
    wide = (e - w) * 111.32 * math.cos(math.radians((s + n) / 2))
    tall = (n - s) * 110.57
    if max(wide, tall) > MAX_SPAN_KM:
        raise ValueError(f"section {section['id']} is {wide:.0f} x {tall:.0f} km; one region holds "
                         f'at most {MAX_SPAN_KM:.0f} km: build its smaller parts')
    return [round(v, 5) for v in (w, s, e, n)]


def shape(section, margin=MARGIN):
    """The section's outline grown by margin (lon/lat): the cells it exports."""
    import shapely
    return shapely.geometry.shape(section['geometry']).buffer(margin)
