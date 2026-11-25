-- The game's own minimap (the UI app in a corner of the screen, lua/ge/extensions/ui/apps/minimap)
-- on an EarthNG level. The game draws 200 m across at rest and 350 m at speed: enough for a
-- track, too little to see where a street leads in a real town. Here, without replacing a file
-- of the game:
--
--   scale    the app asks its vehicles module for the scale every frame (drawPlayer's result);
--            that function is wrapped and its answer multiplied by M.zoom (the option
--            'minimapZoom'), so the app's own easing by speed and by walking stays;
--   roads    the app draws a road 2 m wide whatever the scale: under a pixel when zoomed out.
--            Its roads module gets a scale that keeps the line ROAD_PX wide;
--   markers  the points of interest round the car, as the app's own circle markers in their
--            group's colour, through its hook onDrawOnMinimap: those of the installed packs' map
--            data (poiindex.lua: every OSM point the atlas on M knows, before its place is
--            built) and those of the streamed tiles (a pack built before the map data had
--            points has only these); the route's destination with the app's edge pointer.
--
-- Both wraps are put back when the level is left (M.restore) and put on again if the game
-- reloads its modules. A game without these modules (0.37 and older) is left alone.
--
-- Every frame: the markers are drawn from arrays filled a few times a second (M.refresh); no
-- table and no string is made.
local M = {}
local floor, max, min, cos, rad = math.floor, math.max, math.min, math.cos, math.rad

M.ZOOMS = {1, 2, 3, 5}   -- the option's steps: times the game's own scale
M.zoom = 3
M.ROAD_PX = 2.4          -- a road's width on the minimap, px
M.REACH = 1500           -- m round the car the points are taken from
M.EVERY, M.MOVED = .5, 60  -- s, m: the points are taken again after either
M.MOST = 140             -- markers at most
M.CELL = 34              -- px between two markers at the least
M.MINOR = 7              -- priorities over this (a kiosk, a parcel locker) stay off the minimap
M.BASE = .5              -- the game's scale, m a pixel (vehicles.lua scaleSetting)

local wrapped = {}       -- module -> {field, original, wrapper}
local on = false

local function wrap(module, field, make)
  if type(module) ~= 'table' or type(module[field]) ~= 'function' then return end
  local w = wrapped[module]
  if w and module[field] == w.wrapper then return end
  local original = module[field]
  w = {field = field, original = original}
  w.wrapper = make(original)
  module[field] = w.wrapper
  wrapped[module] = w
end

-- put the wraps on (again, when the game has reloaded a module)
function M.install()
  on = true
  wrap(rawget(_G, 'ui_apps_minimap_vehicles'), 'drawPlayer', function(original)
    return function(...)
      local scale = original(...)
      if on and type(scale) == 'number' then return scale * M.zoom end
      return scale
    end
  end)
  wrap(rawget(_G, 'ui_apps_minimap_roads'), 'drawRoads', function(original)
    return function(p, radius, td, debugSettings, camPos, scale, dpi, ...)
      if on and type(scale) == 'number' and scale > 0 then
        -- the app's line is 2 / scale px wide: a smaller scale here is a wider line only
        scale = min(scale, 2 / M.ROAD_PX)
      end
      return original(p, radius, td, debugSettings, camPos, scale, dpi, ...)
    end
  end)
end

-- the game's own functions back in their places
function M.restore()
  on = false
  for module, w in pairs(wrapped) do
    if module[w.field] == w.wrapper then module[w.field] = w.original end
    wrapped[module] = nil
  end
end

function M.active() return on end

function M.setZoom(value)
  value = tonumber(value) or M.zoom
  M.zoom = max(1, min(8, value))
  M.at = nil   -- the markers' spacing follows the scale
end

-- --- markers ---------------------------------------------------------------------------------
local count = 0
local mx, my, mr, mc = {}, {}, {}, {}     -- world x, y, radius px, colour
local colours, white
local occupied, stamp = {}, 0
local enabled, enabledKey = {}, nil
-- the candidates of a refresh: world x, y, priority, group
local found = {n = 0, x = {}, y = {}, level = {}, group = {}}
local toLocal
local function add(e, i, level)
  local x, y = toLocal(e.lat[i], e.lon[i])
  if not x then return end
  local style = M.pins.STYLE[M.index.PARENT[e.cat[i]]]
  local n = found.n + 1
  found.n, found.x[n], found.y[n], found.level[n], found.group[n] = n, x, y, level, style and style.group
end
M.markers = {x = mx, y = my, r = mr, colour = mc, count = function() return count end}

-- the categories shown: those with a look, not switched off on the atlas, not too minor
local function refreshEnabled(env)
  local index, pins = env.index, env.pins
  local key = index.revision * 4096 + #index.CATS + (env.filterRev or 0) * 1e7
  if key == enabledKey then return end
  enabledKey = key
  for k in pairs(enabled) do enabled[k] = nil end
  local off = env.off or {}
  for id, name in ipairs(index.CATS) do
    local parent = index.PARENT[id]
    local style = parent and pins.STYLE[parent]
    if style and not off[name] and not off[parent] and (index.PRIORITY[id] or 9) <= M.MINOR then enabled[id] = true end
  end
end

-- Take the points round the car again. env: index (poiindex), pins, toGeo(x, y) -> lat, lon,
-- toLocal(lat, lon) -> x, y, off (the atlas's switched-off categories), filterRev, colour(r, g, b)
-- -> the game's colour.
function M.refresh(now, x, y, env)
  if M.at and now - M.at < M.EVERY and (x - M.atX) ^ 2 + (y - M.atY) ^ 2 < M.MOVED ^ 2 then return false end
  local index = env.index
  if not index or not index.collect then return false end
  M.index, M.pins, toLocal = index, env.pins, env.toLocal
  M.at, M.atX, M.atY = now, x, y
  local lat, lon = env.toGeo(x, y)
  if not lat then count = 0; return false end
  refreshEnabled(env)
  if not colours then
    colours, white = {}, env.colour(255, 255, 255)
    for group, rgb in pairs(env.pins.GROUP) do
      colours[group] = env.colour(floor(rgb[1] * 255 + .5), floor(rgb[2] * 255 + .5), floor(rgb[3] * 255 + .5))
    end
  end
  local dLat = M.REACH / 110574
  local dLon = M.REACH / (111320 * max(.05, cos(rad(lat))))
  -- metres between two markers: CELL px at the scale the minimap has at speed
  local cell = M.CELL * M.BASE * M.zoom * 1.4
  local perCell = max(1, min(400, math.ceil((index.GRID * 110574 / cell) ^ 2)))
  found.n = 0
  index.collect(lon - dLon, lat - dLat, lon + dLon, lat + dLat, perCell, enabled, add, nil, nil)
  local indexed = found.n
  -- the streamed tiles' own points (pins.lua draw reads the same records): a pin by its
  -- category, a network's point as the service or the shop it is
  local off, STYLE = env.off or {}, env.pins.STYLE
  for _, tile in pairs(env.tiles or {}) do
    local list = tile.brandPOIs
    for k = 1, list and #list or 0 do
      local poi = list[k]
      local cat = poi.kind == 'pin' and poi.cat or poi.kind == 'fuel' and 'service_map' or 'shop_map'
      local style = STYLE[cat]
      local level = poi.kind == 'pin' and style and style.priority or 3
      if style and poi.x and level <= M.MINOR and not off[cat] then
        local n = found.n + 1
        found.n, found.x[n], found.y[n], found.level[n], found.group[n] = n, poi.x, poi.y, level, style.group
      end
    end
  end
  -- the best first: by priority; one marker a square of `cell` metres
  stamp = stamp + 1
  local n = 0
  for level = 1, M.MINOR do
    for k = 1, found.n do
      if found.level[k] == level and n < M.MOST then
        local px, py = found.x[k], found.y[k]
        if (px - x) ^ 2 + (py - y) ^ 2 <= M.REACH ^ 2 then
          local key = floor(px / cell) * 65536 + floor(py / cell)
          if occupied[key] ~= stamp then
            occupied[key] = stamp
            n = n + 1
            mx[n], my[n] = px, py
            mr[n] = level <= 2 and 6.5 or level <= 4 and 5.5 or 4.5
            mc[n] = colours[found.group[k]] or white
          end
        end
      end
    end
  end
  count = n
  M.stats = {found = found.n, indexed = indexed, shown = n}
  return true
end

function M.clear() count, M.at = 0, nil end

-- The app's hook: its texture is being drawn. utils: ui_apps_minimap_utils. dest: the route's
-- destination {x, y} or nil.
local P = {x = 0, y = 0}
function M.draw(td, utils, dest, destColour)
  if not on or type(utils) ~= 'table' or not utils.simpleCircle then return 0 end
  local circle = utils.simpleCircle
  for k = 1, count do
    P.x, P.y = mx[k], my[k]
    circle(P, mc[k], white, mr[k])
  end
  if dest and dest.x and utils.simpleCircleWithEdgePointer then
    P.x, P.y = dest.x, dest.y
    utils.simpleCircleWithEdgePointer(P, destColour, white, 8)
  end
  return count
end

return M
