-- EarthNG planet level; active only in e2r_world. Native mode discovers mounted
-- country source packs, generates 500m tiles in Lua and streams them over several
-- frames. See docs/NATIVE_MODS.md. Native is the only supported release runtime.
local M = {}
local loadNewMaterials
local AP = nil   -- autopilot state (route test); read by writePose for the route ahead
local im = ui_imgui
local imguiUtils = require('ui/imguiUtils')
local ffi = require('ffi')
local logTag = 'e2r_world'
local LANG = 'uk'   -- build_mod.py --lang en rewrites this line (the English packages: UK, California, New York)
local NATIVE = true   -- fixed for releases; protocol stubs remain for isolated widget tests
local native = NATIVE and require('ge/extensions/e2r/native') or nil
-- On M, not a chunk local: this file is already at LuaJIT's 200-local limit.
M.live = (function()
  local ok, mod = pcall(require, 'ge/extensions/e2r/live')
  if ok and type(mod) == 'table' and type(mod.request) == 'function' then return mod end
end)()
local planetMap = NATIVE and require('ge/extensions/e2r/planetMap') or nil
local quality = require('ge/extensions/e2r/quality')
local detail = require('ge/extensions/e2r/detail')
local collision = require('ge/extensions/e2r/collision')
local parking = require('ge/extensions/e2r/parking')
M.fifo = require('ge/extensions/e2r/fifo') -- keep below LuaJIT's 200 chunk locals
M.brandStyles = NATIVE and require('ge/extensions/e2r/generator').BRANDS or {}
-- the route to a point picked on the map (docs/NAVIGATION.md); on M for the same reason
M.navigator = NATIVE and require('ge/extensions/e2r/navigator') or nil
M.location = NATIVE and require('ge/extensions/e2r/location') or nil
M.signals = NATIVE and require('ge/extensions/e2r/signals') or nil
if M.signals and not M.signals.step then M.signals = nil end
if M.navigator then M.navigator.source = native end
M.gc = require('ge/extensions/e2r/gc')   -- the collector's step while in the level (gc.lua)
-- the settings registry shared by the widget and the game's UI app (options.lua, docs/INGAME_UI.md);
-- nil where a test stubs require
M.options = (function()
  local o = require('ge/extensions/e2r/options')
  if type(o) == 'table' and rawget(o, 'REGISTRY') == true then return o end
end)()
M.flowSim = require('ge/extensions/e2r/flow')   -- cars without physics, hundreds of them (flow.lua)
M.handoffSim = require('ge/extensions/e2r/handoff')   -- real cars in their place round the player
M.walkSim = require('ge/extensions/e2r/walkers')   -- pedestrians on the sidewalks, no physics (walkers.lua)
M.pedHit = require('ge/extensions/e2r/pedhit')   -- a physical body in a walker's place before a hit
M.knock = require('ge/extensions/e2r/knock')   -- street furniture a vehicle knocks down (knock.lua)
M.winguard = require('ge/extensions/e2r/winguard')   -- widget windows stay on the game screen (winguard.lua)
M.far = NATIVE and require('ge/extensions/e2r/far') or nil   -- the land to the horizon (far.lua)
-- the gate: scene changes while driving only after calm frames, one a frame, in bursts (pace.lua)
M.pace = require('ge/extensions/e2r/pace')
local detailStream
-- the UI language: the package's LANG until the player switches it (settings/earthng.json)
local LANG_FILE = 'settings/earthng.json'
local lang = LANG
local function L(uk, en) return lang == 'en' and en or uk end
local function loadLang()
  local ok, cfg = pcall(jsonReadFile, LANG_FILE)
  if ok and type(cfg) == 'table' and (cfg.lang == 'uk' or cfg.lang == 'en') then lang = cfg.lang end
end
local function setLang(l)
  lang = l
  local ok, cfg = pcall(jsonReadFile, LANG_FILE)
  cfg = ok and type(cfg) == 'table' and cfg or {}
  cfg.lang = l
  pcall(jsonWriteFile, LANG_FILE, cfg, true)
end

local W, H = 720, 440          -- map picture size, px
local BUDGET_MS = 4            -- spawn work per frame
local CAM_HIGH, CAM_LOW = 350, 28
local LOAD_R, UNLOAD_R = 800, 1250   -- tile centre distance from the car, m
local COLLISION_EVERY = 2.0          -- s between batched reloadCollision calls
local LAMP_SHAPE = '/art/shapes/objects/lamp1.dae'   -- fast_style.LAMP
local PRESETS = {
  {'Оболонь', 50.5070, 30.4990, 'ukraine', 'Obolon'}, {'Поділ', 50.4655, 30.5170, 'ukraine', 'Podil'},
  {'Хрещатик', 50.4475, 30.5225, 'ukraine', 'Khreshchatyk'}, {'Печерськ', 50.4280, 30.5410, 'ukraine', 'Pechersk'},
  {'Голосіїв', 50.3920, 30.5080, 'ukraine', 'Holosiiv'}, {'Біличі', 50.4775, 30.3600, 'ukraine', 'Bilychi'},
  -- (the 5th field: the English name; the rest of the presets are English already)
  -- Kyiv oblast towns (data/osm_tiles/ukraine-260918)
  {'Ірпінь', 50.5210, 30.2500, 'ukraine', 'Irpin'}, {'Бровари', 50.5110, 30.7900, 'ukraine', 'Brovary'},
  {'Бориспіль', 50.3520, 30.9550, 'ukraine', 'Boryspil'}, {'Фастів', 50.0780, 29.9180, 'ukraine', 'Fastiv'},
  {'Біла Церква', 49.7960, 30.1150, 'ukraine', 'Bila Tserkva'},
  -- oblast centres (data/osm_tiles/ukraine-260918)
  {'Львів', 49.8400, 24.0280, 'ukraine', 'Lviv'}, {'Одеса', 46.4800, 30.7300, 'ukraine', 'Odesa'},
  {'Харків', 49.9900, 36.2300, 'ukraine', 'Kharkiv'}, {'Дніпро', 48.4650, 35.0460, 'ukraine', 'Dnipro'},
  {'Запоріжжя', 47.8390, 35.1400, 'ukraine', 'Zaporizhzhia'}, {'Вінниця', 49.2330, 28.4680, 'ukraine', 'Vinnytsia'},
  {'Житомир', 50.2550, 28.6590, 'ukraine', 'Zhytomyr'}, {'Чернігів', 51.4980, 31.2890, 'ukraine', 'Chernihiv'},
  {'Полтава', 49.5880, 34.5510, 'ukraine', 'Poltava'}, {'Черкаси', 49.4440, 32.0600, 'ukraine', 'Cherkasy'},
  {'Ужгород', 48.6210, 22.2880, 'ukraine', 'Uzhhorod'}, {'Чернівці', 48.2920, 25.9400, 'ukraine', 'Chernivtsi'},
  {'Івано-Франківськ', 48.9230, 24.7110, 'ukraine', 'Ivano-Frankivsk'}, {'Луцьк', 50.7470, 25.3250, 'ukraine', 'Lutsk'},
  -- California (data/osm_tiles/california-261013; an English package)
  {'Los Angeles', 34.0505, -118.2475, 'california'}, {'Hollywood', 34.1015, -118.3265, 'california'},
  {'Santa Monica', 34.0160, -118.4925, 'california'}, {'San Francisco', 37.7880, -122.4075, 'california'},
  {'San Diego', 32.7150, -117.1610, 'california'}, {'Sacramento', 38.5780, -121.4920, 'california'},
  {'San Jose', 37.3360, -121.8900, 'california'}, {'Fresno', 36.7390, -119.7860, 'california'},
  {'Palm Springs', 33.8250, -116.5420, 'california'}, {'Big Sur', 36.2700, -121.8070, 'california'},
  {'Lake Tahoe', 38.9350, -119.9800, 'california'}, {'Death Valley', 36.4600, -116.8700, 'california'},
  -- United Kingdom: the whole country (united-kingdom-*) or a regional package (uk-<region>-*, its
  -- status.area); the 4th field is the region, one row each
  {'London', 51.5080, -0.1281, 'uk-london-south-east'}, {'Brighton', 50.8225, -0.1372, 'uk-london-south-east'},
  {'Oxford', 51.7520, -1.2577, 'uk-london-south-east'}, {'Cambridge', 52.2053, 0.1218, 'uk-london-south-east'},
  {'Canterbury', 51.2802, 1.0789, 'uk-london-south-east'}, {'Dover', 51.1279, 1.3134, 'uk-london-south-east'},
  {'Windsor', 51.4839, -0.6044, 'uk-london-south-east'}, {'Portsmouth', 50.7989, -1.0912, 'uk-london-south-east'},
  {'Bristol', 51.4545, -2.5879, 'uk-south-west'}, {'Bath', 51.3811, -2.3590, 'uk-south-west'},
  {'Exeter', 50.7184, -3.5339, 'uk-south-west'}, {'Plymouth', 50.3714, -4.1422, 'uk-south-west'},
  {'St Ives', 50.2110, -5.4800, 'uk-south-west'}, {'Cheddar Gorge', 51.2830, -2.7600, 'uk-south-west'},
  {'Stonehenge', 51.1789, -1.8262, 'uk-south-west'}, {'Birmingham', 52.4796, -1.9026, 'uk-central-england'},
  {'Manchester', 53.4794, -2.2453, 'uk-central-england'}, {'Liverpool', 53.4058, -2.9800, 'uk-central-england'},
  {'Nottingham', 52.9536, -1.1505, 'uk-central-england'}, {'Sheffield', 53.3811, -1.4701, 'uk-central-england'},
  {'Peak District', 53.3440, -1.7770, 'uk-central-england'}, {'Chester', 53.1905, -2.8900, 'uk-central-england'},
  {'Leicester', 52.6369, -1.1398, 'uk-central-england'}, {'Leeds', 53.7965, -1.5478, 'uk-north-england'},
  {'Newcastle', 54.9738, -1.6132, 'uk-north-england'}, {'York', 53.9590, -1.0815, 'uk-north-england'},
  {'Durham', 54.7761, -1.5733, 'uk-north-england'}, {'Lake District', 54.6013, -3.1347, 'uk-north-england'},
  {'Whitby', 54.4858, -0.6206, 'uk-north-england'}, {'Cardiff', 51.4816, -3.1791, 'uk-wales'},
  {'Swansea', 51.6214, -3.9436, 'uk-wales'}, {'Snowdonia', 53.1190, -4.1290, 'uk-wales'},
  {'Aberystwyth', 52.4153, -4.0829, 'uk-wales'}, {'Conwy', 53.2800, -3.8300, 'uk-wales'},
  {'Brecon Beacons', 51.9460, -3.3920, 'uk-wales'}, {'Belfast', 54.5973, -5.9301, 'uk-northern-ireland'},
  {'Derry', 54.9966, -7.3086, 'uk-northern-ireland'}, {"Giant's Causeway", 55.2408, -6.5116, 'uk-northern-ireland'},
  {'Enniskillen', 54.3438, -7.6315, 'uk-northern-ireland'},
  {'Newcastle (NI)', 54.2180, -5.8880, 'uk-northern-ireland'}, {'Glasgow', 55.8609, -4.2514, 'uk-south-scotland'},
  {'Edinburgh', 55.9520, -3.1960, 'uk-south-scotland'}, {'Stirling', 56.1165, -3.9369, 'uk-south-scotland'},
  {'Ayr', 55.4586, -4.6292, 'uk-south-scotland'}, {'Dumfries', 55.0700, -3.6050, 'uk-south-scotland'},
  {'Loch Lomond', 56.1010, -4.6380, 'uk-south-scotland'}, {'Aberdeen', 57.1497, -2.0943, 'uk-scotland-east'},
  {'Dundee', 56.4620, -2.9707, 'uk-scotland-east'}, {'Inverness', 57.4778, -4.2247, 'uk-scotland-east'},
  {'Perth', 56.3950, -3.4310, 'uk-scotland-east'}, {'Cairngorms', 57.1950, -3.8250, 'uk-scotland-east'},
  {"John o' Groats", 58.6373, -3.0689, 'uk-scotland-east'}, {'Glencoe', 56.6826, -5.1023, 'uk-scotland-west'},
  {'Fort William', 56.8198, -5.1052, 'uk-scotland-west'}, {'Oban', 56.4150, -5.4720, 'uk-scotland-west'},
  {'Isle of Skye', 57.4125, -6.1946, 'uk-scotland-west'}, {'Ullapool', 57.8960, -5.1590, 'uk-scotland-west'},
  {'Stornoway', 58.2090, -6.3880, 'uk-scotland-west'},
  -- New York State (data/osm_tiles/new-york-*; an English package): the city, then the state
  {'Times Square', 40.7580, -73.9855, 'new-york'}, {'Wall Street', 40.7069, -74.0113, 'new-york'},
  {'Central Park', 40.7680, -73.9819, 'new-york'}, {'Brooklyn', 40.6928, -73.9903, 'new-york'},
  {'Queens', 40.7447, -73.9485, 'new-york'}, {'The Bronx', 40.8270, -73.9260, 'new-york'},
  {'Staten Island', 40.6437, -74.0736, 'new-york'}, {'Montauk', 41.0359, -71.9545, 'new-york'},
  {'Albany', 42.6526, -73.7562, 'new-york'}, {'Buffalo', 42.8864, -78.8784, 'new-york'},
  {'Niagara Falls', 43.0896, -79.0636, 'new-york'}, {'Rochester', 43.1566, -77.6088, 'new-york'},
  {'Syracuse', 43.0481, -76.1474, 'new-york'}, {'Lake Placid', 44.2795, -73.9799, 'new-york'},
  -- Zanzibar (data/osm_tiles/zanzibar-*; an English package): Unguja, then Pemba
  {'Stone Town', -6.1630, 39.1910, 'zanzibar'}, {'Nungwi', -5.7266, 39.2970, 'zanzibar'},
  {'Kendwa', -5.7530, 39.2930, 'zanzibar'}, {'Paje', -6.2650, 39.5350, 'zanzibar'},
  {'Jambiani', -6.3150, 39.5450, 'zanzibar'}, {'Jozani Forest', -6.2610, 39.4130, 'zanzibar'},
  {'Chake Chake', -5.2460, 39.7690, 'zanzibar'}, {'Wete', -5.0570, 39.7280, 'zanzibar'},
  {'Mkoani', -5.3700, 39.6440, 'zanzibar'},
  -- Romania (data/osm_tiles/romania-*; an English package)
  {'Bucharest', 44.4355, 26.1025, 'romania'}, {'Cluj-Napoca', 46.7695, 23.5899, 'romania'},
  {'Timisoara', 45.7537, 21.2257, 'romania'}, {'Iasi', 47.1620, 27.5890, 'romania'},
  {'Brasov', 45.6427, 25.5887, 'romania'}, {'Constanta', 44.1733, 28.6383, 'romania'},
  {'Sibiu', 45.7975, 24.1522, 'romania'}, {'Sighisoara', 46.2190, 24.7920, 'romania'},
  {'Oradea', 47.0570, 21.9290, 'romania'}, {'Craiova', 44.3190, 23.7967, 'romania'},
  {'Transfagarasan', 45.6030, 24.6170, 'romania'}, {'Bran Castle', 45.5150, 25.3672, 'romania'},
  {'Tulcea', 45.1790, 28.8050, 'romania'},
}
local S = {
  widgetHidden = false, pickerOpen = false,
  state = 'off', center = {lat = 50.4501, lon = 30.5234}, zoom = 11, marker = nil,
  seq = 0, viewDirty = true, lastViewAt = -1, tex = nil, texView = nil, status = nil,
  statusReadAt = -1, landSeq = nil, landAt = nil, now = 0, frames = {},
  tiles = {}, far = {}, horizon = {}, queue = {}, nav = {}, navPending = {}, poseAt = -1, collisionDirty = false, collisionAt = -1, knownMats = {},
}
local coordBuf = im.ArrayChar(64)
local test, result = nil, {status = 'waiting', shots = {}}
local frameTimer = hptimer()
-- Streaming limits; see the comments where each is used.
-- sceneLag: s, a scene item queues as the road of a tile reached this much later (its grass 3x)
local LIMIT = {pairsDriving = 3, pairsLanding = 24, plantBatch = 128, sceneLag = 3,
  forestStep = 0.12, forestKind = 1.5, forestMax = 2500, propMax = 600,
  -- Trees of one shape split into forestVariants^2 kinds by cells of forestCell m (0: off), and a
  -- commit takes kinds until forestLive crowns stand in them (see forestCommit)
  forestCell = 1000, forestVariants = 3, forestLive = 6000,
  -- kinds joining the first one: at most this many more, while the commit has taken under
  -- forestJoinCalls engine calls and forestJoinMs (79 kinds and 2500 calls in one commit were
  -- 51 ms of Lua at a landing, far-view-06)
  forestJoinKinds = 3, forestJoinCalls = 400, forestJoinMs = 4,
  collisionWant = 200, collisionLead = 4, collisionSceneLead = 2.5, collisionMargin = 200, vehicleCollision = {100, 300}, otherCars = {80, 160},
  collisionScene = {fast = 15, ahead = 1.5, want = 1, side = 100, margin = 100,
    roadSide = 120, roadKeep = 200, roadLane = 120, roadStep = 100},
  roadAhead = 18, roadUrgent = 8, roadFloorMs = 2.5,
  -- the spawn budget of a frame the gate opens (it opens every QUIET + 1 frames at most): the
  -- trickle of BUDGET_MS a frame in one go, the engine's cost of it landing in a single frame
  burstMs = 20,
  -- Until the car stands on the road (the landing: the player waits and the camera hangs still)
  -- the generator and the spawn queue take most of the frame instead of BUDGET_MS: at 4 ms a
  -- frame the nine tiles of a landing in central Kyiv took 82 s, most of them idle. 60 ms: the
  -- tiles were ready in 18.6 s at 40 ms a frame and in 17.4 s at 90 (the picker at 6 frames a second)
  loadNativeMs = 60, loadQueueMs = 14, loadQueueLastMs = 30}
-- Read-only view for the development probe (earthng/probe.py); nothing in the mod calls it.
function M.dbg() return {S = S, result = result, native = native, detail = detailStream, test = test} end

-- the 4th field of a preset: the tile package area it belongs to (status.area, the tile folder's
-- name without the date); a UK region also belongs to the whole united-kingdom package
local function presetArea(tag)
  return tag:match('^uk%-') and 'united-kingdom' or tag
end
local KNOWN_AREAS = {}
for _, p in ipairs(PRESETS) do KNOWN_AREAS[p[4]] = true; KNOWN_AREAS[presetArea(p[4])] = true end

-- only the presets of the companion's OSM package: by its area when the buttons know it (the
-- Ukraine box holds Bucharest, the Wales box Bristol), else inside status.packageBox, so a
-- California package does not offer Kyiv
local function presetInPackage(p)
  if NATIVE then return native.at(p[2], p[3]) ~= nil end
  local area = S.status and S.status.area
  if p[4] and area and KNOWN_AREAS[area] then return p[4] == area or presetArea(p[4]) == area end
  local box = S.status and S.status.packageBox
  if NATIVE and not box and not S.centredOnPackage then
    S.center, S.zoom, S.centredOnPackage = {lat = 20, lon = 0}, 2, true
  end
  return not box or (p[3] >= box[1] and p[2] >= box[2] and p[3] <= box[3] and p[2] <= box[4])
end

-- --- helpers -------------------------------------------------------------------------------------
local function merc(lat, lon, z)
  local n = 256 * 2 ^ z
  local s = math.sin(math.rad(math.max(-85.05, math.min(85.05, lat))))
  return (lon + 180) / 360 * n, (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n
end

local function unmerc(x, y, z)
  local n = 256 * 2 ^ z
  local m = math.pi * (1 - 2 * y / n)
  return math.deg(math.atan(0.5 * (math.exp(m) - math.exp(-m)))), x / n * 360 - 180
end

local function saveResult()
  if test then jsonWriteFile('e2r-world-result.json', result, true) end
end

local function shot(name)
  if not test then return end
  createScreenshot2({filename = 'screenshots/e2r-' .. name, writeJPG = false, superSampling = 1})
  table.insert(result.shots, name)
  -- what the picture was taken under (pack looks vary run to run: exposure, night sky)
  pcall(function()
    local lx, sky = scenetree.findObject('PostEffectLocalExposureObject'), scenetree.findObject('sunsky')
    result.shotState = result.shotState or {}
    result.shotState[name] = {lx and tostring(lx.autoExposure), lx and lx.manualEV,
                              sky and sky:getField('nightCubemap', 0), sky and sky:getField('useNightCubemap', 0),
                              sky and sky:getField('elevation', 0)}
  end)
  -- the streaming state at the picture: a view without its ground says what held the loads
  pcall(function()
    local st = S.status and S.status.stream or {}
    local function n(t) local c = 0; for _ in pairs(t or {}) do c = c + 1 end; return c end
    local near, far = 0, 0
    for _, due in pairs(st.wanted or {}) do if due < 1e6 then near = near + 1 else far = far + 1 end end
    local g = S.graves and S.graves[1]
    local head = g and g:getCount() > 0 and g:getObject(g:getCount() - 1)
    result.shotStream = result.shotStream or {}
    result.shotStream[name] = {graves = S.graves and #S.graves or 0, graveHead = g and g:getCount() or nil,
      graveClass = head and head:getClassName() or nil, queue = #(S.queue or {}), tiles = n(S.tiles),
      far = n(S.far), ready = n(st.ready), stFar = n(st.far), wantNear = near, wantFar = far,
      cached = st.cachedTiles, camDist = S.camDist}
  end)
end

local function request(tbl)
  S.seq = S.seq + 1
  tbl.seq = S.seq
  if NATIVE then
    if tbl.type == 'land' then
      -- Objects saved from the World Editor this session stand in the old landing's frame.
      -- The new landing's tiles bring them back from the saved records where they belong.
      local saved = scenetree and scenetree.findObject and scenetree.findObject('E2R_editor')
      if saved then saved:deleteAllObjects(); saved:delete() end
      native.land(tbl)
    end
    return S.seq
  end
  jsonWriteFile(string.format('e2r_world/request_%d.json', S.seq), tbl, false)
  return S.seq
end

local function readStatus()
  if S.now - S.statusReadAt < 0.25 then return end
  S.statusReadAt = S.now
  if NATIVE then
    S.status = native.status()
    S.coverage = S.status.coverage
  else
    if not FS:fileExists('/e2r_world/status.json') then return end
    local ok, st = pcall(jsonReadFile, '/e2r_world/status.json')
    if ok and type(st) == 'table' then S.status = st end
  end
  -- the map opens over the package's own land (the default centre is Kyiv)
  local box = S.status and S.status.packageBox
  if box and not S.centredOnPackage and NATIVE then
    -- every installed pack in view; the picker fits the box once it knows its map size
    S.centredOnPackage, S.fitAll = true, true
  elseif box and not S.centredOnPackage then
    S.centredOnPackage = true
    if not presetInPackage({'', S.center.lat, S.center.lon}) then
      S.center, S.viewDirty = {lat = (box[2] + box[4]) / 2, lon = (box[1] + box[3]) / 2}, true
      for _, p in ipairs(PRESETS) do
        if presetInPackage(p) then S.center = {lat = p[2], lon = p[3]}; break end
      end
    end
  end
end

local function serverUp()
  if NATIVE then return true end
  return S.status and S.status.heartbeat and (os.time() - S.status.heartbeat) < 6
end

local function setMarker(lat, lon)
  S.marker = {lat = lat, lon = lon}
  S.viewDirty = true
end

local function goTo(lat, lon, zoom)
  S.center = {lat = lat, lon = lon}
  S.zoom = zoom or S.zoom
  setMarker(lat, lon)
end

-- The landing's phases for the report (result.loadReal): real seconds since the request (S.now
-- stands still in a long frame), frames, and the Lua the generator, the spawn queue and the window
-- took by then; the generator's own account of its layers.
-- An early arrival (beginArrival with native job.early) once the job is ready: the chosen spawn
-- replaces the provisional one; a failed job goes back to the landing window with its error.
function M.landFinal()
  local job = S.status and S.status.job
  if not job or job.seq ~= S.landSeq then return end
  if job.state == 'ready' then
    local manifest = type(job.manifest) == 'table' and job.manifest or jsonReadFile(job.manifest)
    if not manifest then return end
    loadNewMaterials(manifest.materials, manifest.stockMaterials)
    S.landing, S.landEarly, result.timings = manifest, nil, job.timings
    M.loadMark('final')
  elseif job.state == 'error' then
    S.landEarly, S.state = nil, 'generating'
  end
end

function M.loadMark(name)
  local P, st = S.prof or {sum = {}}, S.status and S.status.stream
  result.loadReal = result.loadReal or {}
  result.loadReal[name] = {s = S.landTimer and S.landTimer:stop() / 1000, frames = P.frames,
    nativeMs = P.sum.native, queueMs = P.sum.queue, windowMs = P.sum.window, tilesMs = P.sum.tiles,
    navMs = P.sum.nav, forestMs = P.sum.forest, testMs = P.sum.test,
    collisionMs = P.sum.collision, built = st and st.built,
    spent = st and st.spentMs and deepcopy(st.spentMs), heapKb = collectgarbage('count')}
end

-- Automation: the engine's own split of each frame of the landing (Lua, LuaGC, Render, Ticking,
-- physics...), summed per phase into result.loadEngine. The Lua parts above see half the frame.
function M.loadEngine(state)
  S.engineM = S.engineM or {}
  -- test.gcCycle = {10, 1, 400, -10, 100}: the collector's step changes every 2 s of the landing,
  -- and the frames are summed per step ('generating@10'): what the step is worth there
  if test and test.gcCycle and state == 'generating' then
    state = state .. '@' .. tostring(M.gc.try or '-')
    M.gc.try = test.gcCycle[math.floor(S.now / 2) % #test.gcCycle + 1]
  else
    M.gc.try = nil
  end
  if not pcall(Engine.Debug.getLastPerformanceMetrics, S.engineM) then return end
  result.loadEngine = result.loadEngine or {}
  local sum = result.loadEngine[state] or {frames = 0}
  result.loadEngine[state] = sum
  sum.frames = sum.frames + 1
  sum.stepmulSeen = (sum.stepmulSeen or 0) + (M.gc.seen or 0)
  sum.nativeMs = (sum.nativeMs or 0) + (S.nativeMs or 0)
  sum.heapMaxMB = math.max(sum.heapMaxMB or 0, collectgarbage('count') / 1024)
  for k, v in pairs(S.engineM) do
    if type(v) == 'number' then sum[k] = (sum[k] or 0) + v end
  end
end

local function land()
  if not S.marker then return end
  if NATIVE and not native.at(S.marker.lat, S.marker.lon) then return end
  if M.navigator then M.navigator.clear() end   -- the old route is in the old region's frame
  if M.signals then M.signals.clear() end
  S.location = nil
  S.landSeq = request({type = 'land', lat = S.marker.lat, lon = S.marker.lon})
  S.landAt = S.now
  S.landTimer = hptimer()
  result.loadReal = nil
  M.loadMark('request')
  S.pickerOpen = false
  S.state = 'generating'
  result.landRequestedAt = S.now
  saveResult()
end

-- --- pieces (as measured in EarthNG earthng/e2rstream.lua, S2) ---------------------------------
-- Pieces: u32 subCount; per submesh u32 nameLen (padded to 4), name, u32 verts, u32 indices,
-- f32 pos[3v], f32 normal[3v], f32 uv[2v], u32 index[i]. ffi.cast is a no-op in game Lua, so the
-- bytes are copied into a uint32 and a float buffer and indexed by 4-byte word.
local function binMeshes(path, pause)
  local t = hptimer()
  local f = io.open(path, 'rb')
  if not f then return nil end
  local data = f:read('*all')
  f:close()
  local ms = t:stop()
  if ms > (result.readMs or 0) then result.readMs, result.readItem = ms, path end
  local words = #data / 4
  local u = ffi.new('uint32_t[?]', words)
  ffi.copy(u, data, #data)
  local fl = ffi.new('float[?]', words)
  ffi.copy(fl, data, #data)
  pause()
  local meshes, w = {}, 1
  for s = 1, u[0] do
    local len = u[w]
    local mat = data:sub(4 * w + 5, 4 * w + 4 + len):gsub('%z+$', '')
    w = w + 1 + len / 4
    local nv, ni = u[w], u[w + 1]
    w = w + 2
    local pw, nw, tw, iw = w, w + 3 * nv, w + 6 * nv, w + 8 * nv
    local verts, normals, uvs, faces = {}, {}, {}, {}
    for k = 0, nv - 1 do
      verts[k + 1] = {x = fl[pw + 3 * k], y = fl[pw + 3 * k + 1], z = fl[pw + 3 * k + 2]}
      normals[k + 1] = {x = fl[nw + 3 * k], y = fl[nw + 3 * k + 1], z = fl[nw + 3 * k + 2]}
      uvs[k + 1] = {u = fl[tw + 2 * k], v = fl[tw + 2 * k + 1]}
      if k % 256 == 255 then pause() end
    end
    for k = 0, ni - 1 do
      local v = u[iw + k]
      faces[k + 1] = {v = v, n = v, u = v}
      if k % 768 == 767 then pause() end
    end
    w = iw + ni
    meshes[s] = {verts = verts, normals = normals, uvs = uvs, faces = faces, material = mat}
  end
  return meshes
end

-- One Forest for the whole level. BeamNG gives every Forest global bounds, so a
-- Forest per tile is never culled: each one runs its own cell walk and render
-- submission on the main thread every frame, and the GPU waits. That is a full
-- frame at ~20 FPS with the CPU near one core and the GPU near a third busy.
-- Collidable stays off: deleting a Forest whose items sit in static collision
-- hangs the game, and a colliding population makes every later add cost the
-- engine tick. The object is never deleted; the level unload drops it.
local plantData, plantShape, sharedForestId = {}, {}, nil
-- Plants of a scene go through the queue in batches; each one only joins the Forest commit.
-- createNewItem and removeItem show and hide a crown on their own in 0.39. The
-- editor's rebuildForestManagerInstanceData walked every crown of the level:
-- 47-60 ms at 40-50k crowns, up to 2.5 times a second while tiles streamed in.
-- Frames before and after it were pixel-identical (night-probe-01), so the
-- mod no longer calls it.

local function shapeKey(shape)
  local h = 17
  for i = 1, #shape do h = (h * 131 + shape:byte(i)) % 2147483647 end
  return h
end

-- Trees and bushes only. Grass and rocks stay TSStatic without collision (~12 us each,
-- night-probe-12): a Forest item with an alpha tuft is not drawn, and every Forest kind
-- adds ~3 ms to each Forest commit (forestCommit), which five rock kinds would pay.
local function vegetationShape(shape)
  return type(shape) == 'string' and not shape:find('3d_grass', 1, true) and not shape:find('/rocks/', 1, true)
    and (shape:find('/trees/', 1, true) or shape:find('trees_library', 1, true) or shape:find('scots_pine', 1, true))
end

-- BeamNG 0.39 registers the datablock as ForestItemData. TSForestItemData does
-- not exist: createObject logged "unknown class" once per tree and every crown
-- fell back to a TSStatic, which is why the canopy popped while the camera sat still.
local function newForestItemData()
  if worldEditorCppApi and worldEditorCppApi.createObject then
    local ok, created = pcall(worldEditorCppApi.createObject, 'ForestItemData')
    if ok and created then return created end
  end
  local ok, created = pcall(createObject, 'ForestItemData')
  if ok and created then return created end
end

local function setPlantField(obj, field, value)
  if pcall(function() obj:setField(field, '', value) end) then return end
  obj:setField(field, 0, value)
end

-- shape .. '#solid': a street prop, the same shape as a collidable kind (a rebuild takes 6000 of
-- them for ~1 ms, out/overnight/props)
local function plantDataFor(shape)
  if S.forestOff then return nil end
  local known = plantData[shape]
  if known ~= nil then return known or nil end
  local name = 'e2rPlant_' .. tostring(shapeKey(shape))
  local d = scenetree.findObject(name)
  if not d then
    local created = newForestItemData()
    if not created then
      if not S.forestOff then log('W', logTag, 'ForestItemData unavailable, vegetation stays TSStatic') end
      S.forestOff = true
      result.forest = 'static'
      return nil
    end
    local file = shape:match('^(.-)#solid$')
    -- shape .. '#knock': a prop knock.lua can knock down; no static collision, since an item that
    -- leaves the Forest keeps its collision until the next reloadCollision (p24_knock_forest)
    local knockFile = shape:match('^(.-)#knock$')
    setPlantField(created, 'shapeFile', file or knockFile or shape)
    setPlantField(created, 'collidable', file and '1' or '0')
    -- props do not sway
    file = file or knockFile
    setPlantField(created, 'windScale', file and '0' or '0.35')
    setPlantField(created, 'branchAmp', file and '0' or '0.08')
    setPlantField(created, 'detailAmp', file and '0' or '0.15')
    local registered = pcall(function() created:registerObject('') end)
      or pcall(function() created:registerObject(name) end)
    if not registered then
      plantData[shape] = false
      return nil
    end
    pcall(function() created:setName(name) end)
    pcall(function() created:setInternalName(name) end)
    pcall(function()
      local group = scenetree.findObject('dataBlockGroup')
      if group then group:addObject(created) end
    end)
    pcall(function()
      if Sim and Sim.getDataBlockSet then Sim.getDataBlockSet():addObject(created) end
    end)
    d = created
  end
  plantData[shape] = d
  plantShape[d:getName()] = shape
  return d
end

local function forestFor(tile)
  if S.forestOff then return nil end
  local f = sharedForestId and scenetree.findObjectById(sharedForestId)
  if not f then
    sharedForestId = nil
    f = scenetree.findObject('e2rForest')
    if f then sharedForestId = f:getID() end
  end
  if not f then
    local ok, created = pcall(createObject, 'Forest')
    if not ok or not created then
      if not S.forestOff then log('W', logTag, 'Forest unavailable, vegetation stays TSStatic') end
      S.forestOff = true
      result.forest = 'off'
      return nil
    end
    created.canSave = false
    -- Reflections redraw the forest. A high scalar drops that pass to billboards.
    pcall(function() created.lodReflectScalar = 8 end)
    if not pcall(function() created:registerObject('e2rForest') end) then
      S.forestOff = true
      result.forest = 'off'
      return nil
    end
    if scenetree.MissionGroup then scenetree.MissionGroup:addObject(created) end
    f = created
    sharedForestId = f:getID()
  end
  if tile then tile.forestId = sharedForestId end
  -- 'on' means a crown was accepted. The container alone used to report 'on'
  -- while every item fell back to a TSStatic.
  if result.forest ~= 'on' and result.forest ~= 'static' then result.forest = 'object' end
  return f
end

local function yawOf(rot)
  return 2 * math.atan2(rot and rot[3] or 0, rot and rot[4] or 1)
end

-- Each change to the Forest costs the engine work a few frames later (its Ticking):
-- ~3 ms for every crown kind (ForestItemData) the change touched, whatever the number
-- of crowns or Forests (night-probe-06, -08). Crowns used to go in as tiles streamed and
-- out as they unloaded, so the Forest changed in nearly every frame and Ticking sat at
-- 20-25 ms; one commit a second of all 18 kinds was a 55 ms frame. Now adds and removals
-- wait in a queue per kind, and a commit takes one kind: at most one every
-- LIMIT.forestStep s, each kind at most once per LIMIT.forestKind s.

local function forestQueue(name)
  S.forestQ = S.forestQ or {}
  local q = S.forestQ[name]
  if not q then q = {adds = M.fifo.new(), removes = M.fifo.new(), removing = {}, since = nil, at = -10}; S.forestQ[name] = q end
  if not q.since then q.since = S.now or 0 end
  return q
end

-- The engine's deferred work for a Forest change (its Ticking, a few frames later) grows with
-- every crown of each kind the change touched, ~0.5 us a crown (switzerlandNG measured it,
-- BeamNG.Earth splits populations by path): a commit to a birch kind holding 20k crowns of the
-- whole loaded area costs ~10 ms. A tree goes in a kind of its cell instead, cells of forestCell
-- m in forestVariants^2 residues, each spelt with as many './' before the file name, so the
-- tiles streaming in at the edge touch a few small kinds. The same file loads once a spelling.
function M.variantShape(shape, x, y)
  local cell, k = LIMIT.forestCell, LIMIT.forestVariants
  if not cell or cell <= 0 or not k or k <= 1 then return shape end
  local v = math.floor(x / cell) % k + k * (math.floor(y / cell) % k)
  if v == 0 then return shape end
  local dir, file = shape:match('^(.*/)([^/]+)$')
  if not dir then return shape end
  return dir .. string.rep('./', v) .. file
end

local function spawnForestItem(it, tile)
  if S.forestOff or not tile or not MatrixF then return false end
  -- a knockable prop (knock.lua's table) has no static collision while knocking is on
  local key = it.prop and it.shape .. ((not S.knockOff and M.knock.kindOf(it.shape)) and '#knock' or '#solid')
    or M.variantShape(it.shape, it.pos[1], it.pos[2])
  if it.prop then result.propsQueued = (result.propsQueued or 0) + 1 end
  local kind = forestFor(tile) and plantDataFor(key)
  if not kind then return false end
  local adds = forestQueue(key).adds
  M.fifo.push(adds, {it, tile, tile.forestGen or 0})
  return true
end

-- A tile does not keep its crowns: OASIS held ~160k ForestItem userdata in Lua for the
-- game's collector to walk, and a full collection took 294 ms (night-route-oasis). The
-- crowns a tile planted are found again in the Forest by its rectangle when it goes; a
-- crown of this tile still waiting for a commit is skipped there instead (forestGen).
-- Near and far crowns of one key never stand at once, so the rectangle is the tile's.
local function retireForest(tile)
  if detailStream and tile then detailStream:remove(tile) end
  if not tile then return end
  tile.forestGen = (tile.forestGen or 0) + 1
  -- its knockable props leave knock.lua's hash, its debris the scene (they stand again when it is rebuilt)
  if S.knock then M.knock.unregisterTile(S.knock.K, tile, S.knock.api) end
  if not tile.forestId or not tile.i then tile.forestId = nil; return end
  tile.forestId = nil
  local f = forestFor()
  local data = f and f:getData()
  if not data or not Box3F then return end
  local timer = hptimer()
  local t = S.stream and S.stream.tile or 500
  local box = Box3F()
  -- getItemsBox tests model bounds, not anchors: a neighbouring bench/tree can
  -- overlap this box. Query the full tile, then use the generator's half-open
  -- anchor ownership so unloading one tile cannot erase its neighbour's props.
  box.minExtents = vec3(tile.i * t, tile.j * t, -1e5)
  box.maxExtents = vec3((tile.i + 1) * t, (tile.j + 1) * t, 1e5)
  local ok, items = pcall(data.getItemsBox, data, box)
  if not ok or type(items) ~= 'table' then return end
  for _, item in ipairs(items) do
    local okData, itemData = pcall(item.getData, item)
    local shape = okData and itemData and plantShape[itemData:getName()]
    local okPos, pos = pcall(item.getPosition, item)
    if shape and okPos and pos and math.floor(pos.x / t) == tile.i and math.floor(pos.y / t) == tile.j then
      local q, key = forestQueue(shape), item:getKey()
      -- Near/far retirement can query the same tile before a batch drains.
      -- Passing an already-removed ForestItem back to C++ is unsafe.
      if not q.removing[key] then
        q.removing[key] = true
        M.fifo.push(q.removes, item)
        if (shape == LAMP_SHAPE .. '#solid' or shape == LAMP_SHAPE .. '#knock') and S.lamps then
          S.lamps[string.format('%d_%d', math.floor(pos.x), math.floor(pos.y))] = nil
        end
      end
    end
  end
  result.forestRetireMaxMs = math.max(result.forestRetireMaxMs or 0, timer:stop())
  result.forestRetireMaxScanned = math.max(result.forestRetireMaxScanned or 0, #items)
end

-- One kind's queue into the Forest: removals first, then adds, `limit` engine calls in all
-- (a field: world.lua's chunk is at Lua's 200 locals)
function M.commitKind(name, q, data, limit)
  local removed, added = 0, 0
  local knockKind = name:find('#knock', 1, true) ~= nil
  local retireCount = math.min(M.fifo.size(q.removes), limit)
  for _ = 1, retireCount do
    local item = M.fifo.pop(q.removes)
    q.removing[item:getKey()] = nil
    if data and pcall(data.removeItem, data, item) then removed = removed + 1 end
  end
  local adds = q.adds
  local count = math.min(M.fifo.size(adds), limit - retireCount)
  local kind = data and plantDataFor(name)
  -- createNewItem copies the transform, so one matrix and two vectors serve every crown
  local m, euler, at = MatrixF(true), vec3(0, 0, 0), vec3(0, 0, 0)
  for _ = 1, count do
    local entry = M.fifo.pop(adds)
    local it, tile = entry[1], entry[2]
    if kind and not tile.dropped and not tile.vegetationDropped and (tile.forestGen or 0) == entry[3] then
      euler.z = yawOf(it.rot)
      m:setFromEuler(euler)
      at.x, at.y, at.z = it.pos[1], it.pos[2], it.pos[3]
      m:setPosition(at)
      local ok, item = pcall(data.createNewItem, data, kind, m, it.scale or 1)
      if ok and item then
        tile.forestId = sharedForestId
        added = added + 1
        -- knock.lua finds it again by its tile, place and kind (no ForestItem kept in Lua)
        if knockKind then M.knockRegister(tile, it.shape, at, m, it.scale) end
        if it.shape == LAMP_SHAPE then
          S.lamps = S.lamps or {}
          S.lamps[string.format('%d_%d', math.floor(at.x), math.floor(at.y))] = {at.x, at.y, at.z}
        end
      else
        S.forestFails = (S.forestFails or 0) + 1
        if S.forestFails >= 3 and not S.forestOff then
          S.forestOff = true
          result.forest = 'off'
          log('W', logTag, 'Forest item create failed, vegetation stays TSStatic')
        end
      end
    end
  end
  q.live = math.max(0, (q.live or 0) + added - removed)
  q.since = (M.fifo.size(adds) > 0 or M.fifo.size(q.removes) > 0) and S.now or nil
  return added, removed, retireCount + count
end

local function forestCommit()
  local queues = S.forestQ
  if not queues or (S.now or 0) - (S.forestCommitAt or -10) < LIMIT.forestStep then return end
  -- the kinds that waited, longest first, if their last commit was long enough ago
  local ready = {}
  for shape, candidate in pairs(queues) do
    if candidate.since and (S.now or 0) - candidate.at >= LIMIT.forestKind then
      ready[#ready + 1] = shape
    end
  end
  if #ready == 0 then return end
  table.sort(ready, function(a, b)
    local qa, qb = queues[a], queues[b]
    if qa.since ~= qb.since then return qa.since < qb.since end
    return a < b
  end)
  S.forestCommitAt = S.now
  local timer = hptimer()
  local f = forestFor()
  local data = f and f:getData()
  -- The oldest kind always goes. More kinds join while the crowns standing in all of them stay
  -- under LIMIT.forestLive (the engine's cost) and the calls under the first kind's limit:
  -- 2500 solid props of one kind made a 19 ms commit (out/overnight/drive-p6). Retiring
  -- several dense tiles obeys the same budget as planting them.
  local first = ready[1]
  local limit = (first:find('#knock', 1, true) or first:find('#solid', 1, true)) and LIMIT.propMax or LIMIT.forestMax
  local live, calls, kinds = 0, 0, 0
  local added, removed = 0, 0
  for index, name in ipairs(ready) do
    local q = queues[name]
    local standing = (q.live or 0) + M.fifo.size(q.adds)
    if index > 1 and (live + standing > LIMIT.forestLive or kinds > LIMIT.forestJoinKinds
        or calls >= LIMIT.forestJoinCalls or timer:stop() > LIMIT.forestJoinMs
        or (name:find('#', 1, true) ~= nil) ~= (first:find('#', 1, true) ~= nil)) then
      break
    end
    q.at = S.now
    local a, r, c = M.commitKind(name, q, data, index > 1 and math.min(limit, LIMIT.forestJoinCalls) - calls or limit)
    added, removed, calls, kinds = added + a, removed + r, calls + c, kinds + 1
    live = live + (q.live or 0)
    if index == 1 then result.forestCommitKind = name end
  end
  result.forestPendingAdds, result.forestPendingRemoves = 0, 0
  for _, pending in pairs(queues) do
    result.forestPendingAdds = result.forestPendingAdds + M.fifo.size(pending.adds)
    result.forestPendingRemoves = result.forestPendingRemoves + M.fifo.size(pending.removes)
  end
  if added > 0 then result.forest = 'on' end
  result.forestItems = math.max(0, (result.forestItems or 0) + added - removed)
  if first:find('#solid', 1, true) then
    result.forestProps = math.max(0, (result.forestProps or 0) + added - removed)
  end
  result.forestCommits = (result.forestCommits or 0) + 1
  result.forestCommitKinds = math.max(result.forestCommitKinds or 0, kinds)
  result.forestCommitLive = math.max(result.forestCommitLive or 0, live)
  local ms = timer:stop()
  result.forestCommitMs = ms
  if ms > (result.forestCommitMaxMs or 0) then
    result.forestCommitMaxMs, result.forestCommitMaxKind = ms, first
    result.forestCommitMaxAdded, result.forestCommitMaxRemoved = added, removed
  end
end

local function resetForests()
  detailStream = nil
  sharedForestId, plantData, plantShape = nil, {}, {}
  S.forestQ, S.forestOff, S.forestFails, S.forestCommitAt = nil, nil, nil, nil
end

-- The engine pays ~2.3 ms the first frame it draws each new (object, material) pair
-- (night-probe-10). The queue used to create every small piece that fit its Lua budget,
-- and the next frame drew ten new pairs at once (RenderShadows 40-118 ms in Kyiv).
-- The queue and the grass cells have separate allowances, so streaming meshes cannot
-- starve the grass round the car.
local function pairsLeft()
  return (S.state == 'driving' and LIMIT.pairsDriving or LIMIT.pairsLanding) - (S.pairsFrame or 0)
end

-- layer: 'road' or 'scene' for a near tile's job (collision.quiet), nil otherwise
local function spawnItem(it, group, pause, tile, layer)
  if it.kind == 'plants' then
    if tile.vegetationDropped then return end
    for _, plant in ipairs(it.items) do
      spawnItem(plant, group, pause, tile, layer)
      pause()
    end
  elseif it.kind == 'ocean' then
    -- One WaterPlane for the open sea (infinite, no tile seams). Kept on S, outside tile groups,
    -- so unloading a coastal tile does not delete the ocean under the next one.
    if S.ocean then
      S.ocean:setPosition(vec3(0, 0, it.pos[3]))
      result.waterSpawned = (result.waterSpawned or 0) + 1
      return
    end
    local obj = createObject('WaterPlane')
    if not obj then return end
    obj.canSave = false
    obj:setField('fullReflect', 0, 'false')
    obj:setField('baseColor', 0, '26 44 50 255')
    obj:setField('rippleTex', 0, '/core/art/water/ripple.dds')
    obj:setField('foamTex', 0, '/core/art/water/foam.dds')
    obj:setField('depthGradientTex', 0, '/core/art/water/depthcolor_ramp_b.png')
    obj:setField('cubemap', 0, 'DefaultSkyCubemap')
    obj:setField('fresnelBias', 0, '0.1')
    obj:setField('fresnelPower', 0, '15')
    obj:setField('specularPower', 0, '200')
    obj:setField('overallRippleMagnitude', 0, '0.28')
    obj:setField('overallWaveMagnitude', 0, '0.05')
    obj:setField('overallFoamOpacity', 0, '0.55')
    obj:setField('foamMaxDepth', 0, '0.35')
    obj:setField('reflectivity', 0, '0.65')
    obj:setField('viscosity', 0, '0.001')
    obj:setField('waterFogDensity', 0, '0.5')
    obj:setField('depthGradientMax', 0, '80')
    obj:setField('gridSize', 0, '120')
    obj:setField('gridElementSize', 0, '1.5')
    obj:setField('rippleDir', 0, '0 1'); obj:setField('rippleDir', 1, '0.707 0.707'); obj:setField('rippleDir', 2, '0.5 0.86')
    obj:setField('rippleSpeed', 0, '-0.01'); obj:setField('rippleSpeed', 1, '0.02'); obj:setField('rippleSpeed', 2, '0.012')
    obj:setField('rippleTexScale', 0, '120 120'); obj:setField('rippleTexScale', 1, '20 28'); obj:setField('rippleTexScale', 2, '60 60')
    obj:setField('waveDir', 0, '0 1'); obj:setField('waveDir', 1, '0.707 0.707'); obj:setField('waveDir', 2, '0.5 0.86')
    obj:setField('waveMagnitude', 0, '0.25'); obj:setField('waveMagnitude', 1, '0.2'); obj:setField('waveMagnitude', 2, '0.15')
    obj:setField('waveSpeed', 0, '1.2'); obj:setField('waveSpeed', 1, '1'); obj:setField('waveSpeed', 2, '0.8')
    if obj.reloadTextures then obj:reloadTextures() end
    obj:setPosition(vec3(0, 0, it.pos[3]))
    obj:registerObject('e2r_ocean')
    S.ocean = obj
    result.waterSpawned = (result.waterSpawned or 0) + 1
  elseif it.kind == 'water' or it.kind == 'river' then
    -- Real engine water: WaterBlock (lake) or River (channel). Look fields inline —
    -- this file is at LuaJIT's 200-local limit.
    local river = it.kind == 'river'
    local obj = createObject(river and 'River' or 'WaterBlock')
    if not obj then return end
    obj.canSave = false
    obj:setField('fullReflect', 0, 'false')
    obj:setField('baseColor', 0, river and '34 55 70 255' or '0 67 115 255')
    obj:setField('rippleTex', 0, '/core/art/water/ripple.dds')
    obj:setField('foamTex', 0, '/core/art/water/foam.dds')
    obj:setField('depthGradientTex', 0, '/core/art/water/depthcolor_ramp_b.png')
    obj:setField('cubemap', 0, 'DefaultSkyCubemap')
    obj:setField('fresnelBias', 0, '0.1')
    obj:setField('fresnelPower', 0, '10')
    obj:setField('specularPower', 0, '200')
    obj:setField('overallRippleMagnitude', 0, river and '0.35' or '0.28')
    obj:setField('overallWaveMagnitude', 0, river and '0.02' or '0.04')
    obj:setField('overallFoamOpacity', 0, river and '0.85' or '0.6')
    obj:setField('foamMaxDepth', 0, '0.55')
    obj:setField('reflectivity', 0, '0.4')
    obj:setField('viscosity', 0, '0.001')
    obj:setField('waterFogDensity', 0, river and '1.2' or '0.9')
    obj:setField('depthGradientMax', 0, river and '6' or '12')
    obj:setField('rippleDir', 0, '0 1'); obj:setField('rippleDir', 1, '0.707 0.707'); obj:setField('rippleDir', 2, '0.5 0.86')
    obj:setField('rippleSpeed', 0, river and '0.05' or '-0.015')
    obj:setField('rippleSpeed', 1, '0.015'); obj:setField('rippleSpeed', 2, '0.01')
    obj:setField('rippleTexScale', 0, river and '4 12' or '10 10')
    obj:setField('rippleTexScale', 1, '12 16'); obj:setField('rippleTexScale', 2, '50 50')
    obj:setField('waveDir', 0, '0 1'); obj:setField('waveDir', 1, '0.707 0.707'); obj:setField('waveDir', 2, '0.5 0.86')
    obj:setField('waveMagnitude', 0, '0.2'); obj:setField('waveMagnitude', 1, '0.2'); obj:setField('waveMagnitude', 2, '0.2')
    obj:setField('waveSpeed', 0, '1'); obj:setField('waveSpeed', 1, '1'); obj:setField('waveSpeed', 2, '1')
    if river then
      obj:setField('FlowMagnitudePhysics', 0, '2')
      obj:setField('SegmentLength', 0, '12')
      obj:setField('SubdivideLength', 0, '3')
      obj:setField('LowLODDistance', 0, '80')
    end
    if obj.reloadTextures then obj:reloadTextures() end
    obj:registerObject(it.name or '')
    if group then group:addObject(obj) end
    if river then
      local up = vec3(0, 0, 1)
      for i = 1, #(it.nodes or {}) do
        local node = it.nodes[i]
        obj:insertNodeNoRegen(vec3(node[1], node[2], node[3]), node[4], node[5], up, i - 1)
      end
      if obj.regenerate then obj:regenerate() end
    else
      local scale = it.scale or {10, 10, 8}
      local grid = it.grid or math.max(2, math.min(16, math.min(scale[1], scale[2]) * .06))
      obj:setField('gridElementSize', 0, tostring(grid))
      obj:setPosition(vec3(it.pos[1], it.pos[2], it.pos[3]))
      obj:setScale(vec3(scale[1], scale[2], scale[3]))
    end
    result.waterSpawned = (result.waterSpawned or 0) + 1
  elseif it.kind == 'proc' then
    local meshes = it.meshes or binMeshes(it.shape, pause)
    S.pairsFrame = (S.pairsFrame or 0) + #(meshes or {})
    if not meshes then error('missing mesh: ' .. tostring(it.shape)) end
    pause()
    -- the one call that cannot yield: its worst case is the floor of a frame's streaming cost
    local t = hptimer()
    local obj = createObject('ProceduralMesh')
    obj:registerObject(it.name)
    obj.canSave = false
    group:addObject(obj.obj)
    obj:createMesh({meshes})
    obj:setPosition(vec3(it.pos[1], it.pos[2], it.pos[3]))
    -- a collision proxy is invisible until a rebuild unhides the cells round the car
    if it.proxy then obj:setHidden(true) end
    if NATIVE and tile then
      S.coll = S.coll or collision.new()
      S.coll:track(tile, obj:getID(),
        not (tile.far or tile.horizon) and not it.proxy and collision.quiet(meshes, layer),
        it.triangles, layer, it.proxy and it.cell)
    end
    if it.lens and M.signals then M.signals.addMesh(obj:getID(), it.lens, it.colour) end
    local ms = t:stop()
    if ms > (result.createMeshMs or 0) then result.createMeshMs, result.createMeshItem = ms, it.name end
  else
    if it.editorObject then
      -- Built before a save that moved or removed it: the record has a newer version.
      if native and native.editorObjectCurrent and it.editorId
        and not native.editorObjectCurrent(it.editorId, it.editorRev) then return end
      -- One object, one name: the World Editor's own copy (E2R_editor) or another tile's
      -- copy is already standing. A buried tile's copy is leaving: take its name over.
      local existing = scenetree and scenetree.findObject and scenetree.findObject(it.name)
      if existing then
        local g = existing.getGroup and existing:getGroup()
        local gname = g and g:getName()
        if g and (gname == nil or gname == '') then existing:setName('') else return end
      end
    end
    -- An editor object has an exact user-authored quaternion and possibly non-uniform
    -- scale. Forest instances only carry yaw and uniform scale; keep these TSStatic.
    if tile and not it.editorObject and (it.prop or vegetationShape(it.shape)) and spawnForestItem(it, tile) then return end
    -- Forest lamps register on successful commit; fallback statics register here.
    if it.shape == LAMP_SHAPE then
      S.lamps = S.lamps or {}
      S.lamps[string.format('%d_%d', math.floor(it.pos[1]), math.floor(it.pos[2]))] = {it.pos[1], it.pos[2], it.pos[3]}
    end
    local obj = createObject('TSStatic')
    local itemName = it.name or ''
    if vegetationShape(it.shape) then result.staticTrees = (result.staticTrees or 0) + 1
    elseif itemName:find('grass', 1, true) then result.grassSpawned = (result.grassSpawned or 0) + 1
    elseif itemName:find('rock', 1, true) then result.rockSpawned = (result.rockSpawned or 0) + 1 end
    obj:setField('shapeName', 0, it.shape)
    obj:setField('collisionType', 0, it.collision or 'Collision Mesh')
    obj:setField('decalType', 0, it.decal or 'None')
    obj.useInstanceRenderData = true
    obj:setPosRot(it.pos[1], it.pos[2], it.pos[3], it.rot[1], it.rot[2], it.rot[3], it.rot[4])
    if type(it.scale) == 'table' then
      obj:setScale(vec3(it.scale[1], it.scale[2], it.scale[3]))
    elseif it.scale then
      obj:setScale(vec3(it.scale, it.scale, it.scale))
    end
    obj:registerObject(it.name)
    group:addObject(obj)
    return obj:getID()
  end
end

-- A streamed cell of tufts or rocks as TSStatic without collision (~12 us each once the shape
-- is loaded, night-probe-12). Merged ProceduralMesh cells were tried and dropped: every
-- ProceduralMesh triangle is static collision, so the blades became bumps under the wheels.
local function grassCell(parts, pause)
  local handle = {}
  for _, source in ipairs(parts) do
    local part = detail.expand(source, pause)
    local group = part.tile.far and part.tile.group or part.tile.decor
    for k = 1, part.n do
      local half = part.yaw[k] / 2
      local obj = createObject('TSStatic')
      obj:setField('shapeName', 0, part.shape[k])
      obj:setField('collisionType', 0, 'None')
      obj:setField('decalType', 0, 'None')
      obj.useInstanceRenderData = true
      obj:setPosRot(part.x[k], part.y[k], part.z[k], 0, 0, math.sin(half), math.cos(half))
      -- a far ring's tuft is broader than tall (detail.lua TUFT)
      local scale, wide = part.scale[k], part.wide and part.wide[k] or part.scale[k]
      if scale ~= 1 or wide ~= 1 then obj:setScale(vec3(wide, wide, scale)) end
      obj:registerObject('')
      if group then group:addObject(obj) end
      handle[#handle + 1] = obj:getID()
      if k % 32 == 0 then pause() end
    end
  end
  result.grassSpawned = (result.grassSpawned or 0) + #handle
  return handle
end

local function getDetailStream()
  if not detailStream then
    detailStream = detail.new(grassCell, function(handle)
      for _, id in ipairs(handle or {}) do
        local obj = scenetree.findObjectById(id)
        if obj then obj:delete() end
      end
    end)
  end
  return detailStream
end

-- Batches avoid sorting/shifting tens of thousands of individual queue entries.
-- Grass/rocks are indexed once and do not block delivery of a scene's meshes.
local function queueItems(items, tile, key, layer)
  local count, batch = 0, nil
  for _, it in ipairs(items) do
    if it.editorObject or not getDetailStream():add(tile, it) then
      if not it.editorObject and it.kind ~= 'proc' and (it.prop or vegetationShape(it.shape)) then
        if not batch or #batch.items >= LIMIT.plantBatch then
          batch = {kind='plants', name='plants_' .. key, decor=true, items={}}
          S.queue[#S.queue+1] = {tile=tile, key=key, item=batch, scene=layer=='scene', far=layer=='far', grass=layer=='grass'}
          count = count + 1
        end
        batch.items[#batch.items+1] = it
      else
        S.queue[#S.queue+1] = {tile=tile, key=key, item=it, scene=layer=='scene', far=layer=='far', grass=layer=='grass'}
        count = count + 1
      end
    end
  end
  return count
end

local function tileGroup(name, outside)
  local g = scenetree.findObject(name)
  if g then
    g:deleteAllObjects()
    return g
  end
  g = createObject('SimGroup')
  g:registerObject(name)
  -- outside: decoration kept out of the MissionGroup (and so out of the static collision)
  if not outside then scenetree.MissionGroup:addObject(g) end
  return g
end

local function dropGroup(name)
  local g = scenetree.findObject(name)
  if g then
    g:deleteAllObjects()
    g:delete()
  end
end

-- A decoration group (trees, lamps, lines, the far city) goes a few dozen objects a frame: a
-- scene tile holds up to ~900 trees, and deleting them in one frame stalled it. At speed many
-- tiles leave at once; digGraves takes a higher budget so the backlog does not keep drawing.
-- Budget numbers stay literals: this file is at LuaJIT's 200 chunk-local limit.
local function buryGroup(name)
  local g = scenetree.findObject(name)
  if not g then return end
  -- out of the way at once (a renamed group cannot be found again by a new tile of that key)
  g:setName('')
  S.graves = S.graves or {}
  table.insert(S.graves, g)
end

local function digGraves(budget)
  local graves = S.graves
  if not graves or #graves == 0 then return end
  local left = budget or 60
  while left > 0 and #graves > 0 do
    local g = graves[1]
    local n = g:getCount()
    if n == 0 then
      g:delete()
      table.remove(graves, 1)
    else
      for _ = 1, math.min(left, n) do
        local o = g:getObject(g:getCount() - 1)
        if o then o:delete() end
        left = left - 1
      end
    end
  end
end

local function frameStats(list)
  local worst, total = 0, 0
  for _, dt in ipairs(list) do worst, total = math.max(worst, dt), total + dt end
  local sorted = {}
  for k, dt in ipairs(list) do sorted[k] = dt end
  table.sort(sorted)
  return {frames = #list, worstFrameMs = worst, meanFrameMs = #list > 0 and total / #list or 0,
          p99FrameMs = sorted[math.max(1, math.ceil(#sorted * 0.99))] or 0}
end

-- The whole driving phase, however long: 0.5 ms bins up to 1 s (p99 without keeping every frame),
-- and the first 20000 frames in order (slow pairs, accStats).
local function newAcc() return {n = 0, total = 0, worst = 0, over33 = 0, over100 = 0, bins = {}, worstAt = 0, ms = {}} end

local function accFrame(acc, ms, now)
  -- the frames that carried a one-time wait (the flow's pool spawn) are left out
  if (acc.skip or 0) > 0 then acc.skip = acc.skip - 1; return end
  acc.n, acc.total = acc.n + 1, acc.total + ms
  if acc.n <= 20000 then acc.ms[acc.n] = ms end
  if ms > acc.worst then acc.worst, acc.worstAt = ms, now end
  if ms > 33.3 then acc.over33 = acc.over33 + 1 end
  if ms > 100 then acc.over100 = acc.over100 + 1 end
  local b = math.min(2000, math.floor(ms * 2))
  acc.bins[b] = (acc.bins[b] or 0) + 1
end

local function accStats(acc)
  local need, seen, p99 = math.ceil(acc.n * 0.99), 0, 0
  for b = 0, 2000 do
    seen = seen + (acc.bins[b] or 0)
    if seen >= need then p99 = (b + 1) / 2; break end
  end
  -- The engine moves the world by a smoothed frame time: a lone slow frame is filtered out,
  -- two in a row (or slow, fast, slow) warp the game (pace.lua). slowPairs: frames that were
  -- slow, as was one of the two before, slow being over 1.5x (and 2x) the median frame.
  local half, p50 = math.ceil(acc.n * .5), 0
  seen = 0
  for b = 0, 2000 do
    seen = seen + (acc.bins[b] or 0)
    if seen >= half then p50 = (b + 1) / 2; break end
  end
  local pairs15, pairs2, list = 0, 0, acc.ms or {}
  for k = 3, #list do
    local a, b = list[k], math.max(list[k - 1], list[k - 2])
    if a > 1.5 * p50 and b > 1.5 * p50 then pairs15 = pairs15 + 1 end
    if a > 2 * p50 and b > 2 * p50 then pairs2 = pairs2 + 1 end
  end
  return {frames = acc.n, meanFrameMs = acc.n > 0 and acc.total / acc.n or 0, p99FrameMs = p99,
          worstFrameMs = acc.worst, worstAt = acc.worstAt, over33 = acc.over33, over100 = acc.over100,
          p50FrameMs = p50, slowPairs15 = pairs15, slowPairs2 = pairs2}
end

-- --- tile streaming ------------------------------------------------------------------------------
-- S.stream: the companion's stream status (region, tile size, ready tiles). S.tiles[key]:
-- {state = 'loading'|'loaded', i, j, manifest, group}. S.queue: items of loading tiles, in order.
-- Free flight used to keep the near bubble on the parked car, so the lens sat
-- in the far ring: fences and trees popped at the nose. Past this gap the
-- bubble follows the camera and look-ahead stays off.
local CAM_HANDOFF_M = 100
-- Cockpit and hood stay on the car. Every other camera past the gap owns the
-- bubble, so a free-flight name other than "free" or "orbit" still leaves the far ring.
local DRIVE_CAM = {driver = true, ['onboard.driver'] = true, cockpit = true, hood = true,
  driver_in = true, ['driver.driver'] = true, passenger = true}

local function focus()
  if S.replayPose then return S.replayPose.p, S.replayPose.v end
  if S.state == 'driving' then
    local veh = getPlayerVehicle(0)
    if veh then
      local p, v = veh:getPosition(), veh:getVelocity()
      local okName, name = pcall(function() return core_camera.getActiveCamName(0) end)
      local okPos, cam = pcall(function() return core_camera.getPosition() end)
      local dist
      if okPos and cam and p then
        local dx, dy, dz = cam.x - p.x, cam.y - p.y, cam.z - p.z
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)
      end
      S.camName = okName and name or nil
      S.camDist = dist
      S.heldCar = nil
      if okPos and cam and dist and dist > CAM_HANDOFF_M and not (okName and DRIVE_CAM[name]) then
        -- the car stays where it was parked: updateTiles keeps the ground under it. The camera's
        -- own motion is the velocity, so a flight gets its tiles ahead like a driven car.
        S.heldCar = {p.x, p.y}
        if S.camFrame ~= S.now then      -- focus() runs several times a frame
          local prev, vx, vy = S.camPrev, 0, 0
          if prev and (S.dt or 0) > 0 then vx, vy = (cam.x - prev[1]) / S.dt, (cam.y - prev[2]) / S.dt end
          if vx * vx + vy * vy > 250 ^ 2 then vx, vy = 0, 0 end   -- a jump, not a flight
          S.camPrev, S.camFrame, S.camVel = {cam.x, cam.y}, S.now, {vx, vy}
        end
        return vec3(cam.x, cam.y, cam.z), vec3(S.camVel[1], S.camVel[2], 0)
      end
      S.camPrev = nil
      return p, v
    end
  end
  local sp = S.landing and S.landing.spawn.pos
  if sp then return vec3(sp[1], sp[2], sp[3]), vec3(0, 0, 0) end
end

local function tileCentre(i, j)
  local t = S.stream.tile
  return (i + 0.5) * t, (j + 0.5) * t
end

local function tileOf(x, y)
  local t = S.stream.tile
  return math.floor(x / t), math.floor(y / t)
end

local function writePose()
  if S.now - S.poseAt < 0.5 then return end
  S.poseAt = S.now
  local p, v = focus()
  if not p then return end
  -- the planned route ahead (autopilot), so the companion builds along the road the car will take
  -- rather than straight along its heading: points every 250 m for the next 4 km
  local ahead
  if AP and AP.pts then
    ahead = {}
    local k, acc, nextAt = AP.idx, 0, 250
    while k < #AP.pts and acc < 4000 do
      acc = acc + math.sqrt((AP.pts[k + 1][1] - AP.pts[k][1]) ^ 2 + (AP.pts[k + 1][2] - AP.pts[k][2]) ^ 2)
      k = k + 1
      if acc >= nextAt then
        table.insert(ahead, {AP.pts[k][1], AP.pts[k][2], math.floor(acc)})
        nextAt = nextAt + 250
      end
    end
  end
  local active = {}
  for key, tile in pairs(S.tiles) do
    active[key] = tile.failed and 'error' or (tile.collided and 'collision_active' or
      (tile.roadComplete and 'loaded' or 'loading'))
  end
  S.poseSeq = (S.poseSeq or 0) + 1
  local pose = {x = p.x, y = p.y, z = p.z, vx = v.x, vy = v.y, t = os.time(), seq = S.poseSeq,
    region = S.stream and S.stream.region, state = S.state, ahead = ahead,
    active = active, deliveryP99 = S.deliveryP99 or 2}
  if NATIVE then native.pose(pose); return end
  -- a UDP datagram to the companion never blocks; writing pose.json once held a frame 5.2 s
  -- (fast-replay-game-05). The file stays as the fallback for an older companion.
  local port = S.status and S.status.posePort
  if port then
    if not S.udp or S.udpPort ~= port then
      local ok, sock = pcall(function() local s = (socket or require('socket')).udp(); s:settimeout(0); s:setpeername('127.0.0.1', port); return s end)
      S.udp, S.udpPort = ok and sock or nil, port
    end
    if S.udp and S.udp:send(jsonEncode(pose)) then return end
  end
  jsonWriteFile('e2r_world/pose.json', pose, false)
end

-- A game file a material names, by its own path or (a '.png' map) the '.dds' beside it, as the
-- game resolves its maps. Only the game's /assets are checked; our own art ships with the mod.
local assetSeen = {}
local function assetMissing(path)
  if type(path) ~= 'string' or path:sub(1, 8) ~= '/assets/' then return false end
  if assetSeen[path] == nil then
    local found = FS:fileExists(path) or (path:sub(-4) == '.png' and FS:fileExists(path:sub(1, -5) .. '.dds'))
    assetSeen[path] = found and true or false
  end
  return not assetSeen[path]
end

-- The road decals and the curb (fast_style.DECAL_FALLBACK) use maps an older game may not have:
-- such a material is loaded as its e2rFallback, the look it had before them.
local function materialFor(def)
  if type(def) ~= 'table' or not def.e2rFallback then return def end
  local fallback = def.e2rFallback
  def.e2rFallback = nil
  for _, stage in ipairs(def.Stages or {}) do
    for _, value in pairs(stage) do
      if assetMissing(value) then return fallback end
    end
  end
  return def
end

-- A texture pack's fields (and its warm-up materials) leave out a map the game does not have.
local function dropMissingMaps(fields)
  for _, f in pairs(fields or {}) do
    if type(f) == 'table' then
      for field, value in pairs(f) do
        if assetMissing(value) then f[field] = '' end
      end
      for _, stage in ipairs(f.Stages or {}) do
        for field, value in pairs(stage) do
          if assetMissing(value) then stage[field] = nil end
        end
      end
    end
  end
  return fields
end

-- Every tile's materials file defines all of the region's shared names. Loading a file re-creates
-- the materials that already exist ("duplicate material. Overwriting"), ~80 per tile, and the
-- frames after it stall for 1-3 s (route-05). So only the definitions not loaded yet go through
-- a small temporary file.
loadNewMaterials = function(path, stock)
  -- another climate's plants and stones: their level's material files, each once, before the
  -- first shape that needs them (generator VEG.stockFor), or it draws without material
  S.stockMats = S.stockMats or {}
  for _, file in ipairs(type(stock) == 'table' and stock or {}) do
    if type(file) == 'string' and not S.stockMats[file] then
      S.stockMats[file] = true
      if FS:fileExists(file) then loadJsonMaterialsFile(file) end
    end
  end
  if not path then return end
  local ok, defs = pcall(jsonReadFile, path)
  if not ok or type(defs) ~= 'table' then return end
  local fresh, n = {}, 0
  for name, def in pairs(defs) do
    if not S.knownMats[name] then
      fresh[name] = materialFor(def)
      S.knownMats[name] = true
      n = n + 1
    end
  end
  if n == 0 then return end
  S.matSeq = (S.matSeq or 0) + 1
  local tmp = string.format('e2r_world/materials_%d.json', S.matSeq)
  jsonWriteFile(tmp, fresh, false)
  loadJsonMaterialsFile('/' .. tmp)
  result.materialLoads = (result.materialLoads or 0) + 1
  result.materialsLoaded = (result.materialsLoaded or 0) + n
end

-- Past the vista: one plane VISTA.PLANE m out at the lowest ground the vista found (native.lua
-- vistaLow, vistaGround), without collision worth a thought (it lies under all the land). From
-- Mount Whitney the sky under the horizon read as a sea past the last block.
-- (one table: the main chunk is at LuaJIT's 200 locals)
-- 200 km: at 60 km the plane's edge sat 3 degrees under the horizon of a 4 km summit, a blue band
local VISTA = {PLANE = 200000}
function VISTA.plane(z, kind, cx, cy)
  local old = scenetree.findObject('e2r_vista_plane')
  if old then old:delete() end
  S.vistaPlaneAt = z and {z, kind, cx, cy} or nil
  if not z then return end
  local R, k = VISTA.PLANE, kind == 'ground' and 1 / 96 or 1 / 24   -- generator.lua COVER_SCALE
  local verts = {{x = -R, y = -R, z = 0}, {x = R, y = -R, z = 0}, {x = R, y = R, z = 0}, {x = -R, y = R, z = 0}}
  local up = {x = 0, y = 0, z = 1}
  local uvs = {}
  for n, v in ipairs(verts) do uvs[n] = {u = v.x * k, v = v.y * k} end
  local faces = {}
  for _, v in ipairs({0, 2, 1, 0, 3, 2}) do table.insert(faces, {v = v, n = v, u = v}) end
  local obj = createObject('ProceduralMesh')
  obj:registerObject('e2r_vista_plane')
  obj.canSave = false
  obj:createMesh({{{verts = verts, normals = {up, up, up, up}, uvs = uvs, faces = faces, material = 'e2rf_' .. kind}}})
  obj:setPosition(vec3(cx, cy, z))
end

-- The vista ring (native.lua VISTA_RADIUS, from a summit or a pass): the level's far clip and fog
-- follow it, so the land 24 km off draws and fades as the 5 km ring did; the pack's own values
-- come back when it ends. radius nil: no vista.
function VISTA.apply(radius)
  if S.vistaApplied == (radius or false) then return end
  S.vistaApplied = radius or false
  local info = scenetree.findObject('theLevelInfo')
  if not info then return end
  if radius then
    S.vistaBase = S.vistaBase or {visible = info:getField('visibleDistance', 0), fog = info:getField('fogDensity', 0)}
    local fog = tonumber(S.vistaBase.fog) or .00015
    info:setField('visibleDistance', 0, tostring(math.max(tonumber(S.vistaBase.visible) or 8000, VISTA.PLANE)))
    -- twice the 5 km ring's haze at its edge: the land 24 km off fades out, not cut against the sky
    info:setField('fogDensity', 0, tostring(fog * 2 * 5000 / radius))
  elseif S.vistaBase then
    info:setField('visibleDistance', 0, S.vistaBase.visible)
    info:setField('fogDensity', 0, S.vistaBase.fog)
    S.vistaBase = nil
  end
  pcall(function() info:postApply() end)
  result.vista = radius
end

-- A delivered manifest keeps only its item count (native.release).
local function itemCount(manifest) return manifest.itemCount or #(manifest.items or {}) end

local function tilePath(key, layer)
  local st = S.status and S.status.stream
  if NATIVE and st then
    local paths = layer == 'scene' and st.scenes or (layer == 'far' and st.far or st.tileManifests)
    return paths and paths[key]
  end
  return string.format('/e2r_stream/%s/tiles/%s%s.json', S.stream.region, key, layer and '.' .. layer or '')
end

local function startTile(key, i, j)
  local ok, manifest
  if NATIVE then ok, manifest = true, native.manifest(key, 'road')
  else ok, manifest = pcall(jsonReadFile, tilePath(key)) end
  if not ok or type(manifest) ~= 'table' then return end
  loadNewMaterials(manifest.materials, manifest.stockMaterials)
  local tile = {state = 'loading', i = i, j = j, manifest = manifest, group = tileGroup('E2RT_' .. key), decor = tileGroup('E2RD_' .. key, true),
                left = #manifest.items, roadLeft = #manifest.items, startedAt = S.now}
  S.tiles[key] = tile
  if manifest.nav then table.insert(S.navPending, {key = key, path = manifest.nav}) end
  if manifest.navSegments then
    table.insert(S.navPending, {key = key, data = {segments = manifest.navSegments,
      signals = manifest.navSignals, names = manifest.navNames}})
  end
  for _, it in ipairs(manifest.items) do table.insert(S.queue, {tile = tile, key = key, item = it}) end
  if #manifest.items == 0 then tile.state = 'loaded'; tile.roadComplete = true end
end

local function startScene(key, tile)
  local ok, manifest
  if NATIVE then ok, manifest = true, native.manifest(key, 'scene')
  else ok, manifest = pcall(jsonReadFile, tilePath(key, 'scene')) end
  if not ok or type(manifest) ~= 'table' or manifest.source ~= S.stream.region then return end
  loadNewMaterials(manifest.materials, manifest.stockMaterials)
  tile.sceneStarted = true
  tile.parking = manifest.parking
  -- Small POI records survive release of the scene's mesh tables and leave with the tile.
  tile.brandPOIs = manifest.brandPOIs
  tile.sceneGroup = tileGroup('E2RS_' .. key)
  tile.sceneLeft = queueItems(manifest.items, tile, key, 'scene')
  if M.signals then M.signals.addTile(key, manifest.lights) end
  if (tile.flowLights and #tile.flowLights > 0) or (manifest.lights and #manifest.lights > 0) then
    S.flowLightVersion = (S.flowLightVersion or 0) + 1
    -- Roads may already be in the graph. Refresh just its signal edges in a batch; a scene
    -- arriving does not require another expensive map.reset of the road graph.
    S.signalDirty = true
  end
  tile.flowLights = manifest.lights
  tile.sceneComplete = tile.sceneLeft == 0
  tile.left = tile.left + tile.sceneLeft
  if NATIVE and tile.refreshScene then native.release(key, 'road'); tile.refreshScene = nil end
  if NATIVE and tile.sceneComplete then native.release(key, 'scene') end
end

-- A tile's grass, flowers and loose stones, built after its scene while driving (native.lua
-- sceneReady). Nearly all of it goes to the detail stream round the car; the odd bush is a job.
local function startGrass(key, tile)
  tile.grassStarted = true
  local manifest = native.manifest(key, 'grass')
  if type(manifest) ~= 'table' or manifest.source ~= S.stream.region then return end
  loadNewMaterials(nil, manifest.stockMaterials)
  tile.grassLeft = queueItems(manifest.items, tile, key, 'grass')
  tile.left = tile.left + tile.grassLeft
  if tile.grassLeft == 0 then native.release(key, 'grass') end
end

-- --- traffic -----------------------------------------------------------------------------------
-- The game's AI drives on a navgraph built from DecalRoads; ours are ProceduralMesh, so the graph
-- comes from the tiles (<key>.nav.json, fast.nav_segments) and goes to map.reset(nodes). Built
-- also for the stock minimap, from the segments within NAV_R of the car, again once the car has gone
-- NAV_MOVE m from the last build (a rebuild is one frame of ~30 us a node).
local NAV_R, NAV_MOVE = 1000, 250
-- Which cars drive: the game's light 'simple_traffic' (Type PropTraffic; the parked ones are
-- PropParked), its full soft-body vehicles, or the Agent Traffic mod's EU cars (full too). The
-- game's own group follows its setting trafficSimpleVehicles (true by default in 0.40), so both
-- of ours are built here. The road AI and the navgraph are the same for all three. group(amount)
-- is the vehicle group, nil when the kind is not installed (the game's own group then). Kinds and
-- amounts share one table: world.lua is at LuaJIT's 200 chunk locals.
local function stockGroup(amount, filters)
  if not core_multiSpawn then extensions.load('core_multiSpawn') end
  local utils = gameplay_traffic_trafficUtils
  if not (core_multiSpawn and utils and utils.getBaseGroupParams) then return end
  local ok, group = pcall(function()
    local params = utils.getBaseGroupParams()
    params.allConfigs = true
    if filters.Type.proptraffic then params.minPop, params.maxYear = 0, nil end
    for k, v in pairs(filters) do params.filters[k] = v end
    return core_multiSpawn.createGroup(amount, params)
  end)
  if ok and type(group) == 'table' and #group > 0 then return group end
end
local TRAFFIC_KINDS = {
  {'simple', 'Прості', 'Simple', source = 'simple', group = function(amount)
    return stockGroup(amount, {Type = {proptraffic = 1}})
  end},
  {'full', 'Повні', 'Full', source = 'full', group = function(amount)
    return stockGroup(amount, {Type = {car = 1, truck = 0.6}, ['Config Type'] = {Police = 0, other = 1}})
  end},
  {'agent', 'Agent Traffic', 'Agent Traffic', source = 'Agent Traffic EU', group = function(amount)
    local file = '/vehicleGroups/agentTraffic/agent_traffic_eu.vehGroup.json'
    if not FS:fileExists(file) then return end
    local ok, g = pcall(jsonReadFile, file)
    if not (ok and g and g.data and #g.data > 0) then return end
    local group = {}
    for k = 1, amount do group[k] = deepcopy(g.data[math.random(#g.data)]) end
    return group
  end},
  -- parked in Kyiv each simple car is ~1.5 ms of the frame (16: 34 ms, 32: 62, 48: 95; traffic-07):
  -- real cars stay the near layer, a crowd needs cars without physics (docs/NATIVE_MODS.md)
  amounts = {{0, 'Вимк', 'Off'}, {4, '4', '4'}, {8, '8', '8'}, {16, '16', '16'}, {24, '24', '24'}},
  -- the flow's cars (flow.lua): no physics, no collision
  flow = {{0, 'Вимк', 'Off'}, {100, '100', '100'}, {200, '200', '200'}, {400, '400', '400'}},
  -- how many of them round the player are real cars one can hit (handoff.lua), ~1.5 ms each
  real = {{0, 'Вимк', 'Off'}, {4, '4', '4'}, {8, '8', '8'}, {12, '12', '12'}, {16, '16', '16'}}}
-- (pedestrians: a 0..1000 slider and a switch, options 'walkers' and 'walkersOn', drawPeopleRows)

local function navRead()
  local job = table.remove(S.navPending, 1)
  if not job then return end
  local ok, data = true, job.data
  if not data then ok, data = pcall(jsonReadFile, job.path) end
  if not ok or type(data) ~= 'table' or not data.segments then return end
  -- the tile's traffic lights {x, y} for the flow (flow.lua), while the tile is loaded
  S.navLights = S.navLights or {}
  local oldLights = S.navLights[job.key]
  local newLights = data.signals and #data.signals > 0 and data.signals or nil
  S.navLights[job.key] = newLights
  if oldLights or newLights then S.flowLightVersion = (S.flowLightVersion or 0) + 1 end
  for _, s in ipairs(data.segments) do
    local seg = S.nav[s[1]]
    if not seg then
      local n = (#s - 7) / 3
      local mid = 8 + 3 * math.floor((n - 1) / 2)
      seg = {s = require('ge/extensions/e2r/navigation').simplify(s), tiles = {}, x = s[mid], y = s[mid + 1]}
      local box = {math.huge, math.huge, -math.huge, -math.huge}
      for k = 8, #seg.s - 2, 3 do
        local px, py = seg.s[k], seg.s[k + 1]
        box[1], box[2], box[3], box[4] = math.min(box[1], px), math.min(box[2], py), math.max(box[3], px), math.max(box[4], py)
      end
      seg.box, seg.names = box, data.names and data.names[s[1]]
      S.nav[s[1]] = seg
      S.navDirty = true
    end
    seg.tiles[job.key] = true
  end
end

-- The line of where the car is (location.lua): looked up four times a second, drawn every frame
-- from the strings it left. Off in the widget (settings/earthng.json).
function M.locationStep()
  if not M.location or S.locationOff or S.now < (S.locationAt or 0) then return end
  S.locationAt = S.now + .25
  local p, v = focus()
  if not p then return end
  local lat, lon = native.toGeo(p.x, p.y)
  S.location = S.location or M.location.new()
  S.locationEnv = S.locationEnv or {places = planetMap.settlements,
    near = function(name) return string.format(L('поблизу %s', 'near %s'), name) end,
    region = function()
      local country, descriptor = native.at(S.locationEnv.lat, S.locationEnv.lon)
      if country then
        S.locationRegion = descriptor and descriptor.section == true and (descriptor.title or descriptor.id) or nil
        S.locationCountry = planetMap.countryName(country.title, lang)
      end
      return S.locationRegion, S.locationCountry
    end}
  local env = S.locationEnv
  env.segments, env.lat, env.lon, env.lang = S.nav, lat, lon, lang
  M.location.step(S.location, S.now, p.x, p.y, v and v.x or 0, v and v.y or 0, env)
end

local function trafficRunning()
  return gameplay_traffic and gameplay_traffic.getState and gameplay_traffic.getState() ~= 'off'
end

local function navBuild()
  local p = focus()
  if not p then return end
  local t = hptimer()
  local nodes, segs, count = {}, 0, 0
  local function node(id, x, y, z, r)
    local n = nodes[id]
    if not n then
      n = {pos = vec3(x, y, z), radius = r, links = {}}
      nodes[id] = n
      count = count + 1
    elseif r > n.radius then
      n.radius = r
    end
    return id
  end
  for sid, seg in pairs(S.nav) do
    -- a segment whose every tile has gone goes too
    local alive = false
    for key in pairs(seg.tiles) do
      if S.tiles[key] then alive = true else seg.tiles[key] = nil end
    end
    if not alive then
      S.nav[sid] = nil
    elseif (seg.x - p.x) ^ 2 + (seg.y - p.y) ^ 2 < NAV_R * NAV_R then
      local s = seg.s
      local a, b, lanes, speed, radius, drive = s[2], s[3], s[4], s[5], s[6], s[7]
      local n = (#s - 7) / 3
      local oneWay = not lanes:find('-', 1, true)
      local prev
      for k = 1, n do
        local o = 8 + 3 * (k - 1)
        local id = k == 1 and ('e2r_n' .. tostring(a)) or k == n and ('e2r_n' .. tostring(b)) or ('e2r_s' .. sid .. '_' .. k)
        -- never a self-link or a zero-length edge: the game's random route walk (graphpath
        -- getRandomPathG, traffic respawns) adds edge lengths and froze on a piece of graph without
        -- any. An inner knot on top of the last one is skipped; an end node always stays.
        local pp = prev and nodes[prev].pos
        local same = pp and (prev == id or (pp.x - s[o]) ^ 2 + (pp.y - s[o + 1]) ^ 2 < 1e-4)
        if same and k < n then goto knot end
        node(id, s[o], s[o + 1], s[o + 2], radius)
        if prev and not same then
          local data = {drivability = drive, oneWay = oneWay, lanes = lanes, speedLimit = speed,
                        inNode = prev, outNode = id, inPos = nodes[prev].pos, outPos = nodes[id].pos,
                        inRadius = nodes[prev].radius, outRadius = nodes[id].radius}
          nodes[prev].links[id] = data
          nodes[id].links[prev] = data
        end
        prev = id
        ::knot::
      end
      segs = segs + 1
    end
  end
  -- junction radii grew after their first links were made
  for _, n in pairs(nodes) do
    for lid, data in pairs(n.links) do
      data.inRadius, data.outRadius = nodes[data.inNode].radius, nodes[data.outNode].radius
    end
  end
  local tLua = t:stop()
  -- map.reset(custom) puts our table in map.nodes; the traffic extension keeps the old one
  -- (mapNodes, refreshed only on respawns) and indexed it every frame with our node names
  -- (traffic.lua:1252 "attempt to index a nil value", traffic-03). The old table keeps its place.
  local m = map.getMap()
  local keep = m.nodes
  local rules = map.getRoadRules and map.getRoadRules()
  if rules and native.keepsLeft then rules.rightHandDrive = native.keepsLeft() end
  map.reset(nodes)
  if M.signals then
    M.signals.navgraph(nodes, S.nav, p.x, p.y, trafficRunning(), vec3)
    S.signalDirty, S.signalAt = false, S.now
  end
  m = map.getMap()
  if keep and m.nodes ~= keep then
    table.clear(keep)
    for k, v in pairs(m.nodes) do keep[k] = v end
    m.nodes = keep
  end
  S.navSerial = m.buildSerial
  -- BeamNG 0.38+ caches a separate spatial tree for its stock minimap. map.reset does not
  -- invalidate that tree. Do not load the app if it is disabled/absent on an older game.
  if ui_apps_minimap_roads and ui_apps_minimap_roads.reset then ui_apps_minimap_roads.reset() end
  S.navDirty, S.navAt, S.navPos = false, S.now, {p.x, p.y}
  S.navStats = {nodes = count, segments = segs, ms = t:stop(), luaMs = tLua}
  result.nav = S.navStats
end

local function navStep()
  if #S.navPending > 0 then navRead() end
  if not S.stream or not map or not map.getMap then return end
  -- someone else (an editor tool, a mission) rebuilt the graph from the empty level: ours again
  local current = map.getMap()
  local foreign = S.navSerial and current.buildSerial ~= S.navSerial
  local p = focus()
  local moved = p and (not S.navPos or (p.x - S.navPos[1]) ^ 2 + (p.y - S.navPos[2]) ^ 2 > NAV_MOVE * NAV_MOVE)
  -- New tiles must appear even while parked. Batch updates instead of resetting per tile.
  if foreign or moved or S.navDirty then
    if S.now - (S.navAt or -10) >= 2 then navBuild() end
    return
  end
  -- A late scene changes lights, not roads. Use only our current graph and let a pending
  -- road rebuild take precedence, so signals never attach to a stale or foreign graph.
  if S.signalDirty and p and M.signals and S.navSerial and current.buildSerial == S.navSerial
    and current.nodes and next(current.nodes) and S.now - (S.signalAt or -10) >= 2 then
    M.signals.navgraph(current.nodes, S.nav, p.x, p.y, trafficRunning(), vec3)
    S.signalDirty, S.signalAt = false, S.now
  end
end

local function setTraffic(amount, kind)
  if not gameplay_traffic then extensions.load('gameplay_traffic') end
  if not gameplay_traffic then S.lastError = L('gameplay_traffic недоступний', 'gameplay_traffic is not available'); return end
  S.trafficAmount = amount
  S.trafficKind = kind or S.trafficKind or 'simple'
  if amount == 0 then
    S.trafficWanted = nil
    gameplay_traffic.deleteVehicles()
    return
  end
  S.trafficWanted = true
  navBuild()
  if not next(map.getMap().nodes or {}) then
    S.lastError = L('Трафік: доріг поруч ще немає', 'Traffic: no roads nearby yet')
    return
  end
  local options = {}
  for _, k in ipairs(TRAFFIC_KINDS) do
    if k[1] == S.trafficKind then options.vehGroup = k.group(amount); S.trafficSource = k.source end
  end
  -- full, or the chosen kind is not installed: the game's own group
  if not options.vehGroup then S.trafficSource = 'game cars' end
  result.trafficSource = S.trafficSource
  result.trafficKind = S.trafficKind
  gameplay_traffic.setupTraffic(amount, options)
end

-- The flow (flow.lua): hundreds of cars without physics on the graph of the tiles (S.nav), one
-- TSStatic each in a group outside the MissionGroup (no collision). Round the player's car the
-- nearest of them are real simple_traffic cars (handoff.lua), so the cars one can hit are real.
-- The player's car, those real cars and the game's AI traffic are the flow's obstacles.
function M.flowSet(n)
  local fs, hs = M.flowSim, M.handoffSim
  if n > 0 and not S.flow then
    local F = fs.new{leftHand = fs.leftHand(S.stream and S.stream.country), seed = math.floor(S.now * 1000) % 100000 + 1,
      paints = fs.SHARE, bodies = fs.BODY_SHARE}
    local shapes = {}
    for b, body in ipairs(fs.BODIES) do
      shapes[b] = {}
      for k, paint in ipairs(fs.PAINTS) do shapes[b][k] = '/levels/e2r_world/art/flow/car_' .. body .. '_' .. paint .. '.dae' end
    end
    -- the game's simple cars, picked once (a group scans every config) and sorted by the flow's
    -- bodies, so a flow sedan becomes a real sedan; a body the group lacks takes stock configs
    local t = hptimer()
    local byBody, k = hs.byBody(TRAFFIC_KINDS[1].group(48)), {}
    local api = hs.gameApi(fs.PAINT_RGB, function(body)
      body = body or 1
      k[body] = (k[body] or 0) + 1
      local list = byBody[body]
      if list and #list > 0 then return list[(k[body] - 1) % #list + 1] end
      local stock = hs.STOCK[body] or hs.STOCK[1]
      return {model = 'simple_traffic', config = stock[(k[body] - 1) % #stock + 1]}
    end)
    api.ms.group = t:stop()
    S.flow = {F = F, V = fs.view(F, shapes, tileGroup('E2R_flow', true)), H = hs.new{bodies = fs.BODY_SHARE,
      size = S.flowReal or hs.SIZE}, api = api}
    local veh = getPlayerVehicle(0)
    local q = veh and veh:getPosition() or focus()
    if q then hs.prewarm(S.flow.H, api, q.x, q.y) end
  end
  if S.flow then fs.setTarget(S.flow.F, n) end
  if n == 0 and S.flow then
    hs.clear(S.flow.H, S.flow.api)
    dropGroup('E2R_flow')
    S.flow = nil
  end
  result.flowTarget = n
end

-- the real cars round the player: a bigger pool is spawned now (one wait, ~0.5 s a car), a
-- smaller one hands its extra cars back to the flow (handoff.lua)
function M.flowReal(n)
  S.flowReal = n
  local fl = S.flow
  if fl then
    fl.H.size = n
    local veh = getPlayerVehicle(0)
    local q = veh and veh:getPosition() or focus()
    if q and #fl.H.pool < M.handoffSim.target(fl.H) then M.handoffSim.prewarm(fl.H, fl.api, q.x, q.y) end
  end
  result.flowReal = n
end

function M.flowStep()
  local fs, fl = M.flowSim, S.flow
  local p = focus()
  if not p then return end
  local t = hptimer()
  -- the graph follows navBuild (new tiles, 250 m of driving)
  local sceneChanged = fl.lightVersion ~= (S.flowLightVersion or 0)
  if fl.syncAt ~= S.navAt or (sceneChanged and S.now - (fl.lightAt or -10) >= 1) then
    fl.syncAt = S.navAt
    fl.lightVersion, fl.lightAt = S.flowLightVersion or 0, S.now
    local lights, sceneLights = {}, {}
    for key, list in pairs(S.navLights or {}) do
      if S.tiles[key] then
        for _, q in ipairs(list) do lights[#lights + 1] = q end
      else
        S.navLights[key] = nil
      end
    end
    for _, tile in pairs(S.tiles) do
      for _, light in ipairs(tile.flowLights or {}) do sceneLights[#sceneLights + 1] = light end
    end
    fs.sync(fl.F, S.nav, p.x, p.y, lights, sceneLights)
    fl.syncMs = t:stopAndReset()
  end
  local obs = {}
  local veh = getPlayerVehicle(0)
  local car = veh and veh:getPosition()
  local pv
  if veh then
    pv = veh:getVelocity()
    obs[1] = {x = car.x, y = car.y, vx = pv.x, vy = pv.y}
  end
  M.handoffSim.obstacles(fl.H, fl.api, obs)
  -- pedestrians crossing a road (walkers.lua): the flow's cars stop for them
  if S.walk then
    for _, w in ipairs(S.walk.W.onRoad or {}) do obs[#obs + 1] = {x = w.x, y = w.y, vx = 0, vy = 0} end
  end
  -- every other physical car in the level: the game's traffic, a second car the player spawned,
  -- police in a pursuit. Only the game's traffic used to count, so the flow drove through the rest.
  local mine = {}
  for _, e in ipairs(fl.H.pool) do mine[e.id] = true end
  for i = 0, be:getObjectCount() - 1 do
    local o = be:getObject(i)
    local id = o and o:getID()
    if id and not mine[id] and o ~= veh and be:getObjectActive(id) then
      local q, v = o:getPosition(), o:getVelocity()
      obs[#obs + 1] = {x = q.x, y = q.y, vx = v.x, vy = v.y}
    end
  end
  -- the simulation's time, as the physics cars round them: paused or in slow motion the flow
  -- used to drive on at full speed through the real cars standing still
  fs.step(fl.F, S.dtSim or S.dt or 1 / 60, p.x, p.y, obs, S.now, M.signals and M.signals.current)
  -- the swap follows the player's car, not a free camera: the cars one can hit are round it
  if car then M.handoffSim.step(fl.H, fs, fl.F, car.x, car.y, S.now, fl.api, pv.x, pv.y) end
  fl.simMs = t:stopAndReset()
  fl.moved = fs.draw(fl.F, fl.V, p.x, p.y)
  fl.drawMs = t:stop()
  local r = result.flow or {}
  result.flow = r
  r.cars, r.links, r.simMs, r.drawMs, r.syncMs = fl.F.count, fl.F.linkList and #fl.F.linkList or 0, fl.simMs, fl.drawMs, fl.syncMs
  r.simMax, r.drawMax = math.max(r.simMax or 0, fl.simMs), math.max(r.drawMax or 0, fl.drawMs)
  r.syncMax = math.max(r.syncMax or 0, fl.syncMs or 0)
  r.stats = fl.F.stats
  r.real, r.pool, r.handoff, r.handoffMs = M.handoffSim.activeCount(fl.H), #fl.H.pool, fl.H.stats, fl.api.ms
  r.handoffSpawns = fl.api.spawns
  r.crossings, r.lights, r.atRed = fl.F.crossings or 0, fl.F.lights and #fl.F.lights or 0, fl.F.atRed or 0
  -- once a second the shapes as drawn against their lanes (flow.poseCheck)
  if test and S.now - (fl.poseAt or -1) >= 1 then
    fl.poseAt = S.now
    local ok, yawErr, noseErr, n = pcall(fs.poseCheck, fl.F, fl.V, 40)
    if ok and n > 0 then
      r.poseErr = r.poseErr or {yaw = 0, nose = 0, cars = 0}
      r.poseErr.yaw, r.poseErr.nose = math.max(r.poseErr.yaw, yawErr), math.max(r.poseErr.nose, noseErr)
      r.poseErr.cars = r.poseErr.cars + n
    elseif not ok then
      r.poseErr = {error = tostring(yawErr)}
    end
  end
end

-- Pedestrians (walkers.lua) on the sidewalks of the same graph, drawn as static pose shapes in a
-- group outside the MissionGroup. A vehicle with physics about to touch one (the player's car, the
-- real cars of the hand-off, the game's traffic) meets a physical body in its place (pedhit.lua).
-- The walkers' shapes: the walk poses, then the one waiting at the kerb (walkers.view); with blood,
-- the blood stains' too. The landing warms them when walkers will come with the drive: a shape's
-- first TSStatic costs ~12 ms, and a walker's first posed set (all nine at once) was a 110 ms frame
-- in every drive with walkers (polish-01..03).
function M.peopleShapes(blood)
  local ws, dir = M.walkSim, '/levels/e2r_world/art/people/'
  local shapes = {}
  for k = 0, ws.POSES - 1 do shapes[k + 1] = dir .. 'ped_walk' .. k .. '.dae' end
  shapes[ws.POSES + 1] = dir .. 'ped_stand.dae'
  if blood then shapes[#shapes + 1] = dir .. 'blood_splat.dae'; shapes[#shapes + 1] = dir .. 'blood_spray.dae' end
  return shapes
end

-- M.walkersSet(n [, now]): n walkers asked, clamped to 0..walkers.MAX (1000). Cheap to call every
-- frame of a slider drag: the count changes in place and the shapes follow a few a frame. 0 hides
-- every walker at once and releases the objects, the group and the body pool 2 s later unless a
-- count comes back (now: at once). Asked before the drive (the menu, a landing), the count is kept
-- and the walkers come with the drive. M.walkersGet() -> asked, walking, room (see walkers.counts).
function M.walkersSet(n, now)
  local ws, ph, wk = M.walkSim, M.pedHit, S.walk
  n = math.max(0, math.min(ws.MAX, math.floor(tonumber(n) or 0)))
  result.walkTarget = n
  if n == 0 then
    if not wk then return end
    if now or wk.parked or S.state ~= 'driving' then
      if wk.V then ws.clear(wk.W, wk.V) end
      -- the body pool stays, parked (inactive: no cost): spawning it again is ~0.25 s a body in
      -- one frame, a 1.5 s stall each time pedestrians come back on (verify-01)
      if wk.P then ph.parkAll(wk.P, wk.api); S.walkPool = {P = wk.P, api = wk.api} end
      M.walkBloodClear(wk)
      dropGroup('E2R_walkers')
      S.walk = nil
    else
      ws.setTarget(wk.W, 0)
      wk.zeroAt = wk.zeroAt or S.now
    end
    return
  end
  if not wk then
    wk = {W = ws.new{seed = math.floor(S.now * 1000) % 100000 + 7}, parked = true, boxes = {}, H = {}}
    S.walk = wk
  end
  wk.zeroAt = nil
  ws.setTarget(wk.W, n)
  if not (wk.parked and S.state == 'driving') then return end
  wk.V, wk.parked, wk.syncAt = ws.view(wk.W, M.peopleShapes(), tileGroup('E2R_walkers', true)), nil, nil
  if not wk.ground then
    -- the ground under a walker: one vec3 filled again (no garbage per read)
    local at = vec3(0, 0, 0)
    wk.timer = hptimer()
    wk.ground = function(x, y, z)
      at.x, at.y, at.z = x, y, z + 2
      local h = be:getSurfaceHeightBelow(at)
      if h and h > -1e6 then return h end
    end
  end
  if not wk.P and S.walkPool then   -- the pool parked when the count went to 0
    wk.api, wk.P, S.walkPool = S.walkPool.api, S.walkPool.P, nil
  end
  if not wk.P then
    wk.api, wk.P = ph.gameApi(ws), ph.new{size = S.walkBodies or ph.SIZE}
    M.walkBloodBind(wk)
    local veh = getPlayerVehicle(0)
    local q = veh and veh:getPosition() or focus()
    -- a few bodies now so the first hit works; more on demand near a stop (SIZE=24 at once would hitch ~5 s)
    local t = hptimer()
    if q then
      for _ = 1, math.min(4, wk.P.size) do
        if not ph.prewarmOne(wk.P, wk.api, q.x, q.y) then break end
      end
    end
    wk.spawnMs = t:stop()
    if veh and getPlayerVehicle(0) ~= veh then pcall(function() be:enterVehicle(0, veh) end) end
  elseif wk.api and not wk.api.splat then
    M.walkBloodBind(wk)
  end
end

function M.walkersGet()
  if not S.walk then return 0, 0, 0 end
  return M.walkSim.counts(S.walk.W)
end

-- Blood stains of pedhit hits (api.splat): flat alpha-tested TSStatic quads of people_art, blood_splat
-- (a round stain) and blood_spray (thrown along its +x). A hit leaves a stain where it struck, a spray
-- or two further along the car's way, one on a wall, pole or fence ahead within 4 m, and one on the
-- car; a body come to rest bleeds a pool that spreads for a few seconds (pedhit, kind 'pool'). Ground
-- and wall stains lie on the surface a ray finds, tilted to its normal, and stay BLOOD.ttl s, until
-- the player is BLOOD.farR m away, or until the oldest go past BLOOD.max. A car stain hangs on three
-- of the car's nodes, the top of its body where it struck (bumper, hood, windscreen), so it moves,
-- tilts and dents with the car; it goes when the car is reset (M.onVehicleResetted) or gone.
-- one table, not locals: the main chunk is at LuaJIT's 200 locals
local BLOOD = {dir = '/levels/e2r_world/art/people/', max = 96, ttl = 1200, carTtl = 900, farR = 1500,
  carMax = 6, lift = .025, carLift = .06}

function BLOOD.take(B, shape)
  local pool = B.pool[shape]
  if not pool then pool = {}; B.pool[shape] = pool end
  local obj = pool[#pool]
  if obj then
    pool[#pool] = nil
    obj:setHidden(false)
    return obj
  end
  obj = createObject('TSStatic')
  obj:setField('shapeName', 0, BLOOD.dir .. shape .. '.dae')
  obj:setField('collisionType', 0, 'None')
  obj:setField('decalType', 0, 'None')
  obj.useInstanceRenderData = true
  obj.canSave = false
  obj:registerObject('')
  local g = scenetree.findObject('E2R_blood') or tileGroup('E2R_blood', true)
  g:addObject(obj)
  return obj
end

function BLOOD.drop(B, s)
  local obj = s and s.obj
  if not obj then return end
  s.obj = nil
  local pool = B.pool[s.shape]
  if not pool then pool = {}; B.pool[s.shape] = pool end
  if #pool < 16 then
    pcall(function() obj:setHidden(true) end)
    pool[#pool + 1] = obj
  else
    pcall(function() obj:delete() end)
  end
end

-- the stain's frame: its z along the normal n, its x along the hint t laid into the surface
function BLOOD.pose(s, px, py, pz, nx, ny, nz, tx, ty, tz)
  local d = tx * nx + ty * ny + tz * nz
  tx, ty, tz = tx - nx * d, ty - ny * d, tz - nz * d
  local l = math.sqrt(tx * tx + ty * ty + tz * tz)
  if l < 1e-3 then
    -- the hint along the normal: any tangent
    if math.abs(nz) < .9 then tx, ty, tz = -ny, nx, 0 else tx, ty, tz = 1, 0, 0 end
    d = tx * nx + ty * ny + tz * nz
    tx, ty, tz = tx - nx * d, ty - ny * d, tz - nz * d
    l = math.sqrt(tx * tx + ty * ty + tz * tz)
  end
  tx, ty, tz = tx / l, ty / l, tz / l
  -- quatFromDir puts y along its first vector and z towards the second: y = n x t
  local q = quatFromDir(vec3(ny * tz - nz * ty, nz * tx - nx * tz, nx * ty - ny * tx), vec3(nx, ny, nz))
  local lift = s.lift or BLOOD.lift
  pcall(s.obj.setPosRot, s.obj, px + nx * lift, py + ny * lift, pz + nz * lift, q.x, q.y, q.z, q.w)
end

-- the first static surface on a ray (roads, buildings, poles, terrain): point and normal, or nil;
-- a vehicle in the way (a lying body, a car) is no surface for a stain
function BLOOD.surface(x, y, z, dx, dy, dz, len)
  if not (Engine and Engine.castRay) then return end
  local ok, hit = pcall(Engine.castRay, vec3(x, y, z), vec3(x + dx * len, y + dy * len, z + dz * len), true, false)
  if not ok or type(hit) ~= 'table' or not hit.pt then return end
  local o = hit.obj
  if o then
    local okC, cls = pcall(function() return o:getClassName() end)
    if okC and cls == 'BeamNGVehicle' then return end
  end
  local p, n = hit.pt, hit.norm
  if not n then return p.x, p.y, p.z, 0, 0, 1 end
  return p.x, p.y, p.z, n.x, n.y, n.z
end

-- a wall, pole or fence on a level ray: static collision (castRayStatic, as knock's fliers; the
-- generated buildings answer it, Engine.castRay found only trees, blood-03). Taken upright: its
-- normal level, from two more rays 0.4 m to either side (window sills and recesses tipped a normal
-- from a ray above, blood-05); point and normal, or nil
function BLOOD.wall(x, y, z, dx, dy, len)
  if not castRayStatic then return end
  local dir = vec3(dx, dy, 0)
  local function dist(ox, oy)
    local ok, d = pcall(castRayStatic, vec3(ox, oy, z), dir, len + .6)
    if ok and type(d) == 'number' and d < len + .6 then return d end
  end
  local d0 = dist(x, y)
  if not d0 or d0 > len then return end
  local sx, sy = -dy * .4, dx * .4
  local dl, dr = dist(x - sx, y - sy), dist(x + sx, y + sy)
  local nx, ny = -dx, -dy
  if dl and dr and math.abs(dl - dr) < .8 then
    -- the wall's run from the left hit to the right one; its normal faces back along the ray
    local ax, ay = 2 * sx + dx * (dr - dl), 2 * sy + dy * (dr - dl)
    local l = math.sqrt(ax * ax + ay * ay)
    nx, ny = -ay / l, ax / l
    if nx * dx + ny * dy > 0 then nx, ny = -nx, -ny end
  end
  return x + dx * d0, y + dy * d0, z, nx, ny, 0, d0
end

-- how far the car's skin stands over a node along n: a ray down onto the car's own mesh, or
-- BLOOD.carLift where it finds none (a stain on the node itself sank under the hood, blood-03)
function BLOOD.skin(vid, px, py, pz, nx, ny, nz)
  if Engine and Engine.castRay then
    local ok, hit = pcall(Engine.castRay, vec3(px + nx, py + ny, pz + nz), vec3(px - nx * .3, py - ny * .3, pz - nz * .3),
      false, true)
    if ok and type(hit) == 'table' and hit.pt then
      local okI, hid = pcall(function() return hit.obj and hit.obj:getID() end)
      if okI and hid == vid then
        local d = (hit.pt.x - px) * nx + (hit.pt.y - py) * ny + (hit.pt.z - pz) * nz
        if d > -.1 and d < .3 then return math.max(.015, d + .015), true end
      end
    end
  end
  return BLOOD.carLift, false
end

function BLOOD.ground(x, y, z)
  local px, py, pz, nx, ny, nz = BLOOD.surface(x, y, z + 1.5, 0, 0, -1, 4)
  if px and nz > .5 then return px, py, pz, nx, ny, nz end
  local h = be:getSurfaceHeightBelow(vec3(x, y, z + 1.5))
  if h and h > -1e6 then return x, y, h, 0, 0, 1 end
end

function BLOOD.lay(B, s, px, py, pz, nx, ny, nz, tx, ty, tz)
  if B.n >= BLOOD.max then
    BLOOD.drop(B, B.list[1])
    table.remove(B.list, 1)
    B.n = B.n - 1
  end
  s.obj, s.at, s.x, s.y = BLOOD.take(B, s.shape), S.now, px, py
  B.n = B.n + 1
  B.list[B.n] = s
  local k = s.grow and .3 or 1
  s.obj:setScale(vec3(s.len * k, s.wid * k, 1))
  BLOOD.pose(s, px, py, pz, nx, ny, nz, tx, ty, tz)
  return s
end

-- a car stain: the highest node of the car within .25 m (seen from above) of a point on its hood
-- (0.3 to 1.2 m behind the front), across where it struck, and two nodes near it on the same
-- surface (one across, one along) to tilt the stain with; nil where the car has no node there
function BLOOD.carAnchor(veh, h, x, y)
  local okN, count = pcall(function() return veh:getNodeCount() end)
  if not okN or not count or count < 4 then return end
  local o = veh:getPosition()
  local fx, fy, lx, ly = h.fx, h.fy, -h.fy, h.fx
  local dx, dy = x - h.x, y - h.y
  local across = math.max(-h.hw + .2, math.min(h.hw - .2, dx * lx + dy * ly))
  local along = h.hl - .3 - math.random() * .9
  local cx, cy = h.x + fx * along + lx * across - o.x, h.y + fy * along + ly * across - o.y
  local pos, a, az = {}, nil, -1e9
  for id = 0, count - 1 do
    local p = veh:getNodePosition(id)
    pos[id] = p
    if (p.x - cx) ^ 2 + (p.y - cy) ^ 2 < .0625 and p.z > az then a, az = id, p.z end
  end
  if not a then return end
  local pa, b, c, db, dc = pos[a], nil, nil, 1e9, 1e9
  for id = 0, count - 1 do
    local p = pos[id]
    local ex, ey, ez = p.x - pa.x, p.y - pa.y, p.z - pa.z
    local dh = math.sqrt(ex * ex + ey * ey)
    if dh > .12 and dh < .6 and math.abs(ez) < .3 then
      if math.abs(ex * lx + ey * ly) > .8 * dh and dh < db then b, db = id, dh end
      if math.abs(ex * fx + ey * fy) > .8 * dh and dh < dc then c, dc = id, dh end
    end
  end
  return a, b and c and b or nil, b and c and c or nil
end

-- where a car stain is now: point, outward normal, tangent hint (towards the car's back)
function BLOOD.onCar(s, veh)
  local o, pa, up, f = veh:getPosition(), veh:getNodePosition(s.a), veh:getDirectionVectorUp(), veh:getDirectionVector()
  local nx, ny, nz = up.x, up.y, up.z
  if s.b then
    local pb, pc = veh:getNodePosition(s.b), veh:getNodePosition(s.c)
    local ux, uy, uz = pb.x - pa.x, pb.y - pa.y, pb.z - pa.z
    local vx, vy, vz = pc.x - pa.x, pc.y - pa.y, pc.z - pa.z
    local cx, cy, cz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    local l = math.sqrt(cx * cx + cy * cy + cz * cz)
    if l > 1e-4 then
      nx, ny, nz = cx / l, cy / l, cz / l
      if nx * up.x + ny * up.y + nz * up.z < 0 then nx, ny, nz = -nx, -ny, -nz end
    end
  end
  return o.x + pa.x, o.y + pa.y, o.z + pa.z, nx, ny, nz, -f.x, -f.y, -f.z
end

function BLOOD.hit(B, x, y, z, h, kind)
  local rnd = math.random
  z = z or 0
  local px, py, pz, nx, ny, nz = BLOOD.ground(x, y, z)
  if kind == 'pool' then
    if px then
      local r, a = 1.1 + rnd() * .6, rnd() * 6.283
      BLOOD.lay(B, {kind = 'ground', shape = 'blood_splat', len = r, wid = r * (.75 + rnd() * .25), grow = S.now},
        px, py, pz, nx, ny, nz, math.cos(a), math.sin(a), 0)
    end
    return
  end
  local fx, fy
  if h and h.fx then fx, fy = h.fx, h.fy else local a = rnd() * 6.283; fx, fy = math.cos(a), math.sin(a) end
  -- a wall, pole or fence ahead within 4 m: a stain about chest height, and the sprays stop short of it
  local wx, wy, wz, wnx, wny, wnz, wd = BLOOD.wall(x, y, z + .8 + rnd() * .6, fx, fy, 4)
  B.walls = B.walls or {rays = 0, hits = 0}
  B.walls.rays, B.walls.hits = B.walls.rays + 1, B.walls.hits + (wx and 1 or 0)
  if wx then
    local r = .7 + rnd() * .4
    BLOOD.lay(B, {kind = 'wall', shape = rnd() < .5 and 'blood_splat' or 'blood_spray', len = r, wid = r * .8},
      wx, wy, wz, wnx, wny, wnz, fx, fy, -.3)
  end
  -- where it struck
  if px then
    local r, a = .7 + rnd() * .4, rnd() * 6.283
    BLOOD.lay(B, {kind = 'ground', shape = 'blood_splat', len = r, wid = r * (.8 + rnd() * .3)},
      px, py, pz, nx, ny, nz, math.cos(a), math.sin(a), 0)
  end
  -- thrown along the car's way: a spray or two further on
  for k = 1, 1 + math.floor(rnd() * 2) do
    local d, side = 1.2 + k * 1.4 + rnd() * 1.2, (rnd() - .5) * 1.2
    if wd then d = math.min(d, wd - .9) end
    px, py, pz, nx, ny, nz = nil, nil, nil, nil, nil, nil
    if d > .6 then px, py, pz, nx, ny, nz = BLOOD.ground(x + fx * d - fy * side, y + fy * d + fx * side, z) end
    if px then
      local l, a = 1.3 + rnd() * .9, (rnd() - .5) * .5
      BLOOD.lay(B, {kind = 'ground', shape = 'blood_spray', len = l, wid = l * .5}, px, py, pz, nx, ny, nz,
        fx * math.cos(a) - fy * math.sin(a), fy * math.cos(a) + fx * math.sin(a), 0)
    end
  end
  -- on the car
  local veh = h and h.id and getObjectByID(h.id)
  if not veh then return end
  local n = 0
  for i = 1, B.n do if B.list[i].vid == h.id then n = n + 1 end end
  if n >= BLOOD.carMax then return end
  local a, b, c = BLOOD.carAnchor(veh, h, x, y)
  if not a then return end
  local spray = rnd() < .5
  local l = spray and .7 + rnd() * .25 or .45 + rnd() * .2
  local s = {kind = 'car', shape = spray and 'blood_spray' or 'blood_splat', len = l, wid = spray and l * .5 or l * .85,
    vid = h.id, a = a, b = b, c = c}
  local qx, qy, qz, qnx, qny, qnz = BLOOD.onCar(s, veh)
  s.lift, s.skin = BLOOD.skin(h.id, qx, qy, qz, qnx, qny, qnz)
  BLOOD.lay(B, s, BLOOD.onCar(s, veh))
end

function M.walkBloodClear(wk)
  local B = wk and wk.blood
  if not B then return end
  for i = 1, B.n do
    local s = B.list[i]
    if s then BLOOD.drop(B, s); B.list[i] = nil end
  end
  B.n = 0
  dropGroup('E2R_blood')
  B.pool = {}
end

function M.walkBloodBind(wk)
  if not wk or not wk.api then return end
  local B = wk.blood
  if not B then
    B = {list = {}, pool = {}, n = 0}
    wk.blood = B
  end
  -- (x, y, z) where it struck, h the vehicle (pedhit's hitter) or nil; kind 'pool' under a body at rest
  function wk.api.splat(x, y, z, h, kind)
    local ok, err = pcall(BLOOD.hit, B, x, y, z, h, kind)
    if not ok then B.err = tostring(err) end
  end
end

-- a car put back by the game (its reset) is clean again
function M.onVehicleResetted(vid)
  local B = S.walk and S.walk.blood
  if not B or B.n == 0 then return end
  local keep, kn = {}, 0
  for i = 1, B.n do
    local s = B.list[i]
    if s.vid == vid then BLOOD.drop(B, s); B.resets = (B.resets or 0) + 1 else kn = kn + 1; keep[kn] = s end
  end
  B.list, B.n = keep, kn
end

function M.walkBloodStep(wk, px, py)
  local B = wk.blood
  if not B or B.n == 0 then return end
  local keep, kn = {}, 0
  for i = 1, B.n do
    local s = B.list[i]
    local live
    if s.kind == 'car' then
      local veh = S.now - s.at < BLOOD.carTtl and getObjectByID(s.vid)
      if veh then
        local ok, err = pcall(function() BLOOD.pose(s, BLOOD.onCar(s, veh)) end)
        if not ok then B.err = tostring(err) end
        live = ok
      end
    else
      live = S.now - s.at < BLOOD.ttl and (not px or (s.x - px) ^ 2 + (s.y - py) ^ 2 < BLOOD.farR * BLOOD.farR)
      if live and s.grow then
        -- a pool spreads over 8 s
        local k = math.min(1, .3 + (S.now - s.grow) / 8 * .7)
        pcall(function() s.obj:setScale(vec3(s.len * k, s.wid * k, 1)) end)
        if k >= 1 then s.grow = nil end
      end
    end
    if live then
      kn = kn + 1
      keep[kn] = s
    else
      BLOOD.drop(B, s)
    end
  end
  B.list, B.n = keep, kn
end

-- development (earthng/probe/blood_hit.lua): a splat as pedhit makes one, and the stains as they lie
function M.bloodSplat(x, y, z, h, kind)
  local wk = S.walk
  if not (wk and wk.api and wk.api.splat) then return false end
  wk.api.splat(x, y, z, h, kind)
  return true
end
function M.bloodState()
  local B = S.walk and S.walk.blood
  local r = {n = B and B.n or 0, err = B and B.err, resets = B and B.resets, walls = B and B.walls, kinds = {}, list = {}}
  for i = 1, r.n do
    local s = B.list[i]
    r.kinds[s.kind] = (r.kinds[s.kind] or 0) + 1
    local p = s.obj and s.obj:getPosition()
    r.list[i] = {kind = s.kind, shape = s.shape, len = s.len, x = p and p.x, y = p and p.y, z = p and p.z,
      vid = s.vid, a = s.a, b = s.b, c = s.c, lift = s.lift, skin = s.skin}
  end
  return r
end

-- A new landing or a pack gone: the walkers and their shapes go at once; the count asked and the
-- body pool stay, and the walkers come back with the next drive (walkersStep).
function M.walkersPark()
  local ws, wk = M.walkSim, S.walk
  if not wk or wk.parked then return end
  if wk.zeroAt then return M.walkersSet(0, true) end
  local n = wk.W.target
  if wk.V then ws.clear(wk.W, wk.V) end
  if wk.P then M.pedHit.parkAll(wk.P, wk.api) end
  M.walkBloodClear(wk)
  dropGroup('E2R_walkers')
  wk.W, wk.V, wk.parked, wk.syncAt, wk.syncCo = ws.new{seed = math.floor(S.now * 1000) % 100000 + 7}, nil, true, nil, nil
  ws.setTarget(wk.W, n)
end

-- The level ended: its objects and the pool's vehicles are gone already (nothing to delete); only
-- the count asked stays, for the next drive.
function M.walkersLost()
  local wk = S.walk
  S.walkPool = nil   -- its vehicles went with the level
  if not wk then return end
  local n = not wk.zeroAt and wk.W.target or 0
  S.walk = nil
  if n > 0 then M.walkersSet(n) end
end

function M.walkersStep()
  local ws, ph, wk = M.walkSim, M.pedHit, S.walk
  if wk.parked then M.walkersSet(wk.W.target) end
  if wk.zeroAt and S.now - wk.zeroAt > 2 then M.walkersSet(0, true) end
  wk = S.walk
  if not wk or wk.parked then return end
  local p = focus()
  if not p then return end
  local t = wk.timer
  t:stopAndReset()
  -- the sidewalks follow the graph (a tile came or went) in a coroutine, ~1.5 ms a frame: a whole
  -- landing's sync is ~20-30 ms of Lua, a tile's 4-5 (earthng/walkers_bench.py)
  if not wk.syncCo and wk.syncAt ~= S.navAt then
    wk.syncAt = S.navAt
    local W, nav, x, y = wk.W, S.nav, p.x, p.y
    wk.pause = wk.pause or function() if wk.timer:stop() > 1.5 then coroutine.yield() end end
    wk.syncCo = coroutine.create(function() ws.sync(W, nav, x, y, wk.pause) end)
  end
  if wk.syncCo then
    local ok, err = coroutine.resume(wk.syncCo)
    if not ok then log('E', logTag, 'walkers sync: ' .. tostring(err)) end
    if not ok or coroutine.status(wk.syncCo) == 'dead' then wk.syncCo = nil end
  end
  local syncMs = t:stopAndReset()
  -- grow the body pool on demand (fewer than 2 idle, or a hit found no body), one at a time, 2 s
  -- apart and only near a stop: a spawn is ~0.2 s of the frame, and two a frame at speed were ~4 s
  -- of 3 fps right after landing (all-08, 340 ms frames). Short of bodies, a struck walker is a
  -- ghost hit (pedhit.lua), never one walked through.
  local P = wk.P
  if #P.pool < P.size and S.now - (wk.fillAt or -1e9) > 2 then
    local idle = 0
    for _, e in ipairs(P.pool) do if e.state == 'idle' then idle = idle + 1 end end
    local veh = getPlayerVehicle(0)
    if (idle < 2 or P.stats.noBody > (wk.noBodySeen or 0)) and (not veh or veh:getVelocity():length() < 8) then
      ph.prewarmOne(P, wk.api, p.x, p.y)
      wk.fillAt, wk.noBodySeen = S.now, P.stats.noBody
    end
  end
  -- the vehicles that can hit (every active one with physics but the pool's own bodies); walkers
  -- wait at the kerb for them and for the flow's cars (as drawn)
  local hitters = ph.gameHitters(wk.H, wk.P, wk.boxes, p.x, p.y)
  ws.step(wk.W, S.dtSim or S.dt or 1 / 60, p.x, p.y, hitters, S.flow and S.flow.F.cars)
  ph.step(wk.P, ws, wk.W, hitters, S.now, wk.api, p.x, p.y)
  if wk.blood then M.walkBloodStep(wk, p.x, p.y) end
  wk.simMs = t:stopAndReset()
  wk.moved = ws.draw(wk.W, wk.V, p.x, p.y, wk.ground)
  wk.drawMs = t:stopAndReset()
  local r = result.walk or {}
  result.walk = r
  r.asked, r.walkers, r.room = ws.counts(wk.W)
  r.segs, r.simMs, r.drawMs, r.syncMs = #wk.W.list, wk.simMs, wk.drawMs, syncMs
  r.simMax, r.drawMax = math.max(r.simMax or 0, wk.simMs), math.max(r.drawMax or 0, wk.drawMs)
  r.syncMax = math.max(r.syncMax or 0, syncMs)
  -- shapes in the scene, walkers posed (within 60 m) and with one shape (to 200 m)
  r.objects, r.posed, r.drawn, r.placed = wk.V.objects, wk.V.nearUsed, wk.V.farUsed, wk.moved
  r.stats, r.hit, r.bodies, r.pool, r.spawnMs = wk.W.stats, wk.P.stats, ph.activeCount(wk.P), #wk.P.pool, wk.spawnMs
  r.hitLog = wk.P.log
  r.blood = wk.blood and wk.blood.n or 0
end

-- The widget's pedestrians and knockable-props rows, through the registry (options.lua) like the
-- game's UI app, so both show the same. The ImGui pointers are made once and refilled from the
-- registry each frame; the note's string is rebuilt only when its counts change (noteText).
function M.drawPeopleRows()
  local o = M.options
  if not (o and o.has('walkers')) then return end   -- a test stubs require
  local P = S.peoplePtrs
  if not P then
    P = {on = im.BoolPtr(false), n = im.IntPtr(0), knock = im.BoolPtr(true), muted = im.ImVec4(.65, .68, .72, 1)}
    S.peoplePtrs = P
  end
  P.on[0] = o.get('walkersOn') and true or false
  if im.Checkbox(L('Пішоходи', 'Pedestrians') .. '##walkOn', P.on) then o.set('walkersOn', P.on[0] and true or false, 'widget') end
  im.SameLine()
  P.n[0] = o.get('walkers') or 0
  if im.SetNextItemWidth then im.SetNextItemWidth(-1) end
  local ok, changed = pcall(im.SliderInt, '##walkN', P.n, 0, 1000, '%d')
  if ok then
    if changed then o.set('walkers', P.n[0], 'widget') end   -- live: walkersSet is cheap
  else
    if im.Button('-##walkN') then o.set('walkers', (o.get('walkers') or 0) - 50, 'widget') end
    im.SameLine()
    if im.Button('+##walkN') then o.set('walkers', (o.get('walkers') or 0) + 50, 'widget') end
    im.SameLine()
    im.Text(tostring(o.get('walkers') or 0))
  end
  local note = o.noteText('walkers', lang)
  if note then im.TextColored(P.muted, note) end
  if o.has('knock') then
    P.knock[0] = o.get('knock') and true or false
    if im.Checkbox(L('Збивані об\'єкти', 'Knockable props') .. '##knock', P.knock) then
      o.set('knock', P.knock[0] and true or false, 'widget')
    end
    if im.IsItemHovered() then
      im.SetTooltip(L('Для щойно завантажених околиць', 'For newly loaded surroundings'))
    end
  end
end

local function drawTraffic()
  local amount = trafficRunning() and (S.trafficAmount or -1) or 0
  local kind = S.trafficKind or 'simple'
  im.Text(L('Трафік:', 'Traffic:'))
  local spacing = im.GetStyle().ItemSpacing.x
  local width = math.floor((im.GetContentRegionAvailWidth() - (#TRAFFIC_KINDS - 1) * spacing) / #TRAFFIC_KINDS)
  for k, a in ipairs(TRAFFIC_KINDS) do
    if k > 1 then im.SameLine() end
    local active = kind == a[1]
    if active then
      im.PushStyleColor2(im.Col_Button, im.ImVec4(0.15, 0.55, 0.3, 1))
      im.PushStyleColor2(im.Col_ButtonHovered, im.ImVec4(0.2, 0.65, 0.35, 1))
    end
    -- a new kind respawns the running traffic with it
    if im.Button(L(a[2], a[3]) .. '##trafficKind_' .. a[1], im.ImVec2(width, 0)) and not active then
      S.trafficKind = a[1]
      if amount > 0 then setTraffic(amount, a[1]) end
    end
    if active then im.PopStyleColor(2) end
  end
  width = math.floor((im.GetContentRegionAvailWidth() - (#TRAFFIC_KINDS.amounts - 1) * spacing) / #TRAFFIC_KINDS.amounts)
  for k, a in ipairs(TRAFFIC_KINDS.amounts) do
    if k > 1 then im.SameLine() end
    local active = amount == a[1]
    if active then
      im.PushStyleColor2(im.Col_Button, im.ImVec4(0.15, 0.55, 0.3, 1))
      im.PushStyleColor2(im.Col_ButtonHovered, im.ImVec4(0.2, 0.65, 0.35, 1))
    end
    if im.Button(L(a[2], a[3]) .. '##traffic_' .. a[1], im.ImVec2(width, 0)) and not active then setTraffic(a[1], kind) end
    if active then im.PopStyleColor(2) end
  end
  im.Text(L('Потік (без фізики):', 'Flow (no physics):'))
  local flowN = S.flow and S.flow.F.target or 0
  width = math.floor((im.GetContentRegionAvailWidth() - (#TRAFFIC_KINDS.flow - 1) * spacing) / #TRAFFIC_KINDS.flow)
  for k, a in ipairs(TRAFFIC_KINDS.flow) do
    if k > 1 then im.SameLine() end
    local active = flowN == a[1]
    if active then
      im.PushStyleColor2(im.Col_Button, im.ImVec4(0.15, 0.55, 0.3, 1))
      im.PushStyleColor2(im.Col_ButtonHovered, im.ImVec4(0.2, 0.65, 0.35, 1))
    end
    if im.Button(L(a[2], a[3]) .. '##flow_' .. a[1], im.ImVec2(width, 0)) and not active then M.flowSet(a[1]) end
    if active then im.PopStyleColor(2) end
  end
  im.Text(L('Справжні машини біля гравця:', 'Real cars round the player:'))
  local realN = S.flowReal or M.handoffSim.SIZE
  width = math.floor((im.GetContentRegionAvailWidth() - (#TRAFFIC_KINDS.real - 1) * spacing) / #TRAFFIC_KINDS.real)
  for k, a in ipairs(TRAFFIC_KINDS.real) do
    if k > 1 then im.SameLine() end
    local active = realN == a[1]
    if active then
      im.PushStyleColor2(im.Col_Button, im.ImVec4(0.15, 0.55, 0.3, 1))
      im.PushStyleColor2(im.Col_ButtonHovered, im.ImVec4(0.2, 0.65, 0.35, 1))
    end
    if im.Button(L(a[2], a[3]) .. '##flowReal_' .. a[1], im.ImVec2(width, 0)) and not active then M.flowReal(a[1]) end
    if active then im.PopStyleColor(2) end
  end
  M.drawPeopleRows()   -- pedestrians (on/off and a 0..1000 slider) and knockable props
  im.Text(L('Припарковані машини:', 'Parked cars:'))
  local parked = S.parkedPick or (S.tune and S.tune.parkedCars) or 0
  width = math.floor((im.GetContentRegionAvailWidth() - 2 * spacing) / 3)
  for k, a in ipairs(parking.AMOUNTS) do
    if k > 1 then im.SameLine() end
    local active = parked == a[1]
    if active then
      im.PushStyleColor2(im.Col_Button, im.ImVec4(0.15, 0.55, 0.3, 1))
      im.PushStyleColor2(im.Col_ButtonHovered, im.ImVec4(0.2, 0.65, 0.35, 1))
    end
    if im.Button(L(a[2], a[3]) .. '##parked_' .. a[1], im.ImVec2(width, 0)) and not active then S.parkedPick = a[1] end
    if active then im.PopStyleColor(2) end
  end
  if S.park and (S.park.spawned or 0) > 0 then
    im.Text(string.format(L('На стоянках: %d машин, місць %d', 'In the lots: %d cars, %d spots'),
      gameplay_parking and gameplay_parking.getParkedCarsAmount() or 0, S.park.count))
  end
end

local function updateTiles()
  local st = S.status and S.status.stream
  if not (S.stream and st and st.region == S.stream.region) then return end
  local p, v = focus()
  if not p then return end
  local fast = st.generator ~= nil
  local loadR = fast and (st.loadRadius or 1000) or LOAD_R
  -- the descent needs every tile within 500 m of the spawn (tick): a corner tile's centre is up to
  -- ~1060 m away, beyond the 1 km radius, and was never loaded (native-hops-02, landing hung)
  if S.state ~= 'driving' then loadR = math.max(loadR, 500 * math.sqrt(2) + S.stream.tile * 0.71) end
  local unloadR = fast and loadR + 350 or UNLOAD_R
  -- fast, at speed: tiles well behind the car are neither kept nor loaded (the static collision
  -- costs ~7.5 ms per MB of loaded world at every rebuild); a U-turn loads them back from disk.
  -- keepBack matches native.lua AHEAD (backM / backS + half tile): without the half-tile pad,
  -- past the mid-tile the centre sat "behind" and the tile under the car unloaded every few
  -- hundred metres (reload flicker after the streaming-zone change).
  local speed = v:length()
  local tileSize = S.stream.tile or 500
  local keepBack = math.max(200, speed * 3.5) + tileSize * 0.5
  local underI, underJ = math.floor(p.x / tileSize), math.floor(p.y / tileSize)
  local function behind(cx, cy, d, i, j)
    if not fast or speed < 15 then return false end
    -- the tile the car stands on (and anything whose centre is still inside a half-tile) stays
    if (i and i == underI and j == underJ) or d <= tileSize * 0.71 then return false end
    return ((cx - p.x) * v.x + (cy - p.y) * v.y) < 0 and d > keepBack
  end
  -- native: a near tile's wanted value is the seconds until the car reaches it (native.lua AHEAD;
  -- far tiles and the horizon are 1e6 and up). At speed the near set runs on along the heading
  -- past loadR: such a road is kept and started like one inside it.
  local wantedNow = NATIVE and st.wanted or {}
  local function dueNear(key)
    local due = wantedNow[key]
    return due and due < 1e6 and due or nil
  end
  local graveBacklog = S.graves and #S.graves or 0
  -- unload far tiles (their queued items are skipped)
  for key, tile in pairs(S.tiles) do
    local cx, cy = tileCentre(tile.i, tile.j)
    local d = math.sqrt((cx - p.x) ^ 2 + (cy - p.y) ^ 2)
    local isBehind = behind(cx, cy, d, tile.i, tile.j)
    -- A free camera far from the car owns the bubble; the tiles under the parked car used to
    -- unload with the rest and it fell through the world (night-fence-02, z 179 -> 0.2).
    -- dueNear must not hold a behind tile: native drops it from wanted, but a stale wanted bit
    -- or a keep-bubble edge used to block unload while the far ring rebuilt the same key.
    local held = (tile.i == underI and tile.j == underJ)
      or (S.heldCar and (cx - S.heldCar[1]) ^ 2 + (cy - S.heldCar[2]) ^ 2 <= 600 * 600)
      or (dueNear(key) and not isBehind)
    if not held and (d > unloadR or isBehind) then
      retireForest(tile)
      -- bury roads too: dropGroup on a dense tile hitching the frame; digGraves drains them
      buryGroup('E2RT_' .. key); buryGroup('E2RD_' .. key); buryGroup('E2RS_' .. key)
      if M.signals then M.signals.dropTile(key) end
      if tile.flowLights and #tile.flowLights > 0 then S.flowLightVersion = (S.flowLightVersion or 0) + 1 end
      S.tiles[key] = nil
      S.navDirty = true
      if NATIVE then native.unload(key) end
      tile.dropped = true
      S.collisionDirty = true
      -- fast: a far tile's stale collision is harmless until the next rebuild; forcing one per
      -- unload (and per scene piece) made rebuilds back to back at 300 km/h
      if not (S.stream and S.stream.generator) then S.removedCollision = true end
      result.unloaded = (result.unloaded or 0) + 1
    end
  end
  -- start the nearest ready tile in range (one per call keeps the material loads apart);
  -- the look-ahead point counts the speed, so the tile ahead comes before the one behind.
  -- Natively the first is the one the car reaches first (its wanted seconds), and a road due
  -- within LIMIT.roadAhead s starts however long the queue of scenes is.
  local ax, ay = p.x + v.x * 3, p.y + v.y * 3
  local best, bestD, bestRank
  for key, n in pairs(st.ready or {}) do
    if not S.tiles[key] then
      local i, j = key:match('^(-?%d+)_(-?%d+)$')
      i, j = tonumber(i), tonumber(j)
      local cx, cy = tileCentre(i, j)
      local dp = math.sqrt((cx - p.x) ^ 2 + (cy - p.y) ^ 2)
      local d = math.min(dp, math.sqrt((cx - ax) ^ 2 + (cy - ay) ^ 2))
      local due = dueNear(key)
      local rank = due or d
      -- at speed the native wanted set is the corridor + keep bubble; a ready tile still
      -- inside the old load disk but outside that set must not start (side/back clutter)
      local inRange = due or (d <= loadR and (not NATIVE or speed < 15))
      if inRange and not behind(cx, cy, dp, i, j) and (not bestRank or rank < bestRank) then
        best, bestD, bestRank = {key, i, j}, d, rank
      end
    end
  end
  local soon = best and dueNear(best[1])
  -- a deep unload backlog digs first; only an urgent road ahead still starts
  local allowLoad = graveBacklog < 16 or (soon and soon < LIMIT.roadUrgent)
  if allowLoad and best and (#S.queue < 400 or (soon and soon < LIMIT.roadAhead)) then
    startTile(best[1], best[2], best[3])
  end
  -- the nearest scene (look-ahead point too) whose road is in: it used to wait for every road tile
  -- in loadR and then took any one, so buildings next to the car came after roads 1 km away
  if allowLoad and fast and #S.queue < 300 and st.scenes then
    local bestS, bestSD
    for key, tile in pairs(S.tiles) do
      if tile.roadComplete and not tile.sceneStarted and st.scenes[key] then
        local cx, cy = tileCentre(tile.i, tile.j)
        local d = math.min(math.sqrt((cx - p.x) ^ 2 + (cy - p.y) ^ 2), math.sqrt((cx - ax) ^ 2 + (cy - ay) ^ 2))
        if not bestSD or d < bestSD then bestS, bestSD = {key, tile}, d end
      end
    end
    if bestS and (not best or bestSD < bestD) then startScene(bestS[1], bestS[2]) end
  end
  if NATIVE and st.grass then
    for key, tile in pairs(S.tiles) do
      if st.grass[key] and tile.sceneStarted and not tile.grassStarted then startGrass(key, tile); break end
    end
  end
  if fast then
    -- the far city (earthng/fast_far.py): a tile without its own scene, within farRadius, gets
    -- its far layer; the far layer goes when the scene is in or the car is far away
    local farR = st.farRadius or 3000
    -- Companion far tiles are decoration and stay gated above 90 km/h (their churn at
    -- 300 km/h doubled be:reloadCollision). Native far ground is the mountain ring, so it
    -- keeps loading; only its buildings and trees wait for a slower speed.
    local farLoadR = (not NATIVE and speed > (st.farFast or 25)) and 0 or farR
    for key, far in pairs(S.far) do
      local cx, cy = tileCentre(far.i, far.j)
      local d = math.sqrt((cx - p.x) ^ 2 + (cy - p.y) ^ 2)
      local near = S.tiles[key]
      -- The far canopy used to stay up until the near scene finished, so the same
      -- trees were drawn twice and z-fought for the whole spawn. Drop the far
      -- forest as soon as the near scene starts; its ground mesh stays until the
      -- near ground has replaced it.
      if near and near.sceneStarted then retireForest(far); far.vegetationDropped = true end
      if d > farR + 500 or (near and near.sceneComplete) or behind(cx, cy, d) then
        retireForest(far)
        buryGroup('E2RF_' .. key)
        far.dropped = true
        S.far[key] = nil
        if NATIVE then native.unload(key, 'far') end
      end
    end
    for key, token in pairs(st.far or {}) do
      local spawned = S.far[key]
      if spawned and type(token) == 'number' and spawned.serial ~= token then
        retireForest(spawned)
        buryGroup('E2RF_' .. key)
        spawned.dropped = true
        S.far[key] = nil
      end
    end
    if allowLoad and graveBacklog < 8 and #S.queue < 60 then
      local bestF, bestFD
      for key in pairs(st.far or {}) do
        local near = S.tiles[key]
        if not S.far[key] and not (near and (near.sceneStarted or near.sceneComplete)) then
          local i, j = key:match('^(-?%d+)_(-?%d+)$')
          i, j = tonumber(i), tonumber(j)
          local cx, cy = tileCentre(i, j)
          local d = math.sqrt((cx - p.x) ^ 2 + (cy - p.y) ^ 2)
          if d <= farLoadR and not behind(cx, cy, d) and (not bestFD or d < bestFD) then
            bestF, bestFD = {key, i, j}, d
          end
        end
      end
      if bestF then
        local key, i, j = bestF[1], bestF[2], bestF[3]
        local ok, manifest
        if NATIVE then ok, manifest = true, native.manifest(key, 'far')
        else ok, manifest = pcall(jsonReadFile, tilePath(key, 'far')) end
        if ok and type(manifest) == 'table' and manifest.source == S.stream.region then
          loadNewMaterials(manifest.materials, manifest.stockMaterials)
          local far = {i = i, j = j, left = #manifest.items, group = tileGroup('E2RF_' .. key, true), far = true,
            serial = type(st.far[key]) == 'number' and st.far[key] or 1}
          S.far[key] = far
          far.left = queueItems(manifest.items, far, key, 'far')
          if NATIVE and far.left == 0 then native.release(key, 'far') end
        end
      end
    end
    -- DEM horizon past the far ring. Its own group stays out of MissionGroup, so it never
    -- joins the static collision. A coarser ring is not scheduled until the 5 km one is checked.
    local horizonR = (NATIVE and st.horizonDem) and (st.horizonRadius or 0) or 0
    VISTA.apply(NATIVE and st.vista or nil)
    -- the plane follows the lowest ground found (down only), its climate, and a camera gone far
    local want, at = NATIVE and st.vista and st.vistaLow, S.vistaPlaneAt
    if want then
      if not at or want < at[1] - 30 or st.vistaGround ~= at[2] or (p.x - at[3]) ^ 2 + (p.y - at[4]) ^ 2 > 15000 ^ 2 then
        pcall(VISTA.plane, math.min(want, at and at[1] or want), st.vistaGround or 'forest', p.x, p.y)
      end
    elseif at then
      pcall(VISTA.plane, nil)
    end
    S.horizon = S.horizon or {}
    if horizonR > 0 then
      for key, spawned in pairs(S.horizon) do
        local info = st.horizon and st.horizon[key]
        local cx = info and info.x or spawned.x or p.x
        local cy = info and info.y or spawned.y or p.y
        -- DEM horizon stays a full ring (native wants it all round); behind culling is near/far
        if not info or math.sqrt((cx - p.x) ^ 2 + (cy - p.y) ^ 2) > horizonR + 800 then
          buryGroup(spawned.groupName or ('E2RH_' .. key:gsub('[^%w_]', '_')))
          spawned.dropped = true
          S.horizon[key] = nil
          if NATIVE then native.unload(key, 'horizon') end
        end
      end
      if allowLoad and graveBacklog < 8 and #S.queue < 40 then
        local bestH, bestHD
        for key, info in pairs(st.horizon or {}) do
          if not S.horizon[key] and type(info) == 'table' and info.x and info.y then
            local d = math.sqrt((info.x - p.x) ^ 2 + (info.y - p.y) ^ 2)
            if d <= horizonR + 250 and (not bestHD or d < bestHD) then bestH, bestHD = key, d end
          end
        end
        if bestH then
          local info = st.horizon[bestH]
          local manifest = native.manifest(bestH, 'horizon')
          if type(manifest) == 'table' and manifest.source == S.stream.region then
            loadNewMaterials(manifest.materials, manifest.stockMaterials)
            local groupName = 'E2RH_' .. bestH:gsub('[^%w_]', '_')
            local horizon = {left = #manifest.items, group = tileGroup(groupName, true), horizon = true,
              serial = info.serial, x = info.x, y = info.y, groupName = groupName}
            S.horizon[bestH] = horizon
            if horizon.left == 0 then native.release(bestH, 'horizon')
            else
              for _, it in ipairs(manifest.items) do
                table.insert(S.queue, {tile = horizon, key = bestH, item = it, horizon = true})
              end
            end
          end
        end
      end
    end
    local horizonCount = 0
    for _ in pairs(S.horizon) do horizonCount = horizonCount + 1 end
    result.horizonResident = horizonCount
    -- the far view past the DEM horizon: its level 0 starts where the horizon (or the far ring)
    -- is sure to have ground round the focus (500 m tiles by their centres: 354 m short)
    if M.far then
      local holeR = (horizonR > 0 and horizonR or (st.farRadius or 3000)) - 354
      local on = M.farEnabled ~= false
      native.farActive = on
      local okFar, errFar = pcall(M.far.update, p, native.farSource(), holeR, function(id, triangles)
        S.coll = S.coll or collision.new()
        M.farOwner = M.farOwner or {horizon = true}
        S.coll:track(M.farOwner, id, true, triangles)
      end, on)
      if not okFar then result.farError = tostring(errFar) end
      result.far = M.far.status()
    end
    -- Reprioritize pending work when direction changes. Ground meshes of every
    -- tile come before any plant: a nearer tile's crowns used to sit ahead of
    -- the next tile's road and the bubble painted at the forest cap.
    -- Among meshes, roads and scenes go by the car's arrival (wanted, s), a
    -- scene LIMIT.sceneLag s after its road: the buildings by the car come before
    -- the roads of a tile a kilometre ahead.
    local wanted = st.wanted or {}
    local function rank(job) return job.horizon and 2 or (job.far and 1 or 0) end
    local function due(job) return (wanted[job.key] or 1e6) + (job.scene and LIMIT.sceneLag or 0) + (job.grass and 3 * LIMIT.sceneLag or 0) end
    -- Ground, then grass and rocks, then trees. A tile of 1800 crowns used to
    -- fill the frame budget before a single tuft or stone was spawned.
    local function decorRank(job)
      local it = job.item
      if it and it.kind == 'proc' then return 0 end
      local name = it and it.name or ''
      if name:find('grass', 1, true) or name:find('rock', 1, true) then return 1 end
      return 2
    end
    table.sort(S.queue, function(a, b)
      local dra, drb = decorRank(a), decorRank(b)
      local pa, pb = dra == 0, drb == 0
      if pa ~= pb then return pa end
      local ra, rb = rank(a), rank(b)
      if ra ~= rb then return ra < rb end
      local da, db = due(a), due(b)
      if da ~= db then return da < db end
      if dra ~= drb then return dra < drb end
      return (a.scene and 1 or 0) < (b.scene and 1 or 0)
    end)
  end
end

local function stepQueue(burst)
  local frame = hptimer()
  local worked = false
  -- Retires queued by updateTiles this frame start before new crowns are added.
  -- test.genBudget (showcase stills): frame time does not matter, the place must finish loading
  -- A road due within LIMIT.roadUrgent s at the head of the queue (updateTiles sorts it) gets
  -- LIMIT.roadFloorMs however much the generator took: at 0.5 ms it spawned a piece a frame.
  local head, wanted = S.queue[1], S.status and S.status.stream and S.status.stream.wanted
  local urgent = NATIVE and head and not (head.scene or head.grass or head.far or head.horizon) and wanted
    and (wanted[head.key] or 1e6) < LIMIT.roadUrgent
  local budget = test and test.genBudget or (S.state == 'spawning' and (S.landOwed == false and LIMIT.loadQueueLastMs or LIMIT.loadQueueMs))
    or burst or math.max(urgent and LIMIT.roadFloorMs or .5, BUDGET_MS - (S.nativeMs or 0))
  local function over() return frame:stop() >= budget end
  local function pause() if over() then coroutine.yield() end end
  if S.co and S.job and S.job.tile.dropped then S.co, S.job = nil, nil end
  repeat
    if not S.co then
      local job = table.remove(S.queue, 1)
      while job and job.tile.dropped do job = table.remove(S.queue, 1) end
      if not job then break end
      if job.item.kind == 'proc' and pairsLeft() <= 0 then table.insert(S.queue, 1, job); break end
      S.job = job
      local group = ((job.far or job.horizon) and job.tile.group) or (job.item.decor and job.tile.decor)
        or (job.scene and job.tile.sceneGroup) or job.tile.group
      local layer = not (job.far or job.horizon) and ((job.scene or job.grass) and 'scene' or 'road') or nil
      S.co = coroutine.create(function(p) spawnItem(job.item, group, p, job.tile, layer) end)
    end
    -- a resume far over the budget: is it the collector (Lua heap shrinks inside it)?
    local kb0, t0 = collectgarbage('count'), hptimer()
    local ok, err = coroutine.resume(S.co, pause)
    worked = true
    local resumeMs = t0:stop()
    if resumeMs > 30 then
      result.slowResumes = result.slowResumes or {}
      if #result.slowResumes < 40 then
        table.insert(result.slowResumes, {math.floor(S.now * 10) / 10, math.floor(resumeMs), math.floor(kb0),
                                          math.floor(collectgarbage('count')), S.job.item.name})
      end
    end
    if not ok then
      log('E', logTag, tostring(err))
      result.errors = (result.errors or 0) + 1
      if not S.job.far and not S.job.horizon then S.job.tile.failed = true end
    end
    -- createMesh has copied the source arrays into the engine. Retaining every
    -- vertex table in Lua made later garbage collections pause driving frames.
    if NATIVE and ok and coroutine.status(S.co) == 'dead' then S.job.item.meshes = nil end
    if coroutine.status(S.co) == 'dead' and (S.job.far or S.job.horizon) then
      S.co = nil
      S.job.tile.left = S.job.tile.left - 1
      if NATIVE and S.job.tile.left == 0 then native.release(S.job.key, S.job.horizon and 'horizon' or 'far') end
    elseif coroutine.status(S.co) == 'dead' then
      S.co = nil
      local tile = S.job.tile
      tile.left = tile.left - 1
      if S.job.grass then
        tile.grassLeft = tile.grassLeft - 1
        if NATIVE and tile.grassLeft == 0 and not tile.dropped then native.release(S.job.key, 'grass') end
      elseif not S.job.scene then tile.roadLeft = tile.roadLeft - 1 end
      if S.job.scene then
        tile.sceneLeft = tile.sceneLeft - 1
        tile.sceneComplete = tile.sceneLeft == 0 and not tile.failed
        if NATIVE and tile.sceneComplete then native.release(S.job.key, 'scene') end
      end
      if tile.roadLeft <= 0 and not tile.dropped and not tile.failed and not tile.roadComplete then
        tile.roadComplete = true
        if NATIVE then native.release(S.job.key, 'road') end
        tile.state = 'loaded'
        tile.loadSeconds = S.now - tile.startedAt
        S.collisionDirty = true
        result.tilesLoaded = (result.tilesLoaded or 0) + 1
        S.deliveryTimes = S.deliveryTimes or {}
        table.insert(S.deliveryTimes, tile.loadSeconds)
        if #S.deliveryTimes > 128 then table.remove(S.deliveryTimes, 1) end
        local sorted = {}
        for k, value in ipairs(S.deliveryTimes) do sorted[k] = value end
        table.sort(sorted)
        S.deliveryP99 = sorted[math.ceil(#sorted * .99)]
      end
      if S.job.scene and not tile.dropped and not S.job.item.decor then S.collisionDirty = true; tile.sceneDirty = true end
    end
  until over()
  return worked
end

-- be:reloadCollision rebuilds the static collision of the whole loaded world; the call returns in
-- ~0.2 s but the frames after it stall for seconds (route-04), more with more tiles loaded. So it
-- runs only when a loaded tile without collision is near the car (COLLISION_R); far tiles get
-- theirs with the next rebuild. tileReady() (autopilot, touchdown) needs the collision.
local COLLISION_R = 450
-- be:reloadCollision rebuilds the static collision of every ProceduralMesh in the scene,
-- in the MissionGroup or not (night-probe-11): 66 ms in Yaremche, 100-130 ms in central
-- Kyiv, +20-30 ms of physics the next frame. A rebuild is asked for only when a tile the
-- car can reach soon lacks collision; the radius grows with speed.
function LIMIT.collisionRadius(v)
  local speed = v and v:length() or 0
  return math.max(650, math.min(1600, speed * ((S.deliveryP99 or 2) + 10) + 400))
end

-- true when this open gate may insert into the scene. A road due inside roadUrgent always
-- may. Everything else waits a second since the last packet, and an early slot is yielded
-- so the gate's next change is still two calm frames away.
function LIMIT.allowSpawn(gate)
  if not gate then return true end
  local head = S.queue and S.queue[1]
  local wanted = S.status and S.status.stream and S.status.stream.wanted
  local urgent = head and not (head.scene or head.grass or head.far or head.horizon)
    and wanted and (wanted[head.key] or 1e6) < LIMIT.roadUrgent
  S.urgentRoad = urgent and true or false
  if S.urgentRoad or S.now - (S.burstAt or -1e9) >= 1 then return true end
  gate:yield()
  return false
end

-- Natively a rebuild keeps only the tiles round the car, a parked car and the traffic
-- (collision.lua: central Kyiv 133 + 34 ms -> ~40 + 12 ms). Collision has to stay ahead of
-- the next rebuild, not of the generator: the car's reach grows with speed, and the tiles it
-- leaves out are rebuilt with collision once one of them comes within `want`.
local function collisionPoints(p, v)
  local points = {}
  if not p then return points end
  local speed = v and v:length() or 0
  local want = math.min(1600, math.max(LIMIT.collisionWant, speed * LIMIT.collisionLead + 100))
  -- a scene spawned since the last rebuild asks for one only nearer: at 250 km/h a road, then its
  -- scene, then the rows beside it each asked within 6 s and the rebuilds came every 2 s
  local sceneWant = math.min(want, math.max(LIMIT.collisionWant, speed * LIMIT.collisionSceneLead + 100))
  -- the descent waits for collision on every tile within 500 m of the spawn (tick)
  if S.state ~= 'driving' then want, sceneWant = math.max(want, 750), math.max(want, 750) end
  local C = LIMIT.collisionScene
  if S.state == 'driving' and speed >= C.fast then
    -- At speed the buildings and fences of a tile join only round a point `ahead` s in front of
    -- the car (`want` s of the car's travel round it, kept `margin` m further), and the car's own
    -- tile and those within `side` m: Kyiv at 69 m/s kept 8-10 tiles' walls (150-270k triangles)
    -- in every rebuild, 2/3 of its 50-130 ms.
    -- The ground and roads the same way: within `roadSide` m of the car (kept to `roadKeep`) and
    -- `roadLane` m either side of its heading out to `want` (kept a margin further): the tiles
    -- behind and beside the car were half of the 55-100k road triangles a rebuild kept.
    local dx, dy = v.x / speed, v.y / speed
    local lead, around = speed * C.ahead, speed * C.want + 50
    points[1] = {p.x, p.y, C.roadSide, C.roadKeep, 0, C.side}
    points[2] = {p.x + dx * lead, p.y + dy * lead, -1, -1, around, around + C.margin}
    local reach = want + LIMIT.collisionMargin
    for k = 1, math.ceil(reach / C.roadStep) do
      local d = math.min(k * C.roadStep, reach)
      points[#points + 1] = {p.x + dx * d, p.y + dy * d, d <= want and C.roadLane or -1, C.roadLane + C.roadStep / 2, -1, -1}
    end
  else
    points[1] = {p.x, p.y, want, want + LIMIT.collisionMargin, sceneWant, want + LIMIT.collisionMargin}
  end
  local vw, vk = LIMIT.vehicleCollision[1], LIMIT.vehicleCollision[2]
  -- the player's car while the camera is elsewhere keeps its buildings; other cars only the ground
  if S.heldCar then points[#points + 1] = {S.heldCar[1], S.heldCar[2], vw, vk, vw, vk} end
  pcall(function()
    for k = 0, be:getObjectCount() - 1 do
      -- a car the parking pool has hidden needs no ground where it was left
      local obj = be:getObject(k)
      if obj:getActive() then
        -- parked cars and traffic: ground under them and a couple of seconds round them (a 300 m
        -- disc each kept 3x3 city tiles in every rebuild); the player's car is points[1]
        local q = obj:getPosition()
        points[#points + 1] = {q.x, q.y, LIMIT.otherCars[1], LIMIT.otherCars[2], -1, -1}
      end
    end
  end)
  return points
end

local function updateCollision()
  if not S.collisionDirty or S.now - S.collisionAt < COLLISION_EVERY then return end
  local p, v = focus()
  local fast = S.stream and S.stream.generator
  local radius = fast and LIMIT.collisionRadius(v) or COLLISION_R
  -- the descent waits for collision on every tile within 500 m of the spawn (tick): a corner
  -- tile's centre is up to ~1060 m away, and when such a tile came in last nothing else asked for
  -- a rebuild and the landing waited forever (native-perf-10)
  if S.state ~= 'driving' then radius = math.max(radius, 500 * math.sqrt(2) + S.stream.tile * 0.71) end
  local size = S.stream and S.stream.tile or 500
  local points = NATIVE and collisionPoints(p, v) or {}
  local near = S.removedCollision or false
  for _, tile in pairs(S.tiles) do
    local empty = tile.manifest.empty or itemCount(tile.manifest) == 0
    if NATIVE then
      if tile.state == 'loaded' and not tile.collided and not empty then
        if #points == 0 or collision.within(tile, points, size, 3) then near = true; break end
      elseif fast and tile.sceneIds and #tile.sceneIds > 0 and (tile.sceneDirty or not tile.sceneCollided) then
        if #points == 0 or collision.within(tile, points, size, 5) then near = true; break end
      end
    else
      if tile.state == 'loaded' and not tile.collided and not empty then
        local cx, cy = tileCentre(tile.i, tile.j)
        if not p or math.sqrt((cx - p.x) ^ 2 + (cy - p.y) ^ 2) <= radius then near = true; break end
      end
      -- buildings/ground next to the car get theirs soon; far scenery waits for a road rebuild
      if fast and tile.sceneDirty and p then
        local cx, cy = tileCentre(tile.i, tile.j)
        if math.sqrt((cx - p.x) ^ 2 + (cy - p.y) ^ 2) <= 400 then near = true; break end
      end
    end
  end
  if not near then return end
  local timer = hptimer()
  if NATIVE then
    S.coll = S.coll or collision.new()
    S.coll:rebuild(points, size, function(id) return scenetree.findObjectById(id) end,
      function() be:reloadCollision() end)
    result.collisionHidden = S.coll.lastHidden
  else
    be:reloadCollision()
  end
  local ms = timer:stop()
  if NATIVE and S.state == 'driving' then
    -- each rebuild while driving: s, ms, tiles kept, objects hidden, kilo-triangles kept by layer
    result.collisionLog = result.collisionLog or {}
    if #result.collisionLog < 80 then
      local k = {}
      for slot, n in pairs(S.coll.lastKept or {}) do k[slot] = math.floor(n / 1000) end
      table.insert(result.collisionLog, {math.floor(S.now * 10) / 10, math.floor(ms), S.coll.lastSolid, S.coll.lastHidden, k})
    end
  end
  result.reloadCollisionMs = math.max(result.reloadCollisionMs or 0, ms)
  result.collisionReloads = (result.collisionReloads or 0) + 1
  result.collisionMsSum = (result.collisionMsSum or 0) + ms
  local left = false
  for _, tile in pairs(S.tiles) do
    if tile.roadComplete and not tile.failed then
      tile.collided = not NATIVE or collision.solid(tile, points, size)
      left = left or not tile.collided
    end
    tile.sceneDirty = false
    tile.sceneCollided = not NATIVE or collision.sceneSolid(tile, points, size)
    left = left or (fast and tile.sceneIds and #tile.sceneIds > 0 and not tile.sceneCollided)
  end
  -- natively the tiles left out keep the check running as the car moves
  S.collisionDirty, S.collisionAt = NATIVE and left, S.now
  S.removedCollision = false
  return true
end

local function tileLoadedAt(x, y, offRoad)
  local i, j = tileOf(x, y)
  local t = S.tiles[i .. '_' .. j]
  -- an off-road landing (native.lua: no road within reach) stands on a tile of ground alone
  return t and not t.failed and t.roadComplete and t.collided and (offRoad or t.manifest.drivable ~= false)
end

-- --- texture packs (fast generator) -----------------------------------------------------------------
-- packs.json (earthng/fast_art.py): pack -> material -> stage-0 fields. A switch rewrites the
-- fields of the loaded materials in place; no tile is rebuilt or reloaded.
-- Button names come from here first (the labels in packs.json are escaped JSON strings); a pack
-- the table does not know shows its packs.json label or its id.
local PACK_LABELS_EN =
  {real = 'Realistic', toon = 'Cartoon', model = 'Mock-up', synth = 'Synthwave', pixel = 'Retro City',
   night = 'Night', rain = 'Rain', cyber = 'Cyberpunk', winter = 'Winter', autumn = 'Autumn'}
local PACK_LABELS_UK =
  {real = 'Реальний', toon = 'Мультяшний', model = 'Макет', synth = 'Синтвейв', pixel = 'Ретро-місто',
   night = 'Ніч', rain = 'Дощ', cyber = 'Кіберпанк', winter = 'Зима', autumn = 'Осінь'}
-- {id, packs.json label or nil}; the shown name is packLabel(), in the current language
local PACK_NAMES = {}
for _, name in ipairs({'real', 'toon', 'model', 'synth', 'pixel', 'night', 'rain', 'cyber', 'winter', 'autumn'}) do
  table.insert(PACK_NAMES, {name})
end
local function packLabel(p)
  return (lang == 'en' and PACK_LABELS_EN or PACK_LABELS_UK)[p[1]] or p[2] or p[1]
end

-- Street lights of a night pack: a pool of lights moved onto the lamps nearest the camera
-- (env.lights: colors, radius, brightness, height, count). Lamps are noted as tiles spawn them.
-- A lamp is a SpotLight aimed down, as the game's own Italy level lights its road lamps
-- (range 30, cone 100/140 degrees, brightness = lumens / 5000; 6000 lm is the pool's lamp).
-- A PointLight lit a pool under each lamp and left the road between two lamps dark.
-- env.lights.spot = false keeps the PointLights.
-- (LIMIT.lamp: world.lua's chunk is at Lua's 200 locals)
LIMIT.lamp = {range = 30, inner = 100, outer = 140, brightness = 6000 / 5000,
  -- the cone's axis is the light's local +Y: a quarter turn about x points it at the ground
  -- (used where quatFromDir is missing, see lightsStep)
  down = {-0.70710678, 0, 0, 0.70710678}}
local function dropLights()
  for _, l in ipairs(S.lightPool or {}) do l:delete() end
  S.lightPool, S.lightCfg, S.lightsAt, S.lightSpot = nil, nil, nil, nil
end

local function showLights(cfg)
  dropLights()
  if not cfg then return end
  S.lightCfg, S.lightPool = cfg, {}
  -- test.lights (stills): a bigger pool over a wider reach; a frame seen from above lit 1-2 lamps
  for k = 1, (test and test.lights) or cfg.count or 24 do
    local c = cfg.colors[(k - 1) % #cfg.colors + 1]
    local spot = cfg.spot ~= false
    local l = createObject(spot and 'SpotLight' or 'PointLight')
    if spot then
      l:setField('range', 0, tostring(cfg.range or LIMIT.lamp.range))
      l:setField('innerAngle', 0, tostring(LIMIT.lamp.inner))
      l:setField('outerAngle', 0, tostring(LIMIT.lamp.outer))
      l:setField('brightness', 0, tostring(cfg.spotBrightness or LIMIT.lamp.brightness))
    else
      l:setField('radius', 0, tostring(cfg.radius or 20))
      l:setField('brightness', 0, tostring(cfg.brightness or 2))
    end
    l:setField('color', 0, string.format('%f %f %f 1', c[1], c[2], c[3]))
    l:setField('castShadows', 0, '0')
    l:setField('flareType', 0, 'BNG_LightFlare_1')
    l:setField('flareScale', 0, tostring(cfg.flare or 0.6))
    l:registerObject('e2r_light_' .. k)
    l.canSave = false
    l:setPosition(vec3(0, 0, -10000))
    S.lightPool[k], S.lightSpot = l, spot
  end
  S.lightsAt = -1
end

local function lightsStep()
  local pool, cfg = S.lightPool, S.lightCfg
  if not pool or not S.lamps or S.now - (S.lightsAt or -1) < 0.4 then return end
  S.lightsAt = S.now
  local ok, cam = pcall(function() return core_camera.getPosition() end)
  if not ok or not cam then return end
  local near = {}
  for key, p in pairs(S.lamps) do
    local d = (p[1] - cam.x) ^ 2 + (p[2] - cam.y) ^ 2
    if d < (test and test.lights and 900 or 400) ^ 2 then near[#near + 1] = {d, p} elseif d > 2000 * 2000 then S.lamps[key] = nil end
  end
  table.sort(near, function(a, b) return a[1] < b[1] end)
  result.lampsNear, result.lightsPlaced = #near, math.min(#near, #pool)
  for k, l in ipairs(pool) do
    local n = near[k]
    local z = n and n[2][3] + (cfg.height or 7.3) or -10000
    local x, y = n and n[2][1] or 0, n and n[2][2] or 0
    if S.lightSpot then
      -- the cone's axis straight down, as the game's own lighting setup aims a SpotLight
      -- (quatFromDir of the direction it shines; up must not be parallel to it)
      if not S.lampRot then
        local ok, r = pcall(function() return quatFromDir(vec3(0, 0, -1), vec3(0, 1, 0)) end)
        local d = LIMIT.lamp.down
        S.lampRot = ok and r and {r.x, r.y, r.z, r.w} or d
      end
      local q = S.lampRot
      l:setPosRot(x, y, z, q[1], q[2], q[3], q[4])
    else
      l:setPosition(vec3(x, y, z))
    end
  end
end

-- Rain or snow round the camera (env.precip: the game's PrecipitationData rain_medium or Snow_menu)
local function showPrecip(cfg)
  local old = scenetree.findObject('e2r_precip')
  if old then old:delete() end
  S.precipPending = nil
  if not cfg then return end
  -- not before the car is on the road: the drops regenerate round a camera that jumps from 350 m
  -- down to the car, and that touch-down frame took 114 ms (vis-packs-drive-cyber)
  if S.state ~= 'driving' or S.now - (S.phaseAt or 0) < 1.5 then
    S.precipPending = cfg
    return
  end
  local obj = createObject('Precipitation')
  obj:setField('dataBlock', 0, cfg.dataBlock)
  for k, v in pairs({numDrops = cfg.numDrops or 3000, boxWidth = cfg.boxWidth or 60, boxHeight = cfg.boxHeight or 40,
                     dropSize = cfg.dropSize or 0.6, minSpeed = cfg.minSpeed or 1.5, maxSpeed = cfg.maxSpeed or 2,
                     splashSize = cfg.splashSize or 0.25, splashMS = 250, fadeDist = 4, fadeDistEnd = 60,
                     useTurbulence = cfg.turbulence and 1 or 0, useWind = 1, followCam = 1}) do
    obj:setField(k, 0, tostring(v))
  end
  obj:registerObject('e2r_precip')
  obj.canSave = false
end

-- The synthwave sun: one big textured quad that keeps its place on the horizon, as far from the
-- camera as the view distance allows (env.sun: azimuth, distance, size, height, material).
local function placeSun()
  local cfg, obj = S.sunCfg, S.sunObj
  if not (cfg and obj) then return end
  local ok, cam = pcall(function() return core_camera.getPosition() end)
  if not ok or not cam then return end
  local a = math.rad(cfg.azimuth)
  obj:setPosition(vec3(cam.x + math.sin(a) * cfg.distance, cam.y + math.cos(a) * cfg.distance, cam.z + cfg.height))
end

local function showSun(cfg)
  if S.sunObj then S.sunObj:delete(); S.sunObj = nil end
  S.sunCfg = cfg or nil
  if not cfg then return end
  local a, h = math.rad(cfg.azimuth), cfg.size / 2
  local rx, ry = math.cos(a), -math.sin(a)          -- right of the view toward the sun
  local nx, ny = -math.sin(a), -math.cos(a)         -- faces the camera
  local verts = {{x = -rx * h, y = -ry * h, z = -h}, {x = rx * h, y = ry * h, z = -h},
                 {x = rx * h, y = ry * h, z = h}, {x = -rx * h, y = -ry * h, z = h}}
  local obj = createObject('ProceduralMesh')
  obj:registerObject('e2r_synth_sun')
  obj.canSave = false
  obj:createMesh({{{verts = verts, normals = {{x = nx, y = ny, z = 0}},
                    uvs = {{u = 0, v = 1}, {u = 1, v = 1}, {u = 1, v = 0}, {u = 0, v = 0}},
                    faces = {{v = 0, n = 0, u = 0}, {v = 2, n = 0, u = 2}, {v = 1, n = 0, u = 1},
                             {v = 0, n = 0, u = 0}, {v = 3, n = 0, u = 3}, {v = 2, n = 0, u = 2}},
                    material = cfg.material}}})
  S.sunObj = obj
  placeSun()
end

local function restoreSkyDriver()
  local c = core_celestial
  if S.skyDriverOwned and c and c.getDriver and c.setDriver then
    -- Do not remove a driver installed by somebody else after ours.
    if c.getDriver() == S.skyDriver then c.setDriver(S.skyDriverOrig) end
  end
  S.skyDriverOwned, S.skyDriver, S.skyDriverOrig = nil, nil, nil
end

local function applySkyDriver(env)
  local c = core_celestial
  if not (c and c.getDriver and c.setDriver) then return end -- older BeamNG
  if not env.authoredSun then restoreSkyDriver(); return end
  if not S.skyDriverOwned then
    S.skyDriverOrig, S.skyDriverOwned = c.getDriver(), true
  end
  local sun = env.objects.sunsky
  local az, el = tonumber(sun.azimuth), tonumber(sun.elevation)
  local previous = S.skyDriverOrig
  S.skyDriver = function(ctx)
    if previous then previous(ctx) end
    ctx.sunAz, ctx.sunEl = az, el
  end
  c.setDriver(S.skyDriver)
end

local function applyExposure(env)
  local lx = scenetree.findObject('PostEffectLocalExposureObject')
  if not lx then
    S.exposurePending = env
    S.exposureRetryAt = S.now + 0.5
    return
  end
  S.exposurePending = nil
  if S.exposureOrig == nil then S.exposureOrig = {lx.autoExposure, lx.manualEV} end
  if env.exposure ~= nil and env.exposure ~= false then
    lx.autoExposure, lx.manualEV = false, env.exposure
  else
    lx.autoExposure, lx.manualEV = S.exposureOrig[1], S.exposureOrig[2]
  end
  result.exposure = {tostring(S.exposureOrig[1]), S.exposureOrig[2], tostring(lx.autoExposure), lx.manualEV}
end

local function applyEnvObjects(env)
  -- Capture the original exposure before sky postApply can change its state.
  applyExposure(env)
  S.envOrig = S.envOrig or {}
  for name, fields in pairs(S.envOrig) do
    if not (env.objects and env.objects[name]) then
      local obj = scenetree.findObject(name)
      if obj then
        for field, value in pairs(fields) do obj:setField(field, 0, value) end
        pcall(function() obj:postApply() end)
      end
    end
  end
  for objName, fields in pairs(env.objects or {}) do
    local obj = scenetree.findObject(objName)
    if obj then
      local orig = S.envOrig[objName] or {}
      S.envOrig[objName] = orig
      for field in pairs(fields) do
        if orig[field] == nil then orig[field] = obj:getField(field, 0) end
      end
      -- A partial preset (e.g. synth) must not inherit clouds or night fields.
      for field, value in pairs(orig) do
        if fields[field] == nil then obj:setField(field, 0, value) end
      end
      -- in a fixed order and twice: the night cubemap took (or not) depending on the order
      -- pairs() gave nightCubemap and useNightCubemap (vis-packs-10 dark, -11 dusk, same values)
      local keys = {}
      for field in pairs(fields) do table.insert(keys, field) end
      table.sort(keys)
      for _ = 1, 2 do
        for _, field in ipairs(keys) do obj:setField(field, 0, fields[field]) end
        pcall(function() obj:postApply() end)
      end
      result.envCheck = result.envCheck or {}
      for field in pairs(fields) do result.envCheck[objName .. '.' .. field] = tostring(obj:getField(field, 0)) end
    else
      result.envMissing = objName
    end
  end
  applyExposure(env)
  if test then
    result.environmentSamples = result.environmentSamples or {}
    local road = scenetree.findObject('e2rf_road')
    local sky = scenetree.findObject('sunsky')
    table.insert(result.environmentSamples, {at = S.now, pack = S.pack,
      exposure = result.exposure, elevation = sky and sky:getField('elevation', 0),
      roadEmission = road and road:getField('emissiveFactor', 0)})
  end
end

local function envAgainStep()
  if S.exposurePending and S.now >= S.exposureRetryAt then applyExposure(S.exposurePending) end
  local e = S.envAgain
  if not e or S.now < e.at[1] then return end
  table.remove(e.at, 1)
  -- the sun nudged first: a changed elevation makes the sky redo its lighting
  local sky = scenetree.findObject('sunsky')
  local el = e.env.objects and e.env.objects.sunsky and tonumber(e.env.objects.sunsky.elevation)
  if sky and el then
    sky:setField('elevation', 0, tostring(el - 0.3))
    pcall(function() sky:postApply() end)
  end
  applyEnvObjects(e.env)
  if #e.at == 0 then S.envAgain = nil end
end

local RELOADS_PER_FRAME = 2
local function reloadStep()
  local q = S.reloadQueue
  if not q or #q == 0 then return end
  local t = hptimer()
  for _ = 1, RELOADS_PER_FRAME do
    local mat = table.remove(q)
    if not mat then break end
    mat:reload()
  end
  local ms = t:stop()
  if ms > (result.reloadStepMs or 0) then result.reloadStepMs = ms end
end

local function applyPack(name)
  local pack = S.packs and S.packs[name]
  if not pack then return end
  -- the pack sets its own fog: the vista scales the new one (VISTA.apply)
  S.vistaApplied, S.vistaBase = nil, nil
  S.pack = name
  S.envAgain, S.exposurePending = nil, nil
  local timer = hptimer()
  -- a field the previous pack set and this one does not goes back to the material's own value
  -- (noted the first time a pack changed it): roughness of wet roads, hidden leaves, tints
  S.packOrig = S.packOrig or {}
  -- only what differs is set, and only a changed material reloads (a reload of every one of
  -- ~90 materials took 0.6-0.9 s, vis-packs-10)
  local dirty = {}
  local function set(mat, matName, field, value)
    value = tostring(value)
    if mat:getField(field, 0) ~= value then
      mat:setField(field, 0, value)
      dirty[matName] = mat
    end
  end
  for matName, fields in pairs(S.packSet or {}) do
    local mat, orig = scenetree.findObject(matName), S.packOrig[matName]
    if mat and orig then
      for field in pairs(fields) do
        if not (pack[matName] and pack[matName][field] ~= nil) and orig[field] ~= nil then set(mat, matName, field, orig[field]) end
      end
    end
  end
  for matName, fields in pairs(pack) do
    local mat = scenetree.findObject(matName)
    if mat then
      local orig = S.packOrig[matName] or {}
      S.packOrig[matName] = orig
      for field, value in pairs(fields) do
        if orig[field] == nil then orig[field] = mat:getField(field, 0) end
        set(mat, matName, field, value)
      end
    end
  end
  -- reloaded a few a frame (reloadStep): ~80 in one frame stalled it for 0.5-1 s
  -- A second click can arrive before the first queue drains. Even a material
  -- whose final fields already match still needs its pending GPU reload.
  local pending, queued = S.reloadQueue or {}, {}
  S.reloadQueue = {}
  for _, mat in ipairs(pending) do
    if not queued[mat] then table.insert(S.reloadQueue, mat); queued[mat] = true end
  end
  for _, mat in pairs(dirty) do
    if not queued[mat] then table.insert(S.reloadQueue, mat); queued[mat] = true end
  end
  result.packReloads = #S.reloadQueue
  S.packSet = pack
  local tMats = timer:stop()
  -- sky, fog and the sun of the pack
  local env = S.packEnv and S.packEnv[name]
  if env then
    applySkyDriver(env)
    applyEnvObjects(env)
    -- again a little later: the sky's lighting is captured some frame after a change, and a
    -- capture during the switch left the same night lit like dusk in some runs (vis-packs-11, -13)
    S.envAgain = {env = env, at = {S.now + 0.7, S.now + 2.0, S.now + 4.0}}
    showSun(env.sun ~= false and env.sun or nil)
    showLights(env.lights ~= false and env.lights or nil)
    showPrecip(env.precip ~= false and env.precip or nil)
  end
  S.pack = name
  result.pack, result.packSwitchMs = name, timer:stop()
  result.packSwitches = result.packSwitches or {}
  table.insert(result.packSwitches, {name, math.floor(tMats), math.floor(result.packSwitchMs)})
end

-- --- arrival ------------------------------------------------------------------------------------
local function cameraOver(height)
  local sp = S.landing.spawn.pos
  local p = vec3(sp[1] - height * 0.35, sp[2] - height * 0.55, sp[3] + height)
  local q = quatFromDir(vec3(sp[1], sp[2], sp[3]) - p, vec3(0, 0, 1))
  core_camera.setPosRot(0, p.x, p.y, p.z, q.x, q.y, q.z, q.w)
end

-- The land beyond the far city: one plane 40 km wide under the whole world at the lowest ground
-- round the landing (horizonZ from the companion), in the ground material, without collision.
local function makeHorizon(z, cx, cy)
  local old = scenetree.findObject('e2r_horizon')
  if old then old:delete() end
  if not z then return end
  local R, k = 20000, 1 / 96   -- the open land's sheet (generator.lua COVER_SCALE.ground)
  local verts = {{x = -R, y = -R, z = 0}, {x = R, y = -R, z = 0}, {x = R, y = R, z = 0}, {x = -R, y = R, z = 0}}
  local up = {x = 0, y = 0, z = 1}
  local uvs = {}
  for n, v in ipairs(verts) do uvs[n] = {u = v.x * k, v = v.y * k} end
  local faces = {}
  for _, v in ipairs({0, 2, 1, 0, 3, 2}) do table.insert(faces, {v = v, n = v, u = v}) end
  local obj = createObject('ProceduralMesh')
  obj:registerObject('e2r_horizon')
  obj.canSave = false
  obj:createMesh({{{verts = verts, normals = {up, up, up, up}, uvs = uvs, faces = faces, material = 'e2rf_ground'}}})
  obj:setPosition(vec3(cx, cy, z))
end

local function beginArrival(job, early)
  local manifest = early or (type(job.manifest) == 'table' and job.manifest or jsonReadFile(job.manifest))
  if not manifest then return end
  -- where the arrival's own frame goes (result.arrivalMs): it is seconds long
  local arrival, arrivalTimer = {}, hptimer()
  result.arrivalMs = arrival
  -- leave the previous region
  for key, tile in pairs(S.tiles) do
    retireForest(tile)
    dropGroup('E2RT_' .. key); dropGroup('E2RD_' .. key); dropGroup('E2RS_' .. key); tile.dropped = true
  end
  for key, far in pairs(S.far) do
    retireForest(far)
    dropGroup('E2RF_' .. key); far.dropped = true
  end
  for key, horizon in pairs(S.horizon or {}) do
    dropGroup(horizon.groupName or ('E2RH_' .. key:gsub('[^%w_]', '_')))
    horizon.dropped = true
  end
  S.tiles, S.far, S.horizon, S.queue, S.co = {}, {}, {}, {}, nil
  -- traffic and parked cars of the old place have no roads here
  if trafficRunning() then gameplay_traffic.deleteVehicles() end
  if S.flow then M.flowSet(0) end
  if S.walk then M.walkersPark() end   -- the count asked comes back with the drive
  M.knockPark()
  if S.park then parking.clear(S.park) end
  S.nav, S.navPending, S.navLights, S.navDirty, S.trafficWanted = {}, {}, {}, false, nil
  S.navAt, S.navPos, S.navSerial, S.signalDirty, S.signalAt = nil, nil, nil, nil, nil
  map.reset({})
  if ui_apps_minimap_roads and ui_apps_minimap_roads.reset then ui_apps_minimap_roads.reset() end
  S.stream = {region = job.region, country = job.country, tile = job.tileSize, generator = job.generator}
  -- the level's TimeOfDay at the landing: the sun of the place (Kyiv's at Los Angeles was hours off)
  if job.lat and job.lon then pcall(function() core_environment.setTimeOfDay({latitude = job.lat, longitude = job.lon}) end) end
  S.landing = manifest
  S.knownMats = {}
  S.lamps = {}
  arrival.leave = arrivalTimer:stopAndReset()
  -- Stock conifers are level assets. Load their definitions from the user's
  -- installation; no game geometry or material file is distributed with EarthNG.
  -- Stock shapes stay in the player's install. Load their materials or the mesh is orange.
  local stockMaterials = {'/levels/italy/art/shapes/trees/trees_italy/main.materials.json',
    '/levels/east_coast_usa/art/shapes/trees/trees_oak/main.materials.json',
    '/levels/east_coast_usa/art/shapes/trees/trees_beech/main.materials.json',
    '/levels/east_coast_usa/art/shapes/trees/trees_aspen/main.materials.json',
    '/levels/east_coast_usa/art/shapes/groundcover/3d_grass_test/main.materials.json',
    '/levels/east_coast_usa/art/shapes/rocks/main.materials.json',
    -- firs, poplars, garden shrubs, clover, daisies and ferns (generator.lua VEG)
    '/levels/east_coast_usa/art/shapes/trees/trees_douglasfir/main.materials.json',
    '/levels/east_coast_usa/art/shapes/trees/ECA_coast_bush/main.materials.json',
    '/levels/east_coast_usa/art/shapes/groundcover/main.materials.json',
    '/levels/automation_test_track/art/shapes/trees/trees_poplar/main.materials.json'}
  for _, path in ipairs(stockMaterials) do
    if FS:fileExists(path) then loadJsonMaterialsFile(path) end
  end
  arrival.stock = arrivalTimer:stopAndReset()
  loadNewMaterials(manifest.materials, manifest.stockMaterials)
  arrival.materials = arrivalTimer:stopAndReset()
  if manifest.spawn and job.horizonZ then pcall(makeHorizon, job.horizonZ, manifest.spawn.pos[1], manifest.spawn.pos[2]) end
  if manifest.packs and FS:fileExists(manifest.packs) then
    local okP, packs = pcall(jsonReadFile, manifest.packs)
    if okP and packs then
      for _, fields in pairs(packs.fields or {}) do dropMissingMaps(fields) end
      for _, defs in pairs(packs.warm or {}) do dropMissingMaps(defs) end
    end
    S.packs = okP and packs and packs.fields or nil
    S.packEnv = okP and packs and packs.environment or nil
    arrival.packMaps = arrivalTimer:stopAndReset()
    if okP and packs and packs.order then
      PACK_NAMES = {}
      for _, name in ipairs(packs.order) do
        table.insert(PACK_NAMES, {name, packs.labels and packs.labels[name]})
      end
    end
    if okP and packs and packs.extra and not S.packsExtra then      -- the sun's material
      S.matSeq = (S.matSeq or 0) + 1
      local tmpE = string.format('e2r_world/materials_%d.json', S.matSeq)
      jsonWriteFile(tmpE, packs.extra, false)
      loadJsonMaterialsFile('/' .. tmpE)
      S.packsExtra = true
    end
    -- every pack's textures load now, the normal way, on warm-up triangles (removed with the
    -- warm-up; the materials keep them): a texture first met through a runtime swap streams in broken
    if okP and packs and packs.warm and not S.packsWarm then
      local group = tileGroup('E2RWorldPacks')
      local n = 0
      local all = {}
      for pack, defs in pairs(packs.warm) do all[pack] = defs end
      if packs.extra then all.extra = packs.extra end
      for pack, defs in pairs(all) do
        S.matSeq = (S.matSeq or 0) + 1
        local tmp = string.format('e2r_world/materials_%d.json', S.matSeq)
        jsonWriteFile(tmp, defs, false)
        loadJsonMaterialsFile('/' .. tmp)
        for name in pairs(defs) do
          n = n + 1
          local obj = createObject('ProceduralMesh')
          obj:registerObject('e2r_pk_' .. n)
          obj.canSave = false
          group:addObject(obj.obj)
          obj:createMesh({{{verts = {{x = 0, y = 0, z = 0}, {x = 3, y = 0, z = 0}, {x = 0, y = 3, z = 0}},
                            normals = {{x = 0, y = 0, z = 1}}, uvs = {{u = 0, v = 0}, {u = 1, v = 0}, {u = 0, v = 1}},
                            faces = {{v = 0, n = 0, u = 0}, {v = 2, n = 0, u = 2}, {v = 1, n = 0, u = 1}},
                            material = name}}})
          local sp0 = manifest.spawn.pos
          obj:setPosition(vec3(sp0[1] + (n % 20) * 4 - 40, sp0[2] + math.floor(n / 20) * 4 + 30, sp0[3] + 3))
        end
      end
      S.packsWarm = true
      result.packMaterialsWarmed = n
    end
    arrival.packWarm = arrivalTimer:stopAndReset()
    if S.pack and S.pack ~= 'real' then applyPack(S.pack) end   -- keep the player's choice
  end
  arrival.packs = arrivalTimer:stopAndReset()
  commands.setFreeCamera()
  cameraOver(CAM_HIGH)
  -- one visible triangle per material: texture upload and pipeline creation happen now, high up,
  -- instead of while driving (Obolon runs 24/25)
  local warm = tileGroup('E2RWorldWarmup')
  local sp = manifest.spawn.pos
  for k, mat in ipairs(manifest.mats) do
    local obj = createObject('ProceduralMesh')
    obj:registerObject('e2r_warm_' .. k)
    obj.canSave = false
    warm:addObject(obj.obj)
    obj:createMesh({{{verts = {{x = 0, y = 0, z = 0}, {x = 3, y = 0, z = 0}, {x = 0, y = 3, z = 0}},
                      normals = {{x = 0, y = 0, z = 1}}, uvs = {{u = 0, v = 0}, {u = 1, v = 0}, {u = 0, v = 1}},
                      faces = {{v = 0, n = 0, u = 0}, {v = 2, n = 0, u = 2}, {v = 1, n = 0, u = 1}},
                      material = mat}}})
    obj:setPosition(vec3(sp[1] + (k % 12) * 4 - 24, sp[2] + math.floor(k / 12) * 4 - 24, sp[3] + 3))
  end
  -- Render each shape during loading so its materials/shaders are uploaded as well as
  -- its mesh. Keep the instances underground afterwards to retain the loaded resources.
  arrival.warm = arrivalTimer:stopAndReset()
  local shapes = tileGroup('E2RWorldShapes')
  -- walkers coming with this drive (asked before it, or the automation's): their shapes too
  if (M.walkersGet() > 0 or (test and test.walkers)) and manifest.warmShapes and not manifest.peopleWarm then
    manifest.peopleWarm = true
    for _, shape in ipairs(M.peopleShapes(true)) do
      if FS:fileExists(shape) then table.insert(manifest.warmShapes, shape) end
    end
  end
  for k, shape in ipairs(manifest.warmShapes or {}) do
    local obj = createObject('TSStatic')
    obj:setField('shapeName', 0, shape)
    obj:setField('collisionType', 0, 'None')
    obj:setPosRot(sp[1] - CAM_HIGH * 0.35 + 20 + (k - 4) * 8,
                  sp[2] - CAM_HIGH * 0.55 + 35, sp[3] + CAM_HIGH - 65, 0, 0, 0, 1)
    obj:registerObject('e2r_shape_' .. k)
    shapes:addObject(obj)
  end
  arrival.shapes = arrivalTimer:stopAndReset()
  -- (no collection here: the heap is the tiles waiting to be spawned, 817 MB before a 1.1 s
  -- collection and 915 MB at the end of the warm-up, load-05)
  S.state, S.phaseAt, S.frames, S.landOwed = 'warmup', S.now, {}, nil
  -- early: the tile under the requested point is in, the rest of the landing square is still
  -- being built (native job.early); M.landFinal swaps in the chosen spawn when the job is ready
  S.landEarly = early and true or nil
  result.readyAt, result.timings, result.earlyArrival = S.now, job.timings, early and true or nil
  -- the landing in real seconds since the request (S.now stands still in a long frame)
  M.loadMark('ready')
  if not early then M.loadMark('final') end
  saveResult()
end

-- Called after the landing tile is loaded and its collision rebuilt (teleporting in the same frame
-- as reloadCollision dropped the car through the new roads, world-test-04).
local function touchDown()
  -- the landing's garbage goes before the drive starts, not in sweeps during its first seconds: the
  -- engine's own full collection, nudged to run here (gc.lua M.nudge)
  result.touchDownCollectMs = M.gc.nudge()
  local timer = hptimer()
  local veh = getPlayerVehicle(0)
  local s = S.landing.spawn
  if veh then
    spawn.safeTeleport(veh, vec3(s.pos[1], s.pos[2], s.pos[3] + 0.5), quat(0, 0, math.sin(s.yaw / 2), math.cos(s.yaw / 2)))
  end
  result.teleportMs = timer:stopAndReset()
  commands.setGameCamera()
  result.cameraSwitchMs = timer:stop()
  S.state, S.phaseAt = 'driving', S.now
  S.driveAcc = newAcc()
  result.landedAt = S.now
  result.startupSeconds = S.landTimer and S.landTimer:stop() / 1000 or S.now - S.landAt
  M.loadMark('landed')
  if S.samples then
    result.samples = {n = S.samples.n}
    for _, kind in ipairs({'top', 'pair'}) do
      local list = {}
      for where, n in pairs(S.samples[kind]) do list[#list + 1] = {where, n} end
      table.sort(list, function(a, b) return a[2] > b[2] end)
      for k = 71, #list do list[k] = nil end
      result.samples[kind] = list
    end
  end
  saveResult()
end

-- --- autopilot (route test): pure pursuit along the companion's route ----------------------------

local function autopilotStart(route, speed)
  AP = {pts = route.points, idx = 1, speed = speed or 13, travelled = 0, last = nil, stuckAt = S.now}
  -- join the route at its point nearest to the car (the landing spawn is not the route start)
  local veh = getPlayerVehicle(0)
  if veh then
    local p, best = veh:getPosition(), math.huge
    for k, q in ipairs(AP.pts) do
      local d = (q[1] - p.x) ^ 2 + (q[2] - p.y) ^ 2
      if d < best then AP.idx, best = k, d end
    end
    AP.startIdx = AP.idx
  end
end

local function autopilotStep(dt)
  local veh = getPlayerVehicle(0)
  if not (AP and veh) then return end
  local p, v = veh:getPosition(), veh:getVelocity()
  local speed = v:length()
  if AP.last then AP.travelled = AP.travelled + math.sqrt((p.x - AP.last.x) ^ 2 + (p.y - AP.last.y) ^ 2) end
  AP.last = vec3(p.x, p.y, p.z)
  local pts = AP.pts
  -- advance along the route to the nearest point ahead (bounded search window)
  local bestK, bestD = AP.idx, math.huge
  for k = AP.idx, math.min(#pts, AP.idx + 60) do
    local d = (pts[k][1] - p.x) ^ 2 + (pts[k][2] - p.y) ^ 2
    if d < bestD then bestK, bestD = k, d end
  end
  AP.idx = bestK
  AP.offRoute = math.sqrt(bestD)
  if AP.idx >= #pts - 1 then
    AP.done = true
    veh:queueLuaCommand("input.event('throttle', 0, 2) input.event('brake', 1, 2) input.event('steering', 0, 2)")
    return
  end
  local look = math.max(7, speed * 1.1)
  local k, acc = AP.idx, 0
  while k < #pts and acc < look do
    acc = acc + math.sqrt((pts[k + 1][1] - pts[k][1]) ^ 2 + (pts[k + 1][2] - pts[k][2]) ^ 2)
    k = k + 1
  end
  local tx, ty = pts[k][1] - p.x, pts[k][2] - p.y
  local fwd = veh:getDirectionVector()
  local fl = math.sqrt(fwd.x ^ 2 + fwd.y ^ 2) + 1e-6
  local fx, fy = fwd.x / fl, fwd.y / fl
  local cross, dot = fx * ty - fy * tx, fx * tx + fy * ty
  local ang = math.atan2(cross, dot)                     -- >0: target to the left
  local steer = math.max(-1, math.min(1, -ang * 2.2))    -- BeamNG: steering -1 = left
  -- slow down for bends ahead and for tiles that are not there yet
  local k2, acc2 = AP.idx, 0
  local turn = 0
  while k2 < #pts - 1 and acc2 < 45 do
    local ax, ay = pts[k2 + 1][1] - pts[k2][1], pts[k2 + 1][2] - pts[k2][2]
    local bx, by = pts[k2 + 2][1] - pts[k2 + 1][1], pts[k2 + 2][2] - pts[k2 + 1][2]
    turn = turn + math.abs(math.atan2(ax * by - ay * bx, ax * bx + ay * by))
    acc2 = acc2 + math.sqrt(ax * ax + ay * ay)
    k2 = k2 + 1
  end
  local target = AP.speed
  if turn > 0.35 then target = math.min(target, 8) end
  if turn > 0.9 then target = math.min(target, 5.5) end
  local ahead = math.max(25, speed * 4)
  AP.waiting = not tileLoadedAt(p.x + fx * ahead, p.y + fy * ahead)
  AP.aheadKey = string.format('%d_%d', tileOf(p.x + fx * ahead, p.y + fy * ahead))
  if AP.waiting then target = 0 end
  -- stuck without a reason (not waiting for a tile): screenshot, then an assist that puts the car
  -- 20 m further along the route. Assists are counted and reported, never hidden.
  if not AP.waiting and speed < 0.5 then
    AP.stillFor = (AP.stillFor or 0) + dt
  else
    AP.stillFor = 0
  end
  if AP.stillFor > 8 then
    AP.stillFor = 0
    AP.assists = (AP.assists or 0) + 1
    result.assists = result.assists or {}
    table.insert(result.assists, {math.floor(S.now), math.floor(p.x), math.floor(p.y), math.floor(p.z * 10) / 10, AP.idx})
    shot(string.format('7-stuck-%02d', AP.assists))
    local k, acc = AP.idx, 0
    while k < #pts - 1 and acc < 20 do
      acc = acc + math.sqrt((pts[k + 1][1] - pts[k][1]) ^ 2 + (pts[k + 1][2] - pts[k][2]) ^ 2)
      k = k + 1
    end
    -- safeTeleport turns the given rotation by 180 degrees itself (spawn.lua), so the plain
    -- direction quaternion faces the car along the route (route-03 assists faced backwards)
    local dir = vec3(pts[k + 1][1] - pts[k][1], pts[k + 1][2] - pts[k][2], 0):normalized()
    spawn.safeTeleport(veh, vec3(pts[k][1], pts[k][2], p.z + 1.5), quatFromDir(dir, vec3(0, 0, 1)))
    AP.idx = k
    return
  end
  local throttle = math.max(0, math.min(0.6, (target - speed) * 0.25))
  local brake = speed > target + 1.5 and math.min(1, (speed - target) * 0.3) or 0
  -- the arcade gearbox engages reverse when the brake is held at a standstill (and then the
  -- throttle brakes): below 2 m/s stop with the parking brake instead (route-02 stall at 1.8 km)
  local park = 0
  if speed < 2 then
    brake = 0
    if target <= 0.5 then park, throttle = 1, 0 end
  end
  veh:queueLuaCommand(string.format("input.event('steering', %.3f, 2) input.event('throttle', %.3f, 2) input.event('brake', %.3f, 2) input.event('parkingbrake', %d, 2)",
    steer, throttle, brake, park))
end

-- --- UI ------------------------------------------------------------------------------------------
-- --- the map ---------------------------------------------------------------------------------
-- Drawn here from 256 px OSM tiles (one cached texture each; the companion copies missing ones to
-- e2r_world/maptiles/z/x/y.png). A tile not in yet shows a part of an ancestor tile, scaled up.
-- (A composed 720x440 picture per pan was slow, and the old one, shifted by UV while the next was
-- made, wrapped round over itself.)
local MAP_TEX_MAX, MAP_LOADS_PER_FRAME, MAP_RETRY = 320, 4, 8
local mapTex, mapTexN, mapAsked, mapWant, mapLoads, mapFrame = {}, 0, {}, {}, 0, 0
local function col(r, g, b, a) return im.GetColorU322(im.ImVec4(r, g, b, a or 1)) end

local function mapTile(z, x, y, load)
  local key = z .. '/' .. x .. '/' .. y
  local t = mapTex[key]
  if t then t.used = mapFrame; return t end
  if not load then return nil end
  if NATIVE then return nil end
  local asked = mapAsked[key]
  -- the file is looked for a little after asking, not with an FS call per tile and frame
  if asked and S.now - asked.at < 0.2 then return nil end
  local path = '/e2r_world/maptiles/' .. key .. '.png'
  if mapLoads < MAP_LOADS_PER_FRAME and FS:fileExists(path) then
    local ok, tex = pcall(imguiUtils.texObj, path)
    if ok and tex then
      mapLoads = mapLoads + 1
      tex.used = mapFrame
      mapTex[key], mapTexN, mapAsked[key] = tex, mapTexN + 1, nil
      if mapTexN > MAP_TEX_MAX then
        -- forget the least recently drawn half
        local list = {}
        for k, v in pairs(mapTex) do list[#list + 1] = {k, v.used} end
        table.sort(list, function(p, q) return p[2] < q[2] end)
        local drop = math.floor(#list / 2)
        for k = 1, drop do mapTex[list[k][1]] = nil end
        mapTexN = #list - drop
      end
      return tex
    end
  end
  if not asked then
    mapWant[#mapWant + 1] = {z, x, y}
    mapAsked[key] = {at = S.now, sent = S.now, first = S.now}
  elseif S.now - asked.sent > MAP_RETRY then
    mapWant[#mapWant + 1] = {z, x, y}
    asked.at, asked.sent = S.now, S.now
  else
    asked.at = S.now
  end
  return nil
end

-- world x, y (the frame of the landing) -> lat, lon by the companion's local affine (stream.geo)
local function worldToGeo(x, y)
  local g = S.status and S.status.stream and S.status.stream.geo
  if not g then return nil end
  local dx, dy = x - g[1], y - g[2]
  return g[4] + g[7] * dx + g[8] * dy, g[3] + g[5] * dx + g[6] * dy
end

-- A tile's navigation lanes in lat/lon with their bounds ({south, west, north, east}), once per
-- manifest: the minimap culls them by the view instead of projecting every point every frame.
-- Projected a few segments a frame: the minimap's first frame in central Kyiv projected every
-- loaded tile's lanes at once (155 ms, the drive-start hitch). A tile's lanes fill in over a
-- few frames instead; the points a frame are shared by all tiles.
local navLineCache = setmetatable({}, {__mode = 'k'})
local NAV_POINTS_PER_FRAME, navBudget = 1500, {at = -1, left = 0}
local function navLines(manifest)
  local hit = navLineCache[manifest]
  if hit and hit.done then return hit.lines end
  if not (S.status and S.status.stream and S.status.stream.geo) then return hit and hit.lines or {} end
  if navBudget.at ~= mapFrame then navBudget.at, navBudget.left = mapFrame, NAV_POINTS_PER_FRAME end
  if not hit then hit = {lines = {}, next = 1}; navLineCache[manifest] = hit end
  local segments, lines = manifest.navSegments or {}, hit.lines
  while hit.next <= #segments and navBudget.left > 0 do
    local segment = segments[hit.next]
    hit.next = hit.next + 1
    local geo, s, w, n, e = {}, math.huge, math.huge, -math.huge, -math.huge
    for k = 8, #segment, 3 do
      local lat, lon = worldToGeo(segment[k], segment[k + 1])
      geo[#geo + 1], geo[#geo + 2] = lat, lon
      s, w, n, e = math.min(s, lat), math.min(w, lon), math.max(n, lat), math.max(e, lon)
    end
    navBudget.left = navBudget.left - #geo / 2
    if #geo >= 4 then lines[#lines + 1] = {id = segment[1], geo = geo, box = {s, w, n, e}} end
  end
  hit.done = hit.next > #segments
  return lines
end

-- the car on the map: lat, lon of it and of a point 30 m ahead
local function carOnMap()
  if S.state ~= 'driving' or not S.stream then return nil end
  local p, v = focus()
  if not p then return nil end
  local dir
  if v and v:length() > 2 then
    dir = v:normalized()
  else
    local veh = getPlayerVehicle(0)
    dir = veh and veh:getDirectionVector() or vec3(0, 1, 0)
  end
  local lat, lon = worldToGeo(p.x, p.y)
  if not lat then return nil end
  local lat2, lon2 = worldToGeo(p.x + dir.x * 30, p.y + dir.y * 30)
  return {lat = lat, lon = lon, lat2 = lat2, lon2 = lon2}
end

local function loadCoverage()
  if S.coverage or S.now - (S.coverageAt or -10) < 2 then return end
  S.coverageAt = S.now
  if FS:fileExists('/e2r_world/coverage.json') then
    local ok, c = pcall(jsonReadFile, '/e2r_world/coverage.json')
    if ok and c and c.boxes then S.coverage = c.boxes end
  end
end

-- The landing zones as non-overlapping rectangles. Pack coverage boxes are the geographic bounds
-- of projected cells, so neighbours overlap and a translucent fill drew darker stripes where they
-- did. Edges snap to a 0.005 degree grid, each band between edges gets the union of its boxes,
-- and equal neighbouring bands join. Done once per status (the boxes table changes on refresh).
local SNAP = 0.005
local mergedFrom, merged = nil, {}
local function mergedCoverage(boxes)
  if boxes == mergedFrom then return merged end
  mergedFrom, merged = boxes, {}
  if not boxes or #boxes == 0 then return merged end
  -- outwards: neighbouring cells of a tilted grid leave hairline gaps between their boxes
  local bands, keys = {}, {}
  for _, c in ipairs(boxes) do
    local w, s = math.floor(c[1] / SNAP), math.floor(c[2] / SNAP)
    local e, n = math.ceil(c[3] / SNAP), math.ceil(c[4] / SNAP)
    if e > w and n > s then
      for y = s, n - 1 do
        local band = bands[y]
        if not band then band = {}; bands[y] = band; keys[#keys + 1] = y end
        band[#band + 1] = {w, e}
      end
    end
  end
  table.sort(keys)
  local open = {}   -- intervals of the band above, 'w:e' -> its rectangle
  for _, y in ipairs(keys) do
    local band = bands[y]
    table.sort(band, function(a, b) return a[1] < b[1] end)
    local runs, cur = {}, nil
    for _, iv in ipairs(band) do
      if cur and iv[1] <= cur[2] then cur[2] = math.max(cur[2], iv[2])
      else cur = {iv[1], iv[2]}; runs[#runs + 1] = cur end
    end
    local now = {}
    for _, r in ipairs(runs) do
      local key = r[1] .. ':' .. r[2]
      local rect = open[key]
      if rect and rect[4] == y * SNAP then rect[4] = (y + 1) * SNAP
      else
        rect = {r[1] * SNAP, y * SNAP, r[2] * SNAP, (y + 1) * SNAP}
        merged[#merged + 1] = rect
      end
      now[key] = rect
    end
    open = now
  end
  return merged
end

-- Per country: its zone's bounds and the PRESETS inside it, once per status (native.at per
-- preset and frame cost ~120 lookups a frame).
local packsFrom, packs = nil, {}
local function packInfo()
  local status = S.status
  if status == packsFrom and status and status.countries == packs.countries then return packs end
  packsFrom, packs = status, {countries = status and status.countries, byId = {}}
  for _, region in ipairs(status and status.regions or {}) do
    local p = packs.byId[region.country] or {regions = 0, presets = {}, sections = {}}
    packs.byId[region.country] = p
    p.regions = p.regions + 1
    for _, c in ipairs(region.coverage or {}) do
      p.box = p.box and {math.min(p.box[1], c[1]), math.min(p.box[2], c[2]), math.max(p.box[3], c[3]), math.max(p.box[4], c[4])}
        or {c[1], c[2], c[3], c[4]}
    end
  end
  if NATIVE then
    for _, place in ipairs(native.sectionPlaces(status and status.regions)) do
      local pack = packs.byId[place[4]]
      if pack then pack.sections[#pack.sections + 1] = place end
    end
    for _, preset in ipairs(PRESETS) do
      local country = native.at(preset[2], preset[3])
      local p = country and packs.byId[country.id]
      if p then p.presets[#p.presets + 1] = preset end
    end
  end
  return packs
end

-- the zoom that shows a {w, s, e, n} box in a width x height map
local function fitZoom(box, width, height)
  local x0, y0 = merc(box[4], box[1], 0)
  local x1, y1 = merc(box[2], box[3], 0)
  local zx = math.log(width * 0.85 / math.max(1e-9, x1 - x0)) / math.log(2)
  local zy = math.log(height * 0.85 / math.max(1e-9, y1 - y0)) / math.log(2)
  return math.max(3, math.min(13, math.floor(math.min(zx, zy))))
end

local function flyToPack(country, width, height)
  local p = packInfo().byId[country.id]
  S.selectedPack = country.id
  if p and p.box then
    S.center = {lat = (p.box[2] + p.box[4]) / 2, lon = (p.box[1] + p.box[3]) / 2}
    S.zoom = fitZoom(p.box, width or S.mapW or W, height or S.mapH or H)
  elseif country.landing then
    S.center, S.zoom = {lat = country.landing.lat, lon = country.landing.lon}, 9
  end
  if country.landing then setMarker(country.landing.lat, country.landing.lon) end
end

-- a round button drawn on the map (imgui items over the map's InvisibleButton never get the
-- hover); returns hovered, clicked
local function mapButton(dl, x, y, size, label, mouse, clicked)
  local hover = mouse.x >= x and mouse.x <= x + size and mouse.y >= y and mouse.y <= y + size
  im.ImDrawList_AddRectFilled(dl, im.ImVec2(x, y), im.ImVec2(x + size, y + size), hover and col(0.93, 0.95, 0.97) or col(1, 1, 1), 5)
  im.ImDrawList_AddRect(dl, im.ImVec2(x, y), im.ImVec2(x + size, y + size), col(0, 0, 0, 0.25), 5, 0, 1)
  local t = im.CalcTextSize(label)
  im.ImDrawList_AddText1(dl, im.ImVec2(x + (size - t.x) / 2, y + (size - t.y) / 2), col(0.2, 0.2, 0.22), label)
  return hover, hover and clicked
end

-- metres per pixel at a latitude -> a 1/2/5 x 10^k bar up to ~110 px
local function drawScale(dl, x, y, lat, z)
  local mpp = 156543.03392 * math.cos(math.rad(lat)) / 2 ^ z
  local metres = mpp * 110
  local p = 10 ^ math.floor(math.log10(metres))
  local nice = metres / p >= 5 and 5 * p or metres / p >= 2 and 2 * p or p
  local px = nice / mpp
  local label = nice >= 1000 and string.format('%g %s', nice / 1000, L('км', 'km')) or string.format('%g %s', nice, L('м', 'm'))
  im.ImDrawList_AddRectFilled(dl, im.ImVec2(x - 4, y - 18), im.ImVec2(x + px + 4, y + 4), col(1, 1, 1, 0.75), 3)
  im.ImDrawList_AddLine(dl, im.ImVec2(x, y), im.ImVec2(x + px, y), col(0.2, 0.2, 0.22), 2)
  im.ImDrawList_AddLine(dl, im.ImVec2(x, y), im.ImVec2(x, y - 5), col(0.2, 0.2, 0.22), 2)
  im.ImDrawList_AddLine(dl, im.ImVec2(x + px, y), im.ImVec2(x + px, y - 5), col(0.2, 0.2, 0.22), 2)
  im.ImDrawList_AddText1(dl, im.ImVec2(x + 2, y - 17), col(0.2, 0.2, 0.22), label)
end

-- view: {center = {lat, lon}, zoom, follow}; pick: a click sets the landing marker
local function drawMap(width, height, view, pick)
  width, height = width or W, height or H
  view = view or S
  mapFrame, mapLoads = mapFrame + 1, 0
  local car = carOnMap()
  if view.follow and car then view.center = {lat = car.lat, lon = car.lon} end
  im.InvisibleButton('##map', im.ImVec2(width, height))
  local hovered = im.IsItemHovered()
  local r0 = im.GetItemRectMin()
  local r1 = im.ImVec2(r0.x + width, r0.y + height)
  local dl = im.GetWindowDrawList()
  local mouse = im.GetMousePos()
  local clicked = hovered and im.IsMouseClicked(0)
  local onControl = false   -- the mouse is over something of the map's own (no pan, no marker)
  im.ImDrawList_PushClipRect(dl, r0, r1, true)
  im.ImDrawList_AddRectFilled(dl, r0, r1, col(0.67, 0.75, 0.8))
  local z = view.zoom
  local n = 2 ^ z
  local cx, cy = merc(view.center.lat, view.center.lon, z)
  local x0, y0 = cx - width / 2, cy - height / 2
  local function screen(lat, lon)
    local x, y = merc(lat, lon, z)
    return r0.x + x - x0, r0.y + y - y0
  end
  local north, west = unmerc(x0, y0, z)
  local south, east = unmerc(x0 + width, y0 + height, z)
  local missing = 0
  if NATIVE then
    planetMap.draw(im, dl, r0, width, height, view, merc, unmerc, col)
  else
    -- the wrapper's default tint (IM_COL32_WHITE) is not defined in the game: nil broke AddImage
    local white = col(1, 1, 1)
    for tx = math.floor(x0 / 256), math.floor((x0 + width) / 256) do
      for ty = math.max(0, math.floor(y0 / 256)), math.min(n - 1, math.floor((y0 + height) / 256)) do
        local sx, sy = r0.x + tx * 256 - x0, r0.y + ty * 256 - y0
        local x = tx % n
        local t = mapTile(z, x, ty, true)
        if t then
          im.ImDrawList_AddImage(dl, t.texId, im.ImVec2(sx, sy), im.ImVec2(sx + 256, sy + 256), im.ImVec2(0, 0), im.ImVec2(1, 1), white)
        else
          missing = missing + 1
          for k = 1, math.min(6, z) do
            local f = 2 ^ k
            local a = mapTile(z - k, math.floor(x / f), math.floor(ty / f), false)
            if a then
              local u, v = (x % f) / f, (ty % f) / f
              im.ImDrawList_AddImage(dl, a.texId, im.ImVec2(sx, sy), im.ImVec2(sx + 256, sy + 256),
                im.ImVec2(u, v), im.ImVec2(u + 1 / f, v + 1 / f), white)
              break
            end
          end
        end
      end
    end
    if #mapWant > 0 then
      request({type = 'maptiles', tiles = mapWant})
      mapWant = {}
    end
  end
  -- where a landing works: one even tint (pick only; the minimap stays clean)
  loadCoverage()
  if pick or not NATIVE then
    local green = col(0.12, 0.62, 0.28, 0.2)
    for _, c in ipairs(mergedCoverage(S.coverage)) do
      if c[3] >= west and c[1] <= east and c[4] >= south and c[2] <= north then
        -- whole pixels: neighbours share an edge exactly, no lighter seam between them
        local ax, ay = screen(c[4], c[1])
        local bx, by = screen(c[2], c[3])
        ax, ay, bx, by = math.floor(ax + 0.5), math.floor(ay + 0.5), math.floor(bx + 0.5), math.floor(by + 0.5)
        if bx > ax and by > ay then
          im.ImDrawList_AddRectFilled(dl, im.ImVec2(ax, ay), im.ImVec2(bx, by), green)
        end
      end
    end
  end
  if NATIVE and (pick or z < 12) then
    planetMap.drawRoads(im, dl, {w = west, s = south, e = east, n = north}, z, screen, col)
  end
  -- streets of the installed country packs on the landing picker (no map download), OSM-like:
  -- main roads from z11 (wider views take more than MAP_BLOCKS 8 km blocks), the rest closer;
  -- while driving the minimap keeps to the loaded tiles' lanes below, every line costs a draw call
  if NATIVE and pick and z >= 11 then
    local maxRank = z >= 15 and 3 or z >= 13 and 2 or 1
    local casing, major, minor = col(0.75, 0.6, 0.35), col(0.99, 0.84, 0.55), col(1, 1, 1)
    local widthMajor = z >= 13 and 4 or 3
    for _, lines in ipairs(native.mapRoads({w = west, s = south, e = east, n = north}, 3)) do
      for pass = 1, 2 do
        for _, line in ipairs(lines) do
          local b = line.box
          if line.rank <= maxRank and (pass == 2 or line.rank == 1) and b[1] <= north and b[3] >= south and b[2] <= east and b[4] >= west then
            local g, px, py = line.geo, nil, nil
            local c, w = line.rank == 1 and major or minor, line.rank == 1 and widthMajor or (z >= 14 and 2.5 or 1.5)
            if pass == 1 then c, w = casing, widthMajor + 1.5 end
            for k = 1, #g - 1, 2 do
              local x, y = screen(g[k], g[k + 1])
              if px then im.ImDrawList_AddLine(dl, im.ImVec2(px, py), im.ImVec2(x, y), c, w) end
              px, py = x, y
            end
          end
        end
      end
    end
  end
  if NATIVE and S.stream and z >= 12 then
    -- the loaded tiles' lanes: projected once per manifest, drawn only where the view is (all of
    -- them every frame, unculled, took 11 ms and 1 MB of garbage a frame in Stone Town)
    local seen, lane = {}, col(0.4, 0.43, 0.45)
    for _, tile in pairs(S.tiles) do
      for _, line in ipairs(navLines(tile.manifest)) do
        local b = line.box
        if not seen[line.id] and b[1] <= north and b[3] >= south and b[2] <= east and b[4] >= west then
          seen[line.id] = true
          -- Mercator pixels at this zoom, once per line and zoom; points under 4 px from the last
          -- drawn one are skipped (every ImVec2 is an engine object, i.e. garbage)
          local m = line.merc
          if line.zoom ~= z then
            m = {}
            local g = line.geo
            for k = 1, #g - 1, 2 do m[k], m[k + 1] = merc(g[k], g[k + 1], z) end
            line.merc, line.zoom = m, z
          end
          local ox, oy = r0.x - x0, r0.y - y0
          local px, py = m[1] + ox, m[2] + oy
          local last = #m - 1
          -- a segment's end is the next one's start: one ImVec2 per drawn point, not two
          -- (the minimap was ~1000 ImVec2 a frame in central Kyiv, most of the widget's 1.2 ms)
          local from = im.ImVec2(px, py)
          for k = 3, last, 2 do
            local x, y = m[k] + ox, m[k + 1] + oy
            if k == last or (x - px) ^ 2 + (y - py) ^ 2 >= 36 then
              local to = im.ImVec2(x, y)
              im.ImDrawList_AddLine(dl, from, to, lane, 2)
              from, px, py = to, x, y
            end
          end
        end
      end
    end
  end
  -- Mark only loaded scenes, so the map and the generated world use the same OSM facts.
  -- Bound both the draw count and crowding in dense streets; no per-frame world scan.
  if NATIVE and S.stream and z >= 15 then
    local occupied, count = {}, 0
    for _, tile in pairs(S.tiles) do
      for _, poi in ipairs(tile.brandPOIs or {}) do
        local lat, lon = worldToGeo(poi.x, poi.y)
        if lat and lat <= north and lat >= south and lon >= west and lon <= east and count < 80 then
          local x, y = screen(lat, lon)
          local key = math.floor(x / 20) .. ':' .. math.floor(y / 20)
          if not occupied[key] then
            occupied[key], count = true, count + 1
            local brand = M.brandStyles[poi.brand]
            local rgb = poi.rgb or (brand and brand[3])
            local c = rgb and col(rgb[1] / 255, rgb[2] / 255, rgb[3] / 255)
              or (poi.kind == 'fuel' and col(0.10, 0.43, 0.70) or col(0.16, 0.55, 0.27))
            im.ImDrawList_AddCircleFilled(dl, im.ImVec2(x, y), 7, col(1, 1, 1))
            im.ImDrawList_AddCircleFilled(dl, im.ImVec2(x, y), 5.5, c)
            if z >= 17 and (poi.brand or poi.label) then
              im.ImDrawList_AddText1(dl, im.ImVec2(x + 8, y - 7), col(0.12, 0.12, 0.12), poi.label or (brand and brand[2] or poi.brand))
            end
          end
        end
      end
    end
  end
  -- the route and its flag, over the streets and under the labels
  if M.navigator and S.state == 'driving' then
    M.navigator.draw(im, dl, z, r0.x - x0, r0.y - y0, merc, col, north, west, south, east)
  end
  -- the controls' corners and the pins keep the labels off
  if NATIVE then
    planetMap.beginLabels()
    planetMap.reserve(r1.x - 44, r0.y, r1.x, r0.y + 120)
    planetMap.reserve(r0.x, r1.y - 26, r0.x + 140, r1.y)
  end
  -- the installed packs as pins until their streets show: a click flies to the pack
  local pinHit
  if NATIVE and pick and z < 10 then
    local blue, rim = col(0.13, 0.4, 0.85), col(1, 1, 1)
    for _, country in ipairs(S.status and S.status.countries or {}) do
      local at = country.available and country.landing
      if at and at.lat <= north + 1 and at.lat >= south - 1 and at.lon >= west - 1 and at.lon <= east + 1 then
        local x, y = screen(at.lat, at.lon)
        local selected = S.selectedPack == country.id
        local c = selected and col(0.1, 0.6, 0.3) or blue
        im.ImDrawList_AddCircleFilled(dl, im.ImVec2(x, y - 12), 8, rim)
        im.ImDrawList_AddTriangleFilled(dl, im.ImVec2(x - 6, y - 9), im.ImVec2(x + 6, y - 9), im.ImVec2(x, y), rim)
        im.ImDrawList_AddCircleFilled(dl, im.ImVec2(x, y - 12), 6.5, c)
        im.ImDrawList_AddTriangleFilled(dl, im.ImVec2(x - 4.8, y - 9.5), im.ImVec2(x + 4.8, y - 9.5), im.ImVec2(x, y - 1.5), c)
        im.ImDrawList_AddCircleFilled(dl, im.ImVec2(x, y - 12), 2.5, rim)
        -- the name where it fits (packs of one country crowd together; a hover names any pin)
        local t = im.CalcTextSize(country.title)
        local lx, ly = x + 11, y - 12 - t.y / 2 - 2
        local named = planetMap.place(x - 9, y - 22, lx + t.x + 8, y + 2)
        local hover = mouse.x >= x - 9 and mouse.y >= y - 22 and mouse.y <= y + 2 and mouse.x <= (named and lx + t.x + 8 or x + 9)
        if named then
          im.ImDrawList_AddRectFilled(dl, im.ImVec2(lx, ly), im.ImVec2(lx + t.x + 8, ly + t.y + 4),
            hover and col(1, 1, 0.85) or col(1, 1, 1, 0.92), 4)
          im.ImDrawList_AddText1(dl, im.ImVec2(lx + 4, ly + 2), selected and col(0.05, 0.4, 0.2) or col(0.1, 0.2, 0.45), country.title)
        else
          planetMap.reserve(x - 9, y - 22, x + 9, y + 2)
        end
        if hover and hovered then pinHit = country end
      end
    end
  end
  -- cities and countries
  local placeHit
  if NATIVE then
    placeHit = planetMap.drawLabels(im, dl, r0, width, height, view, merc, unmerc, col, lang,
      hovered and mouse or nil, pick and 70 or 25)
    if not pick then placeHit = nil end
  end
  if S.marker then
    local mx, my = screen(S.marker.lat, S.marker.lon)
    -- a red pin on the landing point
    im.ImDrawList_AddCircleFilled(dl, im.ImVec2(mx, my - 14), 9, col(1, 1, 1))
    im.ImDrawList_AddTriangleFilled(dl, im.ImVec2(mx - 7, my - 11), im.ImVec2(mx + 7, my - 11), im.ImVec2(mx, my), col(1, 1, 1))
    im.ImDrawList_AddCircleFilled(dl, im.ImVec2(mx, my - 14), 7.5, col(0.86, 0.15, 0.12))
    im.ImDrawList_AddTriangleFilled(dl, im.ImVec2(mx - 5.6, my - 11.5), im.ImVec2(mx + 5.6, my - 11.5), im.ImVec2(mx, my - 1.5), col(0.86, 0.15, 0.12))
    im.ImDrawList_AddCircleFilled(dl, im.ImVec2(mx, my - 14), 3, col(0.5, 0.05, 0.05))
  end
  if car then
    -- an arrow along the heading, with a white rim for any background
    local px, py = screen(car.lat, car.lon)
    local qx, qy = screen(car.lat2, car.lon2)
    local dx, dy = qx - px, qy - py
    local len = math.sqrt(dx * dx + dy * dy)
    if len < 1e-6 then dx, dy, len = 0, -1, 1 end
    dx, dy = dx / len, dy / len
    local function arrow(s, c)
      im.ImDrawList_AddTriangleFilled(dl,
        im.ImVec2(px + dx * 12 * s, py + dy * 12 * s),
        im.ImVec2(px - dx * 8 * s - dy * 8 * s, py - dy * 8 * s + dx * 8 * s),
        im.ImVec2(px - dx * 8 * s + dy * 8 * s, py - dy * 8 * s - dx * 8 * s), c)
    end
    arrow(1.35, col(1, 1, 1))
    arrow(1, col(0.1, 0.45, 0.95))
  end
  -- zoom buttons and the scale
  local zoomTo
  if hovered or not view.follow then
    local bx, size = r1.x - 38, 28
    local hIn, cIn = mapButton(dl, bx, r0.y + 10, size, '+', mouse, clicked)
    local hOut, cOut = mapButton(dl, bx, r0.y + 10 + size + 4, size, '-', mouse, clicked)
    local hCar, cCar = false, false
    if car then
      hCar, cCar = mapButton(dl, bx, r0.y + 10 + (size + 4) * 2, size, '@', mouse, clicked)
      if cCar then
        view.center = {lat = car.lat, lon = car.lon}
        if not pick then view.follow = true end
      end
      if hCar and hovered then im.SetTooltip(L('До авто', 'Center on car')) end
    end
    onControl = hIn or hOut or hCar
    if cIn then zoomTo = z + 1 elseif cOut then zoomTo = z - 1 end
  end
  drawScale(dl, r0.x + 10, r1.y - 8, view.center.lat, z)
  local credit = NATIVE and 'Natural Earth | (c) OpenStreetMap contributors' or '(c) OpenStreetMap'
  local tw = im.CalcTextSize(credit).x
  im.ImDrawList_AddRectFilled(dl, im.ImVec2(r1.x - tw - 8, r1.y - 18), r1, col(1, 1, 1, 0.75))
  im.ImDrawList_AddText1(dl, im.ImVec2(r1.x - tw - 4, r1.y - 17), col(0.15, 0.15, 0.15), credit)
  -- what a click here would do
  if pick and hovered and not onControl and (pinHit or placeHit) then
    local tip = pinHit and (pinHit.title .. L(' - показати пакет', ' - show the pack')) or (placeHit.name .. L(' - поставити точку', ' - set the point'))
    local t = im.CalcTextSize(tip)
    im.ImDrawList_AddRectFilled(dl, im.ImVec2(mouse.x + 14, mouse.y + 16), im.ImVec2(mouse.x + 22 + t.x, mouse.y + 20 + t.y), col(0.12, 0.13, 0.15, 0.92), 4)
    im.ImDrawList_AddText1(dl, im.ImVec2(mouse.x + 18, mouse.y + 18), col(1, 1, 1), tip)
  end
  im.ImDrawList_PopClipRect(dl)
  -- a tile asked long ago and still not here: the companion could not download it
  if missing > 0 then
    for _, a in pairs(mapAsked) do
      if S.now - a.first > MAP_RETRY then
        im.TextColored(im.ImVec4(1, 0.6, 0.2, 1), L('Частина мапи не завантажилась (інтернет?) - пробую ще.',
          'Part of the map did not load (internet?) - retrying.'))
        break
      end
    end
  end
  -- wheel: zoom round the cursor (round the car while following); drag: pan, stops following;
  -- click: the landing point (a pin: its pack; a city: the city)
  local io = im.GetIO()
  local px, py = mouse.x - r0.x, mouse.y - r0.y
  local minZoom = NATIVE and 2 or 3
  if hovered and io.MouseWheel ~= 0 and not zoomTo then zoomTo = z + (io.MouseWheel > 0 and 1 or -1) end
  if zoomTo then
    local nz = math.max(minZoom, math.min(18, zoomTo))
    -- the buttons zoom round the centre, the wheel round the cursor
    local ax, ay = px, py
    if onControl then ax, ay = width / 2, height / 2 end
    if not (view.follow and car) then
      local lat, lon = unmerc(x0 + ax, y0 + ay, z)
      local wx, wy = merc(lat, lon, nz)
      view.center = {}
      view.center.lat, view.center.lon = unmerc(wx - ax + width / 2, wy - ay + height / 2, nz)
    end
    view.zoom = nz
  end
  if clicked and not onControl then view.dragging, view.dragMoved = true, 0 end
  if view.dragging then
    if im.IsMouseDown(0) then
      local d = im.GetMouseDragDelta(0, 0)
      if d.x ~= 0 or d.y ~= 0 then
        local ccx, ccy = merc(view.center.lat, view.center.lon, z)
        view.center = {}
        view.center.lat, view.center.lon = unmerc(ccx - d.x, ccy - d.y, z)
        view.dragMoved = view.dragMoved + math.abs(d.x) + math.abs(d.y)
        if view.dragMoved > 4 then view.follow = false end
        im.ResetMouseDragDelta(0)
      end
    else
      if pick and view.dragMoved < 4 and hovered then
        if pinHit then flyToPack(pinHit, width, height)
        elseif placeHit then setMarker(placeHit.lat, placeHit.lon)
        else setMarker(unmerc(x0 + px, y0 + py, z)) end
      elseif view.onClick and view.dragMoved < 4 and hovered then
        view.onClick(unmerc(x0 + px, y0 + py, z))
      end
      view.dragging = false
    end
  end
end

local function countTiles()
  local loaded, loading = 0, 0
  for _, t in pairs(S.tiles) do
    if t.state == 'loaded' then loaded = loaded + 1 else loading = loading + 1 end
  end
  return loaded, loading
end

-- texture packs: three equal buttons a row across the window, the active one lit
local function drawPacks()
  local current = S.pack or 'real'
  local label = current
  for _, p in ipairs(PACK_NAMES) do if p[1] == current then label = packLabel(p) end end
  im.Text(L('Стиль: ', 'Style: ') .. label)
  local spacing = im.GetStyle().ItemSpacing.x
  local width = math.floor((im.GetContentRegionAvailWidth() - 2 * spacing) / 3)
  for k, p in ipairs(PACK_NAMES) do
    if (k - 1) % 3 ~= 0 then im.SameLine() end
    local active = current == p[1]
    if active then
      im.PushStyleColor2(im.Col_Button, im.ImVec4(0.15, 0.55, 0.3, 1))
      im.PushStyleColor2(im.Col_ButtonHovered, im.ImVec4(0.2, 0.65, 0.35, 1))
    end
    if im.Button(packLabel(p) .. '##pack_' .. p[1], im.ImVec2(width, 0)) and not active then applyPack(p[1]) end
    if active then im.PopStyleColor(2) end
  end
end

local function recentFrames()
  local list, total, worst = {}, 0, 0
  for _, ms in pairs(S.recent or {}) do
    table.insert(list, ms); total = total + ms; worst = math.max(worst, ms)
  end
  if #list == 0 then return nil end
  table.sort(list)
  return 1000 * #list / math.max(total, 1e-3), list[math.ceil(#list * 0.99)], worst
end

local function drawStats(st, p, v)
  local fps, p99, worst = recentFrames()
  if fps then
    im.Text(string.format(L('FPS %.0f   кадр p99 %.0f мс, найгірший %.0f мс', 'FPS %.0f   frame p99 %.0f ms, worst %.0f ms'), fps, p99, worst))
  end
  if p then
    im.Text(string.format(L('Швидкість %.0f км/год   висота %.0f м', 'Speed %.0f km/h   altitude %.0f m'), (v and v:length() or 0) * 3.6, p.z))
  end
  if st and st.car then im.Text(string.format(L('Авто: %.5f, %.5f', 'Car: %.5f, %.5f'), st.car[2], st.car[1])) end
  -- tiles in the game
  local roads, collided, scenes, loading, failed, far = 0, 0, 0, 0, 0, 0
  for _, t in pairs(S.tiles) do
    if t.failed then failed = failed + 1
    elseif t.roadComplete then
      roads = roads + 1
      if t.collided then collided = collided + 1 end
      if t.sceneComplete then scenes = scenes + 1 end
    else loading = loading + 1 end
  end
  for _ in pairs(S.far) do far = far + 1 end
  local bands = 0
  for _ in pairs(S.horizon or {}) do bands = bands + 1 end
  result.horizonResident = bands
  im.Text(string.format(L('У грі: доріг %d (з колізією %d), сцен %d, далеких %d, горизонт %d',
    'In game: roads %d (with collision %d), scenes %d, far %d, horizon %d'), roads, collided, scenes, far, bands))
  im.Text(string.format(L('Вантажаться %d, збої %d, доставка p99 %.1f с', 'Loading %d, failed %d, delivery p99 %.1f s'), loading, failed, S.deliveryP99 or 0))
  if trafficRunning() and gameplay_traffic.getTrafficAmount then
    local nav = S.navStats or {}
    im.Text(string.format(L('Трафік (%s): авто %d, граф %d вузлів, збірка %.0f мс',
      'Traffic (%s): cars %d, graph %d nodes, build %.0f ms'), S.trafficSource == 'game cars' and L('машини гри', 'game cars') or S.trafficSource == 'simple' and L('прості', 'simple') or S.trafficSource == 'full' and L('повні', 'full') or S.trafficSource or L('гра', 'game'),
      gameplay_traffic.getTrafficAmount(), nav.nodes or 0, nav.ms or 0))
  end
  if S.flow then
    im.Text(string.format(L('Потік: авто %d (справжніх %d), рух %.2f мс, показ %.2f мс',
      'Flow: cars %d (real %d), sim %.2f ms, draw %.2f ms'),
      S.flow.F.count or 0, M.handoffSim.activeCount(S.flow.H), S.flow.simMs or 0, S.flow.drawMs or 0))
    im.Text(string.format(L('Світлофорні перехрестя: %d, стоять на червоному: %d', 'Lit crossings: %d, waiting at red: %d'),
      S.flow.F.crossings or 0, S.flow.F.atRed or 0))
  end
  if S.walk and S.walk.P then   -- (no pool yet: the count was asked before the drive)
    local h = S.walk.P.stats
    im.Text(string.format(L('Пішоходи: %d, тіл %d/%d, зіткнень %d, рух %.2f мс, показ %.2f мс',
      'Pedestrians: %d, bodies %d/%d, hits %d, sim %.2f ms, draw %.2f ms'),
      S.walk.W.count or 0, M.pedHit.activeCount(S.walk.P), #S.walk.P.pool, h.hit, S.walk.simMs or 0, S.walk.drawMs or 0))
  end
  if st and not NATIVE then
    local nFailed = 0
    for _ in pairs(st.failed or {}) do nFailed = nFailed + 1 end
    im.Text(string.format(L('Компаньйон: готові %d, будуються %d, черга %d, збої %d',
      'Companion: ready %d, building %d, queued %d, failed %d'),
      st.readyCount or 0, st.building or 0, st.queued or 0, nFailed))
    im.Text(string.format(L('Збірка тайла: середня %.1f с, p99 %.1f с, зібрано %d',
      'Tile build: mean %.1f s, p99 %.1f s, built %d'),
      st.meanBuildSeconds or 0, st.buildP99 or 0, st.built or 0))
    im.Text(string.format(L('Запас: %.0f с наперед, радіус %.1f км', 'Ahead: %.0f s, radius %.1f km'), st.horizonSeconds or 0, (st.loadRadius or 0) / 1000))
    if st.edgeKm then im.Text(string.format(L('До краю вікна індексу: %.1f км', 'To the index window edge: %.1f km'), st.edgeKm)) end
    if st.origin and p then
      local grey = im.ImVec4(0.65, 0.65, 0.65, 1)
      im.TextColored(grey, string.format(L('Початок координат: %.3f, %.3f, %s', 'Origin: %.3f, %.3f, %s'), st.origin[2], st.origin[1], st.crs or '?'))
      im.TextColored(grey, string.format(L('Авто від початку: %.1f км', 'Car from origin: %.1f km'), math.sqrt(p.x * p.x + p.y * p.y) / 1000))
    end
  end
end

-- --- the look: our windows only (pushed round Begin/End, the game's own UI keeps its style) ------
local theme
local function pushTheme()
  if not theme then
    local function c(r, g, b, a) return im.ImVec4(r, g, b, a or 1) end
    theme = {colors = {
      {im.Col_WindowBg, c(0.10, 0.11, 0.13, 0.97)}, {im.Col_ChildBg, c(0.13, 0.14, 0.17, 1)},
      {im.Col_TitleBg, c(0.10, 0.18, 0.30, 1)}, {im.Col_TitleBgActive, c(0.12, 0.28, 0.50, 1)},
      {im.Col_FrameBg, c(0.19, 0.21, 0.25, 1)}, {im.Col_FrameBgHovered, c(0.24, 0.27, 0.32, 1)},
      {im.Col_Button, c(0.21, 0.24, 0.29, 1)}, {im.Col_ButtonHovered, c(0.27, 0.33, 0.41, 1)},
      {im.Col_ButtonActive, c(0.18, 0.42, 0.78, 1)}, {im.Col_Header, c(0.16, 0.38, 0.70, 0.65)},
      {im.Col_HeaderHovered, c(0.22, 0.44, 0.76, 0.55)}, {im.Col_HeaderActive, c(0.18, 0.42, 0.78, 0.9)},
      {im.Col_Separator, c(0.28, 0.30, 0.35, 1)}, {im.Col_Text, c(0.92, 0.93, 0.95, 1)},
      {im.Col_TextDisabled, c(0.50, 0.53, 0.58, 1)}},
      vars = {{im.StyleVar_WindowRounding, 8}, {im.StyleVar_ChildRounding, 6}, {im.StyleVar_FrameRounding, 5}},
      vars2 = {{im.StyleVar_WindowPadding, im.ImVec2(12, 10)}, {im.StyleVar_FramePadding, im.ImVec2(8, 5)},
        {im.StyleVar_ItemSpacing, im.ImVec2(8, 6)}},
      muted = c(0.62, 0.65, 0.70, 1), accent = c(0.45, 0.70, 1, 1), warn = c(1, 0.65, 0.3, 1),
      green = c(0.13, 0.55, 0.30, 1), greenHover = c(0.16, 0.65, 0.36, 1), greenActive = c(0.10, 0.45, 0.25, 1)}
  end
  for _, p in ipairs(theme.colors) do im.PushStyleColor2(p[1], p[2]) end
  for _, p in ipairs(theme.vars) do im.PushStyleVar1(p[1], p[2]) end
  for _, p in ipairs(theme.vars2) do im.PushStyleVar2(p[1], p[2]) end
end
local function popTheme()
  im.PopStyleColor(#theme.colors)
  im.PopStyleVar(#theme.vars + #theme.vars2)
end

-- the packs in the side list by part of the world (their landing point)
local GROUP_ORDER = {'europe', 'america', 'south', 'africa', 'asia', 'oceania', 'other'}
local GROUP_TITLE = {europe = {'Європа', 'Europe'}, america = {'Північна Америка', 'North America'},
  south = {'Південна Америка', 'South America'}, africa = {'Африка', 'Africa'}, asia = {'Азія', 'Asia'},
  oceania = {'Океанія', 'Oceania'}, other = {'Інші', 'Other'}}
local function presetName(p) return lang == 'en' and p[5] or p[1] end
local function packGroup(country)
  local l = country.landing
  if not l then return 'other' end
  if l.lon >= -30 and l.lon <= 60 and l.lat >= 35 then return 'europe' end
  if l.lon < -30 then return l.lat >= 12 and 'america' or 'south' end
  if l.lon <= 55 and l.lat < 37 then return 'africa' end
  if l.lon > 110 and l.lat < -10 then return 'oceania' end
  return 'asia'
end

local searchBuf = im.ArrayChar(192)
local foundPlaces

-- buttons that wrap to the next line when the row is full
local function flowButtons(items, onClick)
  local spacing = im.GetStyle().ItemSpacing.x
  local avail = im.GetContentRegionAvailWidth()
  local used = 0
  for k, item in ipairs(items) do
    local name = presetName(item)
    local w = im.CalcTextSize(name).x + 16
    if k > 1 and used + spacing + w <= avail then im.SameLine(); used = used + spacing + w else used = w end
    if im.Button(name .. '##preset' .. k) then onClick(item) end
  end
end

local function drawSidebar(mapW, mapH)
  im.SetNextItemWidth(-36)
  local submitted = im.InputTextWithHint('##search', L('Місто, село, країна...', 'City, village, country...'), searchBuf, 192, im.InputTextFlags_EnterReturnsTrue)
  local searchActive = im.IsItemActive()
  im.SameLine()
  if im.Button('X##clearSearch') then ffi.fill(searchBuf, 192); foundPlaces = nil end
  if im.IsItemHovered() then im.SetTooltip(L('Очистити пошук', 'Clear search')) end
  local query = planetMap and planetMap.lower(ffi.string(searchBuf):gsub('^%s+', ''):gsub('%s+$', '')) or ''
  if query ~= S.searchQuery then S.searchChoice, S.searchQuery = 1, query end
  local countries = NATIVE and S.status and S.status.countries or {}
  local info = packInfo()
  im.BeginChild1('##searchResults', im.ImVec2(0, 0), false)
  if query ~= '' then
    local any = false
    for _, country in ipairs(countries) do
      if country.available and planetMap.lower(country.title):find(query, 1, true) then
        if not any then im.TextColored(theme.muted, L('Пакети', 'Packs')); any = true end
        if im.Selectable1(country.title .. '##found_' .. country.id, S.selectedPack == country.id) then flyToPack(country, mapW, mapH) end
      end
    end
    -- the places of a query, with their pack check, once per query (native.at walks the boxes)
    if not foundPlaces or foundPlaces.query ~= query or foundPlaces.status ~= S.status or foundPlaces.lang ~= lang or foundPlaces.revision ~= planetMap.revision() then
      local places = {query = query, status = S.status, lang = lang, revision = planetMap.revision()}
      for _, p in ipairs(PRESETS) do
        local hit = planetMap.lower(p[1]):find(query, 1, true) or (p[5] and planetMap.lower(p[5]):find(query, 1, true))
        if hit and (not NATIVE or native.at(p[2], p[3])) then
          places[#places + 1] = {name = presetName(p), lat = p[2], lon = p[3], zoom = 15, covered = true}
        end
      end
      for _, p in ipairs(planetMap and planetMap.search(query, lang, 25) or {}) do
        p.covered = not NATIVE or native.at(p.lat, p.lon) ~= nil
        places[#places + 1] = p
      end
      foundPlaces = places
    end
    local places = foundPlaces
    if searchActive then
      if im.IsKeyPressed(im.GetKeyIndex(im.Key_DownArrow)) then S.searchChoice = math.min(#places, S.searchChoice + 1) end
      if im.IsKeyPressed(im.GetKeyIndex(im.Key_UpArrow)) then S.searchChoice = math.max(1, S.searchChoice - 1) end
      if im.IsKeyPressed(im.GetKeyIndex(im.Key_Escape)) then ffi.fill(searchBuf, 192); foundPlaces = nil; return end
    end
    S.searchChoice = math.max(1, math.min(#places, S.searchChoice))
    if #places > 0 then
      im.Spacing()
      im.TextColored(theme.muted, L('Місця', 'Places'))
      for k, p in ipairs(places) do
        local suffix = p.kind == 'country' and L(' · країна', ' · country') or p.covered and '' or L('  (немає пакета)', '  (no pack)')
        if im.Selectable1(p.name .. suffix .. '##place' .. k, k == S.searchChoice) or (submitted and k == S.searchChoice) then
          S.searchChoice = k
          if p.kind == 'country' then
            S.center, S.zoom = {lat = p.lat, lon = p.lon}, p.zoom
            S.marker, S.selectedPack = nil, nil
          else goTo(p.lat, p.lon, p.zoom or 12) end
        end
        if p.context then
          local kind = p.kind == 'village' and L('село', 'village') or p.kind == 'hamlet' and L('хутір', 'hamlet')
            or p.kind == 'town' and L('містечко', 'town') or p.kind == 'city' and L('місто', 'city') or L('район', 'district')
          im.TextColored(theme.muted, kind .. ' · ' .. p.context)
        end
      end
    elseif not any then
      im.TextColored(theme.muted, L('Нічого не знайдено', 'Nothing found'))
      im.TextWrapped(L('Спробуйте місцеву або англійську назву. Села доступні з оновленими даними мапи.',
        'Try a local or English name. Villages require updated map data.'))
    end
    im.EndChild()
    return
  end
  if NATIVE then
    local available = 0
    for _, country in ipairs(countries) do if country.available then available = available + 1 end end
    im.TextColored(theme.muted, string.format(L('Встановлені пакети: %d', 'Installed packs: %d'), available))
    if #countries == 0 then
      im.TextWrapped(L('Пакетів країн немає. Додайте earthng_<країна>.zip до папки mods і ввімкніть його в менеджері модів.',
        'No country packs installed. Add earthng_<country>.zip to your mods folder and enable it in the Mod Manager.'))
    end
    local groups = {}
    for _, country in ipairs(countries) do
      local g = packGroup(country)
      groups[g] = groups[g] or {}
      table.insert(groups[g], country)
    end
    for _, g in ipairs(GROUP_ORDER) do
      local list = groups[g]
      if list then
        table.sort(list, function(a, b) return a.title < b.title end)
        im.Spacing()
        im.TextColored(theme.accent, L(GROUP_TITLE[g][1], GROUP_TITLE[g][2]))
        im.Separator()
        for _, country in ipairs(list) do
          if country.available then
            local selected = S.selectedPack == country.id
            if im.Selectable1(country.title .. '##pack_' .. country.id, selected) then flyToPack(country, mapW, mapH) end
            local p = info.byId[country.id]
            if selected and p and #p.sections > 1 then
              im.Indent(10)
              im.TextColored(theme.muted, L('Частини пакета', 'Sections'))
              flowButtons(p.sections, function(section) goTo(section[2], section[3], 13) end)
              im.Unindent(10)
              im.Spacing()
            end
            if selected and p and #p.presets > 0 then
              im.Indent(10)
              flowButtons(p.presets, function(preset) goTo(preset[2], preset[3], 15) end)
              im.Unindent(10)
              im.Spacing()
            end
          else
            im.TextColored(theme.muted, country.title .. ': ' .. tostring(country.reason or L('недоступно', 'unavailable')))
          end
        end
      end
    end
  else
    local shown = {}
    for _, p in ipairs(PRESETS) do if presetInPackage(p) then shown[#shown + 1] = p end end
    im.TextColored(theme.muted, L('Місця пакета', 'Places of the package'))
    flowButtons(shown, function(preset) goTo(preset[2], preset[3], 15) end)
  end
  im.EndChild()
end

-- under the map: the point, the landing button, coordinates
local function drawLandingBar()
  if S.marker then
    local country = NATIVE and native.at(S.marker.lat, S.marker.lon)
    if not NATIVE or country then
      im.PushStyleColor2(im.Col_Button, theme.green)
      im.PushStyleColor2(im.Col_ButtonHovered, theme.greenHover)
      im.PushStyleColor2(im.Col_ButtonActive, theme.greenActive)
      if im.Button(L('Висадитися тут', 'Land here'), im.ImVec2(200, 30)) then land() end
      im.PopStyleColor(3)
      im.SameLine()
      -- while driving: the route to the point instead of a new landing (the driven region only)
      if M.navigator and S.state == 'driving' then
        local car, x, y = focus(), native.localPoint(S.marker.lat, S.marker.lon)
        if car and x and im.Button(L('Вести сюди', 'Navigate here'), im.ImVec2(140, 30)) then
          M.navigator.setDestination(x, y, S.marker.lat, S.marker.lon, car, lang)
          S.pickerOpen = false
        end
        im.SameLine()
      end
      im.Text(string.format('%s%.5f, %.5f', country and (country.title .. '  ') or '', S.marker.lat, S.marker.lon))
    elseif M.live then
      if im.Button(L('Завантажити й висадитися', 'Download and land'), im.ImVec2(240, 30)) then
        M.live.request(S.marker.lat, S.marker.lon)
        S.liveArmed = true
      end
      local st = M.live.status()
      if S.liveArmed and st and (st.message_uk or st.message_en) then
        im.TextColored(theme.muted, lang == 'en' and (st.message_en or st.message_uk) or (st.message_uk or st.message_en))
      elseif S.liveArmed then
        im.TextColored(theme.warn, L('Завантаження ще не почалось.',
          'The download has not started.'))
      else
        im.TextColored(theme.muted, L('Пакета тут немає. Кнопка качає OSM і висоти в самій грі.',
          'No pack here. The button downloads OSM and elevation in the game.'))
      end
      if S.liveArmed and native.at(S.marker.lat, S.marker.lon) then
        S.liveArmed = false
        land()
      end
    else
      im.TextColored(theme.warn, string.format(L('%.5f, %.5f - тут немає даних. Оберіть зелену зону або встановіть пакет.',
        '%.5f, %.5f - no data here. Pick a green area or install a pack.'), S.marker.lat, S.marker.lon))
    end
  else
    im.TextColored(theme.muted, L('Клікніть на мапі в зеленій зоні, щоб обрати точку висадки.',
      'Click inside a green area to pick the landing point.'))
  end
  im.SetNextItemWidth(220)
  im.InputTextWithHint('##coords', L('широта, довгота', 'latitude, longitude'), coordBuf, 64)
  im.SameLine()
  if im.Button(L('Перейти', 'Go')) then
    local lat, lon = ffi.string(coordBuf):match('(-?%d+%.?%d*)%s*[,; ]%s*(-?%d+%.?%d*)')
    if lat then goTo(tonumber(lat), tonumber(lon), 15) end
  end
  im.SameLine()
  im.TextColored(theme.muted, L('Колесо - масштаб, перетягування - рух, клік - точка', 'Wheel - zoom, drag - pan, click - point'))
end

local function drawProblems()
  if S.lastError then
    im.TextColored(im.ImVec4(1, 0.3, 0.3, 1), L('Помилка мода: ', 'Mod error: ') .. S.lastError:sub(1, 160))
  end
  if not serverUp() then
    im.TextColored(im.ImVec4(1, 0.45, 0.3, 1), L('Компаньйон Earth2Road не відповідає. Запустіть EarthNG.bat і натисніть «Запустити».',
      'The Earth2Road companion is not responding. Run EarthNG.bat and press Start.'))
  end
  if NATIVE and S.status and #(S.status.errors or {}) > 0 then
    if im.CollapsingHeader1(L('Проблеми з пакетами', 'Pack errors')) then
      for _, err in ipairs(S.status.errors) do im.TextWrapped(tostring(err.message or err)) end
    end
  end
end

-- UA/EN beside "Hide": the whole widget and the map labels switch at once, remembered on disk
local function drawLangButton()
  im.SameLine()
  if im.Button((lang == 'en' and 'UA' or 'EN') .. '##lang') then
    setLang(lang == 'en' and 'uk' or 'en')
    S.viewDirty = true
  end
  if im.IsItemHovered() then im.SetTooltip(L('Switch to English', 'Перемкнути на українську')) end
end

local function drawPicker()
  im.SetNextWindowSize(im.ImVec2(1180, 720), im.Cond_FirstUseEver)
  im.SetNextWindowSizeConstraints(im.ImVec2(820, 500), im.ImVec2(8000, 8000))
  M.winguard.begin(im, L('EarthNG - планета', 'EarthNG - Planet') .. '###planet',
    im.WindowFlags_NoCollapse + im.WindowFlags_NoScrollbar + im.WindowFlags_NoScrollWithMouse)
  if im.Button(L('Приховати', 'Hide')) then S.widgetHidden = true end
  drawLangButton()
  if S.pickerOpen then
    im.SameLine()
    if im.Button(L('Повернутися до їзди', 'Back to driving')) then S.pickerOpen = false end
  end
  im.SameLine()
  im.TextColored(theme.muted, L('Оберіть пакет зліва або місце на мапі', 'Pick a pack on the left or a place on the map'))
  drawProblems()
  local avail = im.GetContentRegionAvail()
  local sideW = 290
  local barH = 2 * im.GetFrameHeightWithSpacing() + 8
  local mapW = math.max(200, avail.x - sideW - im.GetStyle().ItemSpacing.x)
  local mapH = math.max(200, avail.y - barH)
  S.mapW, S.mapH = mapW, mapH
  -- the part of the world with the most packs in view on the first opening (all of them
  -- together can span the planet)
  if S.fitAll then
    local count, best, box = {}, nil, nil
    for _, country in ipairs(S.status and S.status.countries or {}) do
      if country.available then
        local g = packGroup(country)
        count[g] = (count[g] or 0) + 1
        if not best or count[g] > count[best] then best = g end
      end
    end
    for _, country in ipairs(S.status and S.status.countries or {}) do
      local p = packInfo().byId[country.id]
      if country.available and packGroup(country) == best and p and p.box then
        box = box and {math.min(box[1], p.box[1]), math.min(box[2], p.box[2]), math.max(box[3], p.box[3]), math.max(box[4], p.box[4])}
          or {p.box[1], p.box[2], p.box[3], p.box[4]}
      end
    end
    box = box or (S.status and S.status.packageBox)
    if box then
      S.center = {lat = (box[2] + box[4]) / 2, lon = (box[1] + box[3]) / 2}
      S.zoom = fitZoom(box, mapW, mapH)
    end
    S.fitAll = nil
  end
  im.BeginChild1('##side', im.ImVec2(sideW, avail.y), true)
  drawSidebar(mapW, mapH)
  im.EndChild()
  im.SameLine()
  im.BeginGroup()
  drawMap(mapW, mapH, S, true)
  drawLandingBar()
  im.EndGroup()
  im.End()
end

-- Live density and draw distance. Density rebuilds scenes while roads stay in
-- place; changing only distances or global small-decor caps needs no rebuild.
local TUNE_DEFAULT = quality.preset(50)
local tunePtr = {}

local function ensureTune()
  if S.tune then return end
  S.tune = {}
  for k, v in pairs(TUNE_DEFAULT) do S.tune[k] = v end
end

local function applyTune()
  ensureTune()
  if not NATIVE or not native.setTune then return end
  local applied = native.setTune(S.tune)
  if type(applied) == 'table' then
    S.tune = applied
    for key, ptr in pairs(tunePtr) do
      if key == 'groundTrees' then ptr[0] = applied.groundTrees and true or false
      elseif applied[key] then ptr[0] = applied[key] end
    end
  end
  local base = S.appliedTune or TUNE_DEFAULT
  local rebuild = false
  for _, key in ipairs({'maxTrees','maxFarTrees','maxGrass','maxRocks','forestSpacing','groundSpacing','groundTrees','propSpacing'}) do
    if S.tune[key] ~= base[key] then rebuild = true end
  end
  if ((S.tune.parkedCars or 0) > 0) ~= ((base.parkedCars or 0) > 0) then rebuild = true end
  if rebuild then
    local keep = {}
    for _, job in ipairs(S.queue or {}) do
      if job.horizon or not job.scene and not job.far then keep[#keep+1] = job end
    end
    S.queue = keep
    if S.job and (S.job.scene or S.job.far) then S.co, S.job = nil, nil end
    -- Keep driveable road meshes and collision under the car throughout the rebuild.
    for key, tile in pairs(S.tiles) do
      retireForest(tile)
      buryGroup('E2RD_' .. key); buryGroup('E2RS_' .. key)
      tile.decor = tileGroup('E2RD_' .. key, true)
      tile.left = tile.roadLeft
      tile.sceneStarted, tile.sceneComplete, tile.sceneLeft = nil, nil, nil
      tile.refreshScene = true
      native.unload(key)
    end
    for key, far in pairs(S.far) do
      retireForest(far); buryGroup('E2RF_' .. key)
      far.dropped = true; native.unload(key, 'far')
    end
    S.far = {}
    S.collisionDirty = true
  end
  local ok, cfg = pcall(jsonReadFile, LANG_FILE)
  cfg = ok and type(cfg) == 'table' and cfg or {}
  cfg.lang, cfg.tune = lang, S.tune
  pcall(jsonWriteFile, LANG_FILE, cfg, true)
  result.tuneApplied = S.now
  S.appliedTune = {}
  for k, v in pairs(S.tune) do S.appliedTune[k] = v end
end

-- Parked cars (parking.lua): the spots of the loaded tiles go to the game every parking.EVERY s,
-- the pool follows the setting. The cars load (~0.5 s a car) while the camera comes down, round
-- the spawn point, not in the drive. A pool car left on a tile that has gone or lost its
-- collision would fall through the world: it is moved to a usable spot first.
local function updateParking()
  if S.parkedPick then
    ensureTune()
    S.tune.parkedCars, S.parkedPick = S.parkedPick, nil
    applyTune()
  end
  if not NATIVE or not S.stream or (S.state ~= 'driving' and S.state ~= 'spawning') then return end
  if S.now - (S.parkAt or -1e9) < parking.EVERY then return end
  S.parkAt = S.now
  S.park = S.park or parking.new()
  local timer = hptimer()
  parking.sync(S.park, S.tiles)
  local syncMs = timer:stopAndReset()
  local p = focus()
  if S.state == 'spawning' then local sp = S.landing.spawn.pos; p = vec3(sp[1], sp[2], sp[3]) end
  if p then
    local want = (S.appliedTune or TUNE_DEFAULT).parkedCars or 0
    if parking.step(S.park, want, vec3(p.x, p.y, p.z)) then result.parkedSpawns = (result.parkedSpawns or 0) + 1 end
    result.parkingStepMs = math.max(result.parkingStepMs or 0, timer:stopAndReset())
    if S.state == 'driving' and S.park.spawned > 0 and gameplay_parking then
      for _, id in ipairs(gameplay_parking.getParkedCarsList() or {}) do
        if be:getObjectActive(id) then
          local x, y = be:getObjectPositionXYZ(id)
          local tile = S.tiles[string.format('%d_%d', tileOf(x, y))]
          if not (tile and tile.collided) then
            gameplay_parking.forceTeleport(id, vec3(p.x, p.y, p.z), 0, 400)
            result.parkedRescued = (result.parkedRescued or 0) + 1
          end
        end
      end
    end
  end
  if syncMs > (result.parkingSyncMs or 0) then result.parkingSyncMs = syncMs end
  result.parkingSpots, result.parkingSpotsAll, result.parkedCars = S.park.count, S.park.total, S.park.spawned
end

local function tuneSlider(key, lo, hi, uk, en)
  local tune = S.tune
  if not tunePtr[key] then tunePtr[key] = im.FloatPtr(tune[key]) end
  if uk ~= '' then im.Text(L(uk, en)) end
  if im.SetNextItemWidth then im.SetNextItemWidth(-1) end
  local ok, changed = pcall(im.SliderFloat, '##' .. key, tunePtr[key], lo, hi, '%.0f')
  if ok then
    -- Copy even when the binding does not return true. Rebuild only on release,
    -- otherwise a drag would drop every tile on every frame.
    local value = tonumber(tunePtr[key][0])
    if value then tune[key] = math.floor(value + 0.5) end
    if im.IsItemDeactivatedAfterEdit and im.IsItemDeactivatedAfterEdit() then S.tuneApplyNow = true end
  else
    im.SameLine()
    if im.Button('-##' .. key) then tune[key] = math.max(lo, tune[key] - math.max(1, (hi - lo) / 20)); S.tuneApplyNow = true end
    im.SameLine()
    if im.Button('+##' .. key) then tune[key] = math.min(hi, tune[key] + math.max(1, (hi - lo) / 20)); S.tuneApplyNow = true end
    im.SameLine()
    im.Text(string.format('%.0f', tune[key]))
    tunePtr[key][0] = tune[key]
  end
end

local function tuneDiffers()
  local base = S.appliedTune or TUNE_DEFAULT
  for key, value in pairs(S.tune) do
    if value ~= base[key] then return true end
  end
  return false
end

local function drawTune()
  ensureTune()
  local function quick(key, uk, en)
    local before = S.tune[key]
    tuneSlider(key, 0, 100, uk, en)
    if S.tune[key] ~= before then
      local parked = S.tune.parkedCars
      if key == 'quality' then S.tune = quality.preset(S.tune.quality)
      else S.tune = quality.preset(S.tune.detail, S.tune.distance) end
      S.tune.parkedCars = parked
      for k, ptr in pairs(tunePtr) do if S.tune[k] ~= nil then ptr[0] = S.tune[k] end end
    end
  end
  if not S.qualityFpsAt or S.now - S.qualityFpsAt > .5 then
    local sum, n = 0, 0
    for _, ms in ipairs(S.recent or {}) do sum, n = sum + ms, n + 1 end
    S.qualityFrameMs, S.qualityFpsAt = n > 0 and sum/n or 0, S.now
  end
  if (S.qualityFrameMs or 0) > 0 then
    im.Text(string.format('%.0f FPS  /  %.1f ms', 1000 / S.qualityFrameMs, S.qualityFrameMs))
  end
  im.Text('Potato')
  im.SameLine(math.max(100, im.GetContentRegionAvailWidth() - 50))
  im.Text('OASIS')
  quick('quality', '', '')
  local name = quality.name(S.tune.quality)
  if S.tune.detail ~= S.tune.distance then name = L('Власні', 'Custom') end
  im.Text(name)
  quick('detail', 'Деталізація', 'Detail')
  quick('distance', 'Дальність малювання', 'Draw distance')
  im.Text(string.format(L('Трава %d м · каміння %d м · світ %.1f км',
    'Grass %d m · rocks %d m · world %.1f km'), S.tune.grassM, S.tune.rockM, S.tune.farM / 1000))
  for k, q in ipairs({{'Potato', 0}, {'Balanced', 50}, {'OASIS', 100}}) do
    if k > 1 then im.SameLine() end
    if im.Button(q[1]) then
      local parked = S.tune.parkedCars
      S.tune = quality.preset(q[2]); S.tune.parkedCars = parked
      tunePtr = {}; S.tuneApplyNow = true
    end
  end
  if tuneDiffers() then
    im.TextColored(im.ImVec4(1, .7, .2, 1), L('Відпустіть повзунок, щоб застосувати.', 'Release the slider to apply.'))
    if im.Button(L('Застосувати', 'Apply')) then S.tuneApplyNow = true end
  end
  if im.CollapsingHeader1(L('Точні налаштування', 'Advanced settings')) then
    tuneSlider('grassM', 0, 220, 'Дальність трави, м', 'Grass distance, m')
    tuneSlider('rockM', 0, 900, 'Дальність каміння, м', 'Rock distance, m')
    tuneSlider('nearM', 400, 4000, 'Ближній світ, м', 'Near world, m')
    tuneSlider('farM', 800, 8000, 'Далекий світ, м', 'Far world, m')
    tuneSlider('maxTrees', 0, 2400, 'Крони на ближній тайл', 'Crowns per near tile')
    tuneSlider('maxFarTrees', 0, 1200, 'Крони на далекий тайл', 'Crowns per far tile')
    tuneSlider('maxGrass', 0, 4800, 'Щільність трави на тайл', 'Grass density per tile')
    tuneSlider('maxRocks', 0, 200, 'Каміння на тайл', 'Rocks per tile')
    tuneSlider('grassBudget', 0, 14000, 'Загальний ліміт трави', 'Total grass limit')
    tuneSlider('rockBudget', 0, 1600, 'Загальний ліміт каміння', 'Total rock limit')
    tuneSlider('forestSpacing', 4, 24, 'Крок лісу, м', 'Forest spacing, m')
    tuneSlider('groundSpacing', 4, 30, 'Крок на відкритому ґрунті, м', 'Open-ground spacing, m')
    if not tunePtr.groundTrees then tunePtr.groundTrees = im.BoolPtr(S.tune.groundTrees) end
    if im.Checkbox(L('Дерева на відкритому ґрунті', 'Trees on open ground'), tunePtr.groundTrees) then
      S.tune.groundTrees = tunePtr.groundTrees[0] and true or false; S.tuneApplyNow = true
    end
    local counts = detailStream and detailStream.count or {}
    im.Text(string.format(L('Зараз: трава %d · каміння %d', 'Live: grass %d · rocks %d'), counts.grass or 0, counts.rock or 0))
    im.Text(string.format(L('Черга %d · крон %d', 'Queue %d · crowns %d'), #S.queue, result.forestItems or 0))
  end
  if S.tuneApplyNow and tuneDiffers() then applyTune() end
  S.tuneApplyNow = nil
end

-- The stock big map (M) shows only tiles the level has loaded. Ours is the planet page:
-- click lands there (the stream follows), it does not teleport the car into an empty world.
function LIMIT.bigMapHook()
  S.bigHook = true
  local ext = rawget(_G, 'freeroam_bigMapMode') or rawget(_G, 'freeroam_bigMap')
  if type(ext) ~= 'table' then S.bigKey = true; return end
  local function open() S.bigMap = not S.bigMap end
  if ext.toggleBigMap then ext.toggleBigMap = open end
  if ext.enterBigMap then ext.enterBigMap = open end
end

function LIMIT.bigMapKey()
  if not im or not im.IsKeyPressed(im.GetKeyIndex(im.Key_M)) then return end
  local io = im.GetIO()
  if io and io.WantTextInput then return end
  S.bigMap = not S.bigMap
end

function LIMIT.drawBigMap()
  local io = im.GetIO()
  local w, h = io.DisplaySize.x, io.DisplaySize.y
  im.SetNextWindowPos(im.ImVec2(0, 0), im.Cond_Always)
  im.SetNextWindowSize(im.ImVec2(w, h), im.Cond_Always)
  local flags = im.WindowFlags_NoTitleBar + im.WindowFlags_NoResize + im.WindowFlags_NoMove + im.WindowFlags_NoCollapse
  M.winguard.begin(im, 'EarthNG##bigmap', flags)
  S.big = S.big or {center = {lat = S.center.lat, lon = S.center.lon}, zoom = S.zoom or 12, follow = false}
  if not S.big.onClick then
    S.big.onClick = function(lat, lon)
      goTo(lat, lon, S.big.zoom or 12)
      land()
      S.bigMap = false
    end
  end
  drawMap(w, math.max(1, h - 36), S.big)
  if im.Button(L('Закрити', 'Close')) or im.IsKeyPressed(im.GetKeyIndex(im.Key_Escape)) then S.bigMap = false end
  im.End()
end

local function drawWindow()
  if test and test.clean then return end   -- a clean screen for recorded video
  if M.location and S.location and S.state == 'driving' and not S.locationOff then
    M.location.draw(im, S.location, M.navigator and M.navigator.lines(L))
  end
  if NATIVE then planetMap.update(S.status and S.status.countries) end
  pushTheme()
  if S.widgetHidden then
    M.winguard.begin(im, 'EarthNG##restore', im.WindowFlags_AlwaysAutoResize)
    if im.Button(L('Показати мапу', 'Show map')) then S.widgetHidden = false; S.viewDirty = true end
    im.End()
    popTheme()
    return
  end
  if S.state == 'driving' and not S.pickerOpen then
    im.SetNextWindowSize(im.ImVec2(392, 0), im.Cond_Always)
    M.winguard.begin(im, 'EarthNG##mini', im.WindowFlags_NoCollapse + im.WindowFlags_AlwaysAutoResize)
    if im.Button(L('Приховати', 'Hide')) then S.widgetHidden = true end
    im.SameLine()
    if im.Button(L('Обрати інше місце', 'Pick another place')) then S.pickerOpen = true; S.viewDirty = true end
    drawLangButton()
    -- the mini map follows the car (an arrow along the heading); a drag frees it
    S.mini = S.mini or {center = {lat = S.center.lat, lon = S.center.lon}, zoom = 15, follow = true}
    -- a click (no drag) on the minimap: the route there
    if M.navigator and not S.mini.onClick then
      S.mini.onClick = function(lat, lon)
        local car, x, y = focus(), native.localPoint(lat, lon)
        if car and x then M.navigator.setDestination(x, y, lat, lon, car, lang) end
      end
    end
    drawMap(360, 180, S.mini)
    local routeLines = M.navigator and M.navigator.lines(L)
    if routeLines then
      im.TextColored(theme.green, routeLines[1])
      if routeLines[2] then im.Text(routeLines[2]) end
      if im.Button(L('Скасувати маршрут', 'Cancel the route')) then M.navigator.clear() end
      im.SameLine()
    end
    if not S.mini.follow then
      if im.Button(L('До авто', 'To the car')) then S.mini.follow = true end
      im.SameLine()
    end
    im.TextColored(theme.muted, M.navigator and L('Колесо - масштаб, перетягування - огляд, клік - маршрут',
      'Wheel - zoom, drag - look around, click - route') or L('Колесо - масштаб, перетягування - огляд', 'Wheel - zoom, drag - look around'))
    local st = S.status and S.status.stream
    local p, v = focus()
    if st and st.edgeKm and st.edgeKm < 3 then
      if st.live then
        im.TextColored(im.ImVec4(1, 0.5, 0.2, 1), string.format(L('Край вікна: %.1f км. Околиця ще докачується.',
          'Edge of the window: %.1f km. The surroundings are still downloading.'), math.max(0, st.edgeKm)))
      else
        im.TextColored(im.ImVec4(1, 0.5, 0.2, 1), string.format(L('Край завантаженої області: %.1f км. Далі доріг немає -',
          'Edge of the loaded area: %.1f km. No roads beyond it -'), math.max(0, st.edgeKm)))
        im.TextColored(im.ImVec4(1, 0.5, 0.2, 1), L('висадьтеся ближче до нової точки ("Обрати інше місце").',
          'land again near a new point ("Pick another place").'))
      end
    end
    if p and not tileLoadedAt(p.x, p.y) then
      im.TextColored(im.ImVec4(1, 0.7, 0.2, 1), L('Генерую світ попереду, зачекайте...', 'Generating the world ahead, please wait...'))
    end
    if AP then
      im.Text(string.format(L('Автопілот: %.1f км%s', 'Autopilot: %.1f km%s'), AP.travelled / 1000,
        AP.waiting and L(' (чекаю тайл)', ' (waiting for a tile)') or ''))
    end
    if im.CollapsingHeader1(L('Вигляд і трафік', 'Style and traffic')) then
      if S.packs then drawPacks() end
      drawTraffic()
      S.locationShown = S.locationShown or im.BoolPtr(not S.locationOff)
      if im.Checkbox(L('Рядок з назвою вулиці', 'Street name line'), S.locationShown) then
        if M.options and M.options.has('streetLine') then
          M.options.set('streetLine', S.locationShown[0] and true or false, 'widget')   -- saves locationOff
        else   -- no registry (a test stubs require)
          S.locationOff = not S.locationShown[0]
          local ok, cfg = pcall(jsonReadFile, LANG_FILE)
          cfg = ok and type(cfg) == 'table' and cfg or {}
          cfg.locationOff = S.locationOff
          pcall(jsonWriteFile, LANG_FILE, cfg, true)
        end
      end
    end
    if im.CollapsingHeader1(L('Статистика', 'Statistics')) then drawStats(st, p, v) end
    if im.CollapsingHeader1(L('Якість світу', 'World quality'), im.TreeNodeFlags_DefaultOpen) then drawTune() end
    im.End()
    popTheme()
    return
  end
  if S.state == 'pick' or S.pickerOpen then
    drawPicker()
    popTheme()
    return
  end
  -- the landing under way: a small window of its own
  im.SetNextWindowSize(im.ImVec2(W, 0), im.Cond_Always)
  M.winguard.begin(im, L('EarthNG - висадка', 'EarthNG - Landing') .. '###progress', im.WindowFlags_NoCollapse + im.WindowFlags_AlwaysAutoResize)
  if im.Button(L('Приховати', 'Hide')) then S.widgetHidden = true end
  drawLangButton()
  local job = S.status and S.status.job
  if job and job.seq == S.landSeq then
    im.Text(string.format(L('Генерація %.5f, %.5f', 'Generating %.5f, %.5f'), job.lat or 0, job.lon or 0))
    im.ProgressBar(job.progress or 0, im.ImVec2(W - 24, 0), tostring(job.stage or ''))
    if job.state == 'error' then
      im.TextWrapped(L('Помилка: ', 'Error: ') .. tostring(job.message))
      if im.Button(L('Назад до мапи', 'Back to the map')) then S.state = 'pick' end
    end
  elseif S.state == 'generating' then
    im.Text(NATIVE and L('Завантажую дані пакета...', 'Loading pack data...') or
      L('Запит надіслано, чекаю на компаньйон...', 'Request sent, waiting for the companion...'))
  end
  if S.state == 'warmup' or S.state == 'spawning' then
    local loaded = countTiles()
    im.ProgressBar(math.min(1, loaded / 4), im.ImVec2(W - 24, 0), L('Спуск: будую світ', 'Descent: building the world'))
  end
  drawProblems()
  im.End()
  popTheme()
end

-- --- lifecycle -----------------------------------------------------------------------------------
local function inOurLevel()
  local f = getMissionFilename and getMissionFilename() or ''
  return f:find('/e2r_world/', 1, true) ~= nil
end

local function refreshCountries()
  if not NATIVE then return end
  native.refresh()
  S.status, S.coverage, S.centredOnPackage = native.status(), nil, nil
  -- A removed/disabled pack must stop contributing geometry as well as map coverage.
  if S.stream then
    for key, tile in pairs(S.tiles) do
      retireForest(tile)
      dropGroup('E2RT_' .. key); dropGroup('E2RD_' .. key); dropGroup('E2RS_' .. key); tile.dropped = true
    end
    for key, far in pairs(S.far) do
      retireForest(far)
      dropGroup('E2RF_' .. key); far.dropped = true
    end
    for key, band in pairs(S.horizon or {}) do
      dropGroup(band.groupName or ('E2RH_' .. key:gsub('[^%w_]', '_')))
      band.dropped = true
    end
    dropGroup('E2RWorldWarmup'); dropGroup('E2RWorldPacks'); dropGroup('E2RWorldShapes')
    local horizon = scenetree.findObject('e2r_horizon')
    if horizon then horizon:delete() end
    pcall(VISTA.plane, nil)
    dropLights()
    if trafficRunning() then gameplay_traffic.deleteVehicles() end
    if S.flow then M.flowSet(0) end
    if S.walk then M.walkersPark() end
    M.knockPark()
    map.reset({})
    if ui_apps_minimap_roads and ui_apps_minimap_roads.reset then ui_apps_minimap_roads.reset() end
    S.navAt, S.navPos, S.navSerial, S.signalDirty, S.signalAt = nil, nil, nil, nil, nil
    S.stream, S.co, S.job, S.landing = nil, nil, nil, nil
    S.tiles, S.far, S.horizon, S.queue, S.nav, S.navPending, S.navLights = {}, {}, {}, {}, {}, {}, {}
    S.collisionDirty, S.state, S.coll = true, 'off', nil
  end
  if S.state == 'generating' or S.state == 'warmup' then
    S.state, S.landSeq, S.landAt, S.landTimer = 'off', nil, nil, nil
  end
end

function M.onModManagerModsMounted() refreshCountries() end
function M.onModActivated() refreshCountries() end
function M.onModDeactivated() refreshCountries() end
local function restorePackState()
  restoreSkyDriver()
  S.envAgain, S.exposurePending, S.exposureRetryAt = nil, nil, nil
  local lx = scenetree.findObject('PostEffectLocalExposureObject')
  for name, fields in pairs(S.envOrig or {}) do
    local obj = scenetree.findObject(name)
    if obj then
      for field, value in pairs(fields) do obj:setField(field, 0, value) end
      pcall(function() obj:postApply() end)
    end
  end
  for name, fields in pairs(S.packOrig or {}) do
    local mat = scenetree.findObject(name)
    if mat then
      for field, value in pairs(fields) do mat:setField(field, 0, value) end
      mat:reload()
    end
  end
  if lx and S.exposureOrig then lx.autoExposure, lx.manualEV = S.exposureOrig[1], S.exposureOrig[2] end
  S.exposureOrig, S.envOrig, S.packOrig, S.packSet, S.reloadQueue = nil, nil, nil, nil, nil
  S.packsWarm, S.packsExtra, S.packs, S.packEnv = nil, nil, nil, nil
  showPrecip(nil)
  showSun(nil)
  dropLights()
end

function M.onExtensionUnloaded()
  M.gc.step(false)
  restorePackState()
  if S.park then pcall(parking.clear, S.park) end
  if S.navSerial and map.getMap().buildSerial == S.navSerial then
    map.reset({})
    if ui_apps_minimap_roads and ui_apps_minimap_roads.reset then ui_apps_minimap_roads.reset() end
  end
end

function M.onClientEndMission()
  restorePackState()
  resetForests()
  if NATIVE then native.refresh() end
  if S.ocean then pcall(function() S.ocean:delete() end); S.ocean = nil end
  S.stream, S.co, S.job, S.landing, S.state = nil, nil, nil, nil, 'off'
  S.tiles, S.far, S.horizon, S.queue, S.nav, S.navPending, S.navLights = {}, {}, {}, {}, {}, {}, {}
  S.signalDirty, S.signalAt = nil, nil
  M.walkersLost()   -- the walkers' shapes and bodies went with the level; the count asked stays
  S.knock = nil     -- the debris and its pool went with the level; knockOff (the setting) stays
  S.knownMats, S.coverage, S.centredOnPackage = {}, nil, nil
  dropLights()
end

local function runTest()
  -- automation: pick, land, drive (straight, or the route with the autopilot), screenshots
  local t = S.now - (S.phaseAt or 0)
  -- showcase waits (gallery views, flight start): what still loads round the focus. Near and
  -- far tiles not built, horizon blocks not built, items not spawned; returns busy and a
  -- signature that changes while anything still arrives (the horizon may trail).
  S.settleProbe = S.settleProbe or function()
    local loaded, loading = countTiles()
    local st = S.status and S.status.stream or {}
    local near, far, horizon = 0, 0, 0
    for key, priority in pairs(st.wanted or {}) do
      if key:sub(1, 1) == 'h' then
        if not (st.horizon and st.horizon[key]) then horizon = horizon + 1 end
      elseif priority < 1e6 then
        if not (st.ready and st.ready[key]) then near = near + 1 end
      elseif not ((st.far and st.far[key]) or (st.ready and st.ready[key])) then
        far = far + 1
      end
    end
    -- busy by the generator's own queue: it leaves out failed tiles and those evicted this epoch
    -- (the far ring at OASIS outgrows the tile cache), which never become ready
    local queued, building = st.queued or 0, st.building or 0
    local busy = queued > 0 or building > 0 or loading > 0 or #S.queue > 0 or (S.reloadQueue and #S.reloadQueue > 0) or false
    return busy, string.format('%d/%d/%d/%d/%d/q%d', loaded, near, far, horizon, #S.queue, queued)
  end
  if (test.quality or test.propSpacing) and not S.testQuality and S.state == 'pick' then
    S.testQuality = true
    S.tune = quality.preset(test.quality or 50)
    if test.propSpacing then S.tune.propSpacing = test.propSpacing end
    applyTune()
    result.quality = test.quality or 50
  end
  if S.parkAfter then
    local veh = getPlayerVehicle(0)
    if veh and veh:getVelocity():length() < 2 then
      veh:queueLuaCommand("input.event('brake', 0, 2) input.event('parkingbrake', 1, 2)")
      S.parkAfter = nil
    end
  end
  if test.qualityCycle and S.testDone and not S.qualityCycleDone then
    local veh = getPlayerVehicle(0)
    local p = veh:getPosition()
    veh:queueLuaCommand("input.event('throttle',0,2) input.event('brake',0,2) input.event('parkingbrake',1,2)")
    local records = result.qualityCycle or {}
    result.qualityCycle = records
    local last = records[#records]
    if last then last.minZ = math.min(last.minZ, p.z) end
    if not S.qualityCycleAt or S.now - S.qualityCycleAt > 10 then
      if last and (not last.roadPreserved or last.z - last.minZ > 5) then
        result.failures[#result.failures+1] = 'quality_road_lost'
      end
      local q = test.qualityCycle[#records+1]
      if q then
        local i,j = tileOf(p.x,p.y)
        local tile = S.tiles[i .. '_' .. j]
        local road = tile and tile.group
        S.tune = quality.preset(q); tunePtr = {}; applyTune()
        records[#records+1] = {quality=q,z=p.z,minZ=p.z,
          roadPreserved=tile and tile.group == road and tile.roadComplete and not tile.dropped or false}
        S.qualityCycleAt = S.now
      else S.qualityCycleDone = true end
      saveResult()
    end
    return
  end
  if NATIVE and S.now - (S.nativeReportAt or -10) > 2 then
    S.nativeReportAt = S.now
    local status = native.status()
    local job, stream = status.job or {}, status.stream or {}
    result.native = {countryCount = status.countryCount, provider = status.provider,
      job = {state = job.state, progress = job.progress, message = job.message, stage = job.stage},
      built = stream.built, ready = stream.readyCount, error = S.lastError,
      cachedTiles = stream.cachedTiles, cachedCells = stream.cachedCells, rebuilds = stream.rebuilds,
      slowResumes = stream.slowResumes, spentMs = stream.spentMs, stageMs = stream.stageMs,
      ioStats = stream.ioStats, lost = stream.lost}
    if M.live and M.live.status then
      local liveState = M.live.status()
      if liveState then result.live = {message_en = liveState.message_en, message_uk = liveState.message_uk} end
    end
    local P = S.prof
    if P and P.frames > 0 then
      local mean = {}
      for part, sum in pairs(P.sum) do mean[part] = sum / P.frames end
      local kbMean = {}
      for part, sum in pairs(P.kb) do kbMean[part] = sum / P.frames end
      result.luaProfile = {frames = P.frames, meanMs = mean, maxMs = P.max, heapKb = collectgarbage('count'), kbPerFrame = kbMean,
        garbageKbPerFrame = P.kbUp / P.frames, collections = P.collections,
        -- gc.lua: cycles the pace ended, the engine's full collections seen, the touch-down's nudge
        gc = M.gc.report()}
    end
    saveResult()
  end
  -- picker check: optionally centre the map on a point and hold it there (a desktop capture
  -- sees the imgui map; the game's own screenshots do not contain it)
  if test.pickerOnly and S.state == 'pick' and test.pickerZoom and not S.testPicked and t > 2 then
    goTo(test.lat, test.lon, test.pickerZoom)
    S.testPicked = S.now
  end
  if test.pickerOnly and S.state == 'pick' and t > (test.pickerHold or 4) then
    shot('1-picker')
    local actual = NATIVE and native.status().countryCount or 0
    result.status = actual == (test.expectedCountries or 0) and not S.lastError and 'passed' or 'failed'
    saveResult()
    shutdown(result.status == 'passed' and 0 or 1)
    return
  end
  if test.pickerOnly then return end
  -- the landing bar may leave the picker on its own once the live window exists
  if S.liveTest and not S.testLanded and S.state ~= 'pick' then
    S.testLanded = true
  end
  -- manual play: the automation only picks the point and lands; the player drives from there
  if test.manual and S.testLanded and S.state ~= 'pick' then
    -- the flow and the pedestrians asked for (--flow, --walkers), once driving: the automatic drive
    -- below switches them on, manual play never gets there
    if S.state == 'driving' and not S.manualTraffic then
      S.manualTraffic = true
      if test.flowReal then S.flowReal = test.flowReal end
      if test.flow then M.flowSet(test.flow) end
      if test.walkBodies then S.walkBodies = test.walkBodies end
      if test.walkers then M.walkersSet(test.walkers) end
    end
    -- keep the report current for the drive (it was frozen at the landing, play-bilychi-01)
    if S.state == 'driving' and S.now - (S.manualSaveAt or 0) > 5 then
      S.manualSaveAt = S.now
      result.status = 'manual'
      result.driveFrames = S.driveAcc and accStats(S.driveAcc) or nil
      local veh = getPlayerVehicle(0)
      if veh then
        local p = veh:getPosition()
        S.trace = S.trace or {}
        table.insert(S.trace, {math.floor(S.now), math.floor(p.x), math.floor(p.y), math.floor(p.z * 10) / 10,
                               math.floor(veh:getVelocity():length() * 10) / 10, countTiles()})
        if #S.trace > 4000 then table.remove(S.trace, 1) end
        result.trace = S.trace
      end
      saveResult()
    end
    return
  end
  -- teleports (test.hops: {lat, lon, stage}): land again from 'driving', or mid-descent from
  -- 'spawning'/'warmup', as a player does from the picker; each hop's descent time is reported
  if test.hops and S.testLanded then
    local done = S.hop or 0
    local last = result.hops and result.hops[done]
    if last and not last.landedAfter and S.state == 'driving' then
      last.landedAfter = S.now - last.at
      saveResult()
    end
    if done < #test.hops then
      local h = test.hops[done + 1]
      local stage = h[3] or 'driving'
      if S.state == stage and S.now - S.phaseAt > (stage == 'driving' and 3 or 1) then
        S.hop = done + 1
        result.hops = result.hops or {}
        table.insert(result.hops, {n = S.hop, lat = h[1], lon = h[2], from = S.state, at = S.now})
        S.pickerOpen = true
        goTo(h[1], h[2], 15)
        land()
        saveResult()
      end
      return
    end
    if last and not last.landedAfter then return end
  end
  if S.state == 'pick' and not S.testPicked and (mapTexN > 0 or test.skipMap) and t > 3 then
    shot('1-picker')
    goTo(test.lat, test.lon, 15)
    S.testPicked, S.phaseAt = S.now, S.now
  elseif S.state == 'pick' and S.testPicked and not S.testLanded and (test.skipMap or mapTexN > 0) and t > 2 then
    if NATIVE and M.live and not native.at(test.lat, test.lon) then
      if not S.liveArmed then
        shot('2-marker')
        M.live.request(test.lat, test.lon)
        S.liveArmed = true
        S.liveTest = true
      end
    else
      shot('2-marker')
      S.liveArmed = false
      S.testLanded = true
      land()
    end
  elseif S.state == 'driving' and not S.testDriving and S.now - S.phaseAt > 4 then
    local veh = getPlayerVehicle(0)
    local p = veh:getPosition()
    result.vehicleSettled = {p.x, p.y, p.z}
    local dir = veh:getDirectionVector()
    local yaw = S.landing.spawn.yaw
    -- the car's heading against the spawn's road direction (forward: sin, cos of yaw)
    result.spawnHeading = {dir.x, dir.y, math.sin(yaw), math.cos(yaw)}
    local hl = math.sqrt(dir.x ^ 2 + dir.y ^ 2) + 1e-9
    result.spawnHeadingErrorDeg = math.deg(math.acos(math.max(-1, math.min(1, (dir.x * math.sin(yaw) + dir.y * math.cos(yaw)) / hl))))
    -- a first-run dialog over the game pauses the simulation (fast-game-02 stood still under one)
    local okR, cur = pcall(function() return extensions.ui_router.getCurrent() end)
    result.uiRoute = okR and cur and cur.request and cur.request.name or nil
    local okP, paused = pcall(function() return simTimeAuthority.getPause() end)
    result.simPaused = okP and paused or nil
    shot('4-landed')
    -- the game's own weather and time controls need the level's TimeOfDay/Precipitation/CloudLayer
    local okE, env = pcall(function() return core_environment.getState() end)
    if okE and env then
      result.env = {time = env.time, cloudCover = env.cloudCover, numOfDrops = env.numOfDrops, fogDensity = env.fogDensity}
    end
    if test.rain then
      pcall(function() core_environment.setState({numOfDrops = test.rain, cloudCover = 0.9}) end)
      local okR2, env2 = pcall(function() return core_environment.getState() end)
      if okR2 and env2 then result.envRain = {numOfDrops = env2.numOfDrops, cloudCover = env2.cloudCover} end
    end
    -- showcase shots: the hour of the light (the game's 0..1, 0 noon), after the pack's own
    if test.tod then pcall(function() core_environment.setTimeOfDay({time = test.tod}) end) end
    if test.fog then
      pcall(function()
        local info = scenetree.findObject('theLevelInfo')
        info:setField('fogDensity', 0, tostring(test.fog))
        info:postApply()
      end)
    end
    if test.traffic then setTraffic(test.traffic, test.trafficKind) end
    if test.flowReal then S.flowReal = test.flowReal end
    if test.flow then
      M.flowSet(test.flow)
      -- the pool spawn is a one-time wait at switch-on (result.flow.handoffSpawns), not a drive frame
      if S.driveAcc then S.driveAcc = newAcc(); S.driveAcc.skip = 2 end
    end
    if test.walkBodies then S.walkBodies = test.walkBodies end
    if test.walkers then
      M.walkersSet(test.walkers)
      if S.driveAcc then S.driveAcc = newAcc(); S.driveAcc.skip = 2 end
    end
    if test.recordDrive then
      -- the drive itself is the clip: no game HUD, the driver records until 'stop'
      pcall(function() extensions.ui_visibility.setCef(false) end)
      jsonWriteFile('e2r-rec.json', {rec = 'start', clip = 'drive'}, false)
    end
    S.testDriving, S.frames = S.now, {}
    if test.route then
      local ok, route = pcall(jsonReadFile, test.route)
      -- a native route is lat/lon (geo); the region's own projection puts it in the game's frame
      if ok and route and NATIVE and route.geo then
        route.points = {}
        for _, g in ipairs(route.geo) do
          local x, y = native.localPoint(g[1], g[2])
          if x then route.points[#route.points + 1] = {x, y, 0} end
        end
        local length = 0
        for k = 2, #route.points do
          local a, b = route.points[k - 1], route.points[k]
          length = length + math.sqrt((b[1] - a[1]) ^ 2 + (b[2] - a[2]) ^ 2)
        end
        route.length = length
      end
      if ok and route then
        if test.replay then
          S.replay = {points = route.points, idx = 1, along = 0, distance = 0, speed = test.speed or 83.333}
          result.replay = true
          result.deadlineMisses = {}
          commands.setFreeCamera()
        else
          autopilotStart(route, test.speed)
        end
        result.route = {points = #route.points, length = route.length}
      end
    else
      veh:queueLuaCommand("input.event('throttle', 0.4, 2)")
    end
    S.trace, S.nextShotKm, S.lowestZ = {}, 2, math.huge
  elseif S.testDriving and not S.testDone then
    local veh = getPlayerVehicle(0)
    local p = veh:getPosition()
    -- straight drive: horizontal distance actually covered by the car
    if not S.replay then
      if S.lastP then S.travelled = (S.travelled or 0) + math.sqrt((p.x - S.lastP.x) ^ 2 + (p.y - S.lastP.y) ^ 2) end
      S.lastP = vec3(p.x, p.y, p.z)
    end
    if AP and AP.waiting then result.waitSeconds = (result.waitSeconds or 0) + (S.dt or 0) end
    if S.now - (S.traceAt or 0) > 1 then
      S.traceAt = S.now
      local loaded, loading = countTiles()
      -- the replay's trace is the synthetic pose, not the parked car
      local tp, speed = p, veh:getVelocity():length()
      if S.replayPose then tp, speed = S.replayPose.p, S.replayPose.v:length() end
      table.insert(S.trace, {math.floor(S.now), math.floor(tp.x), math.floor(tp.y), math.floor(tp.z * 10) / 10,
                             math.floor(speed * 10) / 10, loaded, loading, AP and math.floor(AP.travelled) or math.floor(S.travelled or 0),
                             AP and AP.offRoute and math.floor(AP.offRoute) or -1, AP and AP.waiting and AP.aheadKey or '',
                             AP and AP.idx or 0})
      if #S.trace > 4000 then table.remove(S.trace, 1) end
      result.trace = S.trace
      if test.traffic and gameplay_traffic then
        -- how many AI cars there are, how many move, the nearest one
        local n, moving, nearest, cars = 0, 0, math.huge, {}
        for _, id in ipairs(gameplay_traffic.getTrafficList() or {}) do
          local o = be:getObjectByID(id)
          if o then
            n = n + 1
            local v, at = o:getVelocity(), o:getPosition()
            if v:length() > 2 then moving = moving + 1 end
            nearest = math.min(nearest, (at - p):length())
            cars[n] = {x = at.x, y = at.y, vx = v.x, vy = v.y}
          end
        end
        if M.signals then
          result.signalWatch = result.signalWatch or {}
          M.signals.watch(cars, result.signalWatch)
        end
        result.trafficTrace = result.trafficTrace or {}
        table.insert(result.trafficTrace, {math.floor(S.now), n, moving, nearest < math.huge and math.floor(nearest) or -1})
        result.trafficMovingMax = math.max(result.trafficMovingMax or 0, moving)
      end
      result.driveFrames = accStats(S.driveAcc)
      if not S.replay and p.z < (S.lowestZ or math.huge) then S.lowestZ = p.z; result.lowestZ = p.z end
      -- a fall is a drop faster than any road: Kyiv's descent to Podil loses 50 m over a
      -- minute and used to fail the old "lowest point 30 m under the landing" check
      if not S.replay and S.traceZ and S.traceZ - p.z > 10 then
        result.fellAt = result.fellAt or {math.floor(S.now), math.floor(S.traceZ), math.floor(p.z)}
      end
      S.traceZ = p.z
      saveResult()
    end
    if AP and not test.recordDrive and AP.travelled / 1000 >= S.nextShotKm then   -- a shot stalls a recorded frame
      shot(string.format('6-route-%02dkm', S.nextShotKm))
      S.nextShotKm = S.nextShotKm + 2
    end
    local limit = test.driveSeconds or 8
    if (AP and (AP.done or S.now - S.testDriving > limit)) or (not AP and S.now - S.testDriving > limit) then
      veh:queueLuaCommand("input.event('throttle', 0, 2) input.event('brake', 1, 2)")
      -- below 2 m/s the brake is let go and the parking brake holds (S.parkAfter): the arcade
      -- gearbox engages reverse when the brake is held at a standstill, and the car backed away
      -- into a field (out/all-11) while the gallery framed where it had stopped
      S.parkAfter = true
      result.vehicleAfterDrive = {p.x, p.y, p.z, veh:getVelocity():length()}
      result.driveFrames = accStats(S.driveAcc)
      result.travelledM = AP and AP.travelled or S.travelled or 0
      if AP then result.routeDone = AP.done or false end
      if test.recordDrive then jsonWriteFile('e2r-rec.json', {rec = 'stop', clip = 'drive'}, false) end
      shot('5-driving')
      -- 'passed' only when every gate holds; finishing the timer alone is not a result
      local f = {}
      if result.uiRoute and result.uiRoute ~= 'play' then table.insert(f, 'ui_route_' .. tostring(result.uiRoute)) end
      if result.simPaused then table.insert(f, 'sim_paused') end
      if S.replay then
        if #(result.deadlineMisses or {}) > 0 then table.insert(f, 'deadline_misses') end
        local want = (S.replay.speed or 0) * limit * 0.95
        if (result.replayDistanceM or 0) < want then table.insert(f, 'replay_short') end
      else
        if result.travelledM < (test.minDistance or 20) then table.insert(f, 'not_moved') end
        if (result.spawnHeadingErrorDeg or 0) > 20 then table.insert(f, 'spawn_heading') end
        if result.fellAt then table.insert(f, 'fell') end
        if AP and (AP.assists or 0) > 0 then table.insert(f, 'assists') end
        if (result.waitSeconds or 0) > 0 then table.insert(f, 'waited_for_tiles') end
      end
      if result.driveFrames.over100 > 0 then table.insert(f, 'frame_over_100ms') end
      if (result.errors or 0) > 0 then table.insert(f, 'spawn_errors') end
      result.failures = f
      AP = nil
      S.testDone = S.now
    end
  elseif S.testDone and not S.overviewShot and S.now - S.testDone > 0.5 then
    -- a view over the street from 60 m: the look of the city, not just the road under the car
    local veh = getPlayerVehicle(0)
    local p, d = veh:getPosition(), veh:getDirectionVector()
    local f = vec3(d.x, d.y, 0):normalized()
    local cam = vec3(p.x - f.x * 70, p.y - f.y * 70, p.z + 60)
    local q = quatFromDir(vec3(p.x + f.x * 80, p.y + f.y * 80, p.z) - cam, vec3(0, 0, 1))
    commands.setFreeCamera()
    core_camera.setPosRot(0, cam.x, cam.y, cam.z, q.x, q.y, q.z, q.w)
    S.overviewShot = S.now
  elseif S.overviewShot and not S.overviewTaken and S.now - S.overviewShot > 1.5 then
    shot('6-overview')
    S.overviewTaken = S.now
    S.packQueue = test.packs and S.packs and {'toon', 'model', 'synth', 'real'} or nil
  elseif S.packQueue and #S.packQueue > 0 and S.now - S.overviewTaken > 1.5 then
    -- the same view in every pack (test.packs), then back to the default
    local name = table.remove(S.packQueue, 1)
    applyPack(name)
    S.overviewTaken = S.now
    if name ~= 'real' then S.packShot = name end
    if name == 'synth' and S.sunCfg then
      -- look toward the sun from where the overview camera is
      local okC, cam = pcall(function() return core_camera.getPosition() end)
      if okC and cam then
        local a = math.rad(S.sunCfg.azimuth)
        local q = quatFromDir(vec3(math.sin(a), math.cos(a), -0.12), vec3(0, 0, 1))
        core_camera.setPosRot(0, cam.x, cam.y, cam.z, q.x, q.y, q.z, q.w)
      end
    end
  elseif S.packShot and S.now - S.overviewTaken > 1 then
    shot('7-pack-' .. S.packShot)
    S.packShot = nil
  elseif test.gallery and S.overviewTaken and not S.galleryDone and not (S.packQueue and #S.packQueue > 0) and not S.packShot
      and S.now - S.overviewTaken > (S.gallery and 1 or (test.galleryWait or 1)) then
    -- fixed views round the car for before/after comparisons of the look (test.gallery)
    if not S.gallery then
      local veh = getPlayerVehicle(0)
      local p, d = veh:getPosition(), veh:getDirectionVector()
      local f = vec3(d.x, d.y, 0):normalized()
      local r = vec3(f.y, -f.x, 0)
      local function at(back, side, up) return vec3(p.x - f.x * back + r.x * side, p.y - f.y * back + r.y * side, p.z + up) end
      S.gallery = test.onlyViews and {} or {
        {'g1-street', at(7, 0, 1.9), at(-45, 0, 1.2)},
        {'g2-left', at(0, -1.5, 1.7), at(-18, -30, 7)},
        {'g3-right', at(0, 1.5, 1.7), at(-18, 30, 7)},
        {'g4-low', at(45, 8, 22), at(-60, 0, 0)},
        {'g5-high', at(220, 30, 140), at(-180, 0, 0)},
      }
      for _, v in ipairs(test.views or {}) do
        local cam, look = v.cam, v.at
        -- a view by lat/lon (camGeo/atGeo: lat, lon, z in the game's frame) goes through the region's projection
        if v.camGeo and v.atGeo and NATIVE then
          local cx, cy = native.localPoint(v.camGeo[1], v.camGeo[2])
          local tx, ty = native.localPoint(v.atGeo[1], v.atGeo[2])
          cam, look = cx and {cx, cy, v.camGeo[3]}, tx and {tx, ty, v.atGeo[3]}
        end
        if cam and look then
          table.insert(S.gallery, {'v-' .. v.name, vec3(cam[1], cam[2], cam[3]), vec3(look[1], look[2], look[3]), v.camAgl, v.atAgl,
            fov = v.fov})
        end
      end
      S.galleryIdx, S.galleryAt, S.galleryPrefix = 0, S.now - 10, ''
      -- test.packGallery: each view in every pack before the camera moves on. A far view
      -- reloads the place round the camera (minutes at OASIS); a pack switch reloads only
      -- materials, so the packs are the inner loop.
      S.galleryPacks = {}
      if test.packGallery and #test.packGallery > 0 then
        local views = S.gallery
        S.gallery = {}
        for _, v in ipairs(views) do
          for _, name in ipairs(test.packGallery) do table.insert(S.gallery, {v[1], pack = name, view = v}) end
        end
      end
      -- the game's HUD (dashboard, camera help) off for the pictures
      pcall(function() extensions.ui_visibility.setCef(false) end)
    end
    -- test.viewSettle: a far view moves the streaming focus to the camera, so the shot waits
    -- until nothing has loaded for 3 s (at most viewSettle s)
    local ready = S.galleryPending and S.now - S.galleryAt > 1.6
    if ready and test.viewSettle then
      local busy, sig = S.settleProbe()
      if busy or sig ~= S.settleSig or S.settleFor ~= S.galleryPending then
        S.settleSig, S.settleAt, S.settleFor = sig, S.now, S.galleryPending
      end
      local waited = S.now - S.galleryAt
      ready = (waited > 4 and S.now - S.settleAt > 3) or waited > test.viewSettle
      -- heights over the game's own surface (camAgl/atAgl): known only once the ground is built
      local v = S.galleryView
      if ready and v and (v[4] or v[5]) and not v.fixed then
        local function surface(p)
          local okHit, hit = pcall(Engine.castRay, vec3(p.x, p.y, p.z + 3000), vec3(p.x, p.y, p.z - 3000), true, true)
          return okHit and hit and hit.pt and hit.pt.z
        end
        local zc, zt = v[4] and surface(v[2]), v[5] and surface(v[3])
        if zc then v[2] = vec3(v[2].x, v[2].y, zc + v[4]) end
        if zt then v[3] = vec3(v[3].x, v[3].y, zt + v[5]) end
        v.fixed = true
        local q = quatFromDir(v[3] - v[2], vec3(0, 0, 1))
        core_camera.setPosRot(0, v[2].x, v[2].y, v[2].z, q.x, q.y, q.z, q.w)
        S.galleryAt, S.settleAt, ready = S.now - 2.5, S.now - 2, false
      end
      if ready then
        result.settle = result.settle or {}
        result.settle[S.galleryPending] = {math.floor(waited * 10) / 10, busy, sig}
      end
    end
    if ready then
      shot(S.galleryPending)
      S.galleryPending = nil
      S.galleryAt = S.now
    elseif not S.galleryPending and S.now - S.galleryAt > 0.3 then
      S.galleryIdx = S.galleryIdx + 1
      local v = S.gallery[S.galleryIdx]
      if not v and #S.galleryPacks > 0 then
        local name = table.remove(S.galleryPacks, 1)
        applyPack(name)
        S.galleryPrefix, S.galleryIdx, S.galleryAt = name .. '-', 0, S.now + 3
      elseif not v then
        S.galleryDone = true
        pcall(function() extensions.ui_visibility.setCef(true) end)
        S.overviewTaken = S.now - 2
      else
        -- the view itself (its heights corrected once, kept for the next packs)
        local view, switched = v.view or v, false
        if v.pack and S.pack ~= v.pack then applyPack(v.pack); switched = true end
        local q = quatFromDir(view[3] - view[2], vec3(0, 0, 1))
        commands.setFreeCamera()
        core_camera.setPosRot(0, view[2].x, view[2].y, view[2].z, q.x, q.y, q.z, q.w)
        -- a view's own lens (a photo to match); the others keep the camera's own
        S.galleryFov0 = S.galleryFov0 or core_camera.getFovDeg()
        pcall(core_camera.setFOV, 0, view.fov or S.galleryFov0)
        S.galleryPending = (v.pack and v.pack .. '-' or S.galleryPrefix) .. v[1]
        S.galleryAt, S.galleryView = S.now + (switched and 2.5 or 0), view
      end
    end
  elseif test.flight and S.overviewTaken and not S.flightDone and (not test.gallery or S.galleryDone)
      and not (S.packQueue and #S.packQueue > 0) and not S.packShot then
    -- test.flight: a camera flight through keys (lat, lon, z in the game's frame) on a Catmull-Rom
    -- curve at test.flight.speed m/s, eased at both ends. It waits at the first key until the
    -- place has loaded; e2r-rec.json tells the driver when to record.
    local F = S.flight
    if not F then
      local pts, looks = {}, {}
      for _, k in ipairs(test.flight.keys or {}) do
        local cx, cy = native.localPoint(k.cam[1], k.cam[2])
        local tx, ty = native.localPoint(k.at[1], k.at[2])
        if cx and tx then pts[#pts + 1], looks[#looks + 1] = vec3(cx, cy, k.cam[3]), vec3(tx, ty, k.at[3]) end
      end
      local n, samples, length = #pts, {}, 0
      local function cr(t, i, u)
        local p0, p1, p2, p3 = t[math.max(1, i - 1)], t[i], t[math.min(n, i + 1)], t[math.min(n, i + 2)]
        return (p1 * 2 + (p2 - p0) * u + (p0 * 2 - p1 * 5 + p2 * 4 - p3) * (u * u) + (p3 - p0 + (p1 - p2) * 3) * (u * u * u)) * 0.5
      end
      for i = 1, n - 1 do
        for k = 0, (i == n - 1) and 40 or 39 do
          local pos = cr(pts, i, k / 40)
          if #samples > 0 then length = length + (pos - samples[#samples][1]):length() end
          samples[#samples + 1] = {pos, cr(looks, i, k / 40), length}
        end
      end
      F = {samples = samples, length = length, s = 0, idx = 1, at = S.now, phase = n >= 2 and 'settle' or 'done'}
      S.flight = F
      result.flight = {keys = n, length = math.floor(length)}
      commands.setFreeCamera()
      pcall(function() extensions.ui_visibility.setCef(false) end)
    end
    local function place(sample)
      local q = quatFromDir(sample[2] - sample[1], vec3(0, 0, 1))
      core_camera.setPosRot(0, sample[1].x, sample[1].y, sample[1].z, q.x, q.y, q.z, q.w)
    end
    if F.phase == 'settle' then
      place(F.samples[1])
      local busy, sig = S.settleProbe()
      if busy or sig ~= F.sig then F.sig, F.quietAt = sig, S.now end
      if (S.now - F.at > 5 and S.now - F.quietAt > 3) or S.now - F.at > (test.flight.settle or 90) then
        result.flight.settleSeconds, result.flight.settled = math.floor(S.now - F.at), sig
        -- test.flight.warmup: one pass at triple speed, unrecorded, so the take flies through cached tiles
        F.rate = (test.flight.warmup and not F.warmed) and 3 or 1
        F.phase, F.at = 'fly', S.now
        if F.rate == 1 then jsonWriteFile('e2r-rec.json', {rec = 'start', clip = test.flight.clip or 'flight'}, false) end
      end
    elseif F.phase == 'fly' then
      -- 2 s of record lead-in and lead-out, then speed eased over the first and last 15 % of the length
      local t, ease = S.now - F.at, math.max(1, F.length * 0.15)
      if t > 2 or F.rate ~= 1 then
        local f = math.max(0.12, math.min(1, F.s / ease, (F.length - F.s) / ease))
        F.s = math.min(F.length, F.s + (test.flight.speed or 30) * F.rate * f * (S.dt or 0))
      end
      local smp = F.samples
      while F.idx < #smp - 1 and smp[F.idx + 1][3] <= F.s do F.idx = F.idx + 1 end
      local a, b = smp[F.idx], smp[F.idx + 1] or smp[F.idx]
      local u = b[3] > a[3] and (F.s - a[3]) / (b[3] - a[3]) or 0
      place({a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u})
      if F.s >= F.length then F.endAt = F.endAt or S.now end
      if F.endAt and F.rate ~= 1 then
        result.flight.warmSeconds = math.floor(S.now - F.at)
        F.warmed, F.s, F.idx, F.endAt, F.phase, F.at = true, 0, 1, nil, 'settle', S.now
      elseif F.endAt and S.now - F.endAt > 2 then
        jsonWriteFile('e2r-rec.json', {rec = 'stop', clip = test.flight.clip or 'flight'}, false)
        result.flight.seconds = math.floor(S.now - F.at)
        F.phase = 'done'
      end
    else
      S.flightDone = true
      pcall(function() extensions.ui_visibility.setCef(true) end)
      S.overviewTaken = S.now - 2
    end
  elseif S.overviewTaken and not (S.packQueue and #S.packQueue > 0) and not S.packShot and S.now - S.overviewTaken > 1
      and (not test.gallery or S.galleryDone) and (not test.flight or S.flightDone) then
    result.status = #result.failures == 0 and 'passed' or 'failed'
    saveResult()
    shutdown(0)
  end
end

local function replayStep(dt)
  local r = S.replay
  if not r then return end
  r.distance = r.distance + r.speed * dt
  local pts = r.points
  while r.idx < #pts do
    local a,b = pts[r.idx],pts[r.idx+1]
    local len = math.sqrt((b[1]-a[1])^2+(b[2]-a[2])^2)
    if r.along+len > r.distance then break end
    r.along = r.along+len
    r.idx = r.idx+1
  end
  if r.idx >= #pts then
    -- turn round and drive the route back (a long soak keeps moving; tiles behind get revisited)
    result.replayDone = true
    result.replayLaps = (result.replayLaps or 0) + 1
    local back = {}
    for k = #pts, 1, -1 do back[#back + 1] = pts[k] end
    r.points, r.idx, r.along, r.lapStart = back, 1, r.distance, r.distance
    pts = back
  end
  local a,b = pts[r.idx],pts[r.idx+1]
  local d = vec3(b[1]-a[1],b[2]-a[2],0):normalized()
  local p = vec3(a[1],a[2],200)+d*(r.distance-r.along)
  S.replayPose = {p=p,v=d*r.speed}
  local q = quatFromDir(vec3(d.x,d.y,-.45),vec3(0,0,1))
  core_camera.setPosRot(0,p.x-d.x*30,p.y-d.y*30,240,q.x,q.y,q.z,q.w)
  local i,j = tileOf(p.x,p.y)
  local key = i .. '_' .. j
  -- delivered = loaded with collision; a replay crosses tiles without roads (not drivable)
  local here = S.tiles[key]
  if not (here and not here.failed and here.roadComplete and here.collided) and S.lastMiss ~= key then
    local t, st = here, S.status and S.status.stream or {}
    table.insert(result.deadlineMisses,{seconds=S.now-S.testDriving,tile=key,distance=r.distance,
      inGame=t~=nil, road=t and t.roadComplete, collided=t and t.collided, loadSeconds=t and t.startedAt and S.now-t.startedAt,
      left=t and t.left, ready=st.ready and st.ready[key]~=nil, wanted=st.wanted and st.wanted[key],
      failed=st.failed and st.failed[key], queue=#S.queue, collisionAgo=S.now-S.collisionAt, dirty=S.collisionDirty})
    S.lastMiss = key
  end
  -- the scene (buildings, trees, props) of the tile under the car: not spawned yet, or not even generated
  if here and not here.sceneComplete then
    result.sceneMissFrames = (result.sceneMissFrames or 0) + 1
    if S.lastSceneMiss ~= key then
      result.sceneMisses = result.sceneMisses or {}
      table.insert(result.sceneMisses, {seconds = S.now - S.testDriving, tile = key, started = here.sceneStarted or false,
        left = here.sceneLeft})
      S.lastSceneMiss = key
    end
  end
  -- the car's tile has walls the collision does not hold yet (collision.lua: the scene's window)
  if here and here.sceneIds and #here.sceneIds > 0 and not here.sceneCollided then
    result.wallMissFrames = (result.wallMissFrames or 0) + 1
  end
  -- the same for what the camera sees: tiles within 250 m of the car and the tile 400 m ahead
  local size = S.stream and S.stream.tile or 500
  local seen, bare = {}, nil
  for _, q in ipairs({{p.x, p.y, 250}, {p.x + d.x * 400, p.y + d.y * 400, 0}}) do
    for ti = math.floor((q[1] - q[3]) / size), math.floor((q[1] + q[3]) / size) do
      for tj = math.floor((q[2] - q[3]) / size), math.floor((q[2] + q[3]) / size) do
        local k = ti .. '_' .. tj
        local t = S.tiles[k]
        if not seen[k] and not (t and (t.sceneComplete or t.failed)) then bare = bare or k end
        seen[k] = true
      end
    end
  end
  if bare then
    result.sceneViewMissFrames = (result.sceneViewMissFrames or 0) + 1
    result.sceneViewMissTiles = result.sceneViewMissTiles or {}
    if not result.sceneViewMissTiles[bare] then result.sceneViewMissTiles[bare] = math.floor((S.now - S.testDriving) * 10) / 10 end
  end
  result.replayDistanceM = r.distance
end

-- Where a frame's Lua time goes (automation report): sums and maxima per part, and the Lua heap
-- growth between frames (garbage the collector must walk later).
local function profAdd(part, ms, kb)
  local P = S.prof
  if not P then P = {sum = {}, max = {}, kb = {}, frames = 0, kbUp = 0, collections = 0}; S.prof = P end
  -- this frame's parts, for a hitch record (onUpdate reads them at the start of the next frame)
  local F = S.frameParts
  if not F then F = {}; S.frameParts = F end
  F[part] = (F[part] or 0) + ms
  P.sum[part] = (P.sum[part] or 0) + ms
  if ms > (P.max[part] or 0) then P.max[part] = ms end
  if kb and kb > 0 then P.kb[part] = (P.kb[part] or 0) + kb end
end

function M.onUpdate(dtReal, dtSim)
  local ours = inOurLevel()
  local heapKb = M.gc.count()   -- with the previous frame's: a hitch that swept the heap shows it
  M.gc.step(ours, dtReal, S.state == 'generating' or S.state == 'warmup' or S.state == 'spawning')
  if not ours then
    S.state = 'off'
    return
  end
  S.now, S.dt = S.now + dtReal, dtReal
  -- the simulation's own step: 0 while paused, a fraction of dtReal in slow motion
  S.dtSim = dtSim or dtReal
  S.forestTimer = S.forestTimer or hptimer()
  S.forestTimer:stopAndReset()
  -- behind the gate a commit is one of the frame's steps (below), not a change of its own
  if not S.gate then forestCommit() end
  profAdd('forest', S.forestTimer:stop())
  profAdd('gc', M.gc.paceMs or 0)   -- the collector's slice of the frame (gc.lua M.pace)
  local frameMs = frameTimer:stopAndReset()
  table.insert(S.frames, frameMs)
  if S.state == 'driving' and M.paceOn ~= false and not (test and test.pace == false) then
    S.gate = S.gate or M.pace.newGate()
    S.gate:beginFrame(frameMs, (S.dtSim or 0) == 0)
  else
    S.gate = nil
  end
  S.recentAt = (S.recentAt or 0) % 240 + 1        -- the widget's FPS: the last 240 frames
  S.recent = S.recent or {}
  S.recent[S.recentAt] = frameMs
  if S.driveAcc and S.state == 'driving' then accFrame(S.driveAcc, frameMs, S.now) end
  if frameMs > 300 and S.stream then
    result.hitches = result.hitches or {}
    -- {s, ms, state, heap MB before the frame, after it, {part = ms} of the frame's Lua over 20 ms}
    if #result.hitches < 60 then
      local parts = {}
      for k, v in pairs(S.frameParts or {}) do if v > 20 then parts[k] = math.floor(v) end end
      table.insert(result.hitches, {math.floor(S.now), math.floor(frameMs), S.state,
        math.floor((S.heapKb or heapKb) / 1024), math.floor(heapKb / 1024), parts})
    end
  end
  -- (emptied, not made anew: no table of garbage a frame)
  for k in pairs(S.frameParts or {}) do S.frameParts[k] = nil end
  S.heapKb = heapKb
  if #S.frames > 20000 then S.frames = {} end
  if S.state == 'off' then
    if worldReadyState < 2 or not getPlayerVehicle(0) then return end
    S.state, S.phaseAt, S.viewDirty = 'pick', S.now, true
    -- request numbers start from the clock so a status.json left by an earlier session never matches
    S.seq = os.time() * 100
    commands.setFreeCamera()
    core_camera.setPosRot(0, -3000, -60, 40, 0, 0, 0, 1)
  end
  -- automation only: the driver may write the file after start-up (a new profile's first start
  -- removes unknown files from the user folder, world-test-06)
  if not test and S.state == 'pick' and S.now - (S.testCheckAt or -1) > 1 then
    S.testCheckAt = S.now
    if FS:fileExists('/e2r-world-test.json') then
      test = jsonReadFile('/e2r-world-test.json')
      if test and test.pack then S.pack = test.pack end     -- drive in a pack (applied at the landing)
      pcall(function() local tod = scenetree.tod; if tod then tod.play = false end end)
      result.status = 'picker_open'
      S.phaseAt = S.now
      saveResult()
    end
  end
  -- A frame stuck in Lua (ours or another mod's) for seconds writes its Lua stack to
  -- e2r-hang.txt in the user folder from inside the loop (the LuaJIT profiler samples compiled
  -- code too). Freezes in play were otherwise invisible: the log just stopped.
  S.frameStamp = os.clock()
  -- (started once the automation's test file has had its chance to be read: it sets the interval)
  if not S.watchdog and (test or S.now - (S.phaseAt or S.now) > 3) then
    S.watchdog = true
    local okProfile, profile = pcall(require, 'jit.profile')
    if okProfile and profile then
      local dumps, lastDump = 0, -1
      -- test.sample (automation): where the landing's Lua time goes, by the function on top of
      -- the stack and by its caller, every 5 ms (result.samples; the generator is one 13k-line file)
      profile.start(test and test.sample and 'i5' or 'i200', function(thread)
        local now = os.clock()
        if test and test.sample and S.state ~= 'driving' and S.state ~= 'pick' then
          local hist = S.samples or {top = {}, pair = {}, n = 0}
          S.samples = hist
          local top, pair = profile.dumpstack(thread, 'pl', 1), profile.dumpstack(thread, 'pl < ', 2)
          hist.top[top], hist.pair[pair], hist.n = (hist.top[top] or 0) + 1, (hist.pair[pair] or 0) + 1, hist.n + 1
        end
        if S.frameStamp and now - S.frameStamp > 3 and now - lastDump > 2 and dumps < 30 then
          lastDump, dumps = now, dumps + 1
          local f = io.open('e2r-hang.txt', 'a')
          if f then
            f:write(string.format('stuck %.1f s: %s\n', now - S.frameStamp, profile.dumpstack(thread, 'Fpl < ', 40)))
            f:close()
          end
        end
      end)
    end
  end
  -- an error in the logic must not stop the window from being drawn (it flickered when it did)
  local ok, err = xpcall(M.tick, debug.traceback, dtReal)
  if not ok then
    if S.lastError ~= err then log('E', logTag, err) end
    S.lastError = err
  end
  local wkb, wt = collectgarbage('count'), hptimer()
  drawWindow()
  if not S.bigHook then LIMIT.bigMapHook() end
  if S.bigKey then LIMIT.bigMapKey() end
  if S.bigMap then LIMIT.drawBigMap() end
  -- a setting the widget (or anything else) changed reaches the UI app within POLL_EVERY s
  if M.options then M.options.poll(S.now) end
  if S.prof then profAdd('window', wt:stop(), collectgarbage('count') - wkb) end
  if test then
    S.forestTimer:stopAndReset()
    local ok2, err2 = xpcall(runTest, debug.traceback)
    profAdd('test', S.forestTimer:stop())
    if not ok2 and S.lastError ~= err2 then log('E', logTag, err2); S.lastError = err2 end
  end
end

function M.tick(dt)
  S.pairsFrame = 0
  if NATIVE then
    local kb, t = collectgarbage('count'), hptimer()
    if S.profKb then
      local P = S.prof
      if P then
        P.frames = P.frames + 1
        if kb >= S.profKb then P.kbUp = P.kbUp + kb - S.profKb else P.collections = P.collections + 1 end
      end
    end
    local loading = S.state == 'generating' or S.state == 'warmup' or S.state == 'spawning'
    if test and loading then M.loadEngine(S.state) end
    local owed = loading and (S.state ~= 'spawning' or S.landOwed ~= false)
    native.update(dt, test and test.genBudget or (owed and LIMIT.loadNativeMs) or BUDGET_MS, test and test.genBudget, S.now)
    S.nativeMs = t:stop()
    profAdd('native', S.nativeMs, collectgarbage('count') - kb)
    S.profKb = collectgarbage('count')
  end
  placeSun()
  lightsStep()
  reloadStep()
  if S.precipPending and S.state == 'driving' and S.now - (S.phaseAt or 0) >= 1.5 then showPrecip(S.precipPending) end
  envAgainStep()
  readStatus()
  replayStep(dt)
  if S.state == 'generating' then
    local job = S.status and S.status.job
    if job and job.seq == S.landSeq and job.state == 'ready' then beginArrival(job)
    elseif job and job.seq == S.landSeq and job.state == 'working' and job.early and not (test and test.lateArrival) then
      beginArrival(job, job.early)
    end
  end
  if S.landEarly then M.landFinal() end
  if S.state == 'warmup' and S.now - S.phaseAt > 3 then
    if test then shot('3-descent') end
    result.warmupFrames = frameStats(S.frames)
    M.loadMark('warm')
    dropGroup('E2RWorldWarmup')
    dropGroup('E2RWorldPacks')
    local sp = S.landing.spawn.pos
    -- 3 km under the landing, not 40 m: on a summit 40 m down and 150 m east was the air over
    -- the east face, and a fir, a bus stop and a stone hung there in every view (Mount Whitney)
    for k in ipairs(S.landing.warmShapes or {}) do
      local obj = scenetree.findObject('e2r_shape_' .. k)
      if obj then obj:setPosRot(sp[1] + k % 8, sp[2] + math.floor(k / 8), sp[3] - 3000, 0, 0, 0, 1) end
    end
    S.state, S.frames, S.phaseAt = 'spawning', {}, S.now
  end
  if S.stream and (S.state == 'spawning' or S.state == 'driving') then
    -- which step made a slow frame (result.slow, automation and diagnosis)
    local timer = hptimer()
    -- Behind the gate (driving) one frame in QUIET + 1 at most changes the scene, and then with
    -- one step: the collision rebuild, a band of the far view, a Forest commit, or a burst of the
    -- spawn queue with the graves and the detail stream. Without it every frame does a little.
    local gate = S.gate
    local work = not gate or gate:open()
    local changed = false
    if M.far then
      M.far.gate = gate and function() return work and not changed end or nil
      M.far.changed = false
    end
    writePose()
    local tPose = timer:stopAndReset()
    local kb0 = collectgarbage('count')
    updateTiles()
    if M.far and M.far.changed then changed = true end
    local tTiles = timer:stopAndReset()
    local kb1 = collectgarbage('count')
    -- a frame that rebuilds the collision (up to ~65 ms) spawns no mesh: together with a
    -- createMesh and the render they reached 98 ms (fast-oblast-replay-01)
    local reloaded = work and not changed and updateCollision() or false
    if reloaded then changed = true end
    if gate and work and not changed then
      local before = S.forestCommitAt
      forestCommit()
      if S.forestCommitAt ~= before then changed = true end
    end
    local tColl = timer:stopAndReset()
    local kb2 = collectgarbage('count')
    -- props and scenes land as one 20 ms packet a second; a road the car is about to reach
    -- still spawns on the open gate. An idle slot is yielded so the next change waits.
    if work and not changed and LIMIT.allowSpawn(gate) then
      if gate and not S.urgentRoad then S.burstAt = S.now end
      if stepQueue(gate and LIMIT.burstMs or nil) then changed = true end
      local p, vel = focus()
      -- 60 idle / 180 at speed / 240 when many groups wait (was GRAVE_PER_FRAME); a gated
      -- frame digs for the frames it held
      local graveBudget = (vel and vel:length() >= 15) and 180 or 60
      if S.graves and #S.graves > 8 then graveBudget = math.max(graveBudget, 240) end
      if gate and S.graves and #S.graves > 0 then graveBudget, changed = graveBudget * 3, true end
      digGraves(graveBudget)
      local detailTimer = hptimer()
      getDetailStream():step(p, S.appliedTune or TUNE_DEFAULT, S.now, detailTimer, gate and 3 or 1)
      result.detailMs = detailTimer:stop()
      result.liveGrass, result.liveRocks = detailStream.count.grass, detailStream.count.rock
    end
    if gate and changed then gate:done() end
    if gate then result.gate = gate:report() end
    local tQueue = timer:stopAndReset()
    local kb3 = collectgarbage('count')
    if S.state == 'driving' then
      navStep()
      if M.navigator then M.navigator.step(focus, S.now, lang) end
      M.locationStep()
      if M.signals then M.signals.step(S.now, trafficRunning()) end
      local t0 = timer:stop()
      if S.flow then M.flowStep() end
      local t1 = timer:stop()
      if S.walk then M.walkersStep() end
      local t2 = timer:stop()
      if S.knock then M.knockStep() end
      local t3 = timer:stop()
      profAdd('flow', t1 - t0); profAdd('walk', t2 - t1); profAdd('knock', t3 - t2)
    end
    updateParking()
    local tNav = timer:stopAndReset()
    if tNav > (result.navStepMs or 0) then result.navStepMs = tNav end
    profAdd('pose', tPose); profAdd('tiles', tTiles, kb1 - kb0); profAdd('collision', tColl); profAdd('queue', tQueue, kb3 - kb2)
    profAdd('nav', tNav)
    if tPose + tTiles + tQueue + tColl + (S.nativeMs or 0) > 50 then
      result.slow = result.slow or {}
      if #result.slow < 60 then
        table.insert(result.slow, {math.floor(S.now), math.floor(tPose), math.floor(tTiles), math.floor(tQueue), math.floor(tColl),
                                   S.job and S.job.item and S.job.item.name or '', math.floor(S.nativeMs or 0)})
      end
    end
  end
  if S.state == 'spawning' then
    local sp = S.landing.spawn.pos
    local loaded = countTiles()
    -- the camera stays up until the spawn is chosen (an early arrival may land a tile away)
    cameraOver(CAM_HIGH + (CAM_LOW - CAM_HIGH) * (S.landEarly and 0 or math.min(1, loaded / 4)))
    -- touch down once the landing tile is in and its collision has been rebuilt a while ago
    local buffered = true
    if S.stream.generator then
      local li,lj = tileOf(sp[1],sp[2])
      local landingTile = S.tiles[li .. '_' .. lj]
      if not landingTile or not landingTile.sceneComplete then buffered = false end
      -- whether the generator still owes a tile of the touch-down set (S.landOwed): once it does
      -- not, the frame goes to the spawn queue, not to tiles further out (load-04: 33 tiles built
      -- before the touch-down instead of 11, and the wait grew by 7 s)
      local owed = false
      for x = sp[1]-500, sp[1]+500, 250 do
        for y = sp[2]-500, sp[2]+500, 250 do
          local i,j = tileOf(x,y)
          local t = S.tiles[i .. '_' .. j]
          if not t then owed = true end
          if not t or t.failed or not t.roadComplete or (itemCount(t.manifest) > 0 and not t.collided) then buffered = false end
        end
      end
      S.landOwed = owed or S.landEarly == true
      -- the descent only (the index of a big city's window, before it, takes minutes and is
      -- not the stream's fault); a warning in play, a failed run in automation
      -- why the descent waits (automation report): the tiles round the spawn that hold it back
      if S.now - S.phaseAt > 60 and not result.descentBlocked then
        local blocked, st = {}, S.status and S.status.stream or {}
        for x = sp[1]-500, sp[1]+500, 250 do
          for y = sp[2]-500, sp[2]+500, 250 do
            local i,j = tileOf(x,y)
            local key = i .. '_' .. j
            local t = S.tiles[key]
            if not t or t.failed or not t.roadComplete or (itemCount(t.manifest) > 0 and not t.collided) or not blocked[key] then
              blocked[key] = {inGame = t ~= nil, failed = t and t.failed, road = t and t.roadComplete, scene = t and t.sceneComplete,
                collided = t and t.collided, left = t and t.left, ready = st.ready and st.ready[key] ~= nil,
                wanted = st.wanted and st.wanted[key], nativeFailed = st.failed and st.failed[key]}
            end
          end
        end
        result.descentBlocked = {seconds = S.now - S.phaseAt, landing = li .. '_' .. lj, tiles = blocked, queue = #S.queue,
          collisionDirty = S.collisionDirty, collisionAt = S.collisionAt, now = S.now}
        saveResult()
      end
      if not result.startupFailed and S.now - S.phaseAt > 300 then
        result.startupFailed = true
        S.lastError = 'Descent exceeded 300 seconds'
        if test then result.status = 'failed'; saveResult(); shutdown(1) end
      end
    end
    if not S.landEarly and buffered and tileLoadedAt(sp[1], sp[2], S.landing.offRoad) and S.collisionAt > 0 and S.now - S.collisionAt > 0.2 then
      result.spawnFrames = frameStats(S.frames)
      result.spawnSeconds = S.now - S.phaseAt
      S.frames = {}
      touchDown()
    end
  end
  if S.state == 'driving' and AP then autopilotStep(dt) end
end

-- --- knockable street furniture (knock.lua, docs/KNOCKDOWN.md) -------------------------------------
-- The game side of knock.lua: the Forest item leaves, a pooled TSStatic of the shape takes its place,
-- the struck vehicle gets a velocity change. Created with the first knockable prop the Forest commits.
function M.knockState()
  if S.knock then return S.knock end
  local ks = {K = M.knock.new{enabled = true}, boxes = {}, pool = {}, noBodies = {pool = {}}, callMax = {}}
  local api, at = {}, vec3(0, 0, 0)
  local box = Box3F and Box3F()
  -- the slowest of each game call (result.knockCalls): a stalled step is found by these
  local function slowest(kind, t0)
    local ms = (os.clock() - t0) * 1000
    if ms > (ks.callMax[kind] or 0) then ks.callMax[kind] = ms end
  end
  -- the item at (x, y, z) of kind shape .. '#knock' leaves the Forest (not one a retiring tile queued)
  function api.hide(id, shape, x, y, z)
    local key = shape .. '#knock'
    local d = plantData[key]
    local f = d and forestFor()
    local data = f and f:getData()
    if not data or not box then return false end
    box.minExtents = vec3(x - .3, y - .3, z - 2)
    box.maxExtents = vec3(x + .3, y + .3, z + 6)
    local tb = os.clock()
    local ok, items = pcall(data.getItemsBox, data, box)
    tb = (os.clock() - tb) * 1000
    if tb > (ks.callMax.box or 0) then ks.callMax.box, ks.callMax.items = tb, type(items) == 'table' and #items or -1 end
    if not ok or type(items) ~= 'table' then return false end
    local name, q = d:getName(), S.forestQ and S.forestQ[key]
    for _, item in ipairs(items) do
      local okD, itemData = pcall(item.getData, item)
      local p = item:getPosition()
      if okD and itemData and itemData:getName() == name and (p.x - x) ^ 2 + (p.y - y) ^ 2 < .0025 then
        if q and q.removing[item:getKey()] then return false end
        local tr = os.clock()
        local removed = pcall(data.removeItem, data, item)
        tr = (os.clock() - tr) * 1000
        if tr > (ks.callMax.remove or 0) then ks.callMax.remove, ks.callMax.shape = tr, shape end
        if not removed then return false end
        if q then q.live = math.max(0, (q.live or 0) - 1) end
        result.forestItems = math.max(0, (result.forestItems or 0) - 1)
        -- a lamp's light goes with its pole: lightsStep places the pool again on the next frame
        if shape == LAMP_SHAPE and S.lamps then
          S.lamps[string.format('%d_%d', math.floor(x), math.floor(y))] = nil
          S.lightsAt = -1
        end
        return true
      end
    end
    return false
  end
  -- a TSStatic of the shape: from the pool, or a new one (~11 us once the shape was drawn, p24b)
  function api.take(shape, scale)
    local list = ks.pool[shape]
    local obj = list and list[#list]
    if obj then
      list[#list] = nil
      obj:setHidden(false)
    else
      obj = createObject('TSStatic')
      obj:setField('shapeName', 0, shape)
      obj:setField('collisionType', 0, 'None')
      obj:setField('decalType', 0, 'None')
      obj.useInstanceRenderData = true
      obj.canSave = false
      obj:registerObject('')
      -- (tileGroup empties a group it finds: only for the first one)
      local g = scenetree.findObject('E2R_knock') or tileGroup('E2R_knock', true)
      g:addObject(obj)
    end
    if scale and scale ~= 1 then obj:setScale(vec3(scale, scale, scale)) else obj:setScale(vec3(1, 1, 1)) end
    return obj
  end
  function api.drop(obj, shape)
    local t0 = os.clock()
    local list = ks.pool[shape]
    if not list then list = {}; ks.pool[shape] = list end
    if #list < 64 then
      pcall(function() obj:setHidden(true) end)
      list[#list + 1] = obj
    else
      pcall(function() obj:delete() end)
    end
    slowest('drop', t0)
  end
  -- pcall: a debris object deleted from outside (a group emptied) must not stop the step
  function api.place(obj, x, y, z, qx, qy, qz, qw)
    local t0 = os.clock()
    pcall(obj.setPosRot, obj, x, y, z, qx, qy, qz, qw)
    slowest('place', t0)
  end
  function api.ground(x, y, z)
    at.x, at.y, at.z = x, y, z + 1.5
    local h = be:getSurfaceHeightBelow(at)
    if h and h > -1e6 then return h end
  end
  function api.push(vid, dvx, dvy, dvz)
    local t0 = os.clock()
    local o = be:getObjectByID(vid)
    if o then o:applyClusterVelocityScaleAdd(o:getRefNodeId(), 1, dvx, dvy, dvz) end
    slowest('push', t0)
  end
  function api.clock() return os.clock() * 1000 end
  -- a flier's wall ray: static collision only (buildings, solid Forest items, terrain), two reused
  -- vectors, a number back; the distance, or nil for nothing within len
  local ro, rd = vec3(0, 0, 0), vec3(0, 0, 0)
  if castRayStatic then
    function api.ray(x, y, z, dx, dy, len)
      ro.x, ro.y, ro.z = x, y, z
      rd.x, rd.y, rd.z = dx, dy, 0
      local ok, d = pcall(castRayStatic, ro, rd, len)
      if ok and type(d) == 'number' and d < len then return d end
    end
  end
  -- a slow or still vehicle is listed for knocking only next to a prop
  function ks.slow(x, y) return M.knock.near(ks.K, x, y) end
  ks.api = api
  S.knock = ks
  return ks
end

-- one committed '#knock' item (forestCommit): its transform's own rotation, so the debris matches it
function M.knockRegister(tile, shape, pos, m, scale)
  if S.knockOff and not S.knock then return end
  local ks = M.knockState()
  local q = m:toQuatF()
  M.knock.register(ks.K, tile, shape, pos.x, pos.y, pos.z, q.z, q.w, type(scale) == 'number' and scale or 1)
end

-- automation (earthng/probe/knock_row.lua): one knockable prop planted now as the generator's would be,
-- owned by tile (any table; M.knock.unregisterTile takes it away). Returns its id or nil.
function M.knockPlant(tile, shape, x, y, z, yaw)
  local kind = forestFor() and plantDataFor(shape .. '#knock')
  local data = kind and forestFor():getData()
  if not data then return end
  local m = MatrixF(true)
  m:setFromEuler(vec3(0, 0, yaw or 0))
  m:setPosition(vec3(x, y, z))
  local ok, item = pcall(data.createNewItem, data, kind, m, 1)
  if not ok or not item then return end
  local q = m:toQuatF()
  return M.knock.register(M.knockState().K, tile, shape, x, y, z, q.z, q.w, 1)
end

-- every moving vehicle with physics (player, hand-off cars, the game's traffic, not pedestrian bodies):
-- pedhit.gameHitters, the same garbage-free scan the walkers use, with knock.lua's own state
function M.knockStep()
  local ks = S.knock
  local p = focus()
  if not p then return end
  ks.H = ks.H or {}
  local tg = os.clock()
  local hs = M.pedHit.gameHitters(ks.H, S.walk and S.walk.P or ks.noBodies, ks.boxes, p.x, p.y, ks.slow)
  local slowest = (os.clock() - tg) * 1000
  if slowest > (ks.callMax.hitters or 0) then ks.callMax.hitters = slowest end
  local n = ks.H.n or 0
  for i = 1, n do
    local h = hs[i]
    -- no mass in GE: a car's plan area scaled from a 1500 kg sedan
    h.mass = math.max(600, math.min(30000, 1500 * h.hl * h.hw / 2.1))
  end
  local st = ks.K.stats
  if test and not st.armBy then st.armBy, st.touchBy = {}, {} end
  M.knock.step(ks.K, hs, n, S.now, S.dtSim or S.dt or 1 / 60, ks.api)
  result.knock = st
  result.knockCalls = ks.callMax
  -- automation: who armed and touched props, by vehicle name (player, e2r_flow_real, parked ...)
  if test and S.now - (ks.byAt or -10) > 2 then
    ks.byAt = S.now
    local by, player = {}, be:getPlayerVehicleID(0)
    for _, field in ipairs({'armBy', 'touchBy'}) do
      for id, count in pairs(st[field]) do
        local o = getObjectByID(id)
        local name = id == player and 'player' or (o and (o:getName() ~= '' and o:getName() or o:getJBeamFilename())) or 'gone'
        name = name:gsub('_%d+$', '')
        by[name] = by[name] or {arm = 0, touch = 0}
        by[name][field == 'armBy' and 'arm' or 'touch'] = by[name][field == 'armBy' and 'arm' or 'touch'] + count
      end
    end
    result.knockBy = by
  end
end

-- a new landing or a pack gone: every debris back to the pool (the tiles' retireForest has taken
-- their props already); knocking itself stays as set
function M.knockPark()
  if S.knock then M.knock.clear(S.knock.K, S.knock.api) end
end

-- on (default) or off: off stops knocking for props committed from now on (they are solid again);
-- the ones already planted without collision stay knockable until their tile is rebuilt
function M.knockSet(enabled)
  S.knockOff = not enabled or nil
  result.knockOn = enabled and true or false
end

function M.knockGet() return not S.knockOff end

-- {enabled, registered (props in the hash), active (debris live), flying, lying, knocked (total),
-- recycled, missed, ms (last step), msMax, cap}
function M.knockStatus()
  local K = S.knock and S.knock.K
  local st = K and K.stats or {}
  return {enabled = not S.knockOff, registered = K and M.knock.count(K) or 0, active = st.active or 0,
    flying = st.flying or 0, lying = st.lying or 0, knocked = st.knocked or 0, recycled = st.recycled or 0,
    missed = st.missed or 0, ms = st.ms or 0, msMax = st.msMax or 0, cap = K and K.cap or M.knock.CAP}
end

-- --- settings registry (options.lua) and the game's UI app (docs/INGAME_UI.md) --------------------
-- Every setting the widget shows, as options: read from and applied to the same state the widget
-- uses, so both views show the same value whichever changed it. Values keep their old places in
-- settings/earthng.json (lang and tune by setLang/applyTune, locationOff by the registry).
function M.optionsBind()
  local o = M.options
  if not o then return end
  o.storage = {
    read = function() local ok, cfg = pcall(jsonReadFile, LANG_FILE); return ok and type(cfg) == 'table' and cfg or {} end,
    write = function(cfg) pcall(jsonWriteFile, LANG_FILE, cfg, true) end}
  local function driving() return S.state == 'driving' end
  local function tuneRead(key) return function() return (S.tune or TUNE_DEFAULT)[key] end end
  local function tuneApply(key)
    return function(v)
      ensureTune()
      local parked = S.tune.parkedCars
      if key == 'quality' then
        S.tune = quality.preset(v); S.tune.parkedCars = parked
      elseif key == 'detail' or key == 'distance' then
        local d, r = S.tune.detail, S.tune.distance
        if key == 'detail' then d = v else r = v end
        S.tune = quality.preset(d, r); S.tune.parkedCars = parked
      else
        S.tune[key] = v
      end
      -- the widget's sliders keep their own copies and write them back every frame
      for k, ptr in pairs(tunePtr) do
        if k == 'groundTrees' then ptr[0] = S.tune.groundTrees and true or false
        elseif S.tune[k] ~= nil then ptr[0] = S.tune[k] end
      end
      applyTune()   -- rebuilds the scenery when density changed; saves tune
    end
  end
  o.group{key = 'quality', label = {uk = 'Якість світу', en = 'World quality'}}
  o.group{key = 'traffic', label = {uk = 'Трафік і люди', en = 'Traffic and people'}}
  o.group{key = 'view', label = {uk = 'Інтерфейс і стиль', en = 'Interface and style'}}
  o.group{key = 'advanced', label = {uk = 'Точні налаштування', en = 'Advanced settings'}, collapsed = true}
  o.define{key = 'quality', kind = 'int', min = 0, max = 100, step = 1, group = 'quality',
    label = {uk = 'Якість (Potato - OASIS)', en = 'Quality (Potato - OASIS)'},
    hint = {uk = 'Задає деталізацію і дальність разом', en = 'Sets detail and draw distance together'},
    read = tuneRead('quality'), apply = tuneApply('quality')}
  o.define{key = 'detail', kind = 'int', min = 0, max = 100, step = 1, group = 'quality',
    label = {uk = 'Деталізація', en = 'Detail'},
    hint = {uk = 'Густота дерев, трави й каміння; зміна перебудовує сцену', en = 'Trees, grass and rocks; a change rebuilds the scenery'},
    read = tuneRead('detail'), apply = tuneApply('detail')}
  o.define{key = 'distance', kind = 'int', min = 0, max = 100, step = 1, group = 'quality',
    label = {uk = 'Дальність малювання', en = 'Draw distance'}, read = tuneRead('distance'), apply = tuneApply('distance')}
  for _, t in ipairs({
    {'grassM', 0, 220, 5, 'Дальність трави, м', 'Grass distance, m'},
    {'rockM', 0, 900, 10, 'Дальність каміння, м', 'Rock distance, m'},
    {'nearM', 400, 4000, 50, 'Ближній світ, м', 'Near world, m'},
    {'farM', 800, 8000, 100, 'Далекий світ, м', 'Far world, m'},
    {'maxTrees', 0, 2400, 50, 'Крони на ближній тайл', 'Crowns per near tile'},
    {'maxFarTrees', 0, 1200, 25, 'Крони на далекий тайл', 'Crowns per far tile'},
    {'maxGrass', 0, 4800, 100, 'Щільність трави на тайл', 'Grass density per tile'},
    {'maxRocks', 0, 200, 5, 'Каміння на тайл', 'Rocks per tile'},
    {'grassBudget', 0, 14000, 200, 'Загальний ліміт трави', 'Total grass limit'},
    {'rockBudget', 0, 1600, 50, 'Загальний ліміт каміння', 'Total rock limit'},
    {'forestSpacing', 4, 24, 1, 'Крок лісу, м', 'Forest spacing, m'},
    {'groundSpacing', 4, 30, 1, 'Крок на відкритому ґрунті, м', 'Open-ground spacing, m'}}) do
    o.define{key = t[1], kind = 'int', min = t[2], max = t[3], step = t[4], group = 'advanced',
      label = {uk = t[5], en = t[6]}, read = tuneRead(t[1]), apply = tuneApply(t[1])}
  end
  o.define{key = 'groundTrees', kind = 'bool', group = 'advanced',
    label = {uk = 'Дерева на відкритому ґрунті', en = 'Trees on open ground'},
    read = tuneRead('groundTrees'), apply = tuneApply('groundTrees')}
  -- traffic and people: what runs now (not saved, as in the widget)
  o.define{key = 'trafficKind', kind = 'enum', values = TRAFFIC_KINDS, group = 'traffic',
    label = {uk = 'Трафік: машини', en = 'Traffic: cars'},
    read = function() return S.trafficKind or 'simple' end,
    apply = function(v)
      S.trafficKind = v
      local amount = trafficRunning() and S.trafficAmount or 0
      if amount and amount > 0 then setTraffic(amount, v) end   -- the running traffic respawns with it
    end}
  o.define{key = 'trafficAmount', kind = 'enum', values = TRAFFIC_KINDS.amounts, group = 'traffic',
    label = {uk = 'Трафік (з фізикою)', en = 'Traffic (with physics)'},
    hint = {uk = 'Кожна машина ~1,5 мс кадру', en = 'Each car costs ~1.5 ms of the frame'}, available = driving,
    read = function() return trafficRunning() and (S.trafficAmount or -1) or 0 end,
    apply = function(v) setTraffic(v, S.trafficKind) end}
  o.define{key = 'flow', kind = 'enum', values = TRAFFIC_KINDS.flow, group = 'traffic',
    label = {uk = 'Потік (без фізики)', en = 'Flow (no physics)'}, available = driving,
    read = function() return S.flow and S.flow.F.target or 0 end, apply = function(v) M.flowSet(v) end}
  o.define{key = 'flowReal', kind = 'enum', values = TRAFFIC_KINDS.real, group = 'traffic',
    label = {uk = 'Справжні машини біля гравця', en = 'Real cars round the player'},
    read = function() return S.flowReal or M.handoffSim.SIZE end, apply = function(v) M.flowReal(v) end}
  -- pedestrians: a count (kept while they are off) and on/off; walkersSet(on and count or 0). Saved
  -- as walkers and walkersOn; none saved = off, as before the registry. restore() takes walkersOn
  -- first (it asks for the count kept so far or 200), then the count, which follows while on;
  -- before the drive walkersSet only remembers it. walkersSet is cheap: the slider applies live.
  local function asked() return (M.walkersGet()) end
  o.define{key = 'walkersOn', kind = 'bool', default = false, group = 'traffic', path = {'walkersOn'},
    label = {uk = 'Пішоходи на тротуарах', en = 'Pedestrians on the sidewalks'},
    read = function() return asked() > 0 end,
    apply = function(v)
      if not v then
        local n = asked()
        if n > 0 then S.walkCount = n end   -- a count asked elsewhere (test_world --walkers) is kept
        M.walkersSet(0)
      else
        M.walkersSet(S.walkCount or 200)
      end
    end}
  o.define{key = 'walkers', kind = 'int', min = 0, max = 1000, step = 10, default = 200, group = 'traffic',
    label = {uk = 'Скільки пішоходів', en = 'How many pedestrians'}, path = {'walkers'}, live = true,
    read = function() local n = asked(); if n > 0 then return n end return S.walkCount end,
    apply = function(v)
      S.walkCount = v
      if asked() > 0 then M.walkersSet(v) end
    end,
    -- the asked, walking, room counts as one number: the note changes only when one of them does
    watch = function() local a, w, r = M.walkersGet(); return a * 1e8 + w * 1e4 + r end,
    note = function()
      local a, w, r = M.walkersGet()
      if a == 0 then return nil end
      if not S.walk or S.walk.parked then return {uk = 'З\'являться після висадки', en = 'They come with the drive'} end
      return {uk = string.format('Ходять %d з %d · місця на %d', w, a, r),
        en = string.format('Walking %d of %d · room for %d', w, a, r)}
    end}
  o.define{key = 'knock', kind = 'bool', default = true, group = 'traffic', path = {'knock'},
    label = {uk = 'Збивані об\'єкти', en = 'Knockable props'},
    hint = {uk = 'Для щойно завантажених околиць: вже поставлені лишаються як були',
      en = 'For newly loaded surroundings: props already placed stay as they are'},
    read = function() return M.knockGet() end, apply = function(v) M.knockSet(v) end}
  o.define{key = 'parkedCars', kind = 'enum', values = parking.AMOUNTS, group = 'traffic',
    label = {uk = 'Припарковані машини', en = 'Parked cars'},
    read = function() return S.parkedPick or (S.tune or TUNE_DEFAULT).parkedCars or 0 end,
    apply = function(v) S.parkedPick = v end}   -- updateParking applies and saves it
  -- interface and style
  o.define{key = 'lang', kind = 'enum', group = 'view', label = {uk = 'Мова', en = 'Language'},
    values = {{value = 'uk', label = {uk = 'Українська', en = 'Українська'}}, {value = 'en', label = {uk = 'English', en = 'English'}}},
    read = function() return lang end, apply = function(v) setLang(v); S.viewDirty = true end}
  o.define{key = 'streetLine', kind = 'bool', group = 'view', default = true, path = {'locationOff'},
    label = {uk = 'Рядок з назвою вулиці', en = 'Street name line'},
    encode = function(v) return not v end, decode = function(raw) return not raw end,
    read = function() return not S.locationOff end,
    apply = function(v)
      S.locationOff = not v
      if S.locationShown then S.locationShown[0] = v end
    end}
  o.define{key = 'style', kind = 'enum', group = 'view', label = {uk = 'Стиль світу', en = 'World style'},
    available = function() return S.packs ~= nil end,
    values = function()
      local out = {}
      for i, p in ipairs(PACK_NAMES) do
        out[i] = {value = p[1], label = {uk = PACK_LABELS_UK[p[1]] or p[2] or p[1], en = PACK_LABELS_EN[p[1]] or p[2] or p[1]}}
      end
      return out
    end,
    read = function() return S.pack or 'real' end, apply = function(v) applyPack(v) end}
  o.onChange(function() M.optionsList() end, 'ui')
end

-- the UI app's two calls (bngApi.engineLua): the list now, and a change; both answer with the hook
-- EarthNGOptions carrying options.payload()
function M.optionsList()
  if M.options and guihooks then guihooks.trigger('EarthNGOptions', M.options.payload()) end
end

function M.optionsSet(key, value)
  if not M.options then return end
  local _, changed = M.options.set(key, value, 'ui')   -- (nil, reason) when refused
  if changed ~= true then M.optionsList() end   -- refused or the same: the page shows the value in force
end

function M.onExtensionLoaded()
  setExtensionUnloadMode(M, 'manual')
  loadLang()
  if NATIVE then
    native.refresh()
    local ok, cfg = pcall(jsonReadFile, LANG_FILE)
    S.tune = quality.clamp(ok and type(cfg) == 'table' and cfg.tune or nil)
    S.appliedTune = native.setTune(S.tune)
  end
  if M.options then
    M.optionsBind()
    M.options.restore(nil, true)   -- locationOff (the rest is read above)
    M.optionsList()                -- an open UI app redraws after a Lua reload
  end
  log('I', logTag, 'Earth2Road planet extension loaded')
end

return M
