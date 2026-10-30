"""Places known from a register, not from OSM's tags: the list comes from who runs them.

    python earthng/venues.py locate data/pbf/ukraine.osm.pbf --type <type>

No type is in use: TYPES is empty, so packs hold no 'venue' points. The steps a type goes through
(docs/VENUES.md):

1. register: earthng/registers/<type>.tsv, the operator's own list, the only proof a place exists;
2. locate: earthng/registers/<type>.map.json, the operator's own points where it has a map, anchor
   each row; the PBF then gives the building by a name carrying its number, its address or a name
   of the type, beside the anchor. Without an anchor a row needs its town, and a namesake village
   elsewhere in the country passes that test, so a type with no map is checked by hand;
3. the located file, earthng/registers/<type>.located.json, is what pack builds read: one more
   point kind, 'venue', with the facts in its tags, and a venues.json in the pack for missions;
4. look: TYPES below and BLD.VENUE in generator.lua, from photographs of real ones.
"""
import argparse
import csv
import json
from pathlib import Path
import re
import unicodedata

HERE = Path(__file__).resolve().parent
REGISTERS = HERE / 'registers'

# A type: title, a row's name ('{ref}'); credit, {source, data, url} for the pack's CREDITS.txt;
# name and not, patterns of how its buildings call themselves in OSM and what they are not;
# regions (optional), the box (south, west, north, east) of each region a row's number starts with.
TYPES = {}

KEYS = ('name', 'name:uk', 'name:ru', 'official_name', 'alt_name', 'old_name', 'short_name', 'operator')
STREET_WORDS = {'вул', 'вулиця', 'улица', 'ул', 'пр', 'просп', 'проспект', 'прт', 'пртт', 'пров', 'провулок', 'переулок',
                'пл', 'площа', 'площадь', 'шосе', 'шоссе', 'бульвар', 'бул', 'бульв', 'узвіз', 'дорога', 'шлях', 'мікрорайон'}
PLACES = ('city', 'town', 'village', 'hamlet', 'suburb')
REACH = {'city': 30000, 'town': 15000, 'village': 8000, 'hamlet': 5000, 'suburb': 8000}   # m from a place's node
# m from the operator's point: its address is current and OSM may keep an old office under the
# same number; a bare name of the type must be next to it
NUMBER_REACH, ADDRESS_REACH, NAME_REACH = 1500, 1500, 600
MARKS = "'’ʼ`\"«»"


def fold(text):
    """Lower case without apostrophes or accents, Russian letters read as Ukrainian."""
    text = unicodedata.normalize('NFKC', text or '').casefold()
    text = ''.join(c for c in text if c not in MARKS)
    return text.translate(str.maketrans({'ы': 'и', 'э': 'е', 'ё': 'е', 'ъ': ''}))


def house_key(text):
    """'55 А', '4-А', '110-А' -> '55а', '4а', '110а'; '9/92' stays; '' without a number."""
    text = fold(text).replace(' ', '').replace('-', '')
    text = text.translate(str.maketrans('abce', 'абсе'))
    match = re.match(r'\d+[а-яіїєґ]?(/\d+[а-яіїєґ]?)?', text)
    return match.group(0) if match else ''


def street_words(text):
    """The words of a street's name that tell it apart: no 'вул.', initials or a lone number."""
    words = re.findall(r'[\wʼ]+', fold(text))
    return [w for w in words if w not in STREET_WORDS and len(w) > 1 and not w.isdigit()]


def parse_address(text):
    """{settlement, street, house, within}: within is 'mall' or 'metro' for a place inside one."""
    within = 'mall' if 'ТРЦ' in text else 'metro' if 'метро' in text.lower() else None
    body = re.sub(r'^\s*\d{5}[, ]*', '', text)
    body = re.sub(r'[.,]?\s*ТРЦ.*$', '', body)
    settlement = re.search(r'(?:^|[\s,])(?:м\.|с\.|с-ще|смт)\s*([^,]+?)\s*(?=,|вул|$)', body)
    place = settlement.group(1).strip() if settlement else ''
    rest = body[settlement.end():] if settlement else body
    parts = [p.strip() for p in rest.split(',') if p.strip()]
    street, house = '', ''
    if len(parts) >= 2:
        street, house = parts[-2], parts[-1]
    elif parts:
        match = re.match(r'(.*?\D)\s*(\d+\s*[а-яіїєґА-ЯІЇЄҐ]?(?:/\d+)?)\.?$', parts[0])
        street, house = (match.group(1), match.group(2)) if match else (parts[0], '')
    return {'settlement': place, 'street': street, 'house': house_key(re.sub(r'^(б\.|будинок)\s*', '', house)), 'within': within}


