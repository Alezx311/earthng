"""What a point of interest is: the types the world's info stands, wall plaques and the card by
the car speak of (docs/POI.md "Енциклопедія").

A pin's type is read from its OSM tags: the first of KEYS it has whose 'key=value' is in TYPES,
else its category's own ('cat:<e2r_cat>', fast_style.PIN_RULES), so a pack built before the
kind keys were kept still resolves by category. A type has a group (pins.lua's, its colour), a
pictogram (poi_art.MARKS), what stands for it in the world and its names; the ones a player
would drive to also carry two sentences of what such a thing is, in Ukrainian and English.

  look  'stand'   an info stand where the point is in the open, a plaque when it is in a building
        'plaque'  a plaque on its building's wall; in the open a stand, when it has a name
        'blade'   a pictogram sign hung from its building's wall, nothing in the open
        ''        nothing new in the world (it has its own object, sign or surface already: a named
            peak its cairn and plate, a station its board)
  bare  True: its stand is put up even when OSM has no name for it

poi_art.py writes this into mod/lua/ge/extensions/e2r/poi_lib.lua (--lua) and draws the marks.
"""

# the tag keys a type is looked up by, the most telling first
KEYS = ('memorial', 'artwork_type', 'information', 'tower:type', 'historic', 'tourism', 'natural', 'waterway',
        'mountain_pass', 'man_made', 'railway', 'aeroway', 'leisure', 'amenity', 'healthcare', 'highway', 'shop')

# group -> generator.lua YARD.cell name: the colour of its plates
GROUPS = {'sight': 'brown', 'nature': 'green', 'water': 'paint', 'transport': 'red', 'car': 'blue', 'shop': 'orange',
          'money': 'green', 'stay': 'dark', 'health': 'paint', 'civic': 'dark'}

TYPES = {}


def T(key, group, mark, look, uk, en, text_uk='', text_en='', bare=False):
    TYPES[key] = {'group': group, 'mark': mark, 'look': look, 'bare': bare, 'uk': uk, 'en': en,
                  'textUk': text_uk, 'textEn': text_en}


# --- nature -------------------------------------------------------------------------------------
T('natural=peak', 'nature', 'peak', '', 'Вершина', 'Peak',
  'Найвища точка гори або пагорба. Висоту рахують від рівня моря, а не від підніжжя, тому скромний на вигляд горб на '
  'плато може бути вищим за стрімку скелю біля берега.',
  'The highest point of a mountain or hill. Its height is counted from sea level, not from its foot, so a modest '
  'hump on a plateau can stand higher than a steep crag by the shore.')
T('natural=volcano', 'nature', 'volcano', '', 'Вулкан', 'Volcano',
  'Гора, складена з того, що колись вилилося або вилетіло з надр: лави, попелу, уламків. Згаслий вулкан упізнають за '
  'конусом і кратером на вершині.',
  'A mountain built of what once poured or was thrown out of the earth: lava, ash and rock. An extinct one is known '
  'by its cone and the crater at the top.')
T('mountain_pass=yes', 'nature', 'pass', 'stand', 'Перевал', 'Mountain pass',
  'Найнижче місце гірського хребта, де його найлегше перетнути. Дороги через гори майже завжди шукають саме перевал, '
  'тож тут здавна стояли застави, корчми й митниці.',
  'The lowest place on a ridge, where it is easiest to cross. Roads over mountains nearly always look for a pass, '
  'so guard posts, inns and customs houses have stood at them for centuries.')
T('natural=saddle', 'nature', 'pass', 'stand', 'Сідловина', 'Saddle',
  'Пониження між двома вершинами одного хребта. З одного боку від сідловини рельєф підіймається до вершин, з іншого '
  'спадає в долини.',
  'A dip between two summits of one ridge. Along the ridge the ground rises to the summits; across it, it falls '
  'away into the valleys.')
T('natural=spring', 'water', 'spring', 'stand', 'Джерело', 'Spring',
  'Місце, де підземна вода сама виходить на поверхню. Вода джерела пройшла крізь шари піску й каменю, тому зазвичай '
  'холодна й чиста; з таких джерел починаються струмки й річки.',
  'A place where groundwater comes to the surface by itself. It has passed through layers of sand and rock, so it '
  'is usually cold and clear; streams and rivers begin at springs like this.')
