-- The near land in its real colour: Sentinel-2 sheets of a pack (far/<region>.s2.bin, written by
-- earthng/s2_colour.py from the ESA WorldCover 2021 composite, CC BY 4.0).
--
-- A sheet is `sheet` metres of land (6 x 6 tiles) with a gutter round it, a small DDS of its own.
-- The region's file holds them all behind an index; the few round the car are written out to
-- the user folder (the engine loads a texture from a file) and each gets two materials: the sheet
-- as base colour under the game's grass detail (open land) or its crumbly soil (fields), both
-- over 2 m. The detail carries the look at the wheel, the sheet what the place is from 30 m on:
-- a field's own brown, a water meadow's green, the grey-green of a town's worn lawns.
-- The generator (S2 in generator.lua) asks kind(I, J, land) for the kind of a tile's sheet and
-- lays the ground's UVs over it; a tile lies in one sheet, so nothing reads across an edge.
--
-- A ProceduralMesh has one UV set and the detail maps scale it (detailScale): over a whole
-- region's map (100 km) a 2 m repeat is past what a float keeps (steps of 6 mm, several texels
-- of the detail). Over a sheet of 3.2 km the steps are 0.2 mm.
local M = {}

M.DIR = 'e2r_stream/s2'
M.DETAIL_M = 2
local TERRAIN = '/assets/materials/terrain/'
-- land: the detail maps' stem, the detail colour's strength, what the tyres feel, roughness
M.LANDS = {
  -- (.42 of the grass's detail over the picture's pale ground read as confetti, hyperreal run-03)
  -- tint: the sheet is the land seen from above, its grass and all; under the grass that
  -- stands on it here the ground is darker (the engine reads the factor as sRGB: .9 is x 0.8).
  -- Without it sunlit ground showed pale between the blades (hyperreal run-04).
  grass = {stem = 'grass/t_grass_01/t_grass_01', strength = .28, ground = 'GRASS', rough = .93, tint = .9},
  earth = {stem = 'soil/dirt_crumbly/t_dirt_crumbly', strength = .24, ground = 'DIRT', rough = .96, tint = 1},
}
M.enabled = true

local regions = {}     -- far raster path -> region record, or false
local kinds = {}       -- kind -> true once its material is loaded
local stats = {sheets = 0, materials = 0, bytes = 0}
M.stats = stats

local function u32(s, at)
  local a, b, c, d = s:byte(at, at + 3)
  return a + b * 256 + c * 65536 + d * 16777216
end
local function i32(s, at)
  local v = u32(s, at)
  return v >= 2147483648 and v - 4294967296 or v
end

-- The header and index of a sheets file (earthng/s2_colour.pack_sheets): 'EGS2', version, step
-- in mm, side in px, gutter in px, sheet in mm, I0, J0, NI, NJ, then NI * NJ (offset, length).
function M.parse(data)
  if type(data) ~= 'string' or #data < 37 or data:sub(1, 4) ~= 'EGS2' or data:byte(5) ~= 1 then return nil end
  local R = {data = data, step = u32(data, 6) / 1000, px = u32(data, 10), gutter = u32(data, 14),
    sheet = u32(data, 18) / 1000, i0 = i32(data, 22), j0 = i32(data, 26), ni = u32(data, 30), nj = u32(data, 34)}
  if R.step <= 0 or R.px < 4 or R.sheet <= 0 or #data < 37 + 8 * R.ni * R.nj then return nil end
  R.table = 38
  R.span = R.px * R.step
  return R
end

-- the bytes of sheet (I, J), or nil where the region has none
function M.bytes(R, I, J)
  local a, b = I - R.i0, J - R.j0
  if a < 0 or b < 0 or a >= R.ni or b >= R.nj then return nil end
  local at = R.table + 8 * (b * R.ni + a)
  local offset, length = u32(R.data, at), u32(R.data, at + 4)
  if length == 0 or offset + length > #R.data then return nil end
  return R.data:sub(offset + 1, offset + length)
end

local function signed(n) return n < 0 and ('m' .. -n) or tostring(n) end

-- the kind of sheet (I, J) for a land ('grass' or 'earth'): the generator draws it as material
-- 'e2rf_' .. kind
function M.kindName(R, I, J, land)
  return 's2' .. (land == 'earth' and 'e' or 'g') .. '_' .. R.safe .. '_' .. signed(I) .. '_' .. signed(J)
end

