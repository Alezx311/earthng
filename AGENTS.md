# EarthNG: агенти

Мета роботи в цьому репозиторії: нативний мод BeamNG.drive, у якому реальне місце виглядає наповненим і на ньому можна їздити. За містом природа має бути не біднішою за BeamNG.Earth. У місті менше дерев і більше трави, вулиці заставлені стоковими моделями гри. Щільність не має валити кадр. Відповідати користувачу українською.

## Що вже є конвеєр

Три частини, одна гілка `master`:

- **Планета** (`earthng_planet.zip`, збирає `earthng/build_mod.py` з `mod/`) тримає Lua, спільний арт, офлайн-мапу й правила. Під час гри `mod/lua/ge/extensions/e2r/generator.lua` будує тайл навколо авто, `native.lua` планує тайли, `world.lua` веде сцену, колізію й навграф. Трафік без фізики — `flow.lua` і `handoff.lua`, пішоходи — `walkers.lua` і `pedhit.lua`; машини потоку й пішоходи — копії в `DynamicShapeBatch` (`shapebatch.lua`, TSStatic у 0.39). Світлофори — `signals.lua`, маршрут — `routing.lua` і `navigator.lua`, рядок місця — `location.lua`. Клімат читає `biome.lua`, бюджети задає `quality.lua`.
- **Пак країни** (`earthng_<id>.zip`) тримає компактні факти OSM і висоти, не готові міста. Збирає Python-конвеєр `earthng/` (`country_fetch.py` → `osm_tiles_country.py` → `fast_sources.py` → `build_country.py`, класи — `fast_style.py`). Важкі етапи (нарізка, індекс, клітинки, сцени, маршрути, `Map detail`) мають нативну копію в `rust/` (`earthng-mapbuilder.exe`, `earthng_native.dll`), яка пише ті самі байти; `EARTHNG_NATIVE=0` вимикає її.
- **EarthNG.exe** (`rust/crates/app` + сторінка `app/ui/` + сервіс `earthng/app_service.py`) — вікно для гравця: вбудований Python, вибір області, збірка й встановлення пака разом із планетою. Runtime для exe збирає `earthng/prepare_app.py`.

Нове наповнення розширює генератор і спільну маску зайнятого місця. Окремий сервер, статичний експорт міста чи другий рендер доріг не додавати.

Стокові меші й текстури гри лишаються в установці гравця. Мод посилається на них через VFS і не копіює їх у ZIP.

## Перед правкою

В Obsidian відкрий `EarthNG/Документація.md`. Внутрішні документи з історії, планування, правил генерації та перевірок ведемо в `C:/Users/Alezx311/Documents/Obsidian Vault/EarthNG/Knowledge/`. Шляхи на кшталт `docs/FAR_VIEW.md` у коментарях і старих звітах відповідають тим самим шляхам відносно `Knowledge/`. Публічні посібники в Git перелічені в [docs/README.md](docs/README.md). Знімок документації до перенесення є в коміті `d45f2d1`.

Для пошуку зв’язків між кодом і нотатками з кореня репозиторію запускай `graphify query "<питання>"`. Граф і звіт лежать у `graphify-out/`. Як оновити граф, описано в розділі Graphify нотатки `EarthNG/Документація.md`.

Перед зміною вигляду землі, доріг, узбіч або будівель прочитати `Knowledge/docs/REAL_MAP_RULES.md` у vault. Поточна робота над реалістичністю стосується лише паку `real`; інші паки не змінювати, зокрема через спільні матеріали та геометрію.

Наповнення світу: у `Knowledge/docs/` прочитати `GENERATION_GAPS.md` і один профільний документ: `NATURE.md`, `CITY_DETAIL.md`, `VENUES.md`, `SIGNS.md` або `PERFORMANCE.md`. Історичні числа в `PERFORMANCE.md` і `STREET_PROPS.md` не є поточним бюджетом. Бюджет брати з коду (`quality.lua`, генератор) і зі свіжого заміру.

Збирач паків і exe: `docs/MAPBUILDER_RS.md` (нативні етапи і правило «ті самі байти») і `docs/MAPBUILDER_APP.md` (exe, протокол сторінки, джерело тайлів).

## Скіли

Скіли лежать у теках агентів: `.claude/skills/` (Claude Code), `.agents/skills/` (Codex, Cursor, Copilot), `.grok/skills/` (Grok). Якщо модель не бачить скіл у своїй теці, вона читає `SKILL.md` за шляхом нижче, коли задача підпадає під його опис.

