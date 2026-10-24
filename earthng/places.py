"""Geofabrik extracts: any country or subregion, without a planet-sized local dump.

The index is https://download.geofabrik.de/index-v1-nogeom.json (names, parents, PBF
urls). It is cached under data/geofabrik, which is not part of the mod the player drives.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
import urllib.request

import tls


INDEX_URL = 'https://download.geofabrik.de/index-v1-nogeom.json'
USER_AGENT = 'EarthNG/0.4 (country setup)'
SLUG = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,94}[a-z0-9])?\Z')


def cache_path(root):
    return Path(root) / 'data' / 'geofabrik' / 'index-v1-nogeom.json'


def parse_index(payload):
    """[{id, name, parent, pbf}] for every extract that publishes a PBF."""
    features = payload.get('features') if isinstance(payload, dict) else None
    if not isinstance(features, list):
        raise ValueError('Geofabrik index has no features')
    places = []
    for feature in features:
        prop = feature.get('properties') if isinstance(feature, dict) else None
        if not isinstance(prop, dict):
            continue
        place_id, name = prop.get('id'), prop.get('name')
        pbf = (prop.get('urls') or {}).get('pbf') if isinstance(prop.get('urls'), dict) else None
        if not isinstance(place_id, str) or not isinstance(name, str) or not isinstance(pbf, str):
            continue
        if not pbf.startswith('https://download.geofabrik.de/'):
            continue
        places.append({'id': place_id, 'name': name, 'parent': prop.get('parent') or '', 'pbf': pbf})
    if not places:
        raise ValueError('Geofabrik index has no PBF extracts')
    return places


def by_id(places):
    return {place['id']: place for place in places}


def load_cached(root):
    path = cache_path(root)
    if not path.exists():
        return None
    return parse_index(json.loads(path.read_text(encoding='utf-8')))


def fetch_index(root, emit=print):
    """Download the index and cache it. Returns the parsed places."""
    path = cache_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    emit(f'Geofabrik index: {INDEX_URL}')
    request = urllib.request.Request(INDEX_URL, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=60, context=tls.context()) as response:
        payload = response.read()
    places = parse_index(json.loads(payload.decode('utf-8')))
    path.write_bytes(payload)
    emit(f'{len(places)} regions in {path}')
    return places


def load_index(root, refresh=False, emit=print):
    if not refresh:
        cached = load_cached(root)
        if cached:
            return cached
    return fetch_index(root, emit)


def slug(place_id):
    """Country id for the zip. Slashes in Geofabrik ids become hyphens."""
    text = place_id.strip().lower().replace('/', '-').replace('_', '-')
    text = re.sub(r'[^a-z0-9-]+', '-', text)
    text = re.sub(r'-{2,}', '-', text).strip('-')
    if not SLUG.fullmatch(text or ''):
        raise ValueError(f'cannot name a pack from {place_id!r}')
    return text


def search(places, query, limit=None):
    """Case-insensitive match on name and id. Empty query returns every extract, by name."""
    needle = (query or '').strip().casefold()
    ranked = sorted(places, key=lambda place: (place['name'].casefold(), place['id']))
    if needle:
        ranked = [place for place in ranked if needle in place['name'].casefold() or needle in place['id'].casefold()]
    return ranked[:limit] if limit else ranked


def parent_name(place, places_by_id):
    parent = places_by_id.get(place.get('parent') or '')
    return parent['name'] if parent else (place.get('parent') or '')


def load_boundaries(root, refresh=False):
    """Separate, optional geometry cache: the region list remains usable offline."""
    path = Path(root) / 'data' / 'geofabrik' / 'index-v1.json'
    if path.exists() and not refresh:
        payload = json.loads(path.read_text(encoding='utf-8'))
    else:
        request = urllib.request.Request('https://download.geofabrik.de/index-v1.json',
                                         headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(request, timeout=60, context=tls.context()) as response:
            data = response.read()
        payload = json.loads(data)
        parse_index(payload)  # validate before replacing the cache
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.json.part')
        temporary.write_bytes(data)
        temporary.replace(path)
    from shapely.geometry import shape
    result = {}
    for feature in payload['features']:
        prop = feature.get('properties') or {}
        if feature.get('geometry') and prop.get('id'):
            geometry = shape(feature['geometry'])
            if not geometry.is_empty and geometry.is_valid:
                result[prop['id']] = geometry
    return result


def smallest_covering(boundaries, box, available):
    """Choose a complete source for the rectangle, including holes/border crossings."""
    from shapely.geometry import box as rectangle
    area = rectangle(*box)
    candidates = ((geometry.area, key) for key, geometry in boundaries.items()
                  if key in available and geometry.covers(area))
    return min(candidates, default=(None, None))[1]