T('waterway=waterfall', 'water', 'waterfall', 'stand', 'Водоспад', 'Waterfall',
  'Річка падає з уступу там, де тверда порода змінюється м\'якшою: вода вимиває м\'яку швидше. Через це водоспад '
  'повільно відступає вгору за течією, лишаючи по собі ущелину.',
  'A river drops off a ledge where hard rock gives way to softer rock, which the water wears away faster. So a '
  'waterfall slowly retreats upstream and leaves a gorge behind it.', bare=True)
T('natural=cave_entrance', 'nature', 'cave', 'stand', 'Печера', 'Cave',
  'Порожнина в скелі, найчастіше вимита водою у вапняку чи гіпсі. У глибині печери цілий рік тримається майже та сама '
  'температура — середня річна для цієї місцевості.',
  'A hollow in the rock, most often dissolved by water in limestone or gypsum. Deep inside, the temperature stays '
  'nearly the same all year: the yearly mean of the place.', bare=True)
T('natural=rock', 'nature', 'rock', 'stand', 'Скеля', 'Rock',
  'Вихід корінної породи на поверхню. Скелі лишаються там, де м\'якші шари довкола вже зруйнували вода, мороз і вітер.',
  'Bedrock standing out of the ground. A rock remains where water, frost and wind have already worn the softer '
  'layers around it away.')
T('natural=stone', 'nature', 'rock', 'stand', 'Брила', 'Boulder',
  'Окремий великий камінь. Чимало таких брил принесли льодовики: камінь може лежати за сотні кілометрів від скель, '
  'від яких відколовся.',
  'A single large stone. Many were carried by glaciers: a boulder may lie hundreds of kilometres from the rock it '
  'broke off.')
T('tourism=viewpoint', 'sight', 'view', 'stand', 'Оглядовий майданчик', 'Viewpoint',
  'Місце, з якого відкривається далекий краєвид. За ясної погоди з висоти 100 метрів над рівниною обрій лежить '
  'приблизно за 36 кілометрів.',
  'A place with a far view. On a clear day, from 100 metres above a plain the horizon lies about 36 kilometres away.',
  bare=True)

# --- sights -------------------------------------------------------------------------------------
T('historic=castle', 'sight', 'castle', 'stand', 'Замок', 'Castle',
  'Укріплене житло володаря: мури, вежі й брама захищали і господаря, і округу. Замки ставили там, де сама місцевість '
  'допомагала оборонятися, — на скелі, пагорбі чи в закруті річки.',
  'The fortified home of a lord: its walls, towers and gate guarded both him and the land around. Castles were built '
  'where the ground itself helped the defence: on a rock, a hill or in a river bend.', bare=True)
T('historic=fort', 'sight', 'castle', 'stand', 'Фортеця', 'Fort',
  'Військове укріплення без палацу всередині. Низькі товсті вали й кутасті бастіони з\'явилися разом з гарматами: '
  'високий мур ядро пробивало, а земляний вал — ні.',
  'A military stronghold with no palace inside. Low thick ramparts and angled bastions came with the cannon: a ball '
  'broke a high wall but not a bank of earth.', bare=True)
T('historic=city_gate', 'sight', 'gate', 'stand', 'Міська брама', 'City gate',
  'В\'їзд у місто крізь оборонний мур. На ніч браму зачиняли, а вдень біля неї брали мито з возів; нерідко брама — '
  'усе, що лишилося від міських мурів.',
  'The way into a town through its wall. It was shut for the night, and by day tolls were taken from the carts; '
  'often the gate is all that is left of the town walls.', bare=True)
T('historic=manor', 'sight', 'manor', 'stand', 'Садиба', 'Manor',
  'Панський будинок із парком, службами й господарським двором. Садиба була центром маєтку: звідси керували землями '
  'й селами довкола.',
  'A landowner\'s house with its park, outbuildings and farmyard. The manor was the heart of an estate: the lands and '
  'villages around were run from here.')
