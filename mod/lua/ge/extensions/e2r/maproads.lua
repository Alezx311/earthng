-- Roads on the map at every zoom (world.lua drawMap; docs/MAP.md "Roads"), from what a pack
-- already carries:
--
--   zoom 5-10   the sidecar's transparent overview tiles (map/r<z>_<x>_<y>.png), stretched to the
--               view's zoom and drawn with a dark rim, so the thin baked lines read on the chart
--               and on a photograph alike;
--   zoom 11+    the sidecar's level 11 lines (motorway..tertiary, map/11_<x>_<y>.json) as
--               strokes by class, and from STREETS the streets of the blocks under the view
--               (native.mapRoads); from EXACT the blocks alone, their lines are the true ones.
--
-- Nothing here stalls a frame: a road tile is read as text and taken apart a slice a frame (no
-- JSON decode of a megabyte at once: that was the stutter of a panned map), its points are kept
-- as Mercator numbers in plain Lua arrays, and a frame only walks the lines whose box touches the
-- view. Every point drawn is a call into the engine (0.4-0.5 us, and the stroke's corners after
-- it), so a frame has a budget of them: the classes take it in the order of their weight (a
-- motorway before a street), bends under MIN_PX of the drawn level are left out, and what is off
-- the view is not sent at all. A view with more road than the budget is drawn coarser, not with
-- holes: the lighter classes skip more bends from the next frame on (M.coarse) until they fit.
--
-- The walk itself was the cost, not the engine: at zoom 14 over Kyiv 10 of 12 ms went to testing
-- every point of 3800 lines against the bend size. A line keeps its thinned points for the level
-- and the coarseness it was last drawn at (M.coarse moves in steps of STEP, so they stay), and a
-- frame whose view, lines and classes are those of the last one sends the last one's points again.
local M = {}
local floor, max, min, sqrt, log = math.floor, math.max, math.min, math.sqrt, math.log

M.BUDGET = 9000          -- path points sent to the engine a frame (a cased line counts twice)
M.COARSEST = 6           -- times MIN_PX a crowded view may skip
M.STEP = 1.4             -- M.coarse goes up and down by this
M.SLICE = .0025          -- s of taking tiles apart a frame (os.clock)
M.MIN_PX = 2.2           -- a bend smaller than this is not drawn
M.RASTER_FROM, M.RASTER_TO = 5, 10
M.VECTOR = 10.5          -- from this zoom the lines are drawn as strokes
M.TERTIARY = 11.5        -- tertiary roads from this zoom
M.STREETS = 13.2         -- the blocks' streets from this zoom
M.LANES = 15.5           -- service roads and tracks from this zoom
M.EXACT = 14.5           -- from this zoom the blocks' lines replace the simplified ones
M.KEEP_TILES, M.KEEP_POINTS = 48, 900000
M.TEX_LOADS, M.TEX_KEEP = 4, 220

local function mercUnit(lat, lon)
  local s = math.sin(math.rad(max(-85.05, min(85.05, lat))))
  return (lon + 180) / 360, .5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)
end

-- --- tiles of lines --------------------------------------------------------------------------
-- A line: {class, n, xs, ys (Mercator 0..1), x0, y0, x1, y1 (its box), key (the same line of the
-- next tile over)}. class: 1 motorway..primary, 2 secondary, 3 tertiary, 4 a street, 5 the rest.
local tiles, tileCount, pointCount, clock = {}, 0, 0, 0
local job
local seen, frameNo = {}, 0
M.stats = {tiles = 0, points = 0, parsed = 0, sent = 0, lines = 0, cut = false}
M.coarse = 1             -- how much more than MIN_PX the lighter classes skip now

