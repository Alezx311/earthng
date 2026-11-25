-- How a map view moves (world.lua drawMap, worldmap.lua): the zoom is a real number that eases to
-- its target round the point under the cursor, a dragged map keeps its speed when it is let go and
-- slows down, and a jump to a place (a search hit, the car) is a short flight. Pure Lua: the view
-- is {center = {lat, lon}, zoom}; everything else this file keeps on it (zoomTo, anchor, vx, vy,
-- fly). A zoom or centre another piece of code writes straight into the view is taken as it is.
--
-- A map is drawn at the whole zoom level nearest to the view's zoom (M.level) and stretched by
-- M.stretch: Mercator pixels of level L times 2^(zoom - L) are the pixels of the zoom itself, so
-- every cache keyed by a level stays good while the zoom moves half a level either way.
local M = {}
local exp, floor, max, min, abs = math.exp, math.floor, math.max, math.min, math.abs

M.MIN, M.MAX = 2, 18
M.ZOOM_RATE = 13       -- 1/s: the share of the gap to the target zoom closed a second (e-folds)
M.FRICTION = 4.2       -- 1/s: a thrown map loses its speed
M.STOP = 14            -- px/s: under this it stands
M.THROW_AFTER = .09    -- s: the mouse stood this long before the release - no throw
M.FLY = .42            -- s: a flight to a place
M.FLY_SCREENS = 6      -- farther than this many screens away the view jumps

local function mercUnit(lat, lon)
  local s = math.sin(math.rad(max(-85.05, min(85.05, lat))))
  return (lon + 180) / 360, .5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)
end
local function unmercUnit(x, y)
  local m = math.pi * (1 - 2 * y)
  return math.deg(math.atan(.5 * (exp(m) - exp(-m)))), x * 360 - 180
end
M.mercUnit, M.unmercUnit = mercUnit, unmercUnit

-- the whole level a zoom is drawn at and the stretch of that level's pixels
function M.level(zoom, lo, hi)
  local l = floor(zoom + .5)
  if lo and l < lo then l = lo end
  if hi and l > hi then l = hi end
  return l
end
function M.stretch(zoom, level) return 2 ^ (zoom - level) end

local function clampZoom(view, z)
  return max(view.minZoom or M.MIN, min(view.maxZoom or M.MAX, z))
end

-- the view as this file last left it; a zoom written from outside becomes the target at once
local function sync(view)
  if view.zoomSeen ~= view.zoom then
    view.zoomTo, view.zoomSeen, view.anchor = view.zoom, view.zoom, nil
  end
  if view.centerSeen ~= view.center then
    view.centerSeen, view.vx, view.vy, view.fly = view.center, 0, 0, nil
  end
end

local function setCenter(view, lat, lon)
  local c = view.center
  if view.centerSeen ~= c or not c then c = {}; view.center = c end
  c.lat, c.lon = max(-85, min(85, lat)), lon
  view.centerSeen = c
end

-- Zoom by `steps` levels round the screen point sx, sy (pixels from the map's top left corner;
-- nil: the centre). width, height: the map's size.
function M.zoomBy(view, steps, sx, sy, width, height)
  sync(view)
  local to = clampZoom(view, floor((view.zoomTo or view.zoom) * 2 + .5) / 2 + steps)
  view.zoomTo, view.fly = to, nil
  if sx and not view.follow then
    local scale = 256 * 2 ^ view.zoom
    local cx, cy = mercUnit(view.center.lat, view.center.lon)
    view.anchor = {x = cx + (sx - width / 2) / scale, y = cy + (sy - height / 2) / scale, sx = sx, sy = sy}
  else
    view.anchor = nil
  end
end