T('historic=ruins', 'sight', 'ruins', 'stand', 'Руїни', 'Ruins',
  'Залишки споруди, яку більше не відбудовували. За товщиною мурів, кладкою й обрисами фундаментів історики відновлюють, '
  'якою будівля була і коли її звели.',
  'What is left of a building nobody rebuilt. From the thickness of the walls, the masonry and the lines of the '
  'foundations, historians work out what it was and when it was built.', bare=True)
T('historic=archaeological_site', 'sight', 'dig', 'stand', 'Археологічна пам\'ятка', 'Archaeological site',
  'Місце, де в землі збереглися сліди давнього життя: вали городища, кургани, фундаменти. Більшість знахідок лежить '
  'неглибоко, тому такі місця охороняє закон.',
  'A place where the ground keeps traces of ancient life: the banks of a hillfort, burial mounds, foundations. Most '
  'finds lie shallow, so such places are protected by law.', bare=True)
T('historic=building', 'sight', 'manor', 'plaque', 'Історична будівля', 'Historic building',
  'Будівля, цінна своїм віком, архітектурою чи подіями, які в ній відбулися.',
  'A building valued for its age, its architecture or what happened in it.')
T('historic=monument', 'sight', 'monument', 'stand', 'Пам\'ятник', 'Monument',
  'Споруда на честь людини чи події, зведена так, щоб її було видно здалеку. Постамент піднімає фігуру над вулицею '
  'й відділяє її від буденного.',
  'A structure raised to honour a person or an event, built to be seen from afar. The pedestal lifts the figure '
  'above the street and sets it apart from the everyday.')
T('historic=memorial', 'sight', 'memorial', 'stand', 'Меморіал', 'Memorial',
  'Знак пам\'яті про людей чи подію. На відміну від великого пам\'ятника, меморіал може бути скромним: камінь, дошка, '
  'хрест або стела з іменами.',
  'A mark of remembrance of people or an event. Unlike a great monument, a memorial may be modest: a stone, a '
  'plaque, a cross or a slab of names.')
T('memorial=war_memorial', 'sight', 'memorial', 'stand', 'Воєнний меморіал', 'War memorial',
  'Пам\'ять про загиблих на війні. Такі меморіали стоять майже в кожному селі й місті: на плитах — імена місцевих '
  'жителів, які не повернулися.',
  'In memory of those killed in war. Nearly every village and town has one: its slabs carry the names of the local '
  'people who did not come back.')
T('memorial=statue', 'sight', 'statue', 'stand', 'Статуя', 'Statue',
  'Скульптура людини на повен зріст. Бронзову статую відливають порожньою, зі стінками завтовшки в палець, інакше '
  'вона важила б у кілька разів більше.',
  'A full-length sculpture of a person. A bronze statue is cast hollow, its walls a finger thick; solid, it would '
  'weigh several times as much.')
T('memorial=bust', 'sight', 'bust', 'stand', 'Погруддя', 'Bust',
  'Скульптурний портрет: голова й плечі на постаменті. Форма прийшла з античного Риму, де так зберігали портрети предків.',
  'A sculpted portrait: head and shoulders on a pedestal. The form comes from ancient Rome, where portraits of '
  'ancestors were kept this way.')
T('memorial=plaque', 'sight', 'plaque', 'plaque', 'Меморіальна дошка', 'Memorial plaque',
  'Дошка на стіні будинку, де жила чи працювала відома людина або сталася важлива подія.',
  'A plaque on the wall of a house where a notable person lived or worked, or where something important happened.')
T('memorial=stone', 'sight', 'memorial', 'stand', 'Пам\'ятний камінь', 'Memorial stone',
  'Камінь із написом на місці події або майбутнього пам\'ятника.',
  'An inscribed stone at the place of an event, or where a monument is to stand.')
T('memorial=obelisk', 'sight', 'monument', 'stand', 'Обеліск', 'Obelisk',
  'Чотиригранний стовп, що звужується догори. Перші обеліски ставили єгиптяни перед храмами; відтоді це найпростіший '
  'спосіб позначити місце на віки.',
  'A four-sided pillar tapering to its top. The Egyptians raised the first before their temples; ever since it has '
  'been the plainest way to mark a place for centuries.')
T('man_made=obelisk', 'sight', 'monument', 'stand', 'Обеліск', 'Obelisk',
  TYPES['memorial=obelisk']['textUk'], TYPES['memorial=obelisk']['textEn'])
