# EarthNG: агенти

Мета роботи в цьому репозиторії: нативний мод BeamNG.drive, у якому реальне місце виглядає наповненим і на ньому можна їздити. За містом природа має бути не біднішою за BeamNG.Earth. У місті менше дерев і більше трави, вулиці заставлені стоковими моделями гри. Щільність не має валити кадр. Відповідати користувачу українською.

## Що вже є конвеєр

Три частини, одна гілка `master`:

- **Планета** (`earthng_planet.zip`, збирає `earthng/build_mod.py` з `mod/`) тримає Lua, спільний арт, офлайн-мапу й правила. Під час гри `mod/lua/ge/extensions/e2r/generator.lua` будує тайл навколо авто, `native.lua` планує тайли, `world.lua` веде сцену, колізію й навграф. Трафік без фізики — `flow.lua` і `handoff.lua`, світлофори — `signals.lua`, маршрут — `routing.lua` і `navigator.lua`, рядок місця — `location.lua`. Клімат читає `biome.lua`, бюджети задає `quality.lua`.
- **Пак країни** (`earthng_<id>.zip`) тримає компактні факти OSM і висоти, не готові міста. Збирає Python-конвеєр `earthng/` (`country_fetch.py` → `osm_tiles_country.py` → `fast_sources.py` → `build_country.py`, класи — `fast_style.py`). Важкі етапи (нарізка, індекс, клітинки, сцени, маршрути, `Map detail`) мають нативну копію в `rust/` (`earthng-mapbuilder.exe`, `earthng_native.dll`), яка пише ті самі байти; `EARTHNG_NATIVE=0` вимикає її.
- **EarthNG.exe** (`rust/crates/app` + сторінка `app/ui/` + сервіс `earthng/app_service.py`) — вікно для гравця: вбудований Python, вибір області, збірка й встановлення пака разом із планетою. Runtime для exe збирає `earthng/prepare_app.py`.

Нове наповнення розширює генератор і спільну маску зайнятого місця. Окремий сервер, статичний експорт міста чи другий рендер доріг не додавати.

Стокові меші й текстури гри лишаються в установці гравця. Мод посилається на них через VFS і не копіює їх у ZIP.

## Перед правкою

Карта документів — `docs/README.md`.

Наповнення світу: прочитати реєстр `docs/GENERATION_GAPS.md` і один профільний документ: `docs/NATURE.md`, `docs/CITY_DETAIL.md`, `docs/VENUES.md`, `docs/SIGNS.md` або `docs/PERFORMANCE.md`. Історичні числа в `PERFORMANCE.md` і `STREET_PROPS.md` не є поточним бюджетом. Бюджет брати з коду (`quality.lua`, генератор) і зі свіжого заміру.

Збирач паків і exe: `docs/MAPBUILDER_RS.md` (нативні етапи і правило «ті самі байти») і `docs/MAPBUILDER_APP.md` (exe, протокол сторінки, джерело тайлів).

Процедура зміни світу: скіл `earthng-world`.

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

Кадр і місце: назвати lat/lon, пресет якості і що змінилося в кадрі. Зелений тест без проїзду не закриває візуальний пропуск у `docs/GENERATION_GAPS.md`.

## Хто що робить

- `earthng-scout` читає код і документи, нічого не змінює.
- `earthng-author` міняє генератор, стилі й тести і не запускає гру.
- `earthng-runtime` єдиний запускає BeamNG і міряє.

Нові типи з `.grok/agents/` з'являються в наступній сесії. Не спавнити всіх трьох на дрібну правку. Скаут — коли невідомо, де правило. Рантайм — коли твердження про вигляд або кадр інакше не перевірити.

## Git

Гілка релізу — `master`. Пуш і тег лише за окремим проханням. Не комітити `data/`, `out/`, файли гри, розпаковані ассети BeamNG і секрети.