def load_register(kind):
    rows = []
    with open(REGISTERS / f'{kind}.tsv', encoding='utf8', newline='') as stream:
        for row in csv.reader((line for line in stream if not line.startswith('#')), delimiter='\t', quoting=csv.QUOTE_NONE):
            ref, address, facts = (row + [''])[:3]
            rows.append({'ref': ref, 'address': address, 'facts': [f for f in facts.split(',') if f],
                         **parse_address(address)})
    return rows


def metres(a, b):
    """Distance between (lat, lon) pairs, near enough for town scale."""
    import math
    dy = (a[0] - b[0]) * 110540
    dx = (a[1] - b[1]) * 111320 * math.cos(math.radians(a[0]))
    return math.hypot(dx, dy)


def scan(pbf, rows, kind):
    """(places, addressed, named) from the PBF: settlements of the register's names, objects at
    a register's house number on a street of its words, and objects named as the type."""
    import osmium
    spec = TYPES[kind]
    names = {fold(r['settlement']) for r in rows if r['settlement']}
    houses = {}
    for r in rows:
        if r['house'] and street_words(r['street']):
            houses.setdefault(r['house'], []).append(set(street_words(r['street'])))

    def wanted(tags):
        house = house_key(tags.get('addr:housenumber', ''))
        if not house or house not in houses:
            return False
        words = set(street_words(tags.get('addr:street', '')))
        return any(want & words for want in houses[house])

    def named(tags):
        text = ' | '.join(tags.get(k, '') for k in KEYS)
        return bool(text) and spec['name'].search(fold(text)) and not spec['not'].search(fold(text))

    found = {'places': [], 'addressed': [], 'named': []}

    def add(osm, tags, lat, lon, area=0.):
        record = {'osm': osm, 'lat': lat, 'lon': lon, 'area': area, 'name': tags.get('name', ''),
                  'street': tags.get('addr:street', ''), 'house': tags.get('addr:housenumber', ''),
                  'building': tags.get('building', '')}
        if wanted(tags):
            found['addressed'].append(record)
        if named(tags):
            found['named'].append(record)

    class Reader(osmium.SimpleHandler):
        def node(self, n):
            if not n.location.valid():
                return
            tags = dict(n.tags)
            if tags.get('place') in PLACES:
                for key in ('name', 'name:uk', 'name:ru', 'old_name'):
                    if fold(tags.get(key)) in names:
                        found['places'].append({'name': fold(tags[key]), 'lat': n.location.lat, 'lon': n.location.lon,
                                                'place': tags['place']})
                        break
            add(f'node/{n.id}', tags, n.location.lat, n.location.lon)

        def way(self, w):
            tags = dict(w.tags)
            if not wanted(tags) and not named(tags):
                return
            try:
                nodes = [(n.lat, n.lon) for n in w.nodes]
            except osmium.InvalidLocationError:
                return
            if nodes:
                lat = sum(p[0] for p in nodes) / len(nodes)
                lon = sum(p[1] for p in nodes) / len(nodes)
                span = metres(min(nodes), max(nodes))
                add(f'way/{w.id}', tags, lat, lon, span * span)

    Reader().apply_file(str(pbf), locations=True, filters=[
        osmium.filter.KeyFilter('place', 'addr:housenumber', 'name', 'operator', 'official_name').enable_for(
            osmium.osm.NODE | osmium.osm.WAY)])
    return found


