// UI strings, Ukrainian and English. Look and layer labels come from the service (looks.py);
// LOOK_UK translates them by id.
const STRINGS = {
  uk: {
    'nav.map': 'Карта', 'nav.projects': 'Проєкти', 'nav.settings': 'Налаштування',
    'search.placeholder': 'Країна чи регіон Geofabrik…',
    'tool.box': 'Рамка', 'tool.edit': 'Правки',
    'hint.select': 'Натисніть «Рамка» і протягніть по карті, або Shift + перетягування.',
    'hint.drawing': 'Протягніть рамку навколо потрібної області.',
    'hint.edit': 'Клік по карті ставить точку правки. Клік по точці прибирає її.',
    'empty.title': 'Оберіть місце на карті',
    'empty.body': 'Виділіть рамкою місто чи район. Для міста збірка займає кілька хвилин; уперше ще качається PBF країни.',
    'area.title': 'Виділена область', 'area.clear': 'скинути', 'area.size': 'Площа', 'area.source': 'Джерело',
    'area.time': 'Збірка', 'area.name': 'Назва проєкту', 'area.build': 'Зібрати й встановити', 'area.save': 'Зберегти проєкт',
    'area.noSource': 'жоден регіон Geofabrik не покриває всю рамку — зменште її',
    'area.cached': 'тайли вже нарізані', 'area.pbfCached': 'PBF уже на диску',
    'look.title': 'Вигляд', 'look.block': 'Набір', 'layers.title': 'Шари',
    'edits.title': 'Правки перед збиранням',
    'edits.count': n => n ? `${n} точок. Поки зберігаються в проєкті; в пак підуть у наступній версії.` : 'Немає. Кнопка «Правки» над картою.',
    'build.title': 'Збірка', 'build.stop': 'Зупинити', 'build.back': 'До області', 'build.open': 'Відкрити mods',
    'build.complete': 'Готово: пак встановлено. Перезапустіть BeamNG.', 'build.stopped': 'Зупинено. Готові етапи збережено.',
    'build.failed': 'Помилка',
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
    'stage.Sources': 'Джерела', 'stage.Cut tiles': 'Нарізка тайлів', 'stage.Elevation': 'Висоти',
    'stage.Region index': 'Індекс доріг', 'stage.Export': 'Експорт пака', 'stage.Install': 'Встановлення',
  },
  en: {
    'nav.map': 'Map', 'nav.projects': 'Projects', 'nav.settings': 'Settings',
    'search.placeholder': 'Country or Geofabrik region…',
    'tool.box': 'Box', 'tool.edit': 'Edits',
    'hint.select': 'Click “Box” and drag on the map, or Shift + drag.',
    'hint.drawing': 'Drag a box around the area you want.',
    'hint.edit': 'Click the map to place an edit point. Click a point to remove it.',
    'empty.title': 'Pick a place on the map',
    'empty.body': 'Box a city or a district. A city builds in a few minutes; the first time the country PBF is downloaded too.',
    'area.title': 'Selected area', 'area.clear': 'clear', 'area.size': 'Area', 'area.source': 'Source',
    'area.time': 'Build', 'area.name': 'Project name', 'area.build': 'Build and install', 'area.save': 'Save project',
    'area.noSource': 'no Geofabrik region holds the whole box — make it smaller',
    'area.cached': 'tiles already cut', 'area.pbfCached': 'PBF already on disk',
    'look.title': 'Look', 'look.block': 'Preset', 'layers.title': 'Layers',
    'edits.title': 'Edits before packing',
    'edits.count': n => n ? `${n} points. Kept in the project for now; they go into the pack in the next version.` : 'None. Use “Edits” above the map.',
    'build.title': 'Build', 'build.stop': 'Stop', 'build.back': 'Back to area', 'build.open': 'Open mods',
    'build.complete': 'Done: the pack is installed. Restart BeamNG.', 'build.stopped': 'Stopped. Finished stages are kept.',
    'build.failed': 'Failed',
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
    'stage.Sources': 'Sources', 'stage.Cut tiles': 'Cut tiles', 'stage.Elevation': 'Elevation',
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
