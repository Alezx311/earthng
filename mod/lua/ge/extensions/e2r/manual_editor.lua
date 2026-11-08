-- User-authored World Editor objects: a separate layer from the experimental
-- procedural overrides (manual.lua). Records are geographical, never scene IDs,
-- so a saved object comes back in any landing of any region that covers it.
--
-- rotation is stored in a north-up frame (+y = geographic north at the object):
-- a landing's projection turns its grid a little against north away from its
-- centre, and the editor/loader turn the quaternion by that angle both ways.
local M = {}
M.path = 'settings/earthng-editor-objects.json'
M.schema = 'earthng-editor-objects-v1'
M.prefix = 'earthng_obj_'
local LIMIT = 1000

local function finite(x) return type(x) == 'number' and x == x and x ~= math.huge and x ~= -math.huge end
local function bounded(x, lo, hi) return finite(x) and x >= lo and x <= hi end
local function keys(t, allowed)
  if type(t) ~= 'table' then return false end
  for k in pairs(t) do if not allowed[k] then return false end end
  return true
end
local function array(t, count)
  if type(t) ~= 'table' then return false end
  local n = 0
  for k in pairs(t) do
    if not finite(k) or k % 1 ~= 0 or k < 1 then return false end
    n = n + 1
  end
  if count and n ~= count then return false end
  for i = 1, n do if t[i] == nil then return false end end
  return true, n
end
local function uuid(s)
  return type(s) == 'string' and #s == 36 and s:match('^[0-9a-f]+%-[0-9a-f]+%-[0-9a-f]+%-[0-9a-f]+%-[0-9a-f]+$')
    and s:sub(9, 9) == '-' and s:sub(14, 14) == '-' and s:sub(19, 19) == '-' and s:sub(24, 24) == '-'
end
M.uuid = uuid
local function shape(s)
  if type(s) ~= 'string' or #s > 512 or s:sub(1, 1) ~= '/' or s:find('..', 1, true)
    or s:find('\\', 1, true) or s:find('[%c]') then return false end
  local ext = s:lower():match('%.([%w]+)$')
  return ext == 'dae' or ext == 'dts' or ext == 'cdae'
end

