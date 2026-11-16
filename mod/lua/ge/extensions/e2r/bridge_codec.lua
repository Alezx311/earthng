-- Compact binary form of a tile's manifests for the experimental Rust bridge
-- (research/native-bridge/NIGHT_2026-11-16.md). The worker VM encodes, GE Lua decodes.
--
-- Layout (little endian, sections 8-byte aligned from the message start):
--   'EMC2' | u32 ops | u32 nums | u32 strings | u32 string bytes | u32 blobs | u32 blob bytes | u32 0
--   | int32 ops[] (pad) | double nums[] | u32 string ends[] | string bytes (pad)
--   | u32 blob starts[] (pad) | blobs, each padded to 8
-- ops is the structure in pre-order: NIL, FALSE, TRUE, NUM (next of nums), INT v, STR k,
-- TABLE narr nhash (narr values, then nhash key/value pairs), REF id (a table seen before,
-- by order of appearance), ARR type count blob (a Lua array of the generator's mesh cdata:
-- vec3 {x,y,z} double, face {v,n,u} int32, uv {u,v} double), ONE type blob (one such cdata).
-- The game copies the message into an int32 and a double view and reads by index (no per-byte
-- parsing, no pointers: GE Lua's sandbox allows ffi.new/ffi.copy/ffi.string only, ffi.cast is a no-op).
local M = {}
local ffi = require('ffi')
local floor, type, pairs = math.floor, type, pairs

local NIL, FALSE, TRUE, NUM, INT, STR, TABLE, REF, ARR, ONE = 0, 1, 2, 3, 4, 5, 6, 7, 8, 9
M.MAGIC = 'EMC2'

-- The generator's mesh structs, as generator.lua makes them (vec3 is the game's FFI type)
local VEC3, FACE, UV
local function types()
  if VEC3 ~= nil then return end
  VEC3, FACE, UV = false, false, false
  local ok, ct = pcall(ffi.typeof, 'struct __luaVec3_t')
  if ok then VEC3 = ct end
  pcall(ffi.cdef, 'typedef struct { int32_t v, n, u; } e2r_face_t; typedef struct { double u, v; } e2r_uv_t;')
  local okF, f = pcall(ffi.typeof, 'e2r_face_t')
  local okU, u = pcall(ffi.typeof, 'e2r_uv_t')
  if okF then FACE = f end
  if okU then UV = u end
end
-- id -> fields, element C type, bytes per field
local KIND = {{'x', 'y', 'z', ct = 'double', size = 8}, {'v', 'n', 'u', ct = 'int32_t', size = 4},
  {'u', 'v', ct = 'double', size = 8}}

local function kindOf(v)
  types()
  if VEC3 and ffi.istype(VEC3, v) then return 1 end
  if FACE and ffi.istype(FACE, v) then return 2 end
  if UV and ffi.istype(UV, v) then return 3 end
  return nil
end

local function keyOrder(a, b)
  local ta, tb = type(a), type(b)
  if ta ~= tb then return ta < tb end
  if ta == 'number' or ta == 'string' then return a < b end
  if ta == 'boolean' then return (a and 1 or 0) < (b and 1 or 0) end
  return tostring(a) < tostring(b)
end

