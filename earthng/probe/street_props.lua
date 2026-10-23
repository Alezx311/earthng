-- Street props microbenchmark for earthng/probe.py (env persists between commands).
-- Load once:  python earthng/probe.py --user <out>/user -f earthng/probe/street_props.lua
-- Run:        python earthng/props_bench.py <out>/user out.jsonl "method=..."  (or probe.py "return B.run{method='forest', count=3000, radius=250}" --timeout 300
-- method: 'static' (TSStatic, no collision), 'staticColl' (TSStatic, collision mesh),
--         'forest' (items in the level's e2rForest, one ForestItemData per shape)
B = B or {}
B.SHAPES = {
  '/levels/west_coast_usa/art/shapes/objects/garbage_bin_a.dae', '/levels/west_coast_usa/art/shapes/objects/garbage_bin_b.dae',
  '/levels/west_coast_usa/art/shapes/objects/hydrant1.dae', '/levels/west_coast_usa/art/shapes/objects/postbox_blue.dae',
  '/levels/west_coast_usa/art/shapes/objects/planterbox.dae', '/levels/west_coast_usa/art/shapes/objects/bollard_hoop_grey.dae',
  '/art/shapes/objects/bollard_yellow.dae', '/levels/west_coast_usa/art/shapes/objects/sign_stop.dae',
  '/levels/east_coast_usa/art/shapes/clutter/clutter_city_bench_wood.dae',
  '/levels/east_coast_usa/art/shapes/clutter/clutter_city_bike_stand.dae'}

function B.shapes()
  local out = {}
  for _, s in ipairs(B.SHAPES) do if FS:fileExists(s) then out[#out + 1] = s end end
  return out
end

local function metrics()
  local ok, t = pcall(function()
    local m = {}
    Engine.Debug.getLastPerformanceMetrics(m)
    return m
  end)
  return ok and t or nil
end
B.metrics = metrics

-- frames since mark (from the probe's ring): mean, p99, worst, >33, >100
local function stats(list)
  local n, total, worst, o33, o100 = #list, 0, 0, 0, 0
  local sorted = {}
  for k, ms in ipairs(list) do
    total, worst = total + ms, math.max(worst, ms)
    if ms > 33 then o33 = o33 + 1 end
    if ms > 100 then o100 = o100 + 1 end
    sorted[k] = ms
  end
  table.sort(sorted)
  return {n = n, mean = n > 0 and total / n or 0, p50 = sorted[math.max(1, math.ceil(n * .5))] or 0,
    p99 = sorted[math.max(1, math.ceil(n * .99))] or 0, worst = worst, over33 = o33, over100 = o100}
end
B.stats = stats

local function dataFor(shape, collidable)
  B.data = B.data or {}
  local key = shape .. (collidable and '#c' or '')
  if B.data[key] then return B.data[key] end
  local d
  if worldEditorCppApi and worldEditorCppApi.createObject then
    local ok, created = pcall(worldEditorCppApi.createObject, 'ForestItemData')
    if ok then d = created end
  end
  if not d then d = createObject('ForestItemData') end
  local function set(f, v) if not pcall(function() d:setField(f, '', v) end) then d:setField(f, 0, v) end end
  set('shapeFile', shape)
  set('collidable', collidable and '1' or '0')
  set('windScale', '0')
  local name = 'e2rBenchProp' .. tostring(#B.SHAPES + (B.dataCount or 0))
  B.dataCount = (B.dataCount or 0) + 1
  if not pcall(function() d:registerObject(name) end) then d:registerObject('') end
  pcall(function() local g = scenetree.findObject('dataBlockGroup'); if g then g:addObject(d) end end)
  B.data[key] = d
  return d
end

local function forest()
  local f = scenetree.findObject('e2rForest')
  if f then return f end
  f = createObject('Forest')
  f.canSave = false
  f:registerObject('e2rForest')
  scenetree.MissionGroup:addObject(f)
  return f
end

function B.run(cfg)
  local method, count, radius = cfg.method or 'static', cfg.count or 1000, cfg.radius or 250
  local perFrame = cfg.perFrame or 250
  local shapes = B.shapes()
  local veh = be:getPlayerVehicle(0)
  local c = veh and veh:getPosition() or core_camera.getPosition()
  local r = {method = method, count = count, radius = radius, kinds = #shapes}
  local phase, frames, mark = 'settle', {}, 0
  local pts, made, spawnMs, spawnFrames, removeMs = {}, {}, 0, {}, 0
  local seed = cfg.seed or 12345
  local function rnd() seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648 end
  local group
  local metricSamples = {}
  if cfg.view then
    commands.setFreeCamera()
    local from = vec3(c.x + cfg.view[1], c.y + cfg.view[2], c.z + cfg.view[3])
    local q = quatFromDir(c - from, vec3(0, 0, 1))
    core_camera.setPosRot(0, from.x, from.y, from.z, q.x, q.y, q.z, q.w)
  end
  return P.task(function(_, ms)
    if phase == 'settle' then
      mark = mark + 1
      if mark >= (cfg.settle or 120) then phase, mark, frames = 'base', 0, {} end
    elseif phase == 'base' then
      frames[#frames + 1] = ms
      if #frames >= (cfg.frames or 300) then
        r.base, r.baseMetrics = stats(frames), metrics()
        phase, frames = 'points', {}
      end
    elseif phase == 'points' then
      for _ = 1, 400 do
        if #pts >= count then break end
        local x, y = c.x + (rnd() * 2 - 1) * radius, c.y + (rnd() * 2 - 1) * radius
        local ok, hit = pcall(Engine.castRay, vec3(x, y, c.z + 1500), vec3(x, y, c.z - 1500), true, true)
        local z = ok and hit and hit.pt and hit.pt.z or c.z
        pts[#pts + 1] = {x, y, z, rnd() * 6.2832, shapes[(#pts % #shapes) + 1]}
      end
      if #pts >= count then
        phase = 'spawn'
        group = createObject('SimGroup'); group:registerObject('e2rBenchProps')
        if method ~= 'forest' then scenetree.MissionGroup:addObject(group) end
      end
    elseif phase == 'spawn' then
      spawnFrames[#spawnFrames + 1] = ms
      if ms > 50 then r.spikes = r.spikes or {}; if #r.spikes < 6 then r.spikes[#r.spikes + 1] = {phase = 'spawn', at = #made, ms = ms, m = metrics()} end end
      local t = hptimer()
      if method == 'forest' then
        -- one commit per kind and frame, as the generator's queue would do it
        local data = forest():getData()
        local kind = shapes[(#made % #shapes) + 1]
        local d = dataFor(kind, cfg.collidable)
        local m, euler, at = MatrixF(true), vec3(0, 0, 0), vec3(0, 0, 0)
        local placed = 0
        for k, p in ipairs(pts) do
          if p[5] == kind then
            euler.z = p[4]; m:setFromEuler(euler); at.x, at.y, at.z = p[1], p[2], p[3]; m:setPosition(at)
            local ok, item = pcall(data.createNewItem, data, d, m, 1)
            if ok and item then placed = placed + 1; B.items = B.items or {}; B.items[#B.items + 1] = item end
          end
        end
        made[#made + 1] = {kind, placed}
        spawnMs = spawnMs + t:stop()
        if #made >= #shapes then phase, mark, frames = 'tick', 0, {} end
      else
        local start = #made
        for k = start + 1, math.min(count, start + perFrame) do
          local p = pts[k]
          local obj = createObject('TSStatic')
          obj:setField('shapeName', 0, p[5])
          obj:setField('collisionType', 0, method == 'staticColl' and 'Collision Mesh' or 'None')
          obj:setField('decalType', 0, 'None')
          obj.useInstanceRenderData = true
          local h = p[4] / 2
          obj:setPosRot(p[1], p[2], p[3], 0, 0, math.sin(h), math.cos(h))
          obj:registerObject('')
          group:addObject(obj)
          made[#made + 1] = obj:getID()
        end
        spawnMs = spawnMs + t:stop()
        if #made >= count then
          if method == 'staticColl' then
            local tc = hptimer(); be:reloadCollision(); r.reloadCollisionMs = tc:stop()
          end
          phase, mark, frames = 'tick', 0, {}
        end
      end
    elseif phase == 'tick' then
      spawnFrames[#spawnFrames + 1] = ms
      if ms > 50 then r.spikes = r.spikes or {}; if #r.spikes < 6 then r.spikes[#r.spikes + 1] = {phase = 'tick', at = mark, ms = ms, m = metrics()} end end
      mark = mark + 1
      if mark >= (cfg.settle or 120) then phase, frames = 'after', {} end
    elseif phase == 'after' then
      frames[#frames + 1] = ms
      if #frames % 50 == 0 then metricSamples[#metricSamples + 1] = metrics() end
      if #frames >= (cfg.frames or 300) then
        r.after, r.afterMetrics = stats(frames), metricSamples
        r.spawnMs, r.spawnFrames, r.perItemUs = spawnMs, stats(spawnFrames), spawnMs * 1000 / count
        r.made = method == 'forest' and made or #made
        if cfg.keep then return r end
        local t = hptimer()
        if method == 'forest' then
          local data = forest():getData()
          for _, item in ipairs(B.items or {}) do pcall(data.removeItem, data, item) end
          B.items = {}
        else
          group:deleteAllObjects()
        end
        removeMs = t:stop()
        group:delete()
        r.removeMs = removeMs
        return r
      end
    end
  end)
end

function B.clear()
  local g = scenetree.findObject('e2rBenchProps')
  if g then g:deleteAllObjects(); g:delete() end
  local f = scenetree.findObject('e2rForest')
  local data = f and f:getData()
  for _, item in ipairs(B.items or {}) do if data then pcall(data.removeItem, data, item) end end
  B.items = {}
  return true
end

function B.shot(name)
  createScreenshot2({filename = 'screenshots/' .. name, writeJPG = false, superSampling = 1})
  return true
end

return {loaded = true, shapes = B.shapes()}
