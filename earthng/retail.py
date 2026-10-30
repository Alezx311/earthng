"""OSM fuel, food retail and roadside service classes and conservative Ukrainian brand aliases.

Unknown brands are retained as source facts. The ASCII key is a presentation hint,
not a replacement for OSM's original brand, name, operator or object geometry.
"""
import re
import unicodedata

POINT_KEYS = ('amenity', 'shop', 'man_made', 'vending', 'brand', 'operator', 'name',
              'brand:uk', 'brand:en', 'name:uk', 'name:en', 'name:ru', 'operator:uk',
              'operator:en', 'operator:ru', 'brand:wikidata', 'operator:wikidata')

FOOD_SHOPS = frozenset(('supermarket', 'convenience', 'grocery', 'general', 'food', 'greengrocer'))
# Mapped services a driver looks for: each has a plain sign, the networks below their own
SERVICE_AMENITY = frozenset(('car_wash', 'charging_station', 'pharmacy', 'bank', 'cafe', 'restaurant', 'fast_food', 'bar', 'pub'))
SERVICE_SHOPS = frozenset(('car_repair', 'tyres'))


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
    # the service networks, their items from the OSM tags' brand:wikidata
    'oschadbank': ('Ощадбанк', 'Oschadbank'), 'privatbank': ('ПриватБанк', 'PrivatBank'),
    'raiffeisen': ('Райффайзен Банк', 'Raiffeisen Bank', 'Райффайзен', 'Raiffeisen'),
    'ukrsibbank': ('УкрСиббанк', 'UkrSibbank'), 'sense': ('Sense Bank', 'Сенс Банк'),
    'pumb': ('ПУМБ', 'PUMB'), 'ukrgasbank': ('Укргазбанк', 'Ukrgasbank'), 'a_bank': ('А-Банк', 'A-Bank'),
    'credit_agricole': ('Crédit Agricole', 'Credit Agricole', 'Креді Агріколь'), 'otp': ('OTP Bank', 'ОТП Банк'),
    'podorozhnyk': ('Подорожник', 'Аптека Подорожник', 'Podorozhnyk'), 'anc': ('АНЦ', 'Аптека низьких цін', 'ANC'),
    'apteka_911': ('Аптека 911', 'Аптека 9-1-1'), 'apteka_opt': ('Аптека оптових цін', 'Аптека оптових ц‥'),
    'bazhaemo': ("Бажаємо здоров'я", 'Бажаємо здоровʼя'), 'dobroho_dnya': ('Аптека Доброго Дня', 'Доброго Дня'),
    'zdorova_rodyna': ('Здорова Родина',), 'lviv_croissants': ('Lviv Croissants', 'Львівські круасани'),
    'kfc': ('KFC', 'КФС'), 'dominos': ("Domino's", "Domino's Pizza", 'Dominos'),
    'aroma_kava': ('Aroma Kava', 'Арома Кава'), 'kulynychi': ('Кулиничі',), 'puzata_hata': ('Пузата Хата', 'Puzata Hata'),
    'pizza_day': ('Pizza Day',), 'ionity': ('Ionity', 'IONITY Charging Station'), 'toka': ('Toka',),
    'autoenterprise': ('AutoEnterprise', 'Автоентерпрайз', 'AE Charging Station', 'AutoEnterprise Charging Station', 'EVA Chargers'),
    'vianor': ('Vianor', 'Віанор'),
}
# brand:wikidata of the service networks (OSM's own tags, counted over Ukraine)
WIKIDATA = {'Q4340839': 'oschadbank', 'Q1515015': 'privatbank', 'Q4389243': 'raiffeisen', 'Q1976290': 'ukrsibbank',
            'Q16691757': 'sense', 'Q4341156': 'pumb', 'Q4470692': 'ukrgasbank', 'Q28705400': 'a_bank',
            'Q590952': 'credit_agricole', 'Q16688676': 'otp', 'Q117706903': 'podorozhnyk', 'Q100148965': 'anc',
            'Q117705836': 'apteka_911', 'Q117617038': 'apteka_opt', 'Q117404902': 'bazhaemo', 'Q102174228': 'dobroho_dnya',
            'Q117706848': 'zdorova_rodyna', 'Q116871093': 'lviv_croissants', 'Q524757': 'kfc', 'Q839466': 'dominos',
            'Q102175745': 'aroma_kava', 'Q117003960': 'kulynychi', 'Q11832009': 'puzata_hata', 'Q122869046': 'pizza_day',
            'Q42717773': 'ionity', 'Q117745034': 'toka', 'Q113289500': 'autoenterprise', 'Q10714920': 'vianor'}
SERVICE_NETWORKS = frozenset(WIKIDATA.values())


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
        if tags.get(field) in WIKIDATA:
            return WIKIDATA[tags[field]]
    for field in ('brand', 'brand:uk', 'brand:en', 'name', 'name:uk', 'name:en', 'name:ru',
                  'operator', 'operator:uk', 'operator:en', 'operator:ru'):
        value = tags.get(field)
        if not value:
            continue
        normalized = _key(value)
        # a branch's number after the name: 'Подорожник №12'
        found = _LOOKUP.get(normalized) or _LOOKUP.get(re.sub(r'(?:no)?[0-9]+$', '', normalized))
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
    if category in SERVICE_AMENITY or tags.get('shop') in SERVICE_SHOPS:
        return 'service'
    return None


def brand(tags):
    category = kind(tags)
    if not category:
        return None
    found = _recognized(tags)
    if category == 'fuel':
        return found if found in FUEL else None
    if category == 'service':
        return found if found in SERVICE_NETWORKS else None
    if category == 'grocery':
        return found if found and found not in FUEL and found not in SERVICE_NETWORKS and found not in ('mcdonalds', 'nova_poshta') else None
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
