// UI strings, Ukrainian and English. Look and layer labels come from the service (looks.py);
// LOOK_UK translates them by id.
const STRINGS = {
  uk: {
    'nav.map': 'Карта', 'nav.projects': 'Проєкти', 'nav.settings': 'Налаштування',
    'search.placeholder': 'Місто, адреса чи регіон…',
    'search.enter': 'Enter — шукати міста й адреси',
    'search.looking': 'Шукаю…',
    'search.found': 'Місця OpenStreetMap',
    'search.regions': 'Регіони Geofabrik',
    'search.none': 'Нічого не знайдено',
    'tool.box': '▭ Обвести область', 'tool.edit': '✎ Правки',
    'hint.select': 'Знайдіть місто в пошуку або натисніть «Обвести область». Shift + перетягування теж малює рамку.',
    'hint.drawing': 'Затисніть кнопку миші і протягніть рамку навколо потрібної області. Esc — скасувати.',
    'hint.edit': 'Клік по карті ставить точку правки. Клік по точці прибирає її.',
    'empty.title': 'Оберіть область',
    'empty.body': 'Знайдіть місто в пошуку над мапою або обведіть рамку прямо на мапі.',
    'empty.draw': '▭ Обвести область на мапі',
    'empty.tip': 'Місто чи район 5–20 км збирається за кілька хвилин. Уперше для країни ще качаються дані OSM.',
    'empty.recent': 'Нещодавні',
    'area.title': 'Виділена область', 'area.clear': 'інша область', 'area.size': 'Площа', 'area.source': 'Дані',
    'area.time': 'Час', 'area.name': 'Назва', 'area.build': 'Створити карту', 'area.save': 'Зберегти проєкт',
    'area.noSource': 'жоден регіон Geofabrik не покриває всю рамку — зменште її',
    'area.cached': 'тайли вже нарізані', 'area.pbfCached': 'дані вже на диску', 'area.download': mb => `завантажити ${mb} МБ`,
    'area.planet': 'Спершу встановиться мод EarthNG (планета, ~170 МБ з GitHub).',
    'area.planetOld': v => `Мод EarthNG ${v} застарий — оновиться разом з картою.`,
    'area.big': 'Велика область: збірка може тривати довго, а пак займе кілька ГБ. Для першої спроби оберіть місто.',
    'area.noGame': 'Спершу вкажіть теку гри BeamNG (вище).',
    'look.title': 'Вигляд і шари', 'look.block': 'Набір', 'layers.title': 'Шари',
    'project.title': 'Проєкт і правки',
    'edits.title': 'Правки перед збиранням',
    'edits.count': n => n ? `${n} точок правок. Поки зберігаються в проєкті; в пак підуть у наступній версії.` : 'Правок немає. Кнопка «✎ Правки» над картою ставить точки.',
    'build.title': 'Створюю карту', 'build.planetTitle': 'Встановлюю мод EarthNG', 'build.stop': 'Зупинити',
    'build.back': 'Назад', 'build.retry': 'Спробувати ще раз', 'build.open': 'Відкрити теку mods', 'build.log': 'Журнал',
    'build.complete': 'Готово.', 'build.stopped': 'Зупинено. Готові етапи збережено — наступна спроба продовжить.',
    'build.failed': 'Не вдалося',
    'done.title': 'Карту встановлено', 'done.planetTitle': 'Мод EarthNG встановлено',
    'done.body': name => `Запустіть BeamNG.drive → Freeroam → EarthNG - Planet і оберіть точку ${name ? `в «${name}»` : 'у виділеній області'}.`,
    'done.planetBody': 'Тепер оберіть область і створіть карту.',
    'done.launch': 'Запустити BeamNG.drive', 'done.another': 'Створити ще одну карту',
    'setup.gameOk': 'Гра BeamNG.drive знайдена', 'setup.gameMissing': 'Теку гри BeamNG не знайдено',
    'setup.gameFix': 'вказати', 'setup.change': 'змінити',
    'setup.planetOk': v => `Мод EarthNG ${v} встановлено`,
    'setup.planetMissing': 'Мод EarthNG встановиться разом з першою картою',
    'setup.planetOld': v => `Мод EarthNG ${v} оновиться разом з картою`,
    'setup.planetNow': 'встановити зараз',
    'projects.title': 'Проєкти', 'projects.body': 'Збережені області з налаштуваннями й правками.', 'projects.none': 'Ще немає.',
    'projects.open': 'Відкрити',
    'settings.title': 'Налаштування', 'settings.game': 'Тека користувача BeamNG', 'settings.other': 'Інша тека',
    'settings.apply': 'Обрати', 'settings.planet': 'Планета (мод EarthNG)', 'settings.data': 'Дані',
    'settings.openHome': 'Відкрити теку даних',
    'planet.install': 'Встановити планету', 'planet.update': 'Оновити планету',
    'planet.missing': 'Планету не встановлено', 'planet.missingBody': 'Без earthng_planet.zip пак не відкриється в грі. Близько 170 МБ з GitHub.',
    'planet.old': v => `Планета ${v} старша за цей Map Builder`, 'planet.ok': v => `Планета ${v}`,
    'game.missing': 'Теку BeamNG не знайдено', 'game.missingBody': 'Запустіть гру хоч раз або вкажіть теку в налаштуваннях.',
    'game.ok': 'BeamNG', 'disk.free': gb => `вільно ${gb} ГБ`, 'busy': 'Іде завдання…',
    'service.down': 'Сервіс зупинився. Перезапустіть EarthNG; журнал у %LOCALAPPDATA%\\EarthNG\\logs.',
    'stage.Planet': 'Мод EarthNG', 'stage.Sources': 'Дані OSM', 'stage.Cut tiles': 'Нарізка тайлів', 'stage.Elevation': 'Висоти',
    'stage.Region index': 'Індекс доріг', 'stage.Export': 'Експорт пака', 'stage.Install': 'Встановлення',
  },
  en: {
    'nav.map': 'Map', 'nav.projects': 'Projects', 'nav.settings': 'Settings',
    'search.placeholder': 'Town, address or region…',
    'search.enter': 'Enter: search towns and addresses',
    'search.looking': 'Searching…',
    'search.found': 'OpenStreetMap places',
    'search.regions': 'Geofabrik regions',
    'search.none': 'Nothing found',
    'tool.box': '▭ Draw area', 'tool.edit': '✎ Edits',
    'hint.select': 'Search for a town or click “Draw area”. Shift + drag draws a box too.',
    'hint.drawing': 'Hold the mouse button and drag a box around the area you want. Esc cancels.',
    'hint.edit': 'Click the map to place an edit point. Click a point to remove it.',
    'empty.title': 'Choose an area',
    'empty.body': 'Search for a town above the map, or draw a box right on the map.',
    'empty.draw': '▭ Draw an area on the map',
    'empty.tip': 'A town or district of 5–20 km builds in a few minutes. The first time for a country, its OSM data is downloaded too.',
    'empty.recent': 'Recent',
    'area.title': 'Selected area', 'area.clear': 'another area', 'area.size': 'Area', 'area.source': 'Data',
    'area.time': 'Time', 'area.name': 'Name', 'area.build': 'Create the map', 'area.save': 'Save project',
    'area.noSource': 'no Geofabrik region holds the whole box — make it smaller',
    'area.cached': 'tiles already cut', 'area.pbfCached': 'data already on disk', 'area.download': mb => `${mb} MB to download`,
    'area.planet': 'The EarthNG mod (the planet, ~170 MB from GitHub) is installed first.',
    'area.planetOld': v => `EarthNG mod ${v} is out of date — it is updated with the map.`,
    'area.big': 'A large area: the build can take long and the pack takes several GB. For a first try, pick a town.',
    'area.noGame': 'Choose the BeamNG game folder first (above).',
    'look.title': 'Look and layers', 'look.block': 'Preset', 'layers.title': 'Layers',
    'project.title': 'Project and edits',
    'edits.title': 'Edits before packing',
    'edits.count': n => n ? `${n} edit points. Kept in the project for now; they go into the pack in the next version.` : 'No edits. “✎ Edits” above the map places points.',
    'build.title': 'Creating the map', 'build.planetTitle': 'Installing the EarthNG mod', 'build.stop': 'Stop',
    'build.back': 'Back', 'build.retry': 'Try again', 'build.open': 'Open the mods folder', 'build.log': 'Log',
    'build.complete': 'Done.', 'build.stopped': 'Stopped. Finished stages are kept — the next try continues.',
    'build.failed': 'Failed',
    'done.title': 'The map is installed', 'done.planetTitle': 'The EarthNG mod is installed',
    'done.body': name => `Start BeamNG.drive → Freeroam → EarthNG - Planet and pick a point ${name ? `in “${name}”` : 'inside the selected area'}.`,
    'done.planetBody': 'Now choose an area and create a map.',
    'done.launch': 'Start BeamNG.drive', 'done.another': 'Create another map',
    'setup.gameOk': 'BeamNG.drive found', 'setup.gameMissing': 'BeamNG game folder not found',
    'setup.gameFix': 'choose', 'setup.change': 'change',
    'setup.planetOk': v => `EarthNG mod ${v} installed`,
    'setup.planetMissing': 'The EarthNG mod is installed with your first map',
    'setup.planetOld': v => `EarthNG mod ${v} is updated with the map`,
    'setup.planetNow': 'install now',
    'projects.title': 'Projects', 'projects.body': 'Saved areas with their settings and edits.', 'projects.none': 'None yet.',
    'projects.open': 'Open',
    'settings.title': 'Settings', 'settings.game': 'BeamNG user folder', 'settings.other': 'Another folder',
    'settings.apply': 'Use', 'settings.planet': 'Planet (the EarthNG mod)', 'settings.data': 'Data',
    'settings.openHome': 'Open data folder',
    'planet.install': 'Install the planet', 'planet.update': 'Update the planet',
    'planet.missing': 'The planet is not installed', 'planet.missingBody': 'Packs need earthng_planet.zip in the game. About 170 MB from GitHub.',
    'planet.old': v => `Planet ${v} is older than this Map Builder`, 'planet.ok': v => `Planet ${v}`,
    'game.missing': 'BeamNG folder not found', 'game.missingBody': 'Start the game once, or choose the folder in Settings.',
    'game.ok': 'BeamNG', 'disk.free': gb => `${gb} GB free`, 'busy': 'Working…',
    'service.down': 'The service stopped. Restart EarthNG; the log is in %LOCALAPPDATA%\\EarthNG\\logs.',
    'stage.Planet': 'EarthNG mod', 'stage.Sources': 'OSM data', 'stage.Cut tiles': 'Cut tiles', 'stage.Elevation': 'Elevation',
    'stage.Region index': 'Road index', 'stage.Export': 'Export pack', 'stage.Install': 'Install',
  },
};

