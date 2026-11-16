-- Helpers for the capacity probes (research/native-bridge/capacity/run.py runs this first).
-- The probe keeps one environment for every command, so CAP stays for the later scripts.
CAP = CAP or {}
local metrics = {}
CAP.KEYS = {'Lua', 'LuaGC', 'Render', 'RenderShadows', 'RenderMisc', 'OtherRender', 'Ticking', 'FramePresent',
  'Pool', 'PhysicsAndVLUA', 'PreRender', 'PostRender', 'WaitNextFrame'}

function CAP.engine()
  for k in pairs(metrics) do metrics[k] = nil end
  pcall(Engine.Debug.getLastPerformanceMetrics, metrics)
  return metrics
end

-- run.py samples the process memory against this name
function CAP.phase(name)
  CAP.current = name
  local f = io.open('e2r_probe/phase.txt', 'w')
  if f then f:write(name); f:close() end
end

function CAP.window() return {frames = {}, sums = {}} end

function CAP.add(w, ms)
  w.frames[#w.frames + 1] = ms
  local m = CAP.engine()
  for _, k in ipairs(CAP.KEYS) do
    local v = m[k]
    if type(v) == 'number' then w.sums[k] = (w.sums[k] or 0) + v end
  end
end

function CAP.stats(w)
  local n, sorted, total = #w.frames, {}, 0
  for i = 1, n do sorted[i] = w.frames[i]; total = total + w.frames[i] end
  table.sort(sorted)
  local function q(p) return sorted[math.max(1, math.ceil(n * p))] end
  local r = {n = n, mean = n > 0 and total / n or 0, p50 = q(.5), p95 = q(.95), p99 = q(.99), worst = sorted[n]}
  for k, v in pairs(w.sums) do r[k] = v / math.max(1, n) end
  r.heapMb = collectgarbage('count') / 1024
  return r
end

-- The world is quiet: the spawn queue is empty and the far ring is not building.
function CAP.quiet()
  local d = e2r_world and e2r_world.dbg and e2r_world.dbg()
  if not d then return true end
  local q = d.S and d.S.queue
  local far = d.result and d.result.far
  return (not q or #q == 0) and not (far and far.building)
end

-- Where the probes put their models: round the player's car, on its height.
function CAP.origin()
  local veh = be:getPlayerVehicle(0)
  local c = veh and veh:getPosition() or core_camera.getPosition()
  return c.x, c.y, c.z
end

-- A stock shape the game ships, first of the list that exists.
function CAP.shape(list)
  for _, p in ipairs(list) do if FS:fileExists(p) then return p end end
end

CAP.ROCK = CAP.shape({'/levels/east_coast_usa/art/shapes/rocks/eca_rock_small.dae',
  '/levels/east_coast_usa/art/shapes/rocks/eca_rock_small_2.dae'})
CAP.TREE = CAP.shape({'/assets/meshes/foliage/trees_library/oak/tree_oak_sml_a.dae',
  '/levels/east_coast_usa/art/shapes/trees/trees_oak/tree_oak_sml_b.dae'})
CAP.CAR = CAP.shape({'/levels/e2r_world/art/flow/car_sedan_white.dae'})

-- A frame-driven sequence: steps are functions(dt, ms) returning true when done.
-- P.task gets the result table when the last step ends.
function CAP.run(steps, out)
  local i = 1
  return P.task(function(dt, ms)
    local ok, done = pcall(steps[i], dt or 0, ms or 0)
    if not ok then out.error = (out.error or '') .. ' step ' .. i .. ': ' .. tostring(done); done = true end
    if done then
      i = i + 1
      if i > #steps then CAP.phase('idle'); return out end
    end
  end)
end

-- A window of n frames measured after w frames of warm-up; fn(dt, measured) runs each frame,
-- finish() may return fields to add to the window's statistics.
function CAP.measure(out, key, n, w, fn, finish)
  local frame, win = 0, nil
  return function(dt, ms)
    if frame == 0 then CAP.phase(key); win = CAP.window() end
    frame = frame + 1
    if fn then fn(dt, frame > w) end
    if frame > w then CAP.add(win, ms) end
    if frame >= w + n then
      out[key] = CAP.stats(win)
      local extra = finish and finish() or nil
      if type(extra) == 'table' then for k, v in pairs(extra) do out[key][k] = v end end
      frame = 0
      return true
    end
  end
end

-- Wait until the world is quiet (or `limit` seconds), then `settle` more frames.
function CAP.waitQuiet(limit, settle)
  local t, calm = 0, 0
  return function(dt)
    t = t + dt
    calm = CAP.quiet() and calm + 1 or 0
    return calm >= (settle or 60) or t > (limit or 60)
  end
end

return {rock = CAP.ROCK, tree = CAP.TREE, car = CAP.CAR, quiet = CAP.quiet(), heapMb = collectgarbage('count') / 1024}
