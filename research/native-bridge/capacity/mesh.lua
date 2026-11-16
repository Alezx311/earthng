-- Unique geometry capacity: what ProceduralMesh:createMesh costs per vertex for each input form
-- the bridge could hand it (plain tables, tables of vec3 cdata like the generator, raw FFI arrays),
-- what a new mesh object costs on its first drawn frame, and the alternative of geometry written
-- to a file (a COLLADA shape the engine imports itself, then instances).
-- Run after common.lua: python earthng/probe.py --user <user> -f research/native-bridge/capacity/mesh.lua --timeout 600
local ffi = require('ffi')
local cx, cy, cz = CAP.origin()
local out = {forms = {}, objects = {}, files = {}}
local timer = hptimer()
local MAT
for _, name in ipairs({'e2rf_ground', 'e2rf_grass', 'e2rf_asphalt'}) do
  if scenetree.findObject(name) then MAT = name; break end
end
MAT = MAT or 'WarningMaterial'
out.material = MAT
local okVec, VEC3 = pcall(ffi.typeof, 'struct __luaVec3_t')
pcall(ffi.cdef, 'typedef struct { int32_t v, n, u; } e2r_face_t; typedef struct { double u, v; } e2r_uv_t;')
local okFace, FACE = pcall(ffi.typeof, 'e2r_face_t')
local okUv, UV = pcall(ffi.typeof, 'e2r_uv_t')

-- An n x n vertex grid, 2 (n-1)^2 triangles, in one of the input forms.
local function grid(n, form)
  local verts, normals, uvs, faces = {}, {}, {}, {}
  local nv = n * n
  if form == 'ffiarray' then
    verts, normals = ffi.new('struct __luaVec3_t[?]', nv), ffi.new('struct __luaVec3_t[?]', nv)
    uvs, faces = ffi.new('e2r_uv_t[?]', nv), ffi.new('e2r_face_t[?]', 6 * (n - 1) * (n - 1))
  end
  local k = 0
  for j = 0, n - 1 do
    for i = 0, n - 1 do
      local x, y = i * 2, j * 2
      if form == 'tables' then
        verts[k + 1], normals[k + 1], uvs[k + 1] = {x = x, y = y, z = 0}, {x = 0, y = 0, z = 1}, {u = i / 8, v = j / 8}
      elseif form == 'cdata' then
        verts[k + 1], normals[k + 1], uvs[k + 1] = VEC3(x, y, 0), VEC3(0, 0, 1), UV(i / 8, j / 8)
      else
        verts[k].x, verts[k].y, verts[k].z = x, y, 0
        normals[k].z = 1
        uvs[k].u, uvs[k].v = i / 8, j / 8
      end
      k = k + 1
    end
  end
  local f = 0
  local function face(v)
    if form == 'tables' then faces[f + 1] = {v = v, n = v, u = v}
    elseif form == 'cdata' then faces[f + 1] = FACE(v, v, v)
    else faces[f].v, faces[f].n, faces[f].u = v, v, v end
    f = f + 1
  end
  for j = 0, n - 2 do
    for i = 0, n - 2 do
      local a = j * n + i
      face(a); face(a + 1); face(a + n + 1)
      face(a); face(a + n + 1); face(a + n)
    end
  end
  return {verts = verts, normals = normals, uvs = uvs, faces = faces, material = MAT}, nv, f / 3
end