-- the map dragged by dx, dy pixels over dt seconds
function M.drag(view, dx, dy, dt)
  sync(view)
  view.fly, view.anchor = nil, nil
  if dx == 0 and dy == 0 then
    view.dragIdle = (view.dragIdle or 0) + dt
    return
  end
  local scale = 256 * 2 ^ view.zoom
  local cx, cy = mercUnit(view.center.lat, view.center.lon)
  setCenter(view, unmercUnit(cx - dx / scale, max(0, min(1, cy - dy / scale))))
  if dt > 1e-4 then
    -- the speed of the last few frames, so one odd frame does not throw the map
    local k = min(1, dt * 30)
    view.vx = (view.vx or 0) * (1 - k) + dx / dt * k
    view.vy = (view.vy or 0) * (1 - k) + dy / dt * k
  end
  view.dragIdle = 0
end

-- the mouse button is up: the map keeps its speed unless the hand had stopped
function M.release(view)
  if (view.dragIdle or 1) > M.THROW_AFTER then view.vx, view.vy = 0, 0 end
  view.dragIdle = nil
end

function M.stop(view) view.vx, view.vy, view.fly = 0, 0, nil end

-- a flight to lat, lon (and a zoom); a place many screens away is a jump
function M.flyTo(view, lat, lon, zoom, width, height)
  sync(view)
  zoom = clampZoom(view, zoom or view.zoom)
  local scale = 256 * 2 ^ min(view.zoom, zoom)
  local ax, ay = mercUnit(view.center.lat, view.center.lon)
  local bx, by = mercUnit(lat, lon)
  local screens = math.sqrt(((bx - ax) * scale) ^ 2 + ((by - ay) * scale) ^ 2) / max(200, min(width or 1000, height or 1000))
  view.vx, view.vy, view.anchor = 0, 0, nil
  if screens > M.FLY_SCREENS then
    setCenter(view, lat, lon)
    view.zoom, view.zoomTo, view.zoomSeen, view.fly = zoom, zoom, zoom, nil
    return
  end
  view.fly = {ax = ax, ay = ay, bx = bx, by = by, z0 = view.zoom, z1 = zoom, t = 0}
  view.zoomTo = zoom
end

-- One frame. Returns true while the view still moves on its own.
function M.step(view, dt, width, height)
  sync(view)
  -- (a frame time the caller does not know: the clock's own, so the view never stands still)
  local clock = os.clock()
  if not dt or dt <= 0 then dt = view.stepAt and clock - view.stepAt or 0 end
  view.stepAt = clock
  dt = max(0, min(.1, dt))
  local moving = false
  local fly = view.fly
  if fly then
    fly.t = fly.t + dt / M.FLY
    local t = min(1, fly.t)
    local k = t * t * (3 - 2 * t)
    setCenter(view, unmercUnit(fly.ax + (fly.bx - fly.ax) * k, fly.ay + (fly.by - fly.ay) * k))
    view.zoom = fly.z0 + (fly.z1 - fly.z0) * k
    view.zoomSeen = view.zoom
    if t >= 1 then view.fly, view.zoom, view.zoomSeen = nil, fly.z1, fly.z1 end
    return true
  end
  local to = view.zoomTo or view.zoom
  if to ~= view.zoom then
    local z = view.zoom + (to - view.zoom) * (1 - exp(-M.ZOOM_RATE * dt))
    if abs(to - z) < .004 then z = to end
    local a = view.anchor
    if a and not view.follow then
      local scale = 256 * 2 ^ z
      setCenter(view, unmercUnit(a.x - (a.sx - width / 2) / scale, max(0, min(1, a.y - (a.sy - height / 2) / scale))))
    end
    view.zoom, view.zoomSeen = z, z
    if z == to then view.anchor = nil end
    moving = true
  end
  local vx, vy = view.vx or 0, view.vy or 0
  if not view.dragIdle and (vx ~= 0 or vy ~= 0) then
    if vx * vx + vy * vy < M.STOP * M.STOP or view.follow then
      view.vx, view.vy = 0, 0
    else
      local scale = 256 * 2 ^ view.zoom
      local cx, cy = mercUnit(view.center.lat, view.center.lon)
      setCenter(view, unmercUnit(cx - vx * dt / scale, max(0, min(1, cy - vy * dt / scale))))
      local k = exp(-M.FRICTION * dt)
      view.vx, view.vy = vx * k, vy * k
      moving = true
    end
  end
  return moving
end

return M
