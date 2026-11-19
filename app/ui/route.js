// Coordinates in files and in the service protocol are [longitude, latitude].
function readRoute(text) {
  const invalid = () => new Error(t('route.invalid'));
  let coordinates;
  if (text.trimStart().startsWith('<')) {
    const xml = new DOMParser().parseFromString(text, 'application/xml');
    const paths = [...xml.getElementsByTagNameNS('*', 'trkseg'), ...xml.getElementsByTagNameNS('*', 'rte')];
    if (xml.documentElement.localName !== 'gpx' || paths.length !== 1) throw invalid();
    const pointName = paths[0].localName === 'rte' ? 'rtept' : 'trkpt';
    coordinates = Array.from(paths[0].children).filter(p => p.localName === pointName).map(p =>
      ['lon', 'lat'].map(key => p.getAttribute(key)?.trim() ? Number(p.getAttribute(key)) : NaN));
  } else {
    let geometry;
    try { geometry = JSON.parse(text); } catch { throw invalid(); }
    if (geometry?.type === 'FeatureCollection' && geometry.features?.length === 1) geometry = geometry.features[0];
    if (geometry?.type === 'Feature') geometry = geometry.geometry;
    if (geometry?.type !== 'LineString' || !Array.isArray(geometry.coordinates)) throw invalid();
    coordinates = geometry.coordinates;
  }
  const points = [];
  for (const point of coordinates) {
    if (!Array.isArray(point) || !Number.isFinite(point[0]) || !Number.isFinite(point[1])
      || Math.abs(point[0]) > 180 || Math.abs(point[1]) > 90) throw invalid();
    const last = points.at(-1);
    if (!last || last[0] !== point[0] || last[1] !== point[1]) points.push([point[0], point[1]]);
  }
  if (points.length < 2) throw invalid();
  return points;
}

function routeLatLngs(points) {
  let previous = map.getCenter().lng;
  return points.map(([lon, lat]) => {
    previous = lon + 360 * Math.round((previous - lon) / 360);
    return [lat, previous];
  });
}

let routeDraft = null;
let routeLayer = null;

function paintRoute(points) {
  routeLayer?.remove();
  routeLayer = L.layerGroup().addTo(map);
  if (!points?.length) return;
  const line = routeLatLngs(points);
  const color = getComputedStyle(document.body).getPropertyValue('--edit').trim();
  L.polyline(line, { color, weight: 3, interactive: false }).addTo(routeLayer);
  // The endpoints suffice for a GPS track with thousands of samples.
  for (const point of line.length > 100 ? [line[0], line.at(-1)] : line) {
    L.circleMarker(point, { color, radius: 4, fillOpacity: 1, interactive: false }).addTo(routeLayer);
  }
}

function refreshRouteDraft() {
  paintRoute(routeDraft.points);
  $('route-count').textContent = t('route.count', routeDraft.points.length);
  $('route-undo').disabled = !routeDraft.points.length;
  $('route-use').disabled = routeDraft.points.length < 2;
  $('route-error').hidden = true;
}

function startRoute() {
  if (state.building) return;
  if (routeDraft) { cancelRoute(); return; }
  routeDraft = { points: [...(state.selection?.route || [])], name: state.selection?.route ? state.areaName : null };
  $('route-width').value = String(state.selection?.width_km || 10);
  boxLayer?.remove();
  boundaryLayer?.remove();
  showSection('map');
  showCard('route');
  setMode('route');
  refreshRouteDraft();
}

function cancelRoute() {
  routeDraft = null;
  if (state.mode === 'route') setMode('route');
  boxLayer?.addTo(map);
  boundaryLayer?.addTo(map);
  paintRoute(state.selection?.route);
  showCard(state.selection || state.place ? 'area' : 'empty');
}

function addRoutePoint(lon, lat) {
  const draft = routeDraft;
  if (!draft) return;
  const point = [+L.Util.wrapNum(lon, [-180, 180], true).toFixed(7), +lat.toFixed(7)];
  const last = draft.points.at(-1);
  if (!last || last[0] !== point[0] || last[1] !== point[1]) draft.points.push(point);
  refreshRouteDraft();
}

function useRoute() {
  if (!routeDraft || routeDraft.points.length < 2) return;
  const { points, name } = routeDraft;
  if (!state.selection?.route) clearArea();
  routeDraft = null;
  if (state.mode === 'route') setMode('route');
  selectArea({ route: points, width_km: Number($('route-width').value) }, name);
}

async function importRoute(file) {
  const draft = routeDraft;
  if (!draft || !file) return;
  try {
    const points = readRoute(await file.text());
    if (draft !== routeDraft) return;
    draft.points = points;
    draft.name = file.name.replace(/\.[^.]*$/, '');
    map.fitBounds(L.latLngBounds(routeLatLngs(points)), { padding: [40, 40] });
    refreshRouteDraft();
  } catch (err) {
    if (draft !== routeDraft) return;
    $('route-error').textContent = err.message;
    $('route-error').hidden = false;
  }
}
