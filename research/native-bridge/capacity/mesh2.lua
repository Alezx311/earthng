-- Did createMesh build anything from raw FFI arrays (mesh.lua timed them at ~0 us a vertex)?
-- The same 36 x 36 grid as tables and as FFI arrays; compare the objects' boxes, then delete them.
local ffi = require('ffi')
pcall(ffi.cdef, 'typedef struct { int32_t v, n, u; } e2r_face_t; typedef struct { double u, v; } e2r_uv_t;')
local cx, cy, cz = CAP.origin()
local n = 36
local function grid(form)
  local nv, nf = n * n, 6 * (n - 1) * (n - 1)
  local verts, normals, uvs, faces
  if form == 'ffi' then
    verts, normals = ffi.new('struct __luaVec3_t[?]', nv), ffi.new('struct __luaVec3_t[?]', nv)
    uvs, faces = ffi.new('e2r_uv_t[?]', nv), ffi.new('e2r_face_t[?]', nf)
  else
    verts, normals, uvs, faces = {}, {}, {}, {}
  end
  local k = 0
  for j = 0, n - 1 do for i = 0, n - 1 do
    if form == 'ffi' then
      verts[k].x, verts[k].y = i * 2, j * 2; normals[k].z = 1; uvs[k].u, uvs[k].v = i / 8, j / 8
    else
      verts[k + 1], normals[k + 1], uvs[k + 1] = vec3(i * 2, j * 2, 0), vec3(0, 0, 1), {u = i / 8, v = j / 8}
    end
    k = k + 1
  end end
  local f = 0
  local function face(v)
    if form == 'ffi' then faces[f].v, faces[f].n, faces[f].u = v, v, v else faces[f + 1] = {v = v, n = v, u = v} end
    f = f + 1
  end
  for j = 0, n - 2 do for i = 0, n - 2 do
    local a = j * n + i
    face(a); face(a + 1); face(a + n + 1); face(a); face(a + n + 1); face(a + n)
  end end
  return {verts = verts, normals = normals, uvs = uvs, faces = faces, material = 'e2rf_ground'}
end
local out = {}
for _, form in ipairs({'tables', 'ffi'}) do
  local r = {}
  local ok, err = pcall(function()
    local obj = createObject('ProceduralMesh')
    obj:registerObject('e2rcap_check_' .. form)
    obj.canSave = false
    obj:createMesh({{grid(form)}})
    obj:setPosition(vec3(cx, cy, cz + 60))
    local b = obj:getObjBox()
    r.objBox = {b.minExtents.x, b.minExtents.y, b.minExtents.z, b.maxExtents.x, b.maxExtents.y, b.maxExtents.z}
    local w = obj:getWorldBox()
    r.worldSize = {w.maxExtents.x - w.minExtents.x, w.maxExtents.y - w.minExtents.y}
    obj:delete()
  end)
  r.ok = ok
  if not ok then r.error = tostring(err) end
  out[form] = r
end

-- First drawn frames: is the cost per object or per (object, material) pair? 12 new objects of
-- one material, then 12 new objects of 4 materials each (same triangles in all), frames timed.
local mats = {}
for _, name in ipairs({'e2rf_ground', 'e2rf_grass', 'e2rf_asphalt', 'e2rf_concrete', 'e2rf_paved', 'e2rf_dirt',
  'e2rf_sidewalk', 'e2rf_wall', 'e2rf_roof'}) do
  if scenetree.findObject(name) then mats[#mats + 1] = name end
end
out.materials = mats
local made = {}
local function batchOf(count, nmat, tag, dx)
  local timer, ms = hptimer(), 0
  for k = 1, count do
    local list = {}
    for m = 1, nmat do
      local g = grid('tables')
      g.material = mats[(m - 1) % #mats + 1]
      if nmat > 1 then
        -- each submesh a quarter of the faces, so the triangles match the one-material case
        local q, faces = math.floor(#g.faces / 3 / nmat) * 3, {}
        for i = (m - 1) * q + 1, m * q do faces[#faces + 1] = g.faces[i] end
        g.faces = faces
      end
      list[#list + 1] = g
    end
    local obj = createObject('ProceduralMesh')
    obj:registerObject('e2rcap_pair_' .. tag .. '_' .. k)
    obj.canSave = false
    timer:stopAndReset()
    obj:createMesh({list})
    ms = ms + timer:stop()
    obj:setPosition(vec3(cx + dx + (k % 4) * 90, cy + 300 + math.floor(k / 4) * 90, cz + 40))
    made[#made + 1] = obj
  end
  return ms
end
local steps = {CAP.measure(out, 'base', 60, 10)}
for _, case in ipairs({{12, 1, 'one', -500}, {12, 4, 'four', 200}}) do
  steps[#steps + 1] = function() out['create_' .. case[3]] = batchOf(case[1], case[2], case[3], case[4]); return true end
  steps[#steps + 1] = CAP.measure(out, 'first_' .. case[3], 8, 0)
  steps[#steps + 1] = CAP.measure(out, 'settle_' .. case[3], 40, 20)
end
steps[#steps + 1] = function() for _, o in ipairs(made) do pcall(function() o:delete() end) end; return true end
return CAP.run(steps, out)