- `earthng-world` (`.grok/skills/earthng-world/SKILL.md`) — процедура зміни світу: наповнення, шари, маска зайнятого місця, бюджет кадру.
- `beamng-mods` (у всіх трьох теках) — Lua-моддинг BeamNG і BeamMP: розширення GE і vehicle, `extensions.load`, події клієнт-сервер. В EarthNG ціль завжди `beamng-only`: GE-розширення в `mod/lua/ge/extensions/e2r/`. BeamMP мод не використовує, тож уточнювати ціль не треба. `references/` і `examples/` скіла — короткі шпаргалки; де вони розходяться з грою, правду кажуть встановлена гра і «Зовнішні інструкції». Де скіл розходиться з цим файлом або з `earthng-world` (формат звіту, перевірка), діють правила EarthNG.

`beamng-mods` поставлено з `aaronflorey/agent-skills` командою `npx skills add aaronflorey/agent-skills --skill beamng-mods --agent claude-code codex grok --copy`; джерело й коміт записано в `skills-lock.json`. Копії вручну не правити: оновлення — `npx skills update beamng-mods`, після нього три теки мають лишитись однаковими.

## Зовнішні інструкції

Офіційна документація неповна. Для формату рівня джерело правди — встановлена гра і ці сторінки:

- Огляд створення рівня, теки `levels/<map>/main` і `art`: https://documentation.beamng.com/modding/levels/level_creation/section1/
- Формати рівня, ліс, декалі, prefab: https://documentation.beamng.com/modding/levels/level_formats/
- Спільна тека `assets/` і файли `.link` (з 0.37): https://documentation.beamng.com/modding/levels/assets/
- Пакування ZIP, кореневі теки `levels`, `art`, `lua`: https://documentation.beamng.com/modding/mod-support/mod_packing
- Lua-розширення: https://documentation.beamng.com/modding/programming/extensions
- Формати файлів (`.dae`, `.materials.json`, `.prefab`): https://documentation.beamng.com/modding/file_formats/

Чужі репозиторії читати як довідку. Не клонувати їх сюди і не замінювати ними генератор.

