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

-- --- the junction ahead ----------------------------------------------------------------------------
-- The streets that cross the road at the next junction, or the exit a motorway is coming to, for a
-- strip under the line (NAVIGATION.md, "сусідні вулиці"). The navgraph segments (world.lua S.nav)
-- meet at their end nodes (s[2], s[3]: OSM node ids); a node only two segments share is a bend or a
-- tile seam, not a junction, and the walk goes on through it.
local LOOK = 600           -- m: the farthest junction looked for
local SHOW_S, SHOW_MIN, SHOW_MAX = 10, 70, 320   -- shown this many seconds ahead, within these metres
local EXIT_MAX = 900       -- m: an exit is shown from farther, at motorway speed
local AWAY = 15            -- m from the node: the direction a street leaves it in
local SIDE = math.rad(30)  -- turns sharper than this are left or right, the rest straight on
local HOPS = 12

-- node id -> {segment, true at its start / false at its end, ...}, once per set of segments
function M.junctions(segments)
  local index = {}
  for _, seg in pairs(segments) do
    local s = seg.s
    if s and #s >= 13 then
      for k, node in ipairs({s[2], s[3]}) do
        local list = index[node]
        if not list then list = {}; index[node] = list end
        list[#list + 1] = seg
        list[#list + 1] = k == 1
      end
    end
  end
  return index
end

-- metres of a segment's line, kept on it
local function lengthOf(seg)
  local len = seg.len
  if len then return len end
  local s, sum = seg.s, 0
  for k = 8, #s - 5, 3 do sum = sum + math.sqrt((s[k + 3] - s[k]) ^ 2 + (s[k + 4] - s[k + 1]) ^ 2) end
  seg.len = sum
  return sum
end

-- the unit direction a segment leaves its start (fromStart) or its end in, AWAY m out
local function leaving(seg, fromStart)
  local s = seg.s
  local first, last, step = 8, #s - 2, 3
  if not fromStart then first, last, step = #s - 2, 8, -3 end
  local x0, y0 = s[first], s[first + 1]
  local x, y = x0, y0
  for k = first + step, last, step do
    x, y = s[k], s[k + 1]
    if (x - x0) ^ 2 + (y - y0) ^ 2 >= AWAY * AWAY then break end
  end
  local dx, dy = x - x0, y - y0
  local l = math.sqrt(dx * dx + dy * dy)
  if l < 1e-6 then return nil end
  return dx / l, dy / l
end

-- where along the segment the car is: metres from its start, the unit direction there
local function along(seg, x, y)
  local s = seg.s
  local best, at, sum, dirx, diry = math.huge, 0, 0, 1, 0
  for k = 8, #s - 5, 3 do
    local ax, ay = s[k], s[k + 1]
    local dx, dy = s[k + 3] - ax, s[k + 4] - ay
    local l2 = dx * dx + dy * dy
    if l2 > 0 then
      local l = math.sqrt(l2)
      local f = math.max(0, math.min(1, ((x - ax) * dx + (y - ay) * dy) / l2))
      local ex, ey = ax + f * dx - x, ay + f * dy - y
      local d = ex * ex + ey * ey
      if d < best then best, at, dirx, diry = d, sum + f * l, dx / l, dy / l end
      sum = sum + l
    end
  end
  seg.len = seg.len or sum
  return at, dirx, diry
end

local function oneway(seg) return not tostring(seg.s[4]):find('-', 1, true) end

local function nameOf(seg, lang)
  local name, ref = M.label(seg.names, lang)
  return name or ref
end

local function addName(list, name)
  if not name then return end
  for _, have in ipairs(list) do if have == name then return end end
  list[#list + 1] = name
end

local function destination(names)
  if not names or not names.d then return nil end
  return (names.d:gsub('%s*;%s*', ' / '))
end

-- The next junction along the heading (hx, hy) from x, y on `seg`: {dist, left = {names},
-- right = {names}, straight, exit = {ref, to, right}} or nil. index: M.junctions(segments).
function M.ahead(index, seg, x, y, hx, hy, lang, leftHand)
  if not seg or not seg.s then return nil end
  local at, dx, dy = along(seg, x, y)
  local dot = hx * dx + hy * dy
  local forward
  if dot > .3 then forward = true elseif dot < -.3 then forward = false else return nil end
  if forward == false and oneway(seg) then return nil end   -- against a one-way: no sense of ahead
  local here = seg
  local own = seg.names and (seg.names.h or nil)
  local dist = forward and (lengthOf(seg) - at) or at
  local atEnd = forward
  for _ = 1, HOPS do
    if dist > LOOK then return nil end
    local node = atEnd and here.s[3] or here.s[2]
    local list = index[node]
    if not list then return nil end
    -- the way in: the last stretch of the segment, towards the node
    local ix, iy = leaving(here, not atEnd)
    if not ix then return nil end
    ix, iy = -ix, -iy
    local others, n = nil, 0
    for k = 1, #list - 1, 2 do
      if list[k] ~= here then n = n + 1; others = others or {}; others[#others + 1] = list[k]; others[#others + 1] = list[k + 1] end
    end
    if n == 0 then return nil end
    if n == 1 then
      -- a bend, a tile seam or a change of name: the road goes on
      here, atEnd = others[1], others[2]
      dist = dist + lengthOf(here)
    else
      local out = {dist = dist, left = {}, right = {}}
      for k = 1, #others - 1, 2 do
        local o, fromStart = others[k], others[k + 1]
        -- a one-way that only comes into the junction is not a way to go
        local enters = oneway(o) and not fromStart
        local ox, oy = leaving(o, fromStart)
        if ox then
          local angle = math.atan2(ix * oy - iy * ox, ix * ox + iy * oy)
          local name = nameOf(o, lang)
          local names = o.names
          -- an exit: a link leaving a motorway or trunk on the near side, or straight on past a fork
          if names and names.k and not enters and (own == 'motorway' or own == 'trunk')
              and (leftHand and angle > -SIDE or not leftHand and angle < SIDE) then
            out.exit = out.exit or {ref = names.j, to = destination(names) or names.dr or name, right = angle < 0}
          elseif angle > SIDE then addName(out.left, name)
          elseif angle < -SIDE then addName(out.right, name)
          elseif name then out.straight = out.straight or name end
        end
      end
      return out
    end
  end
  return nil
end

-- what the strip says, built when the junction or its distance changes (10 m steps): `nil` hides it
local function aheadText(t, info, speed, lang)
  if not info then return nil end
  local reach = math.max(SHOW_MIN, math.min(SHOW_MAX, speed * SHOW_S))
  if info.exit then reach = math.max(reach, math.min(EXIT_MAX, speed * 25)) end
  if info.dist > reach then return nil end
  local own = t.main
  local left, right = {}, {}
  for _, v in ipairs(info.left) do if v ~= own then left[#left + 1] = v end end
  for _, v in ipairs(info.right) do if v ~= own then right[#right + 1] = v end end
  if not info.exit and #left == 0 and #right == 0 then return nil end
  local metres = info.dist < 1000 and math.max(0, math.floor(info.dist / 10 + .5) * 10) or nil
  return {left = #left > 0 and table.concat(left, ', ') or nil, right = #right > 0 and table.concat(right, ', ') or nil,
    exit = info.exit, metres = metres, km = not metres and info.dist / 1000 or nil, lang = lang}
end

local function sameAhead(a, b)
  if a == nil or b == nil then return a == b end
  if a.left ~= b.left or a.right ~= b.right or a.metres ~= b.metres or a.lang ~= b.lang then return false end
  local x, y = a.exit, b.exit
  if (x == nil) ~= (y == nil) then return false end
  return not x or (x.ref == y.ref and x.to == y.to)
end

-- A street that stays through a junction and an unnamed stretch. Returns true when the names changed.
local function track(t, now, x, y, vx, vy, segments)
  local speed = math.sqrt(vx * vx + vy * vy)
  local hx, hy = 0, 0
  if speed > SLOW then hx, hy = vx / speed, vy / speed end
  local seg = M.nearest(segments, x, y, hx, hy, t.seg)
  t.under = seg            -- named or not: the junction ahead is looked for along it
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

-- the junction ahead, after the line's own text (it leaves out the street the car is on)
local function stepAhead(t, now, x, y, vx, vy, env)
  -- the junction ahead: the node index follows the set of segments (env.version, world.lua S.navVersion)
  if env.noAhead then return end
  -- (re-indexed at most every 2 s while tiles stream in: a table per node is garbage)
  if t.index == nil or t.indexOf ~= env.segments
      or (env.version and t.indexVersion ~= env.version and now - (t.indexAt or -10) >= 2) then
    t.index, t.indexOf, t.indexVersion, t.indexAt = M.junctions(env.segments), env.segments, env.version, now
  end
  local speed = math.sqrt(vx * vx + vy * vy)
  local info
  if speed > SLOW and t.under then
    info = M.ahead(t.index, t.under, x, y, vx / speed, vy / speed, env.lang, env.leftHand)
  end
  local text = aheadText(t, info, speed, env.lang)
  if not sameAhead(text, t.ahead) then t.ahead = text end
  t.exitBlue = env.exitBlue
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
  if not changed then stepAhead(t, now, x, y, vx, vy, env); return false end
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
  stepAhead(t, now, x, y, vx, vy, env)
  return true
end

-- an arrow in a box of `size` px at x, y (the top left): dir -1 left, 1 right; up: bent up (an exit)
local function arrow(im, dl, v, x, y, size, dir, up, colour)
  local cy, h = y + size / 2, size * .18
  if up then
    -- a slip road: a short shaft up and off to the side, the head at its end
    local x0, y0 = x + size / 2 - dir * size * .2, y + size * .85
    local x1, y1 = x + size / 2 + dir * size * .25, y + size * .25
    v.rect.x, v.rect.y, v.rect2.x, v.rect2.y = x0, y0, x1, y1
    im.ImDrawList_AddLine(dl, v.rect, v.rect2, colour, size * .16)
    local ux, uy = (x1 - x0), (y1 - y0)
    local l = math.sqrt(ux * ux + uy * uy)
    ux, uy = ux / l, uy / l
    local px, py = -uy, ux
    local s = size * .3
    im.ImDrawList_AddTriangleFilled(dl, im.ImVec2(x1 + ux * s * .6, y1 + uy * s * .6),
      im.ImVec2(x1 - ux * s * .4 + px * s * .6, y1 - uy * s * .4 + py * s * .6),
      im.ImVec2(x1 - ux * s * .4 - px * s * .6, y1 - uy * s * .4 - py * s * .6), colour)
    return
  end
  local tip, back = x + size / 2 + dir * size * .45, x + size / 2 - dir * size * .45
  local neck = x + size / 2 + dir * size * .05
  v.rect.x, v.rect.y, v.rect2.x, v.rect2.y = math.min(back, neck), cy - h / 2, math.max(back, neck), cy + h / 2
  im.ImDrawList_AddRectFilled(dl, v.rect, v.rect2, colour, 1)
  im.ImDrawList_AddTriangleFilled(dl, im.ImVec2(tip, cy), im.ImVec2(neck, cy - size * .32), im.ImVec2(neck, cy + size * .32), colour)
end

-- The junction ahead under the line: the streets off to the left and right with arrows, the
-- distance between them; an exit as a board in the motorway's colour (green, or blue: exitBlue).
function M.drawAhead(im, dl, v, a, exitBlue)
  local en = a.lang == 'en'
  local far = a.metres and string.format(en and '%d m' or '%d м', a.metres) or string.format(en and '%.1f km' or '%.1f км', a.km or 0)
  local size = im.GetTextLineHeight()
  v.size.x, v.size.y = 1, 4
  im.Dummy(v.size)
  if a.exit then
    local e = a.exit
    local label = (e.ref and ((en and 'Exit ' or 'Виїзд ') .. e.ref) or (en and 'Exit' or 'Виїзд')) .. (e.to and ('  ' .. e.to) or '')
    local at, tw = im.GetCursorScreenPos(), im.CalcTextSize(label)
    local w = size + 8 + tw.x + 16
    v.rect.x, v.rect.y, v.rect2.x, v.rect2.y = at.x, at.y, at.x + w, at.y + size + 8
    im.ImDrawList_AddRectFilled(dl, v.rect, v.rect2, exitBlue and v.road or v.green, 5)
    im.ImDrawList_AddRect(dl, v.rect, v.rect2, v.white, 5, 0, 1.5)
    arrow(im, dl, v, at.x + 5, at.y + 4, size, e.right == false and -1 or 1, true, v.white)
    v.rect.x, v.rect.y = at.x + size + 11, at.y + 4
    im.ImDrawList_AddText1(dl, v.rect, v.white, label)
    v.size.x, v.size.y = w, size + 8
    im.Dummy(v.size)
    im.SameLine()
    im.PushStyleColor2(im.Col_Text, v.muted)
    im.TextUnformatted(far)
    im.PopStyleColor(1)
    return
  end
  v.size.x, v.size.y = size, size
  if a.left then
    local at = im.GetCursorScreenPos()
    arrow(im, dl, v, at.x, at.y, size, -1, false, v.turnU32)
    im.Dummy(v.size)
    im.SameLine()
    im.TextUnformatted(a.left)
    im.SameLine()
  end
  im.PushStyleColor2(im.Col_Text, v.muted)
  im.TextUnformatted(a.left and a.right and ('  ' .. far .. '  ') or far)
  im.PopStyleColor(1)
  if a.right then
    im.SameLine()
    im.TextUnformatted(a.right)
    im.SameLine()
    local at = im.GetCursorScreenPos()
    arrow(im, dl, v, at.x, at.y, size, 1, false, v.turnU32)
    v.size.x, v.size.y = size, size
    im.Dummy(v.size)
  end
end

-- The line itself, top centre: the street large, what it is in under it, a limit roundel and the
-- road's number where they are known, the next turn while a route runs (route: navigator.lines).
-- No inputs: it never takes the mouse from the game. One set of ImVec2 for the whole session
-- (every one is an engine object).
local look
function M.draw(im, t, route, topOffset)
  if not t.main then return end
  local view = im.GetMainViewport()
  if not view then return end
  local v = look
  if not v then
    v = {pos = im.ImVec2(0, 0), pivot = im.ImVec2(.5, 0), pad = im.ImVec2(14, 8), rect = im.ImVec2(0, 0), rect2 = im.ImVec2(0, 0),
      size = im.ImVec2(0, 0), red = im.GetColorU322(im.ImVec4(.85, .12, .12, 1)), white = im.GetColorU322(im.ImVec4(1, 1, 1, 1)),
      ink = im.GetColorU322(im.ImVec4(.08, .08, .1, 1)), road = im.GetColorU322(im.ImVec4(.13, .36, .68, 1)),
      back = im.ImVec4(.08, .09, .11, .78), text = im.ImVec4(.97, .97, .98, 1), muted = im.ImVec4(.72, .75, .8, 1),
      turn = im.ImVec4(.55, .82, 1, 1), turnU32 = im.GetColorU322(im.ImVec4(.55, .82, 1, 1)),
      green = im.GetColorU322(im.ImVec4(.0, .45, .24, 1)),
      flags = im.WindowFlags_NoDecoration + im.WindowFlags_NoInputs + im.WindowFlags_NoNav + im.WindowFlags_NoSavedSettings
        + im.WindowFlags_NoFocusOnAppearing + im.WindowFlags_NoBringToFrontOnFocus + im.WindowFlags_AlwaysAutoResize + im.WindowFlags_NoDocking}
    look = v
  end
  v.pos.x, v.pos.y = view.Pos.x + view.Size.x / 2, view.Pos.y + 10 + (topOffset or 0)
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
  if t.ahead then M.drawAhead(im, dl, v, t.ahead, t.exitBlue) end
  im.EndGroup()
  im.End()
  im.PopStyleVar(3)
  im.PopStyleColor(1)
end

return M
