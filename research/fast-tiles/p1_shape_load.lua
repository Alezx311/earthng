-- Fast tiles, probe 1: the same geometry through ProceduralMesh:createMesh (Lua tables) and as a
-- compiled shape the mod wrote itself (.cdae) loaded by a TSStatic. For each step: the ms of the
-- call that makes it, and the frame times of the 12 frames after (first draw, shadows, Ticking).
-- Shapes: research/fast-tiles/make_shapes.py <user> --materials <the list P1_MATERIALS below prints>.
local MATERIALS = P1_MATERIALS or {}
local veh = getPlayerVehicle(0)
local at = veh:getPosition()
local dir = veh:getDirectionVector()
local R = {order = {}}

local function grid(n, materials, size)
  -- the tables createMesh takes, one mesh a material, as the generator hands them over
  size = size or 100
  local step, meshes = size / n, {}
  local rows = math.max(1, math.floor(n / #materials))
  for k, material in ipairs(materials) do
    local verts, normals, uvs, faces = {}, {}, {}, {}
    local j0, j1 = (k - 1) * rows, (k == #materials) and n or k * rows
    for j = j0, j1 do
      for i = 0, n do
        local x, y = i * step - size / 2, j * step - size / 2
        local z = 2 * math.sin(x * .2) * math.cos(y * .2)
        verts[#verts + 1] = vec3(x, y, z)
        normals[#normals + 1] = vec3(0, 0, 1)
        uvs[#uvs + 1] = {u = x / 4, v = -y / 4}
      end
    end
    local w = n + 1
    for j = 0, j1 - j0 - 1 do
      for i = 0, n - 1 do
        local a = j * w + i
        local b, c, d = a + 1, a + w, a + w + 1
        for _, v in ipairs({a, b, d, a, d, c}) do faces[#faces + 1] = {v = v, n = v, u = v} end
      end
    end
    meshes[k] = {verts = verts, normals = normals, uvs = uvs, faces = faces, material = material}
  end
  return meshes
end

local slot = 0
local function place()
  slot = slot + 1
  -- a row of squares ahead of the car, each 110 m further, 6 m over its roof
  return vec3(at.x + dir.x * (80 + slot * 110), at.y + dir.y * (80 + slot * 110), at.z + 6)
end

local function proc(n, materials, split)
  local t = hptimer()
  local meshes = grid(n, materials)
  local build = t:stopAndReset()
  local pos = place()
  local count = 0
  if split then
    for _, mesh in ipairs(meshes) do
      local obj = createObject('ProceduralMesh')
      obj:registerObject('')
      obj.canSave = false
      obj:createMesh({{mesh}})
      obj:setPosition(pos)
      count = count + 1
    end
  else
    local obj = createObject('ProceduralMesh')
    obj:registerObject('')
    obj.canSave = false
    obj:createMesh({meshes})
    obj:setPosition(pos)
    count = 1
  end
  return {tables = build, call = t:stop(), objects = count}
end

local function shape(file, collision)
  local t = hptimer()
  local obj = createObject('TSStatic')
  obj:setField('shapeName', 0, file)
  obj:setField('collisionType', 0, collision or 'None')
  obj:setField('decalType', 0, 'None')
  obj.canSave = false
  obj:registerObject('')
  local pos = place()
  obj:setPosRot(pos.x, pos.y, pos.z, 0, 0, 0, 1)
  local ms = t:stop()
  local box = obj:getObjBox()
  return {call = ms, id = obj:getID(), box = box and tostring(box.maxExtents - box.minExtents) or 'none'}
end

local one = {MATERIALS[1]}
local twenty = {}
for k = 1, 20 do twenty[k] = MATERIALS[(k - 1) % #MATERIALS + 1] end

local steps = {
  {'idle', function() return {} end},
  {'proc20k_m1', function() return proc(100, one) end},
  {'cdae20k_m1', function() return shape('/e2r_tiles/g20k_m1.cdae') end},
  {'cdae20k_m1_asDae', function() return shape('/e2r_tiles/g20k_m1_b.dae') end},
  {'cdae20k_m1_again', function() return shape('/e2r_tiles/g20k_m1.cdae') end},
  {'proc50k_20objects', function() return proc(158, twenty, true) end},
  {'proc50k_1object_m20', function() return proc(158, twenty) end},
  {'cdae50k_m20', function() return shape('/e2r_tiles/g50k_m20.cdae') end},
  {'cdae50k_o20', function() return shape('/e2r_tiles/g50k_o20.cdae') end},
  {'cdae200k_m1', function() return shape('/e2r_tiles/g200k_m1.cdae') end},
  {'cdae500k_m1', function() return shape('/e2r_tiles/g500k_m1.cdae') end},
  {'cdae20k_collision', function() return shape('/e2r_tiles/g20k_m1_c.cdae', 'Visible Mesh') end},
  {'reloadCollision', function() local t = hptimer(); be:reloadCollision(); return {call = t:stop()} end},
}
if P1_ONLY then
  local keep = {}
  for _, s in ipairs(steps) do if P1_ONLY[s[1]] then keep[#keep + 1] = s end end
  steps = keep
end

local WAIT = 14
local phase, frame, frames, current = 0, WAIT, {}, nil
return P.task(function(dt, ms)
  frame = frame + 1
  if current then frames[#frames + 1] = math.floor(ms * 10 + .5) / 10 end
  if frame < WAIT then return end
  if current then
    current.frames = frames
    local sum, worst = 0, 0
    for k = 1, #frames do sum, worst = sum + frames[k], math.max(worst, frames[k]) end
    current.sum, current.worst = math.floor(sum), worst
  end
  frames, frame = {}, 0
  phase = phase + 1
  local step = steps[phase]
  if not step then return R end
  local ok, value = pcall(step[2])
  current = ok and value or {error = tostring(value)}
  if current.call then current.call = math.floor(current.call * 100 + .5) / 100 end
  if current.tables then current.tables = math.floor(current.tables * 100 + .5) / 100 end
  R[step[1]] = current
  R.order[#R.order + 1] = step[1]
end)