const LOOK_UK = {
  asphalt: 'Асфальт', markings: 'Розмітка', verge: 'Узбіччя', buildings: 'Будинки без тегів', trees: 'Дерева',
  statics: 'Вуличні об’єкти', smooth: 'Рівний', worn: 'Зношений', fresh: 'Свіжий', white: 'Біла', yellow: 'Жовта',
  none: 'Без розмітки', grass: 'Трава', dirt: 'Ґрунт', dry: 'Суха трава', gravel: 'Гравій', panel: 'Панельки з лоджіями',
  brick: 'Цегла', plaster: 'Штукатурка', mixed: 'Змішані', regional: 'За широтою', broadleaf: 'Листяні',
  conifer: 'Хвойні', street: 'Ліхтарі й зупинки', sparse: 'Лише зупинки',
  'layer.buildings': 'Будинки', 'layer.water': 'Вода', 'layer.cover': 'Ліс, поле, парк, двір', 'layer.barriers': 'Паркани й стіни',
  'layer.treeRows': 'Ряди дерев', 'layer.stops': 'Зупинки з даних',
};

let LANG = (() => {
  try { const saved = localStorage.getItem('lang'); if (saved) return saved; } catch (e) { /* storage off */ }
  return (navigator.language || 'en').toLowerCase().startsWith('uk') ? 'uk' : 'en';
})();

function t(key, ...args) {
  const value = (STRINGS[LANG] && STRINGS[LANG][key]) ?? STRINGS.en[key] ?? key;
  return typeof value === 'function' ? value(...args) : value;
}

function lookLabel(id, fallback) {
  return LANG === 'uk' && LOOK_UK[id] ? LOOK_UK[id] : fallback;
}

function applyI18n(root = document) {
  document.documentElement.lang = LANG;
  root.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
  root.querySelectorAll('[data-i18n-title]').forEach(el => { el.title = t(el.dataset.i18nTitle); });
  root.querySelectorAll('[data-i18n-placeholder]').forEach(el => { el.placeholder = t(el.dataset.i18nPlaceholder); });
}
