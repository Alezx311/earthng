// EarthNG Map Builder page. Talks to earthng/app_service.py through EarthNG.exe:
// window.ipc.postMessage(JSON) out, window.earthng.receive(message) in (docs/MAPBUILDER_APP.md).
'use strict';

const $ = id => document.getElementById(id);
const el = (tag, props = {}, ...children) => {
  const node = Object.assign(document.createElement(tag), props);
  children.flat().forEach(c => node.append(c));
  return node;
};

// ------------------------------------------------------------------ transport
const pending = new Map();
let nextId = 1;
const listeners = [];

window.earthng = {
  receive(message) {
    if (message && message.id != null && pending.has(message.id)) {
      const { resolve, reject } = pending.get(message.id);
      pending.delete(message.id);
      message.ok ? resolve(message) : reject(new Error(message.error || 'failed'));
      return;
    }
    listeners.forEach(fn => fn(message));
  },
};

function call(cmd, args = {}, to = 'service') {
  const id = nextId++;
  const message = { id, cmd, ...args, ...(to === 'app' ? { to: 'app' } : {}) };
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    if (window.ipc) window.ipc.postMessage(JSON.stringify(message));
    else mockService(message);
  });
}

// Opened as a plain file (design work in a browser): a small fake service.
function mockService(m) {
  const answer = extra => setTimeout(() => window.earthng.receive({ id: m.id, ok: true, ...extra }), 50);
  const slots = { asphalt: ['smooth', 'worn', 'fresh'], markings: ['white', 'yellow', 'none'], verge: ['grass', 'dirt'],
    buildings: ['panel', 'brick', 'plaster', 'mixed'], trees: ['regional', 'mixed'], statics: ['street', 'sparse', 'none'] };
  const look = { block: 'postsoviet', asphalt: 'worn', markings: 'white', verge: 'grass', buildings: 'panel', trees: 'regional', statics: 'street' };
  switch (m.cmd) {
    case 'status': return answer({ home: 'C:\\Users\\you\\AppData\\Local\\EarthNG\\data', mods: 'C:\\Users\\you\\AppData\\Local\\BeamNG\\BeamNG.drive\\current',
      game_folder_ok: true, planet: { installed: false, version: null, expected: '0.7.0' }, busy: false, build: { version: 'dev' },
      free_gb: 412.3, folders: ['C:\\Users\\you\\AppData\\Local\\BeamNG\\BeamNG.drive\\current'] });
    case 'options': return answer({ slots: Object.fromEntries(Object.entries(slots).map(([k, v]) => [k, v.map(id => ({ id, label: id }))])),
      slot_labels: Object.fromEntries(Object.keys(slots).map(k => [k, k])),
      blocks: [{ id: 'general', title: 'General', look }, { id: 'postsoviet', title: 'Post-Soviet', look }],
      layers: ['buildings', 'water', 'cover', 'barriers', 'treeRows', 'stops'].map(id => ({ id, label: id, default: true })), recommended: look });
    case 'places': return answer({ places: [{ id: 'ukraine', name: 'Ukraine', parent: 'Europe' }, { id: 'albania', name: 'Albania', parent: 'Europe' }] });
    case 'covering': return answer({ place: { id: 'ukraine', name: 'Ukraine', parent: 'Europe' }, km2: 120.4 });
    case 'estimate': return answer({ seconds: [110, 12, 3, 20, 13, 1], stages: ['Sources', 'Cut tiles', 'Elevation', 'Region index', 'Export', 'Install'],
      reason: 'rough estimate', cached_tiles: false, cached_pbf: true });
    case 'projects': return answer({ projects: [] });
    default: return answer({});
  }
}

// ------------------------------------------------------------------ state
const state = {
  status: null, options: null, place: null, box: null, estimate: null,
  look: null, include: null, edits: [], projectId: null, building: false, mode: null,
};

// ------------------------------------------------------------------ map
const map = L.map('map', { zoomControl: true, worldCopyJump: true }).setView([49.0, 31.0], 6);
L.tileLayer(window.ipc ? 'tile/{z}/{x}/{y}.png' : 'https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19, attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
}).addTo(map);
map.attributionControl.setPrefix('');
let boxLayer = null;
let boundaryLayer = null;
const editLayer = L.layerGroup().addTo(map);