T('memorial=stele', 'sight', 'monument', 'stand', 'Стела', 'Stele',
  'Вертикальна плита з написом чи рельєфом.', 'An upright slab with an inscription or a relief.')
T('memorial=cross', 'sight', 'cross', 'stand', 'Пам\'ятний хрест', 'Memorial cross',
  'Хрест на згадку про людей чи подію.', 'A cross in memory of people or an event.')
T('memorial=tank', 'sight', 'tank', 'stand', 'Танк на постаменті', 'Tank memorial',
  'Справжня бойова машина, поставлена на постамент як пам\'ятник. Найчастіше це танк, який першим увійшов у місто.',
  'A real fighting vehicle set on a pedestal as a monument, most often the tank that was first to enter the town.')
T('memorial=aircraft', 'sight', 'plane', 'stand', 'Літак на постаменті', 'Aircraft memorial',
  'Справжній літак, піднятий на постамент — зазвичай біля аеродрому чи льотного училища.',
  'A real aircraft raised on a pedestal, usually by an airfield or a flying school.')
T('memorial=locomotive', 'sight', 'locomotive', 'stand', 'Паровоз-пам\'ятник', 'Locomotive memorial',
  'Паровоз, що відпрацював своє і став пам\'ятником біля станції чи депо.',
  'A steam engine that has done its work and stands as a monument by a station or a depot.')
for _key, _like in (('historic=tank', 'memorial=tank'), ('historic=aircraft', 'memorial=aircraft'),
                    ('historic=locomotive', 'memorial=locomotive')):
    TYPES[_key] = dict(TYPES[_like])
T('historic=wayside_cross', 'sight', 'cross', '', 'Придорожній хрест', 'Wayside cross',
  'Хрест при дорозі, на роздоріжжі чи на краю села. Їх ставили як оберіг громади, на подяку або на згадку; подорожні '
  'звірялися з ними, як з дороговказами.',
  'A cross by a road, at a fork or at the edge of a village. They were raised to guard the community, in thanks or '
  'in memory, and travellers took their bearings from them.')
T('man_made=cross', 'sight', 'cross', '', 'Хрест', 'Cross',
  TYPES['historic=wayside_cross']['textUk'], TYPES['historic=wayside_cross']['textEn'])
T('historic=wayside_shrine', 'sight', 'shrine', '', 'Капличка', 'Wayside shrine',
  'Мала споруда з образом чи фігурою святого при дорозі. Не храм: у ній не служать, біля неї зупиняються на хвилину.',
  'A small structure by a road with the image or figure of a saint. Not a church: no service is held in it, people '
  'stop by it for a minute.')
T('man_made=windmill', 'sight', 'windmill', 'stand', 'Вітряк', 'Windmill',
  'Млин, жорна якого крутить вітер. Щоб ловити його з будь-якого боку, корпус або самий дах повертали довгим дишлом '
  'назустріч вітру.',
  'A mill whose stones are turned by the wind. To catch it from any side, the whole body or just the cap was turned '
  'into the wind by a long tail pole.', bare=True)
T('man_made=lighthouse', 'sight', 'lighthouse', 'stand', 'Маяк', 'Lighthouse',
  'Вежа зі світлом, що показує кораблям берег і небезпеку. Кожен маяк блимає у власному ритмі, тож уночі моряк '
  'упізнає його за самими спалахами.',
  'A tower with a light that shows ships the shore and its dangers. Every lighthouse flashes in a rhythm of its own, '
  'so at night a sailor knows it by the flashes alone.', bare=True)
T('man_made=water_tower', 'sight', 'tower', 'stand', 'Водонапірна вежа', 'Water tower',
  'Бак з водою, піднятий високо над землею. Вода з нього тече в труби власною вагою, тому тиск у мережі тримається '
  'навіть тоді, коли насоси стоять.',
  'A tank of water raised high above the ground. The water runs into the mains by its own weight, so the pressure '
  'holds even while the pumps stand still.')