-- canonical: hash keys sorted (byte-identical output for equal tables; for parity checks)
function M.encode(root, canonical)
  local ops, no = {}, 0
  local nums, nn = {}, 0
  local strIndex, strs, ns = {}, {}, 0
  local blobs, nb = {}, 0
  local seen, tables = {}, 0
  local function str(s)
    local k = strIndex[s]
    if not k then strs[ns + 1] = s; k = ns; strIndex[s] = k; ns = ns + 1 end
    return k
  end
  local function blob(list, first, count, kind)
    local spec = KIND[kind]
    local width = #spec
    local a = ffi.new(spec.ct .. '[?]', count * width)
    local at = 0
    for k = first, first + count - 1 do
      local v = list[k]
      for f = 1, width do a[at] = v[spec[f]]; at = at + 1 end
    end
    blobs[nb + 1] = ffi.string(a, count * width * spec.size)
    nb = nb + 1
    return nb - 1
  end
  local value
  value = function(v)
    local tv = type(v)
    if tv == 'number' then
      if v == floor(v) and v >= -2147483648 and v < 2147483648 and not (v == 0 and 1 / v < 0) then
        ops[no + 1], ops[no + 2] = INT, v; no = no + 2
      else
        ops[no + 1] = NUM; no = no + 1
        nums[nn + 1] = v; nn = nn + 1
      end
    elseif tv == 'string' then
      ops[no + 1], ops[no + 2] = STR, str(v); no = no + 2
    elseif tv == 'table' then
      local id = seen[v]
      if id then ops[no + 1], ops[no + 2] = REF, id; no = no + 2; return end
      seen[v] = tables; tables = tables + 1
      local n = 0
      while v[n + 1] ~= nil do n = n + 1 end
      local keys, nk = nil, 0
      for k in pairs(v) do
        if not (type(k) == 'number' and k >= 1 and k <= n and k == floor(k)) then
          keys = keys or {}
          nk = nk + 1; keys[nk] = k
        end
      end
      if nk == 0 and n > 0 and type(v[1]) == 'cdata' then
        local kind = kindOf(v[1])
        local same = kind ~= nil
        if same then
          local ct = kind == 1 and VEC3 or (kind == 2 and FACE or UV)
          for k = 2, n do if not ffi.istype(ct, v[k]) then same = false; break end end
        end
        if same then
          ops[no + 1], ops[no + 2], ops[no + 3], ops[no + 4] = ARR, kind, n, blob(v, 1, n, kind)
          no = no + 4
          return
        end
      end
      if canonical and nk > 1 then table.sort(keys, keyOrder) end
      ops[no + 1], ops[no + 2], ops[no + 3] = TABLE, n, nk; no = no + 3
      for k = 1, n do value(v[k]) end
      for k = 1, nk do local key = keys[k]; value(key); value(v[key]) end
    elseif tv == 'boolean' then
      ops[no + 1] = v and TRUE or FALSE; no = no + 1
    elseif tv == 'nil' then
      ops[no + 1] = NIL; no = no + 1
    elseif tv == 'cdata' then
      local kind = kindOf(v)
      if not kind then error('e2r-codec: unknown cdata ' .. tostring(ffi.typeof(v))) end
      ops[no + 1], ops[no + 2], ops[no + 3] = ONE, kind, blob({v}, 1, 1, kind); no = no + 3
    else
      error('e2r-codec: cannot encode a ' .. tv)
    end
  end
  value(root)
  local function pad(n) local r = n % 8; return r == 0 and '' or string.rep('\0', 8 - r) end
  local a = ffi.new('int32_t[?]', math.max(1, no))
  for k = 1, no do a[k - 1] = ops[k] end
  local d = ffi.new('double[?]', math.max(1, nn))
  for k = 1, nn do d[k - 1] = nums[k] end
  local sEnds, total = ffi.new('uint32_t[?]', math.max(1, ns)), 0
  for k = 1, ns do total = total + #strs[k]; sEnds[k - 1] = total end
  -- each blob starts on 8 bytes, so the decoder reads it through a double view of the message
  local bStarts, btotal, padded = ffi.new('uint32_t[?]', math.max(1, nb)), 0, {}
  for k = 1, nb do
    bStarts[k - 1] = btotal
    padded[#padded + 1] = blobs[k]
    local p = pad(#blobs[k])
    if p ~= '' then padded[#padded + 1] = p end
    btotal = btotal + #blobs[k] + #p
  end
  local head = ffi.new('uint32_t[7]', no, nn, ns, total, nb, btotal, 0)
  local opsBytes, strBytes = ffi.string(a, 4 * no), table.concat(strs)
  local sEndBytes, bStartBytes = ffi.string(sEnds, 4 * ns), ffi.string(bStarts, 4 * nb)
  return table.concat({M.MAGIC, ffi.string(head, 28), opsBytes, pad(4 * no), ffi.string(d, 8 * nn),
    sEndBytes, strBytes, pad(4 * ns + #strBytes), bStartBytes, pad(4 * nb), table.concat(padded)})
end

-- The whole message is copied into two persistent typed views (int32 and double) and read by
-- index: no section copies (s:sub) and no new arrays per message. Those were megabytes of
-- garbage a city tile, and the collector's debt from them was paid inside the element loops,
-- 82 ms between two pauses (kyiv-q50-rust-2). One set of views per decode under way (M.viewSets:
-- native.lua delivers on two lanes), each grown to the largest message it took and kept. A decode
-- that finds every set taken (a small message while big ones are suspended at a pause) gets its
-- own arrays: twice the message, all of it the collector's debt in that frame (M.stats).
local sets, setCount = {}, 1
M.stats = {fresh = 0, freshKb = 0}
function M.viewSets(n) setCount = math.max(1, math.floor(tonumber(n) or 1)) end
local function views(n, owner)
  if n >= 65536 then
    for k = 1, setCount do
      local v = sets[k]
      if not v then v = {bytes = 0}; sets[k] = v end
      if v.owner == nil then
        if n > v.bytes then
          v.bytes = math.ceil(n / 8) * 8 + 1024 * 1024
          v.I, v.D = ffi.new('int32_t[?]', v.bytes / 4), ffi.new('double[?]', v.bytes / 8)
        end
        v.owner = owner
        return v.I, v.D
      end
    end
  end
  local words = math.ceil(n / 8) * 2
  M.stats.fresh, M.stats.freshKb = M.stats.fresh + 1, M.stats.freshKb + words * 8 / 1024
  return ffi.new('int32_t[?]', words), ffi.new('double[?]', words / 2)
end
local function giveBack(owner)
  for k = 1, #sets do if sets[k].owner == owner then sets[k].owner = nil end end
end
-- a decode abandoned at a pause (its coroutine dropped) gives the views back
function M.release() for k = 1, #sets do sets[k].owner = nil end end

local function align8(n) local r = n % 8; return r == 0 and n or n + 8 - r end

-- ctors (optional): {vec3 = f(x, y, z), face = f(v, n, u), uv = f(u, v)}; default the game's
-- FFI structs like generator.lua (plain {x, y, z} tables where the game's vec3 is absent).
-- pause (optional) is called every few hundred elements (a coroutine's budget check).
-- base (optional): bytes of s before the message (a frame header, a multiple of 8)
function M.decode(s, ctors, pause, base)
  base = base or 0
  if type(s) ~= 'string' or base % 8 ~= 0 or #s < base + 32 or s:sub(base + 1, base + 4) ~= M.MAGIC then
    error('e2r-codec: not an ' .. M.MAGIC .. ' message')
  end
  local owner = {}
  local I, D = views(#s, owner)
  ffi.copy(I, s, #s)
  ffi.copy(D, s, #s)
  local h = base / 4 + 1
  local no, nn, ns, sbytes, nb, bbytes = I[h], I[h + 1], I[h + 2], I[h + 3], I[h + 4], I[h + 5]
  local off = base + 32
  local opsAt = off / 4; off = align8(off + 4 * no)
  local numsAt = off / 8; off = off + 8 * nn
  local sEndsAt = off / 4; off = off + 4 * ns
  local sbase = off; off = align8(off + sbytes)
  local bStartsAt = off / 4; off = align8(off + 4 * nb)
  local bbase = off
  if no < 0 or nn < 0 or ns < 0 or nb < 0 or #s ~= bbase + bbytes then
    giveBack(owner)
    error('e2r-codec: length ' .. #s .. ' ~= ' .. (bbase + bbytes))
  end
  local strCache = {}
  if not ctors then
    types()
    if VEC3 and rawget(_G, 'vec3') ~= nil then
      ctors = {VEC3, FACE, UV}
    else
      ctors = {function(x, y, z) return {x = x, y = y, z = z} end, function(v, n, u) return {v = v, n = n, u = u} end,
        function(u, v) return {u = u, v = v} end}
    end
  else
    ctors = {ctors.vec3, ctors.face, ctors.uv}
  end
  pause = pause or function() end
  local oi, ni, tables, nt, work = opsAt, numsAt, {}, 0, 0
  local opsEnd, numsEnd = opsAt + no, numsAt + nn
  local function fill(t, kind, count, b)
    if b < 0 or b >= nb then error('e2r-codec: blob ' .. b) end
    local at = bbase + I[bStartsAt + b]
    local make = ctors[kind]
    if kind == 2 then
      local i = at / 4
      for k = 1, count do
        t[k] = make(I[i], I[i + 1], I[i + 2]); i = i + 3
        if k % 512 == 0 then pause() end
      end
    elseif kind == 1 then
      local i = at / 8
      for k = 1, count do
        t[k] = make(D[i], D[i + 1], D[i + 2]); i = i + 3
        if k % 512 == 0 then pause() end
      end
    else
      local i = at / 8
      for k = 1, count do
        t[k] = make(D[i], D[i + 1]); i = i + 2
        if k % 512 == 0 then pause() end
      end
    end
    return t
  end
  local value
  value = function()
    local op = I[oi]; oi = oi + 1
    if op == INT then
      local v = I[oi]; oi = oi + 1
      return v
    elseif op == STR then
      local k = I[oi]; oi = oi + 1
      local v = strCache[k]
      if not v then
        local a = k == 0 and 0 or I[sEndsAt + k - 1]
        v = s:sub(sbase + a + 1, sbase + I[sEndsAt + k])
        strCache[k] = v
      end
      return v
    elseif op == NUM then
      local v = D[ni]; ni = ni + 1
      return v
    elseif op == TABLE then
      local n, nk = I[oi], I[oi + 1]; oi = oi + 2
      local t = {}
      nt = nt + 1; tables[nt] = t
      for k = 1, n do t[k] = value() end
      for _ = 1, nk do
        local key = value()
        t[key] = value()
      end
      work = work + n + nk
      if work > 512 then work = 0; pause() end
      return t
    elseif op == REF then
      local id = I[oi]; oi = oi + 1
      return tables[id + 1]
    elseif op == TRUE then return true
    elseif op == FALSE then return false
    elseif op == NIL then return nil
    elseif op == ARR then
      local kind, count, b = I[oi], I[oi + 1], I[oi + 2]; oi = oi + 3
      local t = {}
      nt = nt + 1; tables[nt] = t
      return fill(t, kind, count, b)
    elseif op == ONE then
      local kind, b = I[oi], I[oi + 1]; oi = oi + 2
      return fill({}, kind, 1, b)[1]
    end
    error('e2r-codec: bad op ' .. tostring(op) .. ' at ' .. (oi - opsAt))
  end
  local ok, root = pcall(value)
  giveBack(owner)
  if not ok then error(root, 0) end
  if oi ~= opsEnd or ni ~= numsEnd then error('e2r-codec: trailing structure') end
  return root
end

return M