function setMode(mode) {
  state.mode = state.mode === mode ? null : mode;
  $('tool-box').classList.toggle('on', state.mode === 'box');
  $('tool-edit').classList.toggle('on', state.mode === 'edit');
  document.querySelector('.map-wrap').classList.toggle('drawing', state.mode === 'box');
  $('hint').textContent = t(state.mode === 'box' ? 'hint.drawing' : state.mode === 'edit' ? 'hint.edit' : 'hint.select');
  if (state.mode === 'box') map.dragging.disable(); else map.dragging.enable();
}

let dragStart = null;
map.on('mousedown', e => {
  if (state.building) return;
  if (state.mode === 'box' || e.originalEvent.shiftKey) {
    map.dragging.disable();
    dragStart = e.latlng;
    if (boxLayer) boxLayer.remove();
    boxLayer = L.rectangle([dragStart, dragStart], { color: getComputedStyle(document.body).getPropertyValue('--box'), weight: 2 }).addTo(map);
  }
});
map.on('mousemove', e => { if (dragStart) boxLayer.setBounds([dragStart, e.latlng]); });
map.on('mouseup', e => {
  if (!dragStart) return;
  const b = L.latLngBounds(dragStart, e.latlng);
  dragStart = null;
  if (state.mode !== 'box') map.dragging.enable();
  if (Math.abs(b.getEast() - b.getWest()) < 1e-4 || Math.abs(b.getNorth() - b.getSouth()) < 1e-4) {
    boxLayer.remove(); boxLayer = null; return;
  }
  if (state.mode === 'box') setMode('box');
  selectBox([b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].map(v => +v.toFixed(6)));
});
map.on('click', e => {
  if (state.mode !== 'edit' || state.building) return;
  state.edits.push({ op: 'add', kind: 'point', lat: +e.latlng.lat.toFixed(7), lon: +e.latlng.lng.toFixed(7) });
  drawEdits();
});

function drawEdits() {
  editLayer.clearLayers();
  state.edits.forEach((edit, i) => {
    L.circleMarker([edit.lat, edit.lon], { radius: 6, color: getComputedStyle(document.body).getPropertyValue('--edit') })
      .on('click', ev => { L.DomEvent.stop(ev); if (state.mode === 'edit') { state.edits.splice(i, 1); drawEdits(); } })
      .addTo(editLayer);
  });
  $('edits-count').textContent = t('edits.count', state.edits.length);
}

// ------------------------------------------------------------------ selection
async function selectBox(box) {
  state.box = box;
  if (boxLayer) boxLayer.remove();
  boxLayer = L.rectangle([[box[1], box[0]], [box[3], box[2]]], { color: getComputedStyle(document.body).getPropertyValue('--box'), weight: 2 }).addTo(map);
  showCard('area');
  $('area-source').textContent = '…';
  $('area-time').textContent = '…';
  try {
    const cover = await call('covering', { box });
    $('area-km2').textContent = `${cover.km2.toLocaleString()} km²`;
    if (!cover.place) {
      state.place = null;
      $('area-source').textContent = t('area.noSource');
    } else {
      await choosePlace(cover.place, false);
    }
  } catch (err) {
    $('area-source').textContent = err.message;
  }
  updateBuildButton();
}

async function choosePlace(place, fit) {
  state.place = place;
  $('area-source').textContent = place.parent ? `${place.name} — ${place.parent}` : place.name;
  if (!$('project-title').value) $('project-title').value = place.name;
  if (fit || !state.box) {
    call('boundary', { place: place.id }).then(r => {
      if (boundaryLayer) boundaryLayer.remove();
      if (r.geojson) {
        boundaryLayer = L.geoJSON(r.geojson, { style: { color: '#888', weight: 1, fill: false, dashArray: '4 4' }, interactive: false }).addTo(map);
        if (fit && !state.box) map.fitBounds(boundaryLayer.getBounds());
      }
    }).catch(() => {});
  }
  await loadOptions(place.id);
  refreshEstimate();
}

async function refreshEstimate() {
  if (!state.place) return;
  try {
    const est = await call('estimate', { place: state.place.id, box: state.box, include: state.include });
    state.estimate = est;
    const notes = [];
    if (est.cached_tiles) notes.push(t('area.cached')); else if (est.cached_pbf) notes.push(t('area.pbfCached'));
    if (est.seconds) {
      const total = est.seconds.reduce((a, b) => a + b, 0);
      $('area-time').textContent = `${duration(total * 0.5)}–${duration(total * 2.5)}` + (notes.length ? ` · ${notes.join(', ')}` : '');
    } else {
      $('area-time').textContent = est.reason;
    }
  } catch (err) {
    $('area-time').textContent = err.message;
  }
}

