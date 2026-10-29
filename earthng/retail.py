"""OSM fuel and food retail classes and conservative Ukrainian brand aliases.

Unknown brands are retained as source facts. The ASCII key is a presentation hint,
not a replacement for OSM's original brand, name, operator or object geometry.
"""
import re
import unicodedata

POINT_KEYS = ('amenity', 'shop', 'man_made', 'vending', 'brand', 'operator', 'name',
              'brand:uk', 'brand:en', 'name:uk', 'name:en', 'name:ru', 'operator:uk',
              'operator:en', 'operator:ru', 'brand:wikidata', 'operator:wikidata')

FOOD_SHOPS = frozenset(('supermarket', 'convenience', 'grocery', 'general', 'food', 'greengrocer'))


ALIASES = {
    'okko': ('OKKO', 'ОККО'), 'wog': ('WOG', 'ВОГ'),
    'ukrnafta': ('Укрнафта', 'Ukrnafta'), 'avias': ('Авіас', 'Avias'),
    'brsm': ('БРСМ', 'БРСМ-Нафта', 'BRSM', 'BRSM-Nafta'),
    'shell': ('Shell', 'Шелл'), 'socar': ('SOCAR', 'Сокар'),
    'upg': ('UPG', 'УПГ'), 'k_lo': ('KLO', 'КЛО', 'K.L.O.'),
    'motto': ('Motto', 'Мотто'), 'amic': ('AMIC', 'AMIC Energy', 'Амік'),
    'parallel': ('Parallel', 'Паралель'), 'vst': ('VST', 'ВСТ'), 'bvs': ('BVS', 'БВС'),
    'atb': ('АТБ', 'АТБ-Маркет', 'ATB', 'ATB Market'),
    'silpo': ('Сільпо', 'Silpo'), 'fora': ('Фора', 'Fora'),
    'novus': ('NOVUS', 'Новус'), 'auchan': ('Auchan', 'Ашан'),
    'velmart': ('Велмарт', 'Velmart'), 'kolo': ('Коло', 'Kolo'),
    'rukavychka': ('Рукавичка', 'Rukavychka'), 'sim23': ('Сім23', 'Сім 23', 'Sim23'),
    'simi': ('Сімі', 'Simi'), 'faino': ('Файно маркет', 'Faino Market'),
    'thrash': ('Thrash', 'Траш', 'Thrash! Траш!', 'Траш!'),
    'varus': ('Varus', 'Варус'), 'fozzy': ('Fozzy', 'Фоззі'),
    'eco': ('ЕКО маркет', 'Еко-маркет', 'ЕКО', 'Eco Market'),
    'blyzenko': ('Близенько', 'Blyzenko'),
    'mcdonalds': ("McDonald's", 'McDonalds', 'Макдональдс', 'МакДональдз'),
    'nova_poshta': ('Нова пошта', 'Новая почта', 'Nova Poshta', 'Nova Post'),
}


def _key(value):
    return re.sub(r'[^\w]+', '', unicodedata.normalize('NFKC', value).casefold())

_LOOKUP = {_key(alias): brand for brand, aliases in ALIASES.items() for alias in aliases}
FUEL = frozenset(('okko', 'wog', 'ukrnafta', 'avias', 'brsm', 'shell', 'socar', 'upg', 'k_lo', 'motto', 'amic', 'parallel', 'vst', 'bvs'))


def _recognized(tags):
    # Wikidata is useful when a localized name or brand tag is missing.
    for field in ('brand:wikidata', 'operator:wikidata'):
        if tags.get(field) == 'Q38076':
            return 'mcdonalds'
        if tags.get(field) in ('Q12133863', 'Q118613846'):
            return 'nova_poshta'
    for field in ('brand', 'brand:uk', 'brand:en', 'name', 'name:uk', 'name:en', 'name:ru',
                  'operator', 'operator:uk', 'operator:en', 'operator:ru'):
        value = tags.get(field)
        if not value:
            continue
        normalized = _key(value)
        found = _LOOKUP.get(normalized)
        if found:
            return found
        # OSM often names a branch "Нова Пошта №123" rather than setting ref.
        if re.fullmatch(r'(?:новапошта|новаяпочта|novaposhta|novapost)(?:відділення|отделение)?(?:no)?[0-9]+', normalized):
            return 'nova_poshta'
    return None


def post_type(tags):
    vending = set(tags.get('vending', '').split(';'))
    if (tags.get('amenity') == 'parcel_locker' or tags.get('man_made') == 'parcel_locker'
            or tags.get('shop') == 'parcel_locker' or vending & {'parcel_pickup', 'parcel_mail_in'}):
        return 'locker'
    if tags.get('amenity') == 'post_depot':
        return 'depot'
    return 'office'


def kind(tags):
    category = tags.get('amenity')
    if category == 'fuel':
        return 'fuel'
    if tags.get('shop') in FOOD_SHOPS:
        return 'grocery'
    found = _recognized(tags)
    if found == 'mcdonalds':
        return 'fast_food'
    if found == 'nova_poshta':
        return 'post'
    return None


def brand(tags):
    category = kind(tags)
    if not category:
        return None
    found = _recognized(tags)
    if category == 'fuel':
        return found if found in FUEL else None
    if category == 'grocery':
        return found if found and found not in FUEL and found not in ('mcdonalds', 'nova_poshta') else None
    return found


def enriched(tags):
    result = dict(tags)
    # Never trust an upstream hint or overwrite the original OSM facts.
    result.pop('e2r_brand', None)
    result.pop('e2r_post_type', None)
    recognized = brand(result)
    if recognized:
        result['e2r_brand'] = recognized
    if kind(result) == 'post':
        result['e2r_post_type'] = post_type(result)
    return result