-- the material of a sheet's land (pure: the tests read it)
function M.material(R, file, kind, land)
  local L = M.LANDS[land] or M.LANDS.grass
  local name = 'e2rf_' .. kind
  local scale = R.span / M.DETAIL_M
  return {name = name, mapTo = name, class = 'Material', version = 1.5, groundType = L.ground,
    Stages = {{baseColorMap = file, baseColorFactor = {L.tint, L.tint, L.tint, 1}, roughnessFactor = L.rough, metallicFactor = 0,
      detailMap = TERRAIN .. L.stem .. '_b.png', detailNormalMap = TERRAIN .. L.stem .. '_nm.png',
      roughnessDetailMap = TERRAIN .. L.stem .. '_r.png', detailScale = {scale, scale},
      detailBaseColorMapStrength = L.strength, detailNormalMapStrength = 1, detailRoughnessMapStrength = .4},
      {}, {}, {}}}
end

-- Write sheet (I, J) out and load its materials. Returns true when they are there.
local function ensure(R, I, J)
  local key = signed(I) .. '_' .. signed(J)
  local hit = R.done[key]
  if hit ~= nil then return hit end
  R.done[key] = false
  local bytes = M.bytes(R, I, J)
  if not bytes then return false end
  local ok, err = pcall(function()
    local folder = M.DIR .. '/' .. R.safe
    if FS and FS.directoryCreate and not FS:directoryExists('/' .. folder) then FS:directoryCreate('/' .. folder, true) end
    local path = folder .. '/' .. key .. '.color.dds'
    -- binary: the game's writeFile opens in text mode
    local f = assert(io.open(path, 'wb'))
    f:write(bytes)
    f:close()
    local defs = {}
    for land in pairs(M.LANDS) do
      local kind = M.kindName(R, I, J, land)
      defs['e2rf_' .. kind] = M.material(R, '/' .. path, kind, land)
    end
    local file = 'e2r_world/s2_' .. R.safe .. '_' .. key .. '.json'
    jsonWriteFile(file, defs, false)
    loadJsonMaterialsFile('/' .. file)
    for name in pairs(defs) do kinds[name] = true end
    stats.sheets, stats.materials, stats.bytes = stats.sheets + 1, stats.materials + 2, stats.bytes + #bytes
  end)
  if not ok then
    stats.error = tostring(err)
    log('W', 'e2r.s2', 'sheet ' .. key .. ': ' .. tostring(err))
    return false
  end
  R.done[key] = true
  return true
end

-- The sheets of a region (a native.lua region record: descriptor.manifest, descriptor.id), or nil.
function M.region(r)
  if not M.enabled then return nil end
  local manifest = r and r.descriptor and r.descriptor.manifest
  local id = r and r.descriptor and r.descriptor.id
  if type(manifest) ~= 'string' or not id then return nil end
  local root = manifest:match('^(.*)/regions/[^/]+/manifest%.json$')
  if not root then return nil end
  local path = root .. '/far/' .. id .. '.s2.bin'
  local hit = regions[path]
  if hit ~= nil then return hit or nil end
  regions[path] = false
  local okExists, found = pcall(function() return FS:fileExists(path) end)
  if not okExists or not found then return nil end
  local f = io.open(path, 'rb')
  if not f then return nil end
  local data = f:read('*a')
  f:close()
  local R = M.parse(data)
  if not R then
    log('W', 'e2r.s2', 'bad sheets file ' .. path)
    return nil
  end
  R.id, R.safe, R.done = id, tostring(id):gsub('[^%w]', '_'), {}
  regions[path] = R
  log('I', 'e2r.s2', string.format('%s: sheets of %g m at %g m a texel', id, R.sheet, R.step))
  return R
end

-- What the generator needs of a region's sheets (options.s2), or nil when it has none:
-- sheet, step, px, gutter and kind(I, J, land) -> the kind to draw sheet (I, J) in, or nil.
function M.options(r)
  local R = M.region(r)
  if not R then return nil end
  R.options = R.options or {sheet = R.sheet, step = R.step, px = R.px, gutter = R.gutter,
    kind = function(I, J, land)
      if not ensure(R, I, J) then return nil end
      return M.kindName(R, I, J, land)
    end}
  return R.options
end

-- The level ended: its materials went with it, the written sheets stay for the next landing.
function M.reset()
  regions, kinds = {}, {}
  stats.sheets, stats.materials, stats.bytes, stats.error = 0, 0, 0, nil
end

return M
