"""The proving ground's names in English (25.11, the user: the island's points on the map were
Ukrainian in the English UI). The plan is drawn with Ukrainian names, as the island is a post-Soviet
town; english() gives each its English form, and add_english() writes it as name:en (brand:en,
operator:en, destination:en, addr:street:en) where the plan has none, the way OSM keeps both.

A name not in NAMES is read as a tile's code and a name ('MT-C2 Ряд 3'), as a pattern with a
number or an OSM value ('Двір asphalt', 'ухил 10 %'), or as parts joined by ' · '. A name none of
these reads gives None: test_proving_ground fails on it, so a new Ukrainian name needs its English
here."""
import re

CYRILLIC = re.compile('[Ѐ-ӿ]')
CODE = re.compile(r'^([A-Z]{1,2}-[A-Z]\d+|[A-Z]\d+) (.*)$')
# the tags whose value a player reads: on the map, on a card, on a sign
KEYS = ('name', 'brand', 'operator', 'destination', 'addr:street')

NAMES = {
    # --- shops, chains and services ----------------------------------------------------------------
    'АЗС «Міраж»': 'Mirage gas station', 'АЗС, мотель, відпочинок': 'Gas station, motel, rest stop',
    'АТБ': 'ATB', 'Сільпо': 'Silpo', 'Фора': 'Fora', 'Епіцентр': 'Epicentr', 'Нова Пошта': 'Nova Poshta',
    'Нова Пошта №1': 'Nova Poshta No. 1', 'ПриватБанк': 'PrivatBank', 'Ощадкаса': 'Savings bank',
    'Укрнафта': 'Ukrnafta', 'БРСМ-Нафта': 'BRSM-Nafta', 'ТОКА': 'TOKA', 'Пузата Хата': 'Puzata Hata',
    'Львівські круасани': 'Lviv Croissants', 'Мобілочка': 'Mobilochka', 'Вина світу': 'Wines of the World',
    'Аптека': 'Pharmacy', 'Аптека 911': 'Apteka 911', 'Аптека АНЦ': 'ANC Pharmacy',
    'Аптека Доброго Дня': 'Good Day Pharmacy', 'Автозапчастини': 'Car parts', 'Автосалон': 'Car dealership',
    'Автосалони й СТО': 'Car dealerships and garages', 'СТО': 'Car repair', 'Мийка': 'Car wash',
    'Шини': 'Tires', 'Мото': 'Motorcycles', 'Ательє': 'Tailor', 'Годинникар': 'Watchmaker',
    'Господар': 'Handyman', 'Гастроном': 'Grocery', 'Продукти': 'Groceries', 'Сільмаг': 'Village shop',
    'Овочі': 'Vegetables', 'Одяг': 'Clothes', 'Меблі': 'Furniture', 'Зоотовари': 'Pet shop',
    'Квіти': 'Flowers', 'Книгарня': 'Bookshop', 'Пекарня': 'Bakery', 'Перукарня': 'Hairdresser',
    'Кава': 'Coffee', 'Кав’ярня': 'Café', 'Кав’ярня «Точка»': 'Point Café', 'Кафе «Дальнобій»': 'Trucker Café',
    'Корчма «Під перевалом»': 'Tavern Below the Pass', 'Шаурма': 'Shawarma', 'Преса': 'Newsstand',
    'Лото': 'Lottery', 'Таксі': 'Taxi', 'Фітнес': 'Fitness', 'Пасаж': 'Arcade', 'Ринок': 'Market',
    'Ринок і автостанція': 'Market and bus station', 'Торгівля': 'Retail', 'ТРЦ «Атол»': 'Atoll Mall',
    'Крамниці вздовж дороги': 'Roadside shops', 'Мережі й бренди': 'Chains and brands',
    'Готель «Океан»': 'Ocean Hotel', 'Мотель «Тихий»': 'Quiet Motel', 'Офіси й готель': 'Offices and hotel',
    'БЦ «Немо»': 'Nemo Business Center', 'Логістика': 'Logistics', 'Склади': 'Warehouses',
    'Реклама': 'Billboards',
    # --- town and buildings ------------------------------------------------------------------------
    'Немо': 'Nemo', 'Немоград': 'Nemograd', 'Містечко': 'Small town', 'Село, садиби': 'Village, homesteads',
    'Дачі': 'Summer cottages', 'Котеджі, таунхауси': 'Cottages, townhouses',
    'Новобудови 25 поверхів': 'New towers, 25 floors', 'Панельки 16 поверхів': 'Panel blocks, 16 floors',
    'Панельки 9 поверхів': 'Panel blocks, 9 floors', 'Хрущовки, 1960-ті': 'Khrushchyovkas, 1960s',
    'Сталінки, 1950-ті': 'Stalin-era blocks, 1950s', 'Старе місто, 1900-ті': 'Old town, 1900s',
    'Дім з арками': 'House with arches', 'За будинком': 'Behind the house', 'Будмайданчик': 'Construction site',
    'Гаражі й будова': 'Garages and building site', 'ГБК «Маяк»': 'Mayak Garage Co-op',
    'СТ «Прибій»': 'Surf Garden Plots', 'Городи': 'Vegetable gardens', 'Ферма': 'Farm',
    'Ферма й поля': 'Farm and fields', 'Поля': 'Fields', 'Плантація': 'Plantation',
    'Завод «Полюс»': 'Polus Works', 'Завод і ТЕЦ': 'Factory and power plant', 'ТЕЦ': 'Power plant',
    'Підстанція': 'Substation', 'Очисні': 'Treatment plant', 'Нафтопромисел': 'Oil field',
    'Телевежа': 'TV tower', 'Прохідна': 'Gatehouse', 'Школа № 1': 'School No. 1',
    'Школа, садок, спорт': 'School, kindergarten, sports', 'Дитсадок «Хвиля»': 'Wave Kindergarten',
    'Університет': 'University', 'Лікарня, університет': 'Hospital, university',
    'Лікарня швидкої допомоги': 'Emergency hospital', 'Поліклініка': 'Clinic', 'Швидка': 'Ambulance',
    'Під’їзд швидкої': 'Ambulance entrance', 'Театр': 'Theatre', 'Музей океану': 'Ocean Museum',
    'Собор': 'Cathedral', 'Церква': 'Church', 'Гірська церква': 'Mountain church', 'Замок': 'Castle',
    'Купол': 'Dome', 'Меморіал': 'Memorial', 'Монумент картографам': 'Monument to the Cartographers',
    'Меридіан': 'Meridian', 'Маяк Немо': 'Nemo Lighthouse', 'Арена': 'Arena', 'Спорткомплекс': 'Sports complex',
    'Стадіон «Немо»': 'Nemo Stadium', 'Стадіон, корти, парк': 'Stadium, courts, park', 'Гольф': 'Golf',
    'Цвинтар': 'Cemetery', 'Цвинтар, місця відпочинку': 'Cemetery, rest areas', 'Площа Немо': 'Nemo Square',
    'Парк': 'Park', 'Парк зі ставком': 'Park with a pond', 'Сквер над тунелем': 'Garden over the tunnel',
    'Сквер подяки': 'Garden of Thanks', 'Сквер у дворі': 'Courtyard garden', 'Поле для свят': 'Festival field',
    'Оглядовий майданчик': 'Viewpoint', 'Майданчик відпочинку': 'Rest area',
    'Майданчик автосалону': 'Dealership lot', 'Паркінг': 'Parking', 'Стоянки': 'Parking',
    'Багаторівневий паркінг': 'Parking garage', 'Гравійна стоянка': 'Gravel parking',
    'Перехоплювальна стоянка': 'Park and ride', 'Лижна база': 'Ski center', 'Лижна хата': 'Ski hut',
    'Мисливська хата': 'Hunting lodge', 'Притулок на перевалі': 'Pass shelter',
    # --- transport -----------------------------------------------------------------------------------
    'Вокзал Немо': 'Nemo Station', 'Немо-Пасажирський': 'Nemo-Pasazhyrskyi', 'Автостанція': 'Bus station',
    'Автобусний парк': 'Bus depot', 'Трамвайне депо': 'Tram depot', 'Локомотивне депо': 'Locomotive depot',
    'Сортувальна': 'Marshalling yard', 'У депо': 'To the depot', 'Зупинки': 'Stops', 'Переходи': 'Crossings',
    'Підземний перехід': 'Pedestrian underpass', 'Підйомник': 'Ski lift', 'Пірс': 'Pier', 'Гавань': 'Harbor',
    # --- roads and streets ---------------------------------------------------------------------------
    'Кільцева (захід)': 'Ring Road (west)', 'Кільцева (південь)': 'Ring Road (south)',
    'Кільцева (північ)': 'Ring Road (north)', 'Кільцева (схід)': 'Ring Road (east)',
    'До оази': 'To the oasis', 'До південного берега': 'To the south shore', 'До станції': 'To the station',
    'Дорога крізь джунглі': 'Jungle Road', 'Дорога на плантацію': 'Plantation Road',
    'Дорога на полонину': 'Alpine Meadow Road', 'Дорога на столову гору': 'Mesa Road',
    'Перевальна дорога': 'Pass Road', 'Пустельне шосе': 'Desert Highway', 'Торфова дорога': 'Peat Road',
    'Лісовозна': 'Logging Road', 'Зимник': 'Winter road', 'Крижана дорога': 'Ice road', 'Гать': 'Corduroy road',
    'Збірна дорога': 'Collector road', 'Об’їзд': 'Detour', 'Об’їзд мостів': 'Bridge bypass',
    'Магістраль під мостом': 'Highway under the bridge', 'Вулиця над проїздами': 'Street over the underpasses',
    'Дослідна вулиця': 'Test Street', 'Північна вулиця': 'North Street', 'Пальмова вулиця': 'Palm Street',
    'Грузька вулиця': 'Boggy Street', 'Багнистий провулок': 'Muddy Lane', 'Котеджна': 'Cottage Street',
    'Курортна': 'Resort Street', 'Трамвайна': 'Tram Street', 'Тролейбусна': 'Trolleybus Street',
    'Набережна': 'Embankment', 'Над тунелем': 'Over the tunnel', 'Під мостом': 'Under the bridge',
    'Стежка крізь ліс': 'Forest trail', 'Стежка на гору Немо': 'Mount Nemo trail', 'Брід': 'Ford',
    'Точка Немо': 'Point Nemo', 'Лижна траса': 'Ski run', 'Спуск': 'Downhill run',
    # --- the tiles' subjects -------------------------------------------------------------------------
    'Інженерні споруди': 'Engineering structures', 'Визначні споруди': 'Landmarks',
    'Ворота й шлагбауми': 'Gates and barriers', 'Дерева й живоплоти': 'Trees and hedges',
    'Дорожні знаки': 'Road signs', 'Камери, рами, відбійники': 'Cameras, gantries, guardrails',
    'Лавки, урни, дрібниці': 'Benches, bins and small things', 'Ліхтарі': 'Street lights',
    'Паркани й мури': 'Fences and walls', 'Стовпи й люки': 'Poles and manholes',
    'Точки інтересу': 'Points of interest', 'Студія, асфальт': 'Studio, asphalt', 'Студія, бетон': 'Studio, concrete',
    'Студія, плитка': 'Studio, paving', 'Колія хвилями': 'Wavy track', 'без тегів': 'no tags',
    'lanes=1 (спільна смуга)': 'lanes=1 (shared lane)',
    # --- nature --------------------------------------------------------------------------------------
    'Озеро': 'Lake', 'Гірське озеро': 'Mountain lake', 'Крижане озеро': 'Frozen lake', 'Ставок': 'Pond',
    'Водосховище': 'Reservoir', 'Канал': 'Canal', 'Затока': 'Bay', 'Коса': 'Spit', 'Острів': 'Island',
    'Острівець': 'Islet', 'Західний пляж': 'West Beach', 'Південний пляж': 'South Beach',
    'Міський пляж': 'City Beach', 'Галька': 'Pebbles', 'Північні скелі': 'North Cliffs', 'Струмок': 'Brook',
    'Струмок у трубі': 'Brook in a culvert', 'Потік': 'Torrent', 'Лівий рукав': 'Left channel',
    'Правий рукав': 'Right channel', 'Широка': 'Broad River', 'Двоє': 'Twin River',
    'Канал видів': 'Viewing Canal', 'Тиха': 'Quiet River', 'Грузька': 'Boggy River', 'Ваді': 'Wadi',
    'Оаза': 'Oasis', 'Дюни': 'Dunes', 'Столова гора': 'Mesa', 'Перевал': 'Pass', 'Перевал Немо': 'Nemo Pass',
    'Полонина': 'Alpine meadow', 'Льодовик Немо': 'Nemo Glacier', 'Лижна гора': 'Ski hill',
    'Велике болото': 'Great Marsh', 'Торфовище': 'Peat bog', 'Мангри': 'Mangroves',
    'Дощовий ліс': 'Rainforest', 'Тайга': 'Taiga', 'Старий ліс': 'Old forest',
    'Ліс за річкою': 'Forest across the river', 'Вирубка': 'Clearcut', 'Лісосіка': 'Logging area',
    'Оленяча огорожа': 'Deer fence', 'Кар’єр': 'Quarry',
    # --- the bridges' and the relief's subjects (lower case: after a tile's code) -------------------
    'арки крізь будинки': 'arches through houses', 'арковий міст і ферма': 'arch bridge and truss',
    'балковий міст і віадук': 'beam bridge and viaduct', 'бездоріжжя': 'off-road',
    'болото й очерет': 'swamp and reeds', 'бічна': 'side street', 'велике кільце': 'large roundabout',
    'високий віадук, чотири частини': 'tall viaduct, four parts', 'висячий і вантовий': 'suspension and cable-stayed',
    'водосховище й басейни': 'reservoir and basins', 'вузька колія й депо': 'narrow gauge and depot',
    'віадук на косогорі': 'viaduct on a hillside', 'віадук над долиною': 'viaduct over a valley',
    'галерея на схилі й крита дорога': 'slope gallery and covered road', 'гребенем': 'along the ridge',
    'два мости поруч': 'two bridges side by side', 'дном долини': 'along the valley floor',
    'довга арка': 'long arch', 'довгий тунель, чотири частини, у кривій': 'long tunnel, four parts, on a curve',
    'дорога над колією': 'road over the railway', 'другий міст': 'second bridge',
    'з мосту в тунель': 'from a bridge into a tunnel', 'задня': 'back street', 'зебри': 'zebra crossings',
    'зміщене': 'offset', 'коло бездоріжжям': 'off-road loop', 'колія над дорогою': 'railway over the road',
    'косогір 20 %': 'side slope 20 %', 'кільце': 'roundabout', 'мости для людей': 'footbridges',
    'міні-кільце': 'mini roundabout', 'міст між берегами різної висоти': 'bridge between banks of different heights',
    'міст у кривій, навскіс': 'skewed bridge on a curve', 'міст через заплаву, три частини': 'floodplain bridge, three parts',
    'міст через канал': 'bridge over a canal', 'міст через острів, дві частини': 'bridge across an island, two parts',
    'міст через річку': 'bridge over a river', 'міст із з’їздами': 'bridge with ramps',
    'місток через струмок': 'small bridge over a brook', 'набережна': 'embankment', 'низом': 'low road',
    'озеро й ставок': 'lake and pond', 'паралельна': 'parallel street', 'переїзд': 'level crossing',
    'переїзд, одна колія': 'level crossing, one track', 'проїзд': 'underpass', 'проїзд 16 м': 'underpass, 16 m',
    'проїзд під вулицею, 30 м': 'underpass below a street, 30 m',
    'проїзд під насипом колії': 'underpass below a railway embankment',
    'під колією без насипу': 'under a railway without an embankment', 'під кутом': 'at an angle',
    'п’ятий': 'fifth leg', 'розвідний і критий': 'bascule and covered', 'світлофор': 'traffic lights',
    'середня': 'middle street', 'середній рівень': 'middle level', 'серпантин': 'switchbacks',
    'серпантин і кар’єр': 'switchbacks and quarry', 'станція, дві колії': 'station, two tracks',
    'струмок у трубі': 'brook in a culvert', 'студія: рівні майданчики': 'studio: level lots',
    'сходинками DEM': 'DEM in steps', 'терасами': 'in terraces', 'тераси й цілі метри DEM': 'terraces and whole DEM metres',
    'трамвай у дорозі': 'tram in the road', 'три рівні': 'three levels',
    'труба, підземний перехід, брід': 'culvert, underpass, ford', 'тунель': 'tunnel',
    'тунель під рівною землею': 'tunnel under flat ground', 'тунель під річкою': 'tunnel under a river',
    'тунель під хребтом': 'tunnel under a ridge', 'угору, 20 %': 'uphill, 20 %', 'униз, 20 %': 'downhill, 20 %',
    'хвилі: виїмки й насипи': 'waves: cuts and fills', 'через перевал': 'over the pass',
    'шляхопровід над вулицею': 'overpass over a street', 'шляхопровід над колією': 'overpass over a railway',
    'шляхопровід над магістраллю': 'overpass over a highway',
}

