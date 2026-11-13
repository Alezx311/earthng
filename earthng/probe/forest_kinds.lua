-- What a Forest change costs the engine by the crowns standing in the kind it touched
-- (python earthng/probe.py --user <out>/user -f earthng/probe/forest_kinds.lua --timeout 240).
--
-- switzerlandNG measured ~0.5 us a crown of each touched shape, and BeamNG.Earth splits a shape's
-- crowns into kinds by spelling its path differently (dir/./name). This builds, round the camera:
--   big:   one kind, BIG crowns;
--   twin:  a second datablock on the same path, SMALL crowns (is the cost per datablock?);
--   alias: the same file as 'dir/./name', SMALL crowns (or per shape resource?);
-- then adds one crown to each kind in turn, ROUNDS times, and records the engine's Ticking and
-- frame time over the next WINDOW frames. The kinds and crowns are removed at the end.
local BIG, SMALL, ROUNDS, WINDOW, SETTLE = 20000, 100, 6, 12, 40
local SHAPE = '/art/shapes/trees/trees_birch/birch_tree_01.dae'

local function exists(p) return FS:fileExists(p) end
if not exists(SHAPE) then
  -- any tree the game ships
  local ok, list = pcall(function() return FS:findFiles('/art/shapes/trees/', '*.dae', -1, true, false) end)
  for _, p in ipairs(ok and list or {}) do
    if p:find('tree', 1, true) then SHAPE = p; break end
  end
end
local dir, file = SHAPE:match('^(.*/)([^/]+)$')
local ALIAS = dir .. './' .. file

local forest = scenetree.findObject('e2rForest')
if not forest then return 'no e2rForest (land first)' end
local data = forest:getData()

local function kind(name, shape)
  local d = scenetree.findObject(name)
  if d then return d end
  local ok
  ok, d = pcall(createObject, 'TSForestItemData')
  if not ok or not d then d = createObject('ForestItemData') end
  for field, value in pairs({shapeFile = shape, collidable = '0'}) do
    if not pcall(function() d:setField(field, '', value) end) then d:setField(field, 0, value) end
  end
  d:registerObject(name)
  return d
end
local kinds = {big = kind('e2rProbeBig', SHAPE), twin = kind('e2rProbeTwin', SHAPE), alias = kind('e2rProbeAlias', ALIAS)}

local cam = core_camera.getPosition()
local m, items = MatrixF(true), {}
local function plant(d, n, r)
  for k = 1, n do
    local a = k * 2.399963
    local d0 = r * math.sqrt(k / n)
    m:setPosition(vec3(cam.x + d0 * math.cos(a), cam.y + d0 * math.sin(a), cam.z - 3))
    local ok, item = pcall(data.createNewItem, data, d, m, 1)
    if ok and item then items[#items + 1] = item end
  end
end

local metrics = {}
local function engine()
  pcall(Engine.Debug.getLastPerformanceMetrics, metrics)
  return metrics.Ticking or -1
end

local plan, step, frame, rows = {}, 0, 0, {}
-- planting takes a frame each so the setup's own cost settles before the rounds
plan[#plan + 1] = function() plant(kinds.big, BIG, 1500) end
plan[#plan + 1] = function() plant(kinds.twin, SMALL, 1500) end
plan[#plan + 1] = function() plant(kinds.alias, SMALL, 1500) end
for r = 1, ROUNDS do
  for _, name in ipairs({'big', 'twin', 'alias'}) do
    plan[#plan + 1] = {name = name, round = r}
  end
end

local current, startFrame, baseline
return P.task(function(dt, ms)
  frame = frame + 1
  local t = engine()
  if current then
    local row = rows[#rows]
    row.ticking[#row.ticking + 1] = t
    row.frames[#row.frames + 1] = ms
    if frame - startFrame >= WINDOW then current = nil end
    return nil
  end
  if startFrame and frame - startFrame < SETTLE then return nil end
  step = step + 1
  local job = plan[step]
  if not job then
    -- the result: per kind, the extra Ticking over the window's quietest frame, mean of rounds
    local out = {shape = SHAPE, big = BIG, small = SMALL}
    for _, name in ipairs({'big', 'twin', 'alias'}) do
      local peaks, sums = {}, {}
      for _, row in ipairs(rows) do
        if row.name == name then
          local lo, hi, sum = 1e9, 0, 0
          for _, v in ipairs(row.ticking) do lo, hi = math.min(lo, v), math.max(hi, v) end
          for _, v in ipairs(row.ticking) do sum = sum + (v - lo) end
          peaks[#peaks + 1] = math.floor((hi - lo) * 100) / 100
          sums[#sums + 1] = math.floor(sum * 100) / 100
        end
      end
      out[name] = {peak = peaks, extra = sums}
    end
    for _, item in ipairs(items) do pcall(data.removeItem, data, item) end
    for _, d in pairs(kinds) do pcall(function() d:delete() end) end
    return out
  end
  startFrame = frame
  if type(job) == 'function' then job(); return nil end
  m:setPosition(vec3(cam.x + 30 + job.round, cam.y + 30, cam.z - 3))
  local ok, item = pcall(data.createNewItem, data, kinds[job.name], m, 1)
  if ok and item then items[#items + 1] = item end
  rows[#rows + 1] = {name = job.name, round = job.round, ticking = {t}, frames = {ms}}
  current = job
  return nil
end)