local made = {}
local function mesh(name, m, x, y)
  local obj = createObject('ProceduralMesh')
  obj:registerObject(name)
  obj.canSave = false
  timer:stopAndReset()
  obj:createMesh({{m}})
  local ms = timer:stop()
  obj:setPosition(vec3(x, y, cz + 60))
  made[#made + 1] = obj
  return ms
end

local steps = {CAP.waitQuiet(90, 60), CAP.measure(out, 'base', 120, 30)}
-- input forms at two sizes; each made REPS times
local REPS = 5
for _, n in ipairs({36, 101}) do
  for _, form in ipairs({'tables', 'cdata', 'ffiarray'}) do
    steps[#steps + 1] = function()
      CAP.phase('form-' .. form .. '-' .. n)
      if form == 'cdata' and not (okVec and okFace and okUv) then out.forms[form .. n] = {error = 'no cdata types'}; return true end
      local r = {buildMs = 0, createMs = 0}
      for rep = 1, REPS do
        collectgarbage('collect')
        local kb0 = collectgarbage('count')
        timer:stopAndReset()
        local okB, m, nv, nt = pcall(grid, n, form)
        r.buildMs = r.buildMs + timer:stop()
        if not okB then r.error = 'build: ' .. tostring(m); break end
        r.garbageKb = collectgarbage('count') - kb0
        local okC, ms = pcall(mesh, 'e2rcap_' .. form .. '_' .. n .. '_' .. rep, m, cx + rep * 220, cy - 300)
        if not okC then r.error = 'createMesh: ' .. tostring(ms); break end
        r.createMs = r.createMs + ms
        r.verts, r.tris = nv, nt
      end
      if not r.error then
        r.buildMs, r.createMs = r.buildMs / REPS, r.createMs / REPS
        r.buildUsPerVert = r.buildMs * 1000 / r.verts
        r.createUsPerVert = r.createMs * 1000 / r.verts
        r.createUsPerTri = r.createMs * 1000 / r.tris
      end
      out.forms[form .. n] = r
      return true
    end
    steps[#steps + 1] = CAP.measure(out, 'after-form-' .. form .. '-' .. n, 20, 10)
  end
end

-- new objects on their first drawn frames: OBJ meshes of 2450 triangles in one frame
local OBJ = 24
steps[#steps + 1] = function()
  CAP.phase('objects')
  local m = grid(36, okVec and 'cdata' or 'tables')
  local total = 0
  for k = 1, OBJ do total = total + mesh('e2rcap_obj_' .. k, m, cx - 400 + (k % 6) * 140, cy + 200 + math.floor(k / 6) * 140) end
  out.objects.createMs = total
  out.objects.count = OBJ
  return true
end
steps[#steps + 1] = CAP.measure(out, 'objects-first-frames', 10, 0)
steps[#steps + 1] = CAP.measure(out, 'objects-standing', 120, 30)

-- geometry as a file: a COLLADA grid written by Lua here (the DLL would write it), then a TSStatic
local function dae(n)
  local pos, nor, uv, p = {}, {}, {}, {}
  for j = 0, n - 1 do
    for i = 0, n - 1 do
      pos[#pos + 1] = string.format('%d %d 0', i * 2, j * 2)
      nor[#nor + 1] = '0 0 1'
      uv[#uv + 1] = string.format('%.4f %.4f', i / 8, j / 8)
    end
  end
  local tris = 0
  for j = 0, n - 2 do
    for i = 0, n - 2 do
      local a = j * n + i
      p[#p + 1] = string.format('%d %d %d %d %d %d', a, a + 1, a + n + 1, a, a + n + 1, a + n)
      tris = tris + 2
    end
  end
  local nv = n * n
  return table.concat({
    '<?xml version="1.0" encoding="utf-8"?>',
    '<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">',
    '<asset><unit name="meter" meter="1"/><up_axis>Z_UP</up_axis></asset>',
    '<library_effects><effect id="fx"><profile_COMMON><technique sid="t"><lambert/></technique></profile_COMMON></effect></library_effects>',
    '<library_materials><material id="capmat" name="capmat"><instance_effect url="#fx"/></material></library_materials>',
    '<library_geometries><geometry id="g" name="grid"><mesh>',
    '<source id="p"><float_array id="pa" count="' .. nv * 3 .. '">' .. table.concat(pos, ' ') .. '</float_array>',
    '<technique_common><accessor source="#pa" count="' .. nv .. '" stride="3"><param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source>',
    '<source id="n"><float_array id="na" count="' .. nv * 3 .. '">' .. table.concat(nor, ' ') .. '</float_array>',
    '<technique_common><accessor source="#na" count="' .. nv .. '" stride="3"><param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source>',
    '<source id="u"><float_array id="ua" count="' .. nv * 2 .. '">' .. table.concat(uv, ' ') .. '</float_array>',
    '<technique_common><accessor source="#ua" count="' .. nv .. '" stride="2"><param name="S" type="float"/><param name="T" type="float"/></accessor></technique_common></source>',
    '<vertices id="v"><input semantic="POSITION" source="#p"/></vertices>',
    '<triangles material="capmat" count="' .. tris .. '"><input semantic="VERTEX" source="#v" offset="0"/>',
    '<input semantic="NORMAL" source="#n" offset="0"/><input semantic="TEXCOORD" source="#u" offset="0" set="0"/>',
    '<p>' .. table.concat(p, ' ') .. '</p></triangles></mesh></geometry></library_geometries>',
    '<library_visual_scenes><visual_scene id="s"><node id="grid2" name="grid2"><instance_geometry url="#g">',
    '<bind_material><technique_common><instance_material symbol="capmat" target="#capmat"/></technique_common></bind_material>',
    '</instance_geometry></node></visual_scene></library_visual_scenes><scene><instance_visual_scene url="#s"/></scene></COLLADA>'}, '\n'), nv, tris
end

local statics = {}
for _, n in ipairs({36, 101}) do
  steps[#steps + 1] = function()
    CAP.phase('file-' .. n)
    local text, nv, tris = dae(n)
    local stamp = tostring(os.time()) .. '_' .. n
    local path = 'e2r_probe/capgrid_' .. stamp .. '.dae'
    local f = io.open(path, 'w')
    if not f then out.files[n] = {error = 'cannot write ' .. path}; return true end
    f:write(text); f:close()
    local r = {verts = nv, tris = tris, bytes = #text}
    for rep = 1, 3 do
      timer:stopAndReset()
      local ok, err = pcall(function()
        local o = createObject('TSStatic')
        o:setField('shapeName', 0, '/' .. path)
        o:setField('collisionType', 0, 'None')
        o.canSave = false
        o:setPosRot(cx + rep * 220, cy + 600, cz + 60, 0, 0, 0, 1)
        o:registerObject('')
        statics[#statics + 1] = o
      end)
      r['create' .. rep .. 'Ms'] = timer:stop()
      if not ok then r.error = tostring(err); break end
    end
    out.files[n] = r
    return true
  end
  steps[#steps + 1] = CAP.measure(out, 'after-file-' .. n, 20, 5)
end

steps[#steps + 1] = function()
  CAP.phase('cleanup')
  for _, o in ipairs(made) do pcall(function() o:delete() end) end
  for _, o in ipairs(statics) do pcall(function() o:delete() end) end
  return true
end
steps[#steps + 1] = CAP.measure(out, 'after', 120, 60)
return CAP.run(steps, out)