T('tourism=museum', 'sight', 'museum', 'plaque', 'Музей', 'Museum',
  'Місце, де речі зберігають, досліджують і показують. У залах зазвичай виставлено лише малу частку зібрання: решта '
  'лежить у сховищах.',
  'A place where things are kept, studied and shown. The halls usually display only a small share of the collection; '
  'the rest lies in the stores.')
T('tourism=gallery', 'sight', 'frame', 'plaque', 'Галерея', 'Gallery',
  'Простір для виставок мистецтва. На відміну від музею, виставки тут змінюються, а роботи часто можна купити.',
  'A space for art exhibitions. Unlike a museum, its shows change, and the works can often be bought.')
T('tourism=artwork', 'sight', 'sculpture', 'stand', 'Мистецький об\'єкт', 'Artwork',
  'Твір мистецтва просто неба: скульптура, інсталяція чи розпис.',
  'A work of art in the open: a sculpture, an installation or a painting.')
T('artwork_type=sculpture', 'sight', 'sculpture', 'stand', 'Скульптура', 'Sculpture',
  'Об\'ємний твір, який можна обійти довкола: з кожного боку він виглядає інакше.',
  'A work in three dimensions that can be walked around: it looks different from every side.')
T('artwork_type=statue', 'sight', 'statue', 'stand', 'Статуя', 'Statue',
  TYPES['memorial=statue']['textUk'], TYPES['memorial=statue']['textEn'])
T('artwork_type=bust', 'sight', 'bust', 'stand', 'Погруддя', 'Bust',
  TYPES['memorial=bust']['textUk'], TYPES['memorial=bust']['textEn'])
T('artwork_type=mural', 'sight', 'frame', 'plaque', 'Мурал', 'Mural',
  'Розпис на всю стіну будинку. Глуха торцева стіна багатоповерхівки — найбільше полотно, яке може дістатися художникові.',
  'A painting over the whole wall of a building. The blank end wall of a tower block is the largest canvas an '
  'artist can get.')
T('artwork_type=installation', 'sight', 'sculpture', 'stand', 'Інсталяція', 'Installation',
  'Мистецький об\'єкт, зібраний із різних речей і матеріалів для конкретного місця.',
  'An artwork put together of various things and materials for one particular place.')
T('tourism=attraction', 'sight', 'star', 'stand', 'Цікаве місце', 'Attraction',
  'Місце, заради якого сюди приїздять.', 'A place people come here to see.')
T('tourism=zoo', 'sight', 'paw', 'stand', 'Зоопарк', 'Zoo',
  'Парк, де тримають і показують тварин. Сучасні зоопарки ще й розводять рідкісні види, щоб повертати їх у природу.',
  'A park where animals are kept and shown. Modern zoos also breed rare species to return them to the wild.')
T('tourism=theme_park', 'sight', 'wheel', 'stand', 'Парк розваг', 'Theme park',
  'Парк з атракціонами. Оглядове колесо в ньому — найпростіший спосіб побачити місто згори.',
  'A park of rides. Its big wheel is the simplest way to see the town from above.')
T('tourism=aquarium', 'sight', 'fish', 'plaque', 'Акваріум', 'Aquarium',
  'Зібрання водних тварин і рослин за склом.', 'A collection of water animals and plants behind glass.')
T('tourism=information', 'sight', 'info', 'stand', 'Інформація', 'Information',
  'Стенд, мапа чи вказівник для подорожніх.', 'A board, a map or a guidepost for travellers.', bare=True)
T('information=guidepost', 'sight', 'info', '', 'Вказівник', 'Guidepost')
T('information=office', 'sight', 'info', 'blade', 'Туристичний центр', 'Tourist office')

# --- culture and civic places ---------------------------------------------------------------------
T('amenity=library', 'civic', 'book', 'plaque', 'Бібліотека', 'Library',
  'Зібрання книжок, відкрите для всіх. Книжки на полицях стоять за шифром, тому серед сотень тисяч томів потрібний '
  'знаходять за хвилину.',
  'A collection of books open to everyone. The books stand by shelf mark, so one volume among hundreds of thousands '
  'is found in a minute.')
T('amenity=community_centre', 'civic', 'museum', 'plaque', 'Будинок культури', 'Community centre',
  'Місце зборів громади: зала зі сценою, гуртки, свята.', 'Where a community meets: a hall with a stage, clubs, feasts.')
