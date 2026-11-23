-- A tile's unique geometry as the game's own compiled shape (.cdae, TSShape v31, MessagePack):
-- one TSStatic the engine loads from bytes, instead of triangles handed to createMesh as Lua
-- tables. In the game the tables cost ~3 us a triangle on the game thread (build, createMesh, the
-- first frame of each object); a shape of 500 000 triangles loads in ~30 ms (research/fast-tiles).
--
-- The format (documentation.beamng.com/modding/file_formats/cdae): i32 version, u32 header bytes,
-- a MessagePack map, then the body as a run of MessagePack values in the order TSShape writes its
-- fields; a vector is three values: the count, the bytes of one element, the elements as one bin.
-- earthng/cdae.py reads and writes the same and is the reference (earthng/test_cdae.py).
--
-- Runs wherever the generator runs: a worker VM (a vehicle's Lua), GE Lua, the tests' LuaJIT. GE
-- Lua has no pointers (ffi.cast is a no-op, a pointer type is refused), so the file is put
-- together from strings.
local M = {}
local ffi = require('ffi')
local bit = require('bit')
local char, floor, sqrt, concat = string.char, math.floor, math.sqrt, table.concat
local band, rshift = bit.band, bit.rshift

M.VERSION = 31
M.EXPORTER = 124   -- what BeamNG 0.40 writes in the high half of the version
local INFO = '\r\n\r\n\r\nWelcome! This is a binary file :D\r\n'
  .. 'Please read the docs at https://go.beamng.com/shapeMessagepackFileformat\r\n\r\n\r\n'
-- TSDrawPrimitive.matIndex: triangles, indexed
local INDEXED = 0x20000000

-- --- MessagePack, the part the format uses ------------------------------------------------------
local f32 = ffi.new('float[1]')
local function u16(n) return char(rshift(n, 8), band(n, 255)) end
local function u32(n) return char(floor(n / 16777216) % 256, floor(n / 65536) % 256, floor(n / 256) % 256, n % 256) end
local function int(n)
  if n >= 0 then
    if n < 128 then return char(n) end
    if n < 256 then return char(0xcc, n) end
    if n < 65536 then return char(0xcd) .. u16(n) end
    return char(0xce) .. u32(n)
  end
  if n >= -32 then return char(256 + n) end
  if n >= -128 then return char(0xd0, 256 + n) end
  if n >= -32768 then return char(0xd1) .. u16(65536 + n) end
  return char(0xd2) .. u32(4294967296 + n)
end
-- a whole float goes out as an int, as the game's writer puts it
local function num(v)
  if v == floor(v) and v > -2147483648 and v < 2147483648 then return int(v) end
  f32[0] = v
  local s = ffi.string(f32, 4)
  return char(0xca) .. s:reverse()
end
local function str(s)
  local n = #s
  if n < 32 then return char(0xa0 + n) .. s end
  if n < 256 then return char(0xd9, n) .. s end
  if n < 65536 then return char(0xda) .. u16(n) .. s end
  return char(0xdb) .. u32(n) .. s
end
local function bin(s)
  local n = #s
  if n < 256 then return char(0xc4, n) .. s end
  if n < 65536 then return char(0xc5) .. u16(n) .. s end
  return char(0xc6) .. u32(n) .. s
end
local function arrayHead(n)
  if n < 16 then return char(0x90 + n) end
  if n < 65536 then return char(0xdc) .. u16(n) end
  return char(0xdd) .. u32(n)
end
local function floats(list)
  local out = {arrayHead(#list)}
  for k = 1, #list do out[k + 1] = num(list[k]) end
  return concat(out)
end
M.pack = {int = int, num = num, str = str, bin = bin, floats = floats}

-- a vector: count, bytes of one element, the elements
local function vector(out, count, size, data)
  out[#out + 1] = int(count)
  out[#out + 1] = int(size)
  out[#out + 1] = bin(data or '')
end
local function i32s(...)
  local n = select('#', ...)
  local a = ffi.new('int32_t[?]', n, ...)
  return ffi.string(a, n * 4)
end

-- --- numbers to bytes ---------------------------------------------------------------------------
-- In the game's LuaJIT (GE Lua and a vehicle VM alike) indexing an FFI array costs ~41 ns an
-- element, read or write: it is not compiled there. A struct's field is (0.24 ns), and so is a
-- Lua table (0.9 ns). So the numbers are kept in plain tables and go out through a struct of
-- BLOCK named fields written by generated code, one ffi.string a block (research/fast-tiles, p7
-- and p8: the first writer indexed float arrays and held a worker ~1 s for a town tile's scene).
local BLOCK = 64
local packers = {}
local function packer(ctype, size)
  local hit = packers[ctype]
  if hit then return hit end
  local fields, lines = {}, {}
  for k = 0, BLOCK - 1 do
    fields[#fields + 1] = 'f' .. k
    lines[#lines + 1] = string.format('s.f%d = t[at + %d]', k, k)
  end
  local name = 'e2r_cdae_' .. ctype:gsub('[^%w]', '') .. BLOCK .. '_t'
  pcall(ffi.cdef, string.format('typedef struct { %s %s; } %s;', ctype, concat(fields, ', '), name))
  local block = ffi.new(name)
  local fill = assert(loadstring('local s = ...\nreturn function(t, at)\n' .. concat(lines, '\n') .. '\nend'))(block)
  -- the bytes of t[1 .. count]
  hit = function(t, count, pause)
    local out, n = {}, 0
    -- the last block reads past the end: zeros there
    for k = count + 1, count + BLOCK do t[k] = 0 end
    for at = 1, count, BLOCK do
      fill(t, at)
      n = n + 1
      out[n] = ffi.string(block, math.min(BLOCK, count - at + 1) * size)
      if pause and n % 64 == 0 then pause() end
    end
    return concat(out)
  end
  packers[ctype] = hit
  return hit
end
local function floatBytes(t, count, pause) return packer('float', 4)(t, count, pause) end
local function uintBytes(t, count, pause) return packer('uint32_t', 4)(t, count, pause) end
M.floatBytes, M.uintBytes = floatBytes, uintBytes

-- An object of the shape being built: one mesh of the file, its vertices shared by its materials.
-- pos, nor, uv: flat tables of numbers; vertex v (0-based) is pos[v * 3 + 1 .. v * 3 + 3].
local Object = {}
Object.__index = Object

local function newObject(name)
  return setmetatable({name = name, n = 0, pos = {}, nor = {}, uv = {}, parts = {}, order = {},
    lo = {math.huge, math.huge, math.huge}, hi = {-math.huge, -math.huge, -math.huge}}, Object)
end

-- the indices of one material, joined in order when the shape is written
local function partOf(self, material)
  local part = self.parts[material]
  if not part then
    part = {material = material, n = 0, idx = {}}
    self.parts[material] = part
    self.order[#self.order + 1] = material
  end
  return part
end

-- Add a mesh as the generator makes it for createMesh: verts {x, y, z}, normals {x, y, z},
-- uvs {u, v}, faces {v, n, u} (0-based, three a triangle, clockwise from the front, the side the
-- engine draws and collides), one material. dx, dy, dz: the mesh's origin against the shape's
-- (the item's pos; 0 when equal). A corner {v, n, u} met again is one vertex. Returns the
-- triangles added.
-- pause: called every PAUSE corners (a worker's slice: a mesh of 20 000 triangles held it ~10 ms,
-- and one over CORNER vertices, whose corners were keyed by a string each, several times that:
-- the scene's packing was where a worker ran 50-155 ms past its slice, drive-b2).
local CORNER = 16384
local PAUSE = 4096
function Object:add(mesh, dx, dy, dz, pause)
  dx, dy, dz = dx or 0, dy or 0, dz or 0
  local verts, normals, uvs, faces = mesh.verts, mesh.normals, mesh.uvs, mesh.faces
  local count = #faces
  count = count - count % 3
  if count < 3 then return 0 end
  local part = partOf(self, mesh.material or '')
  local pos, nor, uv, idx = self.pos, self.nor, self.uv, part.idx
  local n, at = self.n, part.n
  local lo, hi = self.lo, self.hi
  local lx, ly, lz, hx, hy, hz = lo[1], lo[2], lo[3], hi[1], hi[2], hi[3]
  local seen = {}
  local wide = #verts >= CORNER or #normals >= CORNER or #uvs >= CORNER
  for t = 1, count do
    local f = faces[t]
    local vi, ni, ui = f.v, f.n, f.u
    -- a corner's key: one number; in a wide mesh a table a vertex, keyed by its normal and uv
    local set, key = seen, nil
    if wide then
      set = seen[vi]
      if not set then set = {}; seen[vi] = set end
      key = ni * 4194304 + ui
    else
      key = (vi * CORNER + ni) * CORNER + ui
    end
    local index = set[key]
    if not index then
      index = n
      set[key] = n
      local p, q, w = verts[vi + 1], normals[ni + 1], uvs[ui + 1]
      local x, y, z = p.x + dx, p.y + dy, p.z + dz
      local a, b = n * 3, n * 2
      pos[a + 1], pos[a + 2], pos[a + 3] = x, y, z
      nor[a + 1], nor[a + 2], nor[a + 3] = q.x, q.y, q.z
      uv[b + 1], uv[b + 2] = w.u, w.v
      if x < lx then lx = x end
      if y < ly then ly = y end
      if z < lz then lz = z end
      if x > hx then hx = x end
      if y > hy then hy = y end
      if z > hz then hz = z end
      n = n + 1
    end
    at = at + 1
    idx[at] = index
    if pause and t % PAUSE == 0 then pause() end
  end
  lo[1], lo[2], lo[3], hi[1], hi[2], hi[3] = lx, ly, lz, hx, hy, hz
  self.n, part.n = n, at
  return count / 3
end

-- A tangent a vertex: the direction u grows in along the surface, summed over its triangles,
-- laid into the plane of the normal; w is the hand of the map, with the sign the game bakes
-- (checked against its own shapes: research/fast-tiles/check_writer.py).
-- self: {n, pos, nor, uv} as an Object keeps them; indices: `count` 0-based vertex indices.
-- Returns a flat table, four numbers a vertex.
local function tangents(self, indices, count, pause)
  local n, pos, nor, uv = self.n, self.pos, self.nor, self.uv
  local tan, bx = {}, {}
  for k = 1, n * 4 do tan[k] = 0 end
  for k = 1, n * 3 do bx[k] = 0 end
  if pause then pause() end
  for t = 1, count - 2, 3 do
    local a, b, c = indices[t], indices[t + 1], indices[t + 2]
    local a3, b3, c3 = a * 3, b * 3, c * 3
    local x1, y1, z1 = pos[b3 + 1] - pos[a3 + 1], pos[b3 + 2] - pos[a3 + 2], pos[b3 + 3] - pos[a3 + 3]
    local x2, y2, z2 = pos[c3 + 1] - pos[a3 + 1], pos[c3 + 2] - pos[a3 + 2], pos[c3 + 3] - pos[a3 + 3]
    local s1, t1 = uv[b * 2 + 1] - uv[a * 2 + 1], uv[b * 2 + 2] - uv[a * 2 + 2]
    local s2, t2 = uv[c * 2 + 1] - uv[a * 2 + 1], uv[c * 2 + 2] - uv[a * 2 + 2]
    local det = s1 * t2 - s2 * t1
    if det ~= 0 then
      local r = 1 / det
      local tx, ty, tz = (t2 * x1 - t1 * x2) * r, (t2 * y1 - t1 * y2) * r, (t2 * z1 - t1 * z2) * r
      local ux, uy, uz = (s1 * x2 - s2 * x1) * r, (s1 * y2 - s2 * y1) * r, (s1 * z2 - s2 * z1) * r
      local a4, b4, c4 = a * 4, b * 4, c * 4
      tan[a4 + 1], tan[a4 + 2], tan[a4 + 3] = tan[a4 + 1] + tx, tan[a4 + 2] + ty, tan[a4 + 3] + tz
      tan[b4 + 1], tan[b4 + 2], tan[b4 + 3] = tan[b4 + 1] + tx, tan[b4 + 2] + ty, tan[b4 + 3] + tz
      tan[c4 + 1], tan[c4 + 2], tan[c4 + 3] = tan[c4 + 1] + tx, tan[c4 + 2] + ty, tan[c4 + 3] + tz
      bx[a3 + 1], bx[a3 + 2], bx[a3 + 3] = bx[a3 + 1] + ux, bx[a3 + 2] + uy, bx[a3 + 3] + uz
      bx[b3 + 1], bx[b3 + 2], bx[b3 + 3] = bx[b3 + 1] + ux, bx[b3 + 2] + uy, bx[b3 + 3] + uz
      bx[c3 + 1], bx[c3 + 2], bx[c3 + 3] = bx[c3 + 1] + ux, bx[c3 + 2] + uy, bx[c3 + 3] + uz
    end
    if pause and t % 6144 == 1 then pause() end
  end
  for v = 0, n - 1 do
    if pause and v % 8192 == 8191 then pause() end
    local v3, v4 = v * 3, v * 4
    local nx, ny, nz = nor[v3 + 1], nor[v3 + 2], nor[v3 + 3]
    local tx, ty, tz = tan[v4 + 1], tan[v4 + 2], tan[v4 + 3]
    local d = nx * tx + ny * ty + nz * tz
    tx, ty, tz = tx - nx * d, ty - ny * d, tz - nz * d
    local len = sqrt(tx * tx + ty * ty + tz * tz)
    if len < 1e-9 then
      -- no map direction here: any direction in the surface
      if nx * nx < .81 then tx, ty, tz = 1 - nx * nx, -nx * ny, -nx * nz else tx, ty, tz = -ny * nx, 1 - ny * ny, -ny * nz end
      len = sqrt(tx * tx + ty * ty + tz * tz)
      if len < 1e-9 then tx, ty, tz, len = 1, 0, 0, 1 end
    end
    tx, ty, tz = tx / len, ty / len, tz / len
    -- (n x t) . b: the map's hand
    local cx, cy, cz = ny * tz - nz * ty, nz * tx - nx * tz, nx * ty - ny * tx
    local hand = cx * bx[v3 + 1] + cy * bx[v3 + 2] + cz * bx[v3 + 3]
    tan[v4 + 1], tan[v4 + 2], tan[v4 + 3], tan[v4 + 4] = tx, ty, tz, hand < 0 and -1 or 1
  end
  return tan
end
M.tangents = tangents

local function sphere(lo, hi)
  local cx, cy, cz = (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2, (lo[3] + hi[3]) / 2
  local dx, dy, dz = hi[1] - cx, hi[2] - cy, hi[3] - cz
  return {cx, cy, cz}, sqrt(dx * dx + dy * dy + dz * dz), sqrt(dx * dx + dy * dy)
end

-- The shape being built: objects by name, each a mesh of the file.
local Builder = {}
Builder.__index = Builder

function M.builder() return setmetatable({objects = {}, byName = {}, triangles = 0, parts = {}}, Builder) end

-- The engine draws a mesh with 16-bit indices: past 65 535 vertices they wrap, and triangles join
-- vertices from the other end of the mesh (23.11: a town tile's scene of 100-190 000 triangles
-- came out with beams and slabs across the streets; the file itself read back whole). So a class
-- of geometry is as many meshes of the file as it needs, each under VERTICES.
M.VERTICES = 65000

function Builder:object(name)
  local object = self.byName[name]
  if not object then
    object = newObject(name)
    self.byName[name] = object
    self.objects[#self.objects + 1] = object
  end
  return object
end

-- name: the class the mesh belongs to; its meshes in the file are name, name_2, name_3, ...
function Builder:add(name, mesh, dx, dy, dz, pause)
  local part = self.parts[name] or 1
  local object = self:object(part == 1 and name or (name .. '_' .. part))
  -- every corner of the mesh may be a new vertex
  if object.n > 0 and object.n + #mesh.faces > M.VERTICES then
    part = part + 1
    self.parts[name] = part
    object = self:object(name .. '_' .. part)
  end
  local n = object:add(mesh, dx, dy, dz, pause)
  self.triangles = self.triangles + n
  return n
end

-- The file's bytes; nil when the shape has no triangle. visibleSize: the size on screen (pixels)
-- below which the engine stops drawing the shape. pause: called between pieces of the work (a
-- worker's slice of a frame).
function Builder:encode(visibleSize, pause)
  visibleSize = visibleSize or 2
  local objects = {}
  for _, object in ipairs(self.objects) do
    if object.n > 0 then objects[#objects + 1] = object end
  end
  if #objects == 0 then return nil end
  local names, nameIndex, materials, materialIndex = {}, {}, {}, {}
  local function nameOf(name)
    local k = nameIndex[name]
    if not k then k = #names; names[k + 1] = name; nameIndex[name] = k end
    return k
  end
  local function materialOf(name)
    local k = materialIndex[name]
    if not k then k = #materials; materials[k + 1] = name; materialIndex[name] = k end
    return k
  end
  local lo, hi = {math.huge, math.huge, math.huge}, {-math.huge, -math.huge, -math.huge}
  for _, object in ipairs(objects) do
    for k = 1, 3 do
      lo[k], hi[k] = math.min(lo[k], object.lo[k]), math.max(hi[k], object.hi[k])
    end
  end
  local centre, radius, tube = sphere(lo, hi)
  local sizeName = tostring(floor(visibleSize))
  -- the node tree a Collada import leaves: base00 > start01 > the node of the detail level
  local base, start, holder = nameOf('base00'), nameOf('start01'), nameOf('tile' .. sizeName)
  local count = #objects
  local out = {num(visibleSize), int(0), num(radius), num(tube), floats(centre),
    floats({lo[1], lo[2], lo[3], hi[1], hi[2], hi[3]})}
  vector(out, 3, 20, i32s(base, -1, -1, 1, -1, start, 0, -1, 2, -1, holder, 1, 0, -1, -1))
  local objectBytes, stateBytes, triangles = {}, {}, 0
  local state = ffi.string(ffi.new('float[1]', 1), 4) .. i32s(0, 0)
  for k, object in ipairs(objects) do
    objectBytes[k] = i32s(nameOf(object.name), 1, k - 1, 2, k == count and -1 or k, -1)
    stateBytes[k] = state
  end
  vector(out, count, 24, concat(objectBytes))
  vector(out, 1, 4, i32s(0))            -- subShapeFirstNode
  vector(out, 1, 4, i32s(0))            -- subShapeFirstObject
  vector(out, 1, 4, i32s(3))            -- subShapeNumNodes
  vector(out, 1, 4, i32s(count))        -- subShapeNumObjects
  local identity = ffi.string(ffi.new('int16_t[4]', 0, 0, 0, 32766), 8)
  vector(out, 3, 8, identity:rep(3))    -- defaultRotations
  vector(out, 3, 12, ('\0'):rep(36))    -- defaultTranslations
  for _, size in ipairs({8, 12, 4, 12, 12, 8, 12, 8}) do vector(out, 0, size) end   -- no animation, no ground
  vector(out, count, 12, concat(stateBytes))
  vector(out, 0, 8)                     -- triggers
  -- the meshes follow the names in the file, and the names are complete only after the meshes
  local packed = {int(count)}
  local function put(v) packed[#packed + 1] = v end
  for _, object in ipairs(objects) do
    local n = object.n
    local total = 0
    local indices, prims = {}, {}
    for _, material in ipairs(object.order) do
      local part = object.parts[material]
      if part.n > 0 then
        local idx = part.idx
        for k = 1, part.n do
          indices[total + k] = idx[k]
          if pause and k % 16384 == 0 then pause() end
        end
        prims[#prims + 1] = ffi.string(ffi.new('uint32_t[3]', total, part.n, INDEXED + materialOf(material)), 12)
        total = total + part.n
        if pause then pause() end
      end
    end
    triangles = triangles + total / 3
    local c, r = sphere(object.lo, object.hi)
    put(int(0))                         -- a standard mesh
    put(int(1)); put(int(1)); put(int(-1))   -- numFrames, numMatFrames, parentMesh
    put(floats({object.lo[1], object.lo[2], object.lo[3], object.hi[1], object.hi[2], object.hi[3]}))
    put(floats(c))
    put(num(r))
    vector(packed, n, 12, floatBytes(object.pos, n * 3, pause))
    vector(packed, n, 8, floatBytes(object.uv, n * 2, pause))
    vector(packed, 0, 8)                -- tverts2
    vector(packed, 0, 4)                -- colors
    vector(packed, n, 12, floatBytes(object.nor, n * 3, pause))
    vector(packed, 0, 1)                -- encodedNorms
    vector(packed, #prims, 12, concat(prims))
    vector(packed, total, 4, uintBytes(indices, total, pause))
    vector(packed, n, 16, floatBytes(tangents(object, indices, total, pause), n * 4, pause))
    put(int(n))                         -- vertsPerFrame
    put(int(0))                         -- flags
  end
  local detail = ffi.new('int32_t[3]', nameOf('detail' .. sizeName), 0, 0)
  local sizes = ffi.new('float[3]', visibleSize, -1, -1)
  vector(out, 1, 52, ffi.string(detail, 12) .. ffi.string(sizes, 12) .. i32s(triangles, 0, 0, 0, 0)
    .. ffi.string(ffi.new('float[1]', 0), 4) .. i32s(0))
  out[#out + 1] = int(#names)
  for _, name in ipairs(names) do out[#out + 1] = str(name) end
  out[#out + 1] = concat(packed)
  out[#out + 1] = int(0)                -- sequences
  out[#out + 1] = int(#materials)
  for k, name in ipairs(materials) do
    -- S_Wrap | T_Wrap; the reflectance map is the material's index, bump and detail maps none
    out[#out + 1] = concat({str(name), int(3), int(k - 1), int(4294967295), int(4294967295), num(1), num(1)})
  end
  local body = concat(out)
  local objectNames = {arrayHead(count)}
  for k, object in ipairs(objects) do objectNames[k + 1] = str(object.name) end
  local header = char(0x84) .. str('info') .. str(INFO) .. str('compression') .. char(0xc2)
    .. str('bodysize') .. int(#body) .. str('objectNames') .. concat(objectNames)
  local version = ffi.new('uint32_t[2]', M.VERSION + M.EXPORTER * 65536, #header)
  return ffi.string(version, 8) .. header .. body, {triangles = triangles, objects = count, materials = #materials}
end

return M