function duration(s) {
  s = Math.max(0, s);
  if (s < 60) return `${Math.max(1, Math.round(s))} s`;
  if (s < 3600) return `${Math.ceil(s / 60)} min`;
  return `${(s / 3600).toFixed(1)} h`;
}

function clearArea() {
  state.box = null; state.place = null;
  if (boxLayer) { boxLayer.remove(); boxLayer = null; }
  if (boundaryLayer) { boundaryLayer.remove(); boundaryLayer = null; }
  showCard('empty');
}

// ------------------------------------------------------------------ options (look and layers)
async function loadOptions(placeId) {
  const opts = await call('options', { place: placeId });
  state.options = opts;
  if (!state.look || state.lookFor !== placeId) { state.look = { ...opts.recommended }; state.lookFor = placeId; }
  if (!state.include) state.include = Object.fromEntries(opts.layers.map(l => [l.id, l.default]));
  renderOptions();
}

function renderOptions() {
  const opts = state.options;
  if (!opts) return;
  const block = $('look-block');
  block.replaceChildren(...opts.blocks.map(b => el('option', { value: b.id, textContent: b.title, selected: b.id === state.look.block })));
  block.onchange = () => {
    const chosen = opts.blocks.find(b => b.id === block.value);
    state.look = { block: chosen.id, ...chosen.look };
    renderOptions();
  };
  $('look-slots').replaceChildren(...Object.entries(opts.slots).map(([slot, choices]) => {
    const select = el('select', {}, choices.map(c => el('option', { value: c.id, textContent: lookLabel(c.id, c.label), selected: c.id === state.look[slot] })));
    select.onchange = () => { state.look[slot] = select.value; };
    return el('label', { className: 'field' }, el('span', { textContent: lookLabel(slot, opts.slot_labels[slot]) }), select);
  }));
  $('layers').replaceChildren(...opts.layers.map(layer => {
    const box = el('input', { type: 'checkbox', checked: state.include[layer.id] });
    box.onchange = () => { state.include[layer.id] = box.checked; refreshEstimate(); };
    return el('label', {}, box, lookLabel(`layer.${layer.id}`, layer.label));
  }));
}

// ------------------------------------------------------------------ build
function updateBuildButton() {
  const planet = state.status && state.status.planet;
  $('build').disabled = state.building || !state.place || !(planet && planet.installed);
}

const stageTimes = {};
let buildStarted = 0;
let elapsedTimer = null;

async function build() {
  if (!state.place) return;
  saveProject(true);
  showCard('build');
  const stages = (state.estimate && state.estimate.stages) || ['Sources', 'Cut tiles', 'Elevation', 'Region index', 'Export', 'Install'];
  $('stages').replaceChildren(...stages.map(name => el('li', { dataset: { stage: name } },
    el('span', { className: 'dot' }), el('span', { textContent: t(`stage.${name}`) }), el('span', { className: 't' }))));
  $('log').textContent = '';
  ['stop'].forEach(id => { $(id).hidden = false; });
  ['build-back', 'open-mods'].forEach(id => { $(id).hidden = true; });
  try {
    await call('build', { place: state.place.id, box: state.box, look: state.look, include: state.include });
    setBuilding(true);
    buildStarted = Date.now();
    elapsedTimer = setInterval(() => { $('build-elapsed').textContent = duration((Date.now() - buildStarted) / 1000); }, 1000);
  } catch (err) {
    appendLog(`${t('build.failed')}: ${err.message}`);
    finishBuild('failed');
  }
}

function setBuilding(on) {
  state.building = on;
  $('st-task').textContent = on ? t('busy') : '';
  updateBuildButton();
}

function appendLog(text) {
  const log = $('log');
  const atEnd = log.scrollTop + log.clientHeight >= log.scrollHeight - 4;
  log.textContent += text + '\n';
  if (log.textContent.length > 200000) log.textContent = log.textContent.slice(-150000);
  if (atEnd) log.scrollTop = log.scrollHeight;
}

function onStage(name, seconds) {
  const row = document.querySelector(`#stages li[data-stage="${CSS.escape(name)}"]`);
  if (!row) return;
  if (seconds == null) {
    row.classList.add('active');
  } else {
    row.classList.remove('active');
    row.classList.add('done');
    row.querySelector('.t').textContent = duration(seconds);
  }
}

