-- The far view's colour maps for a tile built in a worker VM. A far or horizon tile is draped in
-- the pack's far map (generator.lua options.farMap: at, uv, lift), which far.lua answers from the
-- rasters it has loaded in GE Lua. A worker cannot ask it, so GE Lua sends what its answer rests
-- on (far.lua M.mapExport: for each loaded raster with a map its file, the name of the map's
-- material, and the way from the landing frame into the raster's region), and this module gives
-- the same three answers from the raster files themselves.
--
-- Only a raster's header and its class pixels are read (the file's elevations and marks are
-- far.lua's own business). The pixels stay the string they were read as: a byte of a string is
-- compiled by the game's LuaJIT, an element of an FFI array is not (Knowledge/docs/FAST_TILES.md).
local M = {}
local floor = math.floor
local FOREST, NO_DATA = 3, 255     -- far.lua's classes

local rasters = {}   -- path -> {u0, v0, nu, nv, step, cls (string), at (offset of the first pixel)} or false

local function u32(s, at)
  local a, b, c, d = s:byte(at, at + 3)
  return a + b * 256 + c * 65536 + d * 16777216
end
local function i32(s, at)
  local v = u32(s, at)
  return v >= 2147483648 and v - 4294967296 or v
end
local function f32(s, at)
  -- (no FFI needed for one float)
  local b1, b2, b3, b4 = s:byte(at, at + 3)
  local sign = b4 >= 128 and -1 or 1
  local exponent = (b4 % 128) * 2 + floor(b3 / 128)
  local mantissa = ((b3 % 128) * 256 + b2) * 256 + b1
  if exponent == 0 then return sign * mantissa * 2 ^ -149 end
  return sign * (1 + mantissa / 8388608) * 2 ^ (exponent - 127)
end

-- far.lua parse(): 'EGF1', u0, v0 (i32), nu, nv (u32), step, sea (f32), the elevation nodes
-- (u16 each), then the class pixels, a byte each
function M.parse(data)
  if type(data) ~= 'string' or #data < 33 or data:sub(1, 4) ~= 'EGF1' then return nil end
  local R = {u0 = i32(data, 6), v0 = i32(data, 10), nu = u32(data, 14), nv = u32(data, 18), step = f32(data, 22)}
  local nodes, pixels = (R.nu + 1) * (R.nv + 1), R.nu * R.nv
  local at = 30 + 2 * nodes
  if #data < at - 1 + pixels then return nil end
  R.cls, R.at = data, at
  return R
end

local function load(path)
  local hit = rasters[path]
  if hit ~= nil then return hit or nil end
  rasters[path] = false
  local f = io.open(path, 'rb')
  if not f then return nil end
  local data = f:read('*a')
  f:close()
  local R = M.parse(data)
  rasters[path] = R or false
  return R
end

-- desc: {canopy, rasters = {{path, texKind, real, a = {8 numbers} or nil}}}, the home region's
-- raster first, as far.lua looks them up. Returns {at, uv, lift} for options.farMap, or nil when
-- no raster of the list can be read.
function M.make(desc)
  if type(desc) ~= 'table' or type(desc.rasters) ~= 'table' then return nil end
  local list = {}
  for _, spec in ipairs(desc.rasters) do
    local raw = load(spec.path)
    if raw then
      list[#list + 1] = {texKind = spec.texKind, real = spec.real or nil, a = spec.a,
        u0 = raw.u0, v0 = raw.v0, nu = raw.nu, nv = raw.nv, step = raw.step, cls = raw.cls, at0 = raw.at}
    end
  end
  if #list == 0 then return nil end
  local canopy = desc.canopy or 16
  -- landing frame -> the raster's region (far.lua toRegion)
  local function frame(R, x, y)
    local a = R.a
    if not a then return x, y end
    local dx, dy = x - a[1], y - a[2]
    return a[3] + a[5] * dx + a[7] * dy, a[4] + a[6] * dx + a[8] * dy
  end
  local function class(R, fx, fy)
    local u, v = floor(fx / R.step - R.u0), floor(fy / R.step - R.v0)
    if u < 0 or v < 0 or u >= R.nu or v >= R.nv then return NO_DATA end
    return R.cls:byte(R.at0 + v * R.nu + u)
  end
  local function at(x, y)
    for k = 1, #list do
      local R = list[k]
      local fx, fy = frame(R, x, y)
      if class(R, fx, fy) ~= NO_DATA then return R, fx, fy end
    end
    return nil
  end
  return {
    at = function(x, y) return (at(x, y)) end,
    uv = function(R, x, y)
      local fx, fy = frame(R, x, y)
      return (fx / R.step - R.u0) / R.nu, 1 - (fy / R.step - R.v0) / R.nv
    end,
    lift = function(x, y)
      local R, fx, fy = at(x, y)
      if not R then return 0 end
      return class(R, fx, fy) == FOREST and canopy or 0
    end,
  }
end

return M