T('amenity=theatre', 'civic', 'masks', 'plaque', 'Театр', 'Theatre',
  'Будівля для вистав. Сцена театру набагато більша, ніж видно із зали: над нею й обабіч ховаються декорації всіх дій.',
  'A building for plays. Its stage is far larger than the hall can see: the sets of every act hide above it and to '
  'its sides.')
T('amenity=cinema', 'civic', 'film', 'plaque', 'Кінотеатр', 'Cinema',
  'Зала з великим екраном для показу фільмів.', 'A hall with a large screen for showing films.')
T('amenity=arts_centre', 'civic', 'frame', 'plaque', 'Центр мистецтв', 'Arts centre',
  'Виставки, майстерні й концерти під одним дахом.', 'Exhibitions, workshops and concerts under one roof.')
T('amenity=nightclub', 'civic', 'star', 'blade', 'Нічний клуб', 'Nightclub')
T('amenity=school', 'civic', 'cap', 'plaque', 'Школа', 'School')
T('amenity=kindergarten', 'civic', 'cap', 'plaque', 'Дитячий садок', 'Kindergarten')
T('amenity=college', 'civic', 'cap', 'plaque', 'Коледж', 'College')
T('amenity=university', 'civic', 'cap', 'plaque', 'Університет', 'University',
  'Вища школа, де водночас навчають і досліджують.', 'A school of higher learning that both teaches and does research.')
T('amenity=hospital', 'health', 'hospital', 'plaque', 'Лікарня', 'Hospital')
for _value, _uk, _en in (('clinic', 'Клініка', 'Clinic'), ('doctors', 'Лікар', 'Doctor'), ('dentist', 'Стоматологія', 'Dentist')):
    T('amenity=' + _value, 'health', 'plus', 'blade', _uk, _en)
T('healthcare=laboratory', 'health', 'plus', 'blade', 'Лабораторія', 'Laboratory')

# --- leisure ------------------------------------------------------------------------------------
T('leisure=park', 'nature', 'tree', 'stand', 'Парк', 'Park',
  'Зелена ділянка для відпочинку серед міста. Дерева парку помітно охолоджують повітря: влітку тут на кілька градусів '
  'прохолодніше, ніж на сусідній вулиці.',
  'Green ground for rest inside a town. Its trees cool the air noticeably: in summer it is a few degrees cooler here '
  'than in the next street.')
T('leisure=garden', 'nature', 'flower', 'stand', 'Сад', 'Garden',
  'Ділянка, де рослини вирощують заради краси, науки чи врожаю.', 'Ground where plants are grown for beauty, study or harvest.')
T('leisure=stadium', 'nature', 'stadium', 'stand', 'Стадіон', 'Stadium',
  'Спортивна арена з трибунами довкола поля. Овальна форма не випадкова: так найбільше глядачів сидить на однаковій '
  'відстані від гри.',
  'A sports ground with stands around the field. The oval is no accident: it seats the most people at the same '
  'distance from the game.')
T('leisure=sports_centre', 'nature', 'ball', 'plaque', 'Спортивний центр', 'Sports centre')
T('leisure=swimming_pool', 'water', 'waves', 'plaque', 'Басейн', 'Swimming pool')
T('leisure=fitness_centre', 'nature', 'ball', 'blade', 'Фітнес-центр', 'Fitness centre')
T('leisure=pitch', 'nature', 'ball', '', 'Спортивне поле', 'Pitch')
T('leisure=playground', 'nature', 'ball', '', 'Дитячий майданчик', 'Playground')

# --- transport ----------------------------------------------------------------------------------
T('railway=station', 'transport', 'train', '', 'Залізнична станція', 'Railway station',
  'Місце, де зупиняються поїзди. Ширина колії на більшості залізниць Європи — 1435 мм, в Україні й далі на схід — '
  '1520 мм, тому на кордоні вагонам міняють візки.',
  'Where trains stop. Most European railways run on a 1435 mm gauge, Ukraine and the lands to its east on 1520 mm, '
  'so carriages get new bogies at the border.')