function finishBuild(result, error) {
  setBuilding(false);
  clearInterval(elapsedTimer);
  $('stop').hidden = true;
  $('build-back').hidden = false;
  $('open-mods').hidden = result !== 'complete';
  appendLog(result === 'complete' ? t('build.complete') : result === 'stopped' ? t('build.stopped') : `${t('build.failed')}: ${error || ''}`);
  document.querySelectorAll('#stages li.active').forEach(li => li.classList.remove('active'));
}

// ------------------------------------------------------------------ projects
function projectId(title) {
  const base = (title || 'map').toLowerCase().normalize('NFKD').replace(/[^\p{L}\p{N}]+/gu, '-')
    .replace(/[^a-z0-9-]/g, '').replace(/^-+|-+$/g, '').slice(0, 40);
  return base || `map-${Date.now().toString(36)}`;
}

async function saveProject(quiet) {
  if (!state.place && !state.box) return;
  const title = $('project-title').value.trim() || (state.place && state.place.name) || 'Map';
  state.projectId = state.projectId || projectId(title);
  const project = { schema: 'earthng-project-v1', id: state.projectId, title,
    selection: { place: state.place && state.place.id, box: state.box },
    options: { look: state.look, include: state.include }, edits: state.edits };
  try {
    await call('project_save', { project });
    if (!quiet) $('save-project').textContent = '✓';
    setTimeout(() => { $('save-project').textContent = t('area.save'); }, 1200);
  } catch (err) {
    alert(err.message);
  }
}

async function listProjects() {
  const { projects } = await call('projects');
  $('projects').replaceChildren(...(projects.length ? projects.map(p => el('li', {},
    el('span', { textContent: p.title }),
    Object.assign(el('button', { textContent: t('projects.open') }), { onclick: () => openProject(p.id) }))) : [el('li', { className: 'muted', textContent: t('projects.none') })]));
}

async function openProject(name) {
  const { project } = await call('project_load', { name });
  showSection('map');
  state.projectId = project.id;
  state.edits = project.edits || [];
  state.look = project.options && project.options.look || null;
  state.include = project.options && project.options.include || null;
  state.lookFor = project.selection.place;
  $('project-title').value = project.title || project.id;
  drawEdits();
  if (project.selection.box) {
    const b = project.selection.box;
    map.fitBounds([[b[1], b[0]], [b[3], b[2]]], { padding: [40, 40] });
    await selectBox(b);
  }
}

// ------------------------------------------------------------------ status, settings
async function refreshStatus() {
  const s = await call('status');
  state.status = s;
  const planet = s.planet;
  const expected = planet.expected;
  const old = planet.installed && expected && planet.version !== expected;
  $('st-game').innerHTML = '';
  $('st-game').append(el('span', { className: s.game_folder_ok ? 'ok' : 'bad', textContent: s.game_folder_ok ? `● ${t('game.ok')}` : `● ${t('game.missing')}` }));
  $('st-planet').textContent = planet.installed ? t('planet.ok', planet.version || '?') : t('planet.missing');
  $('st-planet').className = planet.installed && !old ? 'ok' : 'bad';
  $('st-disk').textContent = s.free_gb != null ? t('disk.free', s.free_gb) : '';
  const banner = $('banner');
  banner.replaceChildren();
  if (!s.game_folder_ok) {
    banner.append(el('div', { className: 'banner bad' }, el('h4', { textContent: t('game.missing') }),
      el('p', { className: 'small', textContent: t('game.missingBody') })));
  } else if (!planet.installed || old) {
    const install = el('button', { className: 'primary', textContent: t(old ? 'planet.update' : 'planet.install') });
    install.onclick = installPlanet;
    banner.append(el('div', { className: 'banner warn' },
      el('h4', { textContent: old ? t('planet.old', planet.version) : t('planet.missing') }),
      el('p', { className: 'small', textContent: t('planet.missingBody') }), el('div', { className: 'actions' }, install)));
  }
  $('game-folders').replaceChildren(...[...new Set([s.mods, ...s.folders])].map(f => el('option', { value: f, textContent: f, selected: f === s.mods })));
  $('game-folder-state').textContent = s.game_folder_ok ? '✓' : t('game.missingBody');
  $('planet-state').textContent = planet.installed ? `${t('planet.ok', planet.version || '?')} — ${planet.path}` : t('planet.missing');
  $('planet-install').textContent = t(planet.installed ? 'planet.update' : 'planet.install');
  $('home-path').textContent = s.home;
  $('about').textContent = `EarthNG ${s.build.version || 'dev'}${s.build.sourceCommit ? ' · ' + s.build.sourceCommit.slice(0, 7) : ''}`;
  if (s.busy) setBuilding(true);
  updateBuildButton();
}

