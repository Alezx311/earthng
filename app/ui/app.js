// EarthNG Map Builder page. Talks to earthng/app_service.py through EarthNG.exe:
// window.ipc.postMessage(JSON) out, window.earthng.receive(message) in (docs/MAPBUILDER_APP.md).
'use strict';

const $ = id => document.getElementById(id);
const el = (tag, { dataset, ...props } = {}, ...children) => {
  const node = Object.assign(document.createElement(tag), props);
  if (dataset) Object.assign(node.dataset, dataset);       // dataset itself is read-only
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
    case 'geocode': return answer({ results: [{ name: 'Тирана, Albania', lat: 41.3275, lon: 19.8189, bounds: [19.75, 41.28, 19.88, 41.37], kind: 'city' }] });
    case 'covering': return answer({ place: { id: 'ukraine', name: 'Ukraine', parent: 'Europe' }, km2: 120.4 });
    case 'estimate': return answer({ seconds: [30, 110, 12, 3, 20, 13, 1], stages: ['Planet', 'Sources', 'Cut tiles', 'Elevation', 'Region index', 'Export', 'Install'],
      reason: 'rough estimate', cached_tiles: false, cached_pbf: false, pbf_bytes: 54466814, planet: 'missing',
      source: m.box ? 'overpass' : 'pbf', pbf_seconds: 40 });
    case 'projects': return answer({ projects: [] });
    case 'build': case 'install_planet': {   // a pretend job: stages one by one, then done
      answer({ job: m.cmd });
      const stages = m.cmd === 'build' ? ['Planet', 'Sources', 'Cut tiles', 'Elevation', 'Region index', 'Export', 'Install'] : ['Planet'];
      const send = (msg, ms) => setTimeout(() => window.earthng.receive(msg), ms);
      if (m.cmd === 'build' && m.box && !m.allow_pbf) {      // Overpass busy: the page asks for the PBF
        send({ event: 'stage', name: 'Sources', seconds: null }, 300);
        send({ event: 'done', job: 'build', result: 'needs_pbf', reason: 'Overpass did not answer: overpass-api.de: HTTP Error 504: Gateway Timeout',
          place: 'albania', name: 'Albania', pbf_bytes: 54466814, pbf_seconds: 40 }, 1200);
        return undefined;
      }
      stages.forEach((name, i) => {
        send({ event: 'stage', name, seconds: null }, 300 + i * 700);
        send({ event: 'log', text: `${name}…` }, 350 + i * 700);
        send({ event: 'stage', name, seconds: 0.6 }, 900 + i * 700);
      });
      send({ event: 'done', job: m.cmd, result: 'complete', path: 'C:\\Users\\you\\AppData\\Local\\BeamNG\\BeamNG.drive\\current\\mods\\earthng_albania.zip' }, 1000 + stages.length * 700);
      return undefined;
    }
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
const BIG_KM2 = 2500;

async function selectBox(box, name) {
  state.box = box;
  state.areaName = name || null;
  if (boxLayer) boxLayer.remove();
  boxLayer = L.rectangle([[box[1], box[0]], [box[3], box[2]]], { color: getComputedStyle(document.body).getPropertyValue('--box'), weight: 2 }).addTo(map);
  showCard('area');
  $('area-title').textContent = name || t('area.title');
  $('area-km2').textContent = '…';
  $('area-source').textContent = '…';
  $('area-time').textContent = '…';
  state.place = null; state.estimate = null; state.km2 = null;
  renderNotes();
  updateBuildButton();
  try {
    const cover = await call('covering', { box });
    state.km2 = cover.km2;
    $('area-km2').textContent = `${cover.km2.toLocaleString()} km²`;
    if (!cover.place) {
      $('area-source').textContent = t('area.noSource');
    } else {
      await choosePlace(cover.place, false);
    }
  } catch (err) {
    $('area-source').textContent = err.message;
  }
  renderNotes();
  updateBuildButton();
}

async function choosePlace(place, fit) {
  state.place = place;
  $('area-source').textContent = place.parent ? `${place.name} — ${place.parent}` : place.name;
  if (!state.box) $('area-title').textContent = place.name;
  if (!$('project-title').value) $('project-title').value = areaName();
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
  await refreshEstimate();
}

function areaName() {
  return state.areaName || (state.place && state.place.name) || t('area.title');
}

async function refreshEstimate() {
  if (!state.place) return;
  try {
    const est = await call('estimate', { place: state.place.id, box: state.box, include: state.include });
    state.estimate = est;
    const notes = [];
    if (est.cached_tiles) notes.push(t('area.cached'));
    else if (est.source === 'overpass') notes.push(t('area.overpass'));
    else if (est.cached_pbf) notes.push(t('area.pbfCached'));
    else if (est.pbf_bytes) notes.push(t('area.download', Math.round(est.pbf_bytes / 2 ** 20)));
    if (est.seconds) {
      const total = est.seconds.reduce((a, b) => a + b, 0);
      $('area-time').textContent = `${duration(total * 0.5)}–${duration(total * 2.5)}`;
    } else {
      $('area-time').textContent = est.reason;
    }
    $('area-source').textContent = `${state.place.parent ? `${state.place.name} — ${state.place.parent}` : state.place.name}` + (notes.length ? ` · ${notes.join(', ')}` : '');
  } catch (err) {
    $('area-time').textContent = err.message;
  }
  renderNotes();
}

// What the user should know before pressing Create: the mod comes too, the area is large, no game.
function renderNotes() {
  const notes = [];
  const s = state.status;
  if (s && !s.game_folder_ok) notes.push(['bad', t('area.noGame')]);
  const planet = (state.estimate && state.estimate.planet) || planetNeeded();
  if (planet === 'old') notes.push(['info', t('area.planetOld', s ? s.planet.version : '')]);
  else if (planet) notes.push(['info', t('area.planet')]);
  if (state.km2 > BIG_KM2) notes.push(['warn', t('area.big')]);
  $('area-notes').replaceChildren(...notes.map(([kind, text]) => el('p', { className: `note ${kind}`, textContent: text })));
}

function planetNeeded() {
  const s = state.status;
  if (!s) return null;
  const planet = s.planet;
  if (!planet.installed) return 'missing';
  if (planet.error) return 'unreadable';
  if (planet.expected && planet.version !== planet.expected) return 'old';
  return null;
}

function duration(s) {
  s = Math.max(0, s);
  if (s < 60) return `${Math.max(1, Math.round(s))} s`;
  if (s < 3600) return `${Math.ceil(s / 60)} min`;
  return `${(s / 3600).toFixed(1)} h`;
}

function clearArea() {
  state.box = null; state.place = null; state.areaName = null; state.estimate = null; state.km2 = null;
  state.projectId = null;
  $('project-title').value = '';
  if (boxLayer) { boxLayer.remove(); boxLayer = null; }
  if (boundaryLayer) { boundaryLayer.remove(); boundaryLayer = null; }
  showCard('empty');
  renderRecent();
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
  const s = state.status;
  $('build').disabled = state.building || !state.place || !(s && s.game_folder_ok);
}

let buildStarted = 0;
let elapsedTimer = null;
let job = null;            // {kind: 'build' | 'install_planet', name, stages, weights}

function startProgress(kind, stages, weights) {
  // a drawn box has no name of its own: the region's name would mislead ("a point in Ukraine")
  job = { kind, name: state.areaName || (state.box ? null : state.place && state.place.name), stages, weights: weights || stages.map(() => 1), done: new Set(), active: null };
  showCard('build');
  $('build-title').textContent = t(kind === 'build' ? 'build.title' : 'build.planetTitle') + (kind === 'build' && job.name ? ` — ${job.name}` : '');
  $('stages').replaceChildren(...stages.map(name => el('li', { dataset: { stage: name } },
    el('span', { className: 'dot' }), el('span', { textContent: t(`stage.${name}`) }), el('span', { className: 't' }))));
  $('log').textContent = '';
  $('log-box').open = false;
  $('build-error').replaceChildren();
  $('build-elapsed').textContent = '';
  $('stop').hidden = false;
  ['build-retry', 'build-back'].forEach(id => { $(id).hidden = true; });
  drawProgress();
}

function drawProgress() {
  if (!job) return;
  const total = job.weights.reduce((a, b) => a + b, 0) || 1;
  let done = 0;
  job.stages.forEach((name, i) => {
    if (job.done.has(name)) done += job.weights[i];
    else if (job.active === name) done += job.weights[i] / 3;
  });
  $('progress-bar').style.width = `${Math.min(100, (100 * done) / total).toFixed(1)}%`;
}

// allowPbf: the user agreed to download the country's PBF. Without it a drawn area comes from
// Overpass, and the service answers 'needs_pbf' when no Overpass server gives it.
async function build(allowPbf = false) {
  if (!state.place) return;
  const est = state.estimate;
  if (!allowPbf && est && est.source === 'pbf' && !est.cached_pbf) {    // known before trying: ask first
    showPbfOffer({ lead: state.box ? 'pbf.bigLead' : 'pbf.wholeLead', name: state.place.name,
      pbf_bytes: est.pbf_bytes, pbf_seconds: est.pbf_seconds });
    return;
  }
  saveProject(true);
  const stages = (est && est.stages) || ['Sources', 'Cut tiles', 'Elevation', 'Region index', 'Export', 'Install'];
  startProgress('build', stages, est && est.seconds ? est.seconds.map(v => Math.max(1, v)) : null);
  job.allowPbf = allowPbf;
  try {
    await call('build', { place: state.place.id, box: state.box, look: state.look, include: state.include, allow_pbf: allowPbf });
    jobStarted();
  } catch (err) {
    finishBuild('failed', err.message);
  }
}

function jobStarted() {
  setBuilding(true);
  buildStarted = Date.now();
  clearInterval(elapsedTimer);
  elapsedTimer = setInterval(() => { $('build-elapsed').textContent = duration((Date.now() - buildStarted) / 1000); }, 1000);
}

function setBuilding(on) {
  state.building = on;
  $('st-task').textContent = on ? t('busy') : '';
  $('tool-box').disabled = on;
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
  if (!row) return;            // a background stage the list does not show (Map detail)
  if (seconds == null) {
    row.classList.add('active');
    if (job) job.active = name;
  } else {
    row.classList.remove('active');
    row.classList.add('done');
    row.querySelector('.t').textContent = duration(seconds);
    if (job) { job.done.add(name); if (job.active === name) job.active = null; }
  }
  drawProgress();
}

function finishBuild(result, error, path) {
  setBuilding(false);
  clearInterval(elapsedTimer);
  document.querySelectorAll('#stages li.active').forEach(li => li.classList.remove('active'));
  const kind = job ? job.kind : 'build';
  if (result === 'complete') {
    appendLog(t('build.complete'));
    if (job) { job.stages.forEach(n => job.done.add(n)); drawProgress(); }
    showDone(kind, path);
    refreshStatus().catch(() => {});
    return;
  }
  $('stop').hidden = true;
  $('build-back').hidden = false;
  $('build-retry').hidden = false;
  const text = result === 'stopped' ? t('build.stopped') : `${t('build.failed')}: ${error || ''}`;
  appendLog(text);
  $('build-error').replaceChildren(el('p', { className: `note ${result === 'stopped' ? 'info' : 'bad'}`, textContent: text }));
  if (result !== 'stopped') $('log-box').open = true;
}

// The country's PBF, with its size and time, before it is downloaded (the user's choice).
function showPbfOffer(offer) {
  showCard('pbf');
  $('pbf-lead').textContent = t(offer.lead);
  $('pbf-reason').textContent = offer.reason || '';
  $('pbf-reason').hidden = !offer.reason;
  $('pbf-file').textContent = offer.name || (state.place && state.place.name) || '—';
  $('pbf-size').textContent = offer.pbf_bytes ? t('pbf.mb', Math.round(offer.pbf_bytes / 2 ** 20).toLocaleString()) : t('pbf.unknown');
  const s = offer.pbf_seconds;
  $('pbf-time').textContent = s ? `${duration(s * 0.5)}–${duration(s * 2.5)}` : '—';
}

function needsPbf(message) {
  setBuilding(false);
  clearInterval(elapsedTimer);
  appendLog(`${t('build.needsPbf')} ${message.reason || ''}`);
  refreshStatus().catch(() => {});           // the planet may have been installed before Overpass was asked
  const big = /^the area is/.test(message.reason || '');
  showPbfOffer({ lead: big ? 'pbf.bigLead' : 'pbf.busyLead', reason: big ? '' : message.reason,
    name: message.name, pbf_bytes: message.pbf_bytes, pbf_seconds: message.pbf_seconds });
}

function showDone(kind, path) {
  showCard('done');
  const planet = kind === 'install_planet';
  $('done-title').textContent = t(planet ? 'done.planetTitle' : 'done.title');
  $('done-body').textContent = planet ? t('done.planetBody') : t('done.body', job && job.name);
  $('done-path').textContent = path || '';
  $('launch-game').hidden = planet;
  $('done-another').textContent = t(planet ? 'build.back' : 'done.another');
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
  drawEdits();
  if (project.selection.box) {
    const b = project.selection.box;
    map.fitBounds([[b[1], b[0]], [b[3], b[2]]], { padding: [40, 40] });
    await selectBox(b, project.title);
    $('project-title').value = project.title || project.id;
    state.projectId = project.id;
  }
}

// ------------------------------------------------------------------ status, settings
function setupRow(ok, text, action, onAction) {
  const row = [el('span', { className: `mark ${ok === true ? 'ok' : ok === false ? 'bad' : 'info'}`, textContent: ok === true ? '✓' : ok === false ? '!' : '↓' }),
    el('span', { className: 'grow', textContent: text })];
  if (action) row.push(Object.assign(el('button', { className: 'link', textContent: action }), { onclick: onAction }));
  return row;
}

async function refreshStatus() {
  const s = await call('status');
  state.status = s;
  const planet = s.planet;
  const need = planetNeeded();
  $('st-game').innerHTML = '';
  $('st-game').append(el('span', { className: s.game_folder_ok ? 'ok' : 'bad', textContent: s.game_folder_ok ? `● ${t('game.ok')}` : `● ${t('game.missing')}` }));
  $('st-planet').textContent = need === 'old' ? t('setup.planetOld', planet.version) : need ? t('setup.planetMissing') : t('planet.ok', planet.version || '?');
  $('st-planet').className = need ? 'pending' : 'ok';
  $('st-disk').textContent = s.free_gb != null ? t('disk.free', s.free_gb) : '';

  $('setup-game').replaceChildren(...setupRow(s.game_folder_ok, t(s.game_folder_ok ? 'setup.gameOk' : 'setup.gameMissing'),
    t(s.game_folder_ok ? 'setup.change' : 'setup.gameFix'), () => showSection('settings')));
  $('setup-game').title = s.mods;
  $('setup-planet').replaceChildren(...setupRow(need ? null : true,
    need === 'old' ? t('setup.planetOld', planet.version) : need ? t('setup.planetMissing') : t('setup.planetOk', planet.version || '?'),
    need && s.game_folder_ok && !state.building ? t('setup.planetNow') : null, installPlanet));
  $('setup').classList.toggle('attention', !s.game_folder_ok);

  $('game-folders').replaceChildren(...[...new Set([s.mods, ...s.folders])].map(f => el('option', { value: f, textContent: f, selected: f === s.mods })));
  $('game-folder-state').textContent = s.game_folder_ok ? '✓' : t('game.missingBody');
  $('planet-state').textContent = planet.installed ? `${t('planet.ok', planet.version || '?')} — ${planet.path}` : t('planet.missing');
  $('planet-install').textContent = t(planet.installed ? 'planet.update' : 'planet.install');
  $('home-path').textContent = s.home;
  $('about').textContent = `EarthNG ${s.build.version || 'dev'}${s.build.sourceCommit ? ' · ' + s.build.sourceCommit.slice(0, 7) : ''}`;
  if (s.busy && !state.building) setBuilding(true);
  renderNotes();
  updateBuildButton();
}

async function installPlanet() {
  showSection('map');
  const back = state.place ? 'area' : 'empty';
  startProgress('install_planet', ['Planet']);
  job.back = back;
  onStage('Planet', null);
  try {
    await call('install_planet');
    jobStarted();
  } catch (err) {
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
// Typing filters Geofabrik regions locally; Enter asks OpenStreetMap's Nominatim for towns and
// addresses, once per Enter (its usage policy forbids search-as-you-type).
let searchTimer = null;
function regionItem(p, list) {
  const li = el('li', {}, el('div', { textContent: p.name }), el('div', { className: 'parent', textContent: p.parent || '' }));
  li.onclick = () => { list.hidden = true; $('search').value = p.name; clearArea(); showCard('area'); $('area-km2').textContent = '—'; choosePlace(p, true).then(updateBuildButton); };
  return li;
}
// A found town becomes the selection when it is a sensible map size; an address or a point gets
// a 2 x 2 km box around it; a whole country or state is only shown, to be boxed by hand.
function geoBox(r) {
  let [w, s, e, n] = r.bounds;
  const kmX = (e - w) * 111.32 * Math.cos((s + n) / 2 * Math.PI / 180), kmY = (n - s) * 110.57;
  if (kmX < 2 && kmY < 2) {
    const dy = 1 / 110.57, dx = 1 / (111.32 * Math.cos(r.lat * Math.PI / 180));
    [w, s, e, n] = [r.lon - dx, r.lat - dy, r.lon + dx, r.lat + dy];
  }
  return { box: [w, s, e, n].map(v => +v.toFixed(6)), km2: kmX * kmY };
}
function geoItem(r, list) {
  const [head, ...rest] = r.name.split(', ');
  const li = el('li', {}, el('div', { textContent: head }), el('div', { className: 'parent', textContent: rest.join(', ') }));
  li.onclick = () => {
    list.hidden = true;
    $('search').value = head;
    const { box, km2 } = geoBox(r);
    map.fitBounds([[box[1], box[0]], [box[3], box[2]]], { padding: [40, 40] });
    if (km2 <= 2500) selectBox(box, head);
  };
  return li;
}
$('search').addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(async () => {
    const query = $('search').value.trim();
    const list = $('search-results');
    if (!query) { list.hidden = true; return; }
    try {
      const { places } = await call('places', { query, limit: 30 });
      list.replaceChildren(...places.map(p => regionItem(p, list)), el('li', { className: 'muted hint-row', textContent: t('search.enter') }));
      list.hidden = false;
    } catch (err) {
      list.replaceChildren(el('li', { className: 'muted', textContent: err.message }));
      list.hidden = false;
    }
  }, 250);
});
$('search').addEventListener('keydown', async e => {
  if (e.key !== 'Enter') return;
  clearTimeout(searchTimer);
  const query = $('search').value.trim();
  const list = $('search-results');
  if (!query) return;
  list.replaceChildren(el('li', { className: 'muted', textContent: t('search.looking') }));
  list.hidden = false;
  try {
    const [{ results }, { places }] = await Promise.all([call('geocode', { query, lang: LANG }), call('places', { query, limit: 10 })]);
    const rows = [];
    if (results.length) rows.push(el('li', { className: 'group', textContent: t('search.found') }), ...results.map(r => geoItem(r, list)));
    if (places.length) rows.push(el('li', { className: 'group', textContent: t('search.regions') }), ...places.map(p => regionItem(p, list)));
    if (!rows.length) rows.push(el('li', { className: 'muted', textContent: t('search.none') }));
    list.replaceChildren(...rows);
  } catch (err) {
    list.replaceChildren(el('li', { className: 'muted', textContent: err.message }));
  }
});
document.addEventListener('click', e => { if (!e.target.closest('.search')) $('search-results').hidden = true; });

// ------------------------------------------------------------------ layout
function showCard(name) {
  ['empty', 'area', 'pbf', 'build', 'done'].forEach(n => { $(`card-${n}`).hidden = n !== name; });
}

function showSection(name) {
  document.querySelectorAll('.rail-btn[data-section]').forEach(b => b.classList.toggle('active', b.dataset.section === name));
  document.querySelectorAll('[data-panel]').forEach(p => { p.hidden = p.dataset.panel !== name; });
  if (name === 'projects') listProjects();
  if (name === 'settings') refreshStatus();
}

async function renderRecent() {
  try {
    const { projects } = await call('projects');
    const recent = projects.slice(-4).reverse();
    $('recent').replaceChildren(...(recent.length ? [el('h3', { textContent: t('empty.recent') }),
      el('div', { className: 'chips' }, recent.map(p => Object.assign(el('button', { className: 'chip', textContent: p.title }), { onclick: () => openProject(p.id) })))] : []));
  } catch (err) { /* no projects yet */ }
}

function backFromJob() {
  const back = job && job.back;
  showCard(back || (state.place ? 'area' : 'empty'));
}

// ------------------------------------------------------------------ events from the service
listeners.push(message => {
  if (message.event === 'log') appendLog(message.text);
  else if (message.event === 'stage') onStage(message.name, message.seconds);
  else if (message.event === 'done' && message.result === 'needs_pbf') needsPbf(message);
  else if (message.event === 'done') finishBuild(message.result, message.error, message.path);
  else if (message.event === 'ready') refreshStatus().catch(() => {});
  else if (message.event === 'service_exit') {
    setBuilding(false);
    $('banner').replaceChildren(el('div', { className: 'banner bad' }, el('p', { textContent: t('service.down') })));
  }
});

// ------------------------------------------------------------------ wiring
document.querySelectorAll('.rail-btn[data-section]').forEach(b => { b.onclick = () => showSection(b.dataset.section); });
$('tool-box').onclick = () => setMode('box');
$('tool-edit').onclick = () => setMode('edit');
$('empty-draw').onclick = () => { if (state.mode !== 'box') setMode('box'); };
$('area-clear').onclick = clearArea;
$('build').onclick = () => build(false);
$('pbf-go').onclick = () => build(true);
$('pbf-back').onclick = () => showCard(state.place ? 'area' : 'empty');
$('save-project').onclick = () => saveProject(false);
$('stop').onclick = () => call('stop').catch(() => {});
$('build-back').onclick = backFromJob;
$('build-retry').onclick = () => (job && job.kind === 'install_planet' ? installPlanet() : build(!!(job && job.allowPbf)));
$('open-mods').onclick = () => call('open_folder', { which: 'mods' }).catch(() => {});
$('launch-game').onclick = () => call('open_url', { url: 'steam://rungameid/284160' }, 'app').catch(() => {});
$('done-another').onclick = () => { if (job && job.kind === 'install_planet') backFromJob(); else clearArea(); };
$('open-home').onclick = () => call('open_folder', { which: 'home' }).catch(() => {});
$('planet-install').onclick = installPlanet;
$('game-folders').onchange = e => setGameFolder(e.target.value);
$('game-folder-set').onclick = () => setGameFolder($('game-folder').value.trim());
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  if (dragStart) { dragStart = null; if (boxLayer && !state.box) { boxLayer.remove(); boxLayer = null; } }
  if (state.mode) setMode(state.mode);
});
$('lang').onclick = () => {
  LANG = LANG === 'uk' ? 'en' : 'uk';
  try { localStorage.setItem('lang', LANG); } catch (e) { /* storage off */ }
  $('lang').textContent = LANG === 'uk' ? 'УК' : 'EN';
  applyI18n(); renderOptions(); drawEdits(); setMode(state.mode); setMode(state.mode);
  refreshStatus().catch(() => {}); renderRecent();
  if (state.box || state.place) $('area-title').textContent = areaName();
};
$('lang').textContent = LANG === 'uk' ? 'УК' : 'EN';
applyI18n();
drawEdits();
showCard('empty');
refreshStatus().catch(() => {});
renderRecent();
