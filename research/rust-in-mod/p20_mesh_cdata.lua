-- Does ProceduralMesh:createMesh read faces {v, n, u} and uvs {u, v} from FFI structs, as it reads
-- vec3 vertices (p5_mesh.lua)? The fourth vertex lies 100 m away and no face uses it: the object box
-- is 3 m when the faces are read right, 0 when every index reads as 0, 100 if the box ignores faces.
local ffi = require('ffi')
pcall(ffi.cdef, 'typedef struct { int32_t v, n, u; } e2rp_face_t; typedef struct { float u, v; } e2rp_uv_t; typedef struct { double u, v; } e2rp_uvd_t;')
local FACE, UV, UVD = ffi.typeof('e2rp_face_t'), ffi.typeof('e2rp_uv_t'), ffi.typeof('e2rp_uvd_t')
local r = {}
local pos = core_camera and core_camera.getPosition() or vec3(0, 0, 0)
local verts = {vec3(0, 0, 0), vec3(100, 0, 0), vec3(3, 0, 0), vec3(0, 3, 0)}
local normals = {vec3(0, 0, 1)}
local function mk(name, faces, uvs)
  local ok, err = pcall(function()
    local obj = createObject('ProceduralMesh')
    obj:registerObject('e2rp_cdata_' .. name)
    obj:setPosition(vec3(pos.x, pos.y, pos.z - 50))
    obj:createMesh({{{verts = verts, normals = normals, uvs = uvs, faces = faces, material = 'e2rf_ground'}}})
    local b = obj:getObjBox()
    local ext = b and string.format('%.2f x %.2f', b.maxExtents.x - b.minExtents.x, b.maxExtents.y - b.minExtents.y) or 'nil'
    obj:delete()
    return ext
  end)
  r[name] = tostring(ok) .. ' ' .. tostring(err)
end
local tUV = {{u = 0, v = 0}, {u = 1, v = 0}, {u = 0, v = 1}}
mk('tables', {{v = 0, n = 0, u = 0}, {v = 2, n = 0, u = 1}, {v = 3, n = 0, u = 2}}, tUV)
mk('faceStruct', {FACE(0, 0, 0), FACE(2, 0, 1), FACE(3, 0, 2)}, tUV)
mk('uvStruct', {{v = 0, n = 0, u = 0}, {v = 2, n = 0, u = 1}, {v = 3, n = 0, u = 2}}, {UV(0, 0), UV(1, 0), UV(0, 1)})
mk('uvDouble', {{v = 0, n = 0, u = 0}, {v = 2, n = 0, u = 1}, {v = 3, n = 0, u = 2}}, {UVD(0, 0), UVD(1, 0), UVD(0, 1)})
mk('uvVec3', {{v = 0, n = 0, u = 0}, {v = 2, n = 0, u = 1}, {v = 3, n = 0, u = 2}}, {vec3(0, 0, 0), vec3(1, 0, 0), vec3(0, 1, 0)})
mk('faceArray', {{0, 0, 0}, {2, 0, 1}, {3, 0, 2}}, tUV)
-- what vec3 is here: the ctype the generator constructs
local okT, ct = pcall(ffi.typeof, 'struct __luaVec3_t')
r.vec3ctype = tostring(okT) .. ' ' .. tostring(ct)
r.vec3same = okT and ffi.istype(ct, vec3(1, 2, 3)) or false
r.ctypeNew = okT and tostring(ct(1, 2, 3)) or 'n/a'
r.ctypeLen = okT and (ct(3, 4, 0)):length() or 'n/a'
-- allocation per element, JIT on: tables against structs
local function bytes(fn)
  collectgarbage('collect'); collectgarbage('stop')
  local before = collectgarbage('count')
  local keep = fn()
  local after = collectgarbage('count')
  collectgarbage('restart')
  return math.floor((after - before) * 1024 / #keep + .5)
end
r.bytesVec3Table = bytes(function() local t = {} for i = 1, 100000 do t[i] = {x = i, y = i, z = i} end return t end)
r.bytesVec3 = okT and bytes(function() local t = {} for i = 1, 100000 do t[i] = ct(i, i, i) end return t end) or 'n/a'
r.bytesFaceTable = bytes(function() local t = {} for i = 1, 100000 do t[i] = {v = i, n = i, u = i} end return t end)
r.bytesFace = bytes(function() local t = {} for i = 1, 100000 do t[i] = FACE(i, i, i) end return t end)
r.bytesUVTable = bytes(function() local t = {} for i = 1, 100000 do t[i] = {u = i, v = i} end return t end)
r.bytesUV = bytes(function() local t = {} for i = 1, 100000 do t[i] = UVD(i, i) end return t end)
return r
