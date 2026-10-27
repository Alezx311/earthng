-- Navigation to a point picked on the widget's map (docs/NAVIGATION.md). The region's routing
-- graph (routing.lua) finds the route in a coroutine of BUDGET_MS a frame; the game's ground
-- markers show the next AHEAD m of it on the road, as navgraph nodes 'e2r_n<id>' (world.lua
-- navBuild names its junctions so); the minimap draws the line. The world frame is the driven
-- region's, so the graph needs no transform.
local M = {}
local routing = require('ge/extensions/e2r/routing')

local BUDGET_MS = 2
local AHEAD, SPACING = 700, 150      -- m of route handed to core_groundMarkers, m between its waypoints
local REACH = 950                    -- m: the farthest node handed over (world.lua NAV_R is 1000)
local OFF_M, OFF_S = 45, 3           -- this far off the line for this long: a new route from the car
local ARRIVE_M = 30
local FAR_M = 2000                   -- a destination this far from every road of the graph
local WINDOW = 80                    -- route segments searched round the last match each frame
local TEXT_EVERY = .5                -- s between refreshes of the widget's lines

-- M.source: native.lua (routing, readBytes, toGeo); tests give their own
local nav = {state = 'none'}
local cache = {}

local function timer()
  if hptimer then return hptimer() end
  local t0 = os.clock()
  return {stop = function() return (os.clock() - t0) * 1000 end}
end