T('railway=halt', 'transport', 'train', '', 'Зупинний пункт', 'Railway halt')
T('railway=subway_entrance', 'transport', 'metro', '', 'Вхід у метро', 'Metro entrance')
T('railway=tram_stop', 'transport', 'train', '', 'Трамвайна зупинка', 'Tram stop')
T('aeroway=aerodrome', 'transport', 'plane', 'stand', 'Аеродром', 'Airfield',
  'Поле зі злітною смугою. Смугу кладуть уздовж панівних вітрів: літаки злітають і сідають проти вітру, бо так '
  'розгін і пробіг коротші.',
  'A field with a runway. The runway lies along the prevailing winds: aircraft take off and land into the wind, '
  'which shortens both runs.')
T('aeroway=airstrip', 'transport', 'plane', 'stand', 'Злітна смуга', 'Airstrip',
  TYPES['aeroway=aerodrome']['textUk'], TYPES['aeroway=aerodrome']['textEn'])
T('amenity=ferry_terminal', 'transport', 'boat', 'stand', 'Поромна переправа', 'Ferry',
  'Причал, з якого пором перевозить людей і машини через воду там, де немає мосту.',
  'A landing from which a ferry carries people and cars over the water where there is no bridge.')
T('amenity=bus_station', 'transport', 'bus', 'plaque', 'Автостанція', 'Bus station')
T('highway=bus_stop', 'transport', 'bus', '', 'Автобусна зупинка', 'Bus stop')

# --- shops: a blade sign by what they sell ------------------------------------------------------------
SHOPS = {
    'bread': (('bakery', 'pastry', 'confectionery'), 'Пекарня', 'Bakery'),
    'knife': (('butcher', 'seafood', 'deli', 'cheese'), 'М\'ясо й делікатеси', 'Butcher and deli'),
    'hanger': (('clothes', 'shoes', 'fashion', 'boutique', 'fabric', 'tailor', 'bag', 'second_hand', 'charity'), 'Одяг і взуття', 'Clothes and shoes'),
    'flower': (('florist', 'garden_centre'), 'Квіти', 'Flowers'),
    'book': (('books', 'stationery', 'newsagent', 'copyshop'), 'Книги й канцтовари', 'Books and stationery'),
    'screen': (('electronics', 'mobile_phone', 'computer', 'hifi', 'photo'), 'Техніка', 'Electronics'),
    'scissors': (('hairdresser', 'beauty', 'massage', 'tattoo'), 'Краса', 'Hair and beauty'),
    'gem': (('jewelry', 'optician', 'watches'), 'Прикраси й оптика', 'Jewellery and optics'),
    'bottle': (('alcohol', 'wine', 'beverages', 'chemist', 'cosmetics', 'perfumery'), 'Напої та косметика', 'Drinks and cosmetics'),
    'paw': (('pet', 'pet_grooming'), 'Зоотовари', 'Pet shop'),
    'bike': (('bicycle', 'sports', 'outdoor', 'fishing', 'hunting'), 'Спорт і велосипеди', 'Sports and bikes'),
    'chair': (('furniture', 'houseware', 'interior_decoration', 'bed', 'kitchen', 'curtain', 'carpet'), 'Дім і меблі', 'Home and furniture'),
    'hammer': (('doityourself', 'hardware', 'paint', 'trade', 'agrarian', 'electrical', 'tiles'), 'Будматеріали', 'Hardware'),
    'toy': (('toys', 'gift', 'games', 'baby_goods', 'variety_store', 'art', 'craft', 'music'), 'Іграшки й подарунки', 'Toys and gifts'),
}
for _mark, (_values, _uk, _en) in SHOPS.items():
    for _value in _values:
        T('shop=' + _value, 'shop', _mark, 'blade', _uk, _en)
# what wears a sign of its own already (retail.py's shops and services): no second sign
for _value in ('supermarket', 'convenience', 'grocery', 'general', 'food', 'greengrocer', 'kiosk', 'car', 'car_parts',
               'car_repair', 'tyres', 'motorcycle', 'vacant'):
    T('shop=' + _value, 'shop', 'bag', '', 'Магазин', 'Shop')
T('shop=mall', 'shop', 'bag', 'plaque', 'Торговий центр', 'Shopping centre')
T('shop=department_store', 'shop', 'bag', 'plaque', 'Універмаг', 'Department store')