| Джерело | Брати | Не брати |
| --- | --- | --- |
| [Rc-Cookie/Unofficial-BeamNG.drive-Lua-Documentation](https://github.com/Rc-Cookie/Unofficial-BeamNG.drive-Lua-Documentation) | Неофіційні заглушки Lua для редактора. Багато про віртуальну машину рушія, мало про авто. | Повноту API. Збірка незакінчена. |
| [nikkiluzader/mapng](https://github.com/nikkiluzader/mapng) | Як зі стокових фасадів, дахів, дерев і розмітки зібрати впізнаване місто з OSM. | Статичний ZIP рівня замість тайлового рантайму EarthNG. |
| [PrzemekWolw/BeamNGLevelImporter](https://github.com/PrzemekWolw/BeamNGLevelImporter) | Як офіційні міста розставлені в Blender: позиція, матеріали, масштаб. | Експорт чужих мешів у пак. |
| [Grille/BeamNG_LevelTemplateCreator](https://github.com/Grille/BeamNG_LevelTemplateCreator) | Стару схему тек і JSON-ассетів порожнього рівня. | Серіалізацію об'єктів. Її пише World Editor поточної версії гри. |
| [eric-rolph/beamng-mcp `AGENTS.md`](https://github.com/eric-rolph/beamng-mcp/blob/main/AGENTS.md) | Пастки інтерактивного пропа як транспортного засобу: подвійний рендер flexbody, застарілий `getRotation`. | Вуличні меблі. Їх EarthNG уже ставить через Forest. |
| [TecnaGamer/BeamNG.Earth](https://github.com/TecnaGamer/BeamNG.Earth) | Орієнтир вигляду природи поза містом. | Архітектуру. Це стримінг, не нативний мод. |
| `um kb search beamng` | Польові нотатки universal-modder. Зараз там один прохід Minecraft у BeamNG (WebSocket, `-enablemcp`). | Новий міст до гри. Оракул EarthNG — `earthng/test_world.py` і `earthng/probe.py`. |

## Перевірка

Юніт-тести: `.venv\Scripts\python.exe -m unittest discover -s earthng -p "test_*.py"` або вужчий `-p`. Якщо в `.venv` немає `lupa.luajit21`, тест із цим імпортом запустити тим інтерпретатором, де імпорт уже працює, і назвати його у звіті.

Rust: `cargo test --release` у `rust/`. Тести нативних етапів у Python (`test_native_tool`) пропускаються, якщо `cargo build --release` ще не запускали. Зміна функції, яку дзеркалить Rust, ламає `test_rules_fingerprint`: перенести зміну в Rust або назвати розбіжність.

Гра: один процес, окремий профіль `earthng/test_world.py`. Живу теку `mods`, на яку вказує локальний `launcher.json`, не перезаписувати, поки користувач не попросив встановити планету. Паки країн у живій теці не замінювати збіркою планети.

Полігон: `earthng/proving_ground.py` збирає пак `earthng_polygon.zip` — вигаданий острів у точці Немо, де кожен тайл 500 м показує одну тему (класи доріг, покриття, забудова, рельєф тощо) і має свої камери. Параметри генератора для світу або окремого тайла міняє `lab.lua` з вкладки «EarthNG» у меню паузи. Довкола основної сітки острова лежать п'ять всесвітів (гори, пустеля, сніг, багно, джунглі): `universe.lua` задає кожному клімат, регіон асетів, підміну матеріалів, фізику ґрунту й зону рослинності, а кожен блок будує вибірку тем основної сітки. Що з чого зібрано в тайлі, без гри показує `earthng/universe_census.py`; з `--flora data/flora/all --plants` він рахує рослини тайла за видами.

Вода: берегову лінію, тип берега й профіль дна задає `shore.lua`, а `generator.lua` (`WATER.shape`, `WATER.banks`, `WATER.fill`) за ним формує ґратку землі, малює смуги берега й ставить воду нижче за берег; вигляд води за погодою — `waterfx.lua`. Без гри воду тайлів пака з берегами й без них порівнює `earthng/shore_census.py` (карта, довжина краю блока на відкритій воді, час і сміття збірки; JIT з лімітами гри). У грі ті самі види берега за різної погоди знімає проба `earthng/probe/water_lab.lua` (сесія `test_world.py --manual --probe`): перепис не бачить ні прозорості мілкої води, ні зубців кромки на крутому березі.

Рослинність: правила порід і шарів — `flora.lua`, моделі — пак флори з FoliMesh (`earthng/build_flora.py`, рецепти `earthng/flora/*.json`). Моделі FoliMesh не комітити: ліцензія дозволяє їх лише в `data/` і в зібраному ZIP. Посібник — [docs/FLORA.md](docs/FLORA.md). Опис — `Knowledge/docs/PROVING_GROUND.md`.

Трафік і пішоходи: моделі без фізики зроблені через fal і лежать поза Git. `earthng/traffic_art.py --generate` робить джерела в `data/fal/traffic` (картинка → Tripo → для людей риг Meshy; платно, кожен виклик у `fal_manifest.jsonl`), `--build` запікає їх у `data/traffic-art/<VERSION>` (фарба машини як маска кольору копії, хода людини як вісім статичних поз, стійка, сидіння й дальня форма), а `build_mod.py` кладе запечене в планету; без нього планета збирається з намальованими формами `flow_art.py` і `people_art.py`. Аркуш для перевірки без гри: `--build --sheet <файл>`. Потік і підміну без гри міряє `earthng/flow_bench.py` (мс і сміття Lua на кадр), у грі — `earthng/traffic_ab.py`: той самий проліт маршрутом (`--replay`, підміна йде за камерою) з трафіком і без, у таблиці тайли, що запізнилися під камерою. Бюджети генератора й спавну задані на кадр, тож усе, що подовжує кадр, забирає тайли за секунду; ростити їх разом із кадром пробували, і стало гірше (кадр 36 → 41 мс) — допомагає лише дешевший кадр.

Копія в `DynamicShapeBatch` не кидає тіні (її немає в картах тіней), тому ближні машини потоку (до ~95 м) і ближні пішоходи (до ~38 м) — «тверді» копії: `TSStatic` із пулу (`shapebatch.lua`, `addSolid`), з тінню й нахилом на схилі; далі лишаються батчі. Збитий пішохід стає фізичним тілом своєї ж фігури: `traffic_art.py` запікає для кожної вузли скелета за її суглобами й сітку, розрізану по кістках, а `ped_body.py` пише з цього машину `e2r_<фігура>` (маса людини, «тканини» з обмеженням суглобів, трикутники колізії). Швидкість тілу дає лише удар машини: руками нічого не додається (`pedhit.lua`). Плями крові малює `blood_art.py` (без платних викликів): на землі це динамічні декалі рушія (`world.lua` `BLOOD.stain`), на стіні й на машині — вирізані квадрати. Збиття покадрово знімає проба `earthng/probe/ped_hit.lua` (сесія `test_world.py --manual --probe --walkers N`), аркуш із кадрів складає `earthng/probe/strip.py`.

Власна бібліотека поверхонь: `earthng/own_art.py` робить через fal (PATINA, платно, лише з `--generate`) набори в одному стилі й кладе їх у бібліотеку текстур поруч із CC0 (`data/textures/own_*/albedo.jpg, normal.jpg, …`, поза Git; виклики — у `data/textures/own/fal_manifest.jsonl`). Набори землі підміняють фото в аркушах відкритої землі (`fast_photo.own`), стіни й дахи стають аркушами `sh_o_*` і видами `clad_o_*`, `roof_o_*`, `hw_bd_*`, `hw_limewash`, `hw_log`, `hw_shell` (`fast_style`), з яких генератор будує малі будівлі: `generator.lua` `BLD.small` дає гаражу, сараю, хатині, кіоску, теплиці й корівнику свої стіни, дах і його форму (плоский, односхилий, низький двосхилий), ряду гаражів — ворота різних фарб. Без наборів (`own_art.ready()`, `BLD.ownArt()`) усе малюється, як раніше. Колір землі згори: `earthng/ground_colour.py` рахує з композита Sentinel-2 медіанний колір кожного класу покриву зібраного пака (`earthng/ground_targets.json`), `fast_tone` доводить до нього ближню землю (`SATELLITE`), `far.lua` — плоскі класи далекого виду. Після зміни арту чи наборів перемірити середні карт: `earthng/tone_means.py`.

Хати за регіонами: одно- і двоповерховий будинок вдягає `houses.lua`. Стиль (`M.styles`) — це стіни, дахи, форми й нахил даху, вікна й двері, цоколь, димар, карниз і частка двоповерхових; регіон (`M.regions` за блоком вигляду, `M.countries` за паком) — список стилів, який може мати окремі списки для сухого, тропічного, середземноморського й холодного клімату (`biome.lua`). Два будинки з трьох беруть стиль своєї ділянки мапи (170 м), тому вулиця однорідна. Арт — `earthng/house_art.py`: через fal (PATINA і Nano Banana 2, платно, лише з `--generate`) 45 стін і 12 дахів у `data/textures/hs_*`, `hr_*` та 13 аркушів вікон і дверей у `data/textures/house` (поза Git, виклики — у `fal_manifest.jsonl` там само); сірі набори фарбуються видами (`PAINTS`), `TONE` доводить колір і рельєф. З цього `fast_facade.HOUSE_SHEETS`, види `hw_h_*`, `roof_h_*` у `fast_style`, атласи `house_cells`, `house_cells2` (окремий етап арту `house.version`) і згенерований `house_lib.lua` (клітинки атласів, метри на повтор; після зміни аркушів — `house_art.py --lua`). Без джерел (`house_art.ready()`) і в планеті без атласу (`houses.enabled`) хати малюються, як раніше; вимкнути в грі — `E2R_HOUSES = false` у консолі Lua й нова висадка. У лабораторії: «Хати за країною» і «Стиль усіх хат тайла»; серію кадрів одного місця в різних регіонах знімає проба `earthng/probe/houses_lab.lua`. Опис — `Knowledge/docs/HOUSES.md`.

Кадр і місце: назвати lat/lon, пресет якості і що змінилося в кадрі. Зелений тест без проїзду не закриває візуальний пропуск у `Knowledge/docs/GENERATION_GAPS.md` в Obsidian.

## Хто що робить

- `earthng-scout` читає код і документи, нічого не змінює.
- `earthng-author` міняє генератор, стилі й тести і не запускає гру.
- `earthng-runtime` єдиний запускає BeamNG і міряє.

Нові типи з `.grok/agents/` з'являються в наступній сесії. Не спавнити всіх трьох на дрібну правку. Скаут — коли невідомо, де правило. Рантайм — коли твердження про вигляд або кадр інакше не перевірити.

## Git

Гілка релізу — `master`. Пуш і тег лише за окремим проханням. Не комітити `data/`, `out/`, файли гри, розпаковані ассети BeamNG і секрети.
