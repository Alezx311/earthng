-- Which vertex forms ProceduralMesh:createMesh accepts.
local ffi = require('ffi')
local r = {}
local up = {x = 0, y = 0, z = 1}
local pos = core_camera and core_camera.getPosition() or vec3(0, 0, 0)
local function mk(name, verts, normals)
  local ok, err = pcall(function()
    local obj = createObject('ProceduralMesh')
    obj:registerObject('e2rp_mesh_' .. name)
    obj:setPosition(vec3(pos.x, pos.y, pos.z - 50))
    obj:createMesh({{{verts = verts, normals = normals or {up, up, up}, uvs = {{u = 0, v = 0}, {u = 1, v = 0}, {u = 0, v = 1}},
      faces = {{v = 0, n = 0, u = 0}, {v = 1, n = 1, u = 1}, {v = 2, n = 2, u = 2}}, material = 'e2rf_ground'}}})
    local b = obj:getObjBox()
    local ext = b and (b.maxExtents.x - b.minExtents.x) or -1
    obj:delete()
    return ext
  end)
  r[name] = tostring(ok) .. ' ' .. tostring(err)
end
mk('tables', {{x = 0, y = 0, z = 0}, {x = 3, y = 0, z = 0}, {x = 0, y = 3, z = 0}})
mk('vec3', {vec3(0, 0, 0), vec3(3, 0, 0), vec3(0, 3, 0)}, {vec3(0, 0, 1), vec3(0, 0, 1), vec3(0, 0, 1)})
mk('arrays', {{0, 0, 0}, {3, 0, 0}, {0, 3, 0}})
mk('ffiFloat', ffi.new('float[9]', 0, 0, 0, 3, 0, 0, 0, 3, 0))
-- cost of the table form at scale: 20k triangles
local n = 20000
local verts, normals, uvs, faces = {}, {}, {}, {}
for i = 0, n - 1 do
  local x = (i % 100) * 2; local y = math.floor(i / 100) * 2
  verts[#verts + 1] = {x = x, y = y, z = 0}; verts[#verts + 1] = {x = x + 1, y = y, z = 0}; verts[#verts + 1] = {x = x, y = y + 1, z = 0}
  for k = 1, 3 do normals[#normals + 1] = up; uvs[#uvs + 1] = {u = 0, v = 0} end
  for k = 0, 2 do faces[#faces + 1] = {v = 3 * i + k, n = 3 * i + k, u = 3 * i + k} end
end
local t = hptimer()
local obj = createObject('ProceduralMesh'); obj:registerObject('e2rp_mesh_big'); obj:setPosition(vec3(pos.x, pos.y, pos.z - 60))
obj:createMesh({{{verts = verts, normals = normals, uvs = uvs, faces = faces, material = 'e2rf_ground'}}})
r.big20k_ms = t:stop()
obj:delete()
return r