-- One scene name per saved object, whichever tile draws it. The tile spawner and the
-- editor both find the object by it, so it is never drawn twice.
function M.objectName(id) return M.prefix .. (id:gsub('-', '_')) end
function M.idOfName(name)
  if type(name) ~= 'string' or name:sub(1, #M.prefix) ~= M.prefix then return nil end
  local id = name:sub(#M.prefix + 1):gsub('_', '-')
  return uuid(id) and id or nil
end

-- Fully validate before writing or loading; never silently discard a record.
function M.validate(doc)
  if not keys(doc, {schema=true, objects=true}) or doc.schema ~= M.schema then return nil, 'invalid schema' end
  local valid, count = array(doc.objects)
  if not valid or count > LIMIT then return nil, 'invalid objects array or too many objects' end
  local seen, result = {}, {}
  for i = 1, count do
    local p = doc.objects[i]
    if not keys(p, {id=true, lat=true, lon=true, z=true, shape=true, rotation=true, scale=true, radius=true})
      or not uuid(p.id) or seen[p.id] or not bounded(p.lat, -85, 85) or not bounded(p.lon, -180, 180)
      or not bounded(p.z, -10000, 100000) or not shape(p.shape)
      or not array(p.rotation, 4) or not array(p.scale, 3) or not bounded(p.radius, .01, 100) then
      return nil, 'invalid object at index ' .. i
    end
    local norm = 0
    for j = 1, 4 do
      if not finite(p.rotation[j]) then return nil, 'invalid rotation at index ' .. i end
      norm = norm + p.rotation[j] * p.rotation[j]
    end
    if math.abs(norm - 1) > .01 then return nil, 'rotation must be a unit quaternion at index ' .. i end
    for j = 1, 3 do if not bounded(p.scale[j], .01, 100) then return nil, 'invalid scale at index ' .. i end end
    seen[p.id] = true
    result[#result + 1] = p
  end
  return result, nil
end

local function read()
  local ok, exists = pcall(function() return FS:fileExists(M.path) end)
  if not ok then return nil, 'cannot check ' .. M.path end
  if not exists then return {} end
  local readOk, doc = pcall(jsonReadFile, M.path)
  if not readOk or not doc then return nil, 'cannot read ' .. M.path end
  return M.validate(doc)
end
M.read = read

-- changes = {add = {record...}, update = {record...}, remove = {id...}}.
-- Existing data and the complete result are validated before the write. The
-- engine writes a temporary file and renames it; a failed write keeps the old file.
-- An update of a record that is no longer in the file fails the whole save: the
-- file was changed elsewhere and silently re-adding it could resurrect a removal.
function M.apply(changes)
  if type(changes) ~= 'table' then return nil, 'nothing to save' end
  local add, update, remove = changes.add or {}, changes.update or {}, changes.remove or {}
  local okA, nA = array(add)
  local okU, nU = array(update)
  local okR, nR = array(remove)
  if not (okA and okU and okR) then return nil, 'invalid changes' end
  if nA + nU + nR == 0 then return nil, 'nothing to save' end
  local old, err = read()
  if not old then return nil, err end
  local gone, replaced, found = {}, {}, {}
  for _, id in ipairs(remove) do gone[id] = true end
  for _, p in ipairs(update) do
    if type(p) ~= 'table' then return nil, 'invalid changes' end
    replaced[p.id] = p
  end
  local combined = {}
  for _, p in ipairs(old) do
    if replaced[p.id] then
      found[p.id] = true
      if not gone[p.id] then combined[#combined + 1] = replaced[p.id] end
    elseif not gone[p.id] then
      combined[#combined + 1] = p
    end
  end
  for id in pairs(replaced) do
    if not found[id] then return nil, 'object ' .. tostring(id) .. ' is no longer in ' .. M.path end
  end
  for _, p in ipairs(add) do combined[#combined + 1] = p end
  local doc = {schema=M.schema, objects=combined}
  local validated; validated, err = M.validate(doc)
  if not validated then return nil, err end
  local called, saved = pcall(jsonWriteFile, M.path, doc, true, nil, true)
  if not called or saved ~= true then return nil, 'cannot save ' .. M.path end
  return true, nil
end

function M.append(records) return M.apply({add = records}) end

-- Quaternions are {x, y, z, w}. turn(q, a) rotates q about the world z axis by a radians.
function M.turn(q, a)
  local s, c = math.sin(a / 2), math.cos(a / 2)
  local x, y, z, w = q[1], q[2], q[3], q[4]
  local rx, ry, rz, rw = c * x - s * y, c * y + s * x, c * z + s * w, c * w - s * z
  local n = math.sqrt(rx * rx + ry * ry + rz * rz + rw * rw)
  if not finite(n) or n == 0 then return {x, y, z, w} end
  return {rx / n, ry / n, rz / n, rw / n}
end

-- The angle from the scene's +y to geographic north at (lat, lon), counter-clockwise.
function M.northAngle(project, lat, lon)
  local ok, x0, y0 = pcall(project, lat, lon)
  local ok2, x1, y1 = pcall(project, lat + .001, lon)
  if not (ok and ok2 and finite(x0) and finite(y0) and finite(x1) and finite(y1)) then return nil end
  local nx, ny = x1 - x0, y1 - y0
  if nx * nx + ny * ny < 1e-6 then return nil end
  return math.atan2(-nx, ny)
end

function M.load(project)
  local records, err = read()
  if not records then return {}, err end
  local projected, failed = {}, 0
  for _, p in ipairs(records) do
    -- project returns nil for a point this landing's frame does not cover (another
    -- country, another continent): that object simply is not here, it is not an error.
    local ok, x, y = pcall(project, p.lat, p.lon)
    local north = ok and finite(x) and finite(y) and M.northAngle(project, p.lat, p.lon)
    if ok and x == nil then
      -- skipped
    elseif north then
      projected[#projected + 1] = {id=p.id, lat=p.lat, lon=p.lon, x=x, y=y, z=p.z, shape=p.shape,
        rotation=M.turn(p.rotation, north), scale=p.scale, radius=p.radius, editorObject=true}
    else
      failed = failed + 1
    end
  end
  if failed > 0 then return projected, 'coordinate projection failed for ' .. failed .. ' object(s)' end
  return projected, nil
end

local function same(a, b)
  if a.x ~= b.x or a.y ~= b.y or a.z ~= b.z or a.shape ~= b.shape or a.radius ~= b.radius then return false end
  for i = 1, 4 do if a.rotation[i] ~= b.rotation[i] then return false end end
  for i = 1, 3 do if a.scale[i] ~= b.scale[i] then return false end end
  return true
end

-- Keeps the old table (and its rev) for every record that did not change, so tile
-- scenes built before a save still spawn their unchanged objects. nextRev numbers
-- the new versions; the spawner drops an item whose rev is no longer current.
function M.reconcile(old, new, nextRev)
  local byId = {}
  for _, p in ipairs(old or {}) do byId[p.id] = p end
  local out = {}
  for _, p in ipairs(new) do
    local prior = byId[p.id]
    if prior and same(prior, p) then
      out[#out + 1] = prior
    else
      nextRev = nextRev + 1
      p.rev = nextRev
      out[#out + 1] = p
    end
  end
  return out, nextRev
end

-- Circle/rectangle overlap. Unlike the legacy 12m halo this includes larger
-- measured bounds on both sides of a tile boundary.
function M.plan(records, rect)
  local out = {}
  for _, p in ipairs(records or {}) do
    local r = p.radius + .4
    local dx = math.max(rect[1] - p.x, 0, p.x - rect[3])
    local dy = math.max(rect[2] - p.y, 0, p.y - rect[4])
    if dx * dx + dy * dy <= r * r then out[#out + 1] = p end
  end
  return out
end
return M
