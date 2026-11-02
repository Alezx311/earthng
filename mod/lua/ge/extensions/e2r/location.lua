-- Where the car is, for the line at the top of the screen (issue #24, docs/NAVIGATION.md part A):
-- the street from the navgraph segments round the car (world.lua S.nav), the settlement from the
-- country map's places.json with Natural Earth's cities under it, the region from the pack. All
-- offline. M.step runs a few times a second, and text is rebuilt only when a name changes, so a
-- frame allocates nothing here.
local M = {}

local REACH = 40         -- m: farther than this from every road the car is on no street
local STICK = 6          -- m: the street it is on keeps it by this much (a side street at a junction)
local ACROSS = 10        -- m: a road across the heading counts as this much farther
local HOLD = 3           -- s: an unnamed piece of a named street keeps the name this long
local SLOW = 1.5         -- m/s: below this the velocity says nothing of the heading
local PLACE_EVERY = 2    -- s between settlement lookups
local CELL = .25         -- degrees of the settlement index
local NEAR_KM = 20       -- outside every settlement: 'near' the closest within this
local MAX_KM = 30
local KM = 111.32        -- km of a degree
-- how far a place reaches when the point is all OSM gives: at least this, and more with people
local PLACE_KM = {city = 6, town = 3, village = 1.5, hamlet = .7, suburb = 1.5, neighbourhood = .7}
local PARTS = {suburb = true, neighbourhood = true}
local NONE = {}

local function cellKey(i, j) return i * 100000 + j end

-- places: [lat, lon, zoom, en, uk, capital, population, kind] (build_map.py; Natural Earth's
-- labels have no kind and are cities)
function M.index(places)
  local grid = {}
  for _, p in ipairs(places or NONE) do
    local kind = p[8] or 'city'
    local km = PLACE_KM[kind]
    if km then
      p.km = math.min(MAX_KM, math.max(km, math.sqrt(p[7] or 0) / 90))
      p.part = PARTS[kind]
      local key = cellKey(math.floor(p[1] / CELL), math.floor(p[2] / CELL))
      local list = grid[key]
      if not list then list = {}; grid[key] = list end
      list[#list + 1] = p
    end
  end
  return grid
end

-- the settlement the point is in, the part of it (a suburb), and the closest one when in neither
function M.settlement(grid, lat, lon)
  local stretch = math.cos(math.rad(lat))
  local town, share, part, partShare, near, nearKm
  local a, b = math.floor(lat / CELL), math.floor(lon / CELL)
  local spread = math.ceil(MAX_KM / KM / CELL / math.max(.2, stretch))
  for i = a - 2, a + 2 do
    for j = b - spread, b + spread do
      for _, p in ipairs(grid[cellKey(i, j)] or NONE) do
        local dy, dx = (p[1] - lat) * KM, (p[2] - lon) * KM * stretch
        local d = math.sqrt(dx * dx + dy * dy)
        local r = d / p.km
        if p.part then
          if r < 1 and (not partShare or r < partShare) then part, partShare = p, r end
        else
          if r < 1 and (not share or r < share) then town, share = p, r end
          if d < NEAR_KM and (not nearKm or d < nearKm) then near, nearKm = p, d end
        end
      end
    end
  end
  return town, town and part or nil, not town and near or nil
end

-- The street under the car: the closest segment, a road across the heading counting as farther
-- and the current one as nearer. segments: world.lua S.nav, {s = navSegment, box = {x0, y0, x1, y1}}.
function M.nearest(segments, x, y, hx, hy, current)
  local best, score
  for _, seg in pairs(segments) do
    local b = seg.box
    if b and x >= b[1] - REACH and x <= b[3] + REACH and y >= b[2] - REACH and y <= b[4] + REACH then
      local s = seg.s
      for k = 8, #s - 5, 3 do
        local ax, ay = s[k], s[k + 1]
        local dx, dy = s[k + 3] - ax, s[k + 4] - ay
        local l2 = dx * dx + dy * dy
        if l2 > 0 then
          local f = math.max(0, math.min(1, ((x - ax) * dx + (y - ay) * dy) / l2))
          local ex, ey = ax + f * dx - x, ay + f * dy - y
          local d = ex * ex + ey * ey
          if d < REACH * REACH then
            local cost = math.sqrt(d) + ACROSS * (1 - math.abs(hx * dx + hy * dy) / math.sqrt(l2))
            if seg == current then cost = cost - STICK end
            if not score or cost < score then best, score = seg, cost end
          end
        end
      end
    end
  end
  return best
end

-- names: {n, u, e, r, l} of generator.lua ROADS.navNames
function M.label(names, lang)
  if not names then return nil end
  local name = lang == 'en' and names.e or lang ~= 'en' and names.u or nil
  name = name or names.n
  if name then return name, names.r end
  return names.r
end

function M.new() return {placeAt = -math.huge} end

-- A street that stays through a junction and an unnamed stretch. Returns true when the names changed.
local function track(t, now, x, y, vx, vy, segments)
  local speed = math.sqrt(vx * vx + vy * vy)
  local hx, hy = 0, 0
  if speed > SLOW then hx, hy = vx / speed, vy / speed end
  local seg = M.nearest(segments, x, y, hx, hy, t.seg)
  local names = seg and seg.names
  if names and (names.n or names.r) then
    t.seg, t.heldAt = seg, now
    t.limit = names.l
    if names ~= t.names then t.names = names; return true end
  else
    t.limit = names and names.l or (seg and nil or t.limit)
    if t.names and now - (t.heldAt or now) > HOLD then
      t.seg, t.names, t.limit = nil, nil, nil
      return true
    end
  end
  return false
end

local function push(list, value)
  if not value or value == '' then return end
  for _, have in ipairs(list) do if have == value then return end end
  list[#list + 1] = value
end

-- one lookup. env: lat, lon of the car; segments; lang; places() -> index; region() -> region and
-- country names; near(name) -> 'near <name>' in the UI's language
function M.step(t, now, x, y, vx, vy, env)
  local changed = track(t, now, x, y, vx, vy, env.segments)
  if t.lang ~= env.lang then t.lang, changed = env.lang, true end
  if now - t.placeAt >= PLACE_EVERY and env.lat then
    t.placeAt = now
    local index = env.places and env.places()
    local town, part, near
    if index then town, part, near = M.settlement(index, env.lat, env.lon) end
    local region, country
    if env.region then region, country = env.region() end
    if town ~= t.town or part ~= t.part or near ~= t.near or region ~= t.region or country ~= t.country then
      t.town, t.part, t.near, t.region, t.country = town, part, near, region, country
      changed = true
    end
  end
  if not changed then return false end
  local en = env.lang == 'en'
  local function place(p) return p and (en and p[4] or p[5] or p[4]) or nil end
  local street, ref = M.label(t.names, env.lang)
  local where = {}
  push(where, place(t.part))
  push(where, place(t.town))
  if t.near and env.near then push(where, env.near(place(t.near))) end
  -- a spot pack is called after its town: 'London' over 'Лондон'
  local function itself(name) return name and t.town and (name == t.town[4] or name == t.town[5]) end
  if not itself(t.region) then push(where, t.region) end
  if not itself(t.country) then push(where, t.country) end
  if not street then street = table.remove(where, 1) end
  t.ref, t.main, t.rest = ref, street, #where > 0 and table.concat(where, ', ') or nil
  return true
end

-- The line itself, top centre: the street large, what it is in under it, a limit roundel and the
-- road's number where they are known, the next turn while a route runs (route: navigator.lines).
-- No inputs: it never takes the mouse from the game. One set of ImVec2 for the whole session
-- (every one is an engine object).
local look
function M.draw(im, t, route)
  if not t.main then return end
  local view = im.GetMainViewport()
  if not view then return end
  local v = look
  if not v then
    v = {pos = im.ImVec2(0, 0), pivot = im.ImVec2(.5, 0), pad = im.ImVec2(14, 8), rect = im.ImVec2(0, 0), rect2 = im.ImVec2(0, 0),
      size = im.ImVec2(0, 0), red = im.GetColorU322(im.ImVec4(.85, .12, .12, 1)), white = im.GetColorU322(im.ImVec4(1, 1, 1, 1)),
      ink = im.GetColorU322(im.ImVec4(.08, .08, .1, 1)), road = im.GetColorU322(im.ImVec4(.13, .36, .68, 1)),
      back = im.ImVec4(.08, .09, .11, .78), text = im.ImVec4(.97, .97, .98, 1), muted = im.ImVec4(.72, .75, .8, 1),
      turn = im.ImVec4(.55, .82, 1, 1),
      flags = im.WindowFlags_NoDecoration + im.WindowFlags_NoInputs + im.WindowFlags_NoNav + im.WindowFlags_NoSavedSettings
        + im.WindowFlags_NoFocusOnAppearing + im.WindowFlags_NoBringToFrontOnFocus + im.WindowFlags_AlwaysAutoResize + im.WindowFlags_NoDocking}
    look = v
  end
  v.pos.x, v.pos.y = view.Pos.x + view.Size.x / 2, view.Pos.y + 10
  im.SetNextWindowPos(v.pos, im.Cond_Always, v.pivot)
  im.PushStyleColor2(im.Col_WindowBg, v.back)
  im.PushStyleVar1(im.StyleVar_WindowRounding, 10)
  im.PushStyleVar1(im.StyleVar_WindowBorderSize, 0)
  im.PushStyleVar2(im.StyleVar_WindowPadding, v.pad)
  im.Begin('EarthNG##location', nil, v.flags)
  local dl = im.GetWindowDrawList()
  if t.limit then
    local height = im.GetTextLineHeight() * (t.rest and 2.4 or 1.5)
    local r = height / 2
    local at = im.GetCursorScreenPos()
    v.rect.x, v.rect.y = at.x + r, at.y + r
    im.ImDrawList_AddCircleFilled(dl, v.rect, r, v.white, 32)
    im.ImDrawList_AddCircle(dl, v.rect, r - 1.5, v.red, 32, 3.5)
    local label = im.CalcTextSize(t.limit)
    v.rect2.x, v.rect2.y = at.x + r - label.x / 2, at.y + r - label.y / 2
    im.ImDrawList_AddText1(dl, v.rect2, v.ink, t.limit)
    v.size.x, v.size.y = height, height
    im.Dummy(v.size)
    im.SameLine()
  end
  im.BeginGroup()
  im.SetWindowFontScale(1.3)
  im.PushStyleColor2(im.Col_Text, v.text)
  im.TextUnformatted(t.main)
  im.PopStyleColor(1)
  im.SetWindowFontScale(1)
  if t.ref and t.ref ~= t.main then
    im.SameLine()
    local at, label = im.GetCursorScreenPos(), im.CalcTextSize(t.ref)
    v.rect.x, v.rect.y = at.x, at.y + 1
    v.rect2.x, v.rect2.y = at.x + label.x + 12, at.y + label.y + 7
    im.ImDrawList_AddRectFilled(dl, v.rect, v.rect2, v.road, 4)
    v.rect.x, v.rect.y = at.x + 6, at.y + 4
    im.ImDrawList_AddText1(dl, v.rect, v.white, t.ref)
    v.size.x, v.size.y = label.x + 12, label.y + 7
    im.Dummy(v.size)
  end
  if t.rest then
    im.PushStyleColor2(im.Col_Text, v.muted)
    im.TextUnformatted(t.rest)
    im.PopStyleColor(1)
  end
  if route then
    im.PushStyleColor2(im.Col_Text, v.turn)
    im.TextUnformatted(route[2] or route[1])
    im.PopStyleColor(1)
  end
  im.EndGroup()
  im.End()
  im.PopStyleVar(3)
  im.PopStyleColor(1)
end

return M