-- the job's pause point: the timer is the current frame's (a closure made at the first resume
-- would keep the first frame's timer and yield at every point after it)
local frameTimer
local function pauseJob()
  if frameTimer:stop() >= BUDGET_MS then coroutine.yield() end
end

local function setMarkers(list)
  if not (core_groundMarkers and core_groundMarkers.setPath) then return end
  pcall(core_groundMarkers.setPath, list, list and {clearPathOnReachingTarget = false} or nil)
end

local function clearRoute()
  if nav.markersSig then setMarkers(nil) end
  nav.route, nav.markersSig, nav.offSince, nav.lines = nil, nil, nil, nil
end

function M.clear()
  clearRoute()
  nav = {state = 'none'}
end

-- --- the search job -----------------------------------------------------------------------------
-- The file in CHUNK reads with a pause between them: the Kyiv graph (2.8 MB) in one read was an
-- 18 ms stretch in the game, and the zip entry inflates as it is read.
local CHUNK = 262144
local function readFile(source, path, pause)
  local f = io.open(path, 'rb')
  if not f then return source.readBytes(path) end
  local parts = {}
  while true do
    local s = f:read(CHUNK)
    if not s then break end
    parts[#parts + 1] = s
    pause()
  end
  f:close()
  return table.concat(parts)
end

local function startJob(fromX, fromY)
  local dest, lang, source = nav.dest, nav.lang, M.source
  nav.job = coroutine.create(function(pause)
    local path, key = source.routing()
    if not path then return 'nograph' end
    if cache.key ~= key then
      cache.graph, cache.key = nil, nil
      local region = routing.decode(readFile(source, path, pause), nil, pause)
      cache.graph, cache.key = routing.graph({region}, pause), key
    end
    local g = cache.graph
    local from = routing.nearest(g, fromX, fromY)
    pause()
    local to, gap = routing.nearest(g, dest.x, dest.y)
    if not from or not to then return 'noroad' end
    if gap > FAR_M then return 'far' end
    pause()
    local route = routing.route(g, from, to, lang, pause)
    if not route then return 'noroute' end
    return 'ok', route
  end)
  nav.state = nav.route and 'rerouting' or 'searching'
  nav.textAt = nil
end

-- cumulative metres along the line and the minimap's chunks (lat/lon, a box each)
local function install(route)
  local p, cum = route.points, {0}
  for k = 3, #p - 1, 2 do
    cum[#cum + 1] = cum[#cum] + math.sqrt((p[k] - p[k - 2]) ^ 2 + (p[k + 1] - p[k - 1]) ^ 2)
  end
  route.cum = cum
  route.chunks = {}
  local toGeo = M.source and M.source.toGeo
  if toGeo then
    local chunk
    for k = 1, #p - 1, 2 do
      if not chunk or #chunk.geo >= 64 then
        local last = chunk and {chunk.geo[#chunk.geo - 1], chunk.geo[#chunk.geo]}
        chunk = {geo = {}, box = {math.huge, math.huge, -math.huge, -math.huge}}
        route.chunks[#route.chunks + 1] = chunk
        if last then chunk.geo[1], chunk.geo[2] = last[1], last[2] end
      end
      local lat, lon = toGeo(p[k], p[k + 1])
      local g, b = chunk.geo, chunk.box
      g[#g + 1], g[#g + 2] = lat, lon
      b[1], b[2], b[3], b[4] = math.min(b[1], lat), math.min(b[2], lon), math.max(b[3], lat), math.max(b[4], lon)
    end
  end
  nav.route, nav.seg, nav.along, nav.offSince, nav.markersSig, nav.markersAlong = route, 1, 0, nil, nil, nil
  nav.state, nav.textAt = 'route', nil
end

-- --- following ----------------------------------------------------------------------------------
local function follow(x, y, now)
  local route = nav.route
  local p, cum = route.points, route.cum
  local n = #cum
  local best, bestSeg, bestF = math.huge, nav.seg, 0
  for s = math.max(1, nav.seg - 2), math.min(n - 1, nav.seg + WINDOW) do
    local ax, ay, bx, by = p[2 * s - 1], p[2 * s], p[2 * s + 1], p[2 * s + 2]
    local dx, dy = bx - ax, by - ay
    local l2 = dx * dx + dy * dy
    local f = l2 > 0 and math.max(0, math.min(1, ((x - ax) * dx + (y - ay) * dy) / l2)) or 0
    local ex, ey = ax + f * dx - x, ay + f * dy - y
    local d = ex * ex + ey * ey
    if d < best then best, bestSeg, bestF = d, s, f end
  end
  nav.seg = bestSeg
  nav.along = cum[bestSeg] + bestF * (cum[bestSeg + 1] - cum[bestSeg])
  nav.off = math.sqrt(best)
  if cum[n] - nav.along < ARRIVE_M then
    clearRoute()
    nav.state, nav.arrivedAt, nav.textAt = 'arrived', now, nil
    return
  end
  if nav.off > OFF_M then
    nav.offSince = nav.offSince or now
    if now - nav.offSince > OFF_S and not nav.job then startJob(x, y) end
  else
    nav.offSince = nil
  end
end

-- the route's next AHEAD m as navgraph nodes the game has now
local function feedMarkers()
  local route = nav.route
  if not (map and map.getMap) then return end
  local m = map.getMap()
  local nodes = m and m.nodes
  if not nodes then return end
  local serial = m.buildSerial
  local scale = route.length / math.max(1, route.cum[#route.cum])   -- line metres -> edge metres
  local a = nav.along * scale
  -- again after SPACING m, a new navgraph, or nearing the last node handed over (on a long
  -- straight it can be the only one, 58 m ahead in the Kyiv drive: the arrows ended there)
  if nav.markersSig and serial == nav.markersSerial and nav.markersAlong and a - nav.markersAlong < SPACING
    and a < (nav.markersEnd or math.huge) - 60 then return end
  local list, last = {}, -math.huge
  local ids, at = route.ids, route.at
  for k = 1, #ids do
    if at[k] > a + 20 and at[k] <= a + AHEAD then
      local id = 'e2r_n' .. ids[k]
      if nodes[id] and (at[k] - last >= SPACING or k == #ids) then list[#list + 1] = id; last = at[k] end
    elseif at[k] > a + AHEAD then
      -- a long stretch to the next junction: its far end too, if the navgraph (NAV_R round
      -- the car) has it already
      if last < a + AHEAD - SPACING and at[k] <= a + REACH and nodes['e2r_n' .. ids[k]] then
        list[#list + 1] = 'e2r_n' .. ids[k]; last = at[k]
      end
      break
    end
  end
  local sig = table.concat(list, ',')
  nav.markersSerial, nav.markersAlong, nav.markersEnd = serial, a, last
  if sig == nav.markersSig then return end
  nav.markersSig = sig
  setMarkers(#list > 0 and list or nil)
end

-- --- public -------------------------------------------------------------------------------------
-- a destination at world x, y (lat, lon for the pin); the route starts at the car
function M.setDestination(x, y, lat, lon, car, lang)
  clearRoute()
  nav = {state = 'none', dest = {x = x, y = y, lat = lat, lon = lon}, lang = lang}
  if not (M.source and M.source.routing) then nav.state = 'nograph'; return end
  startJob(car.x, car.y)
end

-- one frame: focus() gives the car; now in seconds
function M.step(focus, now, lang)
  if nav.state == 'none' then return end
  if nav.state == 'arrived' and now - (nav.arrivedAt or now) > 6 then nav = {state = 'none'}; return end
  nav.now, nav.lang = now, lang or nav.lang
  if nav.job then
    frameTimer = timer()
    local ok, result, route = coroutine.resume(nav.job, pauseJob)
    if not ok then
      nav.job, nav.state, nav.error = nil, 'error', tostring(result)
      clearRoute()
    elseif coroutine.status(nav.job) == 'dead' then
      nav.job = nil
      if result == 'ok' then install(route) else clearRoute(); nav.state = result end
    end
    nav.textAt = nil
  end
  if nav.route then
    local p = focus()
    if p then
      follow(p.x, p.y, now)
      if nav.route then feedMarkers() end
    end
  end
end

local function distance(m, L)
  if m < 1000 then return string.format(L('%d м', '%d m'), math.floor(m / 10 + .5) * 10) end
  return string.format(L('%.1f км', '%.1f km'), m / 1000)
end

local function turnText(s, L)
  local t = s.turn
  if s.ring then return L('на кільце', 'onto the roundabout') end
  if math.abs(t) < 35 then return L('прямо', 'straight on') end
  if math.abs(t) > 150 then return L('розворот', 'U-turn') end
  if t > 0 then return math.abs(t) > 110 and L('різко ліворуч', 'sharp left') or L('ліворуч', 'left') end
  return math.abs(t) > 110 and L('різко праворуч', 'sharp right') or L('праворуч', 'right')
end

-- the widget's lines: {main, next} (refreshed every TEXT_EVERY s), or nil without navigation
function M.lines(L)
  if nav.state == 'none' then return nil end
  local now = nav.now or 0
  if nav.lines and nav.textAt and now - nav.textAt < TEXT_EVERY then return nav.lines end
  nav.textAt = now
  local main, nextLine
  if nav.state == 'searching' or nav.state == 'rerouting' then
    main = nav.state == 'searching' and L('Будую маршрут...', 'Finding the route...') or L('Перебудовую маршрут...', 'Finding a new route...')
  elseif nav.state == 'nograph' then
    main = L('Для цього регіону немає графа маршрутів (routing/*.bin).', 'This region has no routing graph (routing/*.bin).')
  elseif nav.state == 'far' then
    main = L('Ціль далеко від доріг цього регіону.', 'The destination is far from this region\'s roads.')
  elseif nav.state == 'noroad' or nav.state == 'noroute' then
    main = L('Маршруту туди немає.', 'No route there.')
  elseif nav.state == 'error' then
    main = L('Помилка маршруту: ', 'Route error: ') .. tostring(nav.error)
  elseif nav.state == 'arrived' then
    main = L('Ви на місці.', 'You have arrived.')
  elseif nav.route then
    local route = nav.route
    local total = route.cum[#route.cum]
    local left = math.max(0, total - nav.along)
    main = string.format(L('До цілі %s, ~%d хв', '%s to go, ~%d min'), distance(left, L),
      math.max(1, math.floor(route.time * left / math.max(1, total) / 60 + .5)))
    local scale = total / math.max(1, route.length)
    for _, s in ipairs(route.steps) do
      local d = s.at * scale - nav.along
      if d > 5 then
        local what = turnText(s, L)
        local name = s.name or s.ref
        nextLine = string.format(L('Через %s %s', 'In %s, %s'), distance(d, L), what) .. (name and (': ' .. name) or '')
        break
      end
    end
  end
  nav.lines = {main, nextLine}
  return nav.lines
end

function M.active() return nav.state ~= 'none' end
function M.destination() return nav.dest end

-- The line on a map at zoom z: merc(lat, lon, z) -> pixels; ox, oy shift them to the screen.
-- Pixels are kept per chunk and zoom, and a point under 6 px from the last drawn one is skipped
-- (every ImVec2 is an engine object).
function M.draw(im, dl, z, ox, oy, merc, col, north, west, south, east)
  local route = nav.route
  if route then
    local line, rim = col(.2, .45, .95, .95), col(1, 1, 1, .9)
    for pass = 1, 2 do
      local c, w = pass == 1 and rim or line, pass == 1 and 7 or 4
      for _, chunk in ipairs(route.chunks) do
        local b = chunk.box
        if b[1] <= north and b[3] >= south and b[2] <= east and b[4] >= west then
          local m = chunk.merc
          if chunk.zoom ~= z then
            m = {}
            local g = chunk.geo
            for k = 1, #g - 1, 2 do m[k], m[k + 1] = merc(g[k], g[k + 1], z) end
            chunk.merc, chunk.zoom = m, z
          end
          local px, py = m[1] + ox, m[2] + oy
          local from = im.ImVec2(px, py)
          for k = 3, #m - 1, 2 do
            local x, y = m[k] + ox, m[k + 1] + oy
            if k == #m - 1 or (x - px) ^ 2 + (y - py) ^ 2 >= 36 then
              local to = im.ImVec2(x, y)
              im.ImDrawList_AddLine(dl, from, to, c, w)
              from, px, py = to, x, y
            end
          end
        end
      end
    end
  end
  local d = nav.dest
  if d and d.lat and nav.state ~= 'arrived' then
    local x, y = merc(d.lat, d.lon, z)
    x, y = x + ox, y + oy
    -- a flag: the pole and a cloth, blue like the line
    im.ImDrawList_AddLine(dl, im.ImVec2(x, y), im.ImVec2(x, y - 22), col(.1, .1, .12), 2.5)
    im.ImDrawList_AddTriangleFilled(dl, im.ImVec2(x, y - 22), im.ImVec2(x + 14, y - 17), im.ImVec2(x, y - 12), col(1, 1, 1))
    im.ImDrawList_AddTriangleFilled(dl, im.ImVec2(x + 1, y - 20.5), im.ImVec2(x + 11.5, y - 17), im.ImVec2(x + 1, y - 13.5), col(.2, .45, .95))
    im.ImDrawList_AddCircleFilled(dl, im.ImVec2(x, y), 3, col(.1, .1, .12))
  end
end

return M
