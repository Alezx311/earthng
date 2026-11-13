-- The far view (далечінь): the land past the DEM horizon, so a driver sees where the hills,
-- forests, rivers and towns lie. Read from the pack's far rasters (earthng-far-v1,
-- earthng-mapbuilder far: 200 m nodes of the cells' own elevation, a cover class and the built-up
-- share of every 200 m pixel, and the tall buildings) and drawn as nested square levels round the
-- camera (a geometry clipmap): level L steps BASE * 2^L m over N quads a side, a level covers the
-- hole of the next one, and level 0 begins where the 5 km DEM horizon (native.lua) ends.
--
-- The ground keeps its true shape and bends with the Earth (curve(): the drop of a sphere of
-- R_EFF, the Earth's radius with standard refraction), so a driver on a plain sees the land sink
-- under a real horizon line, and hills, forest edges, towns and towers stand over it the way
-- they do outside. An earlier version folded everything past 7.5 km onto a rising bowl to fit a
-- 24 km far plane: the land stood up behind the town like the inside of a dish (user, 13.11).
-- The far plane now reaches the outermost level; haze (FOG) does the depth, not geometry.
--
-- A coarser level is built earlier than the finer ones inside it (it moves on a coarser snap),
-- so the curvature it was bent with belongs to a camera up to 2*sqrt(2) of its steps away; a
-- skirt down from the rim of its hole closes the step that leaves at the seam (Ticino farlod's
-- rule: a coarse edge is never left hanging over the finer tile beside it).
--
-- No collision: every mesh is hidden while the static collision rebuilds (collision.lua, the
-- horizon owner). Forests stand as a canopy over the ground and built-up pixels as blocks at
-- their roofs' mean height; buildings over 30 m stand as boxes.
local M = {}
local okFfi, ffi = pcall(require, 'ffi')
if not okFfi then ffi = nil end
local floor, sqrt, min, max, abs = math.floor, math.sqrt, math.min, math.max, math.abs

local FAR = {
  BASE = 200,              -- level 0 step = the raster step, m
  N = 128,                 -- quads a level side (a multiple of 4)
  LEVELS = 4,              -- 200 m .. 1.6 km: the outermost level reaches N/2 * 1.6 km = 102 km
  DRIFT = 180,             -- the camera moves this far before level 0 is rebuilt (its snap, 2 * BASE)
  DROP = 6,                -- level 0 under the DEM horizon where both are, m
  CANOPY = 16,             -- forest over its ground, m
  RAISED = 3,              -- levels up to this one stand forests and towns up
  BUDGET = 2.2,            -- ms a frame for building
  BAND = 32,               -- rows of a level in one object (~8k triangles: ~15 ms of createMesh)
  LANDMARK_SIGHT = .0006,  -- a tower is drawn while height / distance is over this (30 m: 50 km)
  LANDMARK_MAX = 1800,
  R_EFF = 6371000 / (1 - .13),  -- the Earth's radius bent by standard refraction (k = 0.13), m
  VIEW = 100000,           -- nothing is drawn past this, m (the far plane)
  FOG = 0.000032,          -- haze: 27 % at 10 km, 47 % at 20 km, 96 % at 100 km
  FOG_HEIGHT = 2500,       -- the haze thins with height over this (fogAtmosphereHeight)
  CLEAR = 2000,            -- visibleDistance pad past VIEW
  WHITE = '/levels/e2r_world/art/far_white.png',
}
M.FAR = FAR

-- how far the ground at distance d from the camera lies under the camera's tangent plane, past
-- r0 (the flat near world ends there: the DEM horizon has no curvature of its own)
function M.curve(d, r0)
  r0 = r0 or 0
  if d <= r0 then return 0 end
  return (d * d - r0 * r0) / (2 * FAR.R_EFF)
end

-- the step a level's hole rim may leave against the finer level inside it (see the header), m
function M.skirt(L)
  local s = FAR.BASE * 2 ^ L
  local half = (FAR.N / 4 - 2) * s
  return 8 + 1.5 * half * (2 * math.sqrt(2) * s) / FAR.R_EFF
end

-- class -> {material, sRGB colour, roughness}; earthng/far_preview.py COLOURS is the same order
local CLASS = {
  [0] = {'e2rfar_grass', {.42, .62, .28}, .95},
  {'e2rfar_farmland', {.74, .66, .34}, .95},
  {'e2rfar_meadow', {.50, .66, .32}, .95},
  {'e2rfar_forest', {.10, .32, .12}, .95},
  {'e2rfar_orchard', {.36, .52, .22}, .95},
  {'e2rfar_town', {.62, .58, .52}, .9},
  {'e2rfar_water', {.22, .52, .74}, .12},
  {'e2rfar_paved', {.50, .50, .48}, .9},
  {'e2rfar_park', {.33, .45, .26}, .95},
  {'e2rfar_wetland', {.36, .42, .30}, .95},
  {'e2rfar_bare', {.60, .55, .44}, .95},
  {'e2rfar_scrub', {.36, .42, .27}, .95},
  {'e2rfar_snow', {.90, .92, .95}, .6},
  {'e2rfar_water', {.26, .42, .52}, .12},
  {'e2rfar_rock', {.48, .46, .43}, .95},
}
local FOREST, TOWN, PAVED, WATER, SEA, NO_DATA = 3, 5, 7, 6, 13, 255
local EXTRA = {
  {'e2rfar_canopy', {.08, .26, .10}, .95},
  {'e2rfar_canopy_side', {.06, .18, .07}, .95},
  {'e2rfar_roofs', {.52, .50, .47}, .85},
  {'e2rfar_walls', {.62, .60, .56}, .85},
  {'e2rfar_tower', {.42, .41, .39}, .8},
  {'e2rfar_tower_top', {.28, .28, .28}, .8},
}
-- class ties in a coarser pixel go to the one listed first
local PRIORITY = {WATER, SEA, TOWN, PAVED, FOREST, 1, 2, 4, 8, 9, 10, 11, 12, 14, 0}

local RS               -- the rasters: {list = {}, byRegion = {}, home = raster of the landing region}
local LV = {}          -- built levels: L -> {centre, square, hole, obj names}
local job              -- the coroutine building a batch of levels
local spawned = {}     -- object ids by name
local trackFn, active, atmosphere
local stats = {builds = 0, buildMs = 0, spawnMs = 0, triangles = 0, faces = {}, landmarks = 0, rasters = 0}
M.stats = stats

-- --- rasters ---------------------------------------------------------------------------------

local function u32(s, at)
  local a, b, c, d = s:byte(at, at + 3)
  return a + b * 256 + c * 65536 + d * 16777216
end
local function i32(s, at)
  local v = u32(s, at)
  return v >= 2147483648 and v - 4294967296 or v
end
local function f32(s, at)
  local buf = ffi.new('float[1]')
  ffi.copy(buf, s:sub(at, at + 3), 4)
  return buf[0]
end

-- 2x2 reduction of a level's class/built/roof arrays: the coarser pixel takes the most common
-- class (PRIORITY breaks ties), the mean built share, and the built-weighted roof height
local RANK = {}
for k, c in ipairs(PRIORITY) do RANK[c] = k end
local function reduce(src, nu, nv)
  local mu, mv = math.ceil(nu / 2), math.ceil(nv / 2)
  local cls, built, roof = ffi.new('uint8_t[?]', mu * mv), ffi.new('uint8_t[?]', mu * mv), ffi.new('uint8_t[?]', mu * mv)
  local count = {}
  for v = 0, mv - 1 do
    for u = 0, mu - 1 do
      for k in pairs(count) do count[k] = nil end
      local bsum, rsum, n, best, bestN = 0, 0, 0, NO_DATA, 0
      for dv = 0, 1 do
        local sv = 2 * v + dv
        if sv < nv then
          for du = 0, 1 do
            local su = 2 * u + du
            if su < nu then
              local at = sv * nu + su
              local c = src.cls[at]
              if c ~= NO_DATA then
                local k = (count[c] or 0) + 1
                count[c] = k
                if k > bestN or (k == bestN and (RANK[c] or 99) < (RANK[best] or 99)) then best, bestN = c, k end
                local b = src.built[at]
                bsum, rsum, n = bsum + b, rsum + b * src.roof[at], n + 1
              end
            end
          end
        end
      end
      local at = v * mu + u
      cls[at] = best
      built[at] = n > 0 and floor(bsum / n + .5) or 0
      roof[at] = bsum > 0 and floor(rsum / bsum + .5) or 0
    end
  end
  return {cls = cls, built = built, roof = roof, nu = mu, nv = mv}
end

local function parse(data, region, pause)
  if #data < 33 or data:sub(1, 4) ~= 'EGF1' then return nil end
  local R = {region = region, u0 = i32(data, 6), v0 = i32(data, 10), nu = u32(data, 14), nv = u32(data, 18),
    step = f32(data, 22), sea = f32(data, 26)}
  local nodes, pixels = (R.nu + 1) * (R.nv + 1), R.nu * R.nv
  local at = 30
  if #data < at - 1 + 2 * nodes + 3 * pixels + 4 then return nil end
  R.elev = ffi.new('uint16_t[?]', nodes)
  ffi.copy(R.elev, data:sub(at, at + 2 * nodes - 1), 2 * nodes)
  at = at + 2 * nodes
  local mip0 = {nu = R.nu, nv = R.nv}
  for _, key in ipairs({'cls', 'built', 'roof'}) do
    mip0[key] = ffi.new('uint8_t[?]', pixels)
    ffi.copy(mip0[key], data:sub(at, at + pixels - 1), pixels)
    at = at + pixels
  end
  R.mips = {[0] = mip0}
  for m = 1, FAR.LEVELS - 1 do
    if pause then pause() end
    R.mips[m] = reduce(R.mips[m - 1], R.mips[m - 1].nu, R.mips[m - 1].nv)
  end
  local count = u32(data, at)
  at = at + 4
  -- 32 bytes: 8 f32, kind last. An earlier writer stored 7 f32 and a u8 kind (29 bytes);
  -- both are whole files, the size says which.
  local rest = #data - (at - 1)
  local stride = 0
  if count > 0 and rest >= 32 * count then stride = 32
  elseif count > 0 and rest >= 29 * count then stride = 29 end
  if stride > 0 then
    local fl = ffi.new('float[?]', 8 * count)
    if stride == 32 then
      ffi.copy(fl, data:sub(at, at + stride * count - 1), stride * count)
    else
      local one = ffi.new('float[7]')
      for k = 0, count - 1 do
        -- array indexes, not pointer adds: the game's LuaJIT rejects the add
        ffi.copy(one, data:sub(at + k * stride, at + k * stride + 27), 28)
        for i = 0, 6 do fl[k * 8 + i] = one[i] end
        fl[k * 8 + 7] = data:byte(at + k * stride + 28)
        if pause and k % 500 == 499 then pause() end
      end
    end
    R.markFloats, R.markCount = fl, count
  else
    R.markCount = 0
  end
  return R
end

-- where a region's far raster lives: in its own pack, or the planet's copy for an older pack
local function rasterPaths(r)
  local manifest = r.descriptor and r.descriptor.manifest
  local id = r.descriptor and r.descriptor.id
  local country = r.country and r.country.id
  local out = {}
  if type(manifest) == 'string' and id then
    local root = manifest:match('^(.*)/regions/[^/]+/manifest%.json$')
    if root then out[#out + 1] = root .. '/far/' .. id .. '.bin' end
  end
  if country and id then out[#out + 1] = '/earthng/planet/far/' .. country .. '/' .. id .. '.bin' end
  return out
end

local function loadRaster(r, pause)
  local key = r.descriptor and r.descriptor.id or tostring(r)
  local hit = RS.byRegion[key]
  if hit ~= nil then return hit or nil end
  RS.byRegion[key] = false
  for _, path in ipairs(rasterPaths(r)) do
    local okExists, found = pcall(function() return FS:fileExists(path) end)
    if okExists and found then
      local f = io.open(path, 'rb')
      if f then
        local data = f:read('*a')
        f:close()
        local ok, R = pcall(parse, data, r, pause)
        if ok and R then
          -- its colour map (earthng-far-tex-v1) beside it, when the pack has one
          local dds = path:gsub('%.bin$', '.color.dds')
          local rough = path:gsub('%.bin$', '_r.data.dds')
          local okTex, hasTex = pcall(function() return FS:fileExists(dds) end)
          local okRough, hasRough = pcall(function() return FS:fileExists(rough) end)
          if okTex and hasTex and M.texMaterial then
            R.texMat = M.texMaterial(tostring(key), dds, okRough and hasRough and rough or nil)
            R.texKind = R.texMat and ('farmap_' .. tostring(key):gsub('[^%w]', '_')) or nil
          end
          RS.byRegion[key] = R
          RS.list[#RS.list + 1] = R
          stats.rasters = stats.rasters + 1
          return R
        end
        stats.error = ok and ('bad far raster ' .. path) or tostring(R)
      end
    end
  end
  return nil
end

-- --- sampling ----------------------------------------------------------------------------------

local function pixelOf(R, fx, fy, m)
  local mip = R.mips[m]
  local u = floor((fx / R.step - R.u0) / 2 ^ m)
  local v = floor((fy / R.step - R.v0) / 2 ^ m)
  if u < 0 or v < 0 or u >= mip.nu or v >= mip.nv then return nil end
  return v * mip.nu + u, mip
end

local function hasData(R, fx, fy)
  local at, mip = pixelOf(R, fx, fy, 0)
  return at ~= nil and mip.cls[at] ~= NO_DATA
end

local function heightOf(R, fx, fy)
  local gu, gv = fx / R.step - R.u0, fy / R.step - R.v0
  if gu < 0 or gv < 0 or gu > R.nu or gv > R.nv then return nil end
  local iu, iv = min(floor(gu), R.nu - 1), min(floor(gv), R.nv - 1)
  local tu, tv = gu - iu, gv - iv
  local w, e = R.nu + 1, R.elev
  local k = iv * w + iu
  local a, b, c, d = e[k], e[k + 1], e[k + w], e[k + w + 1]
  if a == 0 or b == 0 or c == 0 or d == 0 then
    -- an edge of the data: the nearest node that has it
    local best, bestD = 0, 9
    if a ~= 0 and tu + tv < bestD then best, bestD = a, tu + tv end
    if b ~= 0 and 1 - tu + tv < bestD then best, bestD = b, 1 - tu + tv end
    if c ~= 0 and tu + 1 - tv < bestD then best, bestD = c, tu + 1 - tv end
    if d ~= 0 and 2 - tu - tv < bestD then best = d end
    if best == 0 then return nil end
    return best / 4 - 500
  end
  return ((a * (1 - tu) + b * tu) * (1 - tv) + (c * (1 - tu) + d * tu) * tv) / 4 - 500
end

-- The other mounted regions in the landing frame: a box and an affine each way, fitted at the
-- box's centre (regions of one UTM zone differ by a translation; across a zone border the turn of
-- ~2 degrees bends less than a raster pixel over the view). A projection per sample point made a
-- whole build take ~5 s of Lua where half the view lies outside the landing region.
local BLOCK = 3200
local function others()
  if RS.others then return RS.others end
  local src, list = RS.source, {}
  local function finite(v) return v == v and v > -2e6 and v < 2e6 end
  for _, r in ipairs(src.regions or {}) do
    local b = r.data and r.data.bounds
    if r ~= src.region and b then
      local x0, y0, x1, y1, ok = math.huge, math.huge, -math.huge, -math.huge, true
      for _, c in ipairs({{b[1], b[2]}, {b[3], b[2]}, {b[3], b[4]}, {b[1], b[4]}}) do
        local x, y = src.localPoint(src.region, c[2], c[1])
        if not (finite(x) and finite(y)) then ok = false; break end
        x0, y0, x1, y1 = min(x0, x), min(y0, y), max(x1, x), max(y1, y)
      end
      if ok and x0 < FAR.VIEW * 2.5 and y0 < FAR.VIEW * 2.5 and x1 > -FAR.VIEW * 2.5 and y1 > -FAR.VIEW * 2.5 then
        local cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        local function to(x, y) local lon, lat = src.geographic(src.region, x, y); return src.localPoint(r, lat, lon) end
        local ax, ay = to(cx, cy)
        local bx, by = to(cx + 1000, cy)
        local qx, qy = to(cx, cy + 1000)
        local a = {cx, cy, ax, ay, (bx - ax) / 1000, (by - ay) / 1000, (qx - ax) / 1000, (qy - ay) / 1000}
        -- and back: the inverse of the 2x2 part
        local det = a[5] * a[8] - a[7] * a[6]
        if det ~= 0 and finite(ax) and finite(ay) then
          a.i = {a[8] / det, -a[7] / det, -a[6] / det, a[5] / det}
          list[#list + 1] = {r = r, a = a, box = {x0 - 2000, y0 - 2000, x1 + 2000, y1 + 2000}}
        end
      end
    end
  end
  RS.others = list
  return list
end

-- landing frame -> region frame, and back
local function toRegion(o, x, y)
  local a = o.a
  local dx, dy = x - a[1], y - a[2]
  return a[3] + a[5] * dx + a[7] * dy, a[4] + a[6] * dx + a[8] * dy
end
local function fromRegion(o, fx, fy)
  local a, i = o.a, o.a.i
  local dx, dy = fx - a[3], fy - a[4]
  return a[1] + i[1] * dx + i[2] * dy, a[2] + i[3] * dx + i[4] * dy
end

-- the other regions whose box reaches a BLOCK square of the landing frame
local function candidates(x, y)
  local bu, bv = floor(x / BLOCK), floor(y / BLOCK)
  local key = (bu + 32768) * 65536 + bv + 32768
  local cache = RS.blocks
  local hit = cache[key]
  if hit then return hit end
  hit = {}
  local x0, y0 = bu * BLOCK, bv * BLOCK
  for _, o in ipairs(others()) do
    local b = o.box
    if b[1] <= x0 + BLOCK and b[3] >= x0 and b[2] <= y0 + BLOCK and b[4] >= y0 then hit[#hit + 1] = o end
  end
  cache[key] = hit
  return hit
end

-- the raster with data at landing-frame (x, y) and the point in its region's frame
local function rasterAt(x, y)
  local home = RS.home
  if home and hasData(home, x, y) then return home, x, y end
  RS.blocks = RS.blocks or {}
  local last = RS.last
  if last then
    local fx, fy = toRegion(last, x, y)
    if last.R and hasData(last.R, fx, fy) then return last.R, fx, fy end
  end
  for _, o in ipairs(candidates(x, y)) do
    if o ~= last then
      if o.R == nil then
        o.R = loadRaster(o.r, RS.pause) or false
        if o.R then o.R.other = o end
      end
      if o.R then
        local fx, fy = toRegion(o, x, y)
        if hasData(o.R, fx, fy) then RS.last = o; return o.R, fx, fy end
      end
    end
  end
  return nil
end

-- the height a far node is drawn at: its ground, bent down by the Earth past the near world
local function bent(h, x, y, cam)
  local dx, dy = x - cam.x, y - cam.y
  return h - M.curve(sqrt(dx * dx + dy * dy), cam.r0)
end

-- --- meshes ------------------------------------------------------------------------------------

-- The mesh output as FFI structs in the game, as generator.lua makes it: vertices and normals
-- the game's vec3, corners {int v, n, u}, UVs {double u, v}; createMesh reads them by field name.
-- A table a vertex, a normal, a UV and a corner made a whole far build ~35 MB of tables the
-- collector walks, and the engine's own full collection comes at 4/3 of the heap (gc.lua).
-- Outside the game (lupa tests, no vec3): plain tables.
local POINT, CORNER, MESHUV
if ffi and rawget(_G, 'vec3') ~= nil then
  local found, ct = pcall(ffi.typeof, 'struct __luaVec3_t')
  POINT = found and ct or vec3
  pcall(ffi.cdef, 'typedef struct { int32_t v, n, u; } e2r_face_t; typedef struct { double u, v; } e2r_uv_t;')
  local okF, face = pcall(ffi.typeof, 'e2r_face_t')
  local okU, uv = pcall(ffi.typeof, 'e2r_uv_t')
  if okF and okU then CORNER, MESHUV = face, uv end
end
POINT = POINT or function(x, y, z) return {x = x, y = y, z = z} end
CORNER = CORNER or function(v, n, u) return {v = v, n = n, u = u} end
MESHUV = MESHUV or function(u, v) return {u = u, v = v} end

local UV0 = {MESHUV(0, 0)}

local function newMesh(material, textured)
  return {verts = {}, normals = {}, uvs = textured and {} or UV0, faces = {}, material = material}
end

-- a vertex with its own texture coordinate (a mesh made by newMesh(name, true))
local function tvert(m, x, y, z, nx, ny, nz, u, v)
  local k = #m.verts
  m.verts[k + 1] = POINT(x, y, z)
  m.normals[k + 1] = POINT(nx, ny, nz)
  m.uvs[k + 1] = MESHUV(u, v)
  return CORNER(k, k, k)
end

-- the colour map coordinate of landing-frame (x, y) in raster R (row 0 of the map is north)
local function texUV(R, x, y)
  local fx, fy = x, y
  if R.other then fx, fy = toRegion(R.other, x, y) end
  return (fx / R.step - R.u0) / R.nu, 1 - (fy / R.step - R.v0) / R.nv
end

local function vert(m, x, y, z, nx, ny, nz)
  local k = #m.verts
  m.verts[k + 1] = POINT(x, y, z)
  m.normals[k + 1] = POINT(nx, ny, nz)
  return CORNER(k, k, 0)
end

local function tri(m, a, b, c)
  local f = m.faces
  local n = #f
  f[n + 1], f[n + 2], f[n + 3] = a, b, c
end

-- a vertical wall from P to Q (anti-clockwise round the solid seen from above), bottom b to top t
local function wall(m, px, py, pb, pt, qx, qy, qb, qt)
  local dx, dy = qx - px, qy - py
  local l = sqrt(dx * dx + dy * dy)
  if l < 1e-6 then return end
  local nx, ny = dy / l, -dx / l
  local a = vert(m, px, py, pb, nx, ny, 0)
  local b = vert(m, px, py, pt, nx, ny, 0)
  local c = vert(m, qx, qy, qt, nx, ny, 0)
  local d = vert(m, qx, qy, qb, nx, ny, 0)
  tri(m, a, b, c)
  tri(m, a, c, d)
end

-- an up-facing quad from four corner refs (anti-clockwise from above: 00, 10, 11, 01)
local function quad(m, a, b, c, d)
  tri(m, a, c, b)
  tri(m, a, d, c)
end

local function finish(meshes)
  local out, verts, faces = {}, 0, 0
  for _, m in pairs(meshes) do
    if #m.faces > 0 then
      out[#out + 1] = m
      verts, faces = verts + #m.verts, faces + #m.faces / 3
    end
  end
  return out, verts, faces
end

-- --- levels ------------------------------------------------------------------------------------

local function snap(v, s) return floor(v / s + .5) * s end

-- the squares and holes of every level for a camera at p: level L covers the hole of level L+1
-- (a square aligned to L+1's grid, inside the natural square of L), level 0 the ring from the
-- DEM horizon out to that hole
local function plan(p, holeR)
  local out, N, top = {}, FAR.N, FAR.LEVELS - 1
  for L = 0, top do
    local s = FAR.BASE * 2 ^ L
    local o = {s = s, cx = snap(p.x, 2 * s), cy = snap(p.y, 2 * s)}
    if L > 0 then
      local h = (N / 4 - 2) * s
      o.hole = {o.cx - h, o.cy - h, o.cx + h, o.cy + h}
    end
    out[L] = o
  end
  local h = N / 2 * out[top].s
  out[top].square = {out[top].cx - h, out[top].cy - h, out[top].cx + h, out[top].cy + h}
  for L = top - 1, 0, -1 do out[L].square = out[L + 1].hole end
  out[0].circle = {p.x, p.y, holeR}
  return out
end

-- the drop of level 0 where it lies under the DEM horizon (0 past it)
local function nearDrop(d, holeR)
  local a, b = holeR + 1000, holeR + 1400
  if d <= a then return FAR.DROP end
  if d >= b then return 0 end
  return FAR.DROP * (b - d) / (b - a)
end

local function buildLevel(L, P, cam, pause, out)
  local o = P[L]
  local s, sq = o.s, o.square
  local nx, ny = floor((sq[3] - sq[1]) / s + .5), floor((sq[4] - sq[2]) / s + .5)
  local w = nx + 1
  local H = {}
  local circle = o.circle
  local hole = o.hole
  -- a node is needed when a quad round it is drawn: not deep in the hole, not past the view
  local inner = hole and {hole[1] + s, hole[2] + s, hole[3] - s, hole[4] - s}
  local view2 = (FAR.VIEW + 2 * s) ^ 2
  -- heights
  for b = 0, ny do
    local y = sq[2] + b * s
    local dy2 = (y - cam.y) ^ 2
    for a = 0, nx do
      local x = sq[1] + a * s
      local h
      if not (inner and x > inner[1] and x < inner[3] and y > inner[2] and y < inner[4]) and (x - cam.x) ^ 2 + dy2 <= view2 then
        local R, fx, fy = rasterAt(x, y)
        h = R and heightOf(R, fx, fy)
      end
      if h then
        if circle then h = h - nearDrop(sqrt((x - circle[1]) ^ 2 + (y - circle[2]) ^ 2), circle[3]) end
        H[b * w + a + 1] = bent(h, x, y, cam)
      else
        H[b * w + a + 1] = false
      end
    end
    pause()
  end
  -- the outer edge meets the coarser level: its odd nodes lie on the coarse level's edges
  if L < FAR.LEVELS - 1 then
    local function mid(k1, k, k2)
      local h1, h2 = H[k1], H[k2]
      if H[k] and h1 and h2 then H[k] = (h1 + h2) / 2 end
    end
    for a = 1, nx - 1, 2 do
      mid(a, a + 1, a + 2)
      mid(ny * w + a, ny * w + a + 1, ny * w + a + 2)
    end
    for b = 1, ny - 1, 2 do
      mid((b - 1) * w + 1, b * w + 1, (b + 1) * w + 1)
      mid((b - 1) * w + w, b * w + w, (b + 1) * w + w)
    end
  end
  -- pixel classes, built share, roofs per quad
  local Q, T = {}, {}       -- class (or false: skip), raised top over the ground (0: flat)
  local RQ, LQ = {}, {}     -- a textured quad's raster, and how far its land stands up (canopy, roofs)
  local raised = L <= FAR.RAISED
  local inHole = {}         -- quads skipped for the finer level (their rim gets a skirt)
  for b = 0, ny - 1 do
    local y0 = sq[2] + b * s
    for a = 0, nx - 1 do
      local x0 = sq[1] + a * s
      local k = b * nx + a + 1
      local skip = hole and x0 >= hole[1] and x0 + s <= hole[3] and y0 >= hole[2] and y0 + s <= hole[4]
      if skip then inHole[k] = true end
      if not skip and circle then
        local cx, cy = x0 + s / 2 - circle[1], y0 + s / 2 - circle[2]
        skip = cx * cx + cy * cy < circle[3] * circle[3]
      end
      if not skip then
        -- the quad's nearest point to the camera past the far plane
        local qx, qy = max(x0, min(cam.x, x0 + s)), max(y0, min(cam.y, y0 + s))
        skip = (qx - cam.x) ^ 2 + (qy - cam.y) ^ 2 > FAR.VIEW * FAR.VIEW
      end
      local h00, h10, h01, h11 = H[b * w + a + 1], H[b * w + a + 2], H[(b + 1) * w + a + 1], H[(b + 1) * w + a + 2]
      if skip or not (h00 and h10 and h01 and h11) then
        Q[k], T[k] = false, 0
      else
        local R, fx, fy = rasterAt(x0 + s / 2, y0 + s / 2)
        local c, top = 0, 0
        if R then
          local at, mip = pixelOf(R, fx, fy, L)
          if at then
            c = mip.cls[at]
            if c == NO_DATA then c = 0 end
            if R.texMat then
              -- the colour map draws the land; forests and towns only swell up (see the lift below)
              RQ[k] = R
              if raised then
                if c == FOREST then
                  LQ[k] = FAR.CANOPY
                elseif mip.built[at] > 12 then
                  LQ[k] = min(18, mip.roof[at] * mip.built[at] / 255 * .8)
                end
              end
            elseif raised then
              if c == FOREST then
                top = FAR.CANOPY
              elseif (c == TOWN or c == PAVED) and mip.built[at] > 12 then
                local share = mip.built[at] / 255
                top = mip.roof[at] * min(1, .45 + share * 1.6)
                if top < 3 then top = 0 end
              end
            end
          end
        end
        Q[k], T[k] = c, top
      end
    end
    pause()
  end
  -- Textured land swells where forests and towns stand: a node rises by the mean lift of the
  -- quads round it, so a forest edge is a slope one quad wide and a wood a soft dome, not a box.
  -- No lift on a level's outer edge or its hole rim (the levels meet there), nor where level 0
  -- still lies under the DEM horizon.
  local HL = H
  if next(RQ) then
    HL = {}
    for b = 0, ny do
      for a = 0, nx do
        local k = b * w + a + 1
        local h = H[k]
        if h and a > 0 and b > 0 and a < nx and b < ny then
          local sum, n, rim = 0, 0, false
          for i = 1, 4 do
            local q = (i <= 2 and b - 1 or b) * nx + a + (i % 2 == 0 and 1 or 0)
            if inHole[q] then rim = true end
            if Q[q] then sum, n = sum + (LQ[q] or 0), n + 1 end
          end
          if not rim and n > 0 and sum > 0 then
            local lift = sum / 4
            if circle then
              local d = sqrt((sq[1] + a * s - circle[1]) ^ 2 + (sq[2] + b * s - circle[2]) ^ 2)
              lift = lift * max(0, min(1, (d - circle[3] - 1400) / 1000))
            end
            h = h + lift
          end
        end
        HL[k] = h
      end
    end
  end
  -- normals from the grid
  local Nn = {}
  local function hAt(a, b)
    a, b = max(0, min(nx, a)), max(0, min(ny, b))
    return H[b * w + a + 1]
  end
  local function hlAt(a, b)
    a, b = max(0, min(nx, a)), max(0, min(ny, b))
    return HL[b * w + a + 1]
  end
  -- ground
  -- meshes per band of BAND rows: a band is one object, made in a frame of its own
  local bands = {}
  local band = 0
  local function mesh(name, textured)
    local set = bands[band]
    if not set then set = {meshes = {}, refs = {}}; bands[band] = set end
    local m = set.meshes[name]
    if not m then m = newMesh(name, textured); set.meshes[name] = m end
    return m
  end
  local ox, oy = o.cx, o.cy
  -- node (a, b) of a quad of the current band in material `name` (shared within the band)
  local function node(name, a, b)
    local m = mesh(name)
    local refsBy = bands[band].refs
    local map = refsBy[name]
    if not map then map = {}; refsBy[name] = map end
    local k = b * w + a + 1
    local ref = map[k]
    if ref then return ref end
    local n = Nn[k]
    if not n then
      local h = H[k]
      local hl, hr, hd, hu = hAt(a - 1, b) or h, hAt(a + 1, b) or h, hAt(a, b - 1) or h, hAt(a, b + 1) or h
      local gx, gy = (hr - hl) / (2 * s), (hu - hd) / (2 * s)
      local l = sqrt(gx * gx + gy * gy + 1)
      n = POINT(-gx / l, -gy / l, 1 / l)
      Nn[k] = n
    end
    ref = vert(m, sq[1] + a * s - ox, sq[2] + b * s - oy, H[k], n.x, n.y, n.z)
    map[k] = ref
    return ref
  end
  -- node (a, b) on raster R's colour map (its material), lifted
  local TN = {}
  local function tnode(R, a, b)
    local name = R.texMat
    local m = mesh(name, true)
    local refsBy = bands[band].refs
    local map = refsBy[name]
    if not map then map = {}; refsBy[name] = map end
    local k = b * w + a + 1
    local ref = map[k]
    if ref then return ref end
    local n = TN[k]
    if not n then
      local h = HL[k]
      local hl, hr, hd, hu = hlAt(a - 1, b) or h, hlAt(a + 1, b) or h, hlAt(a, b - 1) or h, hlAt(a, b + 1) or h
      local gx, gy = (hr - hl) / (2 * s), (hu - hd) / (2 * s)
      local l = sqrt(gx * gx + gy * gy + 1)
      n = POINT(-gx / l, -gy / l, 1 / l)
      TN[k] = n
    end
    local x, y = sq[1] + a * s, sq[2] + b * s
    local u, v = texUV(R, x, y)
    ref = tvert(m, x - ox, y - oy, HL[k], n.x, n.y, n.z, u, v)
    map[k] = ref
    return ref
  end
  -- a skirt on R's colour map from node P down `depth` to node Q (facing right of P -> Q)
  local function twall(R, pa, pb, qa, qb, depth)
    local m = mesh(R.texMat, true)
    local px, py, qx, qy = sq[1] + pa * s, sq[2] + pb * s, sq[1] + qa * s, sq[2] + qb * s
    local hp, hq = HL[pb * w + pa + 1], HL[qb * w + qa + 1]
    local dx, dy = qx - px, qy - py
    local l = sqrt(dx * dx + dy * dy)
    local wx, wy = dy / l, -dx / l
    local pu, pv = texUV(R, px, py)
    local qu, qv = texUV(R, qx, qy)
    local A = tvert(m, px - ox, py - oy, hp - depth, wx, wy, 0, pu, pv)
    local B = tvert(m, px - ox, py - oy, hp, wx, wy, 0, pu, pv)
    local C = tvert(m, qx - ox, qy - oy, hq, wx, wy, 0, qu, qv)
    local D = tvert(m, qx - ox, qy - oy, hq - depth, wx, wy, 0, qu, qv)
    tri(m, A, B, C)
    tri(m, A, C, D)
  end
  local tops = 0
  for b = 0, ny - 1 do
    band = floor(b / FAR.BAND)
    for a = 0, nx - 1 do
      local k = b * nx + a + 1
      local c = Q[k]
      local R = RQ[k]
      if c and R then
        quad(mesh(R.texMat, true), tnode(R, a, b), tnode(R, a + 1, b), tnode(R, a + 1, b + 1), tnode(R, a, b + 1))
      elseif c and T[k] == 0 then
        local name = CLASS[c] and CLASS[c][1] or CLASS[0][1]
        quad(mesh(name), node(name, a, b), node(name, a + 1, b), node(name, a + 1, b + 1), node(name, a, b + 1))
      elseif c then
        tops = tops + 1
      end
    end
    if b % 8 == 7 then pause() end
  end
  -- forests and towns: a top over the ground and walls where the neighbour is lower
  if tops > 0 then
    for b = 0, ny - 1 do
      band = floor(b / FAR.BAND)
      for a = 0, nx - 1 do
        local k = b * nx + a + 1
        local t = T[k]
        if Q[k] and t > 0 then
          local forest = Q[k] == FOREST
          local topName = forest and 'e2rfar_canopy' or 'e2rfar_roofs'
          local sideName = forest and 'e2rfar_canopy_side' or 'e2rfar_walls'
          local topM, sideM = mesh(topName), mesh(sideName)
          local x0, y0 = sq[1] + a * s - ox, sq[2] + b * s - oy
          local x1, y1 = x0 + s, y0 + s
          local h00, h10, h11, h01 = H[b * w + a + 1], H[b * w + a + 2], H[(b + 1) * w + a + 2], H[(b + 1) * w + a + 1]
          if forest then
            -- one canopy: neighbouring forest quads share their corners
            quad(topM, node(topName, a, b), node(topName, a + 1, b), node(topName, a + 1, b + 1), node(topName, a, b + 1))
          else
            local hm = max(h00, h10, h11, h01)
            local z = hm + t
            quad(topM, vert(topM, x0, y0, z, 0, 0, 1), vert(topM, x1, y0, z, 0, 0, 1),
              vert(topM, x1, y1, z, 0, 0, 1), vert(topM, x0, y1, z, 0, 0, 1))
            h00, h10, h11, h01 = z - t, z - t, z - t, z - t
          end
          local function lower(na, nb)
            if na < 0 or nb < 0 or na >= nx or nb >= ny then return true end
            local nk = nb * nx + na + 1
            return not Q[nk] or T[nk] < t - .5 or (forest and Q[nk] ~= FOREST)
          end
          local sink = 3
          if lower(a, b - 1) then wall(sideM, x0, y0, H[b * w + a + 1] - sink, h00 + t, x1, y0, H[b * w + a + 2] - sink, h10 + t) end
          if lower(a + 1, b) then wall(sideM, x1, y0, H[b * w + a + 2] - sink, h10 + t, x1, y1, H[(b + 1) * w + a + 2] - sink, h11 + t) end
          if lower(a, b + 1) then wall(sideM, x1, y1, H[(b + 1) * w + a + 2] - sink, h11 + t, x0, y1, H[(b + 1) * w + a + 1] - sink, h01 + t) end
          if lower(a - 1, b) then wall(sideM, x0, y1, H[(b + 1) * w + a + 1] - sink, h01 + t, x0, y0, H[b * w + a + 1] - sink, h00 + t) end
        end
      end
      if b % 8 == 7 then pause() end
    end
  end
  -- skirts down from the rim of the hole, facing the camera inside it
  if hole then
    local depth = M.skirt(L)
    for b = 0, ny - 1 do
      band = floor(b / FAR.BAND)
      for a = 0, nx - 1 do
        local k = b * nx + a + 1
        local c = Q[k]
        local R = RQ[k]
        if c and R then
          if a > 0 and inHole[k - 1] then twall(R, a, b + 1, a, b, depth) end
          if a < nx - 1 and inHole[k + 1] then twall(R, a + 1, b, a + 1, b + 1, depth) end
          if b > 0 and inHole[k - nx] then twall(R, a, b, a + 1, b, depth) end
          if b < ny - 1 and inHole[k + nx] then twall(R, a + 1, b + 1, a, b + 1, depth) end
        elseif c then
          local name = CLASS[c] and CLASS[c][1] or CLASS[0][1]
          local m = mesh(name)
          local x0, y0 = sq[1] + a * s - ox, sq[2] + b * s - oy
          local x1, y1 = x0 + s, y0 + s
          local h00, h10, h11, h01 = H[b * w + a + 1], H[b * w + a + 2], H[(b + 1) * w + a + 2], H[(b + 1) * w + a + 1]
          if a > 0 and inHole[k - 1] then wall(m, x0, y1, h01 - depth, h01, x0, y0, h00 - depth, h00) end
          if a < nx - 1 and inHole[k + 1] then wall(m, x1, y0, h10 - depth, h10, x1, y1, h11 - depth, h11) end
          if b > 0 and inHole[k - nx] then wall(m, x0, y0, h00 - depth, h00, x1, y0, h10 - depth, h10) end
          if b < ny - 1 and inHole[k + nx] then wall(m, x1, y1, h11 - depth, h11, x0, y1, h01 - depth, h01) end
        end
      end
      if b % 16 == 15 then pause() end
    end
  end
  local built = {bands = {}, pos = {ox, oy, 0}, verts = 0, faces = 0}
  for k, set in pairs(bands) do
    -- the forest canopy's nodes sit CANOPY over the ground
    local canopy, water = set.meshes.e2rfar_canopy, set.meshes.e2rfar_water
    if canopy then for _, v in ipairs(canopy.verts) do v.z = v.z + FAR.CANOPY end end
    if water then for _, v in ipairs(water.verts) do v.z = v.z - 2 end end
    local list, verts, faces = finish(set.meshes)
    if #list > 0 then
      built.bands[#built.bands + 1] = {meshes = list, verts = verts, faces = faces, key = k}
      built.verts, built.faces = built.verts + verts, built.faces + faces
    end
  end
  table.sort(built.bands, function(p, q) return p.key < q.key end)
  out[L] = built
end

-- tall buildings and towers as boxes within sight (height / distance), round p
local function buildLandmarks(p, cam, minD, pause, out)
  local m, top = newMesh('e2rfar_tower'), newMesh('e2rfar_tower_top')
  local src = RS.source
  local picked = {}
  for _, R in ipairs(RS.list) do
    local fl, same = R.markFloats, R.region == src.region
    if not same and not R.other then fl = nil end
    for k = 0, (fl and R.markCount or 0) - 1 do
      local b = 8 * k
      local x, y, h = fl[b], fl[b + 1], fl[b + 3]
      if not same then x, y = fromRegion(R.other, x, y) end
      local d = sqrt((x - p.x) ^ 2 + (y - p.y) ^ 2)
      if d > minD and d < FAR.VIEW and h >= 40 and h > d * FAR.LANDMARK_SIGHT then
        picked[#picked + 1] = {x, y, bent(fl[b + 2], x, y, cam), h, fl[b + 4], fl[b + 5], fl[b + 6], d}
      end
      if k % 512 == 511 then pause() end
    end
  end
  table.sort(picked, function(a, b) return a[4] / a[8] > b[4] / b[8] end)
  local ox, oy = snap(p.x, 1000), snap(p.y, 1000)
  for n = 1, min(#picked, FAR.LANDMARK_MAX) do
    local q = picked[n]
    local x, y, z, h, ha, hb, ang = q[1] - ox, q[2] - oy, q[3], q[4], max(q[5], 4), max(q[6], 4), q[7]
    local c, sn = math.cos(ang), math.sin(ang)
    local corners = {}
    for i, uv in ipairs({{-1, -1}, {1, -1}, {1, 1}, {-1, 1}}) do
      local u, v = uv[1] * ha, uv[2] * hb
      corners[i] = {x + u * c - v * sn, y + u * sn + v * c}
    end
    local z0, z1 = z - 3, z + h
    for i = 1, 4 do
      local P, Qp = corners[i], corners[i % 4 + 1]
      wall(m, P[1], P[2], z0, z1, Qp[1], Qp[2], z0, z1)
    end
    quad(top, vert(top, corners[1][1], corners[1][2], z1, 0, 0, 1), vert(top, corners[2][1], corners[2][2], z1, 0, 0, 1),
      vert(top, corners[3][1], corners[3][2], z1, 0, 0, 1), vert(top, corners[4][1], corners[4][2], z1, 0, 0, 1))
    if n % 256 == 0 then pause() end
  end
  local list, verts, faces = finish({m, top})
  out.marks = {meshes = list, pos = {ox, oy, 0}, verts = verts, faces = faces, count = min(#picked, FAR.LANDMARK_MAX)}
end

-- --- the game side -----------------------------------------------------------------------------

-- the material of one region's colour map: its name, nil when the engine refuses it
local texDone = {}
function M.texMaterial(id, path, roughPath)
  local safe = tostring(id):gsub('[^%w]', '_')
  local name = 'e2rfar_tex_' .. safe
  if texDone[name] ~= nil then return texDone[name] or nil end
  -- with its roughness map the far water is smooth and mirrors the sky, the land is matte
  local function stage()
    if roughPath then return {baseColorMap = path, roughnessMap = roughPath, roughnessFactor = 1, metallicFactor = 0} end
    return {baseColorMap = path, roughnessFactor = .93, metallicFactor = 0}
  end
  local defs = {}
  defs[name] = {name = name, mapTo = name, class = 'Material', version = 1.5, castShadows = false,
    Stages = {stage(), {}, {}, {}}}
  -- the same map for the generator's horizon tiles (kind farmap_<id>, material e2rf_farmap_<id>)
  local horizon = 'e2rf_farmap_' .. safe
  defs[horizon] = {name = horizon, mapTo = horizon, class = 'Material', version = 1.5, castShadows = false,
    Stages = {stage(), {}, {}, {}}}
  local ok = pcall(function()
    local file = 'e2r_world/far_tex_' .. name .. '.json'
    jsonWriteFile(file, defs, false)
    loadJsonMaterialsFile('/' .. file)
  end)
  texDone[name] = ok and name or false
  return ok and name or nil
end

local function materials()
  if M.materialsLoaded then return end
  local defs = {}
  local function add(spec)
    local name, c, rough = spec[1], spec[2], spec[3]
    if defs[name] then return end
    defs[name] = {name = name, mapTo = name, class = 'Material', version = 1.5, castShadows = false,
      Stages = {{baseColorMap = FAR.WHITE, baseColorFactor = {c[1], c[2], c[3], 1}, roughnessFactor = rough,
        metallicFactor = 0}, {}, {}, {}}}
  end
  for c = 0, #CLASS do add(CLASS[c]) end
  for _, spec in ipairs(EXTRA) do add(spec) end
  local ok = pcall(function()
    jsonWriteFile('e2r_world/far_materials.json', defs, false)
    loadJsonMaterialsFile('/e2r_world/far_materials.json')
  end)
  M.materialsLoaded = ok
end

local function group()
  local g = scenetree.findObject('E2R_far')
  if g then return g end
  g = createObject('SimGroup')
  g:registerObject('E2R_far')
  return g
end

local function drop(name)
  local obj = scenetree.findObject(name)
  if obj then obj:delete() end
  spawned[name] = nil
end

-- one object, hidden until its whole batch is in (reveal()): createMesh costs ~1.7 us a
-- triangle, so a band of ~8k triangles is one frame's work, and the old level stays in sight
-- until every band of the new one is there
local function spawnHidden(name, meshes, pos, faces)
  drop(name)
  local t = hptimer()
  local obj = createObject('ProceduralMesh')
  obj:registerObject(name)
  obj.canSave = false
  group():addObject(obj.obj)
  obj:setHidden(true)
  obj:createMesh({meshes})
  obj:setPosition(vec3(pos[1], pos[2], pos[3]))
  spawned[name] = obj:getID()
  if trackFn then pcall(trackFn, obj:getID(), faces) end
  local ms = t:stop()
  stats.spawnMs = stats.spawnMs + ms
  stats.spawnMax = max(stats.spawnMax or 0, ms)
end

local current = {}   -- level (or 'marks') -> names of the objects in sight
local staged         -- the batch going in: {items, next, names = {level -> names}, done}
local gen = 0

-- every object of the batch in sight and the ones they replace gone, in one frame
local function reveal(batch)
  for key, names in pairs(batch.names) do
    for _, name in ipairs(names) do
      local obj = scenetree.findObject(name)
      if obj then obj:setHidden(false) end
    end
    for _, name in ipairs(current[key] or {}) do drop(name) end
    current[key] = names
  end
end

local function apply(on, radius)
  local info = scenetree.findObject('theLevelInfo')
  if not info then return end
  if on then
    if not atmosphere then
      atmosphere = {visible = info:getField('visibleDistance', 0), fog = info:getField('fogDensity', 0),
        height = info:getField('fogAtmosphereHeight', 0)}
    end
    info:setField('visibleDistance', 0, tostring(max(tonumber(atmosphere.visible) or 8000, radius + FAR.CLEAR)))
    info:setField('fogDensity', 0, string.format('%.6f', FAR.FOG))
    info:setField('fogAtmosphereHeight', 0, tostring(FAR.FOG_HEIGHT))
  elseif atmosphere then
    info:setField('visibleDistance', 0, atmosphere.visible)
    info:setField('fogDensity', 0, atmosphere.fog)
    info:setField('fogAtmosphereHeight', 0, atmosphere.height or '700')
    atmosphere = nil
  end
  pcall(function() info:postApply() end)
end

function M.reset()
  for name in pairs(spawned) do drop(name) end
  local g = scenetree.findObject('E2R_far')
  if g then g:delete() end
  spawned, LV, job, RS, staged, current = {}, {}, nil, nil, nil, {}
  stats.faces, stats.triangles = {}, 0
  if active then apply(false) end
  active, M.applied = false, false
end

-- the outer radius drawn now (0: none)
function M.radius()
  return active and FAR.VIEW or 0
end

-- p: the focus (car or free camera); source: native.farSource(); holeR: where the DEM horizon
-- (or the far ring) is sure to have ground round p; track(id, triangles): the collision owner
function M.update(p, source, holeR, track, enabled)
  trackFn = track
  if not enabled or not ffi or not source or not source.region then
    if active then M.reset() end
    return
  end
  if RS and RS.source.region ~= source.region then M.reset() end
  if not RS then
    RS = {list = {}, byRegion = {}, source = source, pause = function() end}
    materials()
    active = true
  end
  if RS.empty then
    stats.state = 'no far data'
    return
  end
  -- resume the batch in progress
  if job then
    local t = hptimer()
    RS.pause = function()
      if t:stop() > FAR.BUDGET then coroutine.yield(); t = hptimer() end
    end
    local ok, err = coroutine.resume(job.co)
    if not ok then
      stats.error, job = tostring(err), nil
      return
    end
    if coroutine.status(job.co) == 'dead' then
      local done = job
      job = nil
      stats.buildMs = stats.buildMs + (done.ms or 0)
      -- the batch goes in a band a frame, hidden; the levels it replaces stay until it is all in
      gen = gen + 1
      local batch = {items = {}, next = 1, names = {}, done = done}
      for L, built in pairs(done.out) do
        if type(L) == 'number' then
          batch.names[L] = {}
          for k, band in ipairs(built.bands) do
            local name = string.format('e2rfar_L%d_%d_g%d', L, k, gen)
            batch.items[#batch.items + 1] = {name = name, meshes = band.meshes, pos = built.pos, faces = band.faces}
            table.insert(batch.names[L], name)
          end
        end
      end
      if done.out.marks then
        batch.names.marks = {}
        if #done.out.marks.meshes > 0 then
          local name = 'e2rfar_marks_g' .. gen
          batch.items[#batch.items + 1] = {name = name, meshes = done.out.marks.meshes, pos = done.out.marks.pos,
            faces = done.out.marks.faces}
          batch.names.marks[1] = name
        end
      end
      staged = batch
    end
    return
  end
  -- the staged batch: one object a frame (a frame the gate opens, world.lua), then all of it at once
  if staged then
    if M.gate and not M.gate() then return end
    local item = staged.items[staged.next]
    if item then
      spawnHidden(item.name, item.meshes, item.pos, item.faces)
      staged.next = staged.next + 1
      M.changed = true
      return
    end
    local done = staged.done
    if not M.applied then apply(true, M.radius()); M.applied = true end
    reveal(staged)
    M.changed = true
    staged = nil
    for L, built in pairs(done.out) do
      if type(L) == 'number' then
        LV[L] = done.plan[L]
        stats.faces['L' .. L] = built.faces
      end
    end
    if done.out.marks then
      LV.marks = {x = done.p.x, y = done.p.y}
      stats.landmarks = done.out.marks.count
      stats.faces.marks = done.out.marks.faces
    end
    stats.triangles = 0
    for _, n in pairs(stats.faces) do stats.triangles = stats.triangles + n end
    stats.builds = stats.builds + 1
    stats.state = 'ready'
    return
  end
  -- what changed: the coarsest level whose centre moved takes every finer one with it
  local P = plan(p, holeR)
  local from = nil
  for L = FAR.LEVELS - 1, 0, -1 do
    local o, old = P[L], LV[L]
    if not old or old.cx ~= o.cx or old.cy ~= o.cy or (L == 0 and ((old.circle[1] - p.x) ^ 2 + (old.circle[2] - p.y) ^ 2 > FAR.DRIFT ^ 2
        or abs(old.circle[3] - holeR) > 200)) then
      from = L
      break
    end
  end
  local marksDue = not LV.marks or (LV.marks.x - p.x) ^ 2 + (LV.marks.y - p.y) ^ 2 > 1500 ^ 2
  if not from and not marksDue then return end
  local pos = {x = p.x, y = p.y}
  local cam = {x = pos.x, y = pos.y, z = p.z or 0, r0 = holeR}
  job = {plan = P, out = {}, p = pos, cam = cam}
  job.co = coroutine.create(function()
    local t = hptimer()
    local pause = function() RS.pause() end
    if not RS.homeTried then
      RS.homeTried = true
      RS.home = loadRaster(source.region, pause)
      if not RS.home then RS.empty = true; return end
    end
    if from then
      for L = from, 0, -1 do buildLevel(L, P, cam, pause, job.out) end
    end
    if marksDue or from == FAR.LEVELS - 1 then buildLandmarks(pos, cam, holeR * .5, pause, job.out) end
    job.ms = t:stop()
  end)
end

-- The colour map under landing-frame (x, y) for the generator's horizon tiles: an already loaded
-- raster with a map (this never loads one: it runs inside the generator's coroutine), or nil.
function M.mapAt(x, y)
  if not RS then return nil end
  local home = RS.home
  if home and home.texMat and hasData(home, x, y) then return home end
  for _, o in ipairs(RS.others or {}) do
    local R = o.R
    if R and R.texMat then
      local fx, fy = toRegion(o, x, y)
      if hasData(R, fx, fy) then return R end
    end
  end
  return nil
end
M.mapUV = texUV

function M.status()
  return {active = active, radius = M.radius(), levels = (function() local n = 0; for k in pairs(LV) do if type(k) == 'number' then n = n + 1 end end; return n end)(),
    building = job ~= nil or staged ~= nil, spawnMax = stats.spawnMax, rasters = stats.rasters, builds = stats.builds, buildMs = stats.buildMs, spawnMs = stats.spawnMs,
    landmarks = stats.landmarks, triangles = stats.triangles, state = stats.state, error = stats.error}
end

M.parse = parse

-- tests: the levels below `levels` for a camera at p over one raster R, built at once
function M.buildLevels(R, p, holeR, levels)
  local saved = RS
  RS = {list = {R}, byRegion = {}, home = R, pause = function() end, source = {region = R.region, regions = {},
    geographic = function() return 0, 0 end, localPoint = function() return 0, 0 end}}
  local P = plan(p, holeR)
  local cam, out = {x = p.x, y = p.y, z = p.z or 0, r0 = holeR}, {}
  for L = (levels or FAR.LEVELS) - 1, 0, -1 do buildLevel(L, P, cam, function() end, out) end
  RS = saved
  return out, P
end

return M