# --- a category's own type: what a pin is when no key tells more (every PIN_RULES category) -----------
CATEGORY = {
    'peak': 'natural=peak', 'pass': 'mountain_pass=yes', 'spring': 'natural=spring', 'waterfall': 'waterway=waterfall',
    'cave': 'natural=cave_entrance', 'rock': 'natural=rock', 'viewpoint': 'tourism=viewpoint', 'castle': 'historic=castle',
    'monument': 'historic=monument', 'cross': 'historic=wayside_cross', 'shrine': 'historic=wayside_shrine',
    'windmill': 'man_made=windmill', 'lighthouse': 'man_made=lighthouse', 'water_tower': 'man_made=water_tower',
    'library': 'amenity=library', 'culture': 'amenity=community_centre', 'hospital': 'amenity=hospital',
    'school': 'amenity=school', 'clinic': 'amenity=clinic', 'station': 'railway=station', 'metro': 'railway=subway_entrance',
    'tram_stop': 'railway=tram_stop', 'airfield': 'aeroway=aerodrome', 'ferry': 'amenity=ferry_terminal',
    'mall': 'shop=mall', 'diy': 'shop=doityourself',
}
T('cat:sight', 'sight', 'star', 'plaque', 'Пам\'ятка', 'Sight', 'Місце, яке варто побачити.', 'A place worth seeing.')
T('cat:leisure_map', 'nature', 'tree', '', 'Відпочинок', 'Leisure')
T('cat:shop_map', 'shop', 'bag', 'blade', 'Магазин', 'Shop')
T('cat:well', 'water', 'spring', '', 'Криниця', 'Well',
  'Шахта, викопана до водоносного шару. Глибина криниці показує, як глибоко тут лежить ґрунтова вода: у долині це '
  'кілька метрів, на пагорбі — десятки.',
  'A shaft dug down to the water table. Its depth tells how deep the groundwater lies here: a few metres in a '
  'valley, tens of metres on a hill.')
for _cat, _group, _mark, _uk, _en in (
        ('parking', 'car', 'car', 'Парковка', 'Parking'), ('car_dealer', 'car', 'car', 'Автосалон', 'Car dealer'),
        ('car_parts', 'car', 'car', 'Автозапчастини', 'Car parts'), ('rest_area', 'car', 'car', 'Місце відпочинку', 'Rest area'),
        ('toilets', 'car', 'info', 'Туалет', 'Toilets'), ('hotel', 'stay', 'manor', 'Готель', 'Hotel'),
        ('motel', 'stay', 'manor', 'Мотель', 'Motel'), ('atm', 'money', 'info', 'Банкомат', 'ATM'),
        ('payment_terminal', 'money', 'info', 'Термінал', 'Payment terminal'), ('exchange', 'money', 'info', 'Обмін валют', 'Exchange'),
        ('kiosk', 'shop', 'bag', 'Кіоск', 'Kiosk'), ('coffee_vending', 'shop', 'bag', 'Кавовий автомат', 'Coffee machine'),
        ('water_vending', 'water', 'spring', 'Автомат з водою', 'Water machine'),
        ('drinking_water', 'water', 'spring', 'Питна вода', 'Drinking water'), ('picnic', 'sight', 'tree', 'Пікнік', 'Picnic'),
        ('food', 'shop', 'bag', 'Їжа', 'Food'), ('service_map', 'car', 'car', 'Сервіс', 'Service'),
        ('station_map', 'transport', 'bus', 'Зупинка', 'Stop'), ('parcel_locker', 'shop', 'bag', 'Поштомат', 'Parcel locker')):
    T('cat:' + _cat, _group, _mark, '', _uk, _en)


def marks():
    """The pictograms the types use, in a stable order: a mark's place in the atlas."""
    return sorted({t['mark'] for t in TYPES.values()})


def type_of(tags):
    """The TYPES key of a pin's tags (poi.lua typeOf mirrors this), or None."""
    for key in KEYS:
        value = tags.get(key)
        if value and f'{key}={value}' in TYPES:
            return f'{key}={value}'
    category = tags.get('e2r_cat')
    key = CATEGORY.get(category) or (f'cat:{category}' if category else None)
    return key if key in TYPES else None