# a word and a number or an OSM value after it
LOTS = {'Двір': 'Yard', 'Майданчик': 'Lot', 'Площа': 'Square', 'Стоянка': 'Parking'}
PATTERNS = (
    (re.compile(r'^(Двір|Майданчик|Площа|Стоянка) ([a-z_:]+)$'), lambda m: f'{LOTS[m[1]]} {m[2]}'),
    (re.compile(r'^Зупинка (\S+)$'), lambda m: f'Stop {m[1]}'),
    (re.compile(r'^До кільцевої, ряд (\d+)$'), lambda m: f'To the ring road, row {m[1]}'),
    (re.compile(r'^Ряд (\d+)$'), lambda m: f'Row {m[1]}'),
    (re.compile(r'^Модуль (\d+)$'), lambda m: f'Module {m[1]}'),
    (re.compile(r'^Платформа (\d+)$'), lambda m: f'Platform {m[1]}'),
    (re.compile(r'^Провулок (\d+)$'), lambda m: f'Lane {m[1]}'),
    (re.compile(r'^провулок (\d+)$'), lambda m: f'lane {m[1]}'),
    (re.compile(r'^ухил (\d+) %$'), lambda m: f'grade {m[1]} %'),
    (re.compile(r'^ґрунтова, (\d+) %$'), lambda m: f'dirt road, {m[1]} %'),
    (re.compile(r'^Вітка (\S+)$'), lambda m: f'Spur {m[1]}'),
    (re.compile(r'^Колія (\S+)$'), lambda m: f'Track {m[1]}'),
)