async function installPlanet() {
  showSection('map');
  showCard('build');
  $('stages').replaceChildren();
  $('log').textContent = '';
  $('stop').hidden = false;
  ['build-back', 'open-mods'].forEach(id => { $(id).hidden = true; });
  try {
    await call('install_planet');
    setBuilding(true);
  } catch (err) {
    appendLog(err.message);
    finishBuild('failed', err.message);
  }
}

async function setGameFolder(path) {
  try {
    await call('set_game_folder', { path });
    await refreshStatus();
  } catch (err) {
    $('game-folder-state').textContent = err.message;
  }
}

// ------------------------------------------------------------------ search
let searchTimer = null;
$('search').addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(async () => {
    const query = $('search').value.trim();
    const list = $('search-results');
    if (!query) { list.hidden = true; return; }
    try {
      const { places } = await call('places', { query, limit: 30 });
      list.replaceChildren(...places.map(p => {
        const li = el('li', {}, el('div', { textContent: p.name }), el('div', { className: 'parent', textContent: p.parent || '' }));
        li.onclick = () => { list.hidden = true; $('search').value = p.name; clearArea(); showCard('area'); $('area-km2').textContent = '—'; choosePlace(p, true).then(updateBuildButton); };
        return li;
      }));
      list.hidden = !places.length;
    } catch (err) {
      list.replaceChildren(el('li', { className: 'muted', textContent: err.message }));
      list.hidden = false;
    }
  }, 250);
});
document.addEventListener('click', e => { if (!e.target.closest('.search')) $('search-results').hidden = true; });

// ------------------------------------------------------------------ layout
function showCard(name) {
  ['empty', 'area', 'build'].forEach(n => { $(`card-${n}`).hidden = n !== name; });
}

function showSection(name) {
  document.querySelectorAll('.rail-btn[data-section]').forEach(b => b.classList.toggle('active', b.dataset.section === name));
  document.querySelectorAll('[data-panel]').forEach(p => { p.hidden = p.dataset.panel !== name; });
  if (name === 'projects') listProjects();
  if (name === 'settings') refreshStatus();
}

// ------------------------------------------------------------------ events from the service
listeners.push(message => {
  if (message.event === 'log') appendLog(message.text);
  else if (message.event === 'stage') onStage(message.name, message.seconds);
  else if (message.event === 'done') {
    finishBuild(message.result, message.error);
    if (message.job === 'install_planet') refreshStatus();
  } else if (message.event === 'ready') refreshStatus();
  else if (message.event === 'service_exit') {
    setBuilding(false);
    $('banner').replaceChildren(el('div', { className: 'banner bad' }, el('p', { textContent: t('service.down') })));
  }
});

// ------------------------------------------------------------------ wiring
document.querySelectorAll('.rail-btn[data-section]').forEach(b => { b.onclick = () => showSection(b.dataset.section); });
$('tool-box').onclick = () => setMode('box');
$('tool-edit').onclick = () => setMode('edit');
$('area-clear').onclick = clearArea;
$('build').onclick = build;
$('save-project').onclick = () => saveProject(false);
$('stop').onclick = () => call('stop').catch(() => {});
$('build-back').onclick = () => showCard(state.place ? 'area' : 'empty');
$('open-mods').onclick = () => call('open_folder', { which: 'mods' }).catch(() => {});
$('open-home').onclick = () => call('open_folder', { which: 'home' }).catch(() => {});
$('planet-install').onclick = installPlanet;
$('game-folders').onchange = e => setGameFolder(e.target.value);
$('game-folder-set').onclick = () => setGameFolder($('game-folder').value.trim());
$('lang').onclick = () => {
  LANG = LANG === 'uk' ? 'en' : 'uk';
  try { localStorage.setItem('lang', LANG); } catch (e) { /* storage off */ }
  $('lang').textContent = LANG === 'uk' ? 'УК' : 'EN';
  applyI18n(); renderOptions(); drawEdits(); setMode(state.mode); setMode(state.mode);
};
$('lang').textContent = LANG === 'uk' ? 'УК' : 'EN';
applyI18n();
drawEdits();
showCard('empty');
refreshStatus().catch(() => {});