local function newLine(class, xs, ys, n, key)
  local x0, y0, x1, y1 = math.huge, math.huge, -math.huge, -math.huge
  for k = 1, n do
    local x, y = xs[k], ys[k]
    if x < x0 then x0 = x end
    if x > x1 then x1 = x end
    if y < y0 then y0 = y end
    if y > y1 then y1 = y end
  end
  return {class = class, n = n, xs = xs, ys = ys, x0 = x0, y0 = y0, x1 = x1, y1 = y1, key = key}
end
M.newLine = newLine

-- The lines of a road tile's text ([{"rank":1,"box":[..],"geo":[lat,lon,..]},..], build_map.py
-- road_tiles), without a JSON decode; pause() may yield. A file written another way goes through
-- decode (jsonDecode in the game) whole.
function M.parse(text, pause, decode)
  local lines, n = {}, 0
  for rank, geo in text:gmatch('"rank":(%d+),"box":%[[^%]]*%],"geo":%[([^%]]*)%]') do
    local xs, ys, k, lat = {}, {}, 0, nil
    for v in geo:gmatch('[^,]+') do
      local num = tonumber(v)
      if num then
        if lat then
          k = k + 1
          xs[k], ys[k] = mercUnit(lat, num)
          lat = nil
        else
          lat = num
        end
      end
    end
    if k >= 2 then
      n = n + 1
      lines[n] = newLine(tonumber(rank) or 3, xs, ys, k, #geo .. ':' .. geo:sub(1, 44))
    end
    if pause and n % 12 == 0 then pause() end
  end
  if n == 0 and decode and text:find('"geo"', 1, true) then
    local ok, data = pcall(decode, text)
    for _, item in ipairs(ok and type(data) == 'table' and data or {}) do
      local g = type(item) == 'table' and item.geo
      if type(g) == 'table' and #g >= 4 then
        local xs, ys, k = {}, {}, 0
        for i = 1, #g - 1, 2 do
          k = k + 1
          xs[k], ys[k] = mercUnit(g[i], g[i + 1])
        end
        n = n + 1
        lines[n] = newLine(tonumber(item.rank) or 3, xs, ys, k, #g .. ':' .. g[1] .. ',' .. g[2] .. ',' .. g[#g])
      end
    end
  end
  return lines
end

-- the level 11 tiles of each sidecar, as arrays ({w, s, e, n, path}), once per catalog revision
local levelRev, levelTiles = nil, {}
local function tilesOfLevel(catalog, level)
  if levelRev ~= catalog.revision then levelRev, levelTiles = catalog.revision, {} end
  local list = levelTiles[level]
  if not list then
    list = {}
    for _, c in ipairs(catalog.catalogs()) do
      for _, t in pairs(c.index.tiles) do
        if t.zoom == level and type(t.file) == 'string' and t.file:match('^[%d_%-]+%.json$') and type(t.box) == 'table' then
          list[#list + 1] = {t.box[1], t.box[2], t.box[3], t.box[4], c.root .. t.file}
        end
      end
    end
    table.sort(list, function(a, b) return a[5] < b[5] end)
    levelTiles[level] = list
  end
  return list
end

local function evict()
  while tileCount > M.KEEP_TILES or (pointCount > M.KEEP_POINTS and tileCount > 4) do
    local oldest, at
    for path, t in pairs(tiles) do
      if t.lines and t.used < clock and (not at or t.used < at) then oldest, at = path, t.used end
    end
    if not oldest then return end
    pointCount, tileCount = pointCount - tiles[oldest].points, tileCount - 1
    tiles[oldest] = nil
    seen = {}
  end
end

-- The parsed tiles of `level` under the box, into out (an array, emptied first); the nearest
-- missing one to the box's middle is read and taken apart, SLICE a frame.
-- read(path) -> text or nil; decode: see parse.
function M.sidecar(catalog, level, west, south, east, north, out, read, decode)
  clock = clock + 1
  local count, missing, missingD = 0, nil, nil
  local midLon, midLat = (west + east) / 2, (south + north) / 2
  for _, t in ipairs(tilesOfLevel(catalog, level)) do
    if t[1] <= east and t[3] >= west and t[2] <= north and t[4] >= south then
      local hit = tiles[t[5]]
      if hit then
        hit.used = clock
        if hit.lines then count = count + 1; out[count] = hit.lines end
      else
        local d = ((t[1] + t[3]) / 2 - midLon) ^ 2 + ((t[2] + t[4]) / 2 - midLat) ^ 2
        if not missingD or d < missingD then missing, missingD = t[5], d end
      end
    end
  end
  for k = count + 1, #out do out[k] = nil end
  if job and not tiles[job.path] then job = nil end   -- dropped with its catalogs
  if not job and missing then
    tiles[missing] = {used = clock, points = 0}
    tileCount = tileCount + 1
    local path = missing
    job = {path = path, co = coroutine.create(function(start)
      local ok, text = pcall(read, path)
      if not ok or type(text) ~= 'string' then return {} end
      start = coroutine.yield()
      local function pause()
        if os.clock() - start > M.SLICE then start = coroutine.yield() end
      end
      return M.parse(text, pause, decode)
    end)}
  end
  if job then
    local ok, lines = coroutine.resume(job.co, os.clock())
    if not ok or coroutine.status(job.co) == 'dead' then
      local t = tiles[job.path]
      job = nil
      if t then
        t.lines = ok and type(lines) == 'table' and lines or {}
        local points = 0
        for _, line in ipairs(t.lines) do points = points + line.n end
        t.points, pointCount = points, pointCount + points
        M.stats.parsed = M.stats.parsed + 1
        evict()
      end
    end
  end
  M.stats.tiles, M.stats.points = tileCount, pointCount
  return count
end

function M.busy() return job ~= nil end

-- a block's line of native.mapRoads ({rank, geo = {lat, lon, ..}, box}) as a line of ours, once
function M.ofBlock(line)
  local m = line.m
  if not m then
    local g, xs, ys, k = line.geo, {}, {}, 0
    for i = 1, #g - 1, 2 do
      k = k + 1
      xs[k], ys[k] = mercUnit(g[i], g[i + 1])
    end
    -- the blocks know three ranks: motorway..secondary, tertiary and streets, the rest
    m = newLine(line.rank == 1 and 1 or line.rank == 2 and 4 or 5, xs, ys, k, nil)
    line.m = m
  end
  return m
end

-- --- drawing ---------------------------------------------------------------------------------
-- style[class] = {width, colour, casing width or nil, casing colour}: by drawn level, on the
-- chart or over a photograph. Colours are made once per look (col: r, g, b, a -> the engine's).
local looks = {}
local function styleOf(col, level, photo)
  local key = (photo and 100 or 0) + level
  local s = looks[key]
  if s then return s end
  local wide = level >= 16 and 2 or level >= 14 and 1.5 or level >= 12 and 1.15 or 1
  if photo then
    s = {
      {3.2 * wide, col(1, .86, .42, .96), 5.2 * wide, col(.10, .08, .05, .78)},
      {2.4 * wide, col(1, .95, .70, .92), 4.2 * wide, col(.10, .08, .05, .66)},
      {1.9 * wide, col(1, 1, 1, .88), level >= 13 and 3.5 * wide or nil, col(.08, .08, .08, .55)},
      {1.4 * wide, col(1, 1, 1, .66)},
      {1, col(1, 1, 1, .42)},
    }
  else
    s = {
      {3.2 * wide, col(.99, .80, .36), 5.2 * wide, col(.72, .42, .10)},
      {2.4 * wide, col(1, .93, .62), 4.2 * wide, col(.66, .56, .30)},
      {1.9 * wide, col(1, 1, 1), 3.5 * wide, col(.62, .63, .65)},
      {level >= 15 and 2.4 * wide or 1.5, level >= 15 and col(1, 1, 1) or col(.60, .62, .65),
        level >= 15 and 3.8 * wide or nil, col(.66, .67, .69)},
      {1, col(.70, .71, .73)},
    }
  end
  looks[key] = s
  return s
end
M.styleOf = styleOf

local CLASSES = 5
local picked, pickedN, shorts, shortN = {}, {}, {}, {}
for c = 1, CLASSES do picked[c], pickedN[c], shorts[c], shortN[c] = {}, 0, {}, 0 end

-- A set's grid: GRID cells a Mercator unit (16384: 1.5 km at Kyiv), a cell -> the lines whose box
-- touches it; a line over more than WIDE cells is kept in grid.wide and looked at every frame.
-- Built as the set grows (the blocks' sets are made a few thousand points a frame).
M.GRID, M.GRID_CELLS, M.WIDE = 16384, 160, 64
local function gridOf(set)
  local grid = set.grid
  if not grid then grid = {done = 0, wide = {}}; set.grid = grid end
  local G = M.GRID
  for i = grid.done + 1, #set do
    local line = set[i]
    local cx0, cy0, cx1, cy1 = floor(line.x0 * G), floor(line.y0 * G), floor(line.x1 * G), floor(line.y1 * G)
    if (cx1 - cx0 + 1) * (cy1 - cy0 + 1) > M.WIDE then
      grid.wide[#grid.wide + 1] = line
    else
      for cy = cy0, cy1 do
        for cx = cx0, cx1 do
          local key = cy * 1048576 + cx
          local list = grid[key]
          if not list then list = {}; grid[key] = list end
          list[#list + 1] = line
        end
      end
    end
  end
  grid.done = #set
  return grid
end
M.gridOf = gridOf

-- the walk's view (Mercator units), the least size of a line drawn, the size of a long one, the
-- classes wanted, the set's first class, the lines taken
local W = {}
local function take(line)
  local c = line.class
  if c >= W.from and W.classes[c] and line.f ~= frameNo
    and line.x1 >= W.x0 and line.x0 <= W.x1 and line.y1 >= W.y0 and line.y0 <= W.y1 then
    line.f = frameNo   -- a line in several cells is taken once
    local w, h = line.x1 - line.x0, line.y1 - line.y0
    if w > W.tiny or h > W.tiny then
      local key = line.key
      if not key or seen[key] ~= frameNo then
        if key then seen[key] = frameNo end
        if w > W.long or h > W.long then
          local n = pickedN[c] + 1
          pickedN[c], picked[c][n] = n, line
        else
          local n = shortN[c] + 1
          shortN[c], shorts[c][n] = n, line
        end
        W.lines = W.lines + 1
      end
    end
  end
end
-- the points of a frame: screen pixels, and the runs of them ({first, count} flat) by class
local px, py = {}, {}
local runs, runN = {}, {}
for c = 1, CLASSES do runs[c], runN[c] = {}, 0 end
local P

-- The points of `line` kept at the squared gap `gap` (Mercator units): the first, every one at
-- least that far from the last kept, and the last. Kept on the line (sx, sy, sn) under `key`; the
-- arrays are written over when the key changes, so a line makes them once.
local function thin(line, gap, key)
  local xs, ys, n = line.xs, line.ys, line.n
  local sx, sy = line.sx, line.sy
  if not sx then sx, sy = {}, {}; line.sx, line.sy = sx, sy end
  local lx, ly = xs[1], ys[1]
  sx[1], sy[1] = lx, ly
  local m = 1
  for k = 2, n do
    local x, y = xs[k], ys[k]
    local dx, dy = x - lx, y - ly
    if k == n or dx * dx + dy * dy >= gap then
      m = m + 1
      sx[m], sy[m] = x, y
      lx, ly = x, y
    end
  end
  line.sn, line.sk = m, key
end
M.thin = thin

-- what the last frame drew from: the view, the level, the classes, the sets and their sizes
local last = {}
local function same(sets, v, level, ci, classes, budget)
  local L = last
  local ok = L.rx == v.rx and L.ry == v.ry and L.x0 == v.x0 and L.y0 == v.y0 and L.scale == v.scale
    and L.width == v.width and L.height == v.height and L.level == level and L.ci == ci and L.budget == budget
    and L.n == #sets
  L.rx, L.ry, L.x0, L.y0, L.scale, L.width, L.height = v.rx, v.ry, v.x0, v.y0, v.scale, v.width, v.height
  L.level, L.ci, L.budget, L.n = level, ci, budget, #sets
  for c = 1, CLASSES do
    local on = classes[c] and true or false
    if L[c] ~= on then ok, L[c] = false, on end
  end
  for s = 1, #sets do
    local set, k = sets[s], CLASSES + s * 3
    if L[k] ~= set or L[k + 1] ~= #set or L[k + 2] ~= set.from then
      ok, L[k], L[k + 1], L[k + 2] = false, set, #set, set.from
    end
  end
  return ok
end

-- Draw the lines of `sets` (arrays of arrays of lines; block lines go through ofBlock first; a
-- set's `from` leaves out its classes under that one).
-- v: the view {rx, ry (the map's corner on the screen), x0, y0 (its corner in pixels of the
-- zoom), scale (pixels a Mercator unit at the zoom), width, height}. level: the whole zoom drawn.
-- classes: which are wanted {[1] = true, ..}.
function M.draw(im, dl, col, sets, v, level, photo, classes, budget)
  local style = styleOf(col, level, photo)
  budget = budget or M.BUDGET
  -- the coarseness in whole steps: the thinned points of a line stay valid between frames
  local ci = floor(log(max(1, M.coarse)) / log(M.STEP) + .5)
  if same(sets, v, level, ci, classes, budget) then return M.strokes(im, dl, style) end
  frameNo = frameNo + 1
  local scale = v.scale
  local ux0, uy0 = v.x0 / scale, v.y0 / scale
  local ux1, uy1 = (v.x0 + v.width) / scale, (v.y0 + v.height) / scale
  for c = 1, CLASSES do pickedN[c], shortN[c], runN[c] = 0, 0, 0 end
  -- the lines that touch the view, by class: through the sets' grids where the view covers a few
  -- of their cells, every line of a set where it covers many (a wide view sees most of them)
  W.x0, W.y0, W.x1, W.y1, W.tiny, W.long, W.classes, W.lines = ux0, uy0, ux1, uy1, 1.5 / scale, 48 / scale, classes, 0
  local G = M.GRID
  local gx0, gy0, gx1, gy1 = floor(ux0 * G), floor(uy0 * G), floor(ux1 * G), floor(uy1 * G)
  local cells = (gx1 - gx0 + 1) * (gy1 - gy0 + 1)
  for s = 1, #sets do
    local set = sets[s]
    W.from = set.from or 1   -- a set may give its lighter classes only
    if cells > M.GRID_CELLS then
      for i = 1, #set do take(set[i]) end
    else
      local grid = gridOf(set)
      for i = 1, #grid.wide do take(grid.wide[i]) end
      for gy = gy0, gy1 do
        for gx = gx0, gx1 do
          local list = grid[gy * 1048576 + gx]
          if list then for i = 1, #list do take(list[i]) end end
        end
      end
    end
  end
  local lines = W.lines
  -- the short lines after the long ones: a spent budget leaves out the shortest streets all
  -- over the view, not the last cells or the last block
  for c = 1, CLASSES do
    local list, n, short = picked[c], pickedN[c], shorts[c]
    for i = 1, shortN[c] do n = n + 1; list[n] = short[i] end
    pickedN[c] = n
  end
  -- their points, the heaviest class first, while the budget lasts
  local total, spent, cut = 0, 0, false
  -- in Mercator units of the drawn level: the main roads keep every bend worth drawing, the
  -- rest as many as the budget had room for last frame
  local coarse = M.STEP ^ ci
  local fine = (M.MIN_PX / (256 * 2 ^ level)) ^ 2
  local rough = fine * coarse * coarse
  local fineKey, roughKey = level * 64, level * 64 + 1 + ci
  local ox, oy = v.rx - v.x0, v.ry - v.y0
  -- the view and a margin, so a wide stroke does not end at the edge
  local mx0, my0, mx1, my1 = ux0 - 12 / scale, uy0 - 12 / scale, ux1 + 12 / scale, uy1 + 12 / scale
  for c = 1, CLASSES do
    local cost = style[c][3] and 2 or 1
    local gap, key = fine, fineKey
    if c > 1 then gap, key = rough, roughKey end
    local list, rc, rn = picked[c], runs[c], 0
    for i = 1, pickedN[c] do
      if spent >= budget then cut = true; break end
      local line = list[i]
      if line.sk ~= key then thin(line, gap, key) end
      local xs, ys, n = line.sx, line.sy, line.sn
      local first, count, before = total + 1, 0, total
      local lx, ly = xs[1], ys[1]
      -- outside the view on which sides (a segment with both ends off one side is not drawn)
      local lcode = (lx < mx0 and 1 or lx > mx1 and 2 or 0) + (ly < my0 and 4 or ly > my1 and 8 or 0)
      local pending = true   -- the run's first point is not sent yet
      for k = 2, n do
        local x, y = xs[k], ys[k]
        local code = (x < mx0 and 1 or x > mx1 and 2 or 0) + (y < my0 and 4 or y > my1 and 8 or 0)
        if lcode ~= 0 and code ~= 0 and bit.band(lcode, code) ~= 0 then
          -- off the view: the run ends here
          if count >= 2 then rn = rn + 2; rc[rn - 1], rc[rn] = first, count end
          first, count, pending = total + 1, 0, true
        else
          if pending then
            total = total + 1
            px[total], py[total] = lx * scale + ox, ly * scale + oy
            count, pending = count + 1, false
          end
          total = total + 1
          px[total], py[total] = x * scale + ox, y * scale + oy
          count = count + 1
        end
        lx, ly, lcode = x, y, code
      end
      if count >= 2 then rn = rn + 2; rc[rn - 1], rc[rn] = first, count end
      spent = spent + cost * (total - before)
    end
    runN[c] = rn
    if cut then break end
  end
  if cut then
    M.coarse = min(M.COARSEST, M.STEP ^ (ci + 1))
  elseif ci > 0 and spent < budget * .5 then
    M.coarse = M.STEP ^ (ci - 1)
  end
  M.stats.lines, M.stats.cut = lines, cut
  return M.strokes(im, dl, style)
end

-- The points the last walk kept, as strokes: the lightest class first, a class's casings under
-- all of its fills. Returns the points sent and whether the walk ran out of budget.
function M.strokes(im, dl, style)
  P = P or im.ImVec2(0, 0)
  local lineTo, stroke = im.ImDrawList_PathLineTo, im.ImDrawList_PathStroke
  local sent = 0
  for c = CLASSES, 1, -1 do
    local st, rc = style[c], runs[c]
    for pass = st[3] and 1 or 2, 2 do
      local colour, width = pass == 1 and st[4] or st[2], pass == 1 and st[3] or st[1]
      for r = 1, runN[c], 2 do
        local first, count = rc[r], rc[r + 1]
        for k = first, first + count - 1 do
          P.x, P.y = px[k], py[k]
          lineTo(dl, P)
        end
        stroke(dl, colour, 0, width)
        sent = sent + count
      end
    end
  end
  M.stats.sent = sent
  return sent, M.stats.cut
end

-- --- the overview tiles ----------------------------------------------------------------------
local tex, texCount, texFrame = {}, 0, 0
local rasterKey, rasterList = nil, {}
local A, B, UV0, UV1
M.texture = nil   -- function(path) -> a texture object with texId (world.lua LIMIT.mapTexture); false: none

local function texture(path, loads)
  local t = tex[path]
  if t ~= nil then
    if t then t.used = texFrame end
    return t, loads
  end
  if loads >= M.TEX_LOADS then return nil, loads end
  local ok, obj = pcall(M.texture, path)
  t = ok and obj or false
  tex[path], texCount = t, texCount + 1
  if t then t.used = texFrame end
  return t, loads + 1
end

-- The sidecars' overview tiles of the level nearest the zoom, stretched to it. Each is drawn
-- four times in `rim` a pixel aside and once as it is: the baked lines are thin and brown.
function M.raster(im, dl, col, catalog, v, zoom, photo)
  if not M.texture then return 0 end
  local zr = max(M.RASTER_FROM, min(M.RASTER_TO, floor(zoom + .5)))
  local n = 2 ^ zr
  local size = v.scale / n                       -- a tile on the screen, px
  local tx0, tx1 = floor(v.x0 / size), floor((v.x0 + v.width) / size)
  local ty0, ty1 = max(0, floor(v.y0 / size)), min(n - 1, floor((v.y0 + v.height) / size))
  local key = table.concat({zr, tx0, tx1, ty0, ty1, catalog.revision}, ':')
  if key ~= rasterKey then
    rasterKey = key
    local list, count = rasterList, 0
    for _, c in ipairs(catalog.catalogs()) do
      local raster = c.index.raster
      if raster then
        for x = tx0, tx1 do
          for y = ty0, ty1 do
            local file = raster[zr .. '/' .. (x % n) .. '/' .. y]
            if file and file:match('^r[%d_%-]+%.png$') then
              count = count + 1
              local e = list[count]
              if not e then e = {}; list[count] = e end
              e.path, e.x, e.y = c.root .. file, x, y
            end
          end
        end
      end
    end
    for k = count + 1, #list do list[k] = nil end
  end
  texFrame = texFrame + 1
  A = A or im.ImVec2(0, 0)
  B = B or im.ImVec2(0, 0)
  UV0 = UV0 or im.ImVec2(0, 0)
  UV1 = UV1 or im.ImVec2(1, 1)
  local rim = photo and col(.06, .05, .03, .62) or col(.30, .16, .02, .50)
  local body = photo and col(1, .93, .78, 1) or col(1, 1, 1, 1)
  local ox, oy = v.rx - v.x0, v.ry - v.y0
  local loads, drawn = 0, 0
  local image = im.ImDrawList_AddImage
  for pass = 1, 2 do
    for k = 1, #rasterList do
      local e = rasterList[k]
      local t
      t, loads = texture(e.path, loads)
      if t then
        local x, y = floor(e.x * size + ox + .5), floor(e.y * size + oy + .5)
        local x1, y1 = floor((e.x + 1) * size + ox + .5), floor((e.y + 1) * size + oy + .5)
        if pass == 1 then
          for d = 1, 4 do
            local dx, dy = d == 1 and -1 or d == 2 and 1 or 0, d == 3 and -1 or d == 4 and 1 or 0
            A.x, A.y, B.x, B.y = x + dx, y + dy, x1 + dx, y1 + dy
            image(dl, t.texId, A, B, UV0, UV1, rim)
          end
        else
          A.x, A.y, B.x, B.y = x, y, x1, y1
          image(dl, t.texId, A, B, UV0, UV1, body)
          drawn = drawn + 1
        end
      end
    end
  end
  if texCount > M.TEX_KEEP then
    for path, t in pairs(tex) do
      if not t or texFrame - t.used > 90 then tex[path], texCount = nil, texCount - 1 end
    end
  end
  return drawn
end

function M.reset()
  tiles, tileCount, pointCount, job, seen = {}, 0, 0, nil, {}
  levelRev, levelTiles, rasterKey, tex, texCount = nil, {}, nil, {}, 0
  for k in pairs(last) do last[k] = nil end
end

return M