def english(text):
    """text in English, text itself when it has no Cyrillic, None when nothing here reads it."""
    if not isinstance(text, str) or not CYRILLIC.search(text):
        return text
    hit = NAMES.get(text)
    if hit:
        return hit
    m = CODE.match(text)
    if m:
        rest = english(m[2])
        return f'{m[1]} {rest}' if rest else None
    for pattern, make in PATTERNS:
        m = pattern.match(text)
        if m:
            return make(m)
    if ' · ' in text:
        parts = [english(p) for p in text.split(' · ')]
        if all(parts):
            return ' · '.join(parts)
    return None


def missing(tags):
    """The (key, value) pairs of tags a player reads in Ukrainian with no English form."""
    return [(k, v) for k in KEYS if (v := tags.get(k)) and CYRILLIC.search(v)
            and not tags.get(k + ':en') and english(v) is None]


def add_english(plan):
    """name:en (and the other KEYS) for every point, way and relation of the plan whose value is
    Cyrillic and has no English form yet, and every tile's titleEn."""
    def fill(tags):
        for key in KEYS:
            v = tags.get(key)
            if v and CYRILLIC.search(v) and not tags.get(key + ':en'):
                en = english(v)
                if en:
                    tags[key + ':en'] = en
    for p in plan.points:
        fill(p[2])
    for w in plan.ways:
        fill(w[1])
    for r in plan.relations:
        fill(r[1])
    for t in plan.tiles.values():
        if not t.get('titleEn'):
            en = english(t['title'])
            if en and en != t['title']:
                t['titleEn'] = en