def resolve(rows, found, kind, anchors=None):
    """Each row's place and how it was found: 'number', 'address', 'name' for an OSM object beside
    its anchor (or in its town, with none), 'map' for the anchor alone; unplaced rows keep a
    'reason'. Without an anchor a name in a town of several rows cannot tell which is which."""
    anchors = anchors or {}
    out = []
    per_town = {}
    for r in rows:
        per_town[fold(r['settlement'])] = per_town.get(fold(r['settlement']), 0) + 1
    for r in rows:
        anchor = anchors.get(r['ref'])
        town = [p for p in found['places'] if p['name'] == fold(r['settlement']) and in_region(kind, r['ref'], (p['lat'], p['lon']))]
        reach = max([REACH[p['place']] for p in town], default=0)
        # an anchor away from the row's own town is the geocoder's guess
        if anchor and town and not any(metres(anchor, (p['lat'], p['lon'])) <= REACH[p['place']] for p in town):
            anchor = None

        def beside(item, limit):
            if not in_region(kind, r['ref'], (item['lat'], item['lon'])):
                return False
            if anchor:
                return metres((item['lat'], item['lon']), anchor) <= limit
            return any(metres((item['lat'], item['lon']), (p['lat'], p['lon'])) <= reach for p in town)

        hit, how = None, None
        numbered = [n for n in found['named'] if re.search(r'(?<!\d)' + r['ref'] + r'(?!\d)', n['name'])
                    and (beside(n, NUMBER_REACH) or not (anchor or town))]
        if numbered:
            hit, how = max(numbered, key=lambda n: n['area']), 'number'
        if not hit and r['house']:
            want = set(street_words(r['street']))
            same = [a for a in found['addressed'] if house_key(a['house']) == r['house']
                    and want & set(street_words(a['street'])) and beside(a, ADDRESS_REACH)]
            if same:
                hit, how = max(same, key=lambda a: (bool(a['building']), a['area'])), 'address'
        if not hit and (anchor or per_town[fold(r['settlement'])] == 1):
            near = [n for n in found['named'] if beside(n, NAME_REACH)]
            if near:
                hit, how = max(near, key=lambda n: n['area']), 'name'
        record = {k: r[k] for k in ('ref', 'address', 'facts', 'within')}
        record['name'] = TYPES[kind]['title'].format(**r)
        if hit:
            record.update(lat=round(hit['lat'], 7), lon=round(hit['lon'], 7), osm=hit['osm'], how=how)
        elif anchor:
            record.update(lat=anchor[0], lon=anchor[1], how='map')
        else:
            record['reason'] = 'no_settlement' if not town else 'no_address'
            if r['ref'] in anchors:
                record['reason'] += '_anchor_elsewhere'
        out.append(record)
    return out


def located_path(kind):
    return REGISTERS / f'{kind}.located.json'


def scanned(pbf, rows, kind):
    """scan() kept under data/venues until the PBF changes: it reads the whole country."""
    stat = Path(pbf).stat()
    stamp = [Path(pbf).name, stat.st_size, stat.st_mtime_ns]
    path = HERE.parent / 'data' / 'venues' / f'{kind}.scan.json'
    if path.is_file():
        saved = json.loads(path.read_text(encoding='utf8'))
        if saved['stamp'] == stamp:
            return saved['found']
    found = scan(pbf, rows, kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'stamp': stamp, 'found': found}, ensure_ascii=False), encoding='utf8')
    return found


def in_region(kind, ref, at):
    box = TYPES[kind].get('regions', {}).get(ref[:2])
    return box is None or (box[0] <= at[0] <= box[2] and box[1] <= at[1] <= box[3])


def anchors_of(kind):
    """ref -> (lat, lon) from the operator's map, {} for a type without one. A point outside its
    number's region is dropped: its row is then placed as one without a map."""
    path = REGISTERS / f'{kind}.map.json'
    if not path.is_file():
        return {}
    points = {ref: tuple(at) for ref, at in json.loads(path.read_text(encoding='utf8'))['points'].items()}
    return {ref: at for ref, at in points.items() if in_region(kind, ref, at)}


def locate(pbf, kind):
    rows = load_register(kind)
    records = resolve(rows, scanned(pbf, rows, kind), kind, anchors_of(kind))
    document = {'type': kind, 'source': Path(pbf).name, 'records': records}
    located_path(kind).write_text(json.dumps(document, ensure_ascii=False, indent=0) + '\n', encoding='utf8')
    return records


def located(kinds=None):
    """(kind, record) of every placed row of the registers with a located file."""
    for path in sorted(REGISTERS.glob('*.located.json')):
        kind = path.name.split('.')[0]
        if kinds is None or kind in kinds:
            for record in json.loads(path.read_text(encoding='utf8'))['records']:
                if 'lat' in record:
                    yield kind, record


def point_tags(kind, record):
    """What a pack's 'venue' point carries."""
    tags = {'e2r_venue': kind, 'e2r_ref': record['ref'], 'name': record['name']}
    if record.get('within'):
        tags['e2r_within'] = record['within']
    return tags


def catalogue(coverage):
    """The placed rows inside a pack's coverage boxes (west, south, east, north), each with its type."""
    return [{'type': kind, **record} for kind, record in located()
            if any(w <= record['lon'] <= e and s <= record['lat'] <= n for w, s, e, n in coverage)]


def credits(places):
    return [TYPES[kind]['credit'] for kind in sorted({place['type'] for place in places})]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('action', choices=('locate',))
    parser.add_argument('pbf', type=Path)
    parser.add_argument('--type', required=True, choices=sorted(TYPES))
    args = parser.parse_args()
    records = locate(args.pbf, args.type)
    how = {}
    for record in records:
        key = record.get('how') or record['reason']
        how[key] = how.get(key, 0) + 1
    print(len(records), how)


if __name__ == '__main__':
    main()
